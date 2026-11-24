"""The tenant logo (FD-29): upload under the tenant prefix, confirm, store, show through a link, never lose it."""

from unittest.mock import MagicMock, patch

import pytest

from services.tenant_management import branding_logo
from shared import uploads
from shared.exceptions import BusinessRuleViolationError, ValidationError
from shared.providers.base import UploadTicket

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PREFIX = f"{TENANT}/branding/logo/"


def _storage(size: int | None = 20_000) -> MagicMock:
    storage = MagicMock()
    storage.presigned_upload.return_value = UploadTicket(url="https://storage.test/put", method="PUT", headers={})
    storage.presigned_get_url.side_effect = lambda key, expires_in: f"https://storage.test/get/{key}"
    storage.object_size.return_value = size
    return storage


def _configs(branding: dict | None) -> list[dict]:
    return [] if branding is None else [{"config_key": "branding_config", "config_value": branding}]


class TestPolicy:
    @pytest.mark.parametrize("content_type", ["image/png", "image/jpeg", "image/webp"])
    def test_raster_images_are_accepted(self, content_type):
        uploads.TENANT_LOGO.check(content_type, 50_000)

    @pytest.mark.parametrize("content_type", ["image/svg+xml", "application/pdf", "text/html"])
    def test_svg_and_other_types_are_refused(self, content_type):
        with pytest.raises(BusinessRuleViolationError) as caught:
            uploads.TENANT_LOGO.check(content_type, 50_000)
        assert caught.value.rule_id == "INVALID_CONTENT_TYPE"

    def test_over_five_megabytes_is_refused(self):
        with pytest.raises(BusinessRuleViolationError) as caught:
            uploads.TENANT_LOGO.check("image/png", 5 * 1024 * 1024 + 1)
        assert caught.value.rule_id == "FILE_TOO_LARGE"

    def test_a_logo_up_to_five_megabytes_is_accepted(self):
        uploads.TENANT_LOGO.check("image/png", 5 * 1024 * 1024)


class TestUpload:
    def test_presigns_under_the_tenant_logo_prefix(self):
        storage = _storage()
        with patch("shared.uploads.get_storage_provider", return_value=storage):
            result = branding_logo.create_logo_upload(TENANT, "acme logo.png", "image/png", 20_000)
        assert result["file_key"].startswith(PREFIX)
        assert result["upload_url"] == "https://storage.test/put"
        assert storage.presigned_upload.call_args.kwargs["content_length"] == 20_000


class TestSetLogo:
    def _set(self, file_key: str, stored: dict | None = None, size: int | None = 20_000):
        storage = _storage(size)
        saved: dict = {}
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            patch.object(branding_logo, "get_storage_provider", return_value=storage),
            patch.object(branding_logo.repo, "get_all_configs", return_value=_configs(stored)),
            patch.object(branding_logo.repo, "upsert_config", side_effect=lambda t, k, v, updated_by=None: saved.update({k: v})),
            patch.object(branding_logo.repo, "update_tenant") as update_tenant,
            patch.object(branding_logo, "log_audit") as audit,
        ):
            result = branding_logo.set_logo(TENANT, file_key, actor_id="admin-1")
        return result, saved, storage, update_tenant, audit

    def test_stores_the_key_keeps_the_rest_and_returns_a_link(self):
        key = f"{PREFIX}abc-logo.png"
        result, saved, _, update_tenant, audit = self._set(key, stored={"display_name": "Acme", "primary_color": "#123456"})
        assert saved["branding_config"] == {"display_name": "Acme", "primary_color": "#123456", "logo_key": key}
        assert update_tenant.called
        assert result["logo_url"] == f"https://storage.test/get/{key}"
        assert "logo_key" not in result
        assert audit.call_args.kwargs["after_state"] == {"action": "logo_set"}

    def test_deletes_the_logo_it_replaces(self):
        old = f"{PREFIX}old-logo.png"
        _, _, storage, _, _ = self._set(f"{PREFIX}new-logo.png", stored={"logo_key": old})
        storage.delete_object.assert_called_once_with(old)

    @pytest.mark.parametrize(
        "file_key",
        [
            f"{OTHER}/branding/logo/abc-logo.png",  # another tenant's file
            f"{TENANT}/claims/abc/photo.png",  # this tenant, not a logo
            f"{PREFIX}../../claims/abc/photo.png",  # walks out of the prefix
            f"{PREFIX}nested/logo.png",
            PREFIX,
        ],
    )
    def test_refuses_a_key_that_is_not_this_tenants_logo_upload(self, file_key):
        with pytest.raises(ValidationError):
            self._set(file_key)

    def test_refuses_an_upload_that_never_landed(self):
        with pytest.raises(BusinessRuleViolationError) as caught:
            self._set(f"{PREFIX}abc-logo.png", size=None)
        assert caught.value.rule_id == "UPLOAD_NOT_FOUND"

    def test_deletes_and_refuses_an_oversize_file(self):
        key = f"{PREFIX}abc-logo.png"
        storage = _storage(6 * 1024 * 1024)
        with (
            patch("shared.uploads.get_storage_provider", return_value=storage),
            pytest.raises(BusinessRuleViolationError) as caught,
        ):
            branding_logo.set_logo(TENANT, key, actor_id="admin-1")
        assert caught.value.rule_id == "FILE_TOO_LARGE"
        storage.delete_object.assert_called_once_with(key)


