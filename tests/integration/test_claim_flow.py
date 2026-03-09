"""Integration test: Damage claim → inspection → resolution → refund creation."""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _event(method: str, path: str, body=None, role: str = "nigeria_office_staff") -> dict:
    return {
        "requestContext": {
            "requestId": "req-claim-001",
            "http": {"method": method, "path": path},
            "authorizer": {
                "claims": {
                    "sub": "user-staff",
                    "custom:tenant_id": TENANT_ID,
                    "cognito:groups": f"{TENANT_ID}:{role}",
                }
            },
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "body": json.dumps(body) if body else None,
        "queryStringParameters": {},
    }


class TestClaimHandlerDispatch:
    def test_file_claim_returns_201(self, monkeypatch):
        from services.claims import handler

        claim = {
            "id": "claim-001",
            "status": "filed",
            "customer_id": "cust-001",
        }
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.claims.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.file_claim.return_value = claim
            resp = handler.lambda_handler(
                _event(
                    "POST",
                    "/v1/claims",
                    body={
                        "customer_id": "cust-001",
                        "container_id": "cont-001",
                        "cartons_affected": 3,
                        "description": "Water damage",
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 201

    def test_list_claims_returns_200(self, monkeypatch):
        from services.claims import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.claims.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.list_claims.return_value = ([], None, False)
            resp = handler.lambda_handler(_event("GET", "/v1/claims"), {})
        assert resp["statusCode"] == 200

    def test_resolve_claim_returns_200(self, monkeypatch):
        from services.claims import handler

        resolved = {"id": "claim-001", "status": "resolved"}
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with (
            patch("services.claims.handler.service") as mock_svc,
            patch("shared.metering.record_usage"),
        ):
            mock_svc.resolve_claim.return_value = resolved
            resp = handler.lambda_handler(
                _event(
                    "PATCH",
                    "/v1/claims/claim-001/resolve",
                    body={
                        "resolution_type": "compensation",
                        "settlement_amount_usd": "30.00",
                        "notes": "Approved",
                    },
                ),
                {},
            )
        assert resp["statusCode"] == 200

    def test_warehouse_cannot_file_claim(self, monkeypatch):
        from services.claims import handler

        monkeypatch.setattr("shared.auth._check_tenant_active", lambda t: None)
        with patch("shared.metering.record_usage"):
            resp = handler.lambda_handler(
                _event(
                    "POST",
                    "/v1/claims",
                    body={
                        "customer_id": "c",
                        "container_id": "co",
                        "cartons_affected": 1,
                        "description": "d",
                    },
                    role="warehouse_attendant",
                ),
                {},
            )
        assert resp["statusCode"] == 403


class TestClaimResolutionCreatesRefund:
    """Verify that resolving a claim with 'refund' type creates a refund_request."""

    def test_refund_resolution_type_creates_refund_request(self):
        from services.claims import service

        claim = {
            "id": "claim-001",
            "tenant_id": TENANT_ID,
            "customer_id": "customer-001",
            "container_id": "container-001",
            "cartons_affected": 3,
            "description": "Damaged goods",
            "status": "under_inspection",
            "submitted_by": "user-nigeria",
        }
        resolved = {**claim, "status": "resolved", "resolution_type": "refund"}

        req = MagicMock()
        req.resolution_type = MagicMock()
        req.resolution_type.value = "refund"
        req.settlement_amount_usd = Decimal("40")
        req.notes = "Goods damaged"

        with (
            patch.object(service.repo, "get_damage_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_dollar_rate", return_value=Decimal("1550")),
            patch.object(service.repo, "update_claim_status", return_value=resolved),
            patch.object(service.repo, "create_refund_request_for_claim") as mock_create_refund,
            patch.object(service.repo, "get_billing_by_id", return_value=None),
            patch("services.claims.service.publish_event"),
            patch("services.claims.service.log_audit"),
        ):
            ctx = TenantContext(
                tenant_id=TENANT_ID,
                user_id="user-nigeria",
                role=UserRole.NIGERIA_OFFICE_STAFF,
            )
            service.resolve_claim(TENANT_ID, "claim-001", req, actor_id="user-nigeria", ctx=ctx)
            # A refund request must be created for 'refund' resolution type
            mock_create_refund.assert_called_once()
