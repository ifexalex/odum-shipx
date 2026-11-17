"""The shared upload helper (audit BE-12): one set of rules for every direct-to-storage upload."""

from unittest.mock import MagicMock, patch

import pytest

from shared import uploads
from shared.exceptions import BusinessRuleViolationError
from shared.providers.base import UploadTicket

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
POLICIES = [uploads.EVIDENCE, uploads.CONTAINER_DOCUMENT, uploads.SPREADSHEET_IMPORT]


def _storage() -> MagicMock:
    storage = MagicMock()
    storage.presigned_upload.return_value = UploadTicket(url="https://storage.test/put", method="PUT", headers={})
    return storage


class TestContentTypes:
    @pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.name)
    def test_unknown_type_is_refused_everywhere(self, policy):
        # It used to be allowed for container documents, which let any file through the type check.
        with pytest.raises(BusinessRuleViolationError) as caught:
            policy.check_content_type("application/octet-stream")
        assert caught.value.rule_id == "INVALID_CONTENT_TYPE"

    def test_a_policy_cannot_be_declared_with_the_unknown_type(self):
        with pytest.raises(ValueError, match="octet-stream"):
            uploads.UploadPolicy(name="x", content_types=frozenset({"application/octet-stream"}), expires_in=60)

    @pytest.mark.parametrize(
        ("policy", "content_type"),
        [
            (uploads.EVIDENCE, "image/jpeg"),
            (uploads.EVIDENCE, "application/pdf"),
            (uploads.CONTAINER_DOCUMENT, "image/webp"),
            (uploads.SPREADSHEET_IMPORT, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ],
    )
    def test_listed_types_pass(self, policy, content_type):
        policy.check_content_type(content_type)

    def test_evidence_does_not_take_webp_or_html(self):
        for content_type in ("image/webp", "text/html", "image/svg+xml"):
            with pytest.raises(BusinessRuleViolationError):
                uploads.EVIDENCE.check_content_type(content_type)


class TestKeys:
    def test_key_is_under_the_tenant_prefix_with_a_safe_name(self):
        assert uploads.upload_key(TENANT, ("claims", "c1"), "../../etc/pass wd.png") == f"{TENANT}/claims/c1/pass wd.png"

    @pytest.mark.parametrize("segment", ["", "a/b", "..", "a\\b", "x..y"])
    def test_a_segment_that_could_change_the_key_structure_is_refused(self, segment):
        with pytest.raises(ValueError):
            uploads.upload_key(TENANT, ("claims", segment), "a.png")

    @pytest.mark.parametrize("tenant", ["", "PLATFORM", f"{TENANT}/other", "../" + TENANT])
    def test_the_prefix_must_be_a_tenant_id(self, tenant):
        with pytest.raises(ValueError):
            uploads.upload_key(tenant, ("claims", "c1"), "a.png")


class TestPresign:
    def test_signs_the_declared_type_for_the_policy_lifetime(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            upload = uploads.presign_upload(uploads.CONTAINER_DOCUMENT, TENANT, ("containers", "k1"), "bl.pdf", "application/pdf")
        storage.presigned_upload.assert_called_once_with(
            f"{TENANT}/containers/k1/bl.pdf", content_type="application/pdf", expires_in=uploads.CONTAINER_DOCUMENT.expires_in
        )
        assert upload.key == f"{TENANT}/containers/k1/bl.pdf"
        assert upload.as_response()["upload_url"] == "https://storage.test/put"

    def test_a_refused_type_never_reaches_storage(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage), pytest.raises(BusinessRuleViolationError):
            uploads.presign_upload(uploads.EVIDENCE, TENANT, ("claims", "c1"), "a.exe", "application/x-msdownload")
        storage.presigned_upload.assert_not_called()


class TestTheServicesUseIt:
    """Each upload endpoint refuses the unknown type before touching the database."""

    @pytest.mark.parametrize(
        ("module", "call"),
        [
            ("claims", lambda s: s.generate_presigned_url(TENANT, "c1", "a.bin", "application/octet-stream", "u1")),
            ("manifest", lambda s: s.generate_evidence_upload(TENANT, "m1", "a.bin", "application/octet-stream", "u1")),
            (
                "tracking",
                lambda s: s.generate_document_presigned_url(
                    TENANT, "k1", "a.bin", "application/octet-stream", "bill_of_lading", "u1"
                ),
            ),
            ("excel", lambda s: s.generate_import_presigned_url(TENANT, "application/octet-stream")),
            (
                "payment_release",
                lambda s: s.generate_payment_claim_upload_url(TENANT, "b1", "a.bin", "application/octet-stream", MagicMock()),
            ),
        ],
    )
    def test_unknown_type(self, module, call):
        import importlib

        service = importlib.import_module(f"services.{module}.service")
        with (
            patch.object(service, "repo", MagicMock()) as repo,
            patch("shared.uploads.get_storage_provider") as storage,
            pytest.raises(BusinessRuleViolationError),
        ):
            call(service)
        storage.assert_not_called()
        assert not repo.method_calls
