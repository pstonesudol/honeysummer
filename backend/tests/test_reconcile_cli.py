"""The scheduled job must communicate findings to its external monitor."""

from unittest.mock import AsyncMock, patch

import pytest

from app.reconcile import main


def test_clean_reconciliation_exits_successfully(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["app.reconcile"])
    with patch("app.reconcile.reconcile", new_callable=AsyncMock, return_value=[]):
        main()
    assert "reconciled" in capsys.readouterr().out


def test_findings_fail_the_job(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["app.reconcile", "--apply"])
    with patch("app.reconcile.reconcile", new_callable=AsyncMock, return_value=["Order #1: manual review"]):
        with pytest.raises(SystemExit) as error:
            main()
    assert error.value.code == 1
    assert "manual review" in capsys.readouterr().out
