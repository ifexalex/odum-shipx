"""Uploads are listed only once confirmed, and the confirmation checks the stored size.

The browser uploads claim evidence, manifest evidence and container documents straight to storage. The row written at
presign time stays hidden until the client confirms the upload; the confirm call reads the stored size, and a file
over the limit (possible on Azure, where the upload URL cannot bind the length) is deleted with its row.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from shared import uploads
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError
from shared.providers.base import UploadTicket
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
STAFF = TenantContext(tenant_id=TENANT, user_id="staff-1", role=UserRole.NIGERIA_OFFICE_STAFF)
CUSTOMER = TenantContext(tenant_id=TENANT, user_id="user-cust", role=UserRole.CUSTOMER)
TOO_LARGE = uploads.MAX_UPLOAD_BYTES + 1


def _storage(size: int | None = 2048) -> MagicMock:
    storage = MagicMock()
    storage.object_size.return_value = size
    storage.presigned_upload.return_value = UploadTicket(url="https://storage.test/put", method="PUT", headers={})
    storage.presigned_get_url.return_value = "https://storage.test/get"
    return storage


def _evidence(**extra: object) -> dict:
    return {
        "id": "e1",
        "file_key": f"{TENANT}/claims/c1/0123-a.png",
        "file_name": "a.png",
        "file_type": "image/png",
        "created_at": "2026-11-19T10:00:00Z",
        "confirmed_at": None,
        **extra,
    }


class TestClaimEvidence:
    def _patches(self, storage: MagicMock, evidence: dict | None, *, owner: str = "cust-1"):
        from services.claims import service

        return (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_damage_claim_by_id", return_value={"id": "c1", "customer_id": owner}),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}),
            patch.object(service.repo, "get_claim_evidence", return_value=evidence),
            patch.object(service.repo, "confirm_claim_evidence", return_value={**(evidence or {}), "file_size_bytes": 2048}),
            patch.object(service.repo, "delete_unconfirmed_claim_evidence"),
            patch.object(service, "log_audit"),
        )

    def test_confirm_records_the_stored_size(self):
        from services.claims import service

        storage = _storage()
        p = self._patches(storage, _evidence())
        with p[0], p[1], p[2], p[3], p[4] as confirm, p[5] as delete, p[6] as audit:
            result = service.confirm_evidence(TENANT, "c1", "e1", CUSTOMER)
        confirm.assert_called_once_with("c1", "e1", 2048)
        delete.assert_not_called()
        audit.assert_called_once()
        assert result["file_size_bytes"] == 2048

    def test_a_file_over_the_limit_is_deleted_with_its_row(self):
        from services.claims import service

        storage = _storage(TOO_LARGE)
        p = self._patches(storage, _evidence())
        with p[0], p[1], p[2], p[3], p[4] as confirm, p[5] as delete, p[6], pytest.raises(BusinessRuleViolationError) as caught:
            service.confirm_evidence(TENANT, "c1", "e1", STAFF)
        assert caught.value.rule_id == "FILE_TOO_LARGE"
        storage.delete_object.assert_called_once_with(_evidence()["file_key"])
        delete.assert_called_once_with("c1", "e1")
        confirm.assert_not_called()

    def test_a_missing_upload_keeps_the_row_hidden(self):
        from services.claims import service

        storage = _storage(None)
        p = self._patches(storage, _evidence())
        with p[0], p[1], p[2], p[3], p[4] as confirm, p[5] as delete, p[6], pytest.raises(BusinessRuleViolationError) as caught:
            service.confirm_evidence(TENANT, "c1", "e1", STAFF)
        assert caught.value.rule_id == "UPLOAD_NOT_FOUND"
        confirm.assert_not_called()
        delete.assert_not_called()

    def test_confirming_twice_does_not_read_storage_again(self):
        from services.claims import service

        storage = _storage()
        p = self._patches(storage, _evidence(confirmed_at="2026-11-19T10:01:00Z", file_size_bytes=10))
        with p[0], p[1], p[2], p[3], p[4] as confirm, p[5], p[6] as audit:
            result = service.confirm_evidence(TENANT, "c1", "e1", STAFF)
        storage.object_size.assert_not_called()
        confirm.assert_not_called()
        audit.assert_not_called()
        assert result["file_size_bytes"] == 10

    def test_unknown_evidence_is_a_404(self):
        from services.claims import service

        p = self._patches(_storage(), None)
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6], pytest.raises(ResourceNotFoundError):
            service.confirm_evidence(TENANT, "c1", "missing", STAFF)

    def test_a_customer_cannot_confirm_on_another_customers_claim(self):
        from services.claims import service

        storage = _storage()
        p = self._patches(storage, _evidence(), owner="cust-2")
        with p[0], p[1], p[2], p[3], p[4] as confirm, p[5], p[6], pytest.raises(ResourceNotFoundError):
            service.confirm_evidence(TENANT, "c1", "e1", CUSTOMER)
        confirm.assert_not_called()
        storage.object_size.assert_not_called()

    def test_a_customer_cannot_upload_to_another_customers_claim(self):
        """It used to check only that the claim was in the tenant."""
        from services.claims import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_damage_claim_by_id", return_value={"id": "c1", "customer_id": "cust-2"}),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}),
            patch.object(service.repo, "create_claim_evidence") as create,
            pytest.raises(ResourceNotFoundError),
        ):
            service.generate_presigned_url(TENANT, "c1", "a.png", "image/png", CUSTOMER, size_bytes=1024)
        storage.presigned_upload.assert_not_called()
        create.assert_not_called()

    def test_a_customer_uploads_to_their_own_claim(self):
        from services.claims import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_damage_claim_by_id", return_value={"id": "c1", "customer_id": "cust-1"}),
            patch.object(service.repo, "get_customer_by_user_id", return_value={"id": "cust-1"}),
            patch.object(service.repo, "create_claim_evidence", return_value={"id": "e1"}) as create,
        ):
            result = service.generate_presigned_url(TENANT, "c1", "a.png", "image/png", CUSTOMER, size_bytes=1024)
        assert result["evidence_id"] == "e1"
        assert create.call_args.args[0]["uploaded_by"] == "user-cust"
        assert create.call_args.args[0]["file_name"] == "a.png"


class TestManifestEvidence:
    def test_a_file_over_the_limit_is_deleted_with_its_row(self):
        from services.manifest import service

        storage = _storage(TOO_LARGE)
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_manifest_by_id", return_value={"id": "m1"}),
            patch.object(
                service.repo, "get_manifest_evidence", return_value=_evidence(file_key=f"{TENANT}/manifests/m1/x-a.png")
            ),
            patch.object(service.repo, "confirm_manifest_evidence") as confirm,
            patch.object(service.repo, "delete_unconfirmed_manifest_evidence") as delete,
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            service.confirm_evidence(TENANT, "m1", "e1", actor_id="staff-1", ctx=STAFF)
        assert caught.value.rule_id == "FILE_TOO_LARGE"
        storage.delete_object.assert_called_once_with(f"{TENANT}/manifests/m1/x-a.png")
        delete.assert_called_once_with(TENANT, "m1", "e1")
        confirm.assert_not_called()

    def test_confirm_returns_the_listed_shape(self):
        from services.manifest import service

        storage = _storage()
        row = _evidence(file_key=f"{TENANT}/manifests/m1/x-a.png", label="Carton 1")
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch("services.manifest.service.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_manifest_by_id", return_value={"id": "m1"}),
            patch.object(service.repo, "get_manifest_evidence", return_value=row),
            patch.object(service.repo, "confirm_manifest_evidence", return_value={**row, "file_size_bytes": 2048}) as confirm,
            patch.object(service, "log_audit"),
        ):
            result = service.confirm_evidence(TENANT, "m1", "e1", actor_id="staff-1", ctx=STAFF)
        confirm.assert_called_once_with(TENANT, "m1", "e1", 2048)
        assert result["label"] == "Carton 1"
        assert result["download_url"] == "https://storage.test/get"


class TestContainerDocuments:
    def test_a_file_over_the_limit_is_deleted_with_its_row(self):
        from services.tracking import service

        storage = _storage(TOO_LARGE)
        doc = {"id": "d1", "s3_key": f"{TENANT}/containers/k1/x-bl.pdf", "document_type": "other", "confirmed_at": None}
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_container_by_id", return_value={"id": "k1"}),
            patch.object(service.repo, "get_container_document_by_id", return_value=doc) as get,
            patch.object(service.repo, "confirm_container_document") as confirm,
            patch.object(service.repo, "delete_unconfirmed_container_document") as delete,
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            service.confirm_document_upload(TENANT, "k1", "d1", actor_id="staff-1", actor_role="nigeria_office_staff")
        assert caught.value.rule_id == "FILE_TOO_LARGE"
        assert get.call_args.kwargs == {"include_unconfirmed": True}
        storage.delete_object.assert_called_once_with(doc["s3_key"])
        delete.assert_called_once_with(TENANT, "k1", "d1")
        confirm.assert_not_called()

    def test_confirm_records_the_stored_size(self):
        from services.tracking import service

        storage = _storage()
        doc = {"id": "d1", "s3_key": f"{TENANT}/containers/k1/x-bl.pdf", "document_type": "other", "confirmed_at": None}
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_container_by_id", return_value={"id": "k1"}),
            patch.object(service.repo, "get_container_document_by_id", return_value=doc),
            patch.object(service.repo, "confirm_container_document", return_value={**doc, "file_size_bytes": 2048}) as confirm,
            patch.object(service, "log_audit"),
        ):
            result = service.confirm_document_upload(TENANT, "k1", "d1", actor_id="staff-1", actor_role="nigeria_office_staff")
        confirm.assert_called_once_with(TENANT, "k1", "d1", 2048)
        assert result["file_size_bytes"] == 2048


def _event(method: str, path: str) -> dict:
    return {
        "requestContext": {
            "requestId": "req-1",
            "http": {"method": method, "path": path},
            "authorizer": {"claims": {"sub": "staff-1", "custom:tenant_id": TENANT}},
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "headers": {},
        "body": json.dumps({}),
        "queryStringParameters": {},
        "pathParameters": {},
    }


class TestConfirmRoutes:
    """Each confirm path reaches its confirm function, never the presign route that shares its prefix."""

    def test_claim_evidence(self):
        from services.claims import handler, service

        with (
            patch("services.claims.handler.get_tenant_context", return_value=STAFF),
            patch.object(service, "confirm_evidence", return_value={"id": "e1"}) as confirm,
        ):
            resp = handler.lambda_handler(_event("POST", "/v1/claims/c1/evidence/e1/confirm"), None)
        assert resp["statusCode"] == 200, resp["body"]
        assert confirm.call_args.args[:3] == (TENANT, "c1", "e1")

    def test_manifest_evidence(self):
        from services.manifest import handler, service

        with (
            patch("services.manifest.handler.get_tenant_context", return_value=STAFF),
            patch.object(service, "confirm_evidence", return_value={"id": "e1"}) as confirm,
            patch.object(service, "generate_evidence_upload") as presign,
        ):
            resp = handler.lambda_handler(_event("POST", "/v1/manifests/m1/evidence/e1/confirm"), None)
        assert resp["statusCode"] == 200, resp["body"]
        assert confirm.call_args.args[:3] == (TENANT, "m1", "e1")
        presign.assert_not_called()

    def test_container_document(self):
        from services.tracking import handler, service

        with (
            patch("services.tracking.handler.get_tenant_context", return_value=STAFF),
            patch.object(service, "confirm_document_upload", return_value={"id": "d1"}) as confirm,
        ):
            resp = handler.lambda_handler(_event("POST", "/v1/containers/k1/documents/d1/confirm"), None)
        assert resp["statusCode"] == 200, resp["body"]
        assert confirm.call_args.kwargs["doc_id"] == "d1"
