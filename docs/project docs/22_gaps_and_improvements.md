# 22 — Gaps & Improvements Backlog

Identified from end-to-end review of the codebase (2026-05-04).
Work through these iteratively — check off each item when implemented and update the relevant doc per the Doc-First Rule in `CLAUDE.md`.

---

## Priority 1 — Critical (Financial / Data Integrity)

- [x] **Idempotency on payment confirmation** (`POST /v1/payments/{billing-id}/confirm`)
  - Duplicate calls would double-count `amount_paid_ngn` — a financial integrity issue.
  - Add idempotency key check (same pattern as packing list and tracking handlers).
  - _Touches_: `services/payment_release/handler.py`, `13_api_payment_release.md`

- [x] **Billing void / cancel endpoint** (`PATCH /v1/billing/{id}/cancel`)
  - No way to void an incorrect auto-generated invoice. Only workaround is a negative misc charge.
  - Must guard: cannot cancel a billing with confirmed payments or an active release note.
  - _Touches_: `services/billing/handler.py`, `services/billing/service.py`, `services/billing/repository.py`, `11_api_billing.md`

- [x] **Payment gateway webhook** (Flutterwave / Paystack)
  - All payments are manually confirmed by staff. No automated confirmation on customer transfer.
  - Add `POST /v1/webhooks/payment` Lambda route; verify HMAC signature; auto-call `confirm_payment`.
  - _Touches_: `services/payment_release/`, new webhook handler, `13_api_payment_release.md`, `04c_terraform_api_gateway.md`

---

## Priority 2 — Operational Correctness

- [x] **Container status audit trail table**
  - `tracking_event` exists for carton-level changes; nothing equivalent for containers.
  - Cannot answer "when did ACME-001 clear customs, and who actioned it?"
  - Add `container_event` table (append-only): `container_id`, `from_status`, `to_status`, `actor_id`, `notes`, `created_at`.
  - _Touches_: new migration (019), `services/tracking/repository.py`, `services/tracking/service.py`, `05a_database_schema_core.md`, `10_api_tracking.md`

- [x] **Missing item → refund / billing adjustment link**
  - `missing_item` had no money movement record for a lost item (it was written as a `compensated` status, which the schema never allowed; compensation now triggers on `confirmed_lost`, 2026-11-14).
  - Add optional `refund_request_id` FK on `missing_item`; allow staff to create a refund directly from a missing item resolution.
  - _Touches_: migration (020), `services/claims/`, `services/refunds/`, `12_api_claims.md`, `14_api_refunds.md`

- [x] **Seized item → compensation link**
  - Same gap as missing items: `forfeited` / `recovered` statuses don't connect to customer compensation.
  - _Touches_: migration (020), `services/claims/`

- [x] **Carryover ledger apply endpoint**
  - `carryover_ledger` table exists (migration 003) but no API to apply a carryover to a new billing record.
  - Add `PATCH /v1/billing/{billing-id}/apply-carryover` or auto-apply logic in billing generation.
  - _Touches_: `services/billing/`, `11_api_billing.md`

---

## Priority 3 — Missing Endpoints / Workflow Gaps

- [x] **`GET /v1/release-notes` (list all)**
  - Only `GET /v1/release-notes/{id}` exists. Staff cannot list active release notes for a container or customer.
  - Add paginated list with filters: `customer_id`, `container_id`, `status`, `cursor`, `limit`.
  - Roles: `tenant_admin`, `nigeria_office_staff`, `warehouse_attendant`.
  - _Touches_: `services/payment_release/handler.py`, `services/payment_release/repository.py`, `13_api_payment_release.md`, `ShipX_API.postman_collection.json`

- [x] **Partial release note generation (split workflow)**
  - Schema supports `is_partial` + `parent_release_note_id` but the API has no way to create a child release note for remaining cartons after a partial pickup.
  - Add `POST /v1/release-notes/{id}/split` → creates a new release note for un-collected carton tags.
  - _Touches_: `services/payment_release/`, `13_api_payment_release.md`

