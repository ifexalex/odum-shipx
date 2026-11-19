"""Client-supplied upload names in S3 keys and Content-Disposition (shared.validation.safe_filename).

Four presigned-upload flows (claims, manifest evidence, container documents, payment-claim
evidence) embedded the client's `filename` verbatim in the S3 key, and two download flows put the
stored name inside `Content-Disposition: inline; filename="{name}"`. A `"` breaks out of that quoted
string, `/` fabricates key structure, and a bidi-override character spoofs the extension staff see.
"""

from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import ValidationError
from shared.providers.base import UploadTicket
from shared.tenant_context import TenantContext, UserRole
from shared.validation import safe_filename

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("photo.jpg", "photo.jpg"),
            ("IMG (1).jpg", "IMG (1).jpg"),
            ("装箱单.xlsx", "装箱单.xlsx"),  # China-office staff upload Chinese-named files
            ("Packing List - Final.pdf", "Packing List - Final.pdf"),
            ("../../other-tenant/claims/x.png", "x.png"),
            ("C:\\Users\\me\\receipt.pdf", "receipt.pdf"),
            ("a\"; filename*=UTF-8''evil.html", "a__ filename__UTF-8__evil.html"),
            ("a\r\nX-Injected: 1.jpg", "a__X-Injected_ 1.jpg"),
            ("invoice\u202efdp.exe", "invoice_fdp.exe"),  # bidi override would render as invoice.exe.pdf
            (".hidden", "hidden"),
            ("  spaced.pdf  ", "spaced.pdf"),
        ],
    )
    def test_reduces_to_a_safe_name(self, raw, expected):
        assert safe_filename(raw) == expected

    @pytest.mark.parametrize("raw", ["", "..", "...", "/", "///", "____", " ", "\u202e", None, 42, ["a.jpg"]])
    def test_unusable_names_are_rejected(self, raw):
        with pytest.raises(ValidationError):
            safe_filename(raw)

    def test_default_is_used_instead_of_raising(self):
        assert safe_filename("..", default="document") == "document"
        assert safe_filename(None, default="document") == "document"

    def test_result_never_contains_header_or_key_breaking_characters(self):
        nasty = 'x"/\\;\r\n\x00\u202e\u2028<>|:*?'
        cleaned = safe_filename(nasty + "y.pdf")
        assert not set(cleaned) & set('"/\\;\r\n\x00\u202e\u2028<>|:*?')

    def test_long_names_are_capped_and_keep_their_extension(self):
        cleaned = safe_filename("a" * 400 + ".pdf")
        assert len(cleaned) <= 100
        assert cleaned.endswith(".pdf")

    def test_long_names_with_no_extension_are_capped(self):
        assert len(safe_filename("b" * 400)) == 100


HOSTILE = '../../bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/claims/x/evil".png'
EXPECTED = "evil_.png"


def _storage():
    """Fake StorageProvider — records the key/disposition the service passes."""
    storage = MagicMock()
    storage.presigned_upload.return_value = UploadTicket(
        url="https://s3.example/upload", method="PUT", headers={"Content-Type": "image/png"}
    )
    storage.presigned_get_url.return_value = "https://s3.example/get"
    return storage


