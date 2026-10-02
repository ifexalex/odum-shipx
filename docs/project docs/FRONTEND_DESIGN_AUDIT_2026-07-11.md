# Frontend Design Audit — Prototype vs Implementation (2026-07-11)

Full comparison of every prototype section/subsection (`Shipx_frontend_design/screens/Section *.html` → `screens/**/*.jsx`) against the implemented pages (`frontend/src/pages/**`). Verdicts per subsection:

- ✅ **Compliant** — structure, states, and key elements match (cosmetic pixel differences ignored).
- 🟡 **Partial** — page exists and works, but named prototype elements are missing.
- 🔴 **Non-compliant** — a whole screen, tab structure, or workflow from the prototype is absent.
- ⚖️ **Intentional divergence** — deliberately different from the prototype for a documented backend/UX reason; not a defect.
- 🚫 **Data-blocked** — the prototype element cannot be honestly built because no backend data/endpoint exists for it.

---

## Scorecard

| Section | Verdict | Headline |
|---|---|---|
| §1 Authentication | ✅ (3 ⚖️) | All 4 flows + states; register/reset flows follow the real Cognito contract, not the mock |
| §2 Platform Admin | 🟡 | 2.3/2.4/2.5 ✅ · 2.1 and 2.2 missing several structures |
| §3 Tenant Admin | 🔴 | 3.6 tab structure absent; 3.1/3.2/3.5 thin vs prototype |
| §4 Tenant Configuration | 🔴 | **4.1 Company Settings not implemented at all** · 4.2–4.5 largely ✅ |
| §5 China Office | ✅ | All 6 subsections incl. wizard live-pricing, per-item reject flags, bulk partial-failure |
| §6 Nigeria Office | 🟡 | 6.1/6.2/6.3 ✅-ish · 6.4 missing the notification-confirmation step |
| §7 Billing | ✅ (1 ⚖️) | All modals + statuses + storage fees + SLA; dispute side-panel deliberately inline |
| §8 Claims & Refunds | ✅ | All 6 subsections; states, modals, stepper, threshold |
| §9 Payment & Release | 🟡 | 9.1/9.2 ✅ · 9.3 missing the scanner card |
| §10 Customer Portal | 🟡 | **10.2 shipment detail missing 4 of 5 content zones** · pay-online is a placeholder (backend gap) |
| §14 Documents & Reports | ✅ | Import wizard, reports, audit log, notification log, A4 prints |
| §15 Quota | 🟡 | Banner + blocking modal ✅ · tenant-facing per-dimension usage panel missing |
| §16 Gap Fixes | ✅ (1 🔴) | 12 of 13 done · **16.12 Offboarded (410) screen missing** |

---

## 🔴 Non-compliant (missing screens / structures / workflows)

### A1 — §4.1 Company Settings: not implemented
Prototype: full company-profile form (logo upload, company name, warehouse address, contact info, brand colour) with a **live document preview** showing how branding renders on billing documents.
Implementation: `/admin/config` (`ConfigOverview.tsx`) is only a navigation hub of cards; `configApi.updateConfig` is used exclusively for webhooks. There is no UI anywhere for a tenant admin to set their company name, logo, address, or brand colour — even though `PUT /v1/tenant/config` supports it and `ThemeProvider` already consumes tenant `primary_color`.
**Backend ready: yes. Recommend: implement (highest-value gap in the audit).**

### A2 — §3.6 Customer Profile: tab structure absent
Prototype: hero (avatar, name, Verified badge, shipments badge) + 5-tab strip; Profile, Shipments, and Billing tabs fully designed (notification-pref rows, mini-stats, shipments table, billing table).
Implementation: `AdminCustomerDetail.tsx` (230 lines) is a flat single page — profile Kvps + GDPR export/anonymise. No hero, no tabs, no Shipments tab, no Billing tab.
**Backend ready: yes (shipments via packing-list list filtered by customer; billing via `GET /v1/billing/{customer-id}`). Recommend: implement.**

