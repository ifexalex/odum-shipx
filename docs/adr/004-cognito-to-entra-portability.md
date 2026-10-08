# ADR-004: Cognito → Entra Portability (IdentityProvider port + user migration)

**Status:** Accepted — Phases 1–2 implemented (2026-10-06, AWS-only); phases 3–5 need an Azure tenant to build/test/migrate against

**Builds on** ADR-003 (Tenant-Aware Authentication with Cognito Custom Claims, in
`system_design_logistics_management.md`): ADR-003 chose a single Cognito pool with
`custom:tenant_id` + `{tenant_id}:{role}` group claims. This ADR keeps that model as the
default but makes it portable so the same auth contract can be served by Entra.

**Decision:** Make identity portable in two layers — an `IdentityProvider` port over
the management/provisioning operations (a clean adapter swap, like the other six
providers), and a **claim-mapping + JWKS** layer at the authN boundary (not a drop-in;
needs a user-account migration). Cognito stays the default; Entra External ID is the
target when/if we deploy on Azure.

**Why this is its own ADR (and not part of the 7.97–7.100 sweep):** the other seven
touchpoints (KMS, S3, Secrets Manager, EventBridge, SQS, SES, X-Ray) were 1:1 SDK-call
swaps behind a port. Cognito is not — `cognito_client.py` encodes Cognito's *model*
(email-as-username, groups named `{tenant_id}:{role}`, `custom:*` attributes, user
pools), the JWT **claim shape** is baked into `shared/auth.py` and the authorizer, and
real user accounts live in the pool. Porting faithfully is a design + data migration,
not a code move.

---

## Scope of the Cognito surface today

### A. Management / provisioning — portable behind `IdentityProvider`
`services/tenant_management/cognito_client.py` (`CognitoClient`, 14 methods, already
has a `get_cognito_client()` factory), plus `services/auth/cognito_refresh.py`
(token refresh) and the user-purge in `services/scheduled/data_cleanup.py`
(`list_users` + `admin_delete_user`). Consumers: `services/auth/*`,
`services/tenant_management/*`, `services/scheduled/data_cleanup.py`.

Proposed port (new `shared/providers/base.py::IdentityProvider`, AWS adapter
`shared/providers/aws/cognito.py`, Azure adapter `azure/entra.py` via MS Graph):

| `CognitoClient` method | Cognito API | Entra (MS Graph / CIAM) equivalent |
|---|---|---|
| `create_user` (invite) | `admin_create_user` (SUPPRESS/email) | `POST /users` or CIAM invitation + email OTP |
| `create_user_with_password` | `admin_create_user` + `admin_set_user_password(Permanent=True)` | `POST /users` with `passwordProfile` |
| `update_user_attributes` | `admin_update_user_attributes` | `PATCH /users/{id}` |
| `disable_user` | `admin_disable_user` | `PATCH /users/{id}` `accountEnabled=false` |
| `enable_user` | `admin_enable_user` | `accountEnabled=true` |
| `global_sign_out` | `admin_user_global_sign_out` | `POST /users/{id}/revokeSignInSessions` |
| `resend_invite` | re-`admin_create_user` (RESEND) | re-issue invitation |
| `reset_password` | `admin_set_user_password` | `PATCH passwordProfile` (`forceChangePasswordNextSignIn`) / SSPR |
| `create_group_if_not_exists` | `create_group` | `POST /groups` **or app role** (see decision below) |
| `add_user_to_group` | `admin_add_user_to_group` | `POST /groups/{id}/members/$ref` or appRole assignment |
| `remove_user_from_group` | `admin_remove_user_from_group` | `DELETE` member / appRole assignment |
| `list_groups_for_user` | `admin_list_groups_for_user` | `GET /users/{id}/memberOf` / appRoleAssignments |
| `sync_user_groups` | (composite) | reconcile membership/appRoles |

Open decision: model `{tenant_id}:{role}` as **Entra groups** (closest to Cognito,
simplest mapping) **or app roles** (cleaner for RBAC but a bigger rewrite of
`sync_user_groups`). Recommend **groups** for a faithful first cut.

### B. AuthN boundary — claim mapping + JWKS (the hard part)
`services/authorizer/handler.py::_verify_cognito_jwt` (JWKS fetch + RS256 verify) and
`shared/auth.py` (`get_tenant_context` / role parsing). The JWT verification itself is
already env-driven (`COGNITO_JWKS_URL`, `COGNITO_AUDIENCE`) and ports cleanly — Entra
also publishes JWKS and issues RS256 tokens. What does **not** port is the claim shape:

| ShipX claim (Cognito) | Meaning | Entra source |
|---|---|---|
| `sub` | user_id | `oid` (object id) — stable; or `sub` (pairwise) |
| `custom:tenant_id` | tenant UUID | directory **extension attribute** `extension_<appId>_tenant_id` (emitted via a claims-mapping policy / custom claims provider) |
| `cognito:groups` = `["{tenant_id}:{role}", …]` | role grants | `groups` claim **or** `roles` (app roles) |
| `custom:role` | primary role | extension attribute `extension_<appId>_role` |
| `email` | login id (immutable) | `preferred_username` / `mail` |

