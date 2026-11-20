"""The reports page's Export: billing by container for the report's period, every container.

The page lists the 200 containers billed most; the export is what "every container processed this period" promises.
It shares the page's query (one definition of the figures), is refused rather than cut short when too large, and is
the tenant admin's alone, like the invoice-list export.
"""

import csv
import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from services.billing import repository as billing_repo
from services.excel import handler, service
from services.excel.models import ReportExportQuery
from shared.exceptions import BusinessRuleViolationError
from shared.http_routing import resolve_service
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _row(number: str = "MSCU1234567", **kw: object) -> dict[str, object]:
    return {
        "container_number": number,
        "customers": 3,
        "cbm": Decimal("41.250"),
        "billed": Decimal("2500000.00"),
        "collected": Decimal("1000000.00"),
        "outstanding": Decimal("1500000.00"),
        "cbm_rate_usd": Decimal("120.00"),
        "dollar_rate": Decimal("1550.00"),
        **kw,
    }


# ---------------------------------------------------------------------------
# The shared query
# ---------------------------------------------------------------------------


class TestContainerBillingQuery:
    def test_the_period_and_limit_are_bound_parameters(self):
        with patch.object(billing_repo, "execute_with_tenant", return_value=[]) as execute:
            billing_repo.get_container_billing(TENANT, "2026-01-01", "'; DROP TABLE billing; --", limit=7)
        sql, params = execute.call_args.args[1], execute.call_args.args[2]
        assert params == {
            "tenant_id": TENANT,
            "limit": 7,
            "created_after": "2026-01-01",
            "created_before": "'; DROP TABLE billing; --",
        }
        assert "DROP TABLE" not in sql
        assert "b.created_at >= %(created_after)s" in sql and "b.created_at <= %(created_before)s" in sql
        assert "LIMIT %(limit)s" in sql

    def test_no_period_is_every_billing_of_the_tenant(self):
        with patch.object(billing_repo, "execute_with_tenant", return_value=[]) as execute:
            billing_repo.get_container_billing(TENANT, None, None, limit=1)
        assert execute.call_args.args[2] == {"tenant_id": TENANT, "limit": 1}
        assert "created_at" not in execute.call_args.args[1]

    def test_the_report_page_lists_the_top_200_from_the_same_query(self):
        with (
            patch.object(billing_repo, "get_container_billing", return_value=[_row()]) as shared,
            patch.object(billing_repo, "execute_with_tenant", return_value=[]),
        ):
            report = billing_repo.get_tenant_report(TENANT, "2026-01-01", None)
        shared.assert_called_once_with(TENANT, "2026-01-01", None, limit=billing_repo.REPORT_CONTAINER_ROWS)
        assert billing_repo.REPORT_CONTAINER_ROWS == 200
        assert report["container_billing"][0]["billed"] == "2500000.00"


# ---------------------------------------------------------------------------
# The query string
# ---------------------------------------------------------------------------


class TestReportExportQuery:
    def test_only_the_bounds_that_were_set_are_filters(self):
        assert ReportExportQuery(created_after="2026-01-01").filters() == {"created_after": "2026-01-01"}
        assert ReportExportQuery().filters() == {}
        assert ReportExportQuery().format == "xlsx"

    @pytest.mark.parametrize("bad", [{"format": "pdf"}, {"created_after": "2026-99-99"}, {"created_before": "soon"}])
    def test_bad_values_are_refused(self, bad):
        with pytest.raises(PydanticValidationError):
            ReportExportQuery(**bad)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


@pytest.fixture
def stored():
    """Replace S3, the tenant lookup and the audit log; yield what was stored and audited."""
    seen: dict = {}

    def upload(tenant_id, filename, buf, fmt="xlsx"):
        seen.update(filename=filename, content=buf.getvalue(), fmt=fmt)
        return {"filename": filename, "download_url": "https://example.test/f", "format": fmt}

    with (
        patch.object(service.repo, "get_tenant_display_name", return_value="Acme Shipping Ltd"),
        patch.object(service, "_upload_and_presign", side_effect=upload),
        patch.object(service, "log_audit") as audit,
    ):
        seen["audit"] = audit
        yield seen


def _export(rows, fmt="xlsx", filters=None):
    with patch.object(service.billing_repo, "get_container_billing", return_value=rows) as query:
        result = service.export_report_container_billing(TENANT, filters or {}, fmt=fmt, actor_id="u1", actor_role="tenant_admin")
    return result, query


