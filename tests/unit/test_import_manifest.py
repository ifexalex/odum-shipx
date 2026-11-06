"""Unit tests for services.excel.import_manifest (parser) and
services.excel.service.process_manifest_import (orchestration)."""

from io import BytesIO
from unittest.mock import patch

import openpyxl
from openpyxl.styles import Font

from services.excel.import_manifest import parse_manifest_xlsx
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _ctx(role: UserRole = UserRole.CHINA_OFFICE_STAFF) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="actor-1", role=role)


def _build_combined_workbook() -> BytesIO:
    """Build a workbook mimicking the real source file: header metadata rows,
    then a "BALE TYPE" layout block, immediately followed by a "QTY CTNS/PKG"
    layout block — both under one PARTIAL NO, exactly as the real manifest
    export mixes layouts across its own pages."""
    wb = openpyxl.Workbook()
    ws = wb.active

    # Header metadata block (label:value pairs above the tabular data).
    ws.append(["PARTIAL NO: STL377"])
    ws.append(["LOADING DATE", "2026-01-15"])
    ws.append(["PORT", "LAGOS"])
    ws.append(["ARRIVAL DATE", "2026-02-20"])
    ws.append(["DEPARTURE DATE", "2026-01-18"])
    ws.append(["Note: goods on hold — China phone number used"])
    ws.append([])

    # Bale-type layout header + rows.
    ws.append(["DLVY NO.", "NAME", "CONTACT", "ITEM", "BALE NO.", "BALE TYPE", "KG", "OG NO."])
    ws.append(["DN001", "Ngozi Adeyemi (GQL)", "08031234567", "Assorted clothing", "1(3)", "BALE", "45", "OG100"])
    ws.append(["DN002", "Ibrahim Musa", "08037654321", "Shoes", "2", "BALE", "30", "OG101"])

    ws.append([])

    # Qty/ctns layout header + rows (different column order/labels).
    ws.append(["Dlvy No", "Name", "Contact", "Item", "Qty Ctns/Pkg", "Meas.", "Port"])
    ws.append(["DN003", "Chioma Okafor", "08039998888", "Electronics", "17CTNS", "2.5", "LAGOS-ISLAND"])
    on_hold_row = ws.max_row + 1
    ws.append(["DN004", "Yusuf Bello", "08035554444", "China phone item", "3BAGS", "1.2", "LAGOS-TRADE FAIR"])

    # Mark the last row's NAME cell red to simulate an on-hold row.
    ws.cell(row=on_hold_row, column=2).font = Font(color="FFFF0000")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestHeaderMetadataScan:
    def test_scans_partial_no_and_dates(self):
        buf = _build_combined_workbook()
        metadata, rows, errors, total_rows = parse_manifest_xlsx(buf)

        assert metadata["container_number"] == "STL377"
        assert metadata["ship_date"] == "2026-01-15"
        assert metadata["destination"] == "LAGOS"
        assert metadata["estimated_arrival_date"] == "2026-02-20"
        assert metadata["departure_date"] == "2026-01-18"


class TestBothColumnLayouts:
    def test_bale_type_layout_row(self):
        buf = _build_combined_workbook()
        _metadata, rows, errors, _total = parse_manifest_xlsx(buf)

        assert not errors
        bale_row = next(r for r in rows if r["delivery_note_number"] == "DN001")
        assert bale_row["customer_name"] == "Ngozi Adeyemi (GQL)"
        assert bale_row["bale_no"] == "1(3)"
        assert bale_row["package_unit"] == "bale"
        assert bale_row["quantity"] == 1  # no QTY column in this layout -> defaults to 1
        assert bale_row["original_receipt_number"] == "OG100"
        assert bale_row["weight_actual_kg"] == 45.0

    def test_qty_ctns_layout_row(self):
        buf = _build_combined_workbook()
        _metadata, rows, errors, _total = parse_manifest_xlsx(buf)

        assert not errors
        qty_row = next(r for r in rows if r["delivery_note_number"] == "DN003")
        assert qty_row["customer_name"] == "Chioma Okafor"
        assert qty_row["quantity"] == 17
        assert qty_row["package_unit"] == "carton"
        assert qty_row["delivery_zone"] == "LAGOS-ISLAND"
        assert qty_row["cbm"] == 2.5

    def test_bags_quantity_unit_parsed(self):
        buf = _build_combined_workbook()
        _metadata, rows, _errors, _total = parse_manifest_xlsx(buf)

        row = next(r for r in rows if r["delivery_note_number"] == "DN004")
        assert row["quantity"] == 3
        assert row["package_unit"] == "bag"


