"""Standards compliance tests — verify all services meet 00_CROSS_CUTTING_STANDARDS.md."""
import json
from unittest.mock import patch

from shared.exceptions import ResourceNotFoundError
from shared.responses import created, error_response, no_content, paginated, success

_REQUIRED_SECURITY_HEADERS = {
    "X-Content-Type-Options",
    "Strict-Transport-Security",
    "Cache-Control",
    "X-Request-Id",
    "Content-Type",
}


def _assert_security_headers(resp: dict) -> None:
    headers = resp["headers"]
    assert "X-Content-Type-Options" in headers, "Missing X-Content-Type-Options"
    assert "Strict-Transport-Security" in headers, "Missing Strict-Transport-Security"
    assert "Cache-Control" in headers, "Missing Cache-Control"
    assert "X-Request-Id" in headers, "Missing X-Request-Id"
    assert "Content-Type" in headers, "Missing Content-Type"


class TestSecurityHeaders:
    def test_success_includes_security_headers(self):
        _assert_security_headers(success({"id": "1"}))

    def test_created_includes_security_headers(self):
        _assert_security_headers(created({"id": "1"}, location="/v1/x/1"))

    def test_no_content_includes_security_headers(self):
        _assert_security_headers(no_content())

    def test_paginated_includes_security_headers(self):
        _assert_security_headers(paginated([], None, False))

    def test_error_includes_security_headers(self):
        _assert_security_headers(error_response(ResourceNotFoundError("x", "1")))

    def test_x_content_type_options_value(self):
        resp = success({})
        assert resp["headers"]["X-Content-Type-Options"] == "nosniff"

    def test_cache_control_no_store(self):
        resp = success({})
        assert resp["headers"]["Cache-Control"] == "no-store"

    def test_request_id_propagated_to_all_response_types(self):
        rid = "req-test-12345"
        for resp in [
            success({}, request_id=rid),
            created({}, location="/v1/x/1", request_id=rid),
            no_content(request_id=rid),
            paginated([], None, False, request_id=rid),
            error_response(ResourceNotFoundError("x", "1"), request_id=rid),
        ]:
            assert resp["headers"]["X-Request-Id"] == rid


class TestStatusCodes:
    def test_post_create_returns_201(self):
        resp = created({"id": "1"}, location="/v1/x/1")
        assert resp["statusCode"] == 201

    def test_post_create_has_location_header(self):
        resp = created({"id": "1"}, location="/v1/refunds/refund-001")
        assert "Location" in resp["headers"]
        assert resp["headers"]["Location"] == "/v1/refunds/refund-001"

    def test_delete_returns_204(self):
        resp = no_content()
        assert resp["statusCode"] == 204

    def test_delete_has_empty_body(self):
        resp = no_content()
        assert resp["body"] == ""

    def test_list_returns_200(self):
        resp = paginated([], None, False)
        assert resp["statusCode"] == 200

    def test_get_returns_200(self):
        resp = success({"id": "1"})
        assert resp["statusCode"] == 200


class TestRfc7807ErrorFormat:
    def test_error_body_has_required_fields(self):
        resp = error_response(ResourceNotFoundError("container", "cnt-001"))
        body = json.loads(resp["body"])
        for field in ("type", "title", "status", "detail", "error_code"):
            assert field in body, f"RFC 7807 field '{field}' missing from error body"

    def test_error_type_is_uri(self):
        resp = error_response(ResourceNotFoundError("container", "cnt-001"))
        body = json.loads(resp["body"])
        assert body["type"].startswith("https://"), "Error 'type' must be a URI"

    def test_error_status_matches_http_status(self):
        err = ResourceNotFoundError("x", "y")
        resp = error_response(err)
        body = json.loads(resp["body"])
        assert body["status"] == resp["statusCode"]

    def test_not_found_returns_404_not_403(self):
        """Cross-tenant resource returns 404 to prevent enumeration (§security)."""
        resp = error_response(ResourceNotFoundError("container", "cnt-999"))
        assert resp["statusCode"] == 404

    def test_instance_included_when_provided(self):
        resp = error_response(
            ResourceNotFoundError("x", "y"), instance="/v1/containers/cnt-001"
        )
        body = json.loads(resp["body"])
        assert "instance" in body