### A3 — §10.2 Customer Shipment Detail: 4 of 5 content zones missing
Prototype: tracking stepper + **my cartons** + **billing summary with pay CTA** + **documents** + **file-a-claim prompt**.
Implementation: `MyShipmentDetail.tsx` renders the tracking-code hero and journey timeline only.
**Backend ready: mostly (cartons from the customer's packing list; billing summary per customer; claim prompt links to /my-claims/new). Documents need a customer-visible scope decision. Recommend: implement cartons + billing summary + claim prompt; defer documents.**

### A4 — §16.12 Tenant Offboarded (410) full-page state: missing
Prototype: graceful "Account closed" full page when the backend returns 410 `TENANT_OFFBOARDED` on every request.
Implementation: no handling — `api/client.ts` treats 410 as a generic error, so users of an offboarded tenant see raw error banners on every page.
**Backend ready: yes (`TenantOffboardedError`, 410 + `error_code: TENANT_OFFBOARDED`). Recommend: implement (small; also covers the §1.1 "tenant suspended" 403 sibling case).**

### A5 — §6.4 Update Container Status: notification-confirmation step missing
Prototype: two-step flow — stage picker, then a **confirmation step previewing the SMS/WhatsApp/Email messages and the number of customers about to be notified**.
Implementation: `AdvanceStatusModal` is a single-step confirm (ship date + notes). Status changes silently trigger customer notifications with no preview or count.
**Backend ready: partially (customer count derivable from the container's packing lists; message preview would reuse notification templates). Recommend: implement at least the "N customers will be notified" confirmation; message previews optional.**

---

## 🟡 Partial (page exists; named prototype elements missing)

| # | Screen | Missing vs prototype | Backend ready? |
|---|---|---|---|
| B1 | §2.1 Platform Dashboard | Recent-activity feed; 3 quick-action tiles; tenant-health columns Users `x/limit` + Containers `x/limit`; date-range control; trend chips | Feed: yes (`GET /v1/platform/audit-log`). Usage columns: yes (`…/usage` per tenant — needs batching or list-level aggregates). Trends/date-range: 🚫 no historical aggregates |
| B2 | §2.2 Tenant List | Status filter chips w/ counts, search, sort, selectable rows + bulk bar, tenant-ID column, contact name+email cell, users `x/limit` column, pagination footer, kebab menu | Chips/search/pagination: yes. "Onboarding" status: 🚫 not a backend status |
| B3 | §3.1 Tenant Dashboard | Greeting hero + live summary line; "Recent containers" table (admin view); tenant activity feed; "Recent staff logins" card; QuickActionCards (impl has plain nav buttons); "Active customers" + "Pending claims" stats | Recent containers/stats: yes. Activity feed: 🚫 no tenant-scoped audit endpoint. Staff logins: 🚫 no `last_login` field |
| B4 | §3.2 Staff List | Role filter chips w/ counts; search; "Last login" + "Created" columns; kebab | Chips/search/created: yes. Last login: 🚫 |
| B5 | §3.5 Customer List | **"Add customer" button (functional gap — staff cannot create customers from the UI despite `POST /v1/customers`)**; 4 stat cards; filter chips; consent-channel chips column; shipments / outstanding / last-shipment columns; export; GDPR banner | Add customer + consent + shipment_count: yes. Outstanding per customer: needs billing aggregate. |
| B6 | §3.4 Staff Profile | "Recent activity" table (last 7 days of audit events) | 🚫 no tenant-scoped audit endpoint |
| B7 | §4.2/§4.3 Rate pages | 6-month rate trend line chart; hero delta chips vs prior period (history table already shows per-change deltas) | Yes — rate-history endpoint has the data; chart is frontend-only work |
| B8 | §4.4 Charge Types | Per-charge usage analytics ("used 14× this month") | 🚫 no usage-count endpoint |
| B9 | §15.4A Quota | Tenant-facing "Plan usage" panel with per-dimension bars on the dashboard (only the ≥80% warning banner exists tenant-side; bars exist only in the platform admin's tenant-detail Usage tab) | Yes — `GET /v1/tenants/me/quota` already feeds the banner |
| B10 | §9.3 Warehouse | Big QR-scanner card (camera scan → release note) | Needs camera/QR lib; queue + search cover the workflow today |
| B11 | §6.2 Manifest List | Overdue-row flagging; inline per-row Verify/Resolve actions (impl links to detail) | Overdue: derivable from arrival date. Minor |
| B12 | §10.4 Billing Detail (customer) | Live Paystack pay panel — impl button is disabled "coming soon" | 🚫 no payment-initialisation endpoint (webhook + success/failed pages already exist) |

---

## ⚖️ Intentional divergences (documented; recommend keeping)

1. **§1.2 Register has no password fields** — backend `POST /v1/register` emails a temporary Cognito password; prototype's password+confirm+strength on signup contradicts the real contract.
2. **§1.3/1.4 code-based password reset** — Cognito ForgotPassword sends a numeric code, not a magic link; screens follow reality.
3. **§1.1 "tenant suspended" login error** — login never touches our backend (Cognito is the IdP); tenant suspension surfaces on the first API call after login instead.
4. **§7.3 dispute detail side panel** — disputes are managed inline on BillingDetail (where the money context lives); the side-panel duplicate and the dead `/billing/disputes/:id` route were removed.
5. **§9.2 embedded A4 pane** — the printable document is a dedicated shell-less `/release-notes/:id/print` route (real print CSS) rather than a scaled preview pane.
6. **§8.2 resolve modal ₦ input** — backend contract is NGN; prototype's USD + auto-FX would need new backend fields.
7. **F-D3 manifest-verify photo upload** — ~~deferred pending a manifest-scoped presigned-upload contract~~ **closed 2026-07-13** (migration 036 `manifest_evidence` + `POST /v1/manifests/{id}/evidence`; see AUDIT_GAPS.md).

---

## Questionable prototype designs (the "does this even make sense?" list)

Judgment calls on prototype content of dubious value — with a recommendation each:

1. **GDPR/NDPR UI — keep it.** This is the one to be careful with: Nigeria's NDPR (and GDPR for any EU data subjects) makes right-to-erasure and data-export legal obligations, and the backend fully implements both (`DELETE /v1/customers/{id}`, `GET /v1/customers/{id}/export`, migration 012). The admin anonymise/export flows and the customer Privacy tab are the legal minimum and are already built. What *is* skippable fluff from the prototype: the decorative "3 customers have been anonymised" banner on the customer list, and the GDPR tab's illustrated "bundle contents" preview. Recommend: keep the flows, skip the decoration.
2. **Platform MRR + API-call stats (§2.1)** — the platform doesn't bill tenants through the app and doesn't meter API calls anywhere queryable. Unbuildable without inventing numbers. Skip (impl already substitutes real stats).
3. **Trend chips everywhere ("+18.4% vs last period")** — no historical-aggregates endpoints exist; every trend in the prototype is fictional. Skip until an analytics table exists.
4. **"Recent staff logins" (§3.1)** — `tenant_user` has no `last_login`; Cognito doesn't surface it without extra event tracking. Low operational value. Skip or add a backend field first.
5. **"Onboarding" tenant status (§2.2)** — not a real backend status (active/suspended/offboarded only). Skip.
6. **Date-range pickers on dashboards** — stat endpoints take no range params. Skip.
7. **QR scanner card (§9.3)** — genuinely useful on a warehouse phone, but needs camera integration and QR payload conventions; the queue + record-pickup flow covers operations today. Defer, don't drop.
8. **Tenant activity feeds (§3.1)** — needs a tenant-scoped audit endpoint (audit log is platform-only today). Reasonable future backend task; skip frontend-only.

---

## Suggested implementation order (if proceeding)

1. **A1** Company Settings (§4.1) — whole missing feature, backend ready, admins currently cannot brand their tenant.
2. **B5 (partial)** "Add customer" button + modal (§3.5) — functional gap, trivial.
3. **A4** Offboarded/suspended full-page states (§16.12) — small, high-polish, fail-closed UX.
4. **A2** Customer Profile tabs (§3.6) — backend ready.
5. **A3** Customer Shipment Detail zones (§10.2) — highest customer-visible value.
6. **A5** Notify-confirmation step (§6.4) — prevents accidental mass notifications.
7. **B9** Tenant plan-usage panel (§15.4A) — data already fetched for the banner.
8. **B1/B2/B3/B4** list-page chips/search/columns sweep — mechanical, no backend work.
9. **B7** rate trend charts — frontend-only.
10. Defer: B6, B8, B10, B11 (minor), B12 + trends/feeds (backend work first).
