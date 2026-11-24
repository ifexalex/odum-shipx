"""The generated documents (audit FD-39 to FD-42): one theme, the content each must carry, and the hard cases.

Every template is rendered with 40-character carton tags, 60 items and Chinese text, and read back with pypdf: the
pages are numbered "Page n of N", the title and author are set, only the embedded fonts are used, nothing the fonts
cannot draw is in the text, and no table cell's text is wider than its column.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

import pytest
from pypdf import PdfReader
from reportlab.platypus import Paragraph, Table

from services.excel import pdf_theme as t
from services.excel.export_invoice_pdf import generate_invoice_pdf, how_to_pay, line_items, shipping_detail
from services.excel.export_manifest_pdf import customer_rows, generate_manifest_pdf
from services.excel.export_packing_list_pdf import _COLUMNS as PL_COLUMNS
from services.excel.export_packing_list_pdf import generate_packing_list_pdf, item_rows
from services.excel.export_receipt_pdf import generate_receipt_pdf
from services.excel.export_release_note_pdf import build_meta_pairs, generate_release_note_pdf, qr_payload

BRAND = t.Brand.from_branding(
    {
        "company_name": "Acme Logistics Ltd",
        "display_name": "Acme Cargo",
        "tagline": "China to Nigeria, every week",
        "warehouse_address": "12 Wharf Road, Apapa, Lagos",
        "pickup_phone": "+234 1 234 5678",
        "support_email": "support@acme.example",
        "document_footer": "This document is an official record issued by Acme Cargo.",
        "primary_color": "#0a6ed1",
    }
)
LONG_TAG = "ACME-0123456789-ABCDEFGHIJ-0123456789-XY"  # 40 characters, no break opportunity
CHINESE = "电子产品 手机配件 (mixed) & <boxed>"


def _items(n: int = 60) -> list[dict[str, Any]]:
    return [
        {
            "carton_tag": LONG_TAG[:-2] + f"{i:02d}",
            "description": f"{CHINESE} item {i}",
            "package_unit": "carton",
            "quantity": 1,
            "length_cm": "60",
            "width_cm": "40",
            "height_cm": "35.5",
            "cbm": "0.0852",
            "weight_dispatch_kg": "18.25",
            "weight_actual_kg": "18.3",
            "customer_name": f"客户 {i % 7} Okonkwo",
        }
        for i in range(n)
    ]


def _read(buf: BytesIO) -> tuple[PdfReader, list[str]]:
    reader = PdfReader(BytesIO(buf.getvalue()))
    return reader, [page.extract_text() for page in reader.pages]


def _fonts(reader: PdfReader) -> set[str]:
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources") or {}
        for font in (resources.get("/Font") or {}).values():
            names.add(str(font.get_object().get("/BaseFont")))
    return names


def _assert_well_formed(buf: BytesIO, title: str, *, min_pages: int = 1) -> list[str]:
    reader, pages = _read(buf)
    assert len(pages) >= min_pages
    for number, text in enumerate(pages, start=1):
        assert f"Page {number} of {len(pages)}" in text
    assert reader.metadata is not None
    assert reader.metadata.title and reader.metadata.title.startswith(title)
    assert reader.metadata.author == "Acme Cargo"
    fonts = _fonts(reader)
    assert fonts, "no fonts found"
    assert all("Noto" in name for name in fonts), f"unexpected built-in font in {fonts}"
    assert "Helvetica" not in " ".join(fonts) and "Times" not in " ".join(fonts)
    return pages


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class TestFormats:
    @pytest.mark.parametrize(
        ("value", "expected"), [("174375", "₦174,375"), ("174375.5", "₦174,375.50"), ("-5000", "-₦5,000"), (None, "—")]
    )
    def test_money_reads_as_in_the_app(self, value, expected):
        assert t.money(value) == expected

    def test_quantities_use_one_precision_each_rounding_half_up(self):
        assert t.cbm("0.0305") == "0.031"
        assert t.cbm("2.000000") == "2.000"
        assert t.kg("1240.45") == "1,240.5"

    def test_dates_and_times_are_lagos_local(self):
        assert t.day(datetime(2026, 11, 14, 23, 30, tzinfo=UTC)) == "15 Nov 2026"
        assert t.day(date(2026, 9, 9)) == "9 Sep 2026"
        assert t.moment(datetime(2026, 11, 14, 14, 0, tzinfo=UTC)) == "14 Nov 2026, 15:00 WAT"

    def test_status_codes_read_as_words(self):
        assert t.humanise("released_with_outstanding") == "Released with outstanding"


class TestText:
    def test_markup_escapes_user_text(self):
        assert t.markup("A & B <b>") == "A &amp; B &lt;b&gt;"

    def test_chinese_runs_use_the_chinese_font(self):
        assert t.markup("电子 kit") == f'<font name="{t.CJK_FONT}">电子</font> kit'

    def test_the_fonts_cover_naira_and_chinese(self):
        assert t.missing_glyphs(f"₦ {CHINESE} 0123 ABC éü") == set()

    def test_reports_what_no_font_can_draw(self):
        assert t.missing_glyphs("ok 😀") == {"😀"}


class TestBrand:
    def test_uses_the_display_name_and_every_branding_field(self):
        assert BRAND.name == "Acme Cargo"
        assert (BRAND.tagline, BRAND.address, BRAND.phone, BRAND.email) == (
            "China to Nigeria, every week",
            "12 Wharf Road, Apapa, Lagos",
            "+234 1 234 5678",
            "support@acme.example",
        )
        assert BRAND.color == "#0a6ed1"

    def test_defaults_to_the_app_green_not_blue(self):
        assert t.Brand.from_branding({"company_name": "X"}).color == t.DEFAULT_BRAND == "#1c7922"
        assert t.Brand.from_branding({"company_name": "X", "primary_color": "javascript:1"}).color == t.DEFAULT_BRAND

    def test_an_unreadable_logo_falls_back_to_initials(self):
        brand = t.Brand.from_branding({"company_name": "Acme Cargo"}, logo=b"not an image")
        assert isinstance(t.logo_mark(brand), t.InitialsTile)


class TestTables:
    def test_no_cell_is_wider_than_its_column(self):
        table = t.DataTable(PL_COLUMNS, item_rows(_items(5))).build()
        table.wrap(t.CONTENT_WIDTH, 1000)
        widths = table._colWidths
        for row in table._cellvalues:
            for column, cell in enumerate(row):
                if isinstance(cell, Paragraph):
                    cell.wrap(widths[column] - 8, 1000)
                    assert max(cell.getActualLineWidths0() or [0]) <= widths[column] - 8 + 0.01

    def test_the_header_row_repeats_on_each_page(self):
        assert t.DataTable(PL_COLUMNS, item_rows(_items(2))).build().repeatRows == 1


# ---------------------------------------------------------------------------
# Documents, with long data and Chinese text
# ---------------------------------------------------------------------------

PL = {
    "id": "pl-1",
    "reference": "PL-20261121-001",
    "status": "approved",
    "customer_name": "李娜 Okonkwo",
    "customer_phone": "+2348012345678",
    "container_number": "MSCU1234567",
    "arrival_warehouse_name": "Lagos — Trade Fair",
    "loading_date": date(2026, 11, 20),
    "delivery_date": date(2026, 11, 18),
    "created_by_name": "Wei Chen",
    "created_at": datetime(2026, 11, 18, 9, 0, tzinfo=UTC),
    "approved_by_name": "Chidi Okafor",
    "approved_at": datetime(2026, 11, 19, 15, 0, tzinfo=UTC),
}


class TestPackingList:
    def test_renders_sixty_long_tagged_chinese_items_across_numbered_pages(self):
        pages = _assert_well_formed(generate_packing_list_pdf(BRAND, PL, _items()), "Packing list PL-20261121-001", min_pages=2)
        text = "\n".join(pages)
        for expected in ("Acme Cargo", "PACKING LIST", "PL-20261121-001", "Approved", "Wei Chen", "Chidi Okafor", "60 packages"):
            assert expected in text
        assert "电子产品" in text
        assert "<boxed>" in text  # printed, not taken as markup

    def test_rows_use_the_app_formats(self):
        row = item_rows(_items(1))[0]
        assert row[2:] == ["Carton", "1", "60 × 40 × 35.5", "0.085", "18.3", "18.3"]


NOTE = {
    "id": "rn-1",
    "reference_number": "ACM-RN-20261121-0001",
    "status": "active",
    "customer_name": "李娜 Okonkwo",
    "customer_phone": "+2348012345678",
    "container_number": "MSCU1234567",
    "billing_reference": "INV-A-002",
    "carton_count": 60,
    "is_partial": True,
    "carton_tags": [LONG_TAG[:-2] + f"{i:02d}" for i in range(60)],
    "valid_until": date(2026, 12, 5),
    "created_at": datetime(2026, 11, 21, 10, 0, tzinfo=UTC),
    "warehouse_name": "Lagos — Trade Fair",
    "warehouse_address": "Block C, Trade Fair Complex",
    "warehouse_phone": "+234 1 222 3333",
    "payment_status": "partially_paid",
    "billing_total_ngn": Decimal("139500"),
    "billing_amount_paid_ngn": Decimal("100000"),
    "billing_balance_ngn": Decimal("39500"),
    "receipt_number": "RCT-0007",
}


class TestReleaseNote:
    def test_carries_every_field_the_brief_lists(self):
        pages = _assert_well_formed(generate_release_note_pdf(BRAND, NOTE), "Release note ACM-RN-20261121-0001", min_pages=2)
        text = "\n".join(pages)
        for expected in (
            "RELEASE NOTE",
            "Valid until",
            "5 Dec 2026",
            "60 (partial release)",
            "Collected",
            LONG_TAG[:20],
            "₦100,000 of ₦139,500",
            "₦39,500",
            "Trade Fair Complex",
            "Warehouse attendant",
            "Terms",
        ):
            assert expected in text, expected

    def test_the_qr_code_holds_the_bare_reference_the_scanner_looks_up(self):
        assert qr_payload(NOTE) == "ACM-RN-20261121-0001"

    def test_on_credit_names_who_granted_it(self):
        pairs = dict(build_meta_pairs({**NOTE, "is_on_credit": True, "credit_granted_by_name": "Adaeze Okafor"}))
        assert pairs["Payment status"] == "On credit, granted by Adaeze Okafor"
        assert "Amount paid" not in pairs

    def test_a_paid_note_shows_no_balance(self):
        pairs = dict(
            build_meta_pairs({**NOTE, "billing_balance_ngn": Decimal("0"), "billing_amount_paid_ngn": Decimal("139500")})
        )
        assert "Balance outstanding" not in pairs

    def test_a_bare_note_still_renders(self):
        _assert_well_formed(generate_release_note_pdf(BRAND, {"id": "rn-2", "reference_number": "RN-2"}), "Release note RN-2")


PAYMENT = {
    "id": "pay-1",
    "receipt_number": "RCT-0007",
    "payment_date": date(2026, 11, 21),
    "payer_name": "李娜 Okonkwo",
    "customer_phone": "+2348012345678",
    "amount_ngn": Decimal("100000"),
    "payment_method": "bank_transfer",
    "reference_number": "TRF-889912",
    "bank_name": "Zenith Bank",
    "billing_reference": "INV-A-002",
    "billing_total_ngn": Decimal("139500"),
    "balance_after_ngn": Decimal("39500"),
    "received_by_name": "Amaka Nwosu",
}


class TestReceipt:
    def test_carries_amount_in_words_the_invoice_and_the_balance_after(self):
        text = "\n".join(_assert_well_formed(generate_receipt_pdf(BRAND, PAYMENT), "Receipt RCT-0007"))
        for expected in (
            "RECEIPT",
            "₦100,000",
            "one hundred thousand",
            "Bank transfer",
            "TRF-889912",
            "INV-A-002",
            "₦39,500",
            "Amaka Nwosu",
        ):
            assert expected.lower() in text.lower(), expected

    def test_a_bare_payment_still_renders(self):
        _assert_well_formed(generate_receipt_pdf(BRAND, {"id": "p2", "receipt_number": "R2", "amount_ngn": "5"}), "Receipt R2")


BILLING = {
    "id": "b-1",
    "invoice_number": "INV-A-002",
    "status": "partially_paid",
    "customer_name": "李娜 Okonkwo",
    "customer_phone": "+2348012345678",
    "container_number": "MSCU1234567",
    "total_cartons": 60,
    "total_cbm": Decimal("2.000000"),
    "cbm_rate_usd": Decimal("45.0000"),
    "exchange_rate_ngn": Decimal("1550.0000"),
    "subtotal_ngn": Decimal("139500"),
    "storage_fees_ngn": Decimal("3000"),
    "carryover_ngn": Decimal("5000"),
    "credits_applied_ngn": Decimal("2000"),
    "total_ngn": Decimal("145500"),
    "amount_paid_ngn": Decimal("100000"),
    "balance_ngn": Decimal("45500"),
    "billed_at": datetime(2026, 11, 21, 9, 0, tzinfo=UTC),
}
BANK = {"bank_name": "Zenith Bank", "account_name": "Acme Cargo Ltd", "account_number": "1012345678"}


class TestInvoice:
    def test_is_a_branded_invoice_with_line_items_not_a_column_dump(self):
        charges = [{"description": f"清关费 customs fee {i}", "amount_ngn": "1000"} for i in range(40)]
        pages = _assert_well_formed(generate_invoice_pdf(BRAND, BILLING, charges, bank=BANK, online=True), "Invoice INV-A-002")
        text = "\n".join(pages)
        for expected in (
            "INVOICE",
            "Partially paid",
            "2.000 CBM × $45.00 per CBM × ₦1,550 per $",
            "Storage fees",
            "Carried over",
            "-₦2,000",
            "₦145,500",
            "₦45,500",
            "Zenith Bank",
            "1012345678",
        ):
            assert expected in text, expected
        for column_name in ("Cbm Rate Usd", "Exchange Rate Ngn", "Misc Fees Itemized", "partially_paid", "1550.0000", "2.000000"):
            assert column_name not in text

    def test_line_items_follow_the_invoice(self):
        lines = line_items(BILLING, [{"description": "Customs", "amount_ngn": "5000"}])
        assert [line[0] for line in lines] == ["Shipping", "Customs", "Storage fees", "Carried over", "Credit applied"]
        assert shipping_detail(BILLING) == "2.000 CBM × $45.00 per CBM × ₦1,550 per $"

    def test_how_to_pay_uses_only_what_the_tenant_set(self):
        assert how_to_pay(BILLING, None, False, BRAND) == [
            "Contact us to pay: +234 1 234 5678 or support@acme.example. Quote INV-A-002."
        ]
        assert any("Zenith Bank" in line for line in how_to_pay(BILLING, BANK, False, BRAND))

    def test_a_paid_invoice_asks_for_nothing(self):
        text = "\n".join(
            _assert_well_formed(generate_invoice_pdf(BRAND, {**BILLING, "balance_ngn": 0, "status": "paid"}, []), "Invoice")
        )
        assert "How to pay" not in text


MANIFEST = {
    "id": "m-1",
    "container_number": "MSCU1234567",
    "vessel_name": "MSC Aurora",
    "voyage_number": "0457E",
    "shipping_line": "MSC",
    "origin": "Guangzhou",
    "destination": "Lagos",
    "departure_date": date(2026, 10, 1),
    "estimated_arrival_date": date(2026, 11, 15),
    "verification_status": "verified",
    "verified_by_name": "Amaka Nwosu",
    "verified_at": datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
}


class TestManifest:
    def test_one_row_per_customer_with_totals(self):
        rows = customer_rows(_items())
        assert len(rows) == 7
        assert sum(r["cartons"] for r in rows) == 60

    def test_renders_with_chinese_customer_names(self):
        text = "\n".join(_assert_well_formed(generate_manifest_pdf(BRAND, MANIFEST, _items()), "Manifest MSCU1234567"))
        for expected in ("MANIFEST", "MSC Aurora", "0457E", "Verified", "Amaka Nwosu", "客户"):
            assert expected in text, expected


def test_every_table_in_every_document_is_a_wrapping_table():
    """No document builds its own table style: they all come from pdf_theme, so the theme's rules hold everywhere."""
    import inspect

    from services.excel import export_invoice_pdf, export_manifest_pdf, export_packing_list_pdf, export_receipt_pdf

    for module in (export_invoice_pdf, export_manifest_pdf, export_packing_list_pdf, export_receipt_pdf):
        source = inspect.getsource(module)
        assert "Helvetica" not in source and "Times" not in source and "#1a56db" not in source
    assert issubclass(t.DataTable(PL_COLUMNS, []).build().__class__, Table)


