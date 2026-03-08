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
          INSERT storage_fee_log
          UPDATE billing: storage_fees_ngn += fee, total_due_ngn += fee, outstanding_ngn += fee
          Publish StorageFeeAccrued event
```

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

```
For each tenant with status = 'offboarded':
  if (NOW() - offboarded_at) > 90 days:
    Delete all tenant data (customer, container, billing, etc.)
    Delete tenant S3 prefix
    Delete Cognito users with this tenant_id
    Delete tenant record
    Log in platform_audit_log
```

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
