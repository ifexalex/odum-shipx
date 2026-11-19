"""Cursor pagination, walked page by page through real SQL.

The mocked tests of the list queries only look at the SQL text, which is how two defects in `build_paginated_query`
went unnoticed: every aliased list that joins another table failed on its second page ("column reference "id" is
ambiguous": the cursor condition sits in WHERE, where a bare `id` matches every joined table), and a list sorted by
a column other than `created_at` built its cursor from `created_at` anyway, so page two compared the wrong thing.

These tests run the generated SQL (SQLite takes the same simple comparisons, and rejects an ambiguous column just as
Postgres does) over a joined table with ties in the sort column, page by page, and check the pages add up to exactly
the one-shot ordering: nothing repeated, nothing skipped.
"""

import re
import sqlite3
from typing import Any

import pytest

from shared.pagination import build_paginated_query, decode_cursor, encode_cursor, extract_page

ROW_COUNT = 23
PAGE_SIZE = 4


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE container (id TEXT PRIMARY KEY, container_number TEXT);
        CREATE TABLE customer (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE billing (
            id TEXT PRIMARY KEY, tenant_id TEXT, created_at TEXT, invoice_number TEXT,
            container_id TEXT, customer_id TEXT
        );
        """
    )
    conn.execute("INSERT INTO container VALUES ('k1', 'MSCU1')")
    conn.execute("INSERT INTO customer VALUES ('c1', 'Ngozi')")
    for i in range(ROW_COUNT):
        # Ties on created_at (three rows share each timestamp) exercise the id tiebreaker; invoice numbers are
        # deliberately in a different order from created_at, so sorting by them is distinguishable.
        conn.execute(
            "INSERT INTO billing VALUES (?, 't1', ?, ?, 'k1', 'c1')",
            (f"id-{i:03d}", f"2026-11-{1 + i // 3:02d}T10:00:00", f"INV-{(i * 7) % ROW_COUNT:03d}"),
        )
    return conn


def _sqlite(query: str) -> str:
    """psycopg's `%(name)s` as sqlite's `:name`."""
    return re.sub(r"%\((\w+)\)s", r":\1", query)


def _rows(db: sqlite3.Connection, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(_sqlite(query), params).fetchall()]


JOINED = """
    SELECT b.*, c.container_number, cu.name AS customer_name
    FROM billing b
    LEFT JOIN container c  ON c.id  = b.container_id
    LEFT JOIN customer  cu ON cu.id = b.customer_id
    WHERE b.tenant_id = :tenant
"""


def _walk(db, base: str, *, qualified: str, bare: str, direction: str) -> list[str]:
    """Every id, page by page, exactly as a list endpoint serves them."""
    seen: list[str] = []
    cursor = None
    for _ in range(ROW_COUNT):  # an upper bound that also stops a cursor that never advances
        query, params = build_paginated_query(base, cursor, PAGE_SIZE, sort_field=qualified, sort_direction=direction)
        page, next_cursor, has_more = extract_page(_rows(db, query, {**params, "tenant": "t1"}), PAGE_SIZE, bare)
        seen.extend(row["id"] for row in page)
        if not has_more:
            return seen
        cursor = decode_cursor(next_cursor)
    raise AssertionError("pagination never finished")


def _one_shot(db, base: str, *, qualified: str, direction: str) -> list[str]:
    query, params = build_paginated_query(base, None, ROW_COUNT + 10, sort_field=qualified, sort_direction=direction)
    return [row["id"] for row in _rows(db, query, {**params, "tenant": "t1"})]


@pytest.mark.parametrize("direction", ["DESC", "ASC"])
@pytest.mark.parametrize("sort", ["created_at", "invoice_number"])
class TestAliasedJoinedList:
    """The shape of the invoice, claim, release-note, notification and carryover lists."""

    def test_pages_add_up_to_the_whole_ordering(self, db, sort, direction):
        walked = _walk(db, JOINED, qualified=f"b.{sort}", bare=sort, direction=direction)
        assert walked == _one_shot(db, JOINED, qualified=f"b.{sort}", direction=direction)

    def test_nothing_repeats_and_nothing_is_skipped(self, db, sort, direction):
        walked = _walk(db, JOINED, qualified=f"b.{sort}", bare=sort, direction=direction)
        assert len(walked) == len(set(walked)) == ROW_COUNT

    def test_the_cursor_carries_the_column_that_was_sorted_by(self, db, sort, direction):
        query, params = build_paginated_query(JOINED, None, PAGE_SIZE, sort_field=f"b.{sort}", sort_direction=direction)
        rows = _rows(db, query, {**params, "tenant": "t1"})
        _, next_cursor, _ = extract_page(rows, PAGE_SIZE, sort)
        cursor = decode_cursor(next_cursor)
        assert cursor is not None
        assert cursor["sort_value"] == rows[PAGE_SIZE - 1][sort]
        assert cursor["id"] == rows[PAGE_SIZE - 1]["id"]


@pytest.mark.parametrize("direction", ["DESC", "ASC"])
class TestPlainList:
    """A single table, no alias (the shape of the simple lists): unchanged."""

    BASE = "SELECT * FROM billing WHERE tenant_id = :tenant"

    def test_pages_add_up_to_the_whole_ordering(self, db, direction):
        walked = _walk(db, self.BASE, qualified="created_at", bare="created_at", direction=direction)
        assert walked == _one_shot(db, self.BASE, qualified="created_at", direction=direction)
        assert len(set(walked)) == ROW_COUNT


class TestGeneratedSql:
    def test_the_id_tiebreaker_follows_the_sort_fields_alias(self):
        query, _ = build_paginated_query("SELECT 1 FROM t b WHERE 1=1", {"sort_value": "x", "id": "1"}, 10, "b.created_at")
        assert "b.id <" in query
        assert "ORDER BY b.created_at DESC, b.id DESC" in query
        assert " id <" not in query and ", id DESC" not in query

    def test_an_unaliased_sort_field_keeps_a_bare_id(self):
        query, _ = build_paginated_query("SELECT 1 FROM t WHERE 1=1", {"sort_value": "x", "id": "1"}, 10, "created_at")
        assert "ORDER BY created_at DESC, id DESC" in query

    def test_a_cursor_round_trips(self):
        assert decode_cursor(encode_cursor({"sort_value": "2026-11-01", "id": "a"})) == {"sort_value": "2026-11-01", "id": "a"}
