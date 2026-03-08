"""Cursor-based pagination utilities.

Implements ADR-005: cursor-based pagination for stable results under
concurrent writes and no performance cliff at high offsets.

Cursor encodes the sort field value + row id of the last seen row, allowing
the next page query to use inequality filters rather than OFFSET.
"""

import base64
import json
import logging

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100

# Allowlist for sort field names — prevents SQL injection via sort parameter (§2.2)
ALLOWED_SORT_FIELDS: set[str] = {
    "created_at",
    "updated_at",
    "name",
    "status",
    "reference_number",
    "container_number",
    "total_amount_ngn",
    "departure_date",
    "arrival_date",
}


def encode_cursor(data: dict) -> str:
    """Base64url-encode a cursor dict.

    Args:
        data: Dict containing sort field value and row id, e.g.
              {"created_at": "2024-01-01T00:00:00Z", "id": "uuid"}.

    Returns:
        URL-safe base64 string suitable for use in API responses.
    """
    return base64.urlsafe_b64encode(json.dumps(data, default=str).encode()).decode()


def decode_cursor(cursor: str | None) -> dict | None:
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
        return json.loads(decoded)
    except Exception:
        logger.warning("Malformed cursor received — treating as first page")
        return None


def parse_pagination_params(query_params: dict) -> tuple[dict | None, int]:
    """Extract and validate pagination parameters from a query string dict.

    Args:
        query_params: The event["queryStringParameters"] dict (may be None).

    Returns:
        Tuple of (cursor_dict | None, limit).
        cursor_dict is None for the first page.
        limit is clamped between 1 and _MAX_LIMIT, defaulting to _DEFAULT_LIMIT.
    """
    if not query_params:
        return None, _DEFAULT_LIMIT

    cursor_str: str | None = query_params.get("cursor")
    cursor_dict = decode_cursor(cursor_str)

    try:
        limit = int(query_params.get("limit", _DEFAULT_LIMIT))
        limit = max(1, min(limit, _MAX_LIMIT))
    except (ValueError, TypeError):
        limit = _DEFAULT_LIMIT

    return cursor_dict, limit


def build_paginated_query(
    base_query: str,
    cursor: dict | None,
    limit: int,
    sort_field: str = "created_at",
    sort_direction: str = "DESC",
) -> tuple[str, dict]:
    """Append cursor-based pagination clauses to a base SQL query.

    The base_query should NOT include ORDER BY or LIMIT. It may include
    a WHERE clause; this function appends additional conditions using AND.

    Cursor structure expected: {"sort_value": <value>, "id": "<uuid>"}

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
    if clean_field not in ALLOWED_SORT_FIELDS:
        from shared.exceptions import ValidationError
        raise ValidationError(f"Invalid sort field: {clean_field}")

    direction = "DESC" if sort_direction.upper() == "DESC" else "ASC"
    # Comparison operator flips with direction
    op = "<" if direction == "DESC" else ">"

    params: dict = {"limit": limit + 1}  # fetch one extra to determine has_more
    query = base_query

    if cursor:
        sort_value = cursor.get("sort_value")
        cursor_id = cursor.get("id")
        if sort_value is not None and cursor_id:
            # Safe to inject sort_field and direction as they are allowlisted
            query += (
                f" AND ({clean_field} {op} %(cursor_sort_value)s"
                f" OR ({clean_field} = %(cursor_sort_value)s AND id {op} %(cursor_id)s))"
            )
            params["cursor_sort_value"] = sort_value
            params["cursor_id"] = cursor_id

    query += f" ORDER BY {clean_field} {direction}, id {direction} LIMIT %(limit)s"
    return query, params


def extract_page(
    rows: list[dict],
    limit: int,
    sort_field: str = "created_at",
) -> tuple[list[dict], str | None, bool]:
    """Slice the fetched rows and build the next cursor.

    Call this after executing a query built with build_paginated_query.

    Args:
        rows: Raw rows from DB (may contain limit+1 rows).
        limit: The requested page size.
        sort_field: Field used for sorting — must be present in each row.

    Returns:
        Tuple of (page_data, next_cursor | None, has_more).
    """
    has_more = len(rows) > limit
    page = rows[:limit]

    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor({
            "sort_value": last.get(sort_field),
            "id": last.get("id"),
        })
    else:
        next_cursor = None

    return page, next_cursor, has_more
