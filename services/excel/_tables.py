"""Tabular exports of list screens: a column spec and an .xlsx / .csv writer for it.

The writers neutralise spreadsheet formulas. Customer names, vessel names and the like are typed by customers and
staff, and a cell that begins with `=`, `+`, `-` or `@` runs as a formula when the file is opened in Excel (CWE-1236,
"CSV injection"). Text is therefore always written as text, never as a formula.
"""

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Literal

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ColumnKind = Literal["text", "integer", "number", "money", "date", "datetime"]

# Characters that make a spreadsheet treat a cell as a formula (OWASP, "CSV Injection").
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")
_LEADING_FORMULA_CHARS = ("=", "+", "-", "@")
_ILLEGAL_SHEET_CHARS_RE = re.compile(r"[\\/*?:\[\]]")
_MAX_COLUMN_WIDTH = 40
_XLSX_FORMATS: dict[str, str] = {
    "integer": "#,##0",
    "number": "#,##0.000",
    "money": "#,##0.00",
    "date": "yyyy-mm-dd",
    "datetime": "yyyy-mm-dd hh:mm",
}


@dataclass(frozen=True)
class Column:
    """One exported column: which row key it reads, its header, and how its values are written."""

    key: str
    header: str
    kind: ColumnKind = "text"


def _as_utc(value: datetime) -> datetime:
    """A naive UTC datetime: spreadsheets have no time zones, so the header says "(UTC)" instead."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _xlsx_value(kind: ColumnKind, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if kind == "integer":
        return int(raw)
    if kind in ("number", "money"):
        return float(raw)
    if kind == "date":
        return raw.date() if isinstance(raw, datetime) else raw
    if kind == "datetime":
        return _as_utc(raw) if isinstance(raw, datetime) else raw
    return str(raw)


def _csv_value(kind: ColumnKind, raw: Any) -> str:
    if raw is None:
        return ""
    if kind == "integer":
        return str(int(raw))
    if kind in ("number", "money"):
        return str(raw if isinstance(raw, Decimal) else Decimal(str(raw)))
    if kind == "date":
        if isinstance(raw, datetime):  # before `date`: a datetime is a date
            return raw.date().isoformat()
        return raw.isoformat() if isinstance(raw, date) else str(raw)
    if kind == "datetime":
        return _as_utc(raw).strftime("%Y-%m-%d %H:%M") if isinstance(raw, datetime) else str(raw)
    text = str(raw)
    if text.startswith(_FORMULA_PREFIXES) or text.lstrip(" \t\r\n").startswith(_LEADING_FORMULA_CHARS):
        return f"'{text}"
    return text


def neutralise_formulas(workbook: openpyxl.Workbook) -> None:
    """Turn every formula cell in `workbook` back into the text it was written as.

    openpyxl stores any string that starts with `=` as a formula. None of this service's exports writes a formula on
    purpose, so a formula cell is always typed-in text (a customer's name, a goods description) that would otherwise run
    when the file is opened. Call this just before saving a workbook built cell by cell.
    """
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"


def csv_safe(value: Any) -> Any:
    """`value` as it may be written to a csv cell.

    Text that a spreadsheet would read as a formula gets a leading apostrophe. Numbers, dates and None are returned as
    they are, so a negative amount held as a number is not mistaken for a formula.
    """
    if isinstance(value, str) and (
        value.startswith(_FORMULA_PREFIXES) or value.lstrip(" \t\r\n").startswith(_LEADING_FORMULA_CHARS)
    ):
        return f"'{value}"
    return value


def build_xlsx(sheet_title: str, columns: list[Column], rows: Iterable[dict[str, Any]]) -> BytesIO:
    """A single-sheet workbook: bold frozen header, a filter on every column, widths fitted to the content."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    safe_title = _ILLEGAL_SHEET_CHARS_RE.sub("_", str(sheet_title or "Sheet")).strip() or "Sheet"
    sheet.title = safe_title[:31]

    for index, column in enumerate(columns, 1):
        cell = sheet.cell(row=1, column=index, value=column.header)
        cell.font = Font(bold=True)

    widths = [len(column.header) for column in columns]
    count = 0
    for row_index, row in enumerate(rows, 2):
        count += 1
        for index, column in enumerate(columns, 1):
            value = _xlsx_value(column.kind, row.get(column.key))
            cell = sheet.cell(row=row_index, column=index, value=value)
            if column.kind == "text" and isinstance(value, str):
                cell.data_type = "s"  # openpyxl would otherwise turn a leading "=" into a formula
            elif column.kind != "text":
                cell.number_format = _XLSX_FORMATS[column.kind]
            if value is not None:
                widths[index - 1] = max(widths[index - 1], len(str(value)))

    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = min(width + 2, _MAX_COLUMN_WIDTH)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{count + 1}"

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def build_csv(columns: list[Column], rows: Iterable[dict[str, Any]]) -> BytesIO:
    """UTF-8 with a byte-order mark (so Excel reads non-ASCII names correctly) and CRLF line ends."""
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\r\n")
    writer.writerow([_csv_value("text", column.header) for column in columns])
    for row in rows:
        writer.writerow([_csv_value(column.kind, row.get(column.key)) for column in columns])
    return BytesIO(text.getvalue().encode("utf-8-sig"))
