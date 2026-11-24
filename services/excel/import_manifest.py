"""Parse a China-side freight-forwarder manifest .xlsx for flexible import.

Unlike `import_packing_list.py` (exact 8-column header, pre-existing
container/customers required), this parser tolerates the real-world shape of
manifest exports: container-level metadata (PARTIAL NO, LOADING DATE, PORT,
ARRIVAL DATE, DEPARTURE DATE) sitting as label:value pairs in rows *above*
the tabular data, and two different column layouts for the tabular rows
themselves (bale-type goods vs. carton/bag goods) — sometimes within the
same source file.

See `19_excel_import_export.md` §"Manifest Import" for the full field
reference (header-alias table, quantity/unit parsing rules, dedupe
behaviour).
"""

import re
from datetime import date, datetime
from io import BytesIO
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from ._import_helpers import parse_positive_decimal

# ---------------------------------------------------------------------------
# Header-metadata scan (container-level fields above the tabular data)
# ---------------------------------------------------------------------------

# label (lowercased, stripped) -> container metadata field
_METADATA_LABEL_ALIASES: dict[str, str] = {
    "partial no": "container_number",
    "partial no.": "container_number",
    "loading date": "ship_date",
    "port": "destination",
    "arrival date": "estimated_arrival_date",
    # Real exports misspell this ("ARRIVEL DATE:") — matched verbatim rather
    # than fuzzily, so we only ever accept spellings actually seen in the wild.
    "arrivel date": "estimated_arrival_date",
    "departure date": "departure_date",
}

_METADATA_SCAN_ROWS = 10
_METADATA_SCAN_COLS = 12

# ---------------------------------------------------------------------------
# Column-header alias table (flexible resolution across observed layouts)
# ---------------------------------------------------------------------------

# alias (lowercased, stripped) -> canonical field name
_COLUMN_ALIASES: dict[str, str] = {
    "dlvy no.": "delivery_note_number",
    "dlvy no": "delivery_note_number",
    "delivery note no.": "delivery_note_number",
    "delivery note no": "delivery_note_number",
    "name": "customer_name",
    "contact": "customer_phone",
    "item": "description",
    "description": "description",
    "qty": "quantity_raw",
    "ctns/pkg": "quantity_raw",
    "qty ctns/pkg": "quantity_raw",
    "meas.": "cbm",
    "meas": "cbm",
    "cbm": "cbm",
    "kg": "weight_actual_kg",
    "weight(kg)": "weight_actual_kg",
    "bale no.": "bale_no",
    "bale no": "bale_no",
    "bale type": "package_unit",
    "port": "delivery_zone",
    "og no.": "original_receipt_number",
    "og no": "original_receipt_number",
}

# Columns that, once any one of them is seen in a candidate header row,
# confirm that row is the real column-header row (as opposed to noise).
_HEADER_ROW_SIGNAL_FIELDS = {"delivery_note_number", "customer_name", "description", "quantity_raw"}

# Minimum recognized columns for a row to count as a primary header row (see
# _match_header_row) — keeps two-row headers' unit sub-row from hijacking it.
_MIN_HEADER_COLUMNS = 3

# Non-data rows that sit inside the tabular block: the second line of a two-row
# header, and the sheet's own summary/footer rows. They carry no customer, so
# without this they surfaced as bogus "Customer name is required" errors —
# telling staff records had failed when nothing was actually wrong.
_STRUCTURAL_ROW_MARKERS = frozenset(
    {
        "total",
        "close container item",
        "ctns/pkg",
        "ctns/pkgs",
        "(cbm)",
        "cbm",
        "bales",
        "kg",
    }
)

# Matches each "<count><unit>" run inside a quantity cell. Real cells are not
# always a single clean pair: "1PALLET(61items)" carries a parenthetical item
# count, and "3bags2ctns1pallet" packs three units into one cell.
_QUANTITY_UNIT_RE = re.compile(r"(\d+)\s*([A-Za-z]+)")

