# Task FE-06 — Routing, RBAC & Navigation

## Objective

Define the full route tree, which roles see which routes/nav items, and stand up the app shell (sidebar/topbar) that every domain page (Task 07) renders inside.

## Depends On

Tasks 03 (Sidebar/TopBar/PageShell components), 04 (Session/RoleGuard).

## Domain Convention

Production uses a single SPA. The `{tenant}.shipx.co` subdomain pattern seen in the mockups (e.g. `acme.shipx.co/track`) is used only for tenant-branded **customer-facing** surfaces (public tracking, customer portal) so a tenant's customers see that tenant's branding before any auth happens. Staff/admin/platform routes are served from the apex `shipx.co` regardless of tenant — staff don't need a branded pre-auth experience, and `tenant_id` for them comes from the JWT, never the URL. Confirm final domain strategy in [13_deployment_and_cicd.md](13_deployment_and_cicd.md) (single CloudFront distribution with two CNAME patterns, same `dist/` bundle).

## Public Routes (no auth)

| Path | Screen source | Notes |
|---|---|---|
| `/` | `pages/marketing/LandingPage.tsx` | Public marketing landing page, ported from `Shipx_frontend_design/Shipx Landing Page v2.html` (the landing prototypes sit outside `screens/`). `RootRedirect` (in `routes.tsx`, not `routeTable.ts` — it's a dual-behavior apex, not a single guarded page) renders it for signed-out visitors; signed-in visitors are redirected to `homePathForRole(session.role)` as before. Not itself route-guarded. |
| `/login` | `auth/auth-screens.jsx` → `LoginScreen` | |
| `/register`, `/register/:slug` | `pages/auth/RegisterScreen.tsx` | **Customer** self-registration → `POST /v1/register/{slug}`. Bare `/register` (no slug) renders a "Which are you?" chooser (customer → use company link/invite; shipping company → `/get-started`), never the form. |
| `/get-started` | `pages/auth/RequestOnboardingScreen.tsx` | **Shipping-company** onboarding *request* (a lead) → `POST /v1/onboarding-requests`. No account, no password, no tenant created. Deliberately distinct from customer sign-up — see note below. |
| `/forgot-password` | `auth-screens.jsx` → `ForgotPasswordScreen` | |
| `/reset-password?token=...` | `auth-screens.jsx` → `SetPasswordScreen` | |
| `/track`, `/track/:code` | `gapfix/gapfix-screens-a.jsx` → `PublicTracking` | `GET /v1/shipments/{code}?phone={phone}` — no JWT. Served under tenant subdomain for branding. |

### Implementation notes / ground-truth gaps found

- **Shipping-company onboarding separated from customer sign-up (2026-10-11):** companies (tenants) previously had no public entry point, and the only "register" surface (`/register`) demanded a company slug and spoke to *customers*, so a company landing there dead-ended. Added a distinct public lead flow and kept the two audiences unmistakable in both directions:
  - **`/get-started`** (`RequestOnboardingScreen`) is the shipping-company partnership *request* — headline "Partner with ShipX", explicit "Are you a customer?" off-ramp to sign-in, a plain `POST /v1/onboarding-requests`, and no password field (it creates no account).
  - **`/register/:slug`** (`RegisterScreen`) is the customer account form — headline "Create your customer account", with a mirror line pointing companies to `/get-started`.
  - **Bare `/register`** no longer dead-ends on a "missing company" warning: it renders a two-way chooser (customer vs shipping company).
  - **`LoginScreen`** footer carries two labelled CTAs: "Customer of a shipping company? → Create your account" (`/register`) and "Are you a shipping company? → Onboard with ShipX" (`/get-started`).
  - API clients: `companyOnboardingApi.requestOnboarding` (`src/api/customer.ts`) for the public lead; `platformApi.listOnboardingRequests/getOnboardingRequest/updateOnboardingRequest` + `CreateTenantInput.onboarding_request_id` (`src/api/tenantManagement.ts`) for the admin side. Tests: `RequestOnboardingScreen.test.tsx`, `RegisterScreen.test.tsx`, `OnboardingRequests.test.tsx`.
- **Landing page gap closed (2026-07-10):** the apex path `/` previously redirected unconditionally to `/login` for signed-out visitors — no public marketing surface existed, even though the design prototypes had one (`Shipx Landing Page.html` / `... v2.html`, dated after the numbered `screens/` prototypes and never assigned to a task; v2 — same content plus the motion layer — is the implemented source). Implemented as `pages/marketing/LandingPage.tsx` + `LandingPage.module.css`, wired into the existing `RootRedirect` component. All CTAs are `<Link>`/`<a>` styled to look like buttons (not the design system's `<Button>`, which renders a `<button>` — nesting an anchor inside a button is invalid HTML and breaks keyboard/screen-reader focus). "Start free trial" → `/register`; "Sign in" → `/login`; "Talk to sales" / "Book a demo" → `mailto:sales@shipx.co`.

## Platform Admin (`role: platform_admin`)

| Path | Screen source | API |
|---|---|---|
| `/platform/dashboard` | `platform/platform-screens.jsx` → `PlatformDashboard` | `GET /v1/platform/dashboard` |
| `/platform/onboarding-requests` | `pages/platform/OnboardingRequests.tsx` | `GET /v1/platform/onboarding-requests`, `PATCH …/{id}`; **Provision** navigates to `/platform/tenants/new` with the lead in router state (pre-fill + `onboarding_request_id`). Sidebar entry carries a live pending-lead count badge (`useOnboardingPendingCount`). |
| `/platform/tenants` | → `TenantList` | `GET /v1/platform/tenants` |
| `/platform/tenants/new` | `pages/platform/CreateTenantPage.tsx` | `POST /v1/platform/tenants`; accepts an optional lead via `useLocation().state.lead` — pre-fills company/contact/countries and sends `onboarding_request_id` to link + close the lead. |
| `/platform/tenants/:id` (tabs: overview/users/usage/config/audit) | → `TenantDetail`, `TenantOverview`, `TenantUsers`, `TenantUsage`, `TenantConfig`, `TenantAudit` | `GET/PATCH/DELETE /v1/platform/tenants/{id}`, suspend/activate/reactivate |
| `/platform/tenants/:id` → impersonate action | n/a (modal) | `POST /v1/platform/tenants/{id}/impersonate` — see Task 08 |
| `/platform/settings`, `/platform/settings/notifications`, `/platform/settings/plans` | → `PlatformSettings`, `PlatformGeneral`, `PlatformNotifications`, `PlatformPlans` | `GET/PUT /v1/platform/settings` |
| `/platform/audit-log` | `reports/reports-screens.jsx` → `PlatformAuditLog` | `GET /v1/platform/audit-log` |

**Sidebar (role color `--color-role-platform`):** Dashboard, Tenants, Settings, Audit Log.

## Tenant Admin (`role: tenant_admin`)

| Path | Screen source | API |
|---|---|---|
| `/dashboard` | `tenant-admin/tenant-admin-screens.jsx` → `TenantAdminDashboard` | tenant report/summary endpoints |
| `/admin/users`, `/admin/users/:id` | → `StaffUserList`, `StaffUserProfile`, `InviteStaffModal` | `GET/POST /v1/tenant/users`, `PATCH/DELETE /v1/tenant/users/{id}`, resend-invite, reset-password |
| `/admin/customers`, `/admin/customers/:id` (tabs: profile/shipments/billing/claims/GDPR) | → `CustomerList`, `CustomerProfile`, `CustomerProfileTab`, `CustomerShipmentsTab`, `CustomerGDPRTab` | `GET/POST/PATCH/DELETE /v1/customers`, `GET /v1/customers/{id}/export` |
| `/admin/config` | `tenant/tenant-config-screens.jsx` → `CompanySettings` | `GET/PUT /v1/tenant/config` |
| `/admin/config/dollar-rate` | → `DollarRatePage` | `GET/PUT /v1/tenant/dollar-rate`, `GET /v1/tenant/rate-history` |
| `/admin/config/cbm-rate` | → `CbmRatePage` | `GET/PUT /v1/tenant/cbm-rate` |
| `/admin/config/charge-types` | → `ChargeTypesPage`, `ChargeTypeModal` | `GET/POST /v1/tenant/charge-types`, `PUT/DELETE /v1/tenant/charge-types/{id}` |
| `/admin/config/notifications` | → `NotificationTemplatesPage` | `GET /v1/tenant/notification-templates`, `GET/PUT /v1/tenant/notification-templates/{event_type}/{channel}` |
| `/admin/config/webhooks` | `gapfix/gapfix-screens-b.jsx` → `WebhookConfig` | See Task 08 — `webhook_config` on `PUT /v1/tenant/config`, rotate-secret, test |
| `/admin/reports` | `reports/reports-screens.jsx` → `TenantReports` | tenant reporting endpoints |
| `/admin/notifications/log` | → `NotificationLog`, `NotifDetailModal` | `GET /v1/notifications/log`, `GET /v1/notifications/log/{id}`, retry |

Tenant Admin also sees the full Operations + Billing + Claims/Refunds + Release Notes route groups below (read/approve access, per the role column in each table) — the design reuses the same screens with a tenant-admin-scoped nav rather than duplicating pages.

**Sidebar (role color `--color-primary`):** Dashboard, Users, Customers, Configuration, Reports, Notifications.

## Operations — Containers, Packing Lists, Manifests, Tracking

Shared between China Office Staff and Nigeria Office Staff (different actions enabled per role — see the Roles column).

**China office home (2026-11-17, audit UX-10):** `/work-queue` (`pages/china/ChinaWorkQueue.tsx`, china_office_staff only) is China staff's home (`roleHome.ts`; was `/containers`) and the first menu item. Its queues link to `/packing-lists?status=rejected`, `?status=draft`, `/manifests?status=pending` and `/billing/disputes?status=escalated_china`: those three lists read `?status=` through `lib/useStatusParam.ts` (an unknown value means no filter; changing the filter replaces the history entry).

| Path | Screen source | Roles (write access) | API |
|---|---|---|---|
| `/containers`, `/containers/new` | `china/china-screens.jsx` → `ContainerList`, `CreateContainer` | china_office_staff (create) | `GET/POST /v1/containers` |
| `/containers/:id` (tabs: overview/packing-lists/manifest/documents/tracking) | → `ContainerDetail`, `ContainerOverview`, `ContainerPLs`, `ContainerDocs`, `ContainerTracking`, `TrackingStepper` | china + nigeria + tenant_admin (read); status update = china/nigeria | `GET /v1/containers/{id}`, `/events`, `/documents`, presigned-url |
| `/containers/:id/status` (modal) | `nigeria/nigeria-screens.jsx` → `UpdateStatusModal`, `UpdateStatusPicker` | china_office_staff, nigeria_office_staff (jurisdiction-restricted stages — see Task 07 business rules) | `PATCH /v1/containers/{id}/status` |
| `/packing-lists`, `/packing-lists/new` (3-step wizard) | `china-screens.jsx` → `PackingListList`, `CreatePackingList`, `PLStep1/2/3` | china_office_staff (create), tenant_admin/china (approve) | `GET/POST /v1/packing-lists`, submit/approve/reject, bulk-approve/reject |
| `/packing-lists/import` (3-step wizard) | `reports/reports-screens.jsx` → `BulkImport`, `ImportStep1/2/3` | china_office_staff | `POST /v1/packing-lists/import` — see Task 10 |
| `/packing-lists/:id` | → `PackingListDetail` | read: china/nigeria/tenant_admin/customer (own) | `GET /v1/packing-lists/{id}`, export/PDF (Task 10) |
| `/manifests`, `/manifests/:id` | `nigeria/nigeria-screens.jsx` → `ManifestList`, `ManifestDetail`, `VerifyManifestModal` | nigeria_office_staff (verify/resolve) | `GET /v1/manifests`, verify, resolve-discrepancy |

**Sidebar:** China Office (role color `--color-role-china`): Containers, Packing Lists. Nigeria Office (role color `--color-role-nigeria`): Dashboard, Manifests, plus Billing/Claims/Refunds/Release Notes below.

## Billing & Disputes (Nigeria Office Staff, Tenant Admin)

| Path | Screen source | API |
|---|---|---|
| `/billing`, `/billing/:id` | `nigeria/billing-screens.jsx` → `BillingList`, `BillingDetail`, `RecordPaymentModal`, `AddChargeModal` | `GET/POST /v1/billing`, `GET /v1/billing/{customer_id}`, charges, storage-fees |
| `/billing/carryovers` | → `CarryoverLedger`, `ApplyCarryoverModal` | `GET /v1/billing/carryovers`, exempt, apply-carryover |
| `/billing/disputes`, `/billing/disputes/:id` | → `CbmDisputes`, `DisputeDetailPanel` | `GET/POST /v1/billing/disputes`, acknowledge/resolve/reject |

## Claims & Refunds (Nigeria Office Staff, Tenant Admin)

| Path | Screen source | API |
|---|---|---|
| `/claims`, `/claims/:id` | `nigeria/claims-refunds-screens.jsx` → `DamageClaimsList`, `DamageClaimDetail`, `StartInspectionModal`, `ResolveClaimModal` | `GET/POST /v1/claims`, inspect, resolve |
| `/claims/missing-items` | → `MissingItems`, `LogMissingItemModal` | `GET/POST /v1/claims/missing-items`, `PATCH /v1/claims/missing-items/{id}` |
| `/claims/seized-items` | → `SeizedItems` | `GET/POST /v1/claims/seized-items`, `PATCH /v1/claims/seized-items/{id}` |
| `/refunds`, `/refunds/:id` | → `RefundRequestsList`, `RefundDetail`, `RefundStepper`, `AccountsReviewModal`, `ApproveRefundModal` | `GET/POST /v1/refunds`, review/approve/reject |

## Release Notes & Warehouse

| Path | Screen source | Roles | API |
|---|---|---|---|
| `/release-notes`, `/release-notes/:id` | `nigeria/release-notes-screens.jsx` → `ReleaseNotesList`, `ReleaseNoteDetail`, `SplitReleaseModal` | nigeria_office_staff, tenant_admin (generate/split), warehouse_attendant + customer (read) | `GET/POST /v1/release-notes`, split |
| `/warehouse` | → `WarehouseView`, `RecordPickupModal` | warehouse_attendant | `PATCH /v1/release-notes/{id}/release` |

## Customer Portal (`role: customer`, no `/admin` prefix)

| Path | Screen source | API |
|---|---|---|
| `/my-shipments`, `/my-shipments/:code` | `customer/customer-screens.jsx` → `CustomerShipments`, `CustomerShipmentDetail`, `CustomerStepper` | `GET /v1/shipments`, `/v1/packing-lists` (own) |
| `/my-billing`, `/my-billing/:id` | → `CustomerBilling`, `CustomerBillingDetail` | `GET /v1/billing/{customer_id}`, payment confirm/gateway redirect |
| `/my-billing/:id/payment-success`, `/payment-failed` | gateway callback routes | payment webhook lands server-side; these are client redirect targets only |
| `/my-billing/:id/refund-request` | → `CbmDisputeModal` (dispute) / refund preference capture | `POST /v1/billing/{billing_id}/dispute`, `POST /v1/refunds` |
| `/my-claims`, `/my-claims/new` (3-step) | → `CustomerClaims`, `CustomerFileClaim` | `GET/POST /v1/claims`, `/v1/uploads/presigned-url` |
| `/account` (tabs: profile/notifications/privacy) | → `CustomerAccount`, `CustomerProfileTab2`, `CustomerNotificationsTab`, `CustomerPrivacyTab` | `PATCH /v1/customers/{id}`, `GET /v1/customers/{id}/export`, `DELETE /v1/customers/{id}` |

**Sidebar/topnav (role color `--color-role-customer`):** Shipments, Billing, Claims, Account. Uses `CustomerTopNav`, not the staff `Sidebar` — customer portal is a horizontal-nav layout per the mockups, not a left sidebar.

## Reports & Notification Log

Cross-cutting, embedded in Tenant Admin / Platform Admin nav above, not a separate role. Screens: `reports/reports-screens.jsx` (`TenantReports`, `PlatformAuditLog`, `NotificationLog`).

## Route Guard Implementation

```tsx
// src/shell/routes.tsx
<Route path="/admin/config/webhooks" element={
  <RoleGuard allow={["tenant_admin"]}><WebhookConfigPage /></RoleGuard>
} />
```

Build the nav item list per role as data (not JSX) — one `navConfig.ts` exporting `Record<Role, NavGroup[]>` — so `Sidebar`/`CustomerTopNav` render declaratively and a route's guard list and its nav visibility can be derived from the same source, avoiding drift between "what's in the sidebar" and "what's actually guarded."

### Multi-role staff support (2026-07-20, migration 039)

`Session` gained `roles: UserRole[]` (every role the user holds) alongside the existing
`role` (the currently active/display role — defaults to primary, user-switchable). This
is the frontend mirror of `shared/tenant_context.py`'s `TenantContext.roles`.

- **`RoleGuard`** now checks `allow.some(r => session.roles.includes(r))` instead of
  `allow.includes(session.role)` — a route allowed for *either* of a multi-role user's
  roles must not bounce them just because the other role happens to be active for
  nav/display. The wrong-role redirect still targets `homePathForRole(session.role)`
  (the active role), unchanged.
- **Every `Record<UserRole, X>` lookup is unchanged** — `navConfig`, `homePathForRole`,
  `buildBreadcrumb`, `pageTitle`, `visualRoleFor`, `ROLE_DISPLAY` all still key off the
  single active `session.role`. Deliberately **not** merging/unioning navigation across
  a user's roles — the active-role toggle (below) covers that more simply, and keeps
  every one of these lookups untouched.
- **Role-switch toggle:** a small `<select>` in `TopBar`'s user menu
  (`frontend/src/shell/TopBar.tsx`'s `roleOptions`/`activeRole`/`onRoleChange` props,
  wired from `StaffLayout.tsx`), rendered only when `session.roles.length > 1`.
  Calls `useSession().setActiveRole(role)` (new on `SessionContextValue`,
  implemented in both `SessionProvider` and `LocalAuthProvider`) which just swaps
  `session.role` client-side — **no network call, no new token**. Authorization is
  unaffected either way: it's always governed by the full `session.roles` set
  server-side, never by which role happens to be "active."
- **Ground-truth fix (2026-07-20):** `StaffLayout.tsx`'s `onRoleChange` handler
  originally called only `setActiveRole` — the sidebar/breadcrumb correctly updated
  (they're `session.role`-driven), but the current route never changed, so the page
  stayed mounted at whatever URL the *previous* role happened to be on. If that page
  didn't make sense under the new role (or its data hooks assumed the old role's
  shape), the user saw a broken/partial view until they separately clicked a nav
  link, which navigates and fixes it. Fixed by also calling
  `navigate(homePathForRole(nextRole))` in the same handler — switching roles now
  lands on that role's home page, same as login/impersonation-exit already did.
  Regression test: `StaffLayout.test.tsx`.
- **Ground-truth fix (2026-07-20):** the active role is UI-only state and is
  deliberately never persisted — `src/auth/` has a hard CI grep check banning
  `localStorage`/`sessionStorage` outright (session-theft risk, see
  `11_security_and_compliance.md`), and the active role isn't a security boundary
  worth an exception to that rule anyway (authorization is always governed by the
  full `session.roles` set server-side, regardless of which role is "active").
  Consequence: a full page reload rebuilds `session.role` from the JWT's primary
  role, but the URL — and therefore the rendered page — doesn't change. Reported
  live: switch to Warehouse, reload, and the TopBar selector snaps back to
  "Nigeria Office Staff" while the page underneath is still `/warehouse`. Fixed
  without any storage: new `navConfig.ts::roleForPath(pathname, roles, preferred)`
  reverse-looks-up which of the user's assigned roles' nav trees "owns" the
  current path (preferring the currently-active role when it already owns the
  path, so shared routes like `/billing` — reachable by both `tenant_admin` and
  `nigeria_office_staff` — don't flip-flop). `StaffLayout.tsx` runs this in a
  `useEffect` keyed on `location.pathname`/`session.role`/`session.roles` and
  calls `setActiveRole` when they disagree — self-healing on reload, direct
  links, bookmarks, and browser back/forward, with no persistence mechanism to
  keep in sync or go stale. Tests: `navConfig.test.ts` (`describe('roleForPath')`),
  `StaffLayout.test.tsx` (2 new cases: correction + no-false-positive-flip).
- **Local dev:** `LocalAuthProvider`/`RoleSwitcher` add one additional fixed dev
  identity, `nigeria_warehouse` (`nigeria_office_staff` + `warehouse_attendant`),
  alongside the existing six single-role entries — the only dev identity with
  `roles.length > 1`, so it's the one that exercises the role-switch toggle locally.
  `scripts/local_server.py` accepts an `X-Roles` header (comma-separated) alongside
  the existing single `X-Role`.

## Acceptance Criteria

- [x] Every route in the tables above exists, guarded by the listed role(s), via `RoleGuard` — `shell/routeTable.ts` declares all ~60 routes (path/allow/title/layout); `shell/routes.tsx` is the single place that turns each entry into exactly one `<Route>`, wrapped in `RoleGuard` unless `allow: 'public'`. ~~Real screens land in Task 07 — until then each route renders `RouteStub` (still fully guarded and shelled).~~ **Since 2026-11-17 (audit FE-08):** every route has a real screen, registered in `shell/screens.tsx` (`PUBLIC_SCREENS` for `allow: 'public'`, `GUARDED_SCREENS` for the rest — the old name `STAFF_SCREENS` also held customer pages); `RouteStub` is deleted. `routes.test.tsx` fails if a route has no screen, a screen has no route, a guarded page sits in the public map, or a path is declared twice. A route that somehow ships without a screen renders `NotFoundPage`. Route order in `routeTable.ts` does not matter: React Router ranks by specificity.
- [x] Nav items (sidebar for staff/admin, top nav for customer) are generated from one declarative `navConfig.ts`, not hand-duplicated JSX per role — `shell/navConfig.ts`; `navConfig.test.ts` asserts every nav path is guarded for that exact role in `routeTable`, so nav and guards can't drift apart.
- [x] Hitting a route your role can't access redirects to that role's home page (not a blank screen or crash) — `RoleGuard` now distinguishes "no session" (→ `/login`) from "wrong role" (→ `homePathForRole(session.role)`, shared with `LoginScreen`'s post-login redirect via `auth/roleHome.ts`). Verified live in a browser via the local dev shim (switching roles mid-session client-side redirects correctly) and in `routes.test.tsx`.
- [x] Hitting an unknown route renders a 404 page, not a blank screen — `shell/NotFoundPage.tsx`, catch-all `<Route path="*">` in `routes.tsx`.
- [x] Tenant Admin nav correctly surfaces Operations/Billing/Claims/Refunds/Release Notes screens alongside Admin-only screens (config, users, customers) without duplicating page components — confirmed visually (screenshot) and in `routes.test.tsx`; one `AppSidebar` renders whichever `navConfig[role]` groups apply, no separate "tenant admin sidebar" component.
- [x] Customer portal uses the horizontal top-nav layout (`CustomerTopNav`/`CustShell`), not the staff sidebar layout — confirmed against `customer-screens.jsx`'s `CustomerTopNav`/`CustShell` mockup source, ported in `shell/CustomerTopNav.tsx` + `shell/CustShell.tsx`; `routeTable.test.ts` asserts no route with `allow` containing `customer` ever uses `layout: 'staff'`.

**Implementation notes / judgment calls** (flagged per Doc-First Rule, not silently assumed):
- `/dashboard` is allowed for both `tenant_admin` and `nigeria_office_staff` — the doc's table lists it only under Tenant Admin, but the Nigeria Office sidebar prose lists "Dashboard" as its first item too.
- `/packing-lists/:id` and `/release-notes(/:id)` list "customer (own)" as a reader in the Operations/Release Notes tables, but customers reach the same data via their own `/my-shipments/:code` (customer layout) instead — customer is deliberately omitted from those routes' `allow` so a customer can never land inside the staff sidebar shell.
- `Session` has no display name (only `tenantId`/`userId`/`role` from the JWT, per `04_auth_and_session.md`) — `AppSidebar` and `CustomerTopNav` only show a logout control for now, no avatar/name chip. `Sidebar` (Task 03) was extended so its logout button no longer requires a `user` prop. A real profile fetch lands in Task 07.
- In local dev (`VITE_ENVIRONMENT=local`), `App.tsx` mounts `LocalAuthProvider` + a floating `RoleSwitcher` around the *entire* real route tree (not just the isolated `/auth-preview` demo from Task 04), so the full app can be browsed and role-switched without Cognito.
- `RoleGuard`'s prop changed from a single `redirectTo` to `unauthenticatedRedirectTo` (default `/login`) now that wrong-role redirects are role-specific — a breaking change to a FE-04 component, justified by this task's AC requiring the two cases to diverge.
- `RoleGuard`'s allow-check is now a set-intersection against `session.roles` (multi-role staff support, migration 039) — verified in `RoleGuard.test.tsx` with a multi-role session allowed in via a non-active role, and still blocked when none of its roles match.

## Implementation notes — audit Phase 3: blocked flows (2026-11-16)

- **UX-03 Nigeria menu.** `navConfig.nigeria_office_staff` now has the shared Operations group (Containers, Packing Lists, Manifests) between Dashboard/Announcements and Billing & Disputes; Manifests is no longer listed twice. A test checks every Nigeria menu entry is a path the route table lets that role open.
- **UX-01 routes.** `/billing/disputes/:id` (`china_office_staff`, `nigeria_office_staff`, `tenant_admin`, staff layout) is `DisputeDetail`, declared before `/billing/:id`. `DisputeList`'s View goes there for China staff and to the invoice for everyone else.
- **UX-02 route.** `/my-release-notes/:id` (customer layout) is `MyReleaseNote`; `ReleaseNoteCard` shows on `MyBillingDetail` and `MyShipmentDetail` once a note exists for the container.
- **UX-04 return path.** `RoleGuard` sends a signed-out visitor to `/login?next=<path+query>` (`auth/returnPath.ts::loginUrlFor`); `LoginScreen` goes to `next` after sign-in, else the role home. For the Entra round trip the path is kept in `sessionStorage` under `shipx_login_next` by `pages/auth/returnPath.ts` (deliberately *not* in `src/auth/`, which CI forbids from touching web storage) and restored by `AuthCallback`. A session-timeout logout redirects through `RoleGuard` too, so it keeps the page as well. **`safeNextPath` is the only gate**: it accepts only a plain in-app path, and refuses absolute URLs, `//host`, backslashes, control characters, encoded backslashes / double slashes, over-long values, and the sign-in screens themselves (they would loop).
- **UX-05 global search (2026-11-16).** The header search box is now `shell/GlobalSearch.tsx`, a real lookup (`GET /v1/search`, `21_missing_endpoints.md` Part 12) on every staff page and in the customer top bar: container number, packing-list reference, tracking code, invoice number, release-note reference, customer name (and phone, for tenant admin and Nigeria staff). `StaffLayout` renders it through `TopBar`'s `search` slot (the old `onSearch`/`searchPlaceholder` props, and the page-registered `useTopBarSlot({ onSearch })` slot, are removed; `ContainerList` keeps its own table search box); `CustomerLayout` passes it to `CustomerTopNav`. Platform admins get no box (the server refuses them). The placeholder names what the role can find (`searchPlaceholderFor`, copy only; the server decides). Results open through `searchResultPath`: staff to `/containers/:id`, `/packing-lists/:id`, `/billing/:id`, `/release-notes/:id`, `/admin/customers/:id`; customers to `/my-shipments/:id`, `/my-billing/:id`, `/my-release-notes/:id` (`searchRoutes.test.ts` proves every kind a role can find lands on a `routeTable` entry that admits that role). ARIA combobox + listbox: arrow keys move the highlight, Enter opens it (the top match if none), Escape closes then clears, Ctrl/Cmd+K focuses it. Under 860px it collapses to an icon that opens a full-width bar. Requests are debounced 250 ms and never sent under 2 characters.
- **FE-01 error boundaries.** `shell/ErrorBoundary.tsx`: one at the app root (`variant="app"`, outside the router and providers), one around each layout's routed content (`ContentErrorBoundary`, resets on route change, "Go home" points at the role's home), and `QuietBoundary` around optional chrome (announcement and quota banners), which disappears if it breaks instead of taking the page down. It logs the error *name*, the page with ids redacted and the component names, never the message or props (the message in development only).

## Code splitting (audit FE-02, 2026-11-16)

`shell/routes.tsx` no longer imports pages statically. Every page loads on demand through `lazyNamed(areaLoader, 'PageName')` (`lib/lazyPage.ts`), and an **area module** (`shell/areas/*.ts`, one re-export per page) gives each area exactly one chunk: `platform`, `tenantAdmin` (admin and shared staff pages), `china`, `nigeria`, `warehouse`, `customer`, `print`, `accountScreens` (register, get-started, invite, activate, forgot and reset password), plus the two layouts (`StaffLayout`, `CustomerLayout`). **In the entry chunk:** sign-in, the sign-in callback, the landing page and public tracking, as the brief asked. To add a page: export it from its area module and add one `lazyNamed` line in `routes.tsx`; `routes.test.tsx` (`code splitting (FE-02)`) fails if a page or layout is imported statically instead, which would drag it back into the entry chunk for everyone.

Two `Suspense` boundaries, both using `SessionLoading` (the session-restore spinner): outside the layout (its own chunk, first guarded page of a session) and inside it around the page (`inline`, so the sidebar or top bar stays on screen while a page chunk loads). A chunk that fails to download is retried once (a dropped mobile connection); a second failure reaches the error boundary (after a deploy the old file is gone, and a reload is the fix).

**Measured** (production build, JS only, raw / gzip): before, one 1,049 kB / 276 kB bundle for every role. After, the entry plus its shared chunk is 421 kB / 129 kB, and the first page of each role downloads: customer 530 kB / 162 kB, platform admin 505 kB / 156 kB, China staff 587 kB / 178 kB, Nigeria staff 628 kB / 187 kB. Checked in a browser against the built bundle: a customer's first page requests none of the `china`, `nigeria`, `platform`, `tenantAdmin`, `warehouse`, `print` or `StaffLayout` chunks. Initial CSS 184 kB to 67 kB (Vite splits CSS per chunk). Not done: the 257 kB shared `client` chunk (React, router, query, the API client) is loaded by everyone.

- **UX-07 customer claim page (2026-11-16).** `/my-claims/:id` (customer layout, customer role) is `MyClaimDetail`; each card on `/my-claims` opens it (a `role="link"` card, Tab-reachable, Enter or Space opens). It is one more entry in `routeTable.ts`, the customer area module and `routes.tsx`.

- **UX-08 China menu and route (2026-11-16).** `/claims/missing-items` now admits `china_office_staff` (and no other claims route does), and the China menu lists **Missing items** under Coordination, after Manifests and CBM disputes. `navConfig.test.ts` and `routeTable.test.ts` pin both.

## Breadcrumbs (audit FD-45/FD-46, 2026-11-17)

**Every crumb but the last is a link, on every page of both layouts.** Before this the trail was `<span>`s styled as links that did nothing, copied from the sidebar (menu group, then item), so group names like "Operations" appeared, record pages other than containers did not name their record, sub-pages took their parent's trail ("Billing & Disputes / Billing" on CBM disputes and the carryover ledger), all nine settings pages read "Configuration", and the customer portal had none.

- **Where a page lives** is declared in `shell/routeTable.ts`: `parent` (the route above it) and `crumb` (its short name). `shell/breadcrumbs.ts::breadcrumbTrail(pathname, roles, labels)` walks the parents, filling route parameters from the current URL (`/packing-lists/:id/edit` links back to the same list). Top-level pages (dashboards, lists, warehouse, profile, work queue, missing and seized items) have no parent and show no breadcrumb. No sidebar group name is ever used.
- **Record names**: a record page calls `useBreadcrumbLabel(record?.label)` once loaded (invoice number, packing-list reference, container number, claim reference, release-note number, person or company name, refund type); until then the route's `crumb` stands in ("Invoice"). A child page names its parent record by passing the parent's route: the edit page names its packing list, and `pages/customer/useInvoiceCrumb.ts` names the invoice on the refund-request and payment-success pages. ~~The staff top bar's container-number suffix is still honoured as a fallback.~~ (Removed 2026-11-20 with the top-bar slot; the container page calls `useBreadcrumbLabel` like every other record page.)
- **The same for every role**, except that a parent the role cannot open is left out (China staff on a CBM dispute see "CBM disputes / Dispute", not a Billing link that would bounce them home), and a trail with nothing left above the page is not shown.
- **Component**: `shell/Breadcrumb.tsx`, a `nav` labelled "Breadcrumb" holding an `ol`; ancestors are `Link`s, the last item has `aria-current="page"`; keys are the link targets (not the text, which could repeat). Below 600 px the list is replaced by one "← parent" link. ~~The staff layout renders it in the top bar; the customer layout renders it above the page content.~~ Since FD-14 (2026-11-20) both layouts render it at the top of the content area, above the page's `PageHeader`, so it is there while the page is still loading. Both layouts provide `BreadcrumbContext` (`useBreadcrumbLabelState`).
- **Tests**: `shell/breadcrumbs.test.tsx` walks all 78 routes against the brief's table (and fails on a route with no expectation), checks every non-final crumb is a link, no group names, the same trail for every role that can open the page and its parents, record and parent-record labels, and the component's landmark, list, current page and back link. Mutation-checked. Checked in Chromium against the dev data as each role: 30 pages, every first crumb clicked through to its target; phone width shows the back link.
- ~~Not done here: FD-47.~~ **FD-47 done (2026-11-17):** the hand-written "Back to …" links are gone from 19 pages (detail pages, their error states, the settings pages' "Back", the China dispute page's top button); the breadcrumb is the way back. Kept on purpose: form "Cancel", wizard "Back" steps, dialog buttons, the sign-in flow, print pages, and next-action buttons on result screens (payment received or failed, tenant created). `pages/noBackLinks.test.ts` fails if one returns.


## Tab titles and focus after navigation (audit FD-48, 2026-11-20)

- **Before:** every one of the 78 routes shared the tab title "ShipX", so three open tabs (an invoice, a container, a claim) could not be told apart, and history and bookmarks were useless.
- **Title** (`shell/documentTitle.ts::documentTitle`): the breadcrumb trail read upwards from the current page, then whose account it is: `INV-A-002 · Billing · Acme Shipping`, `Edit · PL-0007 · Packing lists · Acme Shipping`. A record page shows its route's name until the record loads (`Invoice · Billing · …`). A top-level page uses its route title (`Containers · Acme Shipping`). Staff tabs end with the tenant's branding display name; platform-admin, customer and public tabs end with "ShipX". Set by `useDocumentTitle` in `StaffLayout` and `CustomerLayout`, and by `RouteTitle` in `routes.tsx` for public and shell-less (print) routes. An unknown path reads "ShipX".
- **Route titles** in `routeTable.ts` are now sentence case and name the page as its header does ("Staff", "Audit log", "New container", "Invoice"); they were Title Case and partly descriptive ("Staff User Profile", "Billing Detail").
- **Focus** (`shell/headingFocus.ts::useFocusOnNavigate`, used by `PageHeader` and `ResultScreen`): after an in-app navigation, keyboard focus moves to the new page's `<h1>` (`tabIndex=-1`, no scroll, no ring), so a screen reader announces the page and Tab starts from its top. Not on the first load (React Router's location key `default`), once per location, and nothing outside a router.
- **Tests** (`shell/documentTitle.test.tsx`): record, parent and tenant order; the route's name before the record loads; top-level and public titles; every staff, customer and shell-less route has a distinct title ending in the owner (the two single-page aliases `/register/:slug` and `/track/:code` excepted); every route title is sentence case; the hook sets `document.title`; focus stays put on first load and lands on the new heading after a click. Mutation-checked: two staff routes given one title fail the distinctness case.

## Not-found page inside the app (audit FD-55, 2026-11-20)

- **Before:** a signed-in user who followed a stale link got a bare "404" page with one button and no sidebar or top bar.
- **Now** (`shell/routes.tsx::UnknownPath`): a signed-in user sees the not-found page inside their own layout (staff sidebar, or the customer portal's top nav), as a `PageHeader` titled "Page not found" with "Go to your home page" and, where there is one, a button to the nearest list above the address (`shell/nearestList.ts`: `/billing/x/oops` offers Billing; a list the user's roles cannot open is skipped, and none is offered when it is their home page). A signed-out visitor keeps the bare page, whose button now says "Sign in". While the session is still being restored the usual loading screen shows.
- The tab reads "Page not found · …" (`documentTitle` names an address that matches no route; the site root stays "ShipX").
- Tests: `shell/routes.test.tsx` (staff and customer inside their layouts with the right buttons and tab title; signed-out bare page), `shell/nearestList.test.ts`.

## The menu (audit FD-15, 2026-11-20)

- **One lit item:** an item used to be active whenever the path started with its link, so `/packing-lists/new` lit both "All packing lists" and "Create packing list", and `/claims/missing-items` lit Claims and Missing items. `navConfig.ts::activeNavPath` picks the longest item path that is the page or one of its parents; the active item carries `aria-current="page"`.
- **Sentence case** everywhere, and **one icon per item** within a role (Damage claims `alert`, Missing items `search`, Seized items `shield`, Refunds `refresh`, Release notes `qr`, Notification log `mail`, Announcements `bell`, Activity log `clock`, Warehouse `building`, the customer's My shipments `ship`).
- **Tenant admin groups:** Overview (Dashboard, Reports, Activity log), Operations (Containers, Packing lists, Manifests), Billing and claims (Billing, Damage claims, Missing items, Seized items, Refunds, Release notes), Admin (Staff, Customers, Announcements, Notification log, Settings). Nigeria staff: Overview (Dashboard, Announcements), Operations, Billing and claims. China staff: Overview (Work queue), Operations, Coordination (CBM disputes, Missing items).
- **No "Create …" items:** "Create container", "Create packing list" and "Import from Excel" left the China menu; each is a button in its list page's header (the packing-list page gained "Import from Excel" for China staff).
- **"Configuration" is "Settings"** in the menu and the breadcrumb ("Settings / Dollar rate"), as the brief's FD-46 table has it; "Users" is "Staff".
- **One user menu**, top right (`TopBar` account button → `MenuButton` with a custom `trigger`): My profile, "Work as …" for each other role of a multi-role user (it replaces the role `<select>`, which was hidden below 860 px, so phones could not switch roles), Sign out. The sidebar no longer shows the user or a log-out button.
- Tests: `shell/navConfig.test.ts` (at most one lit item on every route for every role; the deepest item wins; distinct icons; sentence case and no create pages; the admin's four groups), `shell/TopBar.test.tsx` (account menu items, role switch, sign out), `shell/Sidebar.test.tsx`, `shell/AppSidebar.test.tsx`, `shell/StaffLayout.test.tsx` (role switch through the menu).
