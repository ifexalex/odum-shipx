"""Unit tests for shared/providers/azure/entra.py — the Entra IdentityProvider.
Graph is stubbed (the `_graph` method is patched, or urlopen+token for the one
error-mapping test); no credential or network is used."""

import io
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from shared.exceptions import DuplicateResourceError, ExternalServiceError
from shared.providers import get_claims_mapper, get_identity_provider
from shared.providers.azure.entra import EntraIdentityProvider


def _provider_with_stubbed_graph():
    p = EntraIdentityProvider()
    p._graph = MagicMock()  # noqa: SLF001
    return p


class TestUserLifecycle:
    def test_create_with_password_posts_user_and_syncs_group(self):
        p = _provider_with_stubbed_graph()
        # Stub sync_user_groups (its own reconcile logic is covered separately);
        # the POST /users call returns the new object id.
        p.sync_user_groups = MagicMock()  # noqa: SLF001
        p._graph.side_effect = [{"id": "oid-1"}]  # noqa: SLF001

        uid = p.create_user_with_password("a@x.com", "Ann", "t1", "tenant_admin", "P@ssw0rd!")

        assert uid == "oid-1"
        args = p._graph.call_args_list[0]  # noqa: SLF001
        assert args.args[0] == "POST" and args.args[1] == "/users"
        body = args.args[2]
        assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is False
        p.sync_user_groups.assert_called_once()  # noqa: SLF001

    def test_create_user_forces_password_change(self):
        p = _provider_with_stubbed_graph()
        p.sync_user_groups = MagicMock()  # noqa: SLF001
        p._graph.side_effect = [{"id": "oid-2"}]  # noqa: SLF001
        p.create_user("b@x.com", "Bob", "t1", "customer")
        body = p._graph.call_args_list[0].args[2]  # noqa: SLF001
        assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is True

    def test_disable_and_enable_patch_account_enabled(self):
        p = _provider_with_stubbed_graph()
        p.disable_user("a@x.com")
        p.enable_user("a@x.com")
        assert p._graph.call_args_list[0].args[2] == {"accountEnabled": False}  # noqa: SLF001
        assert p._graph.call_args_list[1].args[2] == {"accountEnabled": True}  # noqa: SLF001


class TestGroupSync:
    def test_sync_adds_missing_and_removes_extra_scoped_to_tenant(self):
        p = _provider_with_stubbed_graph()
        # Current groups for the user: one in-tenant role + one other-tenant group.
        p.list_groups_for_user = MagicMock(return_value={"t1:customer", "t2:tenant_admin"})  # noqa: SLF001
        p.create_group_if_not_exists = MagicMock()  # noqa: SLF001
        p.add_user_to_group = MagicMock()  # noqa: SLF001
        p.remove_user_from_group = MagicMock()  # noqa: SLF001

        p.sync_user_groups("a@x.com", "t1", {"tenant_admin"})

        # Adds the desired t1 role, removes the stale t1 role, leaves t2 untouched.
        p.add_user_to_group.assert_called_once_with("a@x.com", "t1:tenant_admin")  # noqa: SLF001
        p.remove_user_from_group.assert_called_once_with("a@x.com", "t1:customer")  # noqa: SLF001


class TestErrorMapping:
    def _run_graph(self, http_error_code: int):
        p = EntraIdentityProvider()
        p._credential = MagicMock()  # noqa: SLF001
        p._credential.get_token.return_value = MagicMock(token="tok")  # noqa: SLF001
        err = urllib.error.HTTPError(
            url="https://graph", code=http_error_code, msg="x", hdrs=None, fp=io.BytesIO(b'{"error":"e"}')
        )
        with patch("urllib.request.urlopen", side_effect=err):
            return p._graph("POST", "/users", {"x": 1})  # noqa: SLF001

    def test_409_maps_to_duplicate(self):
        with pytest.raises(DuplicateResourceError):
            self._run_graph(409)

    def test_other_maps_to_external_service_error(self):
        with pytest.raises(ExternalServiceError):
            self._run_graph(500)


class TestFactory:
    def test_factory_selects_entra_when_cloud_is_azure(self, monkeypatch):
        import shared.providers as providers

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_identity_provider", None)
        monkeypatch.setattr(providers, "_claims_mapper", None)
        assert isinstance(get_identity_provider(), EntraIdentityProvider)
        from shared.providers.azure.entra_claims import EntraClaimsMapper

        assert isinstance(get_claims_mapper(), EntraClaimsMapper)

    def test_auth_provider_decouples_from_cloud_provider(self, monkeypatch):
        # Bridge: infra on Azure, auth still on Cognito (AUTH_PROVIDER=aws).
        import shared.providers as providers
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_claims_mapper", None)
        monkeypatch.setattr(providers, "_identity_provider", None)
        assert isinstance(get_claims_mapper(), CognitoClaimsMapper)