# Bale-type values from the BALE TYPE column. The trade distinguishes big from
# long bales, so the verbatim type is kept on the row (bale_type) while the
# canonical unit collapses to "bale" — otherwise "count all bales" queries miss
# rows and package_unit mixes units with types.
_BALE_TYPE_UNITS: dict[str, str] = {
    "big bale": "bale",
    "long bale": "bale",
    "small bale": "bale",
}

_UNIT_NORMALIZATION: dict[str, str] = {
    "ctn": "carton",
    "ctns": "carton",
    "carton": "carton",
    "cartons": "carton",
    "bag": "bag",
    "bags": "bag",
    "bale": "bale",
    "bales": "bale",
    "pkg": "package",
    "pkgs": "package",
    "pallet": "pallet",
    "pallets": "pallet",
    "item": "item",
    "items": "item",
}

# Units that only ever appear as a parenthetical annotation of what is *inside*
# a package ("1PALLET(61items)") — never the package unit itself.
_ANNOTATION_UNITS = frozenset({"item"})

_RED_RGB_PREFIXES = ("FFFF0000", "00FF0000")  # openpyxl ARGB hex for pure red
_MAX_SHEET_ROWS = 20_000


def _clean_id_str(raw: Any) -> str | None:
    """Convert an ID/phone/bale cell value to string, stripping Excel's trailing '.0' on integers."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    text = str(raw).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _cell_value(ws: Worksheet, row: int, col: int) -> Any:
    return ws.cell(row=row, column=col).value


def _norm(raw: Any) -> str:
    """Lowercase, strip, and collapse internal whitespace.

    Real headers are hand-typed and inconsistently spaced ("DLVY  NO." with a
    double space), so every alias lookup goes through this.
    """
    if raw is None:
        return ""
    return re.sub(r"\s+", " ", str(raw).strip().lower())


def _scan_header_metadata(ws: Worksheet, stop_row: int | None = None) -> dict[str, Any]:
    """Scan the rows above the tabular data for label:value container metadata.

    Real source documents put fields like "PARTIAL NO: STL377" or
    "LOADING DATE  2026-01-15" as label/value pairs above the tabular data
    rather than as spreadsheet columns.

    `stop_row` is the column-header row; scanning stops *before* it. Without
    that bound the scan runs into the header row itself and mistakes its
    "PORT" column for the container-level "PORT:" label, taking the adjacent
    header cell ("NAME") as the destination.

    The value is not necessarily in the cell immediately right of the label —
    real exports leave gaps or merge cells, putting "PARTIAL NO:" in column 2
    and "STL409" in column 5 — so this scans forward for the first non-empty
    cell that is not itself another known label.
    """
    metadata: dict[str, Any] = {}
    limit = ws.max_row if stop_row is None else stop_row - 1
    max_row = min(limit, _METADATA_SCAN_ROWS)
    max_col = min(ws.max_column, _METADATA_SCAN_COLS)

    def _lookahead(row: int, start_col: int) -> Any:
        """First meaningful value right of a label cell.

        Date cells are returned as the native datetime openpyxl gives us, not
        stringified: Excel stores these as real dates, and str() renders them
        "2026-07-04 00:00:00", a shape no date format matched — so every
        container date silently imported as NULL.
        """
        for probe in range(start_col + 1, max_col + 1):
            raw = _cell_value(ws, row, probe)
            if raw is None or not str(raw).strip():
                continue
            if _norm(raw).rstrip(":") in _METADATA_LABEL_ALIASES:
                return None  # ran into the next label — this one has no value
            return raw if isinstance(raw, datetime | date) else str(raw).strip()
        return None

    for row in range(1, max_row + 1):
        for col in range(1, max_col + 1):
            raw = _cell_value(ws, row, col)
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue

            # Form 1: "LABEL: value" in a single cell.
            if ":" in text:
                label_part, _, value_part = text.partition(":")
                field = _METADATA_LABEL_ALIASES.get(_norm(label_part))
                if field:
                    value = value_part.strip() or _lookahead(row, col)
                    if value:
                        metadata.setdefault(field, value)
                    continue

            # Form 2: bare label cell, value somewhere to the right.
            field = _METADATA_LABEL_ALIASES.get(_norm(text))
            if field:
                value = _lookahead(row, col)
                if value:
                    metadata.setdefault(field, value)

    return metadata


def _match_header_row(ws: Worksheet, row: int) -> dict[int, str] | None:
    """Return {col: field} if `row` looks like a *primary* column-header row.

    Requires both a strong-signal field and at least `_MIN_HEADER_COLUMNS`
    recognized columns. The column count is what distinguishes a real header
    row from a sub-header: real exports use a two-row header where row 2 holds
    only unit qualifiers ("CTNS/PKG" under "QTY", "(CBM)" under "MEAS."). That
    sub-header matches a signal field on its own, so without the minimum-column
    rule it was accepted as a fresh header and *replaced* the real map with a
    single-column one — dropping customer_name and failing every data row.
    """
    col_map: dict[int, str] = {}
    for col in range(1, ws.max_column + 1):
        field = _COLUMN_ALIASES.get(_norm(_cell_value(ws, row, col)))
        if field:
            col_map[col] = field
    if len(col_map) >= _MIN_HEADER_COLUMNS and (set(col_map.values()) & _HEADER_ROW_SIGNAL_FIELDS):
        return col_map
    return None


def _resolve_header_row(ws: Worksheet) -> tuple[int, dict[int, str]]:
    """Locate the *first* column-header row and return (row_index, {col: field}).

    Scans rows after the metadata block. The real source file switches
    column layout again further down (a second "page" with its own header
    row) — that switch is handled separately during the row-by-row scan in
    `parse_manifest_xlsx`, which re-checks every row against
    `_match_header_row` and swaps in a new column map when one matches,
    rather than assuming one static header row for the whole sheet.
    """
    max_row = min(ws.max_row, _METADATA_SCAN_ROWS + 5)
    for row in range(1, max_row + 1):
        col_map = _match_header_row(ws, row)
        if col_map:
            return row, col_map

    raise ValueError("Could not locate a recognizable column-header row in the first rows of the sheet")


def _parse_quantity_unit(raw: Any) -> tuple[int, str | None]:
    """Split a bulk quantity cell into (count, canonical unit).

    Handles the shapes real exports actually contain:
      "17CTNS"            -> (17, 'carton')
      "1PALLET(61items)"  -> (1, 'pallet')    parenthetical item count ignored
      "3bags2ctns1pallet" -> (6, 'mixed')     several units packed in one cell
      "5"                 -> (5, None)        bare count, unit from another column
    """
    if raw is None:
        return 1, None
    text = str(raw).strip()
    if not text:
        return 1, None

    # Drop parenthetical annotations ("(61items)") — they describe the contents
    # of a package, not how many packages there are.
    outer = re.sub(r"\([^)]*\)", " ", text)

    pairs: list[tuple[int, str]] = []
    for count, unit_raw in _QUANTITY_UNIT_RE.findall(outer):
        unit = _UNIT_NORMALIZATION.get(unit_raw.lower())
        if unit and unit not in _ANNOTATION_UNITS:
            pairs.append((int(count), unit))

    if not pairs:
        bare = re.fullmatch(r"\s*(\d+)\s*", outer)
        return (int(bare.group(1)), None) if bare else (1, None)
    if len(pairs) == 1:
        return pairs[0]
    # Mixed parcel: total the packages, flag the unit as mixed. The verbatim
    # source text is preserved separately on the row (quantity_raw).
    return sum(c for c, _ in pairs), "mixed"


def _normalize_package_unit(raw: Any) -> str | None:
    """Normalize a BALE TYPE-style column value to our canonical unit set."""
    text = _norm(raw)
    if not text:
        return None
    if text in _BALE_TYPE_UNITS:
        return _BALE_TYPE_UNITS[text]
    return _UNIT_NORMALIZATION.get(text, text)


def _bale_type(raw: Any) -> str | None:
    """Return the verbatim bale type ("BIG BALE") when the cell names one."""
    if _norm(raw) in _BALE_TYPE_UNITS:
        return str(raw).strip()
    return None


def _is_structural_row(ws: Worksheet, row: int, col_map: dict[int, str]) -> bool:
    """True for a two-row header's unit line or a summary/footer row."""
    for col in range(1, ws.max_column + 1):
        text = _norm(_cell_value(ws, row, col)).rstrip(":")
        if text and text in _STRUCTURAL_ROW_MARKERS:
            return True
    return False