- [x] **Manifest discrepancy resolution workflow**
  - `verification_status = discrepancies_found` is a dead end — no follow-up endpoint.
  - Add `PATCH /v1/manifests/{id}/resolve-discrepancy` with `{ "resolution_notes": "...", "final_counts": {...} }`.
  - _Touches_: `services/manifest/`, `09_api_manifest.md`

- [x] **`GET /v1/containers/{id}/packing-lists`**
  - Currently requires listing packing lists with a `container_id` query param on the packing list endpoint.
  - Add as a sub-resource for ergonomic REST access.
  - _Touches_: `services/packing_list/handler.py`, `08_api_packing_list.md`

- [x] **Container-level document uploads**
  - Claims have S3 presigned URL uploads; containers/manifests do not.
  - Add `POST /v1/containers/{id}/documents/presigned-url` for Bill of Lading, customs certificates, etc.
  - Add `container_document` table (migration 022, RLS-enabled).
  - _Touches_: migration, `services/tracking/`, `10_api_tracking.md`

- [x] **Bulk packing list approve / reject**
  - Staff must approve 50 packing lists individually for a large container.
  - Add `POST /v1/packing-lists/bulk-approve` and `POST /v1/packing-lists/bulk-reject` with `{ "ids": [...] }`.
  - _Touches_: `services/packing_list/`, `08_api_packing_list.md`

---

## Priority 4 — Notifications & Customer Experience

- [x] **Container arrival notification (separate from billing)**
  - When container reaches `at_warehouse`, customers currently only learn via their invoice.
  - Publish a distinct `ContainerArrived` notification before billing is generated.
  - _Touches_: `services/tracking/service.py`, `services/notification/`, `15_api_notifications.md`

- [x] **Notification template management API**
  - SMS/email/WhatsApp templates are hardcoded in `services/notification/service.py`.
  - Add `GET /v1/tenant/notification-templates` and `PUT /v1/tenant/notification-templates/{event_type}/{channel}` for tenant-customisable copy.
  - _Touches_: migration 024, `services/tenant_management/`, `15_api_notifications.md`

- [x] **Customer self-registration flow**
  - Customers can only be created by staff. No self-service registration.
  - `POST /v1/register` (public, no JWT) — tenant resolved from `Host` header (slug subdomain or custom_domain). Creates a Cognito user (sends welcome email with temp password) and a `customer` row linked to that tenant.
  - Subdomain routing: `{slug}.shipx.com`; custom_domain (enterprise): `track.acmelogistics.com`. Migration 023 adds `slug` + `custom_domain` to `tenant`.
  - _Touches_: `services/tenant_management/`, `07_api_tenant_management.md`

---

## Priority 5 — Operational / Infrastructure

- [x] **Outbound webhook to tenant systems**
  - Tenants with internal ERPs or WMS have no integration point.
  - Add `webhook_config` to `tenant_config` (URL + HMAC secret); fire-and-forget HTTP POST on key domain events.
  - _Touches_: new `shared/webhook.py`, `services/tenant_management/`, EventBridge rules, `07_api_tenant_management.md`

- [x] **API rate limiting per tenant** — **corrected 2026-11-15:** ticked in error. An HTTP API has no usage plans, so nothing was configured; done now in `shared/rate_limit.py` (ADR-007).
  - Usage is metered but not enforced. A runaway or compromised tenant can overwhelm the DB.
  - ~~Configure API Gateway usage plan + throttling per tenant;~~ raise `RateLimitExceededError` (429, `Retry-After`) when exceeded.
  - _Touches_: `infrastructure/aws/modules/api-gateway/`, `04c_terraform_api_gateway.md`

- [x] **Rate history (dollar rate + CBM rate changes)**
  - `tenant_config` stores only the current rate. Historical billing rows capture the rate used at invoice time, but there's no dedicated audit table of rate changes.
  - Add `rate_history` table or an append-only `tenant_config_history` table.
  - _Touches_: migration, `services/tenant_management/`, `07_api_tenant_management.md`

