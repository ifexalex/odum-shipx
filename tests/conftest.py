"""Pytest configuration and shared fixtures for all test suites."""
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub aws_xray_sdk before any service handler imports it
# ---------------------------------------------------------------------------
_xray_stub = MagicMock()
sys.modules.setdefault("aws_xray_sdk", _xray_stub)
sys.modules.setdefault("aws_xray_sdk.core", _xray_stub)
sys.modules.setdefault("aws_xray_sdk.ext", _xray_stub)
sys.modules.setdefault("aws_xray_sdk.ext.flask", _xray_stub)
sys.modules.setdefault("aws_xray_sdk.ext.aiohttp", _xray_stub)

from shared.tenant_context import TenantContext, UserRole

# ---------------------------------------------------------------------------
# Tenant ID constants
# ---------------------------------------------------------------------------

TENANT_A_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PLATFORM_TENANT_ID = "PLATFORM"

# ---------------------------------------------------------------------------
# TenantContext fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_a_admin():
    return TenantContext(
        tenant_id=TENANT_A_ID,
        user_id="user-a-admin",
        role=UserRole.TENANT_ADMIN,
    )


@pytest.fixture
def tenant_a_china_staff():
    return TenantContext(
        tenant_id=TENANT_A_ID,
        user_id="user-a-china",
        role=UserRole.CHINA_OFFICE_STAFF,
    )


@pytest.fixture
def tenant_a_nigeria_staff():
    return TenantContext(
        tenant_id=TENANT_A_ID,
        user_id="user-a-nigeria",
        role=UserRole.NIGERIA_OFFICE_STAFF,
    )


@pytest.fixture
def tenant_a_warehouse():
    return TenantContext(
        tenant_id=TENANT_A_ID,
        user_id="user-a-warehouse",
        role=UserRole.WAREHOUSE_ATTENDANT,
    )


@pytest.fixture
def tenant_a_customer():
    return TenantContext(
        tenant_id=TENANT_A_ID,
        user_id="user-a-customer",
        role=UserRole.CUSTOMER,
    )


@pytest.fixture
def tenant_b_admin():
    return TenantContext(
        tenant_id=TENANT_B_ID,
        user_id="user-b-admin",
        role=UserRole.TENANT_ADMIN,
    )


@pytest.fixture
def platform_admin():
    return TenantContext(
        tenant_id=PLATFORM_TENANT_ID,
        user_id="user-platform",
        role=UserRole.PLATFORM_ADMIN,
    )


# ---------------------------------------------------------------------------
# API Gateway event factory
# ---------------------------------------------------------------------------


@pytest.fixture
def api_gateway_event():
    """Factory for API Gateway HTTP API proxy events."""

    def _make_event(
        method: str,
        path: str,
        body=None,
        claims: dict | None = None,
        query_params: dict | None = None,
        path_params: dict | None = None,
        request_id: str = "test-request-id",
    ) -> dict:
        return {
            "requestContext": {
                "requestId": request_id,
                "http": {"method": method.upper(), "path": path},
                "authorizer": {"claims": claims or {}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "body": json.dumps(body) if body else None,
            "queryStringParameters": query_params or {},
            "pathParameters": path_params or {},
        }

    return _make_event


@pytest.fixture
def make_claims():
    """Factory that builds Cognito JWT claims for a given tenant + role."""

    def _make(
        tenant_id: str = TENANT_A_ID,
        user_id: str = "user-test",
        role: str = "nigeria_office_staff",
    ) -> dict:
        return {
            "sub": user_id,
            "custom:tenant_id": tenant_id,
            "cognito:groups": f"{tenant_id}:{role}",
        }

    return _make


# ---------------------------------------------------------------------------
# Database mock helpers
# ---------------------------------------------------------------------------


class MockDb:
    """Configurable mock for shared.db functions.

    Usage in tests:
        mock_db.set_read_result([{"id": "uuid1", ...}])
        mock_db.set_write_result({"id": "uuid1", "status": "draft"})
    """

    def __init__(self):
        self._read_results: list[list[dict]] = []
        self._write_results: list[dict | None] = []

    def set_read_result(self, rows: list[dict]) -> None:
        self._read_results.append(rows)

    def set_write_result(self, row: dict | None) -> None:
        self._write_results.append(row)

    def execute_with_tenant(self, tenant_id, query, params=None) -> list[dict]:
        if self._read_results:
            return self._read_results.pop(0)
        return []

    def execute_write_with_tenant(self, tenant_id, query, params=None) -> dict | None:
        if self._write_results:
            return self._write_results.pop(0)
        return None


@pytest.fixture
def mock_db(monkeypatch):
    """Patch shared.db execute functions for unit tests that avoid real DB."""
    db = MockDb()
    monkeypatch.setattr("shared.db.execute_with_tenant", db.execute_with_tenant)
    monkeypatch.setattr(
        "shared.db.execute_write_with_tenant", db.execute_write_with_tenant
    )
    return db


# ---------------------------------------------------------------------------
# Event / notification mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_publish_event(monkeypatch):
    """Patch shared.events.publish_event to prevent real EventBridge calls."""
    mock = MagicMock(return_value="mock-event-id")
    monkeypatch.setattr("shared.events.publish_event", mock)
    return mock


@pytest.fixture
def mock_enqueue_notification(monkeypatch):
    """Patch shared.notifications.enqueue_notification."""
    mock = MagicMock(return_value=True)
    monkeypatch.setattr("shared.notifications.enqueue_notification", mock)
    return mock


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_tenant_id():
    return TENANT_A_ID


@pytest.fixture
def sample_request_id():
    return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def sample_billing_row():
    return {
        "id": "billing-001",
        "tenant_id": TENANT_A_ID,
        "customer_id": "customer-001",
        "container_id": "container-001",
        "total_ngn": Decimal("166310.00"),
        "amount_paid_ngn": Decimal("0.00"),
        "balance_ngn": Decimal("166310.00"),
        "status": "unpaid",
        "created_at": datetime(2026, 1, 15, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 15, tzinfo=UTC),
    }


@pytest.fixture
def sample_refund_row():
    return {
        "id": "refund-001",
        "tenant_id": TENANT_A_ID,
        "customer_id": "customer-001",
        "billing_id": "billing-001",
        "damage_claim_id": None,
        "refund_type": "overpayment",
        "amount_ngn": Decimal("5000.00"),
        "amount_approved_ngn": None,
        "status": "pending_review",
        "customer_choice": "immediate_refund",
        "reason": "",
        "requested_by": "user-a-nigeria",
        "created_at": datetime(2026, 2, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 2, 1, tzinfo=UTC),
    }


@pytest.fixture
def sample_release_note_row():
    return {
        "id": "note-001",
        "tenant_id": TENANT_A_ID,
        "billing_id": "billing-001",
        "customer_id": "customer-001",
        "container_id": "container-001",
        "reference_number": "ACME-RN-20260301-0001",
        "total_cartons": 10,
        "status": "active",
        "valid_until": None,
        "created_at": datetime(2026, 2, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 2, 1, tzinfo=UTC),
    }
