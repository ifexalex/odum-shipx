"""Unit tests for the account-activation flow (operator-provisioned staff/admins
set their own password via a ShipX link). DB + IdP are mocked."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.tenant_management import service
from shared.exceptions import ResourceNotFoundError
from tests.patching import patch_tenant_management

_TENANT = "11111111-1111-1111-1111-111111111111"
_USER = "22222222-2222-2222-2222-222222222222"


def _valid_row():
    return {
        "id": "act-1",
        "tenant_id": _TENANT,
        "user_id": _USER,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "consumed_at": None,
    }


class TestIssueActivation:
    def test_mints_token_stores_row_and_emails_link(self):
        with (
            patch("shared.activation.delete_unconsumed") as del_mock,
            patch("shared.activation.mint_token", return_value="tok-123"),
            patch("shared.activation.create_activation") as create_mock,
            patch("shared.notifications.enqueue_notifications") as notify,
            patch.dict("os.environ", {"APP_BASE_URL": "https://app.shipx.test"}, clear=False),
        ):
            token = service.issue_activation(_TENANT, _USER, "admin@acme.com", "Jane Admin")

        assert token == "tok-123"
        del_mock.assert_called_once_with(_TENANT, _USER)
        create_mock.assert_called_once()
        notify.assert_called_once()
        kwargs = notify.call_args.kwargs
        assert kwargs["event_type"] == "account_activation"
        assert kwargs["recipient"]["email"] == "admin@acme.com"
        assert kwargs["template_data"]["activation_link"] == "https://app.shipx.test/activate/tok-123"

    def test_app_base_url_falls_back_to_redirect_uri_origin(self):
        with (
            patch("shared.activation.delete_unconsumed"),
            patch("shared.activation.mint_token", return_value="t"),
            patch("shared.activation.create_activation"),
            patch("shared.notifications.enqueue_notifications") as notify,
            patch.dict(
                "os.environ",
                {"APP_BASE_URL": "", "ENTRA_REDIRECT_URI": "https://fd.example.net/auth/callback"},
                clear=False,
            ),
        ):
            service.issue_activation(_TENANT, _USER, "a@b.com", "A B")
        assert notify.call_args.kwargs["template_data"]["activation_link"] == "https://fd.example.net/activate/t"


class TestActivateAccount:
    def test_sets_password_and_consumes_token(self):
        idp = MagicMock()
        with (
            patch("shared.activation.get_activation_by_token", return_value=_valid_row()),
            patch.object(service.repo, "get_user_by_id", return_value={"id": _USER, "email": "admin@acme.com"}),
            patch_tenant_management("get_identity_provider", return_value=idp),
            patch("shared.activation.consume_activation") as consume,
        ):
            result = service.activate_account("tok", "N3wPassw0rd!")

        assert result == {"email": "admin@acme.com"}
        idp.set_password.assert_called_once_with("admin@acme.com", "N3wPassw0rd!", force_change=False)
        consume.assert_called_once_with(_TENANT, "act-1")

    def test_invalid_or_expired_token_raises(self):
        expired = {**_valid_row(), "expires_at": datetime.now(UTC) - timedelta(hours=1)}
        with patch("shared.activation.get_activation_by_token", return_value=expired):
            with pytest.raises(ResourceNotFoundError):
                service.activate_account("tok", "whatever123")

    def test_unknown_token_raises(self):
        with patch("shared.activation.get_activation_by_token", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.activate_account("tok", "whatever123")


class TestResendActivation:
    def test_reissues_for_existing_user(self):
        with (
            patch.object(service.repo, "get_user_by_id", return_value={"id": _USER, "email": "a@b.com", "full_name": "A B"}),
            patch_tenant_management("issue_activation") as issue,
        ):
            result = service.resend_activation(_TENANT, _USER, actor_id="admin-1")
        issue.assert_called_once()
        assert result["email"] == "a***@b.com"

    def test_unknown_user_raises(self):
        with patch.object(service.repo, "get_user_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.resend_activation(_TENANT, _USER)


class TestActivationPreview:
    def test_returns_email_for_valid_token(self):
        with (
            patch("shared.activation.get_activation_by_token", return_value=_valid_row()),
            patch.object(service.repo, "get_user_by_id", return_value={"id": _USER, "email": "x@y.com", "full_name": "X Y"}),
        ):
            assert service.get_activation_preview("tok") == {"email": "x@y.com", "full_name": "X Y"}
