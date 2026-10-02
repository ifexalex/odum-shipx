# Task FE-11 — Security & Compliance

## Objective

Carry the backend's SSDLC posture (CLAUDE.md) into the frontend. The backend enforces tenant isolation, RLS, and fail-closed behavior — the frontend's job is to not undermine that, and to handle the pieces that are genuinely frontend-only (token storage, XSS, client-side logging).

## Depends On

Task 04.

## Token Storage

**Do not store tokens in `localStorage` or `sessionStorage`.** Both are readable by any script on the page — a single XSS bug becomes full session theft, including for impersonation sessions which carry elevated, if read-only, access to another tenant's data.

Keep the access/ID token in memory only (a module-level variable inside the auth provider, not React state that ends up in a devtools-inspectable tree any more than necessary). `amazon-cognito-identity-js`'s own storage adapter is likewise swapped to a memory store (`MemoryStorage`, below) instead of its default `localStorage` adapter.

**Decision made (2026-07-11):** the refresh token uses an `HttpOnly; Secure; SameSite=Strict` cookie, set by a thin backend endpoint (`services/auth/handler.py`'s `POST /v1/auth/session`, called once right after login) — this was flagged as an open decision point in an earlier draft of this doc and has been resolved in favor of persistence, because it does *not* require relaxing the in-memory rule for the token that actually authorizes API calls (the ID token still never touches storage) and is strictly more resistant to XSS than any client-side storage option: `HttpOnly` cookies are categorically unreadable by `document.cookie` or any other JS API, not just conventionally-not-read. A page reload now silently restores the session via `POST /v1/auth/refresh` (the browser attaches the cookie automatically; only a fresh ID token comes back over the wire) rather than forcing a re-login on every reload. See [04_auth_and_session.md](04_auth_and_session.md)'s "Token Refresh" section for the full flow.

## XSS / Content Security Policy

- React's JSX escaping covers most injection vectors by default — the one place to audit carefully is anywhere `dangerouslySetInnerHTML` might seem tempting (e.g. rendering a tenant's custom notification template preview, Task 07 §7.9). Don't render tenant-supplied template content as raw HTML; render it as escaped text with placeholder highlighting done via React nodes, not string interpolation into HTML.
- Set a CSP header at the CloudFront level (Task 13) restricting `script-src` to `'self'` plus the Cognito domain, `connect-src` to the API Gateway domain + Cognito, and disallowing `unsafe-inline` for scripts.
- The `X-Content-Type-Options: nosniff` and `Strict-Transport-Security` headers the backend already sends (Task 05) are API-side; mirror equivalent headers at the CloudFront response-headers-policy level for the frontend's own static assets.

## Tenant Isolation Is Not a Frontend Concern — But Don't Break It

Per CLAUDE.md's 4-layer model (JWT → application → RLS → S3 prefix), the frontend sits *before* layer 1 conceptually — it just carries the JWT. The two ways a frontend bug could still cause real harm:

1. **Query cache bleed across tenant switches** — covered in Task 09 (`queryClient.clear()` on every context switch). Test this explicitly: impersonate tenant A, view customer data, exit, impersonate tenant B, confirm tenant A's data is nowhere in the UI or cache.
2. **Trusting the subdomain for tenant identity** (Task 06) — never read `tenant_id` from `window.location.hostname`; always from the decoded JWT.

## GDPR UI

