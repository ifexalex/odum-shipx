"""Generate billing .xlsx (single-sheet, 14 columns) per spec §7.4."""

import contextlib
from io import BytesIO
from typing import Any

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ._tables import neutralise_formulas


def _autosize_columns(ws: Worksheet) -> None:
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            with contextlib.suppress(Exception):
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_length + 2, 30)


_HEADERS = [
    "Customer Name",  # A
    "Total CBM",  # B
    "CBM Rate (USD)",  # C
    "Dollar Rate (NGN)",  # D
    "Subtotal (USD)",  # E
    "Subtotal (NGN)",  # F
    "Misc Fees (NGN)",  # G
    "Carryover (NGN)",  # H
    "Adjustments (NGN)",  # I
    "Storage Fees (NGN)",  # J
    "Total Due (NGN)",  # K
    "Total Paid (NGN)",  # L
    "Outstanding (NGN)",  # M
    "Payment Status",  # N
]


def _billing_row(b: dict[str, Any]) -> list[Any]:
    """Convert a billing dict (with aggregated fields) to a 14-column list."""
    total_due = float(b.get("total_ngn") or 0)
    total_paid = float(b.get("amount_paid_ngn") or 0)
    outstanding = total_due - total_paid
    return [
        b.get("customer_name") or "",
        float(b.get("total_cbm") or 0),
        float(b.get("cbm_rate_usd") or 0),
        float(b.get("exchange_rate_ngn") or 0),
        float(b.get("subtotal_usd") or 0),
        float(b.get("subtotal_ngn") or 0),
        float(b.get("misc_charges_ngn") or 0),
        float(b.get("carryover_ngn") or 0),
        float(b.get("adjustments_ngn") or 0),
        float(b.get("storage_fees_ngn") or 0),
        total_due,
        total_paid,
        outstanding,
        b.get("status") or "",
    ]


def generate_billing_xlsx(billing_rows: list[dict[str, Any]]) -> BytesIO:
    """Return a BytesIO buffer containing the billing workbook.

    billing_rows may contain one row (single billing export) or many
    (container-level export — one row per customer).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Billing"

    for col, header in enumerate(_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    for row_idx, b in enumerate(billing_rows, 2):
        for col, value in enumerate(_billing_row(b), 1):
            ws.cell(row=row_idx, column=col, value=value)

    ws.auto_filter.ref = f"A1:N{len(billing_rows) + 1}"
    _autosize_columns(ws)

    buf = BytesIO()
    neutralise_formulas(wb)
    wb.save(buf)
    buf.seek(0)
    return buf
