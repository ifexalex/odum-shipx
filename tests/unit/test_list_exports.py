"""The invoice-list and container-list exports behind the Export buttons.

What matters most here: an export is exactly the rows the screen shows (one shared filter), it is refused rather
than cut short when too large, a customer-typed name cannot run as a spreadsheet formula, and only the roles that
may see the list can export it.
"""

import csv
import io
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import openpyxl
import pytest
from pydantic import ValidationError as PydanticValidationError

from services.billing import repository as billing_repo
from services.excel import handler, service
from services.excel import repository as excel_repo
from services.excel._tables import Column, build_csv, build_xlsx
from services.excel.export_lists import BILLING_LIST_COLUMNS, CONTAINER_LIST_COLUMNS
from services.excel.models import ContainerListExportQuery, ListExportQuery
from services.tracking import repository as tracking_repo
from shared.exceptions import BusinessRuleViolationError, ValidationError
from shared.http_routing import resolve_service
from shared.list_filters import billing_filter, container_filter
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
HOSTILE = "'; DROP TABLE billing; --"

BILLING_FILTERS = {
    "status": ["paid"],
    "customer_id": "cu-1",
    "created_after": "2026-01-01",
    "created_before": "2026-02-01",
    "q": "50%_x",
}
CONTAINER_FILTERS = {
    "status": ["arrived"],
    "created_after": "2026-01-01",
    "eta_before": "2026-04-01",
    "q": "50%_x",
}


# ---------------------------------------------------------------------------
# One filter for the list and its export
# ---------------------------------------------------------------------------


class TestSharedFilters:
    """These are the exact fragments the list queries built before they were extracted (captured from the old code,
    so a change here is a change to what the list screens show)."""

    def test_billing_filter_with_nothing_set_is_only_the_tenant(self):
        assert billing_filter("t1", {}) == ("b.tenant_id = %(tenant_id)s", {"tenant_id": "t1"})

    def test_billing_filter_with_everything_set(self):
        clause, params = billing_filter("t1", BILLING_FILTERS)
        assert clause == (
            "b.tenant_id = %(tenant_id)s AND b.status = ANY(%(statuses)s) AND b.customer_id = %(customer_id)s"
            " AND b.billed_at >= %(created_after)s AND b.billed_at <= %(created_before)s"
            " AND (b.invoice_number ILIKE %(q)s OR cu.name ILIKE %(q)s OR c.container_number ILIKE %(q)s)"
        )
        assert params == {
            "tenant_id": "t1",
            "statuses": ["paid"],
            "customer_id": "cu-1",
            "created_after": "2026-01-01",
            "created_before": "2026-02-01",
            "q": "%50%_x%",
        }

    def test_container_filter_with_nothing_set_is_only_the_tenant(self):
        assert container_filter("t1", {}) == ("c.tenant_id = %(tenant_id)s", {"tenant_id": "t1"})

    def test_container_filter_with_everything_set(self):
        clause, params = container_filter("t1", {**CONTAINER_FILTERS, "created_before": "2026-02-01", "eta_after": "2026-03-01"})
        assert clause == (
            "c.tenant_id = %(tenant_id)s AND c.status = ANY(%(statuses)s) AND c.created_at >= %(created_after)s"
            " AND c.created_at <= %(created_before)s AND c.estimated_arrival_date >= %(eta_after)s"
            " AND c.estimated_arrival_date <= %(eta_before)s"
            " AND (c.container_number ILIKE %(q)s OR c.vessel_name ILIKE %(q)s OR c.voyage_number ILIKE %(q)s)"
        )
        assert params["q"] == "%50%_x%"

    @pytest.mark.parametrize("builder", [billing_filter, container_filter])
    def test_one_status_or_several_are_both_a_list(self, builder):
        assert builder("t", {"status": "unpaid"})[1]["statuses"] == ["unpaid"]
        assert builder("t", {"status": ("a", "b")})[1]["statuses"] == ["a", "b"]

    @pytest.mark.parametrize("builder", [billing_filter, container_filter])
    def test_values_only_ever_travel_as_parameters(self, builder):
        clause, params = builder("t", {"q": HOSTILE, "status": [HOSTILE], "created_after": HOSTILE})
        assert HOSTILE not in clause
        assert HOSTILE in str(params)


