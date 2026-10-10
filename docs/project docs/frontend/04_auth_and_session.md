# Task FE-04 — Auth & Session

## Objective

Implement Cognito login, session/token management, and the frontend equivalent of the backend's `TenantContext` — the single source of truth every page reads for `tenant_id`, `role`, and impersonation state.

## Depends On

Task 01.

## Backend Contract (ground truth — `shared/auth.py`, `shared/tenant_context.py`)

### JWT claims

```
sub               → user_id (Cognito subject)
custom:tenant_id   → tenant_id (UUID string, or "PLATFORM" for platform admins)
cognito:groups     → "{tenant_id}:{role}" for tenant users, e.g. "aaaa...:nigeria_office_staff"
                     "platform_admin" (no tenant prefix) for platform admins
```

### Roles (`UserRole` enum — string values, exact match required)

```ts
type Role =
  | "platform_admin"
  | "tenant_admin"
  | "china_office_staff"
  | "nigeria_office_staff"
  | "warehouse_attendant"
  | "customer";
```

### Impersonation

When a platform admin starts an impersonation session (`POST /v1/platform/tenants/{id}/impersonate`), the backend issues a **separate HS256 JWT** (not a normal Cognito token), carrying:

```
sub               → impersonated user_id
custom:tenant_id   → target tenant_id
cognito:groups     → "{tenant_id}:tenant_admin"
impersonated_by    → platform admin's user_id
session_id         → impersonation_session.id (UUID)
read_only          → true
exp                → 30-minute TTL
```

The frontend must send this token with header `X-Token-Type: impersonation` (the API Gateway authorizer uses this to route to HS256 verification instead of Cognito JWKS). Store it exactly like a normal session token but tag it in session state so the UI can render the read-only banner (Task 08) and disable every mutating control.

### Session shape (frontend mirror of backend `TenantContext`)

```ts
interface Session {
  tenantId: string;            // UUID, or "PLATFORM"
  userId: string;
  role: Role;
  isPlatformAdmin: boolean;    // derived: tenantId === "PLATFORM"
  impersonatedBy: string | null;
  sessionId: string | null;    // impersonation_session.id, null outside impersonation
  readOnly: boolean;           // true only inside an impersonation session
  expiresAt: number;           // from JWT exp, drives auto-logout / countdown banner
  tokenType: "cognito" | "impersonation"; // added in implementation: lets tokenStore pick the
                                           // right header shape and skip silent refresh for impersonation
}
```

Parse this once on login (and on every token refresh) from the decoded JWT, store it in a `SessionProvider` context — never re-derive role/tenant from anywhere else (URL, subdomain, local storage flags). The subdomain (`{tenant}.shipx.co`) is cosmetic branding only (Task 02) — it is never a source of `tenantId`.

## Login Flow

1. `LoginScreen` (port from `Shipx_frontend_design/screens/auth/auth-screens.jsx` `LoginScreen`) posts credentials directly to Cognito (`InitiateAuth` / `USER_PASSWORD_AUTH` or `USER_SRP_AUTH` flow) via `amazon-cognito-identity-js`. Do not proxy login through the backend — Cognito is the IdP, the backend never sees passwords.
2. On success, Cognito returns `IdToken` (carries the claims above), `AccessToken`, `RefreshToken`.
3. Decode `IdToken`, populate `Session`, store tokens (see storage decision in [11_security_and_compliance.md](11_security_and_compliance.md) — short answer: memory + silent refresh, not `localStorage`).
4. Redirect by role: platform_admin → `/platform/dashboard`; tenant_admin/staff → `/dashboard`; customer → `/my-shipments`. Full route map in Task 06.

## Token Refresh

Cognito `IdToken`/`AccessToken` expire in ~1 hour by default; refresh silently in the background (on a timer at 80% of token lifetime, or on 401 from the API client — see Task 05) rather than forcing re-login. Impersonation tokens do **not** refresh — they hard-expire at 30 minutes by design (security control, not a bug); show the countdown (Task 08) and force exit-to-platform-admin on expiry, don't attempt silent refresh for these.

