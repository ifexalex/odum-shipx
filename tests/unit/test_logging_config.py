"""Tests for shared.logging_config structured logging and trace context."""

import json
import logging

import pytest

from shared.logging_config import (
    ContextFilter,
    StructuredFormatter,
    bind_log_context,
    clear_log_context,
)


@pytest.fixture(autouse=True)
def _reset_context():
    """Ensure every test starts and ends with a clean trace context."""
    clear_log_context()
    yield
    clear_log_context()


def _format(record: logging.LogRecord) -> dict:
    """Run a record through the filter + formatter and parse the JSON line."""
    ContextFilter().filter(record)
    return json.loads(StructuredFormatter().format(record))


def _record(msg: str = "hello", **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestStructuredFormatter:
    def test_emits_single_line_json_with_core_fields(self):
        entry = _format(_record("boom"))
        assert entry["message"] == "boom"
        assert entry["level"] == "INFO"
        assert entry["logger"] == "test"
        assert {"timestamp", "service", "environment", "request_id", "tenant_id", "user_id"} <= entry.keys()

    def test_passes_through_extra_fields(self):
        # duration_ms used to be silently dropped by the fixed-schema formatter.
        entry = _format(_record(duration_ms=42.0, event_type="shipment.created"))
        assert entry["duration_ms"] == 42.0
        assert entry["event_type"] == "shipment.created"

    def test_serialises_non_json_values(self):
        from decimal import Decimal

        entry = _format(_record(amount=Decimal("10.50")))
        assert entry["amount"] == "10.50"

    def test_includes_exception_when_present(self):
        try:
            raise ValueError("kaboom")
        except ValueError:
            import sys

            record = _record("failed")
            record.exc_info = sys.exc_info()
        entry = _format(record)
        assert "ValueError: kaboom" in entry["exception"]


class TestContextPropagation:
    def test_bound_context_appears_on_every_record(self):
        bind_log_context(request_id="req-1", tenant_id="t-1", user_id="u-1")
        entry = _format(_record())
        assert entry["request_id"] == "req-1"
        assert entry["tenant_id"] == "t-1"
        assert entry["user_id"] == "u-1"

    def test_partial_bind_refines_without_clearing(self):
        bind_log_context(request_id="req-1")
        bind_log_context(tenant_id="t-1", user_id="u-1")
        entry = _format(_record())
        assert entry["request_id"] == "req-1"
        assert entry["tenant_id"] == "t-1"

    def test_explicit_extra_wins_over_bound_context(self):
        bind_log_context(request_id="req-ctx", tenant_id="t-ctx")
        entry = _format(_record(request_id="req-explicit"))
        assert entry["request_id"] == "req-explicit"
        # Unspecified field still falls back to the bound context.
        assert entry["tenant_id"] == "t-ctx"

    def test_clear_prevents_cross_invocation_leak(self):
        bind_log_context(request_id="req-1", tenant_id="t-1", user_id="u-1")
        clear_log_context()
        entry = _format(_record())
        assert entry["request_id"] is None
        assert entry["tenant_id"] is None
        assert entry["user_id"] is None

    def test_unbound_context_is_null_not_missing(self):
        entry = _format(_record())
        assert entry["request_id"] is None
        assert entry["tenant_id"] is None
        assert entry["user_id"] is None


class TestDiagnosticsGate:
    """Verbose auth/token diagnostics must run in dev/local only — never in
    staging or production, where that detail would outlive the debugging
    session in the log store."""

    def test_enabled_in_dev_and_local(self):
        import os
        from unittest.mock import patch

        from shared.logging_config import diagnostics_enabled

        for env_name in ("dev", "local", "DEV", " local "):
            with patch.dict(os.environ, {"ENVIRONMENT": env_name}, clear=False):
                assert diagnostics_enabled() is True, env_name

    def test_disabled_in_staging_prod_demo_and_unset(self):
        import os
        from unittest.mock import patch

        from shared.logging_config import diagnostics_enabled

        for env_name in ("staging", "prod", "production", "demo", ""):
            with patch.dict(os.environ, {"ENVIRONMENT": env_name}, clear=False):
                assert diagnostics_enabled() is False, env_name
