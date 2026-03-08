"""Unit tests for shared.pagination — cursor encode/decode, query building, page extraction."""
import pytest

from shared.exceptions import ValidationError
from shared.pagination import (
    build_paginated_query,
    decode_cursor,
    encode_cursor,
    extract_page,
    parse_pagination_params,
)


class TestEncodeDecode:
    def test_symmetric_encode_decode(self):
        data = {"sort_value": "2024-01-01T00:00:00", "id": "uuid-1"}
        assert decode_cursor(encode_cursor(data)) == data

    def test_decode_none_returns_none(self):
        assert decode_cursor(None) is None

    def test_decode_malformed_returns_none(self):
        assert decode_cursor("!!!not-base64!!!") is None

    def test_decode_invalid_json_returns_none(self):
        import base64
        bad = base64.urlsafe_b64encode(b"not json").decode()
        assert decode_cursor(bad) is None

    def test_encode_handles_datetime_default(self):
        from datetime import datetime, timezone
        data = {"sort_value": datetime(2024, 1, 1, tzinfo=timezone.utc), "id": "u"}
        cursor = encode_cursor(data)
        assert isinstance(cursor, str)
        decoded = decode_cursor(cursor)
        assert decoded is not None
        assert "sort_value" in decoded


class TestParsePaginationParams:
    def test_no_params_returns_defaults(self):
        cursor, limit = parse_pagination_params({})
        assert cursor is None
        assert limit == 20

    def test_limit_clamped_to_max(self):
        _, limit = parse_pagination_params({"limit": "500"})
        assert limit == 100

    def test_limit_minimum_one(self):
        _, limit = parse_pagination_params({"limit": "0"})
        assert limit == 1

    def test_invalid_limit_uses_default(self):
        _, limit = parse_pagination_params({"limit": "abc"})
        assert limit == 20

    def test_cursor_decoded_from_params(self):
        data = {"sort_value": "2024-01-01", "id": "uuid-1"}
        cursor_str = encode_cursor(data)
        cursor, _ = parse_pagination_params({"cursor": cursor_str})
        assert cursor == data

    def test_none_params_returns_defaults(self):
        cursor, limit = parse_pagination_params(None)
        assert cursor is None
        assert limit == 20


class TestBuildPaginatedQuery:
    _BASE = "SELECT * FROM packing_list WHERE tenant_id = %(tenant_id)s"

    def test_adds_order_by_and_limit(self):
        query, params = build_paginated_query(self._BASE, None, 20)
        assert "ORDER BY" in query
        assert "LIMIT" in query
        assert params["limit"] == 21  # limit + 1 for has_more detection

    def test_default_sort_desc(self):
        query, _ = build_paginated_query(self._BASE, None, 20)
        assert "DESC" in query

    def test_asc_sort_direction(self):
        query, _ = build_paginated_query(self._BASE, None, 20, sort_direction="ASC")
        assert "ASC" in query

    def test_cursor_adds_inequality(self):
        cursor = {"sort_value": "2024-01-01T00:00:00", "id": "uuid-1"}
        query, params = build_paginated_query(self._BASE, cursor, 20)
        assert "cursor_sort_value" in params
        assert "cursor_id" in params

    def test_no_cursor_no_inequality(self):
        query, params = build_paginated_query(self._BASE, None, 20)
        assert "cursor_sort_value" not in params

    def test_invalid_sort_field_raises_validation_error(self):
        with pytest.raises(ValidationError):
            build_paginated_query(self._BASE, None, 20, sort_field="injected; DROP TABLE")

    def test_valid_sort_fields_accepted(self):
        for field in ("created_at", "updated_at", "status", "reference_number"):
            query, _ = build_paginated_query(self._BASE, None, 20, sort_field=field)
            assert field in query


class TestExtractPage:
    def _rows(self, n: int) -> list[dict]:
        return [
            {"id": f"id-{i}", "created_at": f"2024-01-{i:02d}T00:00:00"}
            for i in range(1, n + 1)
        ]

    def test_fewer_rows_than_limit_no_more(self):
        rows = self._rows(5)
        page, cursor, has_more = extract_page(rows, 20)
        assert len(page) == 5
        assert has_more is False
        assert cursor is None

    def test_extra_row_signals_has_more(self):
        rows = self._rows(21)  # limit=20, fetched 21
        page, cursor, has_more = extract_page(rows, 20)
        assert len(page) == 20
        assert has_more is True
        assert cursor is not None

    def test_cursor_encodes_last_row(self):
        rows = self._rows(21)
        page, cursor, has_more = extract_page(rows, 20)
        decoded = decode_cursor(cursor)
        assert decoded["id"] == "id-20"

    def test_empty_rows(self):
        page, cursor, has_more = extract_page([], 20)
        assert page == []
        assert cursor is None
        assert has_more is False