- [x] **Health check on all Lambdas**
  - Only the tracking Lambda exposes `GET /v1/health`. All other Lambdas have no health check route.
  - Add a `/health` route (no auth) to each handler for load balancer / uptime monitoring.
  - _Touches_: all `services/*/handler.py`

- [x] **Cognito password reset / invite-resend endpoint**
  - Staff must go to the Cognito console to resend invites or trigger password reset.
  - Add `POST /v1/tenant/users/{id}/resend-invite` and `POST /v1/tenant/users/{id}/reset-password`.
  - _Touches_: `services/tenant_management/`, `07_api_tenant_management.md`

---

## Priority 6 — Data Model Improvements

- [x] **Packing list item version snapshot on rejection**
  - When a packing list is rejected and re-submitted, no history of what changed is kept.
  - Add `packing_list_revision` table or store snapshots in `audit_log` before item edits.
  - _Touches_: migration, `services/packing_list/service.py`, `08_api_packing_list.md`

- [x] **Weight reconciliation workflow**
  - `packing_list_item` has both `weight_dispatch_kg` and `weight_actual_kg` fields but no workflow uses the discrepancy.
  - Add weight reconciliation step to manifest verification: flag items where actual vs dispatch weight diverges > threshold.
  - _Touches_: `services/manifest/service.py`, `09_api_manifest.md`

- [x] **Customer delivery address**
  - Only `tenant_config.warehouse_address` exists. No per-customer delivery address for last-mile tracking.
  - Add `delivery_address` JSONB column to `customer`.
  - _Touches_: migration, `services/tenant_management/`, `05a_database_schema_core.md`

- [x] **Declared value / insurance field on packing list items**
  - No declared value per item for insurance or customs valuation purposes.
  - Add `declared_value_usd DECIMAL(15,2)` to `packing_list_item`.
  - _Touches_: migration, `services/packing_list/`, `05a_database_schema_core.md`

- [x] **Multi-language notification support (EN + ZH)**
  - Notification templates are English-only. China Office Staff notifications should support Simplified Chinese.
  - Add `locale` field to `tenant_user`; pass locale to notification template renderer.
  - _Touches_: `services/notification/service.py`, migration, `15_api_notifications.md`

---

## Priority 7 — Identified Post-Implementation

- [x] **Session invalidation on role change**
  - `update_user` updates Cognito attributes (name, custom:role) but never calls `admin_user_global_sign_out`. A demoted or deactivated user's existing JWT retains the old role claim for its full TTL (~1 hour). A downgraded `tenant_admin` can still act at admin privilege level until token expiry.
  - Call `cognito.global_sign_out(email)` inside `update_user` whenever `role` is in the updates dict.
  - _Touches_: `services/tenant_management/service.py`, `07_api_tenant_management.md`

- [x] **CBM rate history not tracked**
  - P5 claimed "dollar rate + CBM rate changes" but only `update_dollar_rate` was wired to `append_rate_history`. `cbm_rate_per_unit` is a `tenant_config` key with no dedicated update endpoint and no history tracking — half the stated scope was not implemented.
  - Add `PUT /v1/tenant/cbm-rate` endpoint mirroring `dollar-rate`; wire `append_rate_history` for `cbm_rate` changes.
  - _Touches_: `services/tenant_management/service.py`, `services/tenant_management/handler.py`, `services/tenant_management/repository.py`, `07_api_tenant_management.md`

- [x] **`GET /v1/containers/{id}/documents`** — list uploaded documents
  - `list_container_documents` exists in `services/tracking/repository.py` but the handler only exposes the presigned-URL POST. Documents can be uploaded but never listed via the API.
  - Wire `GET /v1/containers/{id}/documents` in the tracking handler calling the existing repo function.
  - _Touches_: `services/tracking/handler.py`, `10_api_tracking.md`, `ShipX_API.postman_collection.json`

