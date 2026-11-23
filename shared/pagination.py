"""Cursor-based pagination utilities.

Implements ADR-005: cursor-based pagination for stable results under
concurrent writes and no performance cliff at high offsets.

Cursor encodes the sort field value + row id of the last seen row, allowing
the next page query to use inequality filters rather than OFFSET.
"""

import base64
import json
import logging
import re
from typing import Any

from shared.exceptions import ValidationError

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100

# Allowlist for sort field names — prevents SQL injection via sort parameter (§2.2)
#
# Ground-truth fix (row 7.37): `departure_date`, `arrival_date`, and
# `total_amount_ngn` never matched any real column on any table in the schema
# (see migrations/versions/002_core_operational_tables.py) — they were dead
# allowlist entries that could never be exercised by build_paginated_query.
# Replaced with the columns the newly-wired Table sort UI actually needs:
# `estimated_arrival_date` (container.eta), `invoice_number`/`billed_at`
# (billing), `reference` (damage_claim's human-readable claim number).
# The *entire* sort expression must be one identifier, optionally prefixed by a
# single table alias ("created_at" or "b.created_at"). This is interpolated
# straight into ORDER BY and the cursor comparison, so it cannot be validated by
# looking at only part of the string: the allowlist check below used to inspect
# just the segment after the last "." while the whole string was interpolated, so
# `id,(select pg_sleep(5))::text,b.created_at` (or `id;UPDATE …;--.created_at`)
# passed as "created_at" and executed. Reachable by any role that can list, via
# GET /v1/billing|claims|containers?sort=… (customers can call the billing list).
# `fullmatch`, not `$` — `$` also matches before a trailing newline.
_SORT_EXPRESSION_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")

ALLOWED_SORT_FIELDS: set[str] = {
    "created_at",
    "updated_at",
    "name",
    "status",
    "reference_number",
    "container_number",
    "estimated_arrival_date",
    "invoice_number",
    "billed_at",
    "reference",
}


def encode_cursor(data: dict[str, Any]) -> str:
    """Base64url-encode a cursor dict.

    Args:
        data: Dict containing sort field value and row id, e.g.
              {"created_at": "2024-01-01T00:00:00Z", "id": "uuid"}.

    Returns:
        URL-safe base64 string suitable for use in API responses.
    """
    return base64.urlsafe_b64encode(json.dumps(data, default=str).encode()).decode()


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    """Decode a cursor string back to a dict.

    Args:
        cursor: The base64url cursor string, or None for the first page.

    Returns:
        Decoded dict, or None if cursor is None or malformed.
    """
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        result: dict[str, Any] = json.loads(decoded)
        return result
    except Exception:
        logger.warning("Malformed cursor received — treating as first page")
        return None


def parse_pagination_params(
    query_params: dict[str, Any] | None,
    *,
    default_limit: int = _DEFAULT_LIMIT,
) -> tuple[dict[str, Any] | None, int]:
    """Extract and validate pagination parameters from a query string dict.

    Args:
        query_params: The event["queryStringParameters"] dict (may be None).
        default_limit: Default page size when `limit` is omitted or invalid.

    Returns:
        Tuple of (cursor_dict | None, limit).
        cursor_dict is None for the first page.
        limit is clamped between 1 and _MAX_LIMIT, defaulting to default_limit.
    """
    safe_default = max(1, min(default_limit, _MAX_LIMIT))
    if not query_params:
        return None, safe_default

    cursor_str: str | None = query_params.get("cursor")
    cursor_dict = decode_cursor(cursor_str)

    try:
        limit = int(query_params.get("limit", safe_default))
        limit = max(1, min(limit, _MAX_LIMIT))
    except (ValueError, TypeError):
        limit = safe_default

    return cursor_dict, limit


