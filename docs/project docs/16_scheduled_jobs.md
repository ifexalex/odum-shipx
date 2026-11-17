# Task 16 — Scheduled Jobs: Storage Fees, Dispute Escalation, Cleanup, Aggregation

## Objective

Implement all 7 scheduled Lambda functions triggered by EventBridge cron rules.

## Depends On

- Task 06 (shared layer), Task 11 (billing), Task 12 (claims)

## Job Registry

| Job | Schedule | Lambda |
|---|---|---|
| Storage Fee Accrual | Daily 00:00 UTC | `logistics-storage-fee-{env}` |
| Dispute Auto-Escalation | Every 6 hours | `logistics-dispute-escalation-{env}` |
| SLA Breach Check | Every 4 hours | `logistics-sla-check-{env}` |
| Storage Reminders | Daily 08:00 UTC | `logistics-storage-reminders-{env}` |
| Tenant Data Cleanup | Daily 02:00 UTC | `logistics-data-cleanup-{env}` |
| Usage Aggregation | Hourly | `logistics-usage-aggregation-{env}` |
| Release Note Expiry | Daily 00:00 UTC | `logistics-release-expiry-{env}` |
| Offboarding Export | Hourly (AWS `rate(1 hour)`; Azure `30 * * * *`) | `logistics-offboarding-export-{env}` (1024 MB, 900 s) |

All jobs iterate over **all active tenants** and process each tenant's data within tenant scope.

## File: `services/scheduled/storage_fee.py`

### Storage Fee Accrual Logic (BR-SF-001, BR-SF-002, BR-SF-003)

```
For each tenant where storage_fee.enabled = TRUE:
  For each release_note with status = 'active':
    grace_period = tenant_config.storage_fee.grace_period_days (default 14)
    days_since_authorized = (NOW() - release_note.authorized_at).days
    if days_since_authorized > grace_period:
      unreleased_count = release_note.carton_count - SUM(pickup_records.cartons_released)
      if unreleased_count > 0:
        day_number = days_since_authorized - grace_period
        if no storage_fee_log for today + this release_note:
          daily_rate = tenant_config.storage_fee.daily_fee_per_carton_ngn
          fee = unreleased_count × daily_rate
          IN ONE TRANSACTION (shared.db.tenant_transaction):
            INSERT storage_fee_log            -- ON CONFLICT (billing_id, accrual_date) DO NOTHING
            UPDATE billing: total_ngn += fee, status recomputed   -- shared.billing_money.adjust_billing
          Publish StorageFeeAccrued event     -- after commit
```

**Updated 2026-11-14.** The log row and the invoice update used to be two separate commits: if the second failed, the
unique `(billing_id, accrual_date)` key blocked every retry and the fee was logged but never charged. They now commit
together or not at all. The status is recomputed in the same statement, so a `paid` invoice that takes a fee becomes
`partially_paid` instead of staying `paid` while owing.

**Storage fees on an invoice = the un-waived rows of `storage_fee_log`.** The job writes only the log and the total; it
never creates `misc_charge` rows. `billing.storage_fees_ngn` in the API is therefore `SUM(storage_fee_log.amount_ngn)
WHERE waived_at IS NULL`. (It used to be summed from `misc_charge` rows of type `storage_fee`, which never exist, so it was
always 0: the storage banner never showed accrued fees and the waive action was never offered.)

**Waiving** (`POST /v1/billing/{id}/storage-fees/waive`): one transaction marks the un-waived rows `waived_at = NOW()`,
takes their sum off `total_ngn`, recomputes the status, and opens a `pending_review` refund request if the customer has
already paid more than the new total. Waived rows stay in the log as history. Fees that accrue after a waiver are charged
as normal (the waiver covers what has accrued so far). With nothing to waive the call returns `422 NO_STORAGE_FEES`.
Before 2026-11-14 the waive query deleted `misc_charge` rows by a `tenant_id` column that table does not have, so every
call returned 500.

## File: `services/scheduled/dispute_escalation.py`

```
For each tenant where dispute_escalation.enabled = TRUE:
  For each cbm_dispute with status = 'investigating':
    days_investigating = (NOW() - last status change to 'investigating').days
    if days_investigating >= tenant_config.dispute_escalation.auto_escalate_days:
      UPDATE cbm_dispute SET status = 'escalated_china', escalated_at = NOW()
      Publish DisputeEscalated event
      Notify China Office Staff + Tenant Admin
```

## File: `services/scheduled/sla_check.py`

