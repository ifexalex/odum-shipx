"""Parse and validate a packing list .xlsx for import per spec §7.3."""
from collections import defaultdict
from io import BytesIO
from typing import Any

import openpyxl

from shared.exceptions import ValidationError

from ._import_helpers import compute_cbm as _compute_cbm
from ._import_helpers import parse_date as _parse_date
from ._import_helpers import parse_positive_decimal as _parse_positive_decimal

_EXPECTED_HEADERS = [
    "customer name",
    "description",
    "weight dispatch (kg)",
    "weight actual (kg)",
    "length (cm)",
    "width (cm)",
    "height (cm)",
    "received date",
]


def parse_packing_list_xlsx(
    file_buffer: BytesIO,
    customers_by_name: dict[str, Any],  # {lowercase_name: customer_id}
) -> tuple[dict[tuple[Any, ...], list[dict[str, Any]]], list[dict[str, Any]], int]:
    """Parse xlsx and return (items_by_group, errors, total_data_rows).

    items_by_group: {(customer_id, received_date): [item_dict, ...]}
    Each item_dict has keys matching packing_list_item columns (no carton_tag/tracking_code yet).
    """
    wb = openpyxl.load_workbook(file_buffer, data_only=True)
    ws = wb.active

    # 1. Validate header row (case-insensitive)
    actual_headers = [str(ws.cell(row=1, column=c).value or "").strip().lower() for c in range(1, 9)]
    if actual_headers != _EXPECTED_HEADERS:
        raise ValidationError(
            "Header row does not match expected format",
            field_errors={"headers": f"Expected {_EXPECTED_HEADERS}, got {actual_headers}"},
        )

    errors: list[dict[str, Any]] = []
    items_by_group: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    total_rows = 0

    for row_idx in range(2, ws.max_row + 1):
        # Skip completely empty rows
        row_values = [ws.cell(row=row_idx, column=c).value for c in range(1, 9)]
        if all(v is None or str(v).strip() == "" for v in row_values):
            continue
        total_rows += 1

        # a. Customer Name (required)
        raw_customer = str(ws.cell(row=row_idx, column=1).value or "").strip()
        customer_id = customers_by_name.get(raw_customer.lower())
        if not customer_id:
            errors.append(
                {
                    "row": row_idx,
                    "field": "Customer Name",
                    "value": raw_customer,
                    "error": "Customer not found",
                }
            )
            continue

        # b. Description (required)
        description = str(ws.cell(row=row_idx, column=2).value or "").strip()
        if not description:
            errors.append(
                {
                    "row": row_idx,
                    "field": "Description",
                    "value": "",
                    "error": "Description is required",
                }
            )
            continue

        # c. Numeric fields (optional, positive)
        row_errors: list[dict[str, Any]] = []
        weight_dispatch, e = _parse_positive_decimal(ws.cell(row=row_idx, column=3).value, "Weight Dispatch (kg)", row_idx)
        if e:
            row_errors.append(e)
        weight_actual, e = _parse_positive_decimal(ws.cell(row=row_idx, column=4).value, "Weight Actual (kg)", row_idx)
        if e:
            row_errors.append(e)
        length_cm, e = _parse_positive_decimal(ws.cell(row=row_idx, column=5).value, "Length (cm)", row_idx)
        if e:
            row_errors.append(e)
        width_cm, e = _parse_positive_decimal(ws.cell(row=row_idx, column=6).value, "Width (cm)", row_idx)
        if e:
            row_errors.append(e)
        height_cm, e = _parse_positive_decimal(ws.cell(row=row_idx, column=7).value, "Height (cm)", row_idx)
        if e:
            row_errors.append(e)

        if row_errors:
            errors.extend(row_errors)
            continue

        # d. Received date (optional, defaults to today)
        received_date, e = _parse_date(ws.cell(row=row_idx, column=8).value, row_idx)
        if e:
            errors.append(e)
            continue

        cbm = _compute_cbm(length_cm, width_cm, height_cm)

        item: dict[str, Any] = {
            "description": description,
            "weight_dispatch_kg": float(weight_dispatch) if weight_dispatch is not None else None,
            "weight_actual_kg": float(weight_actual) if weight_actual is not None else None,
            "length_cm": float(length_cm) if length_cm is not None else None,
            "width_cm": float(width_cm) if width_cm is not None else None,
            "height_cm": float(height_cm) if height_cm is not None else None,
            "cbm": float(cbm),
            "received_date": received_date,
        }
        items_by_group[(customer_id, received_date)].append(item)

    return dict(items_by_group), errors, total_rows