- [x] **Refund approval threshold not enforced**
  - `refund_threshold_usd.staff_limit` is in `DEFAULT_CONFIGS` and documented, but `approve_refund` in `services/refunds/service.py` never reads it. A staff member (`nigeria_office_staff`) can approve an arbitrarily large refund with no escalation check.
  - Read `refund_threshold_usd` from `tenant_config` in `approve_refund`; raise `BusinessRuleViolationError` (or a 403) if `amount_approved_ngn` converted to USD exceeds `staff_limit` and the actor is not `tenant_admin`.
  - _Touches_: `services/refunds/service.py`, `14_api_refunds.md`

---

## Completed

- **Idempotency on payment confirmation** — 2026-05-03. Added `Idempotency-Key` header check to `POST /v1/payments/{billing-id}/confirm` in `services/payment_release/handler.py` (same pattern as packing list / tracking). Prevents double-counting `amount_paid_ngn` on retries.
- **Billing void / cancel endpoint** — 2026-05-03. `PATCH /v1/billing/{id}/cancel` added with guards: `unpaid` status only, no confirmed payments, no active release notes. Migration 017 adds `cancelled` status + `cancel_reason/cancelled_by/cancelled_at` columns.
- **Payment gateway webhook** — 2026-05-03. `POST /v1/webhooks/payment` added to payment_release handler. Supports Paystack (HMAC-SHA512) and Flutterwave (verif-hash). Duplicate-safe via `payment_record.gateway_transaction_id` partial UNIQUE index (migration 018). New `services/payment_release/webhook.py` module.
- **Container status audit trail** — 2026-05-04. `container_event` table (migration 019, append-only, no RLS). Every `PATCH /v1/containers/{id}/status` writes a row. `GET /v1/containers/{id}/events` returns ordered history.
- **Missing item → refund link** — 2026-05-04. `refund_request_id` nullable FK added to `missing_item` (migration 020). ~~Setting status `compensated` with `refund_amount_ngn` auto-creates a `refund_request` and links it.~~ **Corrected 2026-11-14:** `compensated` is not an allowed status, so this never fired; it now triggers on `confirmed_lost` with `refund_amount_ngn`.
- **Seized item → compensation link** — 2026-05-04. Same `refund_request_id` FK on `seized_item` (migration 020). ~~Triggers on `recovered`/`forfeited` status with `refund_amount_ngn`.~~ **Corrected 2026-11-16:** `forfeited` is not a status and recovered goods need no compensation; it triggers on `permanently_lost`.
- **Carryover apply endpoint** — 2026-05-04. `PATCH /v1/billing/{id}/apply-carryover` manually applies an outstanding carryover to a billing record. Guards: billing not cancelled/waived; carryover must be outstanding and same customer.
- **`GET /v1/release-notes`** — 2026-05-05. Paginated list with `customer_id`, `container_id`, `status` filters. Customers see only their own. Roles: `tenant_admin`, `nigeria_office_staff`, `warehouse_attendant`, `customer`.
- **Release note split** — 2026-05-05. `POST /v1/release-notes/{id}/split` creates a child release note for un-collected carton tags. Guards: parent must be active; tags must be in parent and not already picked. Publishes `ReleaseNoteSplit` event.
- **Manifest discrepancy resolution** — 2026-05-05. `PATCH /v1/manifests/{id}/resolve-discrepancy` transitions `discrepancies_found → resolved`. Requires `resolution_notes`. Migration 021 adds `resolved` to verification_status CHECK.
- **`GET /v1/containers/{id}/packing-lists`** — 2026-05-05. Sub-resource alias in packing_list handler. Forwards to existing `list_packing_lists` with `container_id` filter pre-set.
- **Container document uploads** — 2026-05-05. `POST /v1/containers/{id}/documents/presigned-url` generates S3 presigned POST URL. Migration 022 adds `container_document` table (RLS, supports 5 document types).
- **Bulk packing list approve/reject** — 2026-05-05. `POST /v1/packing-lists/bulk-approve` and `POST /v1/packing-lists/bulk-reject`. Per-item validation with partial success reporting (`succeeded`/`failed` lists). Self-approval still blocked per item.
- **Container arrival notification** — 2026-05-05. `container_arrived` event enqueued per customer (SMS/WhatsApp/email) when container transitions to `at_warehouse`. Templates added to `_SMS_TEMPLATES`, `WA_TEMPLATE_MAP`, `EMAIL_SUBJECTS` in notification service.
- **Notification template management API** — 2026-05-05. Migration 024 adds `notification_template` table (RLS). `GET/PUT /v1/tenant/notification-templates/{event_type}/{channel}`. `enqueue_notifications` in `shared/notifications.py` now looks up custom templates and embeds as `template_override` in SQS messages.
- **Customer self-registration** — 2026-05-05. `POST /v1/register` (public, no JWT). Tenant resolved from `Host` header: custom_domain first, then subdomain slug. Migration 023 adds `slug` (NOT NULL UNIQUE, auto-derived from company_name) and `custom_domain` (nullable, enterprise) to `tenant`. Slug auto-generated at tenant creation. Duplicate email guard. Cognito provisions user with role=customer; welcome notification enqueued.
- **Outbound webhook** — 2026-05-06. `shared/webhook.py` HMAC-SHA256 fire-and-forget HTTP POST. Config stored in `tenant_config` key `webhook_config` (url, secret, enabled, events list). Fired from `services/tracking/service.py` on every `container.status_updated` event. `webhook_config` added to `DEFAULT_CONFIGS`. Signature sent as `X-ShipX-Signature-256: sha256=<hex>`.
- ~~**API rate limiting** — 2026-05-06. Implemented at API Gateway level via usage plans and throttling (10 RPS burst, 5 RPS steady per tenant).~~ **Corrected 2026-11-15:** this never existed; an HTTP API has no usage plans and the only limit was one stage-wide throttle shared by every tenant. Real limits shipped with audit Phase 2: per client/username/tracking-code/tenant in `shared/rate_limit.py`, per-route throttles at API Gateway (`04c`, ADR-007). App-level `UsageLimitExceededError` (429) from metering is separate and unchanged.
- **Rate history** — 2026-05-06. Migration 025 adds `rate_history` table (RLS-enabled, append-only). `update_dollar_rate` appends a row on every rate change (best-effort). `GET /v1/tenant/rate-history?rate_type=dollar_rate&limit=50` returns paginated history.
- **Health check on all Lambdas** — 2026-05-06. `GET /v1/health` (no JWT) added to all 7 handlers: billing, claims, manifest, packing_list, payment_release, refunds, tenant_management. Returns `{"status":"healthy","timestamp":"..."}`. Checked before `get_tenant_context`.
- **Cognito resend-invite / reset-password** — 2026-05-06. `POST /v1/tenant/users/{id}/resend-invite` (calls `admin_create_user` with `MessageAction=RESEND`) and `POST /v1/tenant/users/{id}/reset-password` (calls `admin_reset_user_password`). Both tenant_admin only.
- **Packing list rejection snapshot** — 2026-05-06. `reject_packing_list` now snapshots current items in `before_state` of the audit log entry. Item fetch moved before the repo write call so the snapshot is unambiguously pre-rejection state.
- **Weight reconciliation** — 2026-05-06. `manifest/repository.get_items_with_weights_for_manifest` fetches both weight fields per item. `_compute_weight_discrepancies` flags items where `|actual − dispatch|` exceeds 5 % of dispatch weight or 0.1 kg. `weight_discrepancies` list returned in both `GET /v1/manifests/{id}` and `PATCH /v1/manifests/{id}/verify` responses.
- **Customer delivery address** — 2026-05-06. Migration 026 adds `customer.delivery_address JSONB`. Added to `_CUSTOMER_UPDATE_FIELDS` and customer INSERT in `tenant_management/repository.py`.
- **Declared value on packing list items** — 2026-05-06. Migration 026 adds `packing_list_item.declared_value_usd DECIMAL(15,2)`. Added to `PackingListItemInput` and `UpdatePackingListItemInput` models; included in item INSERT.
- **Multi-language notifications (EN + ZH)** — 2026-05-06. Migration 026 adds `tenant_user.locale VARCHAR(10) DEFAULT 'en'`. `enqueue_notifications` accepts `locale` param (passed through SQS body). Notification service: `_SMS_TEMPLATES_ZH`, `_DEFAULT_SMS_TEMPLATE_ZH`, `WA_TEMPLATE_MAP_ZH`, `EMAIL_SUBJECTS_ZH`, `_DEFAULT_EMAIL_SUBJECT_ZH`. `format_sms` selects ZH template when `locale == 'zh'`. WA and email handlers select ZH template names/subjects from locale field.
- **Session invalidation on role change** — 2026-05-06. `update_user` now calls `cognito.global_sign_out(email)` (best-effort) immediately after updating role-related Cognito attributes. Prevents a demoted user's existing JWT from retaining elevated claims for its full TTL.
- **CBM rate endpoint + history** — 2026-05-06. `GET /v1/tenant/cbm-rate` returns current CBM rate config. `PUT /v1/tenant/cbm-rate` (`UpdateCbmRateRequest`) updates `cbm_rate_per_unit` in `tenant_config` and appends a `rate_type="cbm_rate"` row to `rate_history` (same pattern as `dollar-rate`). `models.py`: `UpdateCbmRateRequest` added.
- **`GET /v1/containers/{id}/documents`** — 2026-05-06. Handler now exposes the existing `repo.list_container_documents` via `service.list_container_documents`. Roles: `china_office_staff`, `nigeria_office_staff`, `tenant_admin`. Returns all uploaded documents for the container.
- **Refund approval threshold enforced** — 2026-05-06. `approve_refund` now reads `refund_threshold_usd.staff_limit` and `dollar_rate.rate` from `tenant_config` via `repo.get_refund_threshold_config` (new function in `services/refunds/repository.py`). `nigeria_office_staff` actors approving above `staff_limit × dollar_rate` NGN receive `REFUND_THRESHOLD_EXCEEDED` (`BusinessRuleViolationError`). Falls back silently if config is unavailable.
- **Health check on excel and metering handlers** — 2026-05-06. `GET /v1/health` (no JWT) added to `excel/handler.py` and `metering/handler.py` (`_handle_api`). Both now match the pattern used in all other HTTP handlers.
- **Idempotency on billing, refunds, and excel handlers** — 2026-05-06. `check_idempotency`/`store_idempotency` pattern added to `billing/handler.py`, `refunds/handler.py`, and `excel/handler.py`. All POST routes in these handlers now support the `Idempotency-Key` header consistently with other services.
- **Audit logging in refunds and payment_release services** — 2026-05-06. `log_audit` calls added to all state-changing operations: `create_refund`, `accounts_review`, `approve_refund`, `reject_refund` in refunds; `confirm_payment`, `generate_release_note`, `split_release_note`, `record_pickup` in payment_release. Both services now match the audit coverage of every other service.
- **`POST /v1/billing` role restricted to staff** — 2026-05-06. Generate-billing route previously used `_BILLING_READ_ROLES` (includes CUSTOMER). Changed to `_CHARGE_WRITE_ROLES` (`TENANT_ADMIN`, `NIGERIA_OFFICE_STAFF` only). Customers can no longer manually trigger billing generation.
- **Dead `get_claim_resolution` removed** — 2026-05-06. Function was defined in `claims/repository.py` but never called. Removed to keep the repo surface clean.
- **`process_webhook_payment` audit log** — 2026-05-06. Added `log_audit` after `publish_event` with `actor_id="gateway"`, `actor_role="system"` to match audit coverage of the manual `confirm_payment` path.
- **Auth docstring corrected** — 2026-05-06. `shared/auth.py` docstring said "fail-open" but code raises `ServiceUnavailableError` (correct fail-closed behaviour). Docstring updated to match.
- **Carryover exempt Pydantic validation** — 2026-05-06. Added `ExemptCarryoverRequest(notes: str | None)` to `billing/models.py`. `PATCH /v1/billing/carryovers/{id}/exempt` now uses `_parse_validated(ExemptCarryoverRequest, body)` instead of raw `body.get("notes")`.

