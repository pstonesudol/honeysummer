"""Dispatch generic GitHub Actions alerts for scheduled staging job failures."""

from __future__ import annotations

import os
import re

import httpx

_ALLOWED_JOBS = {"reconciliation", "invoice-refund-audit"}


def dispatch_job_failure(job: str, environ: dict[str, str] | None = None) -> bool:
    """Dispatch a failure notice without including findings, records, or secrets."""
    if job not in _ALLOWED_JOBS:
        raise ValueError("Unknown scheduled job alert type.")
    settings = dict(os.environ) if environ is None else environ
    token = settings.get("GITHUB_ALERT_TOKEN", "").strip()
    repository = settings.get("GITHUB_REPOSITORY", "pstonesudol/honeysummer").strip()
    ref = settings.get("GITHUB_ALERT_REF", "main").strip()
    if (
        not token
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref)
    ):
        return False
    url = f"https://api.github.com/repos/{repository}/actions/workflows/staging-job-alert.yml/dispatches"
    try:
        response = httpx.post(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": ref, "inputs": {"job": job}},
            timeout=10,
        )
        return response.status_code == 204
    except httpx.HTTPError:
        return False
