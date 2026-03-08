"""Unit tests for shared.responses — formatting, headers, RFC 7807."""
import json

import pytest

from shared.exceptions import (
    IllegalTransitionError,
    InsufficientPermissionsError,
    ResourceNotFoundError,
)
from shared.responses import created, error_response, no_content, paginated, success

_SECURITY_HEADERS = {
    "X-Content-Type-Options",
    "Strict-Transport-Security",
    "Cache-Control",
    "X-Request-Id",
    "Content-Type",
}


def _body(resp: dict) -> dict:
    return json.loads(resp["body"])


def _headers_present(resp: dict) -> None:
    """Assert all mandatory security headers are present."""
    for h in _SECURITY_HEADERS:
        assert h in resp["headers"], f"Missing header: {h}"


# ---------------------------------------------------------------------------
# success()
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_status_code_200(self):
        resp = success({"id": "1"})
        assert resp["statusCode"] == 200

    def test_body_data_key(self):
        resp = success({"id": "1"})
        assert _body(resp)["data"] == {"id": "1"}

    def test_list_data(self):
        resp = success([{"id": "1"}, {"id": "2"}])
        assert len(_body(resp)["data"]) == 2

    def test_security_headers_present(self):
        _headers_present(success({}))

    def test_request_id_propagated(self):
        resp = success({}, request_id="req-abc")
        assert resp["headers"]["X-Request-Id"] == "req-abc"

    def test_meta_included_when_provided(self):
        resp = success({"id": "1"}, meta={"count": 5})
        assert _body(resp)["meta"]["count"] == 5

    def test_custom_status_code(self):
        resp = success({}, status_code=202)
        assert resp["statusCode"] == 202


# ---------------------------------------------------------------------------
# created()
# ---------------------------------------------------------------------------


class TestCreated:
    def test_status_code_201(self):
        resp = created({"id": "1"}, location="/v1/items/1")
        assert resp["statusCode"] == 201

    def test_location_header_present(self):
        resp = created({"id": "1"}, location="/v1/items/1")
        assert resp["headers"]["Location"] == "/v1/items/1"

    def test_body_data_key(self):
        resp = created({"id": "1"}, location="/v1/items/1")
        assert _body(resp)["data"]["id"] == "1"

    def test_security_headers_present(self):
        _headers_present(created({}, location="/v1/x/1"))


# ---------------------------------------------------------------------------
# no_content()
# ---------------------------------------------------------------------------


class TestNoContent:
    def test_status_code_204(self):
        assert no_content()["statusCode"] == 204

    def test_empty_body(self):
        assert no_content()["body"] == ""

    def test_security_headers_present(self):
        _headers_present(no_content())


# ---------------------------------------------------------------------------
# paginated()
# ---------------------------------------------------------------------------


class TestPaginated:
    def test_status_code_200(self):
        resp = paginated([], None, False)
        assert resp["statusCode"] == 200

    def test_pagination_meta_has_more_false(self):
        resp = paginated([], None, False)
        meta = _body(resp)["meta"]["pagination"]
        assert meta["has_more"] is False
        assert meta["next_cursor"] is None

    def test_pagination_meta_has_more_true(self):
        resp = paginated([{"id": "x"}], "abc123", True)
        meta = _body(resp)["meta"]["pagination"]
        assert meta["has_more"] is True
        assert meta["next_cursor"] == "abc123"

    def test_data_list_present(self):
        data = [{"id": "1"}]
        resp = paginated(data, None, False)
        assert _body(resp)["data"] == data

    def test_total_count_included_when_provided(self):
        resp = paginated([], None, False, total_count=42)
        assert _body(resp)["meta"]["pagination"]["total_count"] == 42

    def test_security_headers_present(self):
        _headers_present(paginated([], None, False))


# ---------------------------------------------------------------------------
# error_response() — RFC 7807
# ---------------------------------------------------------------------------


class TestErrorResponse:
    def test_not_found_returns_404(self):
        err = ResourceNotFoundError("container", "cnt-001")
        resp = error_response(err)
        assert resp["statusCode"] == 404

    def test_rfc7807_fields_present(self):
        err = ResourceNotFoundError("container", "cnt-001")
        resp = error_response(err)
        body = _body(resp)
        for field in ("type", "title", "status", "detail", "error_code"):
            assert field in body, f"RFC 7807 field missing: {field}"

    def test_type_is_uri(self):
        err = ResourceNotFoundError("container", "cnt-001")
        body = _body(error_response(err))
        assert body["type"].startswith("https://")

    def test_status_matches_status_code(self):
        err = ResourceNotFoundError("container", "cnt-001")
        resp = error_response(err)
        body = _body(resp)
        assert body["status"] == resp["statusCode"]

    def test_instance_included_when_provided(self):
        err = ResourceNotFoundError("container", "cnt-001")
        resp = error_response(err, instance="/v1/containers/cnt-001")
        body = _body(resp)
        assert body["instance"] == "/v1/containers/cnt-001"

    def test_409_for_illegal_transition(self):
        err = IllegalTransitionError(
            entity="packing_list",
            current_state="approved",
            requested_state="draft",
            allowed=[],
        )
        resp = error_response(err)
        assert resp["statusCode"] == 409

    def test_403_for_insufficient_permissions(self):
        err = InsufficientPermissionsError(
            action="approve", required_role="tenant_admin"
        )
        resp = error_response(err)
        assert resp["statusCode"] == 403

    def test_security_headers_on_error(self):
        err = ResourceNotFoundError("x", "1")
        _headers_present(error_response(err))

    def test_request_id_in_error_headers(self):
        err = ResourceNotFoundError("x", "1")
        resp = error_response(err, request_id="req-xyz")
        assert resp["headers"]["X-Request-Id"] == "req-xyz"

    def test_cache_control_no_store(self):
        resp = success({})
        assert resp["headers"]["Cache-Control"] == "no-store"
