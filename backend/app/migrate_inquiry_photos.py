"""Dry-run-first migration of legacy local public inquiry photos.

Run python -m app.migrate_inquiry_photos [--apply]. R2/CDN legacy objects
require a separately reviewed bucket migration and cache purge.
"""

import argparse
import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from .db import session_scope
from .media import read_private_image, store_private_image
from .models import Inquiry
from .settings import get_settings


async def migrate(*, apply: bool = False) -> list[str]:
    """Verify private copies before linking them and deleting public originals."""
    settings = get_settings()
    if settings.r2_bucket or settings.r2_private_bucket:
        raise ValueError(
            "Legacy R2 objects need reviewed copy, verification, deletion and CDN purge; local media only."
        )
    findings = []
    migrated_keys = {}
    async with session_scope() as db:
        inquiries = (
            await db.scalars(select(Inquiry).where(Inquiry.photo != "").order_by(Inquiry.id).with_for_update())
        ).all()
        root = settings.media_root.resolve()
        for inquiry in inquiries:
            old_key = inquiry.photo
            if old_key in migrated_keys:
                inquiry.photo = migrated_keys[old_key]
                await db.commit()
                findings.append(f"Inquiry #{inquiry.id}: linked verified shared private copy")
                continue
            if (root / old_key).is_symlink():
                findings.append(f"Inquiry #{inquiry.id}: symbolic link; manual review")
                continue
            source = (root / old_key).resolve()
            if not source.is_relative_to(root) or not old_key.startswith("inquiries/"):
                findings.append(f"Inquiry #{inquiry.id}: unsafe legacy path; manual review")
                continue
            if not source.is_file():
                try:
                    await asyncio.to_thread(read_private_image, old_key)
                except ValueError, OSError:
                    findings.append(f"Inquiry #{inquiry.id}: photo unavailable; manual review")
                else:
                    findings.append(f"Inquiry #{inquiry.id}: already private")
                continue
            if not apply:
                findings.append(f"Inquiry #{inquiry.id}: would migrate and remove public file {old_key}")
                continue
            body = await asyncio.to_thread(source.read_bytes)
            new_key = await asyncio.to_thread(store_private_image, SimpleNamespace(body=body))
            verified, _ = await asyncio.to_thread(read_private_image, new_key)
            if verified != body:
                raise ValueError("Private copy verification failed; public original retained.")
            inquiry.photo = new_key
            await db.commit()  # A failed commit must never delete the customer's only linked copy.
            migrated_keys[old_key] = new_key
            try:
                await asyncio.to_thread(source.unlink)
            except OSError:
                findings.append(
                    f"Inquiry #{inquiry.id}: private copy linked; REMOVE public original {old_key} manually"
                )
            else:
                findings.append(f"Inquiry #{inquiry.id}: migrated; public original removed: {old_key}")
    return findings or ["No inquiry photos require migration."]


def main():
    """Run a report-only migration unless --apply is explicitly supplied."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for finding in asyncio.run(migrate(apply=args.apply)):
        print(finding)


if __name__ == "__main__":
    main()