# ---------------------------------------------------------------------------
# Routes (FD-39): one PDF route per record; the data exports are spreadsheets only
# ---------------------------------------------------------------------------

import json  # noqa: E402
from unittest.mock import patch  # noqa: E402

from services.excel import handler, service  # noqa: E402
from shared.http_routing import resolve_service  # noqa: E402
from shared.tenant_context import TenantContext, UserRole  # noqa: E402

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _get(role: UserRole, path: str, **query: str) -> tuple[dict[str, Any], Any, Any]:
    event = {
        "requestContext": {"requestId": "r1", "http": {"method": "GET", "path": path}},
        "queryStringParameters": query or None,
        "headers": {},
    }
    ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=role)
    with (
        patch.object(handler, "get_tenant_context", return_value=ctx),
        patch.object(handler, "record_usage"),
        patch.object(service, "export_invoice_pdf", return_value={"download_url": "u"}) as invoice,
        patch.object(service, "export_manifest_pdf", return_value={"download_url": "u"}) as manifest,
    ):
        response = handler.lambda_handler(event, None)
    return response, invoice, manifest


class TestRoutes:
    @pytest.mark.parametrize("path", ["/v1/billing/b-1/pdf", "/v1/manifests/m-1/pdf"])
    def test_the_document_routes_are_served_by_the_excel_service(self, path):
        assert resolve_service(path) == "excel"

    def test_a_customer_opens_their_invoice_with_ownership_checked(self):
        response, invoice, _ = _get(UserRole.CUSTOMER, "/v1/billing/b-1/pdf")
        assert response["statusCode"] == 200
        assert invoice.call_args.kwargs["customer_user_id"] == "user-1"

    def test_staff_open_any_invoice(self):
        response, invoice, _ = _get(UserRole.NIGERIA_OFFICE_STAFF, "/v1/billing/b-1/pdf")
        assert response["statusCode"] == 200 and invoice.call_args.kwargs["customer_user_id"] is None

    def test_the_warehouse_cannot_open_an_invoice(self):
        response, invoice, _ = _get(UserRole.WAREHOUSE_ATTENDANT, "/v1/billing/b-1/pdf")
        assert response["statusCode"] == 403 and not invoice.called

    def test_staff_open_a_manifest_and_a_customer_cannot(self):
        assert _get(UserRole.CHINA_OFFICE_STAFF, "/v1/manifests/m-1/pdf")[0]["statusCode"] == 200
        response, _, manifest = _get(UserRole.CUSTOMER, "/v1/manifests/m-1/pdf")
        assert response["statusCode"] == 403 and not manifest.called

    @pytest.mark.parametrize("path", ["/v1/billing/b-1/export", "/v1/manifests/m-1/export", "/v1/packing-lists/p-1/export"])
    def test_the_data_exports_no_longer_make_a_pdf(self, path):
        response, _, _ = _get(UserRole.TENANT_ADMIN, path, format="pdf")
        assert response["statusCode"] == 422
        assert "/pdf" in json.dumps(json.loads(response["body"]))


class TestServiceLogo:
    def test_reads_the_logo_only_from_the_tenants_own_logo_prefix(self):
        with (
            patch.object(
                service.repo, "get_tenant_branding", return_value={"company_name": "Acme", "logo_key": "bbbb/branding/logo/x.png"}
            ),
            patch.object(service, "get_storage_provider") as storage,
        ):
            brand = service._brand(TENANT)
        storage.return_value.get_object.assert_not_called()
        assert brand.logo is None

    def test_a_logo_that_cannot_be_read_leaves_the_initials(self):
        with (
            patch.object(
                service.repo,
                "get_tenant_branding",
                return_value={"company_name": "Acme", "logo_key": f"{TENANT}/branding/logo/x.png"},
            ),
            patch.object(service, "get_storage_provider") as storage,
        ):
            storage.return_value.get_object.side_effect = OSError("gone")
            brand = service._brand(TENANT)
        assert brand.logo is None and brand.name == "Acme"

    def test_download_links_name_the_file(self):
        assert service._disposition("Acme_invoice_INV-1.pdf", "pdf") == 'inline; filename="Acme_invoice_INV-1.pdf"'
        assert service._disposition("invoices.xlsx", "xlsx") == 'attachment; filename="invoices.xlsx"'