Mapping lives in **one place** behind a small `claims_adapter` (keyed on
`CLOUD_PROVIDER`) so `shared/auth.py` reads logical fields (`user_id`, `tenant_id`,
`roles`, `role`, `email`) regardless of cloud. The authorizer already tries multiple
token types (Cognito JWT + ShipX impersonation token) — add an Entra verifier as a
third, which is exactly what enables the dual-run cutover below.

### C. Unaffected
The **impersonation token** is ShipX's own HS256 JWT (already provider-agnostic via
`SecretsProvider`, ADR-less) — not a Cognito token, so Cognito→Entra does not touch it.
RLS, tenant scoping, and every `@require_roles` check read the logical context, so they
are unaffected once the claim adapter is in place.

---

## User migration

Cognito **cannot export password hashes**, so users cannot be silently moved. Strategy:

1. **Bulk-provision** every active `tenant_user` / customer into Entra via Graph
   (`POST /users`) with `forceChangePasswordNextSignIn=true`, carrying `tenant_id` /
   `role` into the extension attributes. Email stays the stable identifier (honours the
   "email immutable" constraint).
2. **Password reset by invitation** — each user sets a new password on first Entra
   sign-in (send the branded reset/invite email; reuse the existing notification
   pipeline). No hash migration.
3. **Dual-run cutover window** — the authorizer verifies **both** Cognito and Entra
   JWTs (two JWKS/issuer/audience sets). Point the frontend auth at Entra; users who
   haven't reset yet still work via Cognito until the window closes. No big-bang.
4. **Cutover + decommission** — once sign-ins have drained to Entra, remove the Cognito
   verifier and the pool.

Rollback: during dual-run, flipping the frontend back to Cognito is a config change (no
data loss, since Cognito is untouched until decommission).

---

## Rollout phases

1. **Port management ops** — ✅ **done (2026-10-06, master-plan 7.102).** `IdentityProvider`
   port in `shared/providers/base.py`; `cognito_client.py` moved to the AWS adapter
   `shared/providers/aws/cognito.py` (`CognitoIdentityProvider`, byte-identical) and the
   old module deleted; `services/tenant_management/service.py` calls
   `get_identity_provider()`; `azure/entra.py` is the pending Azure adapter. No behaviour
   change on AWS (1152 tests green). This was the only mechanically-safe part and landed
   independently of any Azure decision.
2. **Claim adapter** — ✅ **done (2026-10-06, master-plan 7.103).** `ClaimsMapper` port
   (`shared/providers/base.py`) + AWS adapter `shared/providers/aws/cognito_claims.py`
   (`CognitoClaimsMapper`, holds the `sub`/`custom:tenant_id`/`cognito:groups`/`custom:role`
   reads + bracket-parsing); `shared/auth.py` now reads logical fields via
   `get_claims_mapper()` and keeps only the cloud-agnostic `{tenant_id}:{role}`
   interpretation. AWS-only, no behaviour change (1156 tests green) — done without Azure,
   so `auth.py` never needs editing again for the cutover; the Entra mapper is one new
   file. *(Still pending: the authorizer's verifier list gains an Entra verifier — that's
   Phase 3, since it needs Entra's JWKS/issuer.)*
3. **Entra adapter + Terraform** — `azure/entra.py` (Graph) + `infrastructure/azure`
   Entra External ID tenant, app registration, extension attributes, claims-mapping.
4. **User migration** — bulk-provision + invite (above), behind a one-shot script.
5. **Dual-run → cutover → decommission Cognito.**

## Consequences
- Phases 1–2 are done AWS-only and make the codebase **seam-ready**: identity management
  is behind `IdentityProvider` and the Cognito claim shape is behind `ClaimsMapper`, so
  `services/tenant_management/service.py` and `shared/auth.py` are cloud-agnostic and
  won't need editing for the cutover. They do **not** by themselves achieve auth
  portability — that still needs phases 3–5, which require an actual Azure tenant.
- Entra External ID (CIAM) vs Azure AD B2C is an **open question for the business**
  (B2C is legacy/being superseded by External ID; recommend External ID). The claim
  mechanism (extension attributes + claims-mapping policy or a custom claims provider)
  differs between them — pick before phase 3.
- Cost/credits: Entra External ID MAU-based pricing vs Cognito MAU — fold into the
  `docs/azure_cost_model.md` comparison before committing.

## References
- Portability ports: `docs/project docs/02_shared_utilities.md` → "shared/providers/"
- Current claim parsing: `shared/auth.py`, `services/authorizer/handler.py`
- Management surface: `services/tenant_management/cognito_client.py`
- Related: ADR-001 (serverless), ADR-002 (shared DB + RLS), ADR-003 (Cognito tenant claims — the auth model this makes portable)
