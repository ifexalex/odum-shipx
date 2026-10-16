"""Microsoft Entra IdentityProvider — the Azure analogue of the Cognito
user/group provisioning adapter (ADR-004 Phase 4).

Talks to Microsoft Graph (v1.0). Auth is a bearer token from `azure-identity`:
a ``ClientSecretCredential`` when ``ENTRA_GRAPH_TENANT_ID`` / ``ENTRA_GRAPH_
CLIENT_ID`` / ``ENTRA_GRAPH_CLIENT_SECRET`` are set (required to manage a tenant
the compute identity does not live in — e.g. provisioning into a CIAM tenant from
a Container App whose managed identity is in the subscription's home tenant),
else ``DefaultAzureCredential`` (the Container Apps managed identity in prod,
``az login`` locally). See ``_get_credential``. Graph calls go over stdlib
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
        # Account model. Default = member/UPN accounts, which every Entra tenant
        # supports (including workforce and the externalid/ciamlogin tenant used
        # here). Set ENTRA_LOCAL_ACCOUNTS=true only on an Azure AD B2C tenant that
        # has email sign-in / "name coexistence" enabled — there, local accounts
        # (creationType=LocalAccount + an emailAddress identity) let users sign in
        # with their real email and avoid consumer-account federation. On a tenant
        # without that feature, creating an email-only account fails
        # ("Name coexistence user creation is not enabled"), so this stays off.
        self._local_accounts = os.environ.get("ENTRA_LOCAL_ACCOUNTS", "false").strip().lower() == "true"
        self._credential: Any = None

    # ------------------------------------------------------------------
    # Graph plumbing
    # ------------------------------------------------------------------

    def _get_credential(self) -> Any:
        """Credential for Microsoft Graph calls.

        Prefers client-credentials (``ClientSecretCredential``) when
        ``ENTRA_GRAPH_TENANT_ID`` / ``ENTRA_GRAPH_CLIENT_ID`` /
        ``ENTRA_GRAPH_CLIENT_SECRET`` are set. This is required whenever the
        directory being managed is a *different* tenant from the one the compute
        identity lives in — e.g. provisioning users into an Entra External ID
        (CIAM) tenant from a Container App whose managed identity is in the
        subscription's home tenant. A managed identity is single-tenant and
        cannot mint a Graph token for a foreign tenant, so ``DefaultAzure
        Credential`` fails there ("Unable to load the proper Managed Identity").

        Falls back to ``DefaultAzureCredential`` (the Container Apps managed
        identity in prod, ``az login`` locally) when no app registration is
        configured — correct when the managed directory IS the compute's home
        tenant and the identity holds the Graph app-roles.
        """
        if self._credential is None:
            tenant_id = os.environ.get("ENTRA_GRAPH_TENANT_ID", "").strip()
            client_id = os.environ.get("ENTRA_GRAPH_CLIENT_ID", "").strip()
            client_secret = os.environ.get("ENTRA_GRAPH_CLIENT_SECRET", "").strip()
            if tenant_id and client_id and client_secret:
                from azure.identity import ClientSecretCredential

                self._credential = ClientSecretCredential(tenant_id, client_id, client_secret)
            else:
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
            detail = exc.read().decode(errors="replace") if hasattr(exc, "read") else str(exc)
            # Graph reports an existing object inconsistently: 409 on some routes,
            # but a 400 Request_BadRequest / ObjectConflict for a duplicate
            # userPrincipalName or identity. Normalise both to DuplicateResourceError
            # so callers can treat "already exists" idempotently.
            if exc.code == 409 or (exc.code == 400 and ("ObjectConflict" in detail or "already exists" in detail)):
                raise DuplicateResourceError("user", path) from exc
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
        local account the email is not the UPN, so fall back to filtering on the
        emailAddress identity.

        NB: this filter is a REGULAR query on Entra External ID (CIAM) — sending
        the advanced-query `ConsistencyLevel: eventual` header + `$count=true`
        makes Graph reject it with `Request_UnsupportedQuery` ("Unsupported query
        on property 'ObjectIdentity'"), the opposite of Azure AD B2C. Verified
        live against the tenant: no header → 200 with the match, header → 400.
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
        # Local-account lookup by email identity (regular query — no advanced-query
        # header; see the method docstring).
        flt = urllib.parse.quote(f"identities/any(i:i/issuerAssignedId eq '{username}' and i/issuer eq '{self._user_domain}')")
        result = self._graph("GET", f"/users?$filter={flt}&$select=id")
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
        from shared.exceptions import DuplicateResourceError, ExternalServiceError

        try:
            created = self._graph("POST", "/users", body)
            sub = str(created["id"])
        except DuplicateResourceError as exc:
            # The directory user already exists (e.g. a retried provisioning, or the
            # same person already administers another tenant). Entra is a shared
            # directory with globally-unique UPNs/identities, while ShipX scopes a
            # user to a tenant via the {tenant_id}:{role} group — so reusing the
            # existing object id and just reconciling the group is the correct,
            # idempotent behaviour, not an error.
            key = email if self._local_accounts else self._upn(email)
            sub = self._resolve_user_id(key)
            if not sub:
                raise ExternalServiceError("Entra", f"user {key} reported as existing but could not be resolved") from exc
            logger.info("Entra user already existed; reusing oid=%s tenant_id=%s role=%s", sub, tenant_id, role)
        # Reconcile the role group by object id (works for local + member accounts)
        # so the token carries {tenant_id}:{role}.
        self.sync_user_groups(sub, tenant_id, {role})
        logger.info("Entra user provisioned: tenant_id=%s role=%s oid=%s local=%s", tenant_id, role, sub, self._local_accounts)
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

    def set_password(self, username: str, password: str, force_change: bool = False) -> None:
        """Set the user's password directly via Graph (admin), for ShipX account
        activation — a provisioned staff/admin picks their own password through a
        ShipX link, so they never need the Entra self-service reset. `force_change`
        False makes the chosen password final."""
        from shared.exceptions import ResourceNotFoundError

        uid = self._resolve_user_id(username)
        if not uid:
            raise ResourceNotFoundError("user", username)
        self._graph(
            "PATCH",
            f"/users/{uid}",
            {"passwordProfile": {"password": password, "forceChangePasswordNextSignIn": force_change}},
        )

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
