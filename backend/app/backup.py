"""Create encrypted logical Postgres backups in a private S3-compatible bucket."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from secrets import token_bytes
from uuid import uuid4

import boto3
import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy.engine import make_url

MAGIC = b"HSBACKUP1"
CHUNK_SIZE = 1024 * 1024
_PG_SSL_ENV = {
    "sslmode": "PGSSLMODE",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "connect_timeout": "PGCONNECT_TIMEOUT",
}


def _required(environ: dict[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required backup setting {name} is missing.")
    return value


def _encryption_key(encoded: str) -> bytes:
    try:
        key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be URL-safe base64 for 32 random bytes.") from exc
    if len(key) != 32:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be URL-safe base64 for 32 random bytes.")
    return key


def _postgres_environment(database_url: str, environ: dict[str, str]) -> dict[str, str]:
    """Build libpq environment without putting the database password in argv."""
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or not url.host or not url.database or not url.username:
        raise ValueError("DATABASE_URL must identify a PostgreSQL database with host, database, and username.")

    # pg_dump only receives connection settings and basic runtime paths; it does
    # not inherit R2 credentials or the backup encryption key.
    allowed_environment = ("PATH", "HOME", "LANG", "LC_ALL", "LD_LIBRARY_PATH")
    result = {name: os.environ[name] for name in allowed_environment if name in os.environ}
    result.update(
        {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database,
            "PGUSER": url.username,
        }
    )
    if url.password is not None:
        result["PGPASSWORD"] = url.password
    else:
        result.pop("PGPASSWORD", None)
    for query_name, env_name in _PG_SSL_ENV.items():
        if query_name in url.query:
            result[env_name] = str(url.query[query_name])
    return result


def _encrypt_stream(source, destination: Path, key: bytes) -> tuple[int, str]:
    nonce = token_bytes(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as encrypted:
        encrypted.write(MAGIC + nonce)
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
            ciphertext = encryptor.update(chunk)
            encrypted.write(ciphertext)
        encrypted.write(encryptor.finalize())
        encrypted.write(encryptor.tag)
    return size, digest.hexdigest()


def _encrypt_file(source: Path, destination: Path, key: bytes) -> tuple[int, str]:
    with source.open("rb") as plain:
        return _encrypt_stream(plain, destination, key)


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _upload_encrypted_stream(
    source,
    destination: Path,
    *,
    key: bytes,
    client,
    bucket: str,
    object_key: str,
) -> tuple[int, str]:
    size, plaintext_sha256 = _encrypt_stream(source, destination, key)
    client.upload_file(
        str(destination),
        bucket,
        object_key,
        ExtraArgs={
            "ContentType": "application/octet-stream",
            "Metadata": {"ciphertext-sha256": _sha256_file(destination), "format": "hsbackup1"},
        },
    )
    return size, plaintext_sha256


def decrypt_file(source: Path, destination: Path, encoded_key: str) -> None:
    """Decrypt to a local file; callers must not restore until this returns successfully."""
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing restore file.")
    key = _encryption_key(encoded_key)
    with source.open("rb") as encrypted:
        if encrypted.read(len(MAGIC)) != MAGIC:
            raise ValueError("Backup format is unrecognized.")
        nonce = encrypted.read(12)
        if len(nonce) != 12:
            raise ValueError("Backup is truncated.")
        encrypted.seek(0, os.SEEK_END)
        end = encrypted.tell()
        if end < len(MAGIC) + 12 + 16:
            raise ValueError("Backup is truncated.")
        encrypted.seek(end - 16)
        tag = encrypted.read(16)
        encrypted.seek(len(MAGIC) + 12)
        remaining = end - len(MAGIC) - 12 - 16
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        try:
            with destination.open("wb") as plain:
                while remaining:
                    chunk = encrypted.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("Backup is truncated.")
                    remaining -= len(chunk)
                    plain.write(decryptor.update(chunk))
                plain.write(decryptor.finalize())
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def create_backup(
    environ: dict[str, str] | None = None,
    *,
    s3_client=None,
    source_client=None,
    popen=None,
    now: datetime | None = None,
) -> str:
    """Back up Postgres and public/private R2 objects; return the commit manifest key."""
    settings = dict(os.environ if environ is None else environ)
    database_url = _required(settings, "DATABASE_URL")
    key = _encryption_key(_required(settings, "BACKUP_ENCRYPTION_KEY"))
    endpoint = _required(settings, "R2_ENDPOINT_URL")
    bucket = _required(settings, "BACKUP_R2_BUCKET")
    public_bucket = _required(settings, "R2_BUCKET")
    private_bucket = _required(settings, "R2_PRIVATE_BUCKET")
    source_access_key = _required(settings, "BACKUP_SOURCE_R2_ACCESS_KEY_ID")
    source_secret_key = _required(settings, "BACKUP_SOURCE_R2_SECRET_ACCESS_KEY")
    destination_access_key = _required(settings, "BACKUP_R2_ACCESS_KEY_ID")
    destination_secret_key = _required(settings, "BACKUP_R2_SECRET_ACCESS_KEY")
    if not endpoint.startswith("https://"):
        raise ValueError("R2_ENDPOINT_URL must use HTTPS.")
    if bucket in {public_bucket, private_bucket} or public_bucket == private_bucket:
        raise ValueError("Database backups require a dedicated bucket separate from public and private media.")

    connection_env = _postgres_environment(database_url, settings)
    destination = s3_client or boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=destination_access_key,
        aws_secret_access_key=destination_secret_key,
        region_name="auto",
    )
    source = source_client or boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=source_access_key,
        aws_secret_access_key=source_secret_key,
        region_name="auto",
    )
    timestamp = (now or datetime.now(UTC)).astimezone(UTC)
    run_id = uuid4().hex
    prefix = f"snapshots/{timestamp:%Y/%m/%d}/{run_id}"
    manifest_key = f"{prefix}/manifest.json.hsbackup"
    media_manifest: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="honeysummer-backup-") as directory:
        root = Path(directory)
        database_path = root / "database.hsbackup"
        database_backup_key = f"{prefix}/database.dump.hsbackup"
        command = ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]
        process = (popen or subprocess.Popen)(
            command,
            env=connection_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
        )
        if process.stdout is None:
            process.kill()
            process.wait()
            raise RuntimeError("pg_dump did not provide a backup stream.")
        try:
            dump_size, _ = _encrypt_stream(process.stdout, database_path, key)
            process.stdout.close()
            return_code = process.wait()
        except Exception:
            process.kill()
            process.stdout.close()
            process.wait()
            raise
        if return_code:
            database_path.unlink(missing_ok=True)
            raise subprocess.CalledProcessError(return_code, command)
        if dump_size == 0:
            database_path.unlink(missing_ok=True)
            raise RuntimeError("pg_dump completed without producing a non-empty backup.")
        destination.upload_file(
            str(database_path),
            bucket,
            database_backup_key,
            ExtraArgs={
                "ContentType": "application/octet-stream",
                "Metadata": {"ciphertext-sha256": _sha256_file(database_path), "format": "hsbackup1"},
            },
        )

        object_number = 0
        for scope, source_bucket in (("public", public_bucket), ("private", private_bucket)):
            paginator = source.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=source_bucket):
                for item in page.get("Contents", []):
                    original_key = item["Key"]
                    response = source.get_object(Bucket=source_bucket, Key=original_key)
                    body = response["Body"]
                    encrypted_path = root / f"media-{object_number}.hsbackup"
                    try:
                        copied_bytes, original_digest = _upload_encrypted_stream(
                            body,
                            encrypted_path,
                            key=key,
                            client=destination,
                            bucket=bucket,
                            object_key=f"{prefix}/media/{scope}/{object_number:08d}.object.hsbackup",
                        )
                    finally:
                        body.close()
                    expected_bytes = response.get("ContentLength", item.get("Size"))
                    if expected_bytes is not None and copied_bytes != expected_bytes:
                        raise RuntimeError(f"Media object size mismatch while reading {scope} storage.")
                    backup_key = f"{prefix}/media/{scope}/{object_number:08d}.object.hsbackup"
                    media_manifest.append(
                        {
                            "scope": scope,
                            "source_key": original_key,
                            "backup_key": backup_key,
                            "size": copied_bytes,
                            "sha256": original_digest,
                            "content_type": response.get("ContentType"),
                            "cache_control": response.get("CacheControl"),
                            "metadata": response.get("Metadata", {}),
                        }
                    )
                    encrypted_path.unlink()
                    object_number += 1

        manifest = {
            "format_version": 1,
            "created_at": timestamp.isoformat(),
            "database_backup_key": database_backup_key,
            "media": media_manifest,
        }
        _upload_encrypted_stream(
            BytesIO(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            root / "manifest.json.hsbackup",
            key=key,
            client=destination,
            bucket=bucket,
            object_key=manifest_key,
        )
    return manifest_key


def _dispatch_github_failure(environ: dict[str, str]) -> bool:
    """Dispatch a failing Actions run without sending backup details or secrets."""
    token = environ.get("GITHUB_ALERT_TOKEN", "").strip()
    repository = environ.get("GITHUB_REPOSITORY", "pstonesudol/honeysummer").strip()
    ref = environ.get("GITHUB_ALERT_REF", "main").strip()
    if (
        not token
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref)
    ):
        return False
    url = f"https://api.github.com/repos/{repository}/actions/workflows/staging-backup-alert.yml/dispatches"
    try:
        response = httpx.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": ref, "inputs": {"outcome": "failure"}},
            timeout=10,
        )
        return response.status_code == 204
    except httpx.HTTPError:
        return False


def main() -> None:
    """Run one backup and print only its object key."""
    try:
        object_key = create_backup()
    except Exception:
        if not _dispatch_github_failure(dict(os.environ)):
            print("Backup failed; GitHub alert dispatch was unavailable.", file=sys.stderr)
        raise
    print(f"Backup uploaded: {object_key}")


if __name__ == "__main__":
    main()