class TestPaginationFormat:
    def test_paginated_response_has_data_and_meta(self):
        resp = paginated([{"id": "1"}], "cursor-abc", True)
        body = json.loads(resp["body"])
        assert "data" in body
        assert "meta" in body
        assert "pagination" in body["meta"]

    def test_pagination_meta_has_required_fields(self):
        resp = paginated([], None, False)
        pagination = json.loads(resp["body"])["meta"]["pagination"]
        assert "has_more" in pagination
        assert "next_cursor" in pagination

    def test_body_data_key_present_on_success(self):
        resp = success({"id": "1"})
        body = json.loads(resp["body"])
        assert "data" in body


# ---------------------------------------------------------------------------
# Idempotency (§1.2)
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Verify POST handlers honour the Idempotency-Key header."""

    TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    def _event(self, idempotency_key: str | None = None) -> dict:
        headers = {}
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return {
            "requestContext": {
                "requestId": "req-idem-001",
                "http": {"method": "POST", "path": "/v1/packing-lists"},
                "authorizer": {
                    "claims": {
                        "sub": "user-china",
                        "custom:tenant_id": self.TENANT_ID,
                        "cognito:groups": f"{self.TENANT_ID}:china_office_staff",
                    }
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": headers,
            "body": json.dumps({"customer_id": "cust-001", "container_id": "cont-001", "items": [{"description": "Test carton"}]}),
            "queryStringParameters": {},
        }

    def test_idempotency_hit_returns_cached_response_without_calling_service(
        self, monkeypatch
    ):
        """When check_idempotency finds a prior response, the handler must return
        it immediately without invoking the service layer again."""
        from services.packing_list import handler

        cached_response = {
            "statusCode": 201,
            "body": json.dumps({"data": {"id": "pl-already-created"}}),
            "headers": {"X-Request-Id": "req-original"},
        }

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.check_idempotency", return_value=cached_response),
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            resp = handler.lambda_handler(self._event(idempotency_key="idem-key-001"), {})

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["data"]["id"] == "pl-already-created"
        # Service must NOT have been called — response came from cache
        mock_svc.create_packing_list.assert_not_called()

    def test_post_without_idempotency_key_calls_service_normally(self, monkeypatch):
        """A POST without an Idempotency-Key processes normally."""
        from services.packing_list import handler

        created = {"id": "pl-new", "status": "draft", "packing_list_number": "PL-001"}

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.check_idempotency", return_value=None),
            patch("services.packing_list.handler.store_idempotency"),
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_packing_list.return_value = created
            resp = handler.lambda_handler(self._event(idempotency_key=None), {})

        assert resp["statusCode"] == 201
        mock_svc.create_packing_list.assert_called_once()

    def test_successful_post_stores_idempotency_response(self, monkeypatch):
        """After a successful POST, the response is stored under the Idempotency-Key."""
        from services.packing_list import handler

        created = {"id": "pl-new", "status": "draft", "packing_list_number": "PL-001"}

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.check_idempotency", return_value=None),
            patch("services.packing_list.handler.store_idempotency") as mock_store,
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_packing_list.return_value = created
            resp = handler.lambda_handler(self._event(idempotency_key="idem-key-002"), {})

        assert resp["statusCode"] == 201
        # store_idempotency must have been called with the key and the response
        mock_store.assert_called_once()
        stored_key, stored_resp = mock_store.call_args[0]
        assert stored_key == "idem-key-002"
        assert stored_resp["statusCode"] == 201

    def test_failed_post_does_not_store_idempotency_response(self, monkeypatch):
        """A 4xx or 5xx response must NOT be cached under the Idempotency-Key."""
        from services.packing_list import handler
        from shared.exceptions import ResourceNotFoundError

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.packing_list.handler.check_idempotency", return_value=None),
            patch("services.packing_list.handler.store_idempotency") as mock_store,
            patch("services.packing_list.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.create_packing_list.side_effect = ResourceNotFoundError("container", "co")
            resp = handler.lambda_handler(self._event(idempotency_key="idem-key-003"), {})

        assert resp["statusCode"] == 404
        mock_store.assert_not_called()

    def test_check_idempotency_with_none_key_returns_none(self):
        """check_idempotency(None) must return None — no DB hit."""
        from shared.idempotency import check_idempotency

        result = check_idempotency(None)
        assert result is None

    def test_store_idempotency_with_none_key_is_noop(self):
        """store_idempotency(None, response) must be a no-op (no exception, no DB write)."""
        from shared.idempotency import store_idempotency

        # Should not raise even if called with None
        store_idempotency(None, {"statusCode": 201})