**The refresh token itself never lives in frontend JS memory beyond the single call that hands it off at login.** `CognitoClient.signIn()` returns it to `SessionProvider.login()`, which immediately `POST`s it to `services/auth/handler.py`'s `POST /v1/auth/session` — that endpoint persists it as a `Secure; HttpOnly; SameSite=Strict` cookie scoped to `Path=/v1/auth`. Every subsequent refresh (the proactive 80%-of-lifetime timer, the API client's 401-recovery path, and — critically — **the silent restore on every page load**) goes through `POST /v1/auth/refresh`: the browser attaches the cookie automatically, the backend exchanges it with Cognito's `REFRESH_TOKEN_AUTH` flow, and only the resulting fresh `IdToken` comes back over the wire into memory. `POST /v1/auth/logout` revokes it server-side (Cognito `RevokeToken`) and clears the cookie. See [11_security_and_compliance.md](11_security_and_compliance.md) for why this is the httpOnly-cookie pattern rather than `localStorage`/`sessionStorage`, and why it's *more* secure than the in-memory refresh-token-ref approach it replaced — an `HttpOnly` cookie is categorically unreadable by JS (and therefore by XSS), where a JS variable, however short-lived, is not.

**This is also what makes a page reload not force a re-login.** `SessionProvider` starts in `status: 'loading'` and, on mount, immediately attempts `POST /v1/auth/refresh` before rendering anything route-dependent — `RoleGuard` and `RootRedirect` both treat `'loading'` as "wait" (rendering `SessionLoading`), never "redirect to `/login`." The in-memory `IdToken` is gone after any reload (never persisted, by design), but the httpOnly cookie survives it, so the very first thing the app does is trade that cookie for a fresh token before any guard gets a chance to bounce the user out.

## Route Guards

`RoleGuard` wraps route definitions (Task 06):

```tsx
<RoleGuard allow={["tenant_admin"]}>
  <TenantConfigPage />
</RoleGuard>
```

This is a **UX convenience, not a security boundary** (CLAUDE.md principle — tenant isolation and role enforcement are backend properties). A customer hitting a staff URL directly gets redirected client-side, but the *real* protection is that the API returns 403 regardless. Don't build elaborate client-side permission logic beyond "can this role see this nav item / route" — mirror the `ctx.assert_role(...)` calls documented per-route in the backend handler docs (07–15) and in the route inventory in Task 06, but treat any mismatch as a backend bug to fix, not a frontend permission system to harden.

## Local Dev Auth Shim

The backend's Flask dev server (`scripts/local_server.py`) accepts `X-Tenant-ID` / `X-Role` / `X-User-ID` headers in place of a real JWT when `VITE_ENVIRONMENT=local`. Build a dev-only `LocalAuthProvider` that:

- Skips Cognito entirely.
- Renders a small role-switcher dropdown (not part of production bundle — tree-shake via `import.meta.env.DEV` or a separate local entrypoint) to flip between the 6 roles instantly for UI development without needing 6 real Cognito users.
- Sets the same `Session` shape Task 05's API client reads, so no other code needs to know it's running against the shim.

## Real Cognito-via-Moto Login (Local Dev)

`LocalAuthProvider` (mounted whenever `VITE_ENVIRONMENT=local`) both drives the dev role-switcher **and** supports a real Cognito login through the same `/login` screen — no environment-variable dance required. Its `login()` calls `CognitoClient.signIn()` exactly like `SessionProvider` does; a successful real login overlays a `cognitoSession` on top of the dev-identity session (priority: impersonation > real Cognito session > role-switcher identity) and switches `tokenStore` from the local header trio to a real Bearer token for the rest of that session. Never having logged in for real falls back to the role-switcher identity, same as always — but an *explicit* `logout()` of a real session now does **not** fall back to it (see "Explicit logout must not resurrect the dev-shim session" below); the switcher's own dropdown is still how you deliberately re-enter dev-identity mode afterward. This also persists across a page reload via the same httpOnly refresh-cookie mechanism `SessionProvider` uses (`establishServerSession`/`silentRefresh`).