def _is_red_font(ws: Worksheet, row: int, col_map: dict[int, str]) -> bool:
    """Return True if any mapped cell in this row has red font color."""
    for col in col_map:
        cell = ws.cell(row=row, column=col)
        font = cell.font
        if font is None or font.color is None:
            continue
        rgb = getattr(font.color, "rgb", None)
        if isinstance(rgb, str) and rgb.upper() in _RED_RGB_PREFIXES:
            return True
    return False


def _scan_hold_reason_note(ws: Worksheet) -> str | None:
    """Find the sheet's own caveat note explaining on-hold rows, if present.

    Real source sheets state the business rule as free text somewhere on the
    sheet (e.g. "goods on hold — China phone number used"). Any cell whose
    text contains "hold" as a standalone word and reads like a sentence
    (more than two words) is treated as that note.
    """
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if value is None:
                continue
            text = str(value).strip()
            if not text or len(text.split()) < 3:
                continue
            if re.search(r"\bhold\b", text, re.IGNORECASE):
                return text
    return None


def _parse_manifest_sheet(
    ws: Worksheet,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Parse a single worksheet. See parse_manifest_xlsx for the contract.

    Returns (container_metadata, rows, errors, total_data_rows).

    container_metadata: {container_number, ship_date, destination,
        estimated_arrival_date, departure_date} — raw strings, unparsed.
    rows: list of row dicts with raw/parsed fields (customer_name,
        customer_phone, description, delivery_note_number, quantity,
        package_unit, cbm, weight_actual_kg, bale_no, original_receipt_number,
        delivery_zone, on_hold).
    """
    header_row, col_map = _resolve_header_row(ws)
    container_metadata = _scan_header_metadata(ws, stop_row=header_row)
    hold_reason = _scan_hold_reason_note(ws)
    if hold_reason:
        container_metadata["hold_reason"] = hold_reason

    errors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    total_rows = 0

    for row_idx in range(header_row + 1, min(ws.max_row, _MAX_SHEET_ROWS) + 1):
        # The real source file repeats a fresh header row at each layout
        # switch (a new "page" with different columns) — re-check every row
        # against the alias table and swap in a new column map when one
        # matches, rather than assuming one static header for the sheet.
        new_col_map = _match_header_row(ws, row_idx)
        if new_col_map:
            col_map = new_col_map
            continue

        row_values = {col: _cell_value(ws, row_idx, col) for col in col_map}
        if all(v is None or str(v).strip() == "" for v in row_values.values()):
            continue
        if _is_structural_row(ws, row_idx, col_map):
            continue
        total_rows += 1

        by_field = {field: row_values[col] for col, field in col_map.items()}

        customer_name = str(by_field.get("customer_name") or "").strip()
        if not customer_name:
            errors.append(
                {
                    "row": row_idx,
                    "field": "Name",
                    "value": "",
                    "error": "Customer name is required",
                }
            )
            continue

        description = str(by_field.get("description") or "").strip()
        if not description:
            errors.append(
                {
                    "row": row_idx,
                    "field": "Item",
                    "value": "",
                    "error": "Description is required",
                }
            )
            continue

        row_errors: list[dict[str, Any]] = []

        cbm_value, e = parse_positive_decimal(by_field.get("cbm"), "Meas.", row_idx)
        if e:
            row_errors.append(e)
        weight_actual, e = parse_positive_decimal(by_field.get("weight_actual_kg"), "KG", row_idx)
        if e:
            row_errors.append(e)

        if row_errors:
            errors.extend(row_errors)
            continue

        quantity_raw = by_field.get("quantity_raw")
        if quantity_raw is not None and str(quantity_raw).strip() != "":
            quantity, package_unit = _parse_quantity_unit(quantity_raw)
        else:
            # Bale-layout rows without a QTY column: default quantity=1,
            # package_unit from the BALE TYPE column.
            quantity = 1
            package_unit = _normalize_package_unit(by_field.get("package_unit"))

        on_hold = _is_red_font(ws, row_idx, col_map)

        row_dict: dict[str, Any] = {
            "customer_name": customer_name,
            "customer_phone": _clean_id_str(by_field.get("customer_phone")),
            "description": description,
            "delivery_note_number": _clean_id_str(by_field.get("delivery_note_number")),
            "quantity": quantity,
            "quantity_raw": str(quantity_raw).strip() if quantity_raw is not None else None,
            "package_unit": package_unit,
            "cbm": float(cbm_value) if cbm_value is not None else 0.0,
            "weight_actual_kg": float(weight_actual) if weight_actual is not None else None,
            "bale_no": _clean_id_str(by_field.get("bale_no")),
            "bale_type": _bale_type(by_field.get("package_unit")),
            "original_receipt_number": _clean_id_str(by_field.get("original_receipt_number")),
            "delivery_zone": str(by_field.get("delivery_zone") or "").strip() or None,
            "on_hold": on_hold,
        }
        rows.append(row_dict)

    return container_metadata, rows, errors, total_rows


def parse_manifest_xlsx(
    file_buffer: BytesIO,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Parse a manifest .xlsx across every worksheet it contains.

    Returns (container_metadata, rows, errors, total_data_rows).

    Real exports split the two column layouts across separate sheets rather
    than stacking them ("Master-BALES" + "Master-CTN GOOD", both for the same
    PARTIAL NO), so every sheet is parsed and the rows concatenated. Reading
    only the active sheet silently dropped an entire class of goods.

    Each sheet repeats the same container header block; metadata is merged with
    the first non-empty value winning. A sheet with no recognizable header row
    (a notes/cover tab) is skipped rather than failing the whole import — but
    if *no* sheet parses, the ValueError from the last attempt is re-raised so
    a genuinely unreadable file still errors loudly.

    container_metadata: {container_number, ship_date, destination,
        estimated_arrival_date, departure_date} — raw strings, unparsed.
    rows: list of row dicts (customer_name, customer_phone, description,
        delivery_note_number, quantity, quantity_raw, package_unit, cbm,
        weight_actual_kg, bale_no, original_receipt_number, delivery_zone,
        on_hold), each tagged with its source `sheet_name`.
    """
    try:
        wb = openpyxl.load_workbook(file_buffer, data_only=True)
    except Exception as exc:
        raise ValueError("Invalid or corrupted .xlsx workbook") from exc

    container_metadata: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total_rows = 0
    last_error: ValueError | None = None

    for ws in wb.worksheets:
        try:
            meta, sheet_rows, sheet_errors, sheet_total = _parse_manifest_sheet(ws)
        except ValueError as exc:
            last_error = exc
            continue

        for key, value in meta.items():
            if value not in (None, ""):
                container_metadata.setdefault(key, value)
        for row in sheet_rows:
            row["sheet_name"] = ws.title
        rows.extend(sheet_rows)
        for err in sheet_errors:
            err["sheet"] = ws.title
        errors.extend(sheet_errors)
        total_rows += sheet_total

    if not rows and not errors and last_error is not None:
        raise last_error

    return container_metadata, rows, errors, total_rows
