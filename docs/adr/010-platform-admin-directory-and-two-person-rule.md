# ADR-010: Platform admins are a directory with roles, and dangerous actions need two people

**Status:** Accepted (2026-11-28, platform admin audit Phase 1; owner decisions D2 and D4).
**Related:** `shared/platform_roles.py`, `shared/platform_directory.py`, `services/tenant_management/step_up.py`,
`services/tenant_management/approvals.py`, migration 076, `07_api_tenant_management.md`,
`00_CROSS_CUTTING_STANDARDS.md` ("Platform admin controls").

## Context

Until Phase 1 a platform admin was anyone in the identity provider's `platform_admin` group. Every member could offboard
any tenant, change any provider key and take every tenant offline with maintenance mode, alone and with no fresh proof
of identity. Platform admins had no record of their own (no `tenant_user` row by design), so the audit log could show an
identity subject but not a name, and nothing could give one admin less power than another. One stolen password or one
mistaken click could therefore take every tenant down.

## Decision

* **A directory, not a group.** `platform_user` holds every platform admin with one role: owner, admin, support or
  finance. The group still gets a token to the platform routes; `get_tenant_context` then resolves the caller to an
  active row and refuses anyone else (503 if the lookup fails). Roles map to permissions in one matrix
  (`shared/platform_roles.py`); each route asks for a permission, never a role, and a write with no permission named is
  owner-only.
* **Bootstrap by first sign-in, once.** While the directory has no owner, the first platform admin to sign in becomes
  the owner, serialised by an advisory lock. Before this change every group member had full power, so this grants
  nothing new; after it, people are invited. A seeding script skips bootstrap.
* **Step-up re-authentication, verified by the server.** Dangerous actions need a step-up token issued in the last five
  minutes. The server verifies the re-authentication itself (a Cognito sign-in as the caller, including TOTP, whose
  tokens are revoked at once; or a fresh Entra ID token) rather than trusting a client-side claim such as `auth_time`,
  which a Cognito refresh can renew.
* **Two-person rule for irreversible or platform-wide actions** (offboarding, gateway secrets, maintenance on; plan
  prices, a `data_cleanup` re-run and tenant admin transfer as their routes land). A request waits for a different owner
  or admin; the database forbids self-approval. With nobody else to ask, the requester types the target, every owner is
  emailed, and an offboarding waits 24 hours, cancellable.
* **The approved action runs as the requester**, and the approval row records who agreed. The payload is hashed at
  request time and checked before running; secrets are encrypted in the request and never returned.

## Consequences

* A platform admin with a stolen session cannot act destructively without the password and code; one person acting
  alone cannot offboard a tenant without either a colleague or a 24-hour, owner-emailed window.
* Protected routes answer with an outcome (`pending_approval`, `scheduled`, `executed`) instead of the changed record: a
  wire change the console handles.
* Platform audit rows can name their actor and show before and after states.
* Every new dangerous platform route must name its permission, require step-up, and decide whether it is a protected
  action.
* MFA itself (decision D3: a separate Cognito pool with MFA required, Entra conditional access) is Phase 1b. Until then
  the step-up asks for the TOTP code only when the pool already requires one for that user.