---

## Priority 8 — Second Audit Pass

- [x] **Health check missing from `excel/handler.py` and `metering/handler.py`**
  - Both are HTTP-capable Lambda handlers. Every other HTTP handler has `GET /v1/health` (no JWT, returns `{"status":"healthy"}`). These two were missed.
  - _Touches_: `services/excel/handler.py`, `services/metering/handler.py`

- [x] **Idempotency missing from billing, refunds, and excel handlers**
  - `packing_list`, `payment_release`, `claims`, `tracking`, and `tenant_management` handlers all use `check_idempotency`/`store_idempotency`. Missing from:
    - `billing/handler.py` — 4 POST routes (generate billing, create charge, create dispute, POST /disputes)
    - `refunds/handler.py` — `POST /v1/refunds`
    - `excel/handler.py` — `POST /v1/packing-lists/import`
  - _Touches_: `services/billing/handler.py`, `services/refunds/handler.py`, `services/excel/handler.py`

- [x] **Audit logging absent in `refunds/service.py` and `payment_release/service.py`**
  - Both publish events on financial state changes but neither calls `log_audit`. Every other service has audit logging. These are the two most financially significant services.
  - Add `log_audit` calls after every write in: `create_refund`, `accounts_review`, `approve_refund`, `reject_refund` (refunds); `confirm_payment`, `generate_release_note`, `split_release_note`, `record_pickup` (payment_release).
  - _Touches_: `services/refunds/service.py`, `services/payment_release/service.py`

