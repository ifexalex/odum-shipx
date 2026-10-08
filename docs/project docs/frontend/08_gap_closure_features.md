# Task FE-08 — Gap-Closure Features (Impersonation, Webhooks, Locale)

## Objective

Three features were added to the backend in the Round 2 gap-closure pass (see `00_MASTER_PLAN.md` → "Round 2 Backend Gap Closures") and already have designed screens in `Shipx_frontend_design/screens/gapfix/`. This doc ties the two together — build these once the screens they attach to (Task 07) exist.

## Depends On

Task 07 (these features attach to existing pages — webhook config attaches to the config nav, locale to the staff profile page, impersonation banner wraps the whole shell).

## 8.1 Impersonation Read-Only Banner

**Backend:** `shared/auth.py` — `get_tenant_context` centrally enforces `read_only` for impersonation sessions; any mutating HTTP verb gets a 403 `IMPERSONATION_READ_ONLY` error. See [04_auth_and_session.md](04_auth_and_session.md) for the session/token contract.

**Design source:** `screens/gapfix/gapfix-screens-c.jsx` — `ImpersonationBanner`, `ReadOnlyAction`, `ImpersonatedPortal`.

**Implementation:**

- `ImpersonationBanner` renders sticky at the very top of the page (above `TopBar`, full width), Kola-Copper-deep background, with: "Impersonating" pill, `Viewing <tenant> as <role> · read-only. All editing is disabled. Started by <admin email>`, a live countdown (`mm:ss`, ticks down from the session's 30-minute TTL), and an "Exit impersonation" button (`DELETE /v1/platform/impersonation/{session_id}`, see Task 04 exit flow).
- Mount this banner once, at the root of the authenticated app shell, conditional on `session.readOnly`. It is not a per-page concern.
- Every mutating control (button/action that would trigger POST/PUT/PATCH/DELETE) renders as `ReadOnlyAction` instead of the normal `Button` when `session.readOnly` is true — a dashed-border, not-allowed-cursor pill with a tooltip ("Disabled during read-only impersonation"). This must be a **shared wrapper**, not a per-page `if (readOnly)` check scattered across every action button — e.g. a `<Action readOnly={session.readOnly} variant="primary">Edit</Action>` component that swaps its own rendering, so no individual page can forget the check.
- Add a page-level `Banner variant="warning"` ("You're viewing this tenant as their Tenant Admin for support...") near the top of content on the most sensitive screens (customer profile, billing, user management) per `ImpersonatedPortal`'s example — this is supplementary to the sticky banner, not a replacement.
- On countdown reaching 0, force the exit flow automatically (don't wait for a failed mutation to surface the expiry).

## 8.2 Outbound Webhook Configuration

**Backend:** `services/tenant_management/models.py` (`WebhookConfigRequest`, `WebhookEventType`), `service.py` (`rotate_webhook_secret`, `test_webhook_delivery`), routes `POST /v1/tenant/config/webhook/rotate-secret` and `POST /v1/tenant/config/webhook/test`. Full contract in [05_api_client_contract.md](05_api_client_contract.md) and the Postman collection.

**Design source:** `screens/gapfix/gapfix-screens-b.jsx` — `WebhookConfig`. Route: `/admin/config/webhooks` (new tab in the existing Config side-nav, badge: "New").

**Fields:**

- Endpoint URL (`Field`, must start with `https://` — mirror the backend's Pydantic pattern validation client-side too, so the user gets instant feedback rather than waiting for a 422).
- Enabled toggle (`ToggleSwitch`).
- Signing secret display: **always masked** (`whsec_••••••••••••••••3f9a` — show only the last 4 characters, exactly as the backend masks it to `"****"` on every `GET`). "Reveal" is not a real action — the backend never returns the full secret on read, only once at creation/rotation. Implement "Reveal" as actually triggering `POST .../rotate-secret` (with a confirm step — rotating invalidates the old secret immediately) rather than trying to unmask a value the API never sends. Relabel the button if needed to avoid implying a non-rotating reveal exists.
- Subscribed events: one `ToggleSwitch` row per `WebhookEventType` value (`container.status_updated`, `billing.payment_due`, `release_note.generated`, `packing_list.approved`) — render the event code in `Mono` beneath the label, exactly as designed.
- "Send test event" button → `POST /v1/tenant/config/webhook/test`, show the returned `{success, status_code, error}` inline (toast or banner) rather than a generic "sent" confirmation — a tenant configuring this needs to see the actual HTTP status their endpoint returned.
- "Save webhook" → `PUT /v1/tenant/config` with `webhook_config: { endpoint_url, enabled, events }` — never send `secret` in this payload, it's server-managed exclusively (see Task 05/11).

## 8.3 Staff Notification Language (Locale)

**Backend:** `locale` added to `_USER_UPDATE_FIELDS`, validated against `{"en", "zh"}`; self-service `PATCH /v1/tenant/me`; admin-driven `PATCH /v1/tenant/users/{id}`. Locale only controls **notification template language** (SMS/email/WhatsApp), not the web app's own UI language — there is no broader i18n requirement for this app; do not build a full UI translation framework for this feature.

**Design source:** `screens/gapfix/gapfix-screens-a.jsx` — `LocalePreference`. Surfaces on the staff profile page (`/admin/users/:id`), mainly relevant for China Office Staff.

**Implementation:**

- Two radio-style cards: "English (EN — default)" / "中文 (简体) (ZH — Simplified Chinese)".
- Inline `Banner variant="info"`: "Maps to `tenant_user.locale`. Notification templates render in the selected language where a ZH template exists." — keep this exact explanatory copy or equivalent; it sets correct expectations (not every template has a ZH variant yet).
- Tenant admin can set this for any staff member via `PATCH /v1/tenant/users/{id}`; a user can set their own via `PATCH /v1/tenant/me` (Task 06 — expose this as a small section on the user's own account/profile page too, not just the admin-facing staff profile).
- Customer locale: `customer.locale` exists (migration 029) but there's no customer-facing self-service setter designed or planned — it's populated by region inference, not user choice. Don't build a UI for it unless a future design adds one.

## Implementation Notes

### 8.1 Ground-truth gaps found
- `Session` type extended with `tenantName: string | null` — populated by `startImpersonation(idToken, tenantName)` so the banner shows the human-readable company name, not the raw UUID.
- `ImpersonationBanner` is a plain flex item (not `position:sticky`) mounted above `PageShell` inside a `display:flex; flex-direction:column; height:100%` wrapper in both `StaffLayout` and `CustomerLayout`.
- `StaffLayout` suppresses TopBar `actions` slot entirely when `session.readOnly` — passes `undefined` instead of the live buttons.
- `PlatformTenantDetail` now has an "Impersonate" button that calls `POST /v1/platform/tenants/{id}/impersonate`, then `startImpersonation(idToken, tenant.company_name)` and navigates to `/dashboard`.
- Page-level warning banner uses `icon="eye"` and identical copy on all three sensitive screens (`BillingDetail`, `AdminCustomerDetail`, `StaffUserDetail`).

### 8.2 Ground-truth gaps found
- "Reveal" button was relabelled "Rotate secret" as the spec required — avoids implying a non-rotating reveal exists.
- After rotation the new secret is shown once in a dismissible green banner with a copy button — it cannot be retrieved again after dismissal.
- `WebhookConfig` and `WebhookEventType` types added to `tenantManagement.ts`; `configApi` extended with `getConfig`, `updateConfig`, `rotateWebhookSecret`, `testWebhook`.

### 8.3 Ground-truth gaps found
- `locale: 'en' | 'zh' | null` added to `TenantUser` type and `UpdateUserInput`.
- `usersApi.updateMe(locale)` added for self-service `PATCH /v1/tenant/me`.
- `LocaleCard` component built as a shared design component (`src/design/components/LocaleCard.tsx`) — reused by both `StaffUserDetail` (admin) and `StaffProfile` (self-service).
- New `StaffProfile` page at `/profile`, accessible to all staff roles; TopBar user-menu click navigates there.
- No customer-facing locale picker built — confirmed against design.

## Acceptance Criteria

- [x] `ImpersonationBanner` mounts once at the app-shell root, never per-page; countdown matches the session's actual `expiresAt`
- [x] Every mutating action across the entire app respects `session.readOnly` via the shared `Action` wrapper — **done (2026-07-10)**: hero mutating openers on the reachable-during-impersonation detail pages (Billing, Claim, Refund, ReleaseNote, Manifest) converted to `Action`; a read-only sweep test (`pages/readonly-impersonation.test.tsx`) renders a sample under a read-only impersonation session and asserts zero live mutating controls. The sweep caught and fixed 5 raw-Button openers on BillingDetail.
- [x] Webhook config screen never attempts to display a real secret value — "Rotate secret" button triggers rotation with a confirmation step warning the old secret stops working immediately; new secret shown once in a copy banner
- [x] Webhook test-fire shows the actual `{success, status_code, error}` returned by the backend, not a generic confirmation
- [x] Locale preference (EN/ZH) is settable both via the tenant-admin staff profile (`PATCH /v1/tenant/users/{id}`) and via the logged-in user's own `/profile` page (`PATCH /v1/tenant/me`), hitting the two different endpoints correctly
- [x] No customer-facing locale picker is built (confirmed against design — there isn't one)
