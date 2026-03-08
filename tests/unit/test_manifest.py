"""Unit tests for services.manifest.service — verification workflow."""
from unittest.mock import MagicMock, call, patch

import pytest

from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _ctx(role: UserRole = UserRole.NIGERIA_OFFICE_STAFF) -> TenantContext:
    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=role)


def _manifest(**kw) -> dict:
    base = {
        "id": "manifest-001",
        "tenant_id": TENANT_ID,
        "container_id": "container-001",
        "manifest_number": "ACME-MN-001",
        "verification_status": "pending",
        "created_by": "user-china",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# get_manifest
# ---------------------------------------------------------------------------


class TestGetManifest:
    def test_returns_manifest_with_customers(self):
        from services.manifest import service

        manifest = _manifest()
        customers = [{"customer_id": "cust-001", "total_cbm": 5.0}]

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "get_customer_summaries", return_value=customers),
        ):
            result = service.get_manifest(TENANT_ID, "manifest-001")

        assert result["id"] == "manifest-001"
        assert result["customers"] == customers

    def test_not_found_raises(self):
        from services.manifest import service

        with patch.object(service.repo, "get_manifest_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.get_manifest(TENANT_ID, "nonexistent")


# ---------------------------------------------------------------------------
# verify_manifest — transition guards
# ---------------------------------------------------------------------------


class TestVerifyManifest:
    def _req(self, status: str, discrepancies=None) -> MagicMock:
        req = MagicMock()
        from services.manifest.models import VerificationStatus
        req.verification_status = (
            VerificationStatus.verified
            if status == "verified"
            else VerificationStatus.discrepancies_found
        )
        req.discrepancies = discrepancies or []
        return req

    def test_already_verified_raises(self):
        from services.manifest import service

        manifest = _manifest(verification_status="verified")

        with patch.object(service.repo, "get_manifest_by_id", return_value=manifest):
            with pytest.raises(BusinessRuleViolationError):
                service.verify_manifest(
                    TENANT_ID, "manifest-001", self._req("verified"),
                    actor_id="u", ctx=_ctx()
                )

    def test_already_discrepancies_raises(self):
        from services.manifest import service

        manifest = _manifest(verification_status="discrepancies_found")

        with patch.object(service.repo, "get_manifest_by_id", return_value=manifest):
            with pytest.raises(BusinessRuleViolationError):
                service.verify_manifest(
                    TENANT_ID, "manifest-001", self._req("discrepancies_found"),
                    actor_id="u", ctx=_ctx()
                )

    def test_not_found_raises(self):
        from services.manifest import service

        with patch.object(service.repo, "get_manifest_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.verify_manifest(
                    TENANT_ID, "nonexistent", self._req("verified"),
                    actor_id="u", ctx=_ctx()
                )

    def test_verified_transition_calls_set_verified(self):
        from services.manifest import service

        manifest = _manifest()
        updated = {**manifest, "verification_status": "verified"}
        customers = []

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "set_manifest_verified", return_value=updated) as mock_verify,
            patch.object(service.repo, "get_customer_summaries", return_value=customers),
            patch("services.manifest.service.log_audit"),
        ):
            result = service.verify_manifest(
                TENANT_ID, "manifest-001", self._req("verified"),
                actor_id="u", ctx=_ctx()
            )

        mock_verify.assert_called_once_with(TENANT_ID, "manifest-001", "u", notes=None)
        assert result["verification_status"] == "verified"

    def test_discrepancies_transition_creates_missing_items(self):
        from services.manifest import service

        manifest = _manifest()
        updated = {**manifest, "verification_status": "discrepancies_found"}
        customers = []

        disc = MagicMock()
        disc.type = "missing"
        disc.carton_tags = ["TAG-001", "TAG-002"]
        disc.customer_id = "cust-001"
        disc.notes = "Missing at arrival"

        req = self._req("discrepancies_found", discrepancies=[disc])

        item = {"packing_list_id": "pl-001", "tracking_code": "TK-001"}

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "set_manifest_discrepancies_found", return_value=updated),
            patch.object(service.repo, "get_item_by_carton_tag", return_value=item),
            patch.object(service.repo, "create_missing_item") as mock_create,
            patch.object(service.repo, "get_customer_summaries", return_value=customers),
            patch("services.manifest.service.log_audit"),
        ):
            service.verify_manifest(
                TENANT_ID, "manifest-001", req,
                actor_id="u", ctx=_ctx()
            )

        # One call per carton_tag
        assert mock_create.call_count == 2
        call_args = mock_create.call_args_list
        tags_used = [c[0][1]["carton_tag"] for c in call_args]
        assert "TAG-001" in tags_used
        assert "TAG-002" in tags_used

    def test_damaged_discrepancy_does_not_create_missing_item(self):
        """Damaged items are noted but no missing_item row is created."""
        from services.manifest import service

        manifest = _manifest()
        updated = {**manifest, "verification_status": "discrepancies_found"}

        disc = MagicMock()
        disc.type = "damaged"
        disc.carton_tags = ["TAG-999"]
        disc.customer_id = "cust-001"
        disc.notes = "Visibly damaged"

        req = self._req("discrepancies_found", discrepancies=[disc])

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "set_manifest_discrepancies_found", return_value=updated),
            patch.object(service.repo, "create_missing_item") as mock_create,
            patch.object(service.repo, "get_customer_summaries", return_value=[]),
            patch("services.manifest.service.log_audit"),
        ):
            service.verify_manifest(
                TENANT_ID, "manifest-001", req,
                actor_id="u", ctx=_ctx()
            )

        mock_create.assert_not_called()

    def test_missing_item_with_no_packing_list_item_still_created(self):
        """carton_tag with no matching item → packing_list_id and tracking_code are None."""
        from services.manifest import service

        manifest = _manifest()
        updated = {**manifest, "verification_status": "discrepancies_found"}

        disc = MagicMock()
        disc.type = "missing"
        disc.carton_tags = ["UNKNOWN-TAG"]
        disc.customer_id = "cust-001"
        disc.notes = ""

        req = self._req("discrepancies_found", discrepancies=[disc])

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "set_manifest_discrepancies_found", return_value=updated),
            patch.object(service.repo, "get_item_by_carton_tag", return_value=None),
            patch.object(service.repo, "create_missing_item") as mock_create,
            patch.object(service.repo, "get_customer_summaries", return_value=[]),
            patch("services.manifest.service.log_audit"),
        ):
            service.verify_manifest(
                TENANT_ID, "manifest-001", req,
                actor_id="u", ctx=_ctx()
            )

        mock_create.assert_called_once()
        created_data = mock_create.call_args[0][1]
        assert created_data["packing_list_id"] is None
        assert created_data["tracking_code"] is None

    def test_verify_logs_audit(self):
        from services.manifest import service

        manifest = _manifest()
        updated = {**manifest, "verification_status": "verified"}

        with (
            patch.object(service.repo, "get_manifest_by_id", return_value=manifest),
            patch.object(service.repo, "set_manifest_verified", return_value=updated),
            patch.object(service.repo, "get_customer_summaries", return_value=[]),
            patch("services.manifest.service.log_audit") as mock_audit,
        ):
            service.verify_manifest(
                TENANT_ID, "manifest-001", self._req("verified"),
                actor_id="auditor", ctx=_ctx()
            )

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args[1]
        assert audit_kwargs["action"] == "STATUS_CHANGE"
        assert audit_kwargs["entity_type"] == "manifest"
        assert audit_kwargs["before_state"]["verification_status"] == "pending"


# ---------------------------------------------------------------------------
# list_manifests
# ---------------------------------------------------------------------------


class TestListManifests:
    def test_delegates_to_repo(self):
        from services.manifest import service

        rows = [_manifest()]
        with patch.object(service.repo, "list_manifests", return_value=(rows, None, False)) as mock_list:
            result, cursor, has_more = service.list_manifests(TENANT_ID, {}, 20, None)

        mock_list.assert_called_once_with(TENANT_ID, {}, 20, None)
        assert len(result) == 1
        assert not has_more
