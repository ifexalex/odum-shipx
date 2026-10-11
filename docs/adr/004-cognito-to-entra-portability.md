# ADR-004: Cognito → Entra Portability (IdentityProvider port + user migration)

**Status:** Accepted — Phases 1–4 implemented in code (Phases 1–2 AWS-only 2026-10-06; the Entra adapter, claims mapper, and migration script 2026-10-09, master-plan 7.115). Decision taken: **Entra External ID**, roles as **security groups** `{tenant_id}:{role}`. Remaining to go live (Phase 5): a real External ID tenant + the manual setup checklist (infrastructure/azure/README.md → "Auth setup — Entra External ID"), running the migration, and the dual-run→cutover.

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

> **Addendum (2026-10-11) — the cloud-group claim-shape gap.** The original plan assumed the
> Entra `groups` claim could be emitted as `{tenant_id}:{role}` **display names** via a
> claims-mapping policy. In practice Entra emits **object ids (GUIDs)** for *cloud-only* groups and
> display-name emission is only available for on-prem-synced groups — so a backend built only for
> Cognito's name-carrying `cognito:groups` resolved **no** roles on a real Entra token (the
> Cognito↔Entra incompatibility that surfaced during the first live platform-admin bring-up).
> `EntraClaimsMapper.groups()` now accepts three shapes and is the compatibility layer: (1)
> canonical names pass through; (2) object ids are mapped via `ENTRA_PLATFORM_ADMIN_GROUP_ID` /
> `ENTRA_GROUP_ID_MAP`; (3) the canonical group is **synthesized** from the `tenant_id` + `role`
> optional/extension claims (the primary, policy-free path). `scripts/setup_entra_platform_admin.sh`
> provisions the SPA app, claims, group, and admin user accordingly. Cognito is untouched (separate
> `CognitoClaimsMapper`); `shared/auth.py` stays cloud-agnostic.
>
> **CIAM wrinkle (observed live).** On an Entra **External ID / CIAM** tenant (`*.ciamlogin.com`),
> app-manifest `optionalClaims` for directory extensions are **not** emitted in the token even when
> the extension is registered, the user attribute is set, and the optional claim is configured — but
> the `groups` claim (object ids) *is* emitted. So for the platform admin the `tenant_id`/`role`
> extension claims can be absent while only the `platform_admin` group GUID arrives. Since a platform
> admin is tenant-less by invariant (`tenant_id=PLATFORM`), `EntraClaimsMapper.tenant_id()` **derives**
> `PLATFORM` from `platform_admin` membership (mapped group id or role claim) when no tenant claim is
> present — so a CIAM token carrying only the group GUID resolves fully with just
> `ENTRA_PLATFORM_ADMIN_GROUP_ID` set. Tenant-scoped users still require an explicit tenant claim
> (their tenant id is not derivable).
>
> **Full-roles fix on CIAM — custom authentication extension.** Because tenant users' `tenant_id`
> can't be derived, CIAM needs a **custom claims provider** (OnTokenIssuanceStart) to inject
> `tenant_id` + `role` into every token. Implemented as a standalone Azure Function
> (`services/entra_token_claims/`, Terraformed by `infrastructure/azure/modules/entra_claims_function`)
> that reads the user's `extension_<appId>_tenant_id` / `_role` off the directory via Graph (managed
> identity) and returns them as claims; `EntraIdentityProvider` stamps those extension attributes on
> every user it provisions (`ENTRA_TENANT_ID_ATTR` / `ENTRA_ROLE_ATTR`). The managed-identity Graph
> grant and the extension↔app binding are one-time manual Graph steps (no azurerm/azuread resource),
> documented in `infrastructure/azure/README.md`. With it live, the `EntraClaimsMapper` synthesize
> path resolves all roles on CIAM.

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
3. **Entra adapter + claim mapper** — ✅ **done (2026-10-09, master-plan 7.115).**
   `shared/providers/azure/entra.py` (`EntraIdentityProvider`, Graph via stdlib urllib +
   `azure-identity`) + `entra_claims.py` (`EntraClaimsMapper`). The authorizer's verifier is
   already issuer-driven (`OIDC_JWKS_URL`/`OIDC_AUDIENCE` → Entra; done in Phase 1's
   `shared/auth_verify.py`). Mocked-unit-tested; the External ID **tenant** setup is manual
   (checklist in `infrastructure/azure/README.md`).
4. **User migration** — ✅ **done (2026-10-09).** `scripts/migrate_users_to_entra.py` bulk-
   provisions `tenant_user` rows into Entra via the port (forced password reset + group sync),
   idempotent, `--dry-run`/`--tenant`.
5. **Dual-run → cutover → decommission Cognito** — operational; config flip
   (`DEPLOY_CLOUD`/`CLOUD_PROVIDER` + `OIDC_*`), run against a real tenant.

## Consequences
- Phases 1–2 are done AWS-only and make the codebase **seam-ready**: identity management
  is behind `IdentityProvider` and the Cognito claim shape is behind `ClaimsMapper`, so
  `services/tenant_management/service.py` and `shared/auth.py` are cloud-agnostic and
  won't need editing for the cutover. They do **not** by themselves achieve auth
  portability — that still needs phases 3–5, which require an actual Azure tenant.
- Entra External ID vs Azure AD B2C — **decided: External ID** (B2C is legacy). Roles are
  modelled as **security groups** `{tenant_id}:{role}` (faithful Cognito mirror). The token must
  emit group *display names* (claims-mapping policy) so the `groups` claim arrives in that form.
- Cost/credits: Entra External ID MAU-based pricing vs Cognito MAU — fold into the
  `docs/azure_cost_model.md` comparison before committing.

## References
- Portability ports: `docs/project docs/02_shared_utilities.md` → "shared/providers/"
- Current claim parsing: `shared/auth.py`, `services/authorizer/handler.py`
- Management surface: `services/tenant_management/cognito_client.py`
- Related: ADR-001 (serverless), ADR-002 (shared DB + RLS), ADR-003 (Cognito tenant claims — the auth model this makes portable)
