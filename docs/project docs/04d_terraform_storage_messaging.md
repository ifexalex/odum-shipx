# Task 04d — Terraform: S3, SQS, EventBridge, SES

## Objective

Create Terraform modules for file storage (S3), message queues (SQS), event bus (EventBridge), and email service (SES).

## Depends On

- Task 01 (Terraform directory structure)

## Deliverables

### Module: `infrastructure/modules/s3/main.tf`

**Resources:**
- `aws_s3_bucket` — "logistics-assets-{env}-{account_id}"
  - Versioning enabled
  - Server-side encryption (AES-256)
  - Lifecycle rules: transition to IA after 90 days, delete incomplete multipart uploads after 7 days
  - Block all public access
  - CORS: allow PUT from web client (for presigned uploads)
- `aws_s3_bucket_policy` — enforce SSL-only access

**S3 Prefix Structure (enforced by application, documented here):**
```
{tenant_id}/claims/{claim_id}/           — damage photos
{tenant_id}/documents/{type}/{id}.pdf    — generated PDFs
{tenant_id}/exports/{date}/              — Excel exports
{tenant_id}/branding/                    — tenant logos
```

**Outputs:** bucket_name, bucket_arn

---

### Module: `infrastructure/modules/sqs/main.tf`

**Queues to create (each with a DLQ):**

| Queue | Purpose | Visibility Timeout | Max Receive Count |
|---|---|---|---|
| `logistics-sms-{env}` | SMS notifications | 60s | 3 |
| `logistics-whatsapp-{env}` | WhatsApp notifications | 60s | 3 |
| `logistics-email-{env}` | Email notifications | 60s | 3 |
| `logistics-metering-{env}` | Usage metering events | 30s | 5 |

**For each queue create:**
- `aws_sqs_queue` — main queue with redrive_policy pointing to DLQ
- `aws_sqs_queue` — DLQ (`-dlq` suffix), message_retention_seconds = 1209600 (14 days)

**All queues:** encryption at rest (SSE-SQS), message_retention_seconds = 345600 (4 days)

**Outputs:** queue URLs and ARNs for all queues and DLQs

---

### Module: `infrastructure/modules/eventbridge/main.tf`

**Resources:**
- `aws_cloudwatch_event_bus` — "logistics-events-{env}"
- EventBridge Rules (route events to SQS queues):

| Rule | Pattern | Target |
|---|---|---|
| `route-sms` | source: "logistics.*", detail-type patterns for SMS events | SQS: sms queue |
| `route-whatsapp` | source: "logistics.*", detail-type patterns for WhatsApp events | SQS: whatsapp queue |
| `route-email` | source: "logistics.*", detail-type patterns for email events | SQS: email queue |
| `route-metering` | source: "logistics.*", detail-type: "UsageRecorded" | SQS: metering queue |

**Event types and their notification routing:**
```
PackingListApproved    → email
ShipmentStatusUpdated  → sms, whatsapp
PaymentDue             → sms, whatsapp
CBMDisputeResolved     → whatsapp
ReleaseNoteGenerated   → sms, whatsapp, email
DamageClaimFiled       → email
TenantOnboarded        → email
TenantSuspended        → email
All events             → metering queue
```

- **Scheduled Rules** (for cron jobs — Task 16):
  - `storage-fee-accrual`: rate(1 day) at 00:00 UTC
  - `dispute-auto-escalation`: rate(6 hours)
  - `sla-breach-check`: rate(4 hours)
  - `storage-reminders`: rate(1 day) at 08:00 UTC
  - `tenant-data-cleanup`: rate(1 day) at 02:00 UTC
  - `usage-aggregation`: rate(1 hour)
  - `release-note-expiry`: rate(1 day) at 00:00 UTC

**Outputs:** event_bus_name, event_bus_arn, scheduled_rule_arns

---

### Module: `infrastructure/modules/ses/` (if needed, or inline)

**Resources (minimal for v1):**
- Verify a domain or email for SES sending
- `aws_ses_email_identity` — for dev/staging
- SES is used by Notification Lambda directly via boto3

**Outputs:** ses_identity_arn

## Acceptance Criteria

- [ ] S3 bucket: encrypted, versioned, no public access, CORS for presigned uploads
- [ ] 4 SQS queues + 4 DLQs created with proper redrive policies
- [ ] EventBridge custom bus created
- [ ] Routing rules correctly map events to appropriate SQS queues
- [ ] Scheduled rules created for all 7 cron jobs
- [ ] All outputs exported for Lambda module consumption
- [ ] `terraform plan` succeeds