class TestExportsUseTheListsFilter:
    """The invariant behind "Export gives back what is on screen": the list query and the export query are built
    from the same shared clause, so they cannot disagree about which rows match."""

    @staticmethod
    def _sql(module, fn, *args, **kwargs):
        with patch.object(module, "execute_with_tenant", return_value=[]) as execute:
            fn(*args, **kwargs)
        _, query, params = execute.call_args.args
        return " ".join(query.split()), params

    def test_invoice_list_and_export_share_the_clause(self):
        clause, filter_params = billing_filter(TENANT, BILLING_FILTERS)
        list_sql, list_params = self._sql(billing_repo, billing_repo.list_billing_all, TENANT, BILLING_FILTERS, 25)
        export_sql, export_params = self._sql(excel_repo, excel_repo.list_billing_for_export, TENANT, BILLING_FILTERS, 10_000)
        assert f"WHERE {clause}" in list_sql
        assert f"WHERE {clause}" in export_sql
        assert filter_params.items() <= list_params.items()
        assert filter_params.items() <= export_params.items()

    def test_container_list_and_export_share_the_clause(self):
        clause, filter_params = container_filter(TENANT, CONTAINER_FILTERS)
        list_sql, list_params = self._sql(tracking_repo, tracking_repo.list_containers, TENANT, CONTAINER_FILTERS, 25)
        export_sql, export_params = self._sql(
            excel_repo, excel_repo.list_containers_for_export, TENANT, CONTAINER_FILTERS, 10_000
        )
        assert f"WHERE {clause}" in list_sql
        assert f"WHERE {clause}" in export_sql
        assert filter_params.items() <= list_params.items()
        assert filter_params.items() <= export_params.items()


class TestExportQueries:
    @staticmethod
    def _run(fn, rows=(), **kwargs):
        with patch.object(excel_repo, "execute_with_tenant", return_value=list(rows)) as execute:
            result = fn(TENANT, {"q": HOSTILE}, **kwargs)
        _, query, params = execute.call_args.args
        return result, " ".join(query.split()), params

    def test_invoices_are_tenant_scoped_and_the_text_is_a_bound_parameter(self):
        _, query, params = self._run(excel_repo.list_billing_for_export, limit=10_000)
        assert "b.tenant_id = %(tenant_id)s" in query and params["tenant_id"] == TENANT
        assert HOSTILE not in query
        assert "cl.tenant_id = b.tenant_id" in query and "sfl.tenant_id = b.tenant_id" in query
        assert "cu.tenant_id = b.tenant_id" in query and "c.tenant_id = b.tenant_id" in query

    def test_containers_are_tenant_scoped_and_the_text_is_a_bound_parameter(self):
        _, query, params = self._run(excel_repo.list_containers_for_export, limit=10_000)
        assert "c.tenant_id = %(tenant_id)s" in query and params["tenant_id"] == TENANT
        assert HOSTILE not in query
        assert "pl.tenant_id = c.tenant_id" in query

    def test_it_asks_for_one_row_more_than_the_limit_to_know_whether_there_are_more(self):
        _, _, params = self._run(excel_repo.list_billing_for_export, limit=10_000)
        assert params["limit"] == 10_001

    def test_more_rows_than_the_limit_reports_truncation(self):
        rows = [{"id": str(i)} for i in range(4)]
        (page, truncated), _, _ = self._run(excel_repo.list_containers_for_export, rows=rows, limit=3)
        assert len(page) == 3 and truncated is True
        (page, truncated), _, _ = self._run(excel_repo.list_containers_for_export, rows=rows[:3], limit=3)
        assert len(page) == 3 and truncated is False

    def test_the_sort_follows_the_list_and_is_allowlisted(self):
        _, query, _ = self._run(excel_repo.list_billing_for_export, limit=5, sort_field="invoice_number", sort_direction="ASC")
        assert "ORDER BY b.invoice_number ASC" in query
        with pytest.raises(ValidationError):
            self._run(excel_repo.list_billing_for_export, limit=5, sort_field="password_hash")
        with pytest.raises(ValidationError):
            self._run(excel_repo.list_containers_for_export, limit=5, sort_field="id; DROP TABLE x")


