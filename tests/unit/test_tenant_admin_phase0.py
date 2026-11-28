"""Tenant Admin Audit Phase 0 regression tests (TA-01, TA-02, TA-03/TC-17, TA-04, TC-14)."""

import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.payment_release import service as pr_service
from services.tenant_management.models import WebhookEventType
from shared import http_routing
from shared.tenant_context import TenantContext, UserRole

ROOT = Path(__file__).resolve().parents[2]


def _segments_match(template: str, actual: str) -> bool:
    t_parts = template.strip("/").split("/")
    a_parts = actual.strip("/").split("/")
    if len(t_parts) != len(a_parts):
        return False
    return all(
        (t.startswith("{") and t.endswith("}")) or (a.startswith("{") and a.endswith("}")) or t == a
        for t, a in zip(t_parts, a_parts, strict=True)
    )


def _extract_aws_routes() -> set[tuple[str, str]]:
    tf_text = (ROOT / "infrastructure" / "aws" / "modules" / "api-gateway" / "main.tf").read_text(encoding="utf-8")
    routes: set[tuple[str, str]] = set()
    for method, path in re.findall(r'"(GET|POST|PUT|PATCH|DELETE)\s+(/v1/[^"]+)"\s*=', tf_text):
        routes.add((method, path))
    return routes


def _extract_frontend_api_routes() -> list[tuple[str, str, str]]:
    """Extract (method, normalized_path, source_file) calls from frontend/src/api/*.ts."""
    api_dir = ROOT / "frontend" / "src" / "api"
    found: list[tuple[str, str, str]] = []
    # Match apiRequest / apiRequestList object calls: method: 'GET', path: `/v1/...` or '/v1/...'
    req_re = re.compile(
        r"method:\s*['\"](GET|POST|PUT|PATCH|DELETE)['\"][^}]{0,220}?path:\s*([`'\"])(/v1/[^`'\"]+)\2",
        re.DOTALL,
    )
    # Match apiDownloadFile(`/v1/...`, ...) -> GET
    dl_re = re.compile(r"apiDownloadFile\(\s*([`'\"])(/v1/[^`'\"]+)\1")
    for ts_file in sorted(api_dir.glob("*.ts")):
        if ts_file.name.endswith(".test.ts"):
            continue
        text = ts_file.read_text(encoding="utf-8")
        for method, _q, raw_path in req_re.findall(text):
            norm = re.sub(r"\$\{[^}]+\}", "{id}", raw_path).split("?")[0]
            found.append((method, norm, ts_file.name))
        for _q, raw_path in dl_re.findall(text):
            norm = re.sub(r"\$\{[^}]+\}", "{id}", raw_path).split("?")[0]
            found.append(("GET", norm, ts_file.name))
    return found


class TestTA01TruthfulWebhookEvents:
    def test_every_offered_webhook_event_has_a_backend_sender(self) -> None:
        services_dir = ROOT / "services"
        source = "\n".join(p.read_text(encoding="utf-8") for p in services_dir.rglob("*.py") if p.name != "models.py")
        missing = [ev.value for ev in WebhookEventType if ev.value not in source]
        assert missing == [], f"Webhook events offered without a backend sender: {missing}"


class TestTA02CreditReleaseApproverDerivation:
    def test_credit_granted_by_name_derived_from_authenticated_admin_not_payload(self) -> None:
        admin_ctx = TenantContext(tenant_id="t1", user_id="admin-uuid-1", role=UserRole.TENANT_ADMIN)
        req = SimpleNamespace(
            billing_id="b1",
            carton_tags=["TAG-1"],
            packages_released=None,
            release_with_outstanding=True,
            approval_notes="Approved by owner",
            warehouse_id=None,
            credit_granted_by_name="Spoofed Manager Name",
            due_date=None,
            physical_document_number=None,
            packing_list_invoice_numbers=None,
        )
        billing = {
            "id": "b1",
            "customer_id": "c1",
            "container_id": "ct1",
            "status": "partially_paid",
            "total_cbm": Decimal("5.0"),
            "total_cartons": 1,
            "amount_paid_ngn": Decimal("5000"),
            "total_ngn": Decimal("15000"),
            "balance_ngn": Decimal("10000"),
        }
        captured: dict = {}

        def _capture_note(_tid: str, data: dict) -> dict:
            captured.update(data)
            return {
                "id": "rn-1",
                "reference_number": "ACME-RN-001",
                "status": "active",
                "carton_tags": ["TAG-1"],
                "total_cartons": 1,
                "is_partial": False,
                "is_on_credit": True,
                "credit_granted_by_name": data["credit_granted_by_name"],
                "created_at": None,
            }

        with (
            patch.object(pr_service.repo, "get_billing_by_id", return_value=billing),
            patch.object(pr_service.repo, "lock_billing", return_value=billing),
            patch.object(pr_service.repo, "get_approved_carton_tags_for_billing", return_value=["TAG-1"]),
            patch.object(pr_service.repo, "get_active_release_note_carton_tags", return_value=[]),
            patch.object(pr_service.repo, "get_default_warehouse", return_value=None),
            patch.object(pr_service.repo, "get_tenant_user_name", return_value="Ada Admin"),
            patch.object(pr_service.repo, "mark_billing_released_with_outstanding"),
            patch.object(pr_service.repo, "create_carryover_entry", return_value={"id": "co-1"}),
            patch.object(pr_service.repo, "get_tenant_short", return_value="ACME"),
            patch.object(pr_service.repo, "get_next_release_note_seq", return_value=1),
            patch.object(pr_service.repo, "create_release_note", side_effect=_capture_note),
            patch.object(pr_service, "publish_event"),
        ):
            result = pr_service.generate_release_note("t1", req, actor_id="admin-uuid-1", ctx=admin_ctx)

        assert captured["credit_granted_by"] == "admin-uuid-1"
        assert captured["credit_granted_by_name"] == "Ada Admin"
        assert result["credit_granted_by_name"] == "Ada Admin"


class TestTA03RouteParity:
    def test_every_frontend_api_call_is_routed_in_azure_and_aws_api_gateway(self) -> None:
        aws_routes = _extract_aws_routes()
        frontend_routes = _extract_frontend_api_routes()
        assert len(frontend_routes) > 50, "Expected to extract >50 frontend API routes"

        missing_azure: list[str] = []
        missing_aws: list[str] = []
        for method, path, filename in frontend_routes:
            concrete = path.replace("{id}", "11111111-1111-1111-1111-111111111111")
            if http_routing.resolve_service(concrete) is None:
                missing_azure.append(f"{method} {path} ({filename})")
            if not any(m == method and _segments_match(tpl, path) for m, tpl in aws_routes):
                missing_aws.append(f"{method} {path} ({filename})")

        assert missing_azure == [], f"Frontend routes missing from Azure http_routing: {missing_azure}"
        assert missing_aws == [], f"Frontend routes missing from AWS API Gateway: {missing_aws}"