class TestRemoveLogo:
    def test_drops_the_key_and_deletes_the_file(self):
        old = f"{PREFIX}old-logo.png"
        storage = _storage()
        saved: dict = {}
        with (
            patch.object(branding_logo, "get_storage_provider", return_value=storage),
            patch.object(branding_logo.repo, "get_all_configs", return_value=_configs({"display_name": "Acme", "logo_key": old})),
            patch.object(branding_logo.repo, "upsert_config", side_effect=lambda t, k, v, updated_by=None: saved.update({k: v})),
            patch.object(branding_logo.repo, "update_tenant"),
            patch.object(branding_logo, "log_audit"),
        ):
            result = branding_logo.remove_logo(TENANT, actor_id="admin-1")
        assert saved["branding_config"] == {"display_name": "Acme"}
        storage.delete_object.assert_called_once_with(old)
        assert "logo_url" not in result


class TestReadersAndWriters:
    def test_readers_get_a_link_never_the_key(self):
        storage = _storage()
        with patch.object(branding_logo, "get_storage_provider", return_value=storage):
            shown = branding_logo.with_logo_url(TENANT, {"display_name": "Acme", "logo_key": f"{PREFIX}a-logo.png"})
        assert shown == {"display_name": "Acme", "logo_url": f"https://storage.test/get/{PREFIX}a-logo.png"}

    def test_a_key_outside_the_tenant_prefix_is_never_signed(self):
        storage = _storage()
        with patch.object(branding_logo, "get_storage_provider", return_value=storage):
            shown = branding_logo.with_logo_url(TENANT, {"logo_key": f"{OTHER}/branding/logo/a-logo.png"})
        assert shown == {}
        storage.presigned_get_url.assert_not_called()

    def test_a_branding_save_keeps_the_stored_logo_and_ignores_one_sent_by_the_client(self):
        from services.tenant_management import service
        from services.tenant_management.models import UpdateTenantConfigRequest

        stored = {"display_name": "Acme", "logo_key": f"{PREFIX}a-logo.png"}
        saved: dict = {}
        with (
            patch.object(service.repo, "get_all_configs", return_value=_configs(stored)),
            patch.object(branding_logo.repo, "get_all_configs", return_value=_configs(stored)),
            patch.object(service.repo, "upsert_config", side_effect=lambda t, k, v, updated_by=None: saved.update({k: v})),
            patch.object(service.repo, "update_tenant"),
            patch.object(branding_logo, "get_storage_provider", return_value=_storage()),
        ):
            req = UpdateTenantConfigRequest(
                branding={
                    "display_name": "Acme Cargo",
                    "logo_key": f"{OTHER}/branding/logo/theirs.png",
                    "logo_url": "https://evil.example/x.png",
                }
            )
            service.update_tenant_config(TENANT, req, actor_id="admin-1")
        assert saved["branding_config"] == {"display_name": "Acme Cargo", "logo_key": f"{PREFIX}a-logo.png"}