# ---------------------------------------------------------------------------
# The file writers
# ---------------------------------------------------------------------------

COLUMNS = [
    Column("name", "Name"),
    Column("when", "When (UTC)", "datetime"),
    Column("day", "Day", "date"),
    Column("amount", "Amount", "money"),
    Column("cbm", "CBM", "number"),
    Column("count", "Count", "integer"),
]


def _sheet(rows):
    return openpyxl.load_workbook(BytesIO(build_xlsx("Test", COLUMNS, rows).getvalue())).active


class TestXlsx:
    def test_header_filter_and_freeze(self):
        sheet = _sheet([{"name": "A"}])
        assert [c.value for c in sheet[1]] == [c.header for c in COLUMNS]
        assert sheet["A1"].font.bold
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == "A1:F2"

    @pytest.mark.parametrize("hostile", ['=HYPERLINK("http://evil","click")', "+1 555 0100", "-2+3", "@SUM(1)", "=1+1"])
    def test_a_name_that_looks_like_a_formula_stays_text(self, hostile):
        cell = _sheet([{"name": hostile}])["A2"]
        assert cell.data_type == "s", "stored as a formula: it would run when the file is opened"
        assert cell.value == hostile

    def test_money_and_numbers_are_numbers_with_formats(self):
        sheet = _sheet([{"name": "A", "amount": Decimal("-1234.50"), "cbm": Decimal("2.125"), "count": 7}])
        assert sheet["D2"].value == -1234.5 and sheet["D2"].number_format == "#,##0.00"
        assert sheet["E2"].value == 2.125 and sheet["E2"].number_format == "#,##0.000"
        assert sheet["F2"].value == 7 and sheet["F2"].number_format == "#,##0"

    def test_a_timestamp_is_written_in_utc(self):
        lagos = timezone(timedelta(hours=1))
        sheet = _sheet(
            [{"name": "A", "when": datetime(2026, 1, 1, 23, 30, tzinfo=lagos), "day": datetime(2026, 3, 4, 5, 6, tzinfo=UTC)}]
        )
        assert sheet["B2"].value == datetime(2026, 1, 1, 22, 30)
        assert sheet["C2"].value == datetime(2026, 3, 4)

    def test_missing_values_are_blank(self):
        sheet = _sheet([{"name": None, "amount": None, "when": None}])
        assert all(sheet.cell(row=2, column=i).value is None for i in range(1, 7))

    def test_an_empty_result_is_a_header_only_sheet(self):
        sheet = _sheet([])
        assert sheet.max_row == 1 and sheet["A1"].value == "Name"

    def test_non_ascii_names_survive(self):
        assert _sheet([{"name": "装箱单 Ngọc"}])["A2"].value == "装箱单 Ngọc"


def _csv_rows(rows):
    raw = build_csv(COLUMNS, rows).getvalue()
    assert raw.startswith(b"\xef\xbb\xbf"), "Excel needs the byte-order mark to read UTF-8"
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class TestCsv:
    def test_header_and_crlf(self):
        raw = build_csv(COLUMNS, [{"name": "A"}]).getvalue().decode("utf-8-sig")
        assert raw.split("\r\n")[0] == "Name,When (UTC),Day,Amount,CBM,Count"

    @pytest.mark.parametrize("hostile", ['=HYPERLINK("http://evil","click")', "+1 555 0100", "-2+3", "@SUM(1)", "\tx"])
    def test_a_name_that_looks_like_a_formula_is_defused(self, hostile):
        assert _csv_rows([{"name": hostile}])[1][0] == f"'{hostile}"

    def test_a_negative_amount_is_not_mistaken_for_a_formula(self):
        row = _csv_rows([{"name": "A", "amount": Decimal("-12.50"), "cbm": Decimal("-0.5")}])[1]
        assert row[3] == "-12.50" and row[4] == "-0.5"

    def test_money_is_written_exactly(self):
        assert _csv_rows([{"name": "A", "amount": Decimal("1234.50")}])[1][3] == "1234.50"
        assert _csv_rows([{"name": "A", "amount": "0.10"}])[1][3] == "0.10"

    def test_timestamps_are_utc_and_days_are_iso(self):
        lagos = timezone(timedelta(hours=1))
        row = _csv_rows(
            [{"name": "A", "when": datetime(2026, 1, 1, 23, 30, tzinfo=lagos), "day": datetime(2026, 3, 4, 5, 6, tzinfo=UTC)}]
        )[1]
        assert row[1] == "2026-01-01 22:30" and row[2] == "2026-03-04"

    def test_commas_quotes_and_newlines_round_trip(self):
        assert _csv_rows([{"name": 'Ada, "the" Great\nLtd'}])[1][0] == 'Ada, "the" Great\nLtd'

    def test_blank_and_integer_columns(self):
        row = _csv_rows([{"name": "A", "count": 3}])[1]
        assert row[1] == "" and row[5] == "3"


