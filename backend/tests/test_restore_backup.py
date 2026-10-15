"""Tests for isolated, integrity-checked snapshot restoration."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest

from app.backup import _encrypt_file
from app.restore_backup import _validate_manifest, expected_confirmation, restore_snapshot


def _key() -> str:
    return base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


def _environment() -> dict[str, str]:
    return {
        "RESTORE_TARGET_ENVIRONMENT": "staging-restore",
        "RESTORE_DATABASE_URL": "postgresql://restore_user:secret@postgres-restore.railway.internal:5432/honeysummer_restore",
        "RESTORE_PUBLIC_BUCKET": "honeysummer-public-restore",
        "RESTORE_PRIVATE_BUCKET": "honeysummer-private-restore",
        "R2_BUCKET": "staging-public",
        "R2_PRIVATE_BUCKET": "staging-private",
        "BACKUP_R2_BUCKET": "honeysummer-staging-backups",
        "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "BACKUP_ENCRYPTION_KEY": _key(),
        "RESTORE_BACKUP_R2_ACCESS_KEY_ID": "read-key",
        "RESTORE_BACKUP_R2_SECRET_ACCESS_KEY": "read-secret",
        "RESTORE_R2_ACCESS_KEY_ID": "write-key",
        "RESTORE_R2_SECRET_ACCESS_KEY": "write-secret",
    }


def test_restore_requires_isolated_target_and_exact_confirmation():
    environment = _environment()
    environment["RESTORE_TARGET_ENVIRONMENT"] = "production"
    with pytest.raises(ValueError, match="restricted"):
        restore_snapshot("snapshots/a/manifest.json.hsbackup", confirmation="", environ=environment)

    environment = _environment()
    environment["RESTORE_DATABASE_URL"] = "postgresql://u:p@production-db.internal:5432/live"
    with pytest.raises(ValueError, match="isolated restore service"):
        restore_snapshot("snapshots/a/manifest.json.hsbackup", confirmation="", environ=environment)

    environment = _environment()
    phrase = expected_confirmation(environment["RESTORE_DATABASE_URL"], "staging-restore")
    with pytest.raises(ValueError, match="confirmation"):
        restore_snapshot("snapshots/a/manifest.json.hsbackup", confirmation=phrase + " ", environ=environment)


def test_manifest_rejects_objects_outside_selected_snapshot():
    manifest = {
        "format_version": 1,
        "database_backup_key": "snapshots/a/database.dump.hsbackup",
        "media": [
            {
                "scope": "private",
                "source_key": "private/photo.jpg",
                "backup_key": "snapshots/b/media/private/00000000.object.hsbackup",
                "size": 12,
                "sha256": "0" * 64,
            }
        ],
    }
    with pytest.raises(ValueError, match="outside its snapshot"):
        _validate_manifest(manifest, "snapshots/a/manifest.json.hsbackup")


def test_restore_authenticates_all_contents_then_writes_only_isolated_targets(tmp_path: Path):
    manifest_key = "snapshots/2026/10/14/run/manifest.json.hsbackup"
    prefix = manifest_key.removesuffix("manifest.json.hsbackup")
    objects: dict[str, bytes] = {}
    metadata: dict[str, dict[str, str]] = {}

    def add_encrypted(key: str, plaintext: bytes):
        source = tmp_path / f"plain-{len(objects)}"
        encrypted = tmp_path / f"encrypted-{len(objects)}"
        source.write_bytes(plaintext)
        _encrypt_file(source, encrypted, bytes(range(32)))
        payload = encrypted.read_bytes()
        objects[key] = payload
        metadata[key] = {"ciphertext-sha256": hashlib.sha256(payload).hexdigest()}

    db_key = f"{prefix}database.dump.hsbackup"
    media_key = f"{prefix}media/private/00000000.object.hsbackup"
    media_bytes = b"synthetic private photo"
    manifest = {
        "format_version": 1,
        "created_at": "2026-10-14T03:30:00+00:00",
        "database_backup_key": db_key,
        "media": [
            {
                "scope": "private",
                "source_key": "customer/photo.jpg",
                "backup_key": media_key,
                "size": len(media_bytes),
                "sha256": hashlib.sha256(media_bytes).hexdigest(),
                "content_type": "image/jpeg",
                "cache_control": "private, no-store",
                "metadata": {"fixture": "synthetic"},
            }
        ],
    }
    add_encrypted(manifest_key, json.dumps(manifest).encode())
    add_encrypted(db_key, b"synthetic pg custom archive")
    add_encrypted(media_key, media_bytes)

    class BackupClient:
        def get_object(self, *, Bucket, Key):
            assert Bucket == "honeysummer-staging-backups"
            return {"Body": BytesIO(objects[Key]), "Metadata": metadata[Key]}

    restored_objects: list[dict] = []

    class RestoreClient:
        def list_objects_v2(self, *, Bucket, MaxKeys):
            assert Bucket in {
                "honeysummer-public-restore",
                "honeysummer-private-restore",
            }
            return {}

        def put_object(self, **kwargs):
            kwargs["Body"] = kwargs["Body"].read()
            restored_objects.append(kwargs)

    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True

    environment = _environment()
    result = restore_snapshot(
        manifest_key,
        confirmation=expected_confirmation(environment["RESTORE_DATABASE_URL"], "staging-restore"),
        environ=environment,
        backup_client=BackupClient(),
        restore_client=RestoreClient(),
        run=fake_run,
        assert_database_empty=lambda _: None,
    )

    assert result == {"database_archives": 1, "public_media": 0, "private_media": 1}
    assert len(commands) == 2
    assert commands[0][:2] == ["pg_restore", "--list"]
    assert "--exit-on-error" in commands[1]
    assert restored_objects[0]["Bucket"] == "honeysummer-private-restore"
    assert restored_objects[0]["Key"] == "customer/photo.jpg"
    assert restored_objects[0]["Body"] == media_bytes
    assert restored_objects[0]["ContentType"] == "image/jpeg"
    assert restored_objects[0]["CacheControl"] == "private, no-store"


def test_restore_rejects_ciphertext_checksum_failure_before_any_restore(tmp_path: Path):
    class BackupClient:
        def get_object(self, **kwargs):
            return {"Body": BytesIO(b"bad ciphertext"), "Metadata": {"ciphertext-sha256": "0" * 64}}

    with pytest.raises(ValueError, match="checksum"):
        restore_snapshot(
            "snapshots/a/manifest.json.hsbackup",
            confirmation=expected_confirmation(_environment()["RESTORE_DATABASE_URL"], "staging-restore"),
            environ=_environment(),
            backup_client=BackupClient(),
            restore_client=object(),
        )