`frontend/.env.local` needs the usual Moto-pointing vars (regenerated by every `make bootstrap` / `make stack` — re-copy from the backend's `.env.local` if a login starts failing with `ResourceNotFoundException: User pool ... does not exist`):

```
VITE_COGNITO_USER_POOL_ID=<copy COGNITO_USER_POOL_ID from the backend's .env.local>
VITE_COGNITO_CLIENT_ID=<copy COGNITO_CLIENT_ID from the backend's .env.local>
VITE_COGNITO_ENDPOINT=http://localhost:5100
```

`CognitoClient.ts` only reads `VITE_COGNITO_ENDPOINT` to point `amazon-cognito-identity-js` at Moto instead of real AWS, and only switches to `USER_PASSWORD_AUTH` (instead of the SDK's default `USER_SRP_AUTH`) when that var is set — Moto's cognito-idp doesn't reliably emulate SRP's auth math, but real Cognito is untouched (still SRP, password never leaves the browser).

To create a user to log in as: `python scripts/onboard_tenant.py --company-name "..." --email "..." --tier starter` (provisions a tenant + Cognito user + `tenant_user` row in one shot), then set a permanent password so the dev login screen (which has no force-change-password UI yet) can complete sign-in:

```
aws --endpoint-url=http://localhost:5100 cognito-idp admin-set-user-password \
  --user-pool-id <COGNITO_USER_POOL_ID> --username <email> --password '<Pass123!>' --permanent
```

`scripts/local_server.py`'s `_build_event()` decodes the real JWT from `Authorization: Bearer` (no signature verification — local dev only, same bypass posture as the `X-Tenant-ID`/`X-Role`/`X-User-ID` header path it falls back to) so the backend sees the same `sub`/`custom:tenant_id`/`cognito:groups` claims a real API Gateway JWT authorizer would inject.

**Critical invariant this depends on:** `tenant_user.id` must equal the user's Cognito `sub` (see `create_tenant_user()` in `services/tenant_management/repository.py` and `scripts/onboard_tenant.py`'s `step_create_tenant_user()`) — every `created_by`/`approved_by`/`rejected_by` column is `UUID REFERENCES tenant_user(id)`, and `TenantContext.user_id` (`shared/auth.py`) is the raw Cognito `sub` with no separate resolution step. If a `tenant_user` row is ever created with `id` left to `gen_random_uuid()` instead of the real `cognito_sub`, every write by that user 500s with an FK violation — this was a real, previously-undiscovered bug (not local-dev-only) since no one had ever exercised a real Cognito login against a real write path before.

## Impersonation Lifecycle (Platform Admin side)

1. Platform admin clicks "Impersonate" on a tenant detail page → `POST /v1/platform/tenants/{id}/impersonate`.
2. Backend returns the impersonation JWT + `session_id` + `expires_at`.
3. Frontend swaps the active `Session` to the impersonation one, navigates into the tenant's app shell (now showing `ImpersonationBanner`, Task 08), and starts a countdown.
4. "Exit impersonation" button → `DELETE /v1/platform/impersonation/{session_id}`, then restore the platform admin's own session and navigate back to `/platform/tenants/{id}`.
5. On the 30-minute expiry (client-side timer **and** server-enforced — don't rely on the client timer alone): force the same exit flow, show a toast ("Impersonation session ended").

## Acceptance Criteria

- [x] Login screen authenticates directly against Cognito; no password ever sent to the backend API — `LoginScreen` calls `useSession().login()` → `CognitoClient.signIn()` → `amazon-cognito-identity-js` directly; the backend is never invoked during login.
- [x] `Session` is parsed once from the JWT and exposed via a single `useSession()` hook; no component re-derives tenant/role from anywhere else — `jwt.ts#sessionFromIdToken`, consumed exclusively through `SessionContext`/`useSession()`.
- [x] Silent token refresh keeps a normal session alive past the 1-hour token expiry without forcing re-login — `SessionProvider`'s `scheduleRefresh` fires at 80% of token lifetime; covered with fake-timer tests in `SessionProvider.test.tsx`.
- [x] Impersonation tokens are tagged distinctly (`X-Token-Type: impersonation` header sent on every request while active) and never silently refreshed — `tokenStore.getAuthHeaders()` adds the header for `tokenType: 'impersonation'`; `scheduleRefresh` is a no-op while impersonating. Request-level proof (the header actually reaching `fetch`) lands with Task 05's API client.
- [x] `RoleGuard` redirects (not crashes) when a role hits a route it shouldn't see, and this is documented as UX-only, not the security boundary — see the comment block in `RoleGuard.tsx`; covered by `RoleGuard.test.tsx`.
- [x] Local dev shim works end-to-end against the Flask dev server using header-based auth, with a role switcher for fast manual testing — `LocalAuthProvider` + `RoleSwitcher` set the same `X-Tenant-ID`/`X-Role`/`X-User-ID` trio `scripts/local_server.py` expects via `tokenStore.setActiveLocalAuth()`; verified live at `/auth-preview` (role flips update the rendered `Session` instantly). Full request-level proof against the Flask server lands with Task 05's API client.
- [x] Impersonation exit (manual or on 30-min expiry) always restores the platform admin's own session correctly, with no leaked tenant-scoped UI state (clear all tenant-scoped query cache on exit — see Task 09) — `exitImpersonation()` and the hard-expiry auto-exit both restore the saved platform-admin `Session`, covered in `SessionProvider.test.tsx`. The query-cache invalidation half is Task 09's responsibility once a query client exists.
- [x] A page reload does not force a re-login as long as the refresh token is still valid — `SessionProvider` silently restores the session from the `services/auth/handler.py` httpOnly cookie on mount; `RoleGuard`/`RootRedirect` wait out `status: 'loading'` instead of redirecting. Covered in `SessionProvider.test.tsx` ("restores an authenticated session on mount…") and `services/auth/`'s own unit tests.

## Implementation notes / ground-truth gaps found

- **Reload-forces-relogin bug closed (2026-07-11):** tokens were correctly kept in memory only (per 11_security_and_compliance.md's XSS threat model), but that meant `SessionProvider` had no way to reconstruct a session after any page reload — every reload landed on `/login`, on every page, for every real-Cognito session (`LocalAuthProvider`'s dev shim was unaffected — it hardcodes `status: 'authenticated'` with no persistence step at all). Closed by moving the refresh token out of JS reach entirely: `POST /v1/auth/session` (new `services/auth/handler.py`) persists it as a `Secure; HttpOnly; SameSite=Strict` cookie right after login, and `POST /v1/auth/refresh` exchanges that cookie for a fresh `IdToken` on mount and on the proactive/401-triggered refresh paths. `tokenStore.ts`'s `ActiveAuth` type no longer has a `refreshToken` field at all — not "always null by convention," but structurally impossible to hold one in JS memory, since removing the type slot is a stronger guarantee than trusting every call site to pass `null`.
- Backend routes are public (`authorization_type = "NONE"` in `infrastructure/aws/modules/api-gateway/main.tf`) — they run *before* any JWT exists, by definition. `services/auth/cognito_refresh.py` uses the non-admin `InitiateAuth`/`RevokeToken` Cognito APIs (not `AdminInitiateAuth`), scoped via IAM to only those two actions on the user pool — this Lambda cannot create, disable, or read arbitrary users, unlike `tenant_management`'s broader `cognito_admin` IAM policy.
- Also found and fixed while touching this area: `POST /v1/register` (customer self-registration) was implemented in `tenant_management/handler.py` and called by `RegisterScreen.tsx`, but was missing from both `infrastructure/aws/modules/api-gateway/main.tf`'s route table and `scripts/local_server.py`'s `_ROUTES` — self-registration would 404 in both production and local dev. Added to both.
- **`LocalAuthProvider` blocked every real customer login in local dev, found live (2026-09-06):** its `login()` unconditionally threw `Error('LocalAuthProvider has no login flow — use the role switcher instead')`. Since `App.tsx` mounts `LocalAuthProvider` for the *entire* app tree whenever `VITE_ENVIRONMENT=local` (not just the staff role-switcher demo), this made the real `/login` screen — the one a customer reaches after claiming their invite link — permanently unusable in local dev, even with fully correct Cognito credentials: the thrown `Error`'s `name` doesn't match any of `LoginScreen.tsx#loginErrorMessage`'s known Cognito exception names, so it silently rendered as the generic "Something went wrong signing you in," which looks identical to a real invalid-password failure. Confirmed live: `initiate-auth` against Moto with the exact same credentials succeeded outside the browser while the UI failed 100% of the time. Fixed by giving `LocalAuthProvider` a real `login()`/`logout()` (mirroring `SessionProvider`'s Cognito + httpOnly-cookie-refresh flow) that overlays a real session on top of the dev role-switcher rather than replacing it — the role switcher still works for staff roles with zero Cognito users needed, and a real customer (or any real Cognito user) can now also sign in for real, in the same local environment, through the same screen. Verified end-to-end: claimed invite → real login → real shipment data rendered on `/my-shipments` → session survived a page reload.
- **Explicit logout must not resurrect the dev-shim session, found live (2026-09-13):** user report — "i logged in as ifesinachi (customer), when i logout and refresh the page it still logged in." Two compounding bugs in `LocalAuthProvider`, both introduced by the fix directly above (which gave it a real `login()`/`logout()` but didn't account for what "logged out" should mean underneath the always-on dev shim):
  1. `status` was hardcoded to `'authenticated'` unconditionally — `RoleGuard`'s `status !== 'authenticated' || !session -> /login` check could therefore never fire, no matter what `session` held.
  2. `session` was `impSession ?? cognitoSession ?? roleSession` with no way to express "logged out" — the instant `cognitoSession` cleared, `session` fell straight back to the dev-identity fallback (`roleSession`, e.g. `platform_admin` if the switcher was never touched), which looks and behaves exactly like a real, live-authenticated session. The `useEffect` that (re-)applies the local `X-Tenant-ID`/`X-Role`/`X-User-ID` header trio ran on that same fallback, so it wasn't just a display glitch — subsequent API calls really were authenticated as the dev shim. And since none of this is React state that survives a reload, a page refresh reproduced the identical outcome, matching the "even after refresh" half of the report exactly.

  Fixed with a `loggedOut` flag, set by `logout()` and cleared by `login()`/`startImpersonation()`/picking a role from `RoleSwitcher()`/a genuinely restored cookie session — `session` becomes `impSession ?? cognitoSession ?? (loggedOut ? null : roleSession)`, and `status` is now derived (`session ? 'authenticated' : 'unauthenticated'`) instead of hardcoded. The flag is persisted via a new `src/lib/localDevSession.ts` (deliberately **not** in `src/auth/` — `frontend-ci.yml`'s "no localStorage/sessionStorage in auth layer" check greps that directory literally, including comments, and fixing that grep's scope wasn't part of this fix) so it survives the reload the bug report specifically called out; it holds no token and no PII, and only `LocalAuthProvider` (dev-only, `import.meta.env.DEV`-gated) reads it. A secondary paper-cut found while fixing this: re-selecting the *same* dev role from `RoleSwitcher` after a logout wouldn't fire the `<select>`'s `onChange` at all (its value never actually changed), leaving the switcher looking inert — fixed by rendering a distinct disabled `"— logged out —"` placeholder option whenever `status === 'unauthenticated'`, so the select's current value is never a real identity while logged out and any real pick is a genuine change.

  **Verified two ways.** Unit: 12 cases in `LocalAuthProvider.test.tsx` covering immediate post-logout state, a simulated reload (unmount + remount, since plain React state can't survive a real one), a stale-cookie-wins-over-the-marker edge case, re-entering via `RoleSwitcher`, and logging back in for real afterward. Live, end-to-end, against the real running stack with a real Cognito-via-Moto login (`frontend/e2e/flows/auth-logout.spec.ts`, new): claim a real invite → log in for real → log out → assert `/login` (not a dev-shim home page) → reload → still `/login` → navigate straight to a protected route → still bounced to `/login` → log back in → succeeds. All 4 pass run serially; running the file at the suite's default parallelism intermittently fails at the unrelated invite-minting setup step (`mint_test_invite.py` shelling out under concurrent load) — a pre-existing flakiness class in this e2e suite (shared by `customer-invite.spec.ts`), not a regression from this fix.

- **That fix immediately broke the dev role switcher, found live (2026-09-13, same day):** user report — "The Dev selection bar for roles is no longer working." `api/client.ts`'s `recoverFrom401` calls `actions.logout()` whenever a request still 401s after one silent-refresh-and-replay attempt — a path that was *already* wired up for `LocalAuthProvider` and fires routinely in local dev (any endpoint the current dev role can't call), completely unrelated to any real login/logout. Before the fix above, this was harmless: the old `logout()` had no lasting effect for a pure dev-shim identity (no `cognitoSession`) — it cleared `tokenStore` but the header-restoring `useEffect` immediately reinstated the dev identity on the next render. The fix above made `logout()` set a *sticky*, reload-surviving `loggedOut` flag unconditionally, so the very next stray 401 anywhere in the app permanently (across reloads, via `localDevSession.ts`) knocked the switcher into its "logged out" placeholder — indistinguishable, from the outside, from "the switcher stopped working." Fixed by making `logout()` a true no-op — skipping `clearActiveTokens()` and the `loggedOut` flag both, not just the flag — whenever `cognitoSession` is null, i.e. whenever there was no real session for this call to plausibly be ending. A real Cognito session's `logout()` (explicit click, or `recoverFrom401` genuinely invalidating a real expired token) is unaffected and still sets the flag correctly. New regression test in `LocalAuthProvider.test.tsx`: calling `logout()` with no real Cognito session active leaves `status`/`session`/`getAuthHeaders()` completely unchanged. Re-verified live: `e2e/flows/auth-logout.spec.ts` (real-login case) and `e2e/flows/auth.spec.ts` (pure dev-shim role switching, all 6 roles) both pass together, serially, in the same run.

- **A reload always reset the active dev role to platform_admin, systemically across every page, found live (2026-09-19):** user report — "when i am on tab e.g customer or any other tab and i refresh, it goes to the dashboard. this is experienced in the tenant admin page. i believe this issue will be persistent on other pages as well, check all the pages." `LocalAuthProvider`'s `identity` (which of the 7 dev roles `RoleSwitcher` has active) was plain `useState<DevIdentityKey>(initialRole)` with nothing persisting it, and `App.tsx` never passes an `initialRole` prop — so *any* page reload restarted it at the hardcoded default (`'platform_admin'`), silently discarding whatever role the developer had actually switched to. `RoleGuard` then saw the current route's `allow` list no longer included the (now wrong) role and redirected to that role's home page (`platform_admin` → `/platform/dashboard`, a "dashboard"-titled page — matching the report). Reproduced live with Playwright before writing any fix: switch to `tenant_admin`, open `/admin/customers`, reload → landed on `/platform/dashboard` every single time, on every route tested (a `/admin` sub-page, a `ConfigLayout` sub-nav page, a China-office page, a customer-portal page) — confirming the user's "this will be persistent on other pages" prediction, since the bug is in the identity-restoration step itself, not any individual page.

  Also investigated, but not reproducible and not fixed: a theoretically similar race for a *real* Cognito login tested against local dev specifically — `LocalAuthProvider` has no `'loading'` status window during its mount-time cookie restore the way `SessionProvider` does (`status` is computed synchronously from `session`, which falls back to the dev-shim identity the instant a real `cognitoSession` isn't there yet), so a route requiring a non-`platform_admin` role could theoretically render `RoleGuard`'s wrong-role redirect before the async restore resolves. Tried to reproduce this live (real invite claim → real login → reload on `/my-shipments`) and it did not reproduce — the local cookie-exchange round-trip resolves fast enough that React never commits the stale `<Navigate>` before the correct session lands. Left unfixed: fixing it properly means adding a real loading gate mirroring `SessionProvider`'s (touching ~20 existing `LocalAuthProvider.test.tsx` cases to await it, and adding a real, if brief, loading flash to every dev-shim page load too) for a race that doesn't manifest in this environment and that production's actual code path (`SessionProvider`) was already independently confirmed immune to. Noted here in case a slower environment ever surfaces it.

  **Fix:** the dev-shim identity is now persisted across a reload via a new pair of functions in `src/lib/localDevSession.ts` (`getPersistedDevIdentity`/`setPersistedDevIdentity`/`clearPersistedDevIdentity` — sessionStorage-backed, same file and same "outside `src/auth/`" reasoning as the `loggedOut` flag above) — `useState(() => getPersistedDevIdentity() ?? initialRole)` restores the last-picked role on mount instead of always falling back to the hardcoded default, and `setIdentity()` (called by `RoleSwitcher`) persists every pick going forward.

  **Verified two ways.** Unit: 3 new cases in `LocalAuthProvider.test.tsx` (a picked role surviving a simulated reload via unmount+remount, a persisted identity taking priority over `initialRole`, plus the existing "defaults to platform_admin"/"honors initialRole" cases now proving the *fallback* still works correctly when nothing's persisted) — 769 frontend unit tests pass. Live, end-to-end: a new `describe('dev role survives a reload')` block in `e2e/flows/auth.spec.ts` (4 cases — a `/admin` sub-page, a `ConfigLayout` sub-nav page, a China-office page, a customer-portal page, one per major role family) reproduces the exact bug on the unfixed code and passes cleanly after the fix.

- **The same-day fix above surfaced a second, pre-existing switcher bug, found live (2026-09-19, same day):** user report — "the dev role switcher is not working," persisting after a full dev-server restart and hard browser refresh ruled out stale HMR state. Root cause, unrelated to the identity-persistence fix: `session` is `impSession ?? cognitoSession ?? (loggedOut ? null : roleSession)` — a **lingering real Cognito session** (e.g. left over from earlier real-login testing in the same browser tab, of which this session has done plenty) unconditionally outranks the dev shim. Picking a role in `RoleSwitcher` updated the `<select>` and `identity` state exactly as designed, but had **zero visible effect** on the actual session or page, with nothing telling the developer why — indistinguishable from "the switcher does nothing." Reproduced live before writing any fix: log in as a real customer, pick `tenant_admin` in the switcher, the app stayed on the customer's own `/my-shipments` page. This bug predates the identity-persistence fix above — it was just easier to trigger and notice right after, since testing that fix meant repeatedly using the switcher in the same tab a real login had touched.

  **Fix:** extracted the Cognito-session-ending logic already in `logout()` into a shared `endCognitoSession()`, and `setIdentity()` now calls it whenever `cognitoSession` is set before switching identity — picking a dev role is an unambiguous "use the shim now" signal, so it ends any real session standing in its way rather than being silently outranked by one. This also incidentally closes the reload race noted in the entry above as "left unfixed" for the *specific* case where the switcher was used while a real session was active: since the real session is now properly ended (server-side revoke included) the moment a role is picked, there's no lingering valid cookie left to race against on a subsequent reload.

  **Verified two ways.** Unit: new case in `LocalAuthProvider.test.tsx` — log in for real, pick a dev role via `RoleSwitcher`, assert `signOut`/`revokeServerSession` were called and the session/headers fully reflect the picked role, not the real one. Live: reproduced the exact bug with Playwright (real customer login → pick `tenant_admin` → app stays on the customer's page) before the fix, then re-ran the identical script after — the app now correctly switches to `tenant_admin`'s `/dashboard`, and stays there across a reload.

## Cloud-agnostic auth provider (Cognito ↔ Entra, added 2026-10-10)

The auth layer is no longer hard-wired to Cognito. The app's auth entry points import from
**`src/auth/authClient.ts`**, a facade that selects the provider by build-time env
`VITE_AUTH_PROVIDER` — `'cognito'` (AWS, default) or `'entra'` (Azure):

- **`CognitoClient.ts`** — unchanged (SRP sign-in, new-password + forgot-password challenges).
- **`EntraClient.ts`** (new) — Microsoft Entra (External ID) via the OAuth2 **ROPC** grant, so the
  existing email/password `LoginScreen` works unchanged against Entra for **local accounts** (no
  redirect UX). Same `signIn/refreshSession/signOut` surface + `{idToken,accessToken,refreshToken}`
  shape as Cognito. Password-reset flows are Entra-hosted (the in-app challenge functions reject).
  Config: `VITE_ENTRA_TOKEN_ENDPOINT`, `VITE_ENTRA_CLIENT_ID`, `VITE_ENTRA_SCOPE`.
- **`jwt.ts`** — `buildSession` now reads both claim shapes (Cognito `sub`/`custom:tenant_id`/
  `cognito:groups`/`custom:role` and Entra `oid`/`tenant_id`/`groups`/`role`) via fallbacks, so the
  same `{tenant_id}:{role}` role interpretation works for either issuer. Backward-compatible.

The backend is native per cloud end-to-end: `AUTH_PROVIDER` selects the authorizer verify + claims
mapper **and** the httpOnly-cookie session refresh (`services/auth/handler.py` → `cognito_refresh`
on AWS / `entra_refresh` on Azure, via the OAuth2 refresh-token grant). So **reload-persistence
works on Entra too** — a page reload silently restores the session exactly as on Cognito (the
backend needs `ENTRA_TOKEN_ENDPOINT` + `ENTRA_CLIENT_ID` env to do the exchange). Remaining caveat:
ROPC covers local accounts only (no social/MFA) — swap `EntraClient` for an MSAL redirect flow
behind the same `authClient` seam if those are needed. Validate against a real Entra tenant.

**Tests:** `EntraClient.test.ts` (ROPC password/refresh grants + error mapping, mocked fetch),
`jwt.test.ts` (Entra claim shape → Session), `SessionProvider.test.tsx` re-pointed to mock
`authClient`. 100 auth-suite tests green; `npm run typecheck` clean.