class TestColumnSpecs:
    def test_the_invoice_columns_read_real_billing_columns(self):
        """A key that is not a column silently exports blank (the storage-fee column read ₦0 for months for this
        reason), so these are the names the table and the query actually have."""
        keys = {c.key for c in BILLING_LIST_COLUMNS}
        assert {"invoice_number", "billed_at", "total_ngn", "amount_paid_ngn", "balance_ngn", "exchange_rate_ngn"} <= keys
        assert {"customer_name", "container_number", "carryover_ngn", "storage_fees_ngn"} <= keys  # selected by the query

    def test_the_container_columns_read_real_container_columns(self):
        keys = {c.key for c in CONTAINER_LIST_COLUMNS}
        assert {"container_number", "status", "estimated_arrival_date", "vessel_name", "voyage_number", "seal_number"} <= keys
        assert {"packing_list_count", "approved_packing_list_count", "total_cbm_packed"} <= keys  # selected by the query

    def test_headers_are_unique(self):
        for columns in (BILLING_LIST_COLUMNS, CONTAINER_LIST_COLUMNS):
            assert len({c.header for c in columns}) == len(columns)


# ---------------------------------------------------------------------------
# The query string
# ---------------------------------------------------------------------------


class TestListExportQuery:
    def test_what_the_lists_send_is_accepted_unchanged(self):
        q = ListExportQuery(
            status="unpaid,paid", q="ab", created_after="2026-01-01", created_before="2026-02-01", sort="billed_at"
        )
        assert q.filters() == {
            "status": ["unpaid", "paid"],
            "q": "ab",
            "created_after": "2026-01-01",
            "created_before": "2026-02-01",
        }
        assert (q.format, q.sort, q.direction) == ("xlsx", "billed_at", "desc")

    def test_only_what_is_set_becomes_a_filter(self):
        assert ListExportQuery().filters() == {}
        assert ListExportQuery(status="", q="", created_after="").filters() == {}

    def test_the_container_export_adds_an_eta_window(self):
        q = ContainerListExportQuery(eta_after="2026-03-01", eta_before="2026-04-01", format="csv", direction="ASC")
        assert q.filters() == {"eta_after": "2026-03-01", "eta_before": "2026-04-01"}
        assert q.format == "csv" and q.direction == "asc"

    def test_unknown_parameters_are_ignored(self):
        assert ListExportQuery(limit="50", cursor="x").filters() == {}

    @pytest.mark.parametrize(
        "bad",
        [
            {"format": "pdf"},
            {"status": "paid;drop"},
            {"status": ",".join(["a"] * 13)},
            {"created_after": "2026-13-40"},
            {"created_before": "yesterday"},
            {"sort": "id; DROP TABLE x"},
            {"q": "x" * 101},
            {"direction": "sideways"},
        ],
    )
    def test_bad_values_are_refused(self, bad):
        with pytest.raises(PydanticValidationError):
            ListExportQuery(**bad)

    def test_a_bad_eta_is_refused(self):
        with pytest.raises(PydanticValidationError):
            ContainerListExportQuery(eta_after="soon")


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


def _invoice(**kw):
    return {
        "id": "b1",
        "invoice_number": "ACME-INV-1",
        "customer_name": "Ngozi",
        "container_number": "MSCU1",
        "billed_at": datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        "status": "unpaid",
        "total_ngn": Decimal("1000.00"),
        "amount_paid_ngn": Decimal("250.00"),
        "balance_ngn": Decimal("750.00"),
        **kw,
    }


