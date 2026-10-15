"""Tests for encrypted, isolated logical database backups."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app.backup import (
    _dispatch_github_failure,
    _encrypt_file,
    _postgres_environment,
    create_backup,
    decrypt_file,
    main,
)


def _encoded_key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


def _backup_environment() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql://backup_user:secret@postgres.railway.internal:5432/honeysummer",
        "BACKUP_ENCRYPTION_KEY": _encoded_key(),
        "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "R2_BUCKET": "public-images",
        "R2_PRIVATE_BUCKET": "customer-photos",
        "BACKUP_SOURCE_R2_ACCESS_KEY_ID": "source-access",
        "BACKUP_SOURCE_R2_SECRET_ACCESS_KEY": "source-secret",
        "BACKUP_R2_BUCKET": "honeysummer-staging-backups",
        "BACKUP_R2_ACCESS_KEY_ID": "destination-access",
        "BACKUP_R2_SECRET_ACCESS_KEY": "destination-secret",
        "GITHUB_ALERT_TOKEN": "synthetic-token",
        "GITHUB_REPOSITORY": "pstonesudol/honeysummer",
        "GITHUB_ALERT_REF": "main",
    }


def test_postgres_environment_decodes_credentials_without_argv_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    environment = _postgres_environment(
        "postgresql+asyncpg://backup_user:p%40ss%3Aword@postgres.railway.internal:5433/honeysummer?sslmode=require",
        {
            "BACKUP_ENCRYPTION_KEY": "must-not-be-forwarded",
            "R2_SECRET_ACCESS_KEY": "also-must-not-be-forwarded",
        },
    )

    assert environment["PGHOST"] == "postgres.railway.internal"
    assert environment["PGPORT"] == "5433"
    assert environment["PGDATABASE"] == "honeysummer"
    assert environment["PGUSER"] == "backup_user"
    assert environment["PGPASSWORD"] == "p@ss:word"
    assert environment["PGSSLMODE"] == "require"
    assert "BACKUP_ENCRYPTION_KEY" not in environment
    assert "R2_SECRET_ACCESS_KEY" not in environment


def test_create_backup_dumps_encrypts_and_uploads(tmp_path: Path):
    uploaded: dict[str, bytes] = {}
    upload_metadata: dict[str, dict] = {}
    environment = _backup_environment()

    class FakeS3:
        def upload_file(self, filename, bucket, key, *, ExtraArgs):
            assert bucket == "honeysummer-staging-backups"
            uploaded[key] = Path(filename).read_bytes()
            upload_metadata[key] = ExtraArgs

    class FakePaginator:
        def paginate(self, *, Bucket):
            if Bucket == "public-images":
                yield {"Contents": [{"Key": "gallery/flower.webp", "Size": 12}]}
            elif Bucket == "customer-photos":
                yield {"Contents": [{"Key": "inquiries/private.jpg", "Size": 13}]}
            else:
                raise AssertionError(f"Unexpected source bucket: {Bucket}")

    class FakeSource:
        def get_paginator(self, operation):
            assert operation == "list_objects_v2"
            return FakePaginator()

        def get_object(self, *, Bucket, Key):
            content = b"public-image" if Bucket == "public-images" else b"private-photo"
            return {
                "Body": BytesIO(content),
                "ContentLength": len(content),
                "ContentType": "image/webp" if Bucket == "public-images" else "image/jpeg",
                "CacheControl": "public, max-age=31536000, immutable"
                if Bucket == "public-images"
                else "private, no-store",
                "Metadata": {"fixture": "synthetic"},
            }

    class FakeProcess:
        stdout = BytesIO(b"synthetic pg custom archive")

        def wait(self):
            return 0

        def kill(self):
            raise AssertionError("successful dump should not be killed")

    def fake_popen(command, *, env, stdin, stdout):
        assert command == ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]
        assert "secret" not in " ".join(command)
        assert env["PGPASSWORD"] == "secret"
        assert "BACKUP_ENCRYPTION_KEY" not in env
        return FakeProcess()

    object_key = create_backup(
        environment,
        s3_client=FakeS3(),
        source_client=FakeSource(),
        popen=fake_popen,
        now=datetime(2026, 10, 14, tzinfo=UTC),
    )

    assert object_key.startswith("snapshots/2026/10/14/")
    assert object_key in uploaded
    assert len(uploaded) == 4  # database dump, two media objects, final manifest
    for upload_key, encrypted in uploaded.items():
        assert upload_metadata[upload_key]["Metadata"]["format"] == "hsbackup1"
        assert upload_metadata[upload_key]["Metadata"]["ciphertext-sha256"] == hashlib.sha256(encrypted).hexdigest()

    encrypted_path = tmp_path / "backup.hsbackup"
    database_key = next(key for key in uploaded if key.endswith("/database.dump.hsbackup"))
    encrypted_path.write_bytes(uploaded[database_key])
    restored_path = tmp_path / "restored.dump"
    decrypt_file(encrypted_path, restored_path, _encoded_key())
    assert restored_path.read_bytes() == b"synthetic pg custom archive"

    manifest_encrypted = tmp_path / "manifest.json.hsbackup"
    manifest_encrypted.write_bytes(uploaded[object_key])
    manifest_plain = tmp_path / "manifest.json"
    decrypt_file(manifest_encrypted, manifest_plain, _encoded_key())
    manifest = json.loads(manifest_plain.read_text())
    assert manifest["database_backup_key"] == database_key
    assert {item["scope"] for item in manifest["media"]} == {"public", "private"}
    assert {item["source_key"] for item in manifest["media"]} == {
        "gallery/flower.webp",
        "inquiries/private.jpg",
    }
    for index, item in enumerate(manifest["media"]):
        encrypted_media = tmp_path / "media.hsbackup"
        encrypted_media.write_bytes(uploaded[item["backup_key"]])
        restored_media = tmp_path / f"media-{index}.object"
        decrypt_file(encrypted_media, restored_media, _encoded_key())
        assert hashlib.sha256(restored_media.read_bytes()).hexdigest() == item["sha256"]


def test_decrypt_rejects_unknown_format(tmp_path: Path):
    encrypted = tmp_path / "backup.hsbackup"
    plain = tmp_path / "plain.dump"
    encrypted.write_bytes(b"not-a-backup")
    with pytest.raises(ValueError, match="unrecognized"):
        decrypt_file(encrypted, plain, _encoded_key())


def test_decrypt_rejects_modified_ciphertext_and_removes_partial_plaintext(tmp_path: Path):
    encrypted = tmp_path / "backup.hsbackup"
    plain = tmp_path / "plain.dump"
    source = tmp_path / "source.dump"
    source.write_bytes(b"synthetic archive contents")
    _encrypt_file(source, encrypted, bytes(range(32)))
    encoded = bytearray(encrypted.read_bytes())
    encoded[len(b"HSBACKUP1") + 12 + 2] ^= 0x01
    encrypted.write_bytes(encoded)

    with pytest.raises(InvalidTag):
        decrypt_file(encrypted, plain, _encoded_key())
    assert not plain.exists()


def test_decrypt_rejects_wrong_key_and_never_leaves_unverified_output(tmp_path: Path):
    encrypted = tmp_path / "backup.hsbackup"
    plain = tmp_path / "plain.dump"
    source = tmp_path / "source.dump"
    source.write_bytes(b"synthetic archive contents")

    # Reuse the production encryptor so this test exercises GCM authentication.
    _encrypt_file(source, encrypted, bytes(range(32)))
    wrong_key = base64.urlsafe_b64encode(bytes(reversed(range(32)))).decode("ascii")
    with pytest.raises(InvalidTag):
        decrypt_file(encrypted, plain, wrong_key)
    assert not plain.exists()


def test_backup_requires_separate_private_bucket_before_running():
    environment = _backup_environment()
    del environment["BACKUP_R2_BUCKET"]
    with pytest.raises(ValueError, match="BACKUP_R2_BUCKET"):
        create_backup(environment)


def test_backup_refuses_to_reuse_media_buckets():
    environment = _backup_environment()
    environment["BACKUP_R2_BUCKET"] = "customer-photos"
    with pytest.raises(ValueError, match="dedicated bucket"):
        create_backup(environment)


def test_failed_dump_never_uploads(tmp_path: Path):
    uploaded = False

    class FakeS3:
        def upload_file(self, *args, **kwargs):
            nonlocal uploaded
            uploaded = True

    environment = _backup_environment()

    def failed_dump(*args, **kwargs):
        raise RuntimeError("synthetic pg_dump failure")

    with pytest.raises(RuntimeError, match="pg_dump failure"):
        create_backup(environment, s3_client=FakeS3(), popen=failed_dump)
    assert not uploaded


def test_github_failure_dispatch_uses_only_failure_signal(monkeypatch):
    calls = []

    class Response:
        status_code = 204

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("app.backup.httpx.post", fake_post)
    assert _dispatch_github_failure(
        {
            "GITHUB_ALERT_TOKEN": "synthetic-token",
            "GITHUB_REPOSITORY": "pstonesudol/honeysummer",
            "GITHUB_ALERT_REF": "main",
        }
    )
    assert calls[0][0].endswith("/actions/workflows/staging-backup-alert.yml/dispatches")
    assert calls[0][1]["json"] == {"ref": "main", "inputs": {"outcome": "failure"}}
    assert "synthetic-token" not in repr(calls[0][1]["json"])


def test_backup_failure_dispatches_generic_alert_and_preserves_failure(monkeypatch, capsys):
    def failed_backup():
        raise RuntimeError("sensitive database detail")

    monkeypatch.setattr("app.backup.create_backup", failed_backup)
    monkeypatch.setattr("app.backup._dispatch_github_failure", lambda environ: True)

    with pytest.raises(RuntimeError, match="sensitive database detail"):
        main()
    assert capsys.readouterr().err == ""
