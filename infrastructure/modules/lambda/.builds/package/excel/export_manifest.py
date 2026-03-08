"""Generate manifest .xlsx (2-sheet workbook) per spec §7.2."""
from io import BytesIO

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


def _autosize_columns(ws) -> None:
    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 40)


def generate_manifest_xlsx(
    tenant_display_name: str,
    container_number: str,
    customer_rows: list[dict],
    all_items: list[dict],
) -> BytesIO:
    """Return a BytesIO buffer containing the manifest workbook.

    Args:
        tenant_display_name: Company name for metadata.
        container_number: Container number.
        customer_rows: List of per-customer summary dicts with keys:
            customer_name, carton_count, total_weight_kg, total_cbm, carton_tags.
        all_items: Flat list of all packing_list_item rows across all customers.
    """
    wb = openpyxl.Workbook()

    # ------------------------------------------------------------------
    # Sheet 1: Manifest Summary
    # ------------------------------------------------------------------
    ws = wb.active
    ws.title = "Manifest Summary"

    headers = ["#", "Customer Name", "Carton Count", "Total Weight (kg)", "Total CBM", "Carton Tags"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    for row_idx, cust in enumerate(customer_rows, 2):
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        ws.cell(row=row_idx, column=2, value=cust.get("customer_name") or "")
        ws.cell(row=row_idx, column=3, value=cust.get("carton_count") or 0)
        ws.cell(row=row_idx, column=4, value=float(cust.get("total_weight_kg") or 0))
        ws.cell(row=row_idx, column=5, value=round(float(cust.get("total_cbm") or 0), 6))
        ws.cell(row=row_idx, column=6, value=cust.get("carton_tags") or "")

    ws.auto_filter.ref = f"A1:F{len(customer_rows) + 1}"
    _autosize_columns(ws)

    # ------------------------------------------------------------------
    # Sheet 2: All Items (matches packing list export Sheet 1 columns)
    # ------------------------------------------------------------------
    ws2 = wb.create_sheet("All Items")
    item_headers = [
        "Carton Tag", "Tracking Code", "Description",
        "Weight (Dispatch) kg", "Weight (Actual) kg",
        "Length (cm)", "Width (cm)", "Height (cm)",
        "CBM", "Received Date",
    ]
    for col, header in enumerate(item_headers, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    for row_idx, item in enumerate(all_items, 2):
        ws2.cell(row=row_idx, column=1, value=item.get("carton_tag") or "")
        ws2.cell(row=row_idx, column=2, value=item.get("tracking_code") or "")
        ws2.cell(row=row_idx, column=3, value=item.get("description") or "")
        ws2.cell(row=row_idx, column=4, value=float(item.get("weight_dispatch_kg") or 0))
        ws2.cell(row=row_idx, column=5, value=float(item.get("weight_actual_kg") or 0))
        ws2.cell(row=row_idx, column=6, value=float(item.get("length_cm") or 0))
        ws2.cell(row=row_idx, column=7, value=float(item.get("width_cm") or 0))
        ws2.cell(row=row_idx, column=8, value=float(item.get("height_cm") or 0))
        ws2.cell(row=row_idx, column=9, value=float(item.get("cbm") or 0))
        ws2.cell(row=row_idx, column=10, value=str(item.get("received_date") or ""))

    ws2.auto_filter.ref = f"A1:J{len(all_items) + 1}"
    _autosize_columns(ws2)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
