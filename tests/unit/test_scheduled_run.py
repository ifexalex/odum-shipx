"""Unit tests for services/scheduled/run.py — the Container App Jobs cron runner.
Patches importlib so no real scheduled job (or DB) runs."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.scheduled import run


class TestRunJob:
    def test_unknown_job_raises(self):
        with pytest.raises(ValueError, match="Unknown job"):
            run.run_job("not-a-job")

    def test_success_returns_zero_and_invokes_handler(self):
        fake_handler = MagicMock()
        fake_module = SimpleNamespace(lambda_handler=fake_handler)
        with patch.object(run.importlib, "import_module", return_value=fake_module) as imp:
            code = run.run_job("release_expiry")
        assert code == 0
        imp.assert_called_once_with("services.scheduled.release_expiry")
        fake_handler.assert_called_once()
        # event carries the job name for traceability
        assert fake_handler.call_args.args[0]["job"] == "release_expiry"

    def test_handler_failure_returns_one(self):
        fake_module = SimpleNamespace(lambda_handler=MagicMock(side_effect=RuntimeError("boom")))
        with patch.object(run.importlib, "import_module", return_value=fake_module):
            code = run.run_job("sla_check")
        assert code == 1

    def test_all_jobs_resolve_to_real_modules(self):
        # Every advertised job name must import and expose lambda_handler.
        for job in run.JOBS:
            module = __import__(f"services.scheduled.{job}", fromlist=["lambda_handler"])
            assert hasattr(module, "lambda_handler"), job


class TestMainArgparse:
    def test_rejects_unknown_job(self):
        with pytest.raises(SystemExit):
            run.main(["--job", "bogus"])
