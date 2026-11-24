"""The shared upload helper (audit BE-12): one set of rules for every direct-to-storage upload."""

import re
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
        key = uploads.upload_key(TENANT, ("claims", "c1"), "../../etc/pass wd.png")
        assert re.fullmatch(f"{TENANT}/claims/c1/[0-9a-f]{{32}}-pass wd.png", key)

    def test_two_uploads_of_one_name_get_different_keys(self):
        assert uploads.upload_key(TENANT, ("claims", "c1"), "a.png") != uploads.upload_key(TENANT, ("claims", "c1"), "a.png")

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
            upload = uploads.presign_upload(
                uploads.CONTAINER_DOCUMENT, TENANT, ("containers", "k1"), "bl.pdf", "application/pdf", 2048
            )
        storage.presigned_upload.assert_called_once_with(
            upload.key,
            content_type="application/pdf",
            expires_in=uploads.CONTAINER_DOCUMENT.expires_in,
            content_length=2048,
        )
        assert re.fullmatch(f"{TENANT}/containers/k1/[0-9a-f]{{32}}-bl.pdf", upload.key)
        assert upload.filename == "bl.pdf"
        assert upload.as_response()["upload_url"] == "https://storage.test/put"

    def test_a_refused_type_never_reaches_storage(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage), pytest.raises(BusinessRuleViolationError):
            uploads.presign_upload(uploads.EVIDENCE, TENANT, ("claims", "c1"), "a.exe", "application/x-msdownload", 10)
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


class TestSizeLimit:
    """Every upload is limited to 5 MB, declared at presign and checked again where the stored file is used."""

    def test_the_limit_is_5_mb_on_every_policy(self):
        assert uploads.MAX_UPLOAD_BYTES == 5 * 1024 * 1024
        assert {p.max_bytes for p in POLICIES} == {uploads.MAX_UPLOAD_BYTES}

    def test_exactly_the_limit_is_accepted(self):
        assert uploads.EVIDENCE.check_size(uploads.MAX_UPLOAD_BYTES) == uploads.MAX_UPLOAD_BYTES

    def test_one_byte_over_is_refused(self):
        with pytest.raises(BusinessRuleViolationError) as caught:
            uploads.EVIDENCE.check_size(uploads.MAX_UPLOAD_BYTES + 1)
        assert caught.value.rule_id == "FILE_TOO_LARGE" and "5 MB" in str(caught.value)

    @pytest.mark.parametrize("size", [None, 0, -1, "100", 1.5, True])
    def test_a_missing_or_nonsense_size_is_refused(self, size):
        from shared.exceptions import ValidationError

        with pytest.raises(ValidationError):
            uploads.EVIDENCE.check_size(size)

    def test_the_declared_size_is_signed_into_the_url(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            uploads.presign_upload(uploads.EVIDENCE, TENANT, ("claims", "c1"), "a.png", "image/png", 4096)
        assert storage.presigned_upload.call_args.kwargs["content_length"] == 4096

    def test_an_oversize_request_never_reaches_storage(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage), pytest.raises(BusinessRuleViolationError):
            uploads.presign_upload(uploads.EVIDENCE, TENANT, ("claims", "c1"), "a.png", "image/png", 6 * 1024 * 1024)
        storage.presigned_upload.assert_not_called()

    @pytest.mark.parametrize(("stored", "rule"), [(None, "UPLOAD_NOT_FOUND"), (5 * 1024 * 1024 + 1, "FILE_TOO_LARGE")])
    def test_the_stored_file_is_checked_where_it_is_used(self, stored, rule):
        storage = MagicMock()
        storage.object_size.return_value = stored
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            uploads.check_stored_size(uploads.EVIDENCE, f"{TENANT}/payment-claims/b1/a.png")
        assert caught.value.rule_id == rule

    def test_a_stored_file_within_the_limit_passes(self):
        storage = MagicMock()
        storage.object_size.return_value = 1234
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            assert uploads.check_stored_size(uploads.EVIDENCE, "k") == 1234

    def test_a_payment_claim_with_an_oversize_stored_file_is_refused(self):
        # An Azure upload is not bound to its declared size; the claim checks the stored file.
        from services.payment_release import service

        req = MagicMock(evidence_file_key=f"{TENANT}/payment-claims/b1/a.png", amount_ngn=1000)
        with (
            patch.object(service.repo, "get_billing_by_id", return_value={"id": "b1", "status": "unpaid", "customer_id": "cu1"}),
            patch.object(service, "_customer_owns_billing", return_value=True),
            patch("shared.uploads.check_stored_size", side_effect=BusinessRuleViolationError("big", rule_id="FILE_TOO_LARGE")),
            patch.object(service.repo, "create_payment_claim") as create,
            pytest.raises(BusinessRuleViolationError),
        ):
            service.submit_payment_claim(TENANT, "b1", req, actor_id="u1", ctx=MagicMock())
        create.assert_not_called()

    def test_an_import_with_an_oversize_stored_file_is_refused_before_reading(self):
        from services.excel import service

        storage = MagicMock()
        with (
            patch("shared.uploads.check_stored_size", side_effect=BusinessRuleViolationError("big", rule_id="FILE_TOO_LARGE")),
            patch.object(service, "get_storage_provider", return_value=storage),
            pytest.raises(BusinessRuleViolationError),
        ):
            service.process_manifest_import(TENANT, f"{TENANT}/imports/x.xlsx", actor_id="u1", ctx=MagicMock())
        storage.get_object.assert_not_called()


class TestConfirmStoredUpload:
    """The check that holds on Azure, where the upload URL cannot bind the file's length."""

    def test_returns_the_stored_size(self):
        storage = _storage()
        storage.object_size.return_value = 2048
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            assert uploads.confirm_stored_upload(uploads.EVIDENCE, "k") == 2048
        storage.delete_object.assert_not_called()

    def test_a_missing_file_is_refused_and_nothing_is_deleted(self):
        storage = _storage()
        storage.object_size.return_value = None
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            uploads.confirm_stored_upload(uploads.EVIDENCE, "k")
        assert caught.value.rule_id == "UPLOAD_NOT_FOUND"
        storage.delete_object.assert_not_called()

    def test_a_file_over_the_limit_is_deleted_and_refused(self):
        storage = _storage()
        storage.object_size.return_value = uploads.MAX_UPLOAD_BYTES + 1
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            uploads.confirm_stored_upload(uploads.CONTAINER_DOCUMENT, "k")
        assert caught.value.rule_id == "FILE_TOO_LARGE"
        storage.delete_object.assert_called_once_with("k")

    def test_a_file_exactly_at_the_limit_is_kept(self):
        storage = _storage()
        storage.object_size.return_value = uploads.MAX_UPLOAD_BYTES
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            assert uploads.confirm_stored_upload(uploads.EVIDENCE, "k") == uploads.MAX_UPLOAD_BYTES
        storage.delete_object.assert_not_called()