class TestUploadFlowsSanitiseTheKeyAndTheStoredName:
    def test_claim_evidence(self):
        from services.claims import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_damage_claim_by_id", return_value={"id": "c1"}),
            patch.object(service.repo, "create_claim_evidence", return_value={"id": "e1"}) as create,
        ):
            result = service.generate_presigned_url(TENANT, "c1", HOSTILE, "image/png", "user-1", size_bytes=1024)

        assert result["file_key"] == f"{TENANT}/claims/c1/{EXPECTED}"
        assert storage.presigned_upload.call_args.args[0] == result["file_key"]
        assert create.call_args.args[0]["file_name"] == EXPECTED

    def test_manifest_evidence(self):
        from services.manifest import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_manifest_by_id", return_value={"id": "m1"}),
            patch.object(service.repo, "create_manifest_evidence", return_value={"id": "e1"}) as create,
        ):
            service.generate_evidence_upload(TENANT, "m1", HOSTILE, "image/png", "user-1", size_bytes=1024)

        assert storage.presigned_upload.call_args.args[0] == f"{TENANT}/manifests/m1/{EXPECTED}"
        assert create.call_args.args[1]["file_name"] == EXPECTED

    def test_container_document(self):
        from services.tracking import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_container_by_id", return_value={"id": "k1"}),
            patch.object(service.repo, "create_container_document", return_value={"id": "d1"}) as create,
        ):
            result = service.generate_document_presigned_url(
                TENANT, "k1", HOSTILE, "application/pdf", next(iter(service._ALLOWED_DOCUMENT_TYPES)), "user-1", size_bytes=1024
            )

        assert result["s3_key"] == f"{TENANT}/containers/k1/{EXPECTED}"
        assert storage.presigned_upload.call_args.args[0] == result["s3_key"]
        assert create.call_args.args[1]["filename"] == EXPECTED

    def test_payment_claim_evidence(self):
        from services.payment_release import service

        storage = _storage()
        ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=UserRole.NIGERIA_OFFICE_STAFF)
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_billing_by_id", return_value={"id": "b1", "customer_id": "cu1"}),
        ):
            result = service.generate_payment_claim_upload_url(TENANT, "b1", HOSTILE, "image/png", ctx, size_bytes=1024)

        assert result["file_key"] == f"{TENANT}/payment-claims/b1/{EXPECTED}"

    def test_unusable_filename_is_a_422_before_any_storage_call(self):
        from services.claims import service

        storage = _storage()
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_damage_claim_by_id", return_value={"id": "c1"}),
            pytest.raises(ValidationError),
        ):
            service.generate_presigned_url(TENANT, "c1", "..", "image/png", "user-1", size_bytes=1024)
        storage.presigned_upload.assert_not_called()


class TestDownloadHeadersAreSafeForLegacyRows:
    """Rows written before the fix may hold an unsafe name; the header must still be safe."""

    def test_payment_claim_evidence_content_disposition(self):
        from services.payment_release import service

        storage = _storage()
        ctx = TenantContext(tenant_id=TENANT, user_id="user-1", role=UserRole.NIGERIA_OFFICE_STAFF)
        claim = {
            "id": "cl1",
            "billing_id": "b1",
            "evidence_file_key": f"{TENANT}/payment-claims/b1/x.png",
            "evidence_file_name": "x\"; filename*=UTF-8''evil.html",
        }
        with (
            patch.object(service, "get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_payment_claim_by_id", return_value=claim),
            patch.object(service.repo, "get_billing_by_id", return_value={"id": "b1", "customer_id": "cu1"}),
        ):
            service.get_payment_claim_evidence_url(TENANT, "cl1", ctx)

        disposition = storage.presigned_get_url.call_args.kwargs["response_content_disposition"]
        assert disposition.count('"') == 2  # only the two quotes we add ourselves
        assert "filename*" not in disposition

    def test_container_document_content_disposition(self):
        from services.tracking import service

        storage = _storage()
        doc = {"id": "d1", "s3_key": f"{TENANT}/containers/k1/x.pdf", "filename": 'x".pdf\r\nX-Evil: 1'}
        with (
            patch.object(service, "get_storage_provider", return_value=storage),
            patch.object(service.repo, "get_container_by_id", return_value={"id": "k1"}),
            patch.object(service.repo, "get_container_document_by_id", return_value=doc),
            patch.object(service, "log_audit"),
        ):
            service.get_document_download_url(TENANT, "k1", "d1", "user-1", "tenant_admin")

        disposition = storage.presigned_get_url.call_args.kwargs["response_content_disposition"]
        assert disposition.count('"') == 2
        assert "\r" not in disposition
        assert "\n" not in disposition
