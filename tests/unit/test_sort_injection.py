"""SQL injection through the `sort` query parameter (CRITICAL, fixed 2026-09-23).

`GET /v1/billing|claims|containers?sort=…` handed the raw parameter to
`shared.pagination.build_paginated_query`, which interpolates it into ORDER BY
and the cursor comparison. The allowlist check only looked at the segment after
the last ".", so any payload ending in `.created_at` passed as "created_at":

    sort=id,(select pg_sleep(5))::text,b.created_at        -> executed (verified against Postgres: 2.2s vs 0.1s)
    sort=id;UPDATE billing SET total_ngn=1;--.created_at   -> stacked statement

`GET /v1/billing` is open to the customer role. These tests exercise the real
handler -> service -> repository -> query-builder chain with the DB layer wired to
fail loudly, so they prove no SQL is ever sent for a hostile `sort`, at every
endpoint that accepts one — not just that the builder rejects a string.
"""

from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import ValidationError
from shared.pagination import build_paginated_query
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

# Each of these ends in a real allowlisted column so the *old* validator accepted it.
INJECTION_PAYLOADS = [
    "id,(select pg_sleep(5))::text,b.created_at",
    "id;UPDATE billing SET total_ngn=1 WHERE true;--.created_at",
    "b.created_at desc,id",
    "b.created_at,id",
    "id) OR (1=1,b.created_at",
    "b.id,(select case when (1=1) then 1 else 2 end),b.created_at",
    "a.b.created_at",
    "created_at\n",
    "created_at ",
    "b.created_at;--",
    "",
    "-",
    ".created_at",
    "b..created_at",
    "1b.created_at",
    'b."created_at"',
    "b.created_at\x00",
]


class TestBuildPaginatedQueryRejectsInjection:
    _BASE = "SELECT b.* FROM billing b WHERE b.tenant_id = %(tenant_id)s"

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_hostile_sort_field_is_rejected(self, payload):
        with pytest.raises(ValidationError):
            build_paginated_query(self._BASE, None, 20, sort_field=payload)

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_hostile_sort_field_is_rejected_with_a_cursor_too(self, payload):
        cursor = {"sort_value": "2026-01-01T00:00:00", "id": "x"}
        with pytest.raises(ValidationError):
            build_paginated_query(self._BASE, cursor, 20, sort_field=payload)

    @pytest.mark.parametrize("field", ["created_at", "b.created_at", "-created_at", "rn.created_at", "dc.status"])
    def test_legitimate_fields_still_work(self, field):
        query, _ = build_paginated_query(self._BASE, None, 20, sort_field=field)
        assert f"ORDER BY {field.lstrip('-')} " in query

    def test_field_not_in_the_allowlist_is_still_rejected(self):
        with pytest.raises(ValidationError):
            build_paginated_query(self._BASE, None, 20, sort_field="b.tenant_id")

    def test_direction_is_normalised_so_it_cannot_carry_a_payload(self):
        query, _ = build_paginated_query(self._BASE, None, 20, sort_direction="desc; DROP TABLE billing")
        assert "DROP" not in query
        assert "ASC" in query


def _event(path: str, sort: str) -> dict:
    return {
        "requestContext": {
            "requestId": "req-sort-injection",
            "http": {"method": "GET", "path": path},
            "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "headers": {},
        "body": "{}",
        "queryStringParameters": {"sort": sort},
        "pathParameters": {},
    }


def _ctx(role: UserRole) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)


class TestListEndpointsNeverSendHostileSortToTheDatabase:
    """(module, path, role) for every list endpoint that reads `?sort=`."""

    ENDPOINTS = [
        ("billing", "/v1/billing", UserRole.NIGERIA_OFFICE_STAFF),
        ("billing", "/v1/billing", UserRole.CUSTOMER),  # customers may list their own billing
        ("claims", "/v1/claims", UserRole.NIGERIA_OFFICE_STAFF),
        ("claims", "/v1/claims", UserRole.CUSTOMER),
        ("tracking", "/v1/containers", UserRole.TENANT_ADMIN),
    ]

    @pytest.mark.parametrize(("service_name", "path", "role"), ENDPOINTS)
    @pytest.mark.parametrize(
        "payload",
        [
            "id,(select pg_sleep(5))::text,b.created_at",
            "id;UPDATE billing SET total_ngn=1;--.created_at",
        ],
    )
    def test_returns_422_and_runs_no_query(self, service_name, path, role, payload):
        import importlib

        handler = importlib.import_module(f"services.{service_name}.handler")
        repository = importlib.import_module(f"services.{service_name}.repository")

        explode = MagicMock(side_effect=AssertionError("a query was executed for a hostile sort parameter"))
        with (
            patch(f"services.{service_name}.handler.get_tenant_context", return_value=_ctx(role)),
            patch(f"services.{service_name}.handler.record_usage"),
            patch.object(repository, "execute_with_tenant", explode),
            # Customer-role branches resolve the caller's own customer record first.
            patch.object(repository, "get_customer_by_user_id", return_value={"id": "cust-1"}, create=True),
        ):
            response = handler.lambda_handler(_event(path, payload), None)

        assert response["statusCode"] == 422, response
        explode.assert_not_called()