- [x] **`POST /v1/billing` (generate billing) allows CUSTOMER role**
  - The handler uses `_BILLING_READ_ROLES = (TENANT_ADMIN, NIGERIA_OFFICE_STAFF, CUSTOMER)` for both `GET` and `POST /v1/billing`. `generate_billing` is an administrative operation — a customer calling it could manually trigger their own billing. Should be staff/admin only.
  - _Touches_: `services/billing/handler.py`

- [x] **Dead function: `get_claim_resolution` in `claims/repository.py:182`**
  - Defined but never called from service or handler. `create_claim_resolution` is the active path; this getter is orphaned.
  - _Touches_: `services/claims/repository.py`

---

## Priority 9 — Third Audit Pass

- [x] **`process_webhook_payment` missing audit log**
  - `confirm_payment` has `log_audit` (P8), but `process_webhook_payment` is a parallel code path (gateway webhook → payment record → billing update) with no audit trail. Same financial severity.
  - _Touches_: `services/payment_release/service.py`

- [x] **Auth docstring says fail-open, code is fail-closed**
  - `shared/auth.py:114` docstring reads *"Silently passes if the DB is unavailable (fail-open)"* but lines 147–156 raise `ServiceUnavailableError` — the correct fail-closed behaviour per `CLAUDE.md`. Doc contradicts code.
  - _Touches_: `shared/auth.py`

- [x] **Carryover exempt route uses raw `body.get` instead of Pydantic**
  - `PATCH /v1/billing/carryovers/{id}/exempt` does `notes = body.get("notes")` with no model, while every other mutating billing route uses `_parse_validated(SomeModel, body)`. Inconsistent with codebase pattern.
  - _Touches_: `services/billing/handler.py`, `services/billing/models.py`

---

## Notes

- Follow the **Doc-First Rule**: for every item above, update the doc listed under _Touches_ in the same PR.
- For any new DB table, create a new numbered migration (`017_`, `018_`, etc.) and update `05a_` or `05b_` accordingly.
- Security review checklist (from `CLAUDE.md`) is mandatory for any item touching auth, billing, payments, or PII.
