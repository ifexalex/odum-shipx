"""Microsoft Entra IdentityProvider — the Azure analogue of the Cognito
user/group provisioning adapter (ADR-004 Phase 4).

Talks to Microsoft Graph (v1.0). Auth is a bearer token from
`azure-identity` (DefaultAzureCredential — the Container Apps managed identity in
prod, `az login` / a service principal locally); Graph calls go over stdlib
`urllib` so no HTTP dependency is added. Roles are modelled as **security groups**
named `{tenant_id}:{role}` — the faithful mirror of the Cognito group model, so
the `sync_user_groups` reconcile logic is identical.

Entra divergences from Cognito, handled here:
  - Users are created with a `passwordProfile` (`forceChangePasswordNextSignIn`)
    — the "invite to set a password" analogue; Entra has no Cognito-style invite
    email out of the box (SSPR/invitation flows are tenant-config, documented).
  - `username` is the user's UPN/email (the "email immutable" identifier);
    methods resolve it to the Graph object id as needed.

Behaviour is mocked-unit-tested (stubbed token + urlopen); end-to-end
verification needs a real Entra tenant (see infrastructure/azure/README.md and
the Phase-4 setup checklist in docs/project docs/18_cicd_pipeline.md).
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_GRAPH_BASE = os.environ.get("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class EntraIdentityProvider:
    """IdentityProvider backed by Microsoft Graph for user/group provisioning."""

    def __init__(self) -> None:
        # The verified/managed domain that user principal names are formed under
        # when the email's own domain is not a verified domain in the tenant.
        self._user_domain = os.environ.get("ENTRA_USER_DOMAIN", "")
        self._credential: Any = None

    # ------------------------------------------------------------------
    # Graph plumbing
    # ------------------------------------------------------------------

    def _get_credential(self) -> Any:
        if self._credential is None:
            from azure.identity import DefaultAzureCredential

            self._credential = DefaultAzureCredential()
        return self._credential

    def _token(self) -> str:
        return str(self._get_credential().get_token(_GRAPH_SCOPE).token)

    def _graph(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """Call Graph and return parsed JSON (or None for an empty 2xx body).

        Normalizes failures to the same exceptions the Cognito adapter raises:
        409 → DuplicateResourceError, anything else → ExternalServiceError.
        """
        from shared.exceptions import DuplicateResourceError, ExternalServiceError

        url = f"{_GRAPH_BASE}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token()}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - Graph host only
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise DuplicateResourceError("user", path) from exc
            detail = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
            logger.warning("Graph %s %s failed: %s %s", method, path, exc.code, detail)
            raise ExternalServiceError("Entra", f"{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ExternalServiceError("Entra", str(exc)) from exc

    def _upn(self, email: str) -> str:
        """Form the userPrincipalName. Uses the email directly when it is already
        under the tenant's verified domain, else `local#EXT#@domain`-style under
        the configured managed domain."""
        if not self._user_domain or email.endswith(f"@{self._user_domain}"):
            return email
        local = email.replace("@", "_")
        return f"{local}@{self._user_domain}"

    def _resolve_user_id(self, username: str) -> str:
        """Resolve a UPN/email to the Graph object id."""
        user = self._graph("GET", f"/users/{urllib.parse.quote(username)}")
        return str(user["id"]) if user else ""

    def _group_id(self, group_name: str) -> str | None:
        flt = urllib.parse.quote(f"displayName eq '{group_name}'")
        result = self._graph("GET", f"/groups?$filter={flt}&$select=id")
        values = (result or {}).get("value", [])
        return str(values[0]["id"]) if values else None

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def _create(self, email: str, full_name: str, tenant_id: str, role: str, password: str, force_change: bool) -> str:
        upn = self._upn(email)
        body = {
            "accountEnabled": True,
            "displayName": full_name,
            "mailNickname": email.split("@")[0],
            "userPrincipalName": upn,
            "mail": email,
            "passwordProfile": {
                "password": password,
                "forceChangePasswordNextSignIn": force_change,
            },
        }
        created = self._graph("POST", "/users", body)
        sub = str(created["id"])
        # Reconcile the user's role group so the token carries {tenant_id}:{role}.
        self.sync_user_groups(upn, tenant_id, {role})
        logger.info("Entra user created: tenant_id=%s role=%s oid=%s", tenant_id, role, sub)
        return sub

    def create_user(self, email: str, full_name: str, tenant_id: str, role: str) -> str:
        # No native invite email; create with a random password + forced change
        # (the migration/invite flow drives the password-set email — see the script).
        import secrets

        return self._create(email, full_name, tenant_id, role, secrets.token_urlsafe(24), force_change=True)

    def create_user_with_password(self, email: str, full_name: str, tenant_id: str, role: str, password: str) -> str:
        return self._create(email, full_name, tenant_id, role, password, force_change=False)

    def update_user_attributes(self, username: str, full_name: str | None = None, role: str | None = None) -> None:
        """Update the display name. The primary role lives in group membership
        (`sync_user_groups`), not a mutable attribute, so a `role` change here is
        a no-op — callers reconcile groups separately (parity with how the token's
        role claim is sourced)."""
        if full_name is not None:
            self._graph("PATCH", f"/users/{urllib.parse.quote(username)}", {"displayName": full_name})

    def disable_user(self, username: str) -> None:
        self._graph("PATCH", f"/users/{urllib.parse.quote(username)}", {"accountEnabled": False})

    def enable_user(self, username: str) -> None:
        self._graph("PATCH", f"/users/{urllib.parse.quote(username)}", {"accountEnabled": True})

    def global_sign_out(self, username: str) -> None:
        """Revoke all refresh/session tokens. Missing user is a no-op."""
        from shared.exceptions import ExternalServiceError

        try:
            self._graph("POST", f"/users/{urllib.parse.quote(username)}/revokeSignInSessions")
        except ExternalServiceError as exc:
            if "404" in str(exc):
                return
            raise

    def resend_invite(self, username: str) -> None:
        """Re-trigger the password set: force a change on next sign-in. The actual
        email is driven by the tenant's invitation/SSPR config (documented)."""
        self._graph(
            "PATCH",
            f"/users/{urllib.parse.quote(username)}",
            {"passwordProfile": {"forceChangePasswordNextSignIn": True}},
        )

    def reset_password(self, username: str) -> None:
        """Entra password reset is self-service (SSPR) or admin-initiated via
        passwordProfile; force a change on next sign-in."""
        self.resend_invite(username)

    # ------------------------------------------------------------------
    # Groups (roles)
    # ------------------------------------------------------------------

    def create_group_if_not_exists(self, group_name: str) -> None:
        if self._group_id(group_name) is not None:
            return
        self._graph(
            "POST",
            "/groups",
            {
                "displayName": group_name,
                "mailEnabled": False,
                "mailNickname": group_name.replace(":", "-"),
                "securityEnabled": True,
            },
        )
        logger.info("Entra group created: %s", group_name)

    def add_user_to_group(self, username: str, group_name: str) -> None:
        gid = self._group_id(group_name)
        uid = self._resolve_user_id(username)
        if not gid or not uid:
            return
        self._graph(
            "POST",
            f"/groups/{gid}/members/$ref",
            {"@odata.id": f"{_GRAPH_BASE}/directoryObjects/{uid}"},
        )

    def remove_user_from_group(self, username: str, group_name: str) -> None:
        from shared.exceptions import ExternalServiceError

        gid = self._group_id(group_name)
        uid = self._resolve_user_id(username)
        if not gid or not uid:
            return
        try:
            self._graph("DELETE", f"/groups/{gid}/members/{uid}/$ref")
        except ExternalServiceError as exc:
            if "404" in str(exc):
                return
            raise

    def list_groups_for_user(self, username: str) -> set[str]:
        uid = self._resolve_user_id(username)
        if not uid:
            return set()
        result = self._graph("GET", f"/users/{uid}/memberOf?$select=displayName")
        return {g["displayName"] for g in (result or {}).get("value", []) if g.get("displayName")}

    def sync_user_groups(self, username: str, tenant_id: str, roles: set[str]) -> None:
        """Reconcile the user's role groups to exactly `roles`, scoped to this
        tenant's `{tenant_id}:*` — identical logic to the Cognito adapter so a
        role change actually takes effect in the token."""
        prefix = f"{tenant_id}:"
        current = {g for g in self.list_groups_for_user(username) if g.startswith(prefix)}
        desired = {f"{prefix}{role}" for role in roles}
        for group_name in desired - current:
            self.create_group_if_not_exists(group_name)
            self.add_user_to_group(username, group_name)
        for group_name in current - desired:
            self.remove_user_from_group(username, group_name)
