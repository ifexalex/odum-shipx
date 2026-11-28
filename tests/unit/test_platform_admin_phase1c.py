"""Platform admin audit, Phase 1c: the data the console's later pages stand on (decision D7).

``job_run`` records every scheduled run; ``tenant_metrics_daily`` holds one row of counts per tenant per day.
"""

import importlib
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from shared import job_runs
from shared.seats import staff_seat_condition

# ---------------------------------------------------------------------------
# job_run
# ---------------------------------------------------------------------------


class TestCountingAResult:
    def test_failure_keys_count_as_failures_and_the_rest_as_items(self):
        assert job_runs.count_result({"processed": 5, "skipped": 2, "errors": 1, "refused": 1}) == (7, 2)

    def test_non_counts_are_ignored(self):
        assert job_runs.count_result({"ok": True, "note": "x", "rate": 1.5, "sent": 3}) == (3, 0)

    def test_a_result_that_is_not_a_dict_counts_nothing(self):
        assert job_runs.count_result(None) == (0, 0)


class TestTrackedJob:
    def _record(self):
        calls: list[tuple[str, dict]] = []

        def fake(_tenant, sql, params=None):
            calls.append((" ".join(sql.split()), params or {}))
            return {"id": "run-1"}

        return calls, fake

    def test_a_successful_run_is_opened_then_closed_with_its_counts(self):
        calls, fake = self._record()

        @job_runs.tracked_job("demo")
        def handler(event, context):
            return {"sent": 3, "errors": 1}

        with patch("shared.db.execute_write_with_tenant", side_effect=fake):
            assert handler({}, None) == {"sent": 3, "errors": 1}
        (open_sql, open_params), (close_sql, close_params) = calls
        assert open_sql.startswith("INSERT INTO job_run") and open_params["job"] == "demo"
        assert open_params["trigger"] == "schedule"
        assert "UPDATE job_run" in close_sql and "RETURNING id" in close_sql
        assert (close_params["status"], close_params["items"], close_params["failures"]) == ("succeeded", 3, 1)

    def test_a_failed_run_keeps_only_the_error_class_and_reraises(self):
        calls, fake = self._record()

        @job_runs.tracked_job("demo")
        def handler(event, context):
            raise ValueError("customer ada@example.com could not be billed")

        with patch("shared.db.execute_write_with_tenant", side_effect=fake), pytest.raises(ValueError):
            handler({"trigger": "manual"}, None)
        assert calls[0][1]["trigger"] == "manual"
        close = calls[1][1]
        assert (close["status"], close["failures"], close["error"]) == ("failed", 1, "ValueError")
        assert "ada@example.com" not in str(close)

    def test_a_tracking_outage_never_changes_what_the_job_does(self):
        @job_runs.tracked_job("demo")
        def handler(event, context):
            return {"sent": 1}

        with patch("shared.db.execute_write_with_tenant", side_effect=OSError("db down")):
            assert handler({}, None) == {"sent": 1}

    @pytest.mark.parametrize("job", importlib.import_module("services.scheduled.run").JOBS)
    def test_every_scheduled_job_is_tracked_under_its_own_name(self, job):
        module = importlib.import_module(f"services.scheduled.{job}")
        handler = module.lambda_handler
        assert hasattr(handler, "__wrapped__"), f"{job}.lambda_handler is not wrapped by tracked_job"
        names = {cell.cell_contents for cell in handler.__closure__ or () if isinstance(cell.cell_contents, str)}
        assert job in names, f"{job} is recorded as {names}"


# ---------------------------------------------------------------------------
# tenant_metrics_daily
# ---------------------------------------------------------------------------

TENANT = "11111111-1111-1111-1111-111111111111"