```
For each cbm_dispute with status = 'submitted':
  if (NOW() - submitted_at) > 24 hours AND NOT acknowledged:
    Log SLA breach in audit_log (entity_type = 'sla_breach')
    Send reminder notification to Nigeria Office Staff
```

**Staff bell (2026-09-12):** both jobs' "Notify ..." steps above were email-only until now — each also writes a `staff_notification` row (`cbm_dispute_sla_breach`/`cbm_dispute_escalated`) so the same reminder shows up in the TopBar bell, not just an inbox. Full account in `15_api_notifications.md`.

## File: `services/scheduled/storage_reminders.py`

```
For each tenant where storage_fee.enabled = TRUE:
  reminder_days = tenant_config.reminder_days
  For each release_note with status = 'active' and unreleased cartons:
    days_since = (NOW() - authorized_at).days
    if days_since == reminder_days.storage_first_reminder (default 7):
      Send "goods ready for pickup, X days free storage remaining"
    if days_since == reminder_days.storage_final_reminder (default 13):
      Send "storage fees begin tomorrow"
```

## File: `services/scheduled/data_cleanup.py`

**Ground-truth gap closed (2026-11-17):** the object-storage purge read `TENANT_DATA_BUCKET`, which no deployment sets, so it logged "object-storage cleanup skipped" and a deleted tenant's files (claim evidence, documents, exports) stayed in storage. It now purges `{tenant_id}/` in the assets bucket; `TENANT_DATA_BUCKET` is only an override. Tests: `tests/unit/test_data_cleanup.py`.

```
For each tenant with status = 'offboarded' and offboarded_at older than 90 days:
  if no offboarding export requested at/after offboarded_at has completed:
      refuse: log a warning, count it as `refused`, try again tomorrow          (audit BE-10)
  purge object storage {tenant_id}/ (export archive included)               — a failure stops here; retried tomorrow
  one transaction:
      delete every table in shared/tenant_data.TENANT_TABLES, children first
      delete impersonation_session rows for the tenant (NOT NULL key to tenant)
      anonymise platform_audit_log rows about it (target_tenant_id, details → NULL)
      delete the tenant row
  delete Cognito users with this tenant_id (best effort)
  log in audit_log (platform scope)
Returns {deleted, errors, refused}.
```

**Ground-truth gap closed (2026-11-17, found during BE-10): the cleanup could not delete a real tenant.** Its hand-kept table list had 21 tables; the schema has 42 tables of tenant data. Any tenant with rows in a missing table that references a listed one without a cascade (`payment_claim` → `billing`, `warehouse`, `staff_notification`, `customer_invite`, `container_document`, `impersonation_session` → `tenant`, and more) failed on a foreign key, and since each table was its own commit, it failed half-deleted. It now uses the shared inventory (`shared/tenant_data.py`), deletes in one transaction, and purges storage first so a storage failure never leaves files behind a deleted tenant. `tests/unit/test_tenant_data.py` parses every migration and fails if a table is missing from the inventory or the order breaks a foreign key. **Not run against a real database.**

## File: `services/scheduled/offboarding_export.py` (audit BE-10, 2026-11-17)

Hourly. Claims queued exports one at a time (`shared/tenant_export.claim_next`: pending, failed with attempts left, or running for more than 60 minutes), stops claiming after 300 s so the current export can finish under the AWS (900 s) and Azure (600 s) timeouts, and for each: cancels it if the tenant is no longer offboarded; otherwise writes the archive described in `07_api_tenant_management.md` to `{tenant_id}/exports/offboarding/{export_id}.zip`, marks it completed with size, SHA-256 and row counts, and audits `TENANT_DATA_EXPORTED`. Returns `{completed, failed, cancelled}`. The archive is built in memory (hence 1024 MB on AWS); a tenant much larger than today's would need streaming to a temporary file.

## File: `services/scheduled/usage_aggregation.py`

Aggregate raw usage events into daily summaries in `usage_record` table.

## File: `services/scheduled/release_expiry.py`

```
For each release_note with status = 'active' AND expires_at IS NOT NULL AND expires_at < NOW():
  UPDATE release_note SET status = 'expired'
  Notify customer
```

## Acceptance Criteria

- [x] All 7 jobs implemented with correct tenant iteration
- [x] Storage fee accrual creates storage_fee_log records and updates billing
- [x] Grace period respected (no fees before day 15)
- [x] Partial pickup reduces carton count for fee calculation
- [x] Dispute escalation respects tenant config (enabled/disabled)
- [x] SLA breach logged for unacknowledged disputes after 24h
- [x] Storage reminders sent on correct days
- [x] Data cleanup deletes all tenant data after 90 days
- [x] All jobs are idempotent (safe to re-run)
