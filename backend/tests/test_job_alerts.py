"""Tests for redacted scheduled-job failure alerts."""

import httpx

from app.job_alerts import dispatch_job_failure


def test_dispatch_job_failure_uses_fixed_event_and_no_finding_details(monkeypatch):
    """Only a fixed job identifier leaves the runner in the alert request."""
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return httpx.Response(204)

    monkeypatch.setattr("app.job_alerts.httpx.post", post)
    assert dispatch_job_failure(
        "reconciliation",
        {
            "GITHUB_ALERT_TOKEN": "test-token",
            "GITHUB_REPOSITORY": "pstonesudol/honeysummer",
            "GITHUB_ALERT_REF": "main",
        },
    )
    assert calls == [
        (
            "https://api.github.com/repos/pstonesudol/honeysummer/actions/workflows/staging-job-alert.yml/dispatches",
            {
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer test-token",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            {"ref": "main", "inputs": {"job": "reconciliation"}},
            10,
        )
    ]


def test_dispatch_job_failure_fails_closed_without_token():
    """Missing credentials leave Railway's nonzero job status as the fallback."""
    assert not dispatch_job_failure("invoice-refund-audit", {})


def test_dispatch_job_failure_rejects_arbitrary_event_types():
    """Only the known scheduled jobs may be dispatched."""
    try:
        dispatch_job_failure("production-reconcile", {})
    except ValueError as exc:
        assert "Unknown" in str(exc)
    else:
        raise AssertionError("Unknown alert event type was accepted")