class TestService:
    def test_it_asks_for_one_more_row_than_it_may_export(self, stored):
        _, query = _export([_row()], filters={"created_after": "2026-01-01"})
        query.assert_called_once_with(TENANT, "2026-01-01", None, limit=service.EXPORT_ROW_LIMIT + 1)

    def test_csv_has_the_pages_columns_and_figures(self, stored):
        result, _ = _export([_row(), _row("TGHU7654321")], fmt="csv")
        assert result["row_count"] == 2
        assert stored["filename"].startswith("Acme_Shipping_Ltd_billing_by_container_") and stored["fmt"] == "csv"
        rows = list(csv.reader(io.StringIO(stored["content"].decode("utf-8-sig"))))
        assert rows[0] == [
            "Container",
            "Customers",
            "Volume (CBM)",
            "Average CBM Rate (USD)",
            "Average Dollar Rate (NGN per USD)",
            "Billed (NGN)",
            "Collected (NGN)",
            "Outstanding (NGN)",
        ]
        assert rows[1] == ["MSCU1234567", "3", "41.250", "120.00", "1550.00", "2500000.00", "1000000.00", "1500000.00"]

    def test_xlsx_is_a_workbook(self, stored):
        _export([_row()])
        assert stored["filename"].endswith(".xlsx") and stored["content"][:2] == b"PK"

    def test_more_than_the_limit_is_refused_not_cut_short(self, stored):
        with pytest.raises(BusinessRuleViolationError) as caught:
            _export([_row(str(n)) for n in range(service.EXPORT_ROW_LIMIT + 1)])
        assert caught.value.rule_id == "EXPORT_TOO_LARGE"
        assert caught.value.message == "More than 10,000 containers match. Narrow the period and export again."
        assert "content" not in stored
        stored["audit"].assert_not_called()

    def test_exactly_the_limit_is_exported(self, stored):
        result, _ = _export([_row(str(n)) for n in range(service.EXPORT_ROW_LIMIT)], fmt="csv")
        assert result["row_count"] == service.EXPORT_ROW_LIMIT

    def test_the_export_is_audited_with_its_period(self, stored):
        _export([_row()], filters={"created_after": "2026-01-01", "created_before": "2026-01-31"})
        kwargs = stored["audit"].call_args.kwargs
        assert (kwargs["entity_type"], kwargs["action"], kwargs["actor_id"]) == ("billing", "EXPORT", "u1")
        assert kwargs["after_state"]["filters"] == {"created_after": "2026-01-01", "created_before": "2026-01-31"}
        assert kwargs["after_state"]["row_count"] == 1


# ---------------------------------------------------------------------------
# The handler and routing
# ---------------------------------------------------------------------------

PATH = "/v1/billing/report/export"


def _call(role, **query):
    ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=role)
    event = {
        "requestContext": {"requestId": "r1", "http": {"method": "GET", "path": PATH}},
        "queryStringParameters": query or None,
        "headers": {},
    }
    with (
        patch.object(handler, "get_tenant_context", return_value=ctx),
        patch.object(handler, "record_usage"),
        patch.object(service, "export_report_container_billing", return_value={"download_url": "u"}) as export,
        patch.object(service, "export_billing") as single,
    ):
        response = handler.lambda_handler(event, None)
    return response, export, single


class TestHandler:
    def test_the_tenant_admin_exports_the_period_in_the_chosen_format(self):
        response, export, single = _call(UserRole.TENANT_ADMIN, created_after="2026-01-01", format="csv")
        assert response["statusCode"] == 200 and not single.called
        assert export.call_args.args == (TENANT, {"created_after": "2026-01-01"})
        assert export.call_args.kwargs == {"fmt": "csv", "actor_id": "user-1", "actor_role": "tenant_admin"}

    @pytest.mark.parametrize(
        "role",
        [
            UserRole.NIGERIA_OFFICE_STAFF,
            UserRole.CHINA_OFFICE_STAFF,
            UserRole.WAREHOUSE_ATTENDANT,
            UserRole.CUSTOMER,
            UserRole.PLATFORM_ADMIN,
        ],
    )
    def test_everyone_else_is_refused(self, role):
        response, export, single = _call(role)
        assert response["statusCode"] == 403 and not export.called and not single.called

    @pytest.mark.parametrize("query", [{"format": "pdf"}, {"created_before": "2026-13-01"}])
    def test_bad_input_is_a_422_and_nothing_is_exported(self, query):
        response, export, _ = _call(UserRole.TENANT_ADMIN, **query)
        assert response["statusCode"] == 422 and not export.called

    def test_it_is_served_by_the_excel_service(self):
        assert resolve_service(PATH) == "excel"
