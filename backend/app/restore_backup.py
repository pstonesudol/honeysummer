"""Restore one authenticated backup into explicitly isolated staging resources."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import asyncpg
import boto3
from sqlalchemy.engine import make_url

from .backup import _encryption_key, _postgres_environment, decrypt_file


def _required(environ: dict[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required restore setting {name} is missing.")
    return value


def _restore_target(environ: dict[str, str]) -> tuple[str, str, str, str]:
    """Require a distinctly named, non-production Railway restore target."""
    environment = _required(environ, "RESTORE_TARGET_ENVIRONMENT")
    database_url = _required(environ, "RESTORE_DATABASE_URL")
    url = make_url(database_url)
    if environment != "staging-restore":
        raise ValueError("Restore is restricted to the separately isolated staging-restore environment.")
    if url.get_backend_name() != "postgresql" or not url.host or not url.database or not url.username:
        raise ValueError("RESTORE_DATABASE_URL must identify a PostgreSQL database.")
    if "restore" not in url.host.lower() or "production" in url.host.lower():
        raise ValueError("Restore database host must identify the isolated restore service, not production.")

    public_bucket = _required(environ, "RESTORE_PUBLIC_BUCKET")
    private_bucket = _required(environ, "RESTORE_PRIVATE_BUCKET")
    if "restore" not in public_bucket.lower() or "restore" not in private_bucket.lower():
        raise ValueError("Restore bucket names must clearly identify isolated restore targets.")
    if public_bucket == private_bucket:
        raise ValueError("Public and private restore objects require separate buckets.")
    reserved = {
        environ.get("R2_BUCKET", ""),
        environ.get("R2_PRIVATE_BUCKET", ""),
        environ.get("BACKUP_R2_BUCKET", ""),
    }
    if public_bucket in reserved or private_bucket in reserved:
        raise ValueError("Restore buckets must be separate from source and backup buckets.")
    return database_url, public_bucket, private_bucket, url.host


def expected_confirmation(database_url: str, environment: str) -> str:
    """Return the exact operator phrase required before a restore can write data."""
    url = make_url(database_url)
    return f"RESTORE {environment} {url.host}/{url.database}"


def _download_authenticated(client, bucket: str, key: str, path: Path) -> None:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    try:
        with path.open("xb") as destination:
            while chunk := body.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
    finally:
        body.close()
    expected = response.get("Metadata", {}).get("ciphertext-sha256")
    if not expected or digest.hexdigest() != expected:
        path.unlink(missing_ok=True)
        raise ValueError(f"Encrypted backup checksum verification failed for {key}.")


def _validate_manifest(manifest: object, manifest_key: str) -> tuple[str, list[dict[str, object]]]:
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise ValueError("Backup manifest format is unsupported.")
    prefix = manifest_key.removesuffix("manifest.json.hsbackup")
    if not manifest_key.startswith("snapshots/") or not manifest_key.endswith("/manifest.json.hsbackup"):
        raise ValueError("Manifest key must identify a completed snapshot.")
    database_key = manifest.get("database_backup_key")
    media = manifest.get("media")
    if not isinstance(database_key, str) or not database_key.startswith(prefix):
        raise ValueError("Manifest database object is invalid.")
    if not isinstance(media, list):
        raise ValueError("Manifest media inventory is invalid.")
    seen: set[tuple[str, str]] = set()
    for item in media:
        if not isinstance(item, dict):
            raise ValueError("Manifest media entry is invalid.")
        scope, source_key, backup_key = item.get("scope"), item.get("source_key"), item.get("backup_key")
        size, digest = item.get("size"), item.get("sha256")
        if scope not in {"public", "private"} or not isinstance(source_key, str):
            raise ValueError("Manifest media source is invalid.")
        if not isinstance(backup_key, str) or not backup_key.startswith(f"{prefix}media/{scope}/"):
            raise ValueError("Manifest media object is outside its snapshot prefix.")
        if not isinstance(size, int) or size < 0 or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Manifest media integrity fields are invalid.")
        identity = (scope, source_key)
        if identity in seen:
            raise ValueError("Manifest contains duplicate media keys.")
        seen.add(identity)
    return database_key, media


async def _assert_database_empty(database_url: str) -> None:
    url = make_url(database_url)
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await asyncpg.connect(dsn=dsn)
    try:
        existing = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%') OR EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_namespace "
            "WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public') "
            "AND nspname NOT LIKE 'pg_%')"
        )
        if existing:
            raise ValueError("Restore database is not empty; refusing to write to it.")
    finally:
        await connection.close()


def restore_snapshot(
    manifest_key: str,
    *,
    confirmation: str,
    environ: dict[str, str] | None = None,
    backup_client=None,
    restore_client=None,
    run=None,
    assert_database_empty=None,
) -> dict[str, int]:
    """Authenticate a full snapshot, then restore it only to isolated empty targets."""
    settings = dict(os.environ if environ is None else environ)
    database_url, public_bucket, private_bucket, _ = _restore_target(settings)
    environment = settings["RESTORE_TARGET_ENVIRONMENT"]
    if confirmation != expected_confirmation(database_url, environment):
        raise ValueError("Restore confirmation does not exactly match the isolated target.")

    endpoint = _required(settings, "R2_ENDPOINT_URL")
    backup_bucket = _required(settings, "BACKUP_R2_BUCKET")
    _encryption_key(_required(settings, "BACKUP_ENCRYPTION_KEY"))
    read_key = _required(settings, "RESTORE_BACKUP_R2_ACCESS_KEY_ID")
    read_secret = _required(settings, "RESTORE_BACKUP_R2_SECRET_ACCESS_KEY")
    write_key = _required(settings, "RESTORE_R2_ACCESS_KEY_ID")
    write_secret = _required(settings, "RESTORE_R2_SECRET_ACCESS_KEY")
    if not endpoint.startswith("https://"):
        raise ValueError("R2_ENDPOINT_URL must use HTTPS.")

    reader = backup_client or boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=read_key, aws_secret_access_key=read_secret, region_name="auto"
    )
    writer = restore_client or boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=write_key, aws_secret_access_key=write_secret, region_name="auto"
    )

    with tempfile.TemporaryDirectory(prefix="honeysummer-restore-") as directory:
        root = Path(directory)
        encrypted_manifest = root / "manifest.json.hsbackup"
        plain_manifest = root / "manifest.json"
        _download_authenticated(reader, backup_bucket, manifest_key, encrypted_manifest)
        decrypt_file(encrypted_manifest, plain_manifest, _required(settings, "BACKUP_ENCRYPTION_KEY"))
        manifest = json.loads(plain_manifest.read_text(encoding="utf-8"))
        database_key, media = _validate_manifest(manifest, manifest_key)

        prefix = manifest_key.removesuffix("manifest.json.hsbackup")
        if not database_key.startswith(prefix):
            raise ValueError("Database archive is outside the selected snapshot.")
        database_encrypted = root / "database.dump.hsbackup"
        database_plain = root / "database.dump"
        _download_authenticated(reader, backup_bucket, database_key, database_encrypted)
        decrypt_file(database_encrypted, database_plain, _required(settings, "BACKUP_ENCRYPTION_KEY"))

        restored_media: list[tuple[dict[str, object], Path]] = []
        for index, item in enumerate(media):
            encrypted_path = root / f"media-{index}.hsbackup"
            plain_path = root / f"media-{index}.object"
            _download_authenticated(reader, backup_bucket, str(item["backup_key"]), encrypted_path)
            decrypt_file(encrypted_path, plain_path, _required(settings, "BACKUP_ENCRYPTION_KEY"))
            if plain_path.stat().st_size != item["size"] or _sha256_path(plain_path) != item["sha256"]:
                raise ValueError("Decrypted media integrity check failed; refusing to restore.")
            restored_media.append((item, plain_path))

        command = ["pg_restore", "--list", str(database_plain)]
        (run or subprocess.run)(command, check=True, stdout=subprocess.DEVNULL)
        if assert_database_empty:
            assert_database_empty(database_url)
        else:
            asyncio.run(_assert_database_empty(database_url))

        for bucket in (public_bucket, private_bucket):
            listed = writer.list_objects_v2(Bucket=bucket, MaxKeys=1)
            if listed.get("Contents"):
                raise ValueError("Restore target media buckets must be empty; refusing to overwrite objects.")

        restore_env = _postgres_environment(database_url, settings)
        (run or subprocess.run)(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--dbname",
                make_url(database_url).database,
                str(database_plain),
            ],
            check=True,
            env=restore_env,
        )

        for item, source_path in restored_media:
            bucket = public_bucket if item["scope"] == "public" else private_bucket
            arguments = {
                "Bucket": bucket,
                "Key": item["source_key"],
                "Body": source_path.open("rb"),
                "Metadata": item.get("metadata", {}),
            }
            if item.get("content_type"):
                arguments["ContentType"] = item["content_type"]
            if item.get("cache_control"):
                arguments["CacheControl"] = item["cache_control"]
            try:
                writer.put_object(**arguments)
            finally:
                arguments["Body"].close()

    return {
        "database_archives": 1,
        "public_media": sum(item[0]["scope"] == "public" for item in restored_media),
        "private_media": sum(item[0]["scope"] == "private" for item in restored_media),
    }


def _sha256_path(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    """Run a restore after requiring an exact typed confirmation of the target."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_key", help="Exact encrypted snapshot manifest object key")
    arguments = parser.parse_args()
    target_url = _required(dict(os.environ), "RESTORE_DATABASE_URL")
    target_environment = _required(dict(os.environ), "RESTORE_TARGET_ENVIRONMENT")
    confirmation = expected_confirmation(target_url, target_environment)
    print(f"Restore target: {confirmation}")
    typed = input(f"Type exactly '{confirmation}' to continue: ")
    result = restore_snapshot(arguments.manifest_key, confirmation=typed)
    print(f"Restore complete: {result}")


if __name__ == "__main__":
    main()
