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

_DOMAIN = "tenant.onmicrosoft.com"


def _provider_with_stubbed_graph(local: bool = True):
    p = EntraIdentityProvider()
    p._user_domain = _DOMAIN  # noqa: SLF001
    p._local_accounts = local  # noqa: SLF001
    p._graph = MagicMock()  # noqa: SLF001
    return p


class TestUserLifecycle:
    def test_create_local_account_posts_email_identity_and_syncs_by_oid(self):
        p = _provider_with_stubbed_graph(local=True)
        p.sync_user_groups = MagicMock()  # noqa: SLF001
        p._graph.side_effect = [{"id": "oid-1"}]  # noqa: SLF001

        uid = p.create_user_with_password("a@gmail.com", "Ann", "t1", "tenant_admin", "P@ssw0rd!")

        assert uid == "oid-1"
        method, path, body = p._graph.call_args_list[0].args[:3]  # noqa: SLF001
        assert method == "POST" and path == "/users"
        assert body["creationType"] == "LocalAccount"
        assert body["identities"] == [{"signInType": "emailAddress", "issuer": _DOMAIN, "issuerAssignedId": "a@gmail.com"}]
        assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is False
        assert "userPrincipalName" not in body
        # Group reconcile is keyed on the object id, not email/UPN.
        p.sync_user_groups.assert_called_once_with("oid-1", "t1", {"tenant_admin"})  # noqa: SLF001

    def test_create_user_forces_password_change(self):
        p = _provider_with_stubbed_graph(local=True)
        p.sync_user_groups = MagicMock()  # noqa: SLF001
        p._graph.side_effect = [{"id": "oid-2"}]  # noqa: SLF001
        p.create_user("b@gmail.com", "Bob", "t1", "customer")
        body = p._graph.call_args_list[0].args[2]  # noqa: SLF001
        assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is True

    def test_member_account_mode_posts_upn(self):
        p = _provider_with_stubbed_graph(local=False)
        p.sync_user_groups = MagicMock()  # noqa: SLF001
        p._graph.side_effect = [{"id": "oid-3"}]  # noqa: SLF001
        p.create_user_with_password("c@gmail.com", "Cy", "t1", "customer", "P@ssw0rd!")
        body = p._graph.call_args_list[0].args[2]  # noqa: SLF001
        assert "creationType" not in body
        assert body["userPrincipalName"] == "c_gmail.com@tenant.onmicrosoft.com"

    def test_local_account_requires_user_domain(self):
        p = _provider_with_stubbed_graph(local=True)
        p._user_domain = ""  # noqa: SLF001
        with pytest.raises(ExternalServiceError):
            p.create_user_with_password("a@gmail.com", "Ann", "t1", "customer", "P@ssw0rd!")

    def test_disable_and_enable_resolve_then_patch(self):
        p = _provider_with_stubbed_graph()
        p._resolve_user_id = MagicMock(return_value="oid-7")  # noqa: SLF001
        p.disable_user("a@gmail.com")
        p.enable_user("a@gmail.com")
        assert p._graph.call_args_list[0].args[:2] == ("PATCH", "/users/oid-7")  # noqa: SLF001
        assert p._graph.call_args_list[0].args[2] == {"accountEnabled": False}  # noqa: SLF001
        assert p._graph.call_args_list[1].args[2] == {"accountEnabled": True}  # noqa: SLF001

    def test_disable_missing_user_is_noop(self):
        p = _provider_with_stubbed_graph()
        p._resolve_user_id = MagicMock(return_value="")  # noqa: SLF001
        p.disable_user("gone@gmail.com")
        p._graph.assert_not_called()  # noqa: SLF001


class TestResolveUserId:
    def test_resolves_local_account_by_email_identity(self):
        p = _provider_with_stubbed_graph()
        # Direct GET /users/{email} 404s (email isn't the UPN), then the
        # identities $filter finds the account.
        p._graph = MagicMock(  # noqa: SLF001
            side_effect=[
                ExternalServiceError("Entra", "404: not found"),
                {"value": [{"id": "oid-9"}]},
            ]
        )
        uid = p._resolve_user_id("a@gmail.com")  # noqa: SLF001
        assert uid == "oid-9"
        # The filter query carries the advanced-query consistency header.
        filter_call = p._graph.call_args_list[1]  # noqa: SLF001
        assert "identities/any" in filter_call.args[1]
        assert filter_call.kwargs["extra_headers"] == {"ConsistencyLevel": "eventual"}

    def test_direct_hit_returns_without_filter(self):
        p = _provider_with_stubbed_graph()
        p._graph = MagicMock(return_value={"id": "oid-upn"})  # noqa: SLF001
        assert p._resolve_user_id("c_gmail.com@tenant.onmicrosoft.com") == "oid-upn"  # noqa: SLF001
        p._graph.assert_called_once()  # noqa: SLF001


class TestGroupSync:
    def test_sync_adds_missing_and_removes_extra_scoped_to_tenant(self):
        p = _provider_with_stubbed_graph()
        p.list_groups_for_user = MagicMock(return_value={"t1:customer", "t2:tenant_admin"})  # noqa: SLF001
        p.create_group_if_not_exists = MagicMock()  # noqa: SLF001
        p.add_user_to_group = MagicMock()  # noqa: SLF001
        p.remove_user_from_group = MagicMock()  # noqa: SLF001

        p.sync_user_groups("oid-1", "t1", {"tenant_admin"})

        p.add_user_to_group.assert_called_once_with("oid-1", "t1:tenant_admin")  # noqa: SLF001
        p.remove_user_from_group.assert_called_once_with("oid-1", "t1:customer")  # noqa: SLF001


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
        import shared.providers as providers
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "AUTH_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_claims_mapper", None)
        monkeypatch.setattr(providers, "_identity_provider", None)
        assert isinstance(get_claims_mapper(), CognitoClaimsMapper)