class TestServiceListExports:
    @staticmethod
    def _export_invoices(rows, truncated=False, fmt="xlsx", filters=None):
        with patch.object(service.repo, "list_billing_for_export", return_value=(rows, truncated)) as query:
            result = service.export_billing_list(
                TENANT,
                filters or {},
                fmt=fmt,
                sort_field="billed_at",
                sort_direction="asc",
                actor_id="u1",
                actor_role="nigeria_office_staff",
            )
        return result, query

    def test_it_returns_a_download_with_the_row_count(self, stored):
        result, _ = self._export_invoices([_invoice(), _invoice(id="b2")])
        assert result["download_url"] and result["row_count"] == 2
        assert stored["filename"].startswith("Acme_Shipping_Ltd_invoices_") and stored["filename"].endswith(".xlsx")

    def test_the_lists_sort_and_the_row_limit_reach_the_query(self, stored):
        _, query = self._export_invoices([_invoice()], filters={"status": ["paid"]})
        query.assert_called_once_with(TENANT, {"status": ["paid"]}, service.EXPORT_ROW_LIMIT, "billed_at", "asc")

    def test_csv_is_a_csv_file(self, stored):
        self._export_invoices([_invoice()], fmt="csv")
        assert stored["fmt"] == "csv" and stored["filename"].endswith(".csv")
        assert b"ACME-INV-1" in stored["content"] and b"750.00" in stored["content"]

    def test_too_many_rows_is_refused_not_cut_short(self, stored):
        with pytest.raises(BusinessRuleViolationError) as caught:
            self._export_invoices([_invoice()], truncated=True)
        assert caught.value.rule_id == "EXPORT_TOO_LARGE"
        assert "Narrow the filters" in caught.value.message
        assert "content" not in stored, "nothing may be uploaded for a refused export"
        stored["audit"].assert_not_called()

    def test_an_empty_list_is_still_a_valid_file(self, stored):
        result, _ = self._export_invoices([])
        assert result["row_count"] == 0 and stored["content"]

    def test_the_export_is_audited_without_the_search_text(self, stored):
        self._export_invoices([_invoice()], filters={"status": ["paid"], "q": "Ngozi Adeyemi"})
        kwargs = stored["audit"].call_args.kwargs
        assert (kwargs["entity_type"], kwargs["action"], kwargs["actor_id"]) == ("billing", "EXPORT", "u1")
        after = kwargs["after_state"]
        assert after["row_count"] == 1 and after["text_search"] is True
        assert after["filters"] == {"status": ["paid"]}
        assert "Ngozi" not in json.dumps(after)

    def test_the_container_export(self, stored):
        row = {"id": "k1", "container_number": "MSCU1", "status": "arrived", "packing_list_count": 3}
        with patch.object(service.repo, "list_containers_for_export", return_value=([row], False)):
            result = service.export_container_list(
                TENANT,
                {},
                fmt="csv",
                sort_field="created_at",
                sort_direction="desc",
                actor_id="u1",
                actor_role="china_office_staff",
            )
        assert result["row_count"] == 1 and "_containers_" in stored["filename"]
        assert stored["audit"].call_args.kwargs["entity_type"] == "container"


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------


def _event(path, **query):
    return {
        "requestContext": {"requestId": "r1", "http": {"method": "GET", "path": path}},
        "queryStringParameters": query or None,
        "headers": {},
    }


def _call(role, path, **query):
    ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=role)
    with (
        patch.object(handler, "get_tenant_context", return_value=ctx),
        patch.object(handler, "record_usage"),
        patch.object(service, "export_billing_list", return_value={"download_url": "u"}) as invoices,
        patch.object(service, "export_container_list", return_value={"download_url": "u"}) as containers,
    ):
        response = handler.lambda_handler(_event(path, **query), None)
    return response, invoices, containers