def build_paginated_query(
    base_query: str,
    cursor: dict[str, Any] | None,
    limit: int,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[str, dict[str, Any]]:
    """Append cursor-based pagination clauses to a base SQL query.

    The base_query should NOT include ORDER BY or LIMIT. It may include
    a WHERE clause; this function appends additional conditions using AND.

    Cursor structure expected: {"sort_value": <value>, "id": "<uuid>"}, plus ``"sort_is_null": true`` when the last
    row's sort value was empty.

    Empty sort values come last in both directions (``NULLS LAST``), and the cursor carries "it was empty", so paging
    through them continues by ``id`` instead of starting over. Before 2026-11-19 a cursor whose sort value was NULL was
    ignored, and the next page of, say, invoices sorted by billed date restarted at the first page once it reached the
    unbilled ones.

    Args:
        base_query: SQL query without ORDER BY / LIMIT.
        cursor: Decoded cursor dict, or None for the first page.
        limit: Number of rows to fetch (request limit + 1 to detect has_more).
        sort_field: Column name to sort by — validated against ALLOWED_SORT_FIELDS.
        sort_direction: "ASC" or "DESC".

    Returns:
        Tuple of (modified_query, params_dict).
    """
    clean_field = sort_field.lstrip("-")
    # Allow table-aliased fields like "b.created_at", but only as a single
    # identifier (or alias.identifier) — see _SORT_EXPRESSION_RE.
    if _SORT_EXPRESSION_RE.fullmatch(clean_field) is None:
        raise ValidationError("Invalid sort field")
    col_name = clean_field.split(".")[-1]
    if col_name not in ALLOWED_SORT_FIELDS:
        raise ValidationError(f"Invalid sort field: {col_name}")

    direction = "DESC" if sort_direction.upper() == "DESC" else "ASC"
    # Comparison operator flips with direction
    op = "<" if direction == "DESC" else ">"
    # The id tiebreaker is qualified with the sort field's table alias. A bare `id` is ambiguous the moment the query
    # joins another table (they all have one), and the cursor condition sits in WHERE, where an output column name
    # cannot stand in: the first page worked and every later page failed with "column reference "id" is ambiguous".
    alias = clean_field.rpartition(".")[0]
    id_column = f"{alias}.id" if alias else "id"

    params: dict[str, Any] = {"limit": limit + 1}  # fetch one extra to determine has_more
    query = base_query

    if cursor:
        sort_value = cursor.get("sort_value")
        cursor_id = cursor.get("id")
        if sort_value is not None and cursor_id:
            # Safe to inject sort_field and direction as they are allowlisted. Rows with an empty sort value all come
            # after any value (NULLS LAST), so they are still ahead of this cursor.
            query += (
                f" AND ({clean_field} {op} %(cursor_sort_value)s"
                f" OR ({clean_field} = %(cursor_sort_value)s AND {id_column} {op} %(cursor_id)s)"
                f" OR {clean_field} IS NULL)"
            )
            params["cursor_sort_value"] = sort_value
            params["cursor_id"] = cursor_id
        elif cursor.get("sort_is_null") and cursor_id:
            # The last row had an empty sort value: only empty ones remain, in id order.
            query += f" AND ({clean_field} IS NULL AND {id_column} {op} %(cursor_id)s)"
            params["cursor_id"] = cursor_id

    query += f" ORDER BY {clean_field} {direction} NULLS LAST, {id_column} {direction} LIMIT %(limit)s"
    return query, params


def extract_page(
    rows: list[dict[str, Any]],
    limit: int,
    sort_field: str = "created_at",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Slice the fetched rows and build the next cursor.

    Call this after executing a query built with build_paginated_query.

    Args:
        rows: Raw rows from DB (may contain limit+1 rows).
        limit: The requested page size.
        sort_field: The column the query was sorted by, as a bare name (no table alias). It must be present in each row:
            the next cursor carries its value, so passing a different column makes the next page compare the wrong
            thing. Lists the user can sort pass the column they sorted by; the rest sort by `created_at`.

    Returns:
        Tuple of (page_data, next_cursor | None, has_more).
    """
    has_more = len(rows) > limit
    page = rows[:limit]

    if has_more and page:
        last = page[-1]
        sort_value = last.get(sort_field)
        next_cursor = encode_cursor(
            {
                "sort_value": sort_value,
                "id": last.get("id"),
                **({"sort_is_null": True} if sort_value is None else {}),
            }
        )
    else:
        next_cursor = None

    return page, next_cursor, has_more
