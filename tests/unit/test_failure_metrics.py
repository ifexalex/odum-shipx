"""Failure counters at the catch sites that swallow errors (audit OPS-04)."""

import io
import json
import logging
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared import observability
from shared.logging_config import ContextFilter, StructuredFormatter

TENANT = "11111111-1111-1111-1111-111111111111"


@contextmanager
def _metric_lines():
    """The metric log lines exactly as the production formatter writes them, parsed."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    handler.addFilter(ContextFilter())
    metrics = logging.getLogger("shipx.metrics")
    metrics.addHandler(handler)
    lines: list[dict] = []
    try:
        yield lines
    finally:
        metrics.removeHandler(handler)
        lines.extend(json.loads(line) for line in stream.getvalue().splitlines() if line.strip())


class TestTheMetricLine:
    def test_a_failure_is_one_embedded_metric_format_line(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        with _metric_lines() as lines:
            observability.record_failure("invoice_generation")
        [line] = lines
        directive = line["_aws"]["CloudWatchMetrics"][0]
        assert directive == {
            "Namespace": "ShipX",
            "Dimensions": [["Environment", "Operation"]],
            "Metrics": [{"Name": "Failures", "Unit": "Count"}],
        }
        assert isinstance(line["_aws"]["Timestamp"], int)
        # EMF reads dimension and metric values from top-level keys of the same object.
        assert line["Environment"] == "staging" and line["Operation"] == "invoice_generation" and line["Failures"] == 1

    def test_an_outcome_counts_the_attempt_and_whether_it_failed(self):
        with _metric_lines() as lines:
            observability.record_outcome("notification_send", failed=False)
            observability.record_outcome("notification_send", failed=True)
        assert [(line["Attempts"], line["Failures"]) for line in lines] == [(1, 0), (1, 1)]
        assert [m["Name"] for m in lines[0]["_aws"]["CloudWatchMetrics"][0]["Metrics"]] == ["Attempts", "Failures"]

    def test_it_is_counted_even_when_the_log_level_hides_info(self):
        root = logging.getLogger()
        previous = root.level
        root.setLevel(logging.ERROR)
        try:
            with _metric_lines() as lines:
                observability.record_failure("audit_write")
        finally:
            root.setLevel(previous)
        assert len(lines) == 1

    @pytest.mark.parametrize("operation", ["tenant-1234", "Invoice Generation", "invoice_generation_for_tenant_abc", ""])
    def test_only_the_fixed_operations_become_metrics(self, operation):
        # A name is a billed metric dimension: one built from data would create a metric per value.
        with _metric_lines() as lines:
            observability.record_failure(operation)
        assert lines and all("_aws" not in line for line in lines)

    def test_counting_never_breaks_the_operation_being_counted(self):
        with patch.object(observability._metrics_logger, "info", side_effect=RuntimeError("log sink down")):
            observability.record_failure("audit_write")  # does not raise

    def test_the_line_carries_no_message_or_payload_beyond_the_operation(self):
        with _metric_lines() as lines:
            observability.record_failure("notification_enqueue")
        assert lines[0]["message"] == "metric notification_enqueue"


class TestTheCatchSitesCount:
    def test_a_lost_audit_record(self):
        from shared import audit

        with (
            patch("shared.db.execute_write_with_tenant", side_effect=RuntimeError("db down")),
            patch.object(audit, "record_failure") as counted,
        ):
            audit.log_audit(TENANT, "billing", "b1", "UPDATE", actor_id=None, actor_role="system")
        counted.assert_called_once_with("audit_write")

    def test_a_lost_platform_audit_record_is_counted_and_still_raised(self):
        from shared import platform_audit

        with (
            patch.object(platform_audit, "execute_write_with_tenant", side_effect=RuntimeError("db down")),
            patch.object(platform_audit, "record_failure") as counted,
            pytest.raises(RuntimeError),
        ):
            platform_audit.insert_platform_audit("TENANT_OFFBOARDED", None, TENANT)
        counted.assert_called_once_with("audit_write")

    def test_a_notification_that_could_not_be_queued(self, monkeypatch):
        from shared import notifications

        monkeypatch.setenv("SQS_SMS_QUEUE_URL", "https://queue.test/sms")
        queue = MagicMock()
        queue.send.side_effect = RuntimeError("queue down")
        with (
            patch.object(notifications, "consent_verdict", return_value=None),
            patch.object(notifications, "_get_notification_prefs", return_value={}),
            patch.object(notifications, "get_queue_provider", return_value=queue),
            patch.object(notifications, "record_failure") as counted,
            pytest.raises(RuntimeError),
        ):
            notifications.enqueue_notification(TENANT, "sms", "+2348169760253", "payment_due", {})
        counted.assert_called_once_with("notification_enqueue")

    def test_a_customer_left_unbilled(self):
        from services.billing import service

        with (
            patch.object(service, "handle_payment_due", side_effect=RuntimeError("rate lookup down")),
            patch.object(service, "_notify_unbilled"),
            patch.object(service, "record_failure") as counted,
        ):
            rows = service.generate_container_invoices(TENANT, "c1", "ACME001", [{"id": "cu1", "name": "A"}], request_id="r")
        assert rows[0]["status"] == "failed"
        counted.assert_called_once_with("invoice_generation")

    def test_a_skipped_invoice_is_not_a_failure(self):
        # Missing rates or no CBM are reported to staff in-app; they are not errors to alarm on.
        from services.billing import service

        skipped = service.InvoiceOutcome(status="skipped", reason="NO_CBM", detail="x")
        with (
            patch.object(service, "handle_payment_due", return_value=skipped),
            patch.object(service, "_notify_unbilled"),
            patch.object(service, "record_failure") as counted,
        ):
            service.generate_container_invoices(TENANT, "c1", "ACME001", [{"id": "cu1", "name": "A"}], request_id="r")
        counted.assert_not_called()

    @pytest.mark.parametrize(("function", "failed"), [("log_sent", False), ("log_failed", True)])
    def test_every_send_outcome_feeds_the_failure_rate(self, function, failed):
        from services.notification import service

        with patch.object(service, "record_outcome") as counted:
            if function == "log_sent":
                service.log_sent(TENANT, None, "provider", "id", {})
            else:
                service.log_failed(TENANT, None, "error")
        counted.assert_called_once_with("notification_send", failed=failed)

    @pytest.mark.parametrize(
        ("module", "tenant_step"),
        [
            ("storage_fee", "_process_tenant"),
            ("dispute_escalation", "_process_tenant"),
            ("sla_check", "_process_tenant"),
            ("storage_reminders", "_process_tenant"),
            ("usage_aggregation", "_aggregate_tenant"),
            ("release_expiry", "_process_tenant"),
        ],
    )
    def test_a_failed_tenant_step_in_a_scheduled_job(self, module, tenant_step):
        import importlib

        job = importlib.import_module(f"services.scheduled.{module}")
        with (
            patch.object(job, "_get_active_tenants", return_value=[{"id": TENANT}]),
            patch.object(job, tenant_step, side_effect=RuntimeError("boom")),
            patch.object(job, "record_failure") as counted,
        ):
            result = job.lambda_handler({}, None)
        counted.assert_called_once_with("scheduled_job_step")
        assert result["errors"] == 1


def test_the_failure_count_is_not_used_for_money_amounts():
    """Guard against a misuse seen elsewhere: metric values are counts, never amounts."""
    with _metric_lines() as lines:
        observability.record_failure("invoice_generation")
    assert not any(isinstance(v, Decimal | float) for v in lines[0].values())