class TestOnHoldDetection:
    def test_red_font_row_marked_on_hold(self):
        buf = _build_combined_workbook()
        _metadata, rows, _errors, _total = parse_manifest_xlsx(buf)

        held_row = next(r for r in rows if r["delivery_note_number"] == "DN004")
        assert held_row["on_hold"] is True

        not_held_row = next(r for r in rows if r["delivery_note_number"] == "DN003")
        assert not_held_row["on_hold"] is False


class TestQuantityUnitParsing:
    def test_various_formats(self):
        from services.excel.import_manifest import _parse_quantity_unit

        assert _parse_quantity_unit("17CTNS") == (17, "carton")
        assert _parse_quantity_unit("3BAGS") == (3, "bag")
        assert _parse_quantity_unit("1CTN") == (1, "carton")
        assert _parse_quantity_unit(None) == (1, None)
        assert _parse_quantity_unit("") == (1, None)


# ---------------------------------------------------------------------------
# process_manifest_import — service orchestration
# ---------------------------------------------------------------------------


class TestProcessManifestImport:
    def test_auto_creates_new_container_and_customers(self):
        from services.excel import service

        buf = _build_combined_workbook()

        with (
            patch.object(service, "get_storage_provider") as mock_gsp,
            patch.object(service.repo, "find_container_by_number", return_value=None) as mock_find_container,
            patch.object(
                service.repo,
                "create_container",
                return_value={"id": "container-1", "container_number": "STL377"},
            ) as mock_create_container,
            patch.object(service.repo, "get_tenant_destination_country", return_value="Nigeria"),
            patch.object(service.repo, "find_customer_by_phone", return_value=None),
            patch.object(service.repo, "find_customer_by_name", return_value=None),
            patch.object(
                service.repo,
                "create_customer",
                side_effect=[{"id": f"cust-{i}"} for i in range(4)],
            ) as mock_create_customer,
            patch.object(service.repo, "find_packing_list", return_value=None),
            patch.object(service.repo, "get_next_pl_reference", return_value="PL-20260823-001"),
            patch.object(
                service.repo,
                "create_packing_list",
                side_effect=[{"id": f"pl-{i}"} for i in range(4)],
            ),
            patch.object(service.repo, "find_existing_item_by_delivery_note", return_value=None),
            patch.object(service.repo, "get_tenant_short", return_value="ACM"),
            patch.object(service.repo, "get_next_carton_sequence", return_value=1),
            patch.object(service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(service.repo, "get_next_tracking_sequence", return_value=1),
            patch.object(service.repo, "insert_manifest_items") as mock_insert_items,
            patch("services.tenant_management.service.issue_customer_invite") as mock_issue_invite,
        ):
            mock_gsp.return_value.get_object.return_value = buf.getvalue()

            result = service.process_manifest_import(
                TENANT_ID, file_key=f"{TENANT_ID}/imports/test.xlsx", actor_id="actor-1", ctx=_ctx()
            )

        assert result["containers_created"] == 1
        assert result["customers_created"] == 4
        assert result["packing_lists_created"] == 4
        assert result["items_created"] == 4
        assert result["items_skipped_duplicate"] == 0
        mock_find_container.assert_called_once()
        mock_create_container.assert_called_once()
        assert mock_create_customer.call_count == 4
        assert mock_insert_items.call_count == 4
        # An invite is auto-issued for every *newly created* customer only.
        assert mock_issue_invite.call_count == 4

    def test_matches_existing_container_without_overwriting_fields(self):
        """Re-import against an existing container must never call create_container —
        an existing container's hand-edited fields must survive re-import."""
        from services.excel import service

        buf = _build_combined_workbook()
        existing_container = {"id": "container-existing", "container_number": "STL377"}

        with (
            patch.object(service, "get_storage_provider") as mock_gsp,
            patch.object(service.repo, "find_container_by_number", return_value=existing_container),
            patch.object(service.repo, "create_container") as mock_create_container,
            patch.object(service.repo, "get_tenant_destination_country", return_value="Nigeria"),
            patch.object(service.repo, "find_customer_by_phone", return_value={"id": "cust-existing", "name": "X"}),
            patch.object(service.repo, "find_customer_by_name", return_value=None),
            patch.object(service.repo, "create_customer") as mock_create_customer,
            patch.object(service.repo, "find_packing_list", return_value={"id": "pl-existing"}),
            patch.object(service.repo, "get_next_pl_reference", return_value="PL-20260823-001"),
            patch.object(service.repo, "create_packing_list") as mock_create_pl,
            patch.object(service.repo, "find_existing_item_by_delivery_note", return_value=None),
            patch.object(service.repo, "get_tenant_short", return_value="ACM"),
            patch.object(service.repo, "get_next_carton_sequence", return_value=1),
            patch.object(service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(service.repo, "get_next_tracking_sequence", return_value=1),
            patch.object(service.repo, "insert_manifest_items"),
            patch("services.tenant_management.service.issue_customer_invite") as mock_issue_invite,
        ):
            mock_gsp.return_value.get_object.return_value = buf.getvalue()

            result = service.process_manifest_import(
                TENANT_ID, file_key=f"{TENANT_ID}/imports/test.xlsx", actor_id="actor-1", ctx=_ctx()
            )

        assert result["containers_created"] == 0
        mock_create_container.assert_not_called()
        mock_create_pl.assert_not_called()
        # Matched by phone, so no duplicate customer is created.
        mock_create_customer.assert_not_called()
        # Matched (not created) customers never get an invite — they may
        # already have a login.
        mock_issue_invite.assert_not_called()

    def test_dedupe_skips_existing_delivery_note(self):
        from services.excel import service

        buf = _build_combined_workbook()

        with (
            patch.object(service, "get_storage_provider") as mock_gsp,
            patch.object(service.repo, "find_container_by_number", return_value={"id": "container-1"}),
            patch.object(service.repo, "create_container"),
            patch.object(service.repo, "get_tenant_destination_country", return_value="Nigeria"),
            patch.object(service.repo, "find_customer_by_phone", return_value=None),
            patch.object(service.repo, "find_customer_by_name", return_value=None),
            patch.object(service.repo, "create_customer", side_effect=[{"id": f"cust-{i}"} for i in range(4)]),
            patch.object(service.repo, "find_packing_list", return_value=None),
            patch.object(service.repo, "get_next_pl_reference", return_value="PL-20260823-001"),
            patch.object(service.repo, "create_packing_list", side_effect=[{"id": f"pl-{i}"} for i in range(4)]),
            # Every delivery note already exists -> everything is a duplicate.
            patch.object(service.repo, "find_existing_item_by_delivery_note", return_value={"id": "existing-item"}),
            patch.object(service.repo, "get_tenant_short", return_value="ACM"),
            patch.object(service.repo, "get_next_carton_sequence", return_value=1),
            patch.object(service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(service.repo, "get_next_tracking_sequence", return_value=1),
            patch.object(service.repo, "insert_manifest_items") as mock_insert_items,
            patch("services.tenant_management.service.issue_customer_invite"),
        ):
            mock_gsp.return_value.get_object.return_value = buf.getvalue()

            result = service.process_manifest_import(
                TENANT_ID, file_key=f"{TENANT_ID}/imports/test.xlsx", actor_id="actor-1", ctx=_ctx()
            )

        assert result["items_created"] == 0
        assert result["items_skipped_duplicate"] == 4
        mock_insert_items.assert_not_called()

    def test_rejects_file_key_outside_tenant_prefix(self):
        import pytest

        from services.excel import service
        from shared.exceptions import ValidationError

        with pytest.raises(ValidationError):
            service.process_manifest_import(TENANT_ID, file_key="other-tenant/imports/test.xlsx", actor_id="actor-1", ctx=_ctx())


def _build_real_shape_workbook() -> BytesIO:
    """Reproduce the exact structural quirks of a real STL409 export.

    Every quirk here broke the parser when the genuine file was first run
    through it (0 of 87 rows parsed): two sheets instead of stacked layouts,
    metadata values several columns right of their labels, the "ARRIVEL DATE"
    misspelling, a two-row header, "DLVY  NO." double-spaced, compound
    quantity cells, and TOTAL/CLOSE CONTAINER footer rows.
    """
    wb = openpyxl.Workbook()

    bales = wb.active
    bales.title = "Master-BALES"
    bales.cell(row=2, column=2, value="PARTIAL NO:")
    bales.cell(row=2, column=5, value="STL409")  # value 3 cols right
    bales.cell(row=3, column=3, value="LOADING DATE:")
    bales.cell(row=3, column=5, value="2026-07-04 00:00:00")
    bales.cell(row=3, column=7, value="DEPARTURE DATE:")
    bales.cell(row=3, column=10, value="2026-07-21 00:00:00")
    bales.cell(row=4, column=4, value="PORT:")
    bales.cell(row=4, column=5, value="LAGOS")
    bales.cell(row=4, column=7, value="ARRIVEL DATE:")  # misspelled in source
    bales.cell(row=4, column=10, value="2026-08-17 00:00:00")
    for col, head in enumerate(
        ["CODE", "PORT", "NAME", "CONTACT", "ITEM", "DLVY  NO.", "OG NO.", "BALE TYPE", "BALE NO.", "MEAS.", "KG"], start=2
    ):
        bales.cell(row=8, column=col, value=head)
    bales.cell(row=9, column=11, value="(CBM)")  # two-row header
    for col, val in enumerate(
        [1, "LAGOS", "CHRIS(GQL)", "081-62009462", "WOVEN FABRIC", "0079259", "OG1", "BIG BALE", "19", 1, 760], start=2
    ):
        bales.cell(row=10, column=col, value=val)
    bales.cell(row=11, column=3, value="TOTAL:")  # footer, not data
    bales.cell(row=11, column=10, value="CBM:")
    bales.cell(row=12, column=3, value="CLOSE CONTAINER ITEM:")

    ctn = wb.create_sheet("Master-CTN GOOD")
    ctn.cell(row=2, column=2, value="PARTIAL NO:")
    ctn.cell(row=2, column=5, value="STL409")
    for col, head in enumerate(["CODE", "PORT", "NAME", "CONTACT", "ITEM", "DELIVERY NOTE NO.", "QTY", "MEAS."], start=2):
        ctn.cell(row=8, column=col, value=head)
    ctn.cell(row=9, column=8, value="CTNS/PKG")
    ctn.cell(row=9, column=9, value="(CBM)")
    for col, val in enumerate(
        [1, "LAGOS", "CHINA BEST CAR", "090-10908939", "TRICYCLE", "0079187", "1PALLET(61items)", 3.4], start=2
    ):
        ctn.cell(row=10, column=col, value=val)
    for col, val in enumerate([2, "LAGOS", "DEFRED", "080-68390609", "HANDBAG", "0068631", "3bags2ctns1pallet", 2.8], start=2):
        ctn.cell(row=11, column=col, value=val)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestRealExportShape:
    """Regression tests pinned to the genuine STL409 export's structure."""

    def test_reads_every_sheet_not_just_the_active_one(self):
        _meta, rows, _errors, _total = parse_manifest_xlsx(_build_real_shape_workbook())
        sheets = {r["sheet_name"] for r in rows}
        assert sheets == {"Master-BALES", "Master-CTN GOOD"}
        assert len(rows) == 3

    def test_metadata_value_columns_right_of_label_and_misspelled_arrival(self):
        meta, _rows, _errors, _total = parse_manifest_xlsx(_build_real_shape_workbook())
        assert meta["container_number"] == "STL409"
        assert meta["destination"] == "LAGOS"  # not the header's "NAME"
        assert meta["estimated_arrival_date"].startswith("2026-08-17")
        assert meta["departure_date"].startswith("2026-07-21")

    def test_two_row_header_does_not_clobber_the_column_map(self):
        _meta, rows, errors, _total = parse_manifest_xlsx(_build_real_shape_workbook())
        assert errors == []
        assert all(r["customer_name"] for r in rows)

    def test_double_spaced_alias_and_bale_type_normalisation(self):
        _meta, rows, _errors, _total = parse_manifest_xlsx(_build_real_shape_workbook())
        bale = next(r for r in rows if r["sheet_name"] == "Master-BALES")
        assert bale["delivery_note_number"] == "0079259"  # "DLVY  NO."
        assert bale["package_unit"] == "bale"
        assert bale["bale_type"] == "BIG BALE"

    def test_compound_and_annotated_quantities(self):
        _meta, rows, _errors, _total = parse_manifest_xlsx(_build_real_shape_workbook())
        pallet = next(r for r in rows if r["customer_name"] == "CHINA BEST CAR")
        assert (pallet["quantity"], pallet["package_unit"]) == (1, "pallet")
        assert pallet["quantity_raw"] == "1PALLET(61items)"
        mixed = next(r for r in rows if r["customer_name"] == "DEFRED")
        assert (mixed["quantity"], mixed["package_unit"]) == (6, "mixed")
        assert mixed["quantity_raw"] == "3bags2ctns1pallet"

    def test_total_and_footer_rows_are_skipped_not_reported_as_errors(self):
        _meta, rows, errors, total = parse_manifest_xlsx(_build_real_shape_workbook())
        assert errors == []
        assert total == len(rows) == 3


class TestContainerMetadataDates:
    """Excel stores header dates as real date cells, not text."""

    def test_native_excel_date_cells_survive_to_a_parsed_date(self):
        from datetime import date as _date
        from datetime import datetime as _datetime

        from services.excel.service import _parse_metadata_date

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.cell(row=2, column=2, value="PARTIAL NO:")
        ws.cell(row=2, column=5, value="STL409")
        ws.cell(row=3, column=3, value="LOADING DATE:")
        ws.cell(row=3, column=5, value=_datetime(2026, 7, 4))  # real date cell
        for col, head in enumerate(["NAME", "CONTACT", "ITEM", "QTY"], start=2):
            ws.cell(row=8, column=col, value=head)
        ws.cell(row=9, column=2, value="ACME")
        ws.cell(row=9, column=3, value="080-1")
        ws.cell(row=9, column=4, value="GOODS")
        ws.cell(row=9, column=5, value="2CTNS")
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)

        meta, _rows, _errors, _total = parse_manifest_xlsx(buf)
        # Regression: str()-ing the cell produced "2026-07-04 00:00:00", which
        # matched no format, so every container date imported as NULL.
        assert _parse_metadata_date(meta["ship_date"]) == _date(2026, 7, 4)

    def test_parses_the_printed_manifest_date_style(self):
        from datetime import date as _date

        from services.excel.service import _parse_metadata_date

        assert _parse_metadata_date("21-May-2026") == _date(2026, 5, 21)
        assert _parse_metadata_date("2026-07-04 00:00:00") == _date(2026, 7, 4)
        assert _parse_metadata_date(None) is None
        assert _parse_metadata_date("") is None
        assert _parse_metadata_date("not a date") is None
