# Audit Gaps — Prototype vs Implementation

Working checklist distilled from the full audit ([FRONTEND_DESIGN_AUDIT_2026-07-11.md](FRONTEND_DESIGN_AUDIT_2026-07-11.md) — see it for per-section verdicts, evidence, and the intentional-divergence register). Tick items as they land; move anything descoped to the "Won't do" table with a reason.

**Status legend:** `[ ]` open · `[x]` done · 🚫 = needs a backend endpoint/field that doesn't exist yet.

> **Decision (2026-07-11):** backend work is **in scope** for closing these gaps — where a frontend item is 🚫-marked, build the missing endpoint/field as part of the item rather than deferring it. 🚫 now means "includes backend work," not "won't do." The Won't-do table below is unaffected (those are conceptually dishonest without invented data, e.g. fictional trends), except where noted.

---

## 🔴 Missing screens / structures / workflows

- [x] **A1 — §4.1 Company Settings page** (`/admin/config` company-profile form) — **done 2026-07-11**
  `CompanySettings.tsx` replaces the ConfigOverview nav hub (hub navigation preserved in the prototype's `ConfigSubNav` rail): Company identity / Warehouse & contact / Document footer cards + live PL/RN document preview driven by form state. Consumers wired the same pass: `PrintPackingList`/`PrintReleaseNote` render the tenant's name, tagline, brand colour, pickup address, and footer (`PrintBrand.tsx`; ShipX lockup remains the no-branding fallback), and `StaffLayout` now mounts `ThemeProvider` with `branding_config.primary_color` (platform admins keep the canonical palette; impersonation correctly shows the tenant's brand). Backend: `GET /v1/tenant/config` widened to all staff roles (dollar-rate precedent; secret stays masked, writes stay admin-only). *Divergences:* logo = initials tile + brand colour (no tenant-scoped upload endpoint yet — the only presigned route is claim-scoped); customer-portal theming deferred (config response includes the webhook endpoint URL, so customers need a separate branding-only read).
  *Follow-up (same day):* all six `/admin/config/*` screens now render inside a shared `ConfigLayout` — the prototype's persistent sub-nav rail with routed content — so switching config sections swaps only the content area (feels like one settings page) while keeping per-section URLs, deep links, and back/forward. `WebhookConfig`'s own internal ConfigNav (from the Task 08 gap-fix pass) was removed — it double-railed next to ConfigLayout's; regression-guarded by `ConfigLayout.test.tsx` ("exactly one navigation rail").
- [x] **A2 — §3.6 Customer Profile tab structure** (`AdminCustomerDetail.tsx`) — **done 2026-07-11**
  Hero (avatar, Active/Anonymised badge, phone · email · customer-since) + 5 tabs: Profile (contact card, NDPR/GDPR consent card, lifetime stat cards), Shipments (`GET /v1/packing-lists?customer_id=`), Billing (`GET /v1/billing/{customer-id}` + stats), Claims (`GET /v1/claims?customer_id=` — **backend filter added this pass**; safe for the customer role, which the service pins to its own record regardless), Data & privacy (GDPR export + ANONYMISE erasure folded out of the header). Prototype's "Recent activity" table deliberately skipped (no tenant-scoped audit endpoint — B3/B6 pattern). Tests: `AdminCustomerDetail.test.tsx` + `TestListClaimsCustomerFilter` (incl. customer-cannot-widen-scope).
- [x] **A3 — §10.2 Customer Shipment Detail content zones** (`MyShipmentDetail.tsx`) — **done 2026-07-12**
  Rebuilt to the prototype's zones: hero (reference, container-status badge, container meta), tracking card (CustomerStepper + per-status "where is it now" hint), my-cartons table (tag/description/weight/CBM from the PL items), billing summary card (shipping/misc/total/paid/outstanding + **Pay outstanding** CTA → `/my-billing/{id}`; honest empty-state when no bill exists yet), and the file-a-claim prompt → `/my-claims/new`. Documents zone stays deferred. **Two ground-truth bugs found & fixed:** (1) `publicTrackingApi.lookup` called `/v1/track/{code}` — a route that exists nowhere (API GW + local_server only serve `GET /v1/shipments/{code}?phone=`), so the public tracking page AND this detail page 404'd on every single lookup; path corrected. (2) `MyShipments` navigated with `pl.reference` while the detail needed an id — now navigates with `pl.id` and the detail loads `GET /v1/packing-lists/{id}` (customer-own enforced server-side). Also: `CustShell` gained the `sxapp` container-query context (the customer shell had none, so no customer page could use container queries). Tests: `MyShipmentDetail.test.tsx` (6).
- [x] **A4 — §16.12 Tenant Offboarded (410) full-page state** — **done 2026-07-11**
  `auth/tenantGate.ts` (module store, useSyncExternalStore) is tripped by `api/client.ts` whenever any response carries `TENANT_OFFBOARDED` or `TENANT_SUSPENDED`; `TenantBlockedGate` in both StaffLayout and CustomerLayout then swaps ALL routed content for `TenantBlockedScreen` (prototype 16.12 forest-dark page: closed/suspended copy variants, Contact-support mailto, Sign out, HTTP-code footnote). The gate clears on every session transition (`App.tsx` onSessionChange) so a fresh login to a healthy tenant starts clean. Covered by `TenantBlockedScreen.test.tsx` + gate-wiring tests in `client.test.ts`.
- [x] **A5 — §6.4 Update-status notification confirmation** (`AdvanceStatusModal`) — **done 2026-07-12**
  Two-step flow: details form (ship date/notes) → confirmation step summarising the transition and its customer-facing side effects, mirroring `services/tracking/service.py` exactly: `at_warehouse` → "N customers will be notified their cargo has arrived (SMS · WhatsApp · Email)"; `cleared` → "billing will be generated for N customers + payment-due notifications"; every other stage → explicit "no customer notifications are sent at this stage". Count = distinct customers across the container's packing lists (already loaded). Confirm button reads "Confirm & notify" on notifying stages. Message previews deliberately skipped (would need template-rendering client-side; the honest count + channels covers the accidental-mass-notify risk). Tests in `ContainerDetail.test.tsx`.

## 🟡 Partial — functional gaps

- [x] **B5a — §3.5 "Add customer" button + modal** (`AdminCustomerList.tsx`) — **done 2026-07-11**
  `AddCustomerModal` (name required; phone/email/WhatsApp optional; NDPR/GDPR notification-consent checkboxes, SMS pre-ticked) → `POST /v1/customers`, then invalidates the customer-list cache and navigates straight to the new profile (mirrors the InviteModal → StaffUserDetail flow). Covered by `AdminCustomerList.test.tsx`.
- [x] **B9 — §15.4A tenant-facing plan-usage panel** — **done 2026-07-12**
  `shell/PlanUsagePanel.tsx` on the tenant-admin dashboard: per-dimension bars (Active users / Containers per month / Storage GB) with the prototype's threshold treatment — green <80%, amber badge ≥80%, red "At limit" — fed by the same `useQuota()` the ≥80% warning banner uses. Unlimited counters (API calls, SMS/WhatsApp/email) render as a meta line, not fabricated-percentage bars. Tests: `PlanUsagePanel.test.tsx`.
- [x] **B12 — §10.4 customer pay-online (Paystack)** — **done 2026-07-12, verified live end-to-end**
  New `POST /v1/payments/{billing-id}/initialize` (customer-own; guards: ownership via `customer.user_id`, outstanding > 0, not cancelled/waived, email required, http(s) callback only) → `services/payment_release/paystack.py` creates a hosted-checkout session; `MyBillingDetail`'s Pay button redirects to `authorization_url`. The payment itself is recorded ONLY by the existing HMAC-SHA512-verified webhook. Secret via `PAYSTACK_SECRET_KEY` env (Terraform injects it into the payment_release Lambda **only**; webhook verification falls back to it). **Bugs found:** (1) `POST /v1/webhooks/payment` and `/v1/webhooks/whatsapp` were registered in neither API Gateway nor local_server — the entire webhook receiver was unreachable; both routed now. (2) references were the bare billing UUID, but Paystack rejects duplicate references (retry-impossible) and only allows alphanumerics + `-.=` — now `{billing_id}.{nonce}`, webhook parses both formats. (3) local_server now lowercases event headers like API Gateway v2 (the webhook signature header was being missed locally). Verified against the live Paystack test API: initialize → checkout URL → simulated signed `charge.success` → billing flipped to `paid`.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    
## 🟡 Partial — list/dashboard enrichment sweep

The systematic pattern: list pages are thinner than the prototype (no chips/search/stat rows/rich columns).

- [x] **B1 — §2.1 Platform Dashboard** — **done 2026-07-13**: recent-activity feed from `GET /v1/platform/audit-log` (action badges + tenant name + relative time), 3 quick-action tiles (onboard / audit log / settings), tenant-health table now shows **users x/limit** (from B2's list enrichment). Omitted honestly: containers-x/limit per tenant (no batch usage endpoint — would be N calls), and trends/MRR/API-calls (no historical source).
- [x] **B2 — §2.2 Tenant List** — **done 2026-07-13**: status filter chips w/ counts, client-side search (name/email/slug/id), initials-avatar tenant cell + slug, mono ID column, tier colour, **users x/limit** (backend `list_tenants` now returns `user_count` via active-user LATERAL count + effective `users_limit` per tenant), "showing X of Y" footer. Omitted: "Onboarding" status (not a backend status), bulk actions (no bulk endpoints).
- [x] **B3 — §3.1 Tenant Dashboard** — **done 2026-07-13**: time-of-day greeting hero + container-summary line (in transit / awaiting customs / ready), admin-only **Active customers** (from customers list `total_count`) + **Open claims** (filed + under_inspection) stat cards, and a **Recent containers** table for admins (the Nigeria kanban + PlanUsagePanel were already present). Recent-activity feed added 2026-07-13 via B6's new `GET /v1/tenant/activity`. **Layout completed 2026-07-16:** main area now matches the §3.1 two-column skeleton (Recent containers + Activity side-by-side); bottom row = PlanUsagePanel (filling the staff-logins slot — still no `last_login` field, stays in Won't-do) + real **QuickActionCards** (shared `design/components/QuickActionCard`, also adopted by the platform dashboard): Add customer / Invite staff / Update dollar rate — each deep-links and auto-opens the target modal via router state. The prototype's "Create container" action was deliberately swapped out (POST /v1/containers is china_office_staff-only — dishonest as an admin CTA); the old generic nav-card stacks (never in the prototype) were removed. Nigeria §6.1 bottom also completed: Recent payments + **Incoming containers** (at-sea containers, soonest-ETA-first with Today/N days/N wks chips) in the prototype's two-column grid.
- [x] **B4 — §3.2 Staff List** — **done 2026-07-13**: role filter chips w/ counts, name/email search, "Created" column (customer-role rows always excluded). Omitted: "Last login" (no `last_login` field).
- [x] **B5b — §3.5 Customer List enrichment** — **done 2026-07-13**: stat cards (customers / shipments / WhatsApp-consent — "on this page" framing when paginated), filter chips (All/Active/Anonymised), consent-channel pills (SMS/WA/EM) column, shipments column (`shipment_count`, already on the list endpoint), name+email cell. Omitted: outstanding-₦ (needs a per-customer billing aggregate); last-shipment (no field on the list).
- [x] **B7 — §4.2/4.3 rate trend charts** — **done 2026-07-13**: dependency-free SVG line chart (`RateTrendChart` in DollarRateConfig.tsx) folded into the shared `RateHistoryTable`, so both the Dollar and CBM rate pages get it from the history already fetched (no extra request). Filled area + line + endpoint dot, min/max reference lines, first/last date labels, and a net-change summary. Hidden when < 2 data points (no trend to draw). Tests in `RateHistoryTable.test.tsx`.
- [x] **B11 — §6.2 Manifest List** — **done 2026-07-13**: manifests still `pending` while their container has reached Nigeria (`arrived`/`customs_clearance`/`cleared`/`at_warehouse`) are flagged overdue — error-tint row + "Overdue" badge + a summary warning banner ("N manifests overdue for verification — verify to unblock billing and release"). Derived from real fields (no SLA endpoint). Tests in `ManifestList.test.tsx`.

## Deferred (agreed low priority — revisit deliberately)

- [ ] **B10 — §9.3 warehouse QR-scanner card** — needs camera/QR integration + payload convention; queue + search cover operations today.
- [x] **B6 — §3.1 dashboard feed + §3.4 staff activity table** — **done 2026-07-13 (backend built)**: new `GET /v1/tenant/activity` (tenant_admin only) reads the per-tenant `audit_log` (already populated by every service's `log_audit`) with the actor's display name joined, cursor-paginated; `?actor_id=` narrows to one staff member. Frontend: shared `shell/ActivityFeed.tsx` mounted on the tenant dashboard (Recent activity, admin) **and** the staff-profile page (that user's own activity, `actor_id`-scoped). Verified live against seeded audit data (feed, actor filter, cursor pagination, customer-role 403). Tests: `TestTenantActivityFeed` (backend guard matrix) + `ActivityFeed.test.tsx`.
- [x] **B8 — §4.4 charge-type usage analytics** — **done 2026-07-13 (backend built)**: added a nullable `charge_type_id` FK on `misc_charge` (migration 035, `ON DELETE SET NULL`) so a misc charge added from a configured charge type is attributed back to it. `GET /v1/tenant/charge-types` now returns a `usage_count` per type (correlated `COUNT` over `misc_charge`), surfaced as a "Times used" column on the charge-types settings page. The AddChargeModal sends `charge_type_id` when a configured type is chosen; free-form "other" charges stay unattributed (NULL, uncounted). Counts are accurate going forward — pre-migration rows have NULL `charge_type_id`. **Ground-truth bug found & fixed:** the charge-types wire contract was broken — the frontend sent/read `amount_ngn` while the repo wrote/read the `default_amount_ngn` column with no mapping, so charge-type amounts were silently dropped on write and returned as `undefined` on read (feature had zero tests). The service now maps `amount_ngn` ↔ `default_amount_ngn` at the boundary via `_serialize_charge_type`. Tests: `TestChargeTypes` (mapping + usage_count), `TestAddMiscCharge` (FK passthrough), `ChargeTypes.test.tsx`. Omitted: per-type revenue totals (out of scope — usage count is the §4.4 signal).
- [x] **F-D3 — §6.3 manifest-verify photo upload** — **done 2026-07-13 (backend built)**: new `manifest_evidence` table (migration 036, mirrors `claim_evidence` — no RLS, scoped via manifest_id FK + `{tenant_id}/manifests/...` S3 key prefix) and a manifest-scoped presigned-upload contract `POST /v1/manifests/{id}/evidence` (china/nigeria staff). `GET /v1/manifests/{id}` now returns an `evidence[]` list with short-lived presigned GET `download_url`s. Frontend: the claims `EvidenceUploader` was generalised to take a `getPresignedUrl` callback (claims call sites updated), then mounted **per-discrepancy** in `VerifyManifestModal` (each upload is labelled with the customer + type + carton tags) and as a **Verification evidence** gallery on `ManifestDetail`. Uploads go straight to S3 via the presigned POST; the evidence row is recorded server-side. Tests: `TestEvidenceUpload` (backend — key prefix, content-type guard, not-found, evidence serialisation), `manifest.test.ts` (+1), `ManifestDetail.test.tsx` (+2). **Infra bug found & fixed:** `PATCH /v1/manifests/{id}/resolve-discrepancy` was handled in code and used by the frontend but **missing from the Terraform route map** — it would 404 in production (worked locally only via `local_server.py`'s prefix dispatch); added alongside the new evidence route.

---

## Audit pass 2 — 2026-07-15 (full re-audit after pass-1 closures)

Method: every prototype screen (`Shipx_frontend_design/screens/**/*.jsx`, 13 sections incl. gap-fix sets a/b/c) mapped against the implemented pages, then feature-level comparison on the sections most likely to have drifted. **Screen-level coverage is complete** — every prototype screen has an implemented counterpart (incl. all six gapfix-b items, quota screens, reports screens, and the impersonation set). The findings below are feature-level.

### ✅ P2-1 — `customer.locale` is read by notifications but writable by no one (ground-truth bug) — **fixed 2026-07-16**

`services/tracking/service.py:348` passes `customer.get("locale", "en")` into the notification flow to select the EN vs ZH template set — so the column (migration 029) is **live in production behaviour**. But there is no write path: `locale` is missing from `_CUSTOMER_UPDATE_FIELDS` (staff PATCH) *and* from the customer self-service allowlist (`{phone, whatsapp, delivery_address, notification_consent}` in `tenant_management/handler.py:743`), and no UI exposes it (neither customer `Account` nor `AdminCustomerDetail`). Every customer is therefore permanently stuck on `en`. Staff locale (gapfix A6) is fine — `tenant_user.locale` is in `_USER_UPDATE_FIELDS` with UI on the staff profile.
**Fixed 2026-07-16:** `locale` added to `_CUSTOMER_UPDATE_FIELDS` and the customer self-service allowlist; `update_customer` validates against `_SUPPORTED_LOCALES` (422 `UNSUPPORTED_LOCALE`). UI: EN/中文 radio picker on the customer Account Notifications tab (saved with consent) + an inline select on `AdminCustomerDetail`'s Consent & GDPR card (saves on change; disabled for anonymised customers). Tests: `TestUpdateCustomerLocale` (4), `Account.test.tsx` (2).

### ✅ P2-2 — §9.3 WarehouseDashboard is far leaner than the prototype WarehouseView — **done 2026-07-16**

Implemented: card queue of active notes + record-pickup modal + partial handling. Missing, all honest-data:
- **Reference lookup block** — the prototype's centrepiece: "Scan or type a release note reference". A plain text input satisfies this *and* covers handheld barcode scanners with zero new dependencies (they type the decoded reference as keyboard input). This is the non-camera half of B10 and is buildable now.
- **"Done today" stat is fabricated** — it's session-local (`doneCount` is literally 0 or 1, resets on reload). Fix: count real `picked_up` notes today (list endpoint filter or a small count query) or remove the card.
- **No urgency treatment** — prototype sorts by age with urgent (>24h) / normal / new chips + age labels; impl has no age signal at all. Derivable from `created_at`.
- **No expired-not-collected stat/banner** (status `expired` exists on the wire).
- No greeting hero (cosmetic — optional).

### ✅ P2-3 — §9.1 ReleaseNoteList missing the stats row — **done 2026-07-16**

Prototype has 4 stat cards (Active · Picked up today · Partial · Expired). **Done:** new `GET /v1/release-notes/stats` (single `FILTER`ed aggregate — no page-tallying) feeds 4 real stat cards; row hidden if the endpoint fails. Tests in `ReleaseNoteList.test.tsx`.

### ✅ P2-4 — §6.2 ManifestList missing the verification-status stats row — **done 2026-07-16**

Prototype has 4 stat cards (Awaiting verification · Verified · With discrepancies · Resolved). **Done:** new `GET /v1/manifests/stats` (per-status counts + B11 `overdue` via container join) feeds the stats row; the B11 predicate moved to `manifestRules.isManifestOverdue` (shared with the dashboard queue). Tests in `ManifestList.test.tsx`.

### ✅ P2-5 — §6.1 Nigeria dashboard missing two action queues + recent payments — **done 2026-07-16**

Implemented: pipeline kanban, PL-approval queue, stat cards, greeting. **Done:** "Containers awaiting manifest verification" queue (B11 predicate — pending manifests whose container arrived), "CBM disputes need response" queue (submitted disputes, 24h SLA note), "Recent payments" table (new `GET /v1/billing/payments` — payment_record ⋈ billing ⋈ customer, staff-only), and a "Ready for pickup" stat (active release-note count). Queues render only when non-empty. Tests in `Dashboard.test.tsx`.

### ✅ P2-6 — responsive detail grids (carried from FRONTEND_COMPLIANCE_REVIEW F-F3, its one unfinished item) — **done 2026-07-16**

The prototype's responsive pass (F-F1–F-F8) landed 2026-07-09 except F-F3's second half: fixed multi-column detail grids need per-page `@container sxapp` collapse rules ≤860px. Current state (re-verified this pass): stat rows are fine (`auto-fit/minmax`), 6 page modules already have container rules, but 4 still had fixed `fr` grids with none — **all four now collapse to one column ≤860px via `@container sxapp` rules** (`tenant-admin/TenantReports`, `china/CreatePackingList` incl. `.previewMeta`, `china/CreateContainer`, `china/ContainerDetail` incl. `.summaryGrid`). (`print/` is deliberately fixed A4; `marketing/` is standalone.)

### Leave as-is (100% compliance not sensible — additions to the Won't-do register below)

- **MobileLoginScreen** (§1) — a separate mobile screen is the prototype's artefact; the real login is responsive. No action.
- **Warehouse greeting weather** ("32°C", §9.3) — no weather source; fictional-data class.
- **"QR code scanned / verified" panel** on ReleaseNoteDetail (§9.2) — pairs with B10's scan events; meaningless until B10 lands. Revisit with B10.
- **Camera-based QR scanning + QR image on the printed note** — stays B10 (deferred). Note B10's scope shrinks once P2-2's text lookup ships: remaining work is only rendering a QR on `PrintReleaseNote` (needs a QR lib or SVG generator) and optional phone-camera scanning.

**Suggested order:** P2-1 (bug) → P2-2 (warehouse) → P2-5 → P2-3/P2-4 (stats rows, one small sweep) → P2-6 (responsive grids).

> **Doc note (2026-07-15):** `FRONTEND_COMPLIANCE_REVIEW.md` deleted — every tracked item closed; its one unfinished thread (F-F3) is carried here as P2-6. Historical detail lives in git history. `FRONTEND_DESIGN_AUDIT_2026-07-11.md` is kept as the pass-1 evidence doc.

---

## Won't do (prototype content with no honest data source or descoped by decision)

| Prototype element | Where | Reason |
|---|---|---|
| Platform MRR + API-call stats | §2.1 | Platform doesn't bill tenants in-app and doesn't meter API calls — numbers would be invented |
| Trend chips ("+18.4% vs last period") | all dashboards | No historical-aggregates endpoints; every trend in the prototype is fictional |
| "Recent staff logins" card | §3.1 | No `last_login` field; Cognito doesn't surface it without extra tracking |
| "Onboarding" tenant status | §2.2 | Backend statuses are active/suspended/offboarded only |
| Date-range pickers on dashboards | §2.1/§3.1 | Stat endpoints take no range params |
| "3 customers anonymised" GDPR banner | §3.5 | Decorative noise; the GDPR *flows* (anonymise/export/privacy tab) stay — they're NDPR/GDPR legal obligations already implemented end-to-end |
| GDPR export "bundle contents" illustration | §3.6 | Cosmetic |
| Separate mobile login screen | §1 | Real login is responsive; no separate screen needed (pass 2) |
| Warehouse greeting weather ("32°C") | §9.3 | No weather data source; fictional (pass 2) |
| "QR code scanned/verified" panel | §9.2 | Depends on B10 scan events; revisit with B10 (pass 2) |

## Intentional divergences (register — do not "fix" these)

Kept deliberately; full rationale in the audit doc: register-without-password-fields (backend emails temp password) · code-based password reset (Cognito reality) · tenant-suspended error surfaces post-login (login never touches backend) · dispute detail inline on BillingDetail instead of a side panel (for Nigeria staff and admins; China staff, who cannot open invoices, have `/billing/disputes/:id`, 2026-11-16) · printable A4 as a dedicated print route · resolve-modal ₦ input (backend contract is NGN).

---

**Suggested order:** A1 → B5a → A4 → A2 → A3 → A5 → B9 → B1–B4/B5b sweep → B7 → deferred/blocked as backend allows.
