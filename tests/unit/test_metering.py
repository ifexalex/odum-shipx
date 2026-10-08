"""Regression test for shared/metering.py's record_usage() upsert.

Found live via e2e testing: a plain INSERT hit usage_record's own
uq_usage_tenant_metric_period unique constraint on every write past the
first for a given (tenant, metric, day) — not a rare race, the guaranteed
outcome from the second api_calls record onward each day. Migration 010's
own docstring documents the ON CONFLICT upsert this was always meant to use;
record_usage() never actually used it.
"""
from unittest.mock import patch

from shared.metering import record_usage


class TestRecordUsageUpsert:
    def test_insert_is_an_upsert_on_the_documented_constraint(self) -> None:
        """migration 010 added uq_usage_tenant_metric_period specifically so
        this write could increment an existing day's total instead of
        failing outright on the second call — assert the actual SQL does
        that, not just that some write happens."""
        with patch("shared.metering.execute_write_with_tenant") as mock_write, patch(
            "shared.metering.publish_event",
        ):
            record_usage("tenant-1", "api_calls", value=1.0, request_id="req-1")

        query = mock_write.call_args.args[1]
        assert "ON CONFLICT (tenant_id, metric_type, period_start)" in query
        assert "DO UPDATE SET value = usage_record.value + EXCLUDED.value" in query

    def test_a_write_failure_is_swallowed_not_raised(self) -> None:
        """record_usage is fire-and-forget by design — a DB error here must
        never break the request that triggered it."""
        with patch(
            "shared.metering.execute_write_with_tenant", side_effect=RuntimeError("boom"),
        ), patch("shared.metering.publish_event"):
            record_usage("tenant-1", "api_calls")  # must not raise

    def test_unknown_metric_type_is_skipped_without_a_db_call(self) -> None:
        with patch("shared.metering.execute_write_with_tenant") as mock_write:
            record_usage("tenant-1", "not_a_real_metric")

        mock_write.assert_not_called()

    def test_platform_sentinel_tenant_id_is_skipped_without_a_db_call(self) -> None:
        """usage_record.tenant_id is a UUID column; the platform-admin
        sentinel is the literal string "PLATFORM" — every write for it
        failed with InvalidTextRepresentation, on every platform-admin
        request, for a tenant that has no tier limits to meter anyway."""
        with patch("shared.metering.execute_write_with_tenant") as mock_write:
            record_usage("PLATFORM", "api_calls")

        mock_write.assert_not_called()