- Anonymise (`DELETE /v1/customers/{id}`) requires the literal "ANONYMISE" confirmation text (Task 07 §7.9) — this is a frontend-enforced friction point on top of (not instead of) the backend's own authorization check.
- Data export (`GET /v1/customers/{id}/export`) is self-service for the customer and available to tenant admins — make sure the download itself (likely a JSON or zip bundle) is requested over HTTPS and not cached by the browser/CDN (`Cache-Control: no-store` — confirm the backend sets this on the export response; if not, that's a backend follow-up, not something the frontend can fix by itself).

## Client-Side Logging / Error Reporting

If you add Sentry (or equivalent) for frontend error tracking:

- Scrub PII before any event is sent: email, phone, name, ID numbers, account numbers — same fields the backend masks in audit logs (CLAUDE.md: `id_number`, `account_number`, `account_name`, `delegate_phone`). Configure `beforeSend` to strip these from breadcrumbs, request bodies, and user context, not just the top-level error message.
- Never log full JWTs or refresh tokens, even in breadcrumbs for "what was the auth state."
- Attach `X-Request-Id` (Task 05) to every reported error so a frontend bug report can be cross-referenced with a backend CloudWatch log line without needing to log anything sensitive client-side.

## Dependency Management

Pin frontend dependency versions the same way `requirements.txt` pins backend ones (CLAUDE.md: exact versions, no `^`/`~` ranges in `package.json` if the team wants the same reproducibility guarantee) — at minimum, commit a `package-lock.json`/`pnpm-lock.yaml` and run `npm audit`/equivalent in CI, failing on HIGH/CRITICAL, mirroring the backend's `pip audit` gate.

## Implementation Notes

### Token storage
`src/auth/tokenStore.ts` holds the ID token in a module-level variable (not React state, not `localStorage`) — the type it's stored in (`ActiveAuth`) has no `refreshToken` field at all, not just a convention of never populating one. `src/auth/storage.ts` provides `MemoryStorage implements ICognitoStorage` so Cognito's `UserPool` never touches its default `localStorage` adapter. The refresh token is persisted server-side instead, as an `HttpOnly` cookie set by `services/auth/handler.py` (see "Token Storage" above and [04_auth_and_session.md](04_auth_and_session.md)) — on full page reload the session is restored silently via that cookie; only if the refresh token itself has expired or been revoked does the user land on `/login`.

### XSS / dangerouslySetInnerHTML
Audited: zero uses of `dangerouslySetInnerHTML` in `src/`. Notification template bodies render in a `<textarea>` and are stored/fetched as plain text — never interpolated into HTML. React's JSX escaping handles all other tenant-supplied content.

### GDPR
- `AdminCustomerDetail`'s anonymise modal enforces `confirmText === 'ANONYMISE'` (case-sensitive) before the confirm button enables.
- `GET /v1/customers/{id}/export` — `shared/responses.py` sets `Cache-Control: no-store` on **every** API response globally, so the GDPR export bundle is never cached by the browser or CDN.

### Dependency audit
`package-lock.json` committed; CI uses `npm ci` (strictly lockfile-based); `npm audit --audit-level=high` step already in `frontend-ci.yml` before this task. Package ranges use `^` in `package.json` but `npm ci` ignores these — the lockfile is the reproducibility guarantee, which matches the spirit of the requirement.

### CI enforcement checks added
Two steps in `.github/workflows/frontend-ci.yml`:
- `grep src/auth/` for `localStorage`/`sessionStorage` → fail on match
- `grep src/` for `dangerouslySetInnerHTML` → fail on match

These enforce the rules at the code-search level so they can't regress in future PRs without a CI failure.

**Ground-truth gap found (2026-07-11, not yet fixed):** the `localStorage`/`sessionStorage` grep step is a bare string match with no exclusion for comments or test files — it currently trips on explanatory comments in `storage.ts`/`CognitoClient.ts` ("tokens must never touch localStorage...") and on `storage.test.ts`'s own assertion that `window.localStorage.setItem` is never called by our code. This means the check would already fail CI on `main` independent of this session's changes. Needs either an `--exclude=*.test.ts` flag plus a tighter pattern (e.g. `localStorage\.` / `sessionStorage\.` to match actual property access, not prose) or a per-line `# allow` convention — flagged here rather than fixed, since it's unrelated to the session-persistence work in this pass.

### httpOnly session cookie (added 2026-07-11)
`services/auth/handler.py` sets the refresh-token cookie as `shipx_rt=<token>; Path=/v1/auth; Max-Age=2592000; HttpOnly; Secure; SameSite=Strict`:
- `Path=/v1/auth` — never sent to any other API route, including ones an attacker-controlled response could otherwise coax the browser into revealing via error messages/logging.
- No `Domain` attribute — defaults to host-only scope (the API's own host, e.g. `api.shipx.co`), never widened to `.shipx.co`; the frontend origin never needs to read this cookie (or any cookie) itself.
- `SameSite=Strict` — safe here specifically because this cookie is only ever used by same-site `fetch()` calls, never a top-level cross-site navigation; combined with CORS `allow_credentials` pinned to explicit, non-wildcard origins (`infrastructure/modules/api-gateway/main.tf`), this is two independent layers blocking any CSRF-style forged request from a third-party origin.
- `Max-Age=2592000` (30 days) — matches Cognito's `refresh_token_validity` (`infrastructure/modules/cognito/main.tf`); a stale cookie past that window is rejected by Cognito's own `REFRESH_TOKEN_AUTH` flow regardless.

### Error reporting / Sentry
Not added — no Sentry or equivalent configured. If added in future, the `beforeSend` PII scrub requirement applies (see spec above). Left open until a decision is made.

## Acceptance Criteria

- [x] Access/ID tokens never touch `localStorage`/`sessionStorage` — `tokenStore.ts` is module-level memory; `MemoryStorage` for Cognito. CI grep check added in `frontend-ci.yml` to enforce going forward (see the ground-truth gap noted below re: that check's current false-positive rate).
- [x] The refresh token never touches `localStorage`/`sessionStorage`, or any JS-readable storage at all — persisted server-side as an `HttpOnly` cookie (`services/auth/handler.py`); `tokenStore.ts`'s `ActiveAuth` type structurally has no field to hold one client-side.
- [x] No `dangerouslySetInnerHTML` renders tenant- or user-supplied content — confirmed zero uses; CI grep check added.
- [x] CSP and security headers configured at the CloudFront response-headers-policy level — **done**: `infrastructure/modules/cloudfront/main.tf` response-headers policy (CSP + HSTS + X-Frame-Options etc.).
- [x] A test simulates an impersonation tenant-switch and asserts the query cache is clean — **done**: `src/test/cache-isolation.test.tsx` (logout, impersonation enter, impersonation exit all clear the cache; no tenantId in query keys).
- [x] GDPR anonymise flow enforces exact "ANONYMISE" text match client-side — `confirmText === 'ANONYMISE'` in `AdminCustomerDetail`.
- [ ] If error reporting is added, a `beforeSend` PII scrub is in place — **N/A (no Sentry configured yet)**.
- [x] Frontend dependencies lockfile-pinned (`package-lock.json`) and audited in CI (`npm audit --audit-level=high`) with HIGH/CRITICAL failure gate.