class TestTenantMetrics:
    def test_a_day_is_read_in_the_tenants_own_scope_with_utc_bounds(self):
        from services.scheduled import tenant_metrics as tm

        row = {c: None for c in tm._COLUMNS} | {"customers_total": 5, "api_calls": 12.0, "storage_bytes": "2048"}
        with patch.object(tm, "execute_with_tenant", return_value=[row]) as read:
            figures = tm.compute_day(TENANT, date(2026, 11, 27))
        scope, sql, params = read.call_args.args
        assert scope == TENANT
        assert params["start"] == datetime(2026, 11, 27, tzinfo=UTC)
        assert params["end"] == datetime(2026, 11, 28, tzinfo=UTC)
        assert staff_seat_condition("tenant_user") in sql
        assert (figures["customers_total"], figures["api_calls"], figures["storage_bytes"]) == (5, 12, 2048)
        assert figures["sms_failed"] == 0 and figures["last_activity_at"] is None

    def test_a_row_is_an_idempotent_upsert(self):
        from services.scheduled import tenant_metrics as tm

        with patch.object(tm, "execute_write_with_tenant") as write:
            tm.store_day(TENANT, date(2026, 11, 27), {c: 0 for c in tm._COLUMNS})
        sql = " ".join(write.call_args.args[1].split())
        assert "ON CONFLICT (tenant_id, metric_date) DO UPDATE" in sql and "RETURNING tenant_id" in sql

    def test_one_tenants_failure_does_not_stop_the_others(self):
        from services.scheduled import tenant_metrics as tm

        def compute(tenant_id, day):
            if tenant_id == "bad":
                raise RuntimeError("boom")
            return {}

        with (
            patch.object(tm, "tracked_tenants", return_value=["bad", "good"]),
            patch.object(tm, "compute_day", side_effect=compute),
            patch.object(tm, "store_day") as store,
        ):
            result = tm.refresh([date(2026, 11, 27)])
        assert result == {"metric_rows": 1, "metric_errors": 1}
        assert store.call_args.args[0] == "good"

    def test_the_hourly_refresh_covers_yesterday_and_today(self):
        from services.scheduled import tenant_metrics as tm

        with patch.object(tm, "refresh", return_value={}) as refresh:
            tm.refresh_recent(datetime(2026, 11, 28, 9, tzinfo=UTC))
        assert refresh.call_args.args[0] == [date(2026, 11, 27), date(2026, 11, 28)]

    def test_a_backfill_fills_complete_days_oldest_first(self):
        from services.scheduled import tenant_metrics as tm

        with patch.object(tm, "refresh", return_value={}) as refresh:
            tm.backfill(3, datetime(2026, 11, 28, 9, tzinfo=UTC))
        assert refresh.call_args.args[0] == [date(2026, 11, 25), date(2026, 11, 26), date(2026, 11, 27)]

    def test_old_job_runs_are_pruned(self):
        from services.scheduled import tenant_metrics as tm

        with patch.object(tm, "execute_write_with_tenant_many", return_value=[{"id": 1}, {"id": 2}]) as delete:
            assert tm.prune_job_runs() == 2
        assert delete.call_args.args[2] == {"days": 180}

    def test_only_active_and_suspended_tenants_are_tracked(self):
        from services.scheduled import tenant_metrics as tm

        with patch.object(tm, "execute_with_tenant", return_value=[{"id": TENANT}]) as read:
            assert tm.tracked_tenants() == [TENANT]
        assert "status IN ('active', 'suspended')" in read.call_args.args[1]


class TestUsageJobRunsTheMetrics:
    def test_the_hourly_job_refreshes_metrics_and_prunes(self):
        from services.scheduled import usage_aggregation as job

        with (
            patch.object(job, "_get_active_tenants", return_value=[]),
            patch.object(job.tenant_metrics, "refresh_recent", return_value={"metric_rows": 4, "metric_errors": 0}),
            patch.object(job.tenant_metrics, "prune_job_runs", return_value=2),
            patch("shared.job_runs._start", return_value=None),
        ):
            result = job.lambda_handler({}, None)
        assert result == {"groups_aggregated": 0, "errors": 0, "metric_rows": 4, "metric_errors": 0, "job_runs_pruned": 2}


class TestBackfillScript:
    def test_the_day_count_is_bounded(self):
        import scripts.backfill_tenant_metrics as script

        with pytest.raises(SystemExit):
            script.main(["--days", "0"])
        with patch("services.scheduled.tenant_metrics.backfill", return_value={"metric_rows": 3, "metric_errors": 0}) as run:
            assert script.main(["--days", "30"]) == 0
        run.assert_called_once_with(30)
