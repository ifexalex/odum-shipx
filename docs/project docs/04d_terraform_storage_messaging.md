# Task 04d — Terraform: S3, SQS, EventBridge, SES

## Objective

Create Terraform modules for file storage (S3), message queues (SQS), event bus (EventBridge), and email service (SES).

## Depends On

- Task 01 (Terraform directory structure)

## Deliverables

### Module: `infrastructure/aws/modules/s3/main.tf`

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

### Module: `infrastructure/aws/modules/sqs/main.tf`

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

### Module: `infrastructure/aws/modules/eventbridge/main.tf`

**Resources:**
- `aws_cloudwatch_event_bus` — "logistics-events-{env}"
- EventBridge Rules (route events to SQS queues):

| Rule | Pattern | Target |
|---|---|---|
| ~~`route-sms`~~ | removed 2026-11-17 (audit BE-09) | ~~SQS: sms queue~~ |
| ~~`route-whatsapp`~~ | removed 2026-11-17 (audit BE-09) | ~~SQS: whatsapp queue~~ |
| ~~`route-email`~~ | removed 2026-11-17 (audit BE-09) | ~~SQS: email queue~~ |
| `route-metering` | source prefix `{project_name}.` (every event) | SQS: metering queue |

**Notification routing (corrected 2026-11-17).** ~~Event types fanned out to the sms/whatsapp/email queues by detail-type.~~ **No EventBridge rule targets a notification queue.** The sms, whatsapp and email consumers read only the message `shared/notifications.py::enqueue_notification(s)` writes (`tenant_id`, `event_type`, `recipient`, `template_data`, …; see `15_api_notifications.md`). A raw EventBridge envelope has no `recipient`, so every event the three rules delivered was skipped with "missing recipient … skipping": wasted invocations and log noise, and a duplicate message the day a consumer is taught to read them. Each service enqueues its notifications directly. The bus feeds the metering queue only.

**Least privilege.** `local.eventbridge_queue_keys = ["metering"]` drives both the delivery role's `sqs:SendMessage` (was every queue) and the queue resource policies (were on all four queues). Applying this deletes the three rules, their targets and the EventBridge statements on the sms/whatsapp/email queue policies; the Lambdas send to those queues through their own IAM roles, which are unchanged. Contract test: `TestNoEventGoesToANotificationQueue` (`tests/unit/test_infrastructure_contracts.py`). `terraform validate` passes; not planned or applied against AWS (no credentials here).

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

### Module: `infrastructure/aws/modules/ses/` (if needed, or inline)

**Resources (minimal for v1):**
- Verify a domain or email for SES sending
- `aws_ses_email_identity` — for dev/staging
- SES is used by Notification Lambda directly via boto3

**Outputs:** ses_identity_arn

## Acceptance Criteria

- [x] S3 bucket: encrypted, versioned, no public access, CORS for presigned uploads
- [x] 4 SQS queues + 4 DLQs created with proper redrive policies
- [x] EventBridge custom bus created
- [x] ~~Routing rules correctly map events to appropriate SQS queues~~ Only the metering queue is an EventBridge target; services enqueue notifications directly (audit BE-09, 2026-11-17)
- [x] Scheduled rules created for all 7 cron jobs
- [ ] All outputs exported for Lambda module consumption — `queue_urls` is now wired through to the Lambda module (2026-09-23) as the `SQS_SMS_QUEUE_URL` / `SQS_WHATSAPP_QUEUE_URL` / `SQS_EMAIL_QUEUE_URL` env vars; it was exported but never consumed, so every enqueue was silently dropped in AWS (see `04e_terraform_lambda_monitoring.md`)
- [ ] `terraform plan` succeeds — **`terraform validate` passes (audited 2026-11-11); a real `plan` needs AWS credentials this environment does not have, so the stronger claim is unverified.** Same caveat as `04c_terraform_api_gateway.md`.

**Scheduled rule added 2026-11-17 (audit BE-10):** `offboarding-export = rate(1 hour)` → the `offboarding-export` Lambda (`04e`). Azure: Container App Job `offboarding_export`, cron `30 * * * *`.
