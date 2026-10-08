"""Shared parsing helpers for the Excel import flows.

Extracted from `import_packing_list.py` so both the exact-header packing-list
importer and the flexible manifest importer (`import_manifest.py`) share one
implementation instead of duplicating parsing logic.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def parse_positive_decimal(value: Any, field: str, row: int) -> tuple[Decimal | None, dict[str, Any] | None]:
    """Parse a positive decimal cell value.

    Returns (Decimal, None) on success, (None, None) for a blank cell, or
    (None, error_dict) on failure.
    """
    if value is None or str(value).strip() == "":
        return None, None
    try:
        d = Decimal(str(value).strip())
        if d < 0:
            return None, {"row": row, "field": field, "value": str(value), "error": "Must be a positive number"}
        return d, None
    except InvalidOperation:
        return None, {"row": row, "field": field, "value": str(value), "error": "Invalid number"}


def parse_date(value: Any, row: int) -> tuple[date | None, dict[str, Any] | None]:
    """Parse a date cell value, defaulting to today when blank."""
    if value is None or str(value).strip() == "":
        return date.today(), None
    if isinstance(value, date):
        return value, None
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date(), None
        except ValueError:
            pass
    return None, {"row": row, "field": "Received Date", "value": raw, "error": "Invalid date format (use YYYY-MM-DD)"}


def compute_cbm(length: Decimal | None, width: Decimal | None, height: Decimal | None) -> Decimal:
    """Compute CBM (cubic metres) from length/width/height in centimetres."""
    if length is not None and width is not None and height is not None:
        return (length * width * height) / Decimal("1000000")
    return Decimal("0")