class TestHandler:
    def test_the_tenant_admin_can_export_the_invoice_list(self):
        response, invoices, _ = _call(UserRole.TENANT_ADMIN, "/v1/billing/export")
        assert response["statusCode"] == 200 and invoices.called

    @pytest.mark.parametrize(
        "role",
        [
            UserRole.NIGERIA_OFFICE_STAFF,  # sees the list, but the bulk export is the admin's (owner decision)
            UserRole.CHINA_OFFICE_STAFF,
            UserRole.WAREHOUSE_ATTENDANT,
            UserRole.CUSTOMER,
            UserRole.PLATFORM_ADMIN,
        ],
    )
    def test_invoice_list_export_is_refused_to_everyone_else(self, role):
        response, invoices, _ = _call(role, "/v1/billing/export")
        assert response["statusCode"] == 403 and not invoices.called

    @pytest.mark.parametrize("role", [UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CHINA_OFFICE_STAFF])
    def test_container_list_export_roles_that_may_see_containers(self, role):
        response, _, containers = _call(role, "/v1/containers/export")
        assert response["statusCode"] == 200 and containers.called

    @pytest.mark.parametrize("role", [UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER])
    def test_container_list_export_is_refused_to_everyone_else(self, role):
        response, _, containers = _call(role, "/v1/containers/export")
        assert response["statusCode"] == 403 and not containers.called

    def test_the_lists_filters_sort_and_format_are_forwarded(self):
        _, invoices, _ = _call(
            UserRole.TENANT_ADMIN,
            "/v1/billing/export",
            status="unpaid,paid",
            q="ab",
            created_after="2026-01-01",
            sort="invoice_number",
            direction="ASC",
            format="csv",
            limit="50",
        )
        args, kwargs = invoices.call_args
        assert args == (TENANT, {"status": ["unpaid", "paid"], "q": "ab", "created_after": "2026-01-01"})
        assert (kwargs["fmt"], kwargs["sort_field"], kwargs["sort_direction"]) == ("csv", "invoice_number", "asc")
        assert kwargs["actor_id"] == "user-1" and kwargs["actor_role"] == "tenant_admin"

    def test_the_container_eta_window_is_forwarded(self):
        _, _, containers = _call(UserRole.CHINA_OFFICE_STAFF, "/v1/containers/export", eta_before="2026-04-01", status="arrived")
        assert containers.call_args.args[1] == {"status": ["arrived"], "eta_before": "2026-04-01"}

    @pytest.mark.parametrize(
        "query",
        [{"format": "pdf"}, {"created_after": "2026-99-99"}, {"sort": "id; DROP TABLE x"}, {"status": "a;b"}, {"q": "x" * 200}],
    )
    def test_bad_input_is_a_422_and_nothing_is_exported(self, query):
        response, invoices, _ = _call(UserRole.TENANT_ADMIN, "/v1/billing/export", **query)
        assert response["statusCode"] == 422 and not invoices.called

    def test_the_single_invoice_export_is_not_shadowed(self):
        ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=UserRole.NIGERIA_OFFICE_STAFF)
        with (
            patch.object(handler, "get_tenant_context", return_value=ctx),
            patch.object(handler, "record_usage"),
            patch.object(service, "export_billing", return_value={"download_url": "u"}) as single,
            patch.object(service, "export_billing_list") as whole_list,
        ):
            response = handler.lambda_handler(_event("/v1/billing/b-123/export"), None)
        assert response["statusCode"] == 200 and single.call_args.args[1] == "b-123" and not whole_list.called

    def test_a_service_refusal_reaches_the_client_as_a_422(self):
        ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=UserRole.TENANT_ADMIN)
        too_big = BusinessRuleViolationError("More than 10,000 invoices match.", rule_id="EXPORT_TOO_LARGE")
        with (
            patch.object(handler, "get_tenant_context", return_value=ctx),
            patch.object(handler, "record_usage"),
            patch.object(service, "export_billing_list", side_effect=too_big),
        ):
            response = handler.lambda_handler(_event("/v1/billing/export"), None)
        assert response["statusCode"] == 422
        assert json.loads(response["body"])["rule_id"] == "EXPORT_TOO_LARGE"


class TestRouting:
    @pytest.mark.parametrize("path", ["/v1/billing/export", "/v1/containers/export"])
    def test_the_list_exports_are_served_by_the_excel_service_not_the_record_routes(self, path):
        assert resolve_service(path) == "excel"
