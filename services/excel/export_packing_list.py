"""Generate packing list .xlsx (2-sheet workbook) per spec §7.1."""

import contextlib
from datetime import datetime
from io import BytesIO
from typing import Any

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


def _autosize_columns(ws: Worksheet) -> None:
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            with contextlib.suppress(Exception):
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_length + 2, 40)


def generate_packing_list_xlsx(
    tenant_display_name: str,
    container_number: str,
    customer_name: str,
    items: list[dict[str, Any]],
) -> BytesIO:
    """Return a BytesIO buffer containing the packing list workbook."""
    wb = openpyxl.Workbook()

    # ------------------------------------------------------------------
    # Sheet 1: Packing List
    # ------------------------------------------------------------------
    ws = wb.active
    ws.title = "Packing List"

    headers = [
        "Carton Tag",
        "Tracking Code",
        "Description",
        "Weight (Dispatch) kg",
        "Weight (Actual) kg",
        "Length (cm)",
        "Width (cm)",
        "Height (cm)",
        "CBM",
        "Received Date",
    ]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    for row_idx, item in enumerate(items, 2):
        ws.cell(row=row_idx, column=1, value=item.get("carton_tag") or "")
        ws.cell(row=row_idx, column=2, value=item.get("tracking_code") or "")
        ws.cell(row=row_idx, column=3, value=item.get("description") or "")
        ws.cell(row=row_idx, column=4, value=float(item.get("weight_dispatch_kg") or 0))
        ws.cell(row=row_idx, column=5, value=float(item.get("weight_actual_kg") or 0))
        ws.cell(row=row_idx, column=6, value=float(item.get("length_cm") or 0))
        ws.cell(row=row_idx, column=7, value=float(item.get("width_cm") or 0))
        ws.cell(row=row_idx, column=8, value=float(item.get("height_cm") or 0))
        ws.cell(row=row_idx, column=9, value=float(item.get("cbm") or 0))
        ws.cell(row=row_idx, column=10, value=str(item.get("received_date") or ""))

    # Totals row
    if items:
        total_row = len(items) + 2
        totals_cell = ws.cell(row=total_row, column=3, value="TOTALS")
        totals_cell.font = Font(bold=True)
        ws.cell(row=total_row, column=4, value=sum(float(i.get("weight_dispatch_kg") or 0) for i in items))
        ws.cell(row=total_row, column=5, value=sum(float(i.get("weight_actual_kg") or 0) for i in items))
        ws.cell(row=total_row, column=9, value=round(sum(float(i.get("cbm") or 0) for i in items), 6))

    ws.auto_filter.ref = f"A1:J{len(items) + 1}"
    _autosize_columns(ws)

    # ------------------------------------------------------------------
    # Sheet 2: Summary
    # ------------------------------------------------------------------
    ws2 = wb.create_sheet("Summary")
    summary_rows = [
        ("Company Name", tenant_display_name),
        ("Container Number", container_number),
        ("Customer Name", customer_name),
        ("Total Cartons", len(items)),
        ("Total Weight (kg)", round(sum(float(i.get("weight_actual_kg") or 0) for i in items), 3)),
        ("Total CBM", round(sum(float(i.get("cbm") or 0) for i in items), 6)),
        ("Generated Date", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")),
    ]
    for row_idx, (label, value) in enumerate(summary_rows, 1):
        ws2.cell(row=row_idx, column=1, value=label).font = Font(bold=True)
        ws2.cell(row=row_idx, column=2, value=value)
    _autosize_columns(ws2)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
