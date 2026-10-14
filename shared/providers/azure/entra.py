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


def email_to_upn(email: str, user_domain: str) -> str:
    """Map a login email to the userPrincipalName the user was provisioned under.

    Provisioning (`EntraIdentityProvider._create`) forms the UPN as the email
    verbatim when it is already under the tenant's verified domain, else
    `local_domain@<managed-domain>` (the `@` replaced with `_`). The login proxy
    reuses this so a user can sign in with their real email (e.g. alex@gmail.com)
    even though the account's sign-in name is alex_gmail.com@tenant.onmicrosoft.com.
    Idempotent: a value already ending in the managed domain is returned as-is, so
    passing the full UPN also works.
    """
    if not user_domain or email.endswith(f"@{user_domain}"):
        return email
    return f'{email.replace("@", "_")}@{user_domain}'


class EntraIdentityProvider:
    """IdentityProvider backed by Microsoft Graph for user/group provisioning."""

    def __init__(self) -> None:
        # The verified/managed domain that user principal names are formed under
        # when the email's own domain is not a verified domain in the tenant.
        # For local accounts it is also the identity `issuer` (the tenant's
        # initial *.onmicrosoft.com domain).
        self._user_domain = os.environ.get("ENTRA_USER_DOMAIN", "")
        # The project's Azure target is Entra External ID (B2C/CIAM), whose
        # interactive sign-in uses **local accounts** (creationType=LocalAccount
        # + an emailAddress identity) so users sign in with their real email and
        # no consumer-account federation is triggered. Set ENTRA_LOCAL_ACCOUNTS=
        # false only for a workforce tenant that wants member (UPN) accounts.
        self._local_accounts = os.environ.get("ENTRA_LOCAL_ACCOUNTS", "true").strip().lower() != "false"
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

    def _graph(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Call Graph and return parsed JSON (or None for an empty 2xx body).

        Normalizes failures to the same exceptions the Cognito adapter raises:
        409 → DuplicateResourceError, anything else → ExternalServiceError.
        `extra_headers` carries advanced-query headers (e.g. ConsistencyLevel)
        for the `identities` $filter that resolves B2C local accounts.
        """
        from shared.exceptions import DuplicateResourceError, ExternalServiceError

        url = f"{_GRAPH_BASE}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token()}")
        req.add_header("Content-Type", "application/json")
        for name, value in (extra_headers or {}).items():
            req.add_header(name, value)
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
        """Form the userPrincipalName (see module-level email_to_upn)."""
        return email_to_upn(email, self._user_domain)

    def _resolve_user_id(self, username: str) -> str:
        """Resolve an object id / UPN / email to the Graph object id.

        A direct GET works for an object id or a UPN (member accounts). For a
        B2C **local account** the email is not the UPN, so fall back to filtering
        on the emailAddress identity (needs the advanced-query headers).
        """
        from shared.exceptions import ExternalServiceError

        try:
            user = self._graph("GET", f"/users/{urllib.parse.quote(username)}")
            if user:
                return str(user["id"])
        except ExternalServiceError as exc:
            if "404" not in str(exc):
                raise  # a real failure, not just "not addressable by this key"

        if "@" not in username:
            return ""
        # Local-account lookup by email identity.
        flt = urllib.parse.quote(f"identities/any(i:i/issuerAssignedId eq '{username}' and i/issuer eq '{self._user_domain}')")
        result = self._graph(
            "GET",
            f"/users?$filter={flt}&$select=id&$count=true",
            extra_headers={"ConsistencyLevel": "eventual"},
        )
        values = (result or {}).get("value", [])
        return str(values[0]["id"]) if values else ""

    def _group_id(self, group_name: str) -> str | None:
        flt = urllib.parse.quote(f"displayName eq '{group_name}'")
        result = self._graph("GET", f"/groups?$filter={flt}&$select=id")
        values = (result or {}).get("value", [])
        return str(values[0]["id"]) if values else None

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def _create(self, email: str, full_name: str, tenant_id: str, role: str, password: str, force_change: bool) -> str:
        if self._local_accounts:
            # B2C/CIAM local account: sign-in name IS the email (emailAddress
            # identity), so the interactive flow prompts for a password locally
            # instead of federating the email to a consumer Microsoft account.
            if not self._user_domain:
                from shared.exceptions import ExternalServiceError

                raise ExternalServiceError("Entra", "ENTRA_USER_DOMAIN is required to create local accounts")
            body: dict[str, Any] = {
                "accountEnabled": True,
                "displayName": full_name,
                "creationType": "LocalAccount",
                "identities": [{"signInType": "emailAddress", "issuer": self._user_domain, "issuerAssignedId": email}],
                "passwordProfile": {"password": password, "forceChangePasswordNextSignIn": force_change},
            }
        else:
            # Workforce (member) account keyed by UPN.
            body = {
                "accountEnabled": True,
                "displayName": full_name,
                "mailNickname": email.split("@")[0],
                "userPrincipalName": self._upn(email),
                "mail": email,
                "passwordProfile": {"password": password, "forceChangePasswordNextSignIn": force_change},
            }
        created = self._graph("POST", "/users", body)
        sub = str(created["id"])
        # Reconcile the role group by object id (works for local + member accounts)
        # so the token carries {tenant_id}:{role}.
        self.sync_user_groups(sub, tenant_id, {role})
        logger.info("Entra user created: tenant_id=%s role=%s oid=%s local=%s", tenant_id, role, sub, self._local_accounts)
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
        if full_name is None:
            return
        uid = self._resolve_user_id(username)
        if uid:
            self._graph("PATCH", f"/users/{uid}", {"displayName": full_name})

    def disable_user(self, username: str) -> None:
        uid = self._resolve_user_id(username)
        if uid:
            self._graph("PATCH", f"/users/{uid}", {"accountEnabled": False})

    def enable_user(self, username: str) -> None:
        uid = self._resolve_user_id(username)
        if uid:
            self._graph("PATCH", f"/users/{uid}", {"accountEnabled": True})

    def global_sign_out(self, username: str) -> None:
        """Revoke all refresh/session tokens. Missing user is a no-op."""
        from shared.exceptions import ExternalServiceError

        uid = self._resolve_user_id(username)
        if not uid:
            return
        try:
            self._graph("POST", f"/users/{uid}/revokeSignInSessions")
        except ExternalServiceError as exc:
            if "404" in str(exc):
                return
            raise

    def resend_invite(self, username: str) -> None:
        """Re-trigger the password set: force a change on next sign-in. The actual
        email is driven by the tenant's invitation/SSPR config (documented)."""
        uid = self._resolve_user_id(username)
        if uid:
            self._graph(
                "PATCH",
                f"/users/{uid}",
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
