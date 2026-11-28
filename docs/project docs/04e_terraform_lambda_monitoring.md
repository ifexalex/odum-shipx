# Task 04e — Terraform: Lambda Functions, IAM, CloudWatch, Alarms

## Objective

Create Terraform modules for all Lambda functions, their IAM roles/policies, Lambda Layer, CloudWatch dashboards, and alerting.

## Depends On

- Tasks 04a (VPC, subnets, security groups), 04b (Cognito), 04c (API Gateway), 04d (S3, SQS, EventBridge)

## Lambda Functions to Create

### VPC-Attached Lambdas (need database access):

| Function Name | Runtime | Memory | Timeout | Trigger | VPC |
|---|---|---|---|---|---|
| `logistics-tenant-mgmt-{env}` | python3.12 | 512MB | 30s | API Gateway | Yes |
| `logistics-packing-list-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-manifest-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-tracking-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-billing-{env}` | python3.12 | 512MB | 30s | API Gateway | Yes |
| `logistics-claims-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-payment-release-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-refunds-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-excel-{env}` | python3.12 | 256MB | 60s | API Gateway | Yes |
| `logistics-search-{env}` | python3.12 | 256MB | 15s | API Gateway (`GET /v1/search`, added 2026-11-16) | Yes |
| `logistics-notif-api-{env}` | python3.12 | 256MB | 30s | API Gateway (`/v1/notifications/*`) — `notification.handler.http_handler` (added 2026-09-23) | Yes |
| `logistics-notif-webhook-{env}` | python3.12 | 256MB | 15s | API Gateway (public `/v1/webhooks/whatsapp`) — `notification.handler.webhook_handler` (added 2026-09-23) | Yes |
| `logistics-metering-{env}` | python3.12 | 256MB | 60s | SQS (metering queue) **and** API Gateway (`GET /v1/platform/tenants/{id}/usage`) — dual-mode handler | Yes |

### Non-VPC Lambdas (external API calls, no DB):

| Function Name | Runtime | Memory | Timeout | Trigger |
|---|---|---|---|---|
| `logistics-notif-sms-{env}` | python3.12 | 256MB | 60s | SQS (sms queue) — `notification.handler.sms_handler` |
| `logistics-notif-whatsapp-{env}` | python3.12 | 256MB | 60s | SQS (whatsapp queue) — `notification.handler.whatsapp_handler` |
| `logistics-notif-email-{env}` | python3.12 | 256MB | 60s | SQS (email queue) — `notification.handler.email_handler` |

> **Known gap — needs an architecture decision (2026-09-23).** These were specified as "no DB" (hence non-VPC,
> no NAT), but since migration 027 they write `notification_log` rows (`log_queued`/`log_sent`/`log_failed`,
> best-effort) and meter usage — both need Aurora. From outside the VPC those calls fail after
> `connect_timeout=5s` each: sends still go out, but delivery-log rows and usage metering are lost, and up to
> ~15s per message against a 60s timeout with `batch_size = 10` risks timed-out batches being redelivered
> (duplicate sends). Moving them into the VPC needs NAT egress for Africa's Talking/Meta, which the design
> deliberately avoided ("no NAT in v1"). See `docs/runbook.md` → *Open infrastructure decisions*.

### Scheduled Lambdas (cron jobs, need DB):

| Function Name | Trigger | VPC |
|---|---|---|
| `logistics-storage-fee-{env}` | EventBridge schedule (daily 00:00) | Yes |
| `logistics-dispute-escalation-{env}` | EventBridge schedule (every 6h) | Yes |
| `logistics-sla-check-{env}` | EventBridge schedule (every 4h) | Yes |
| `logistics-storage-reminders-{env}` | EventBridge schedule (daily 08:00) | Yes |
| `logistics-data-cleanup-{env}` | EventBridge schedule (daily 02:00) | Yes |
| `logistics-usage-aggregation-{env}` | EventBridge schedule (hourly) | Yes |
| `logistics-release-expiry-{env}` | EventBridge schedule (daily 00:00) | Yes |

## Deliverables

### Module: `infrastructure/aws/modules/lambda/main.tf`

**For each Lambda:**
- `aws_lambda_function` with:
  - runtime = "python3.12"
  - handler = "{service}.handler.lambda_handler"
  - layers = [shared_layer_arn]
  - VPC config (where applicable): subnet_ids, security_group_ids
  - Environment variables: DATABASE_HOST (RDS Proxy endpoint), DATABASE_NAME, DATABASE_USER, DB_SECRET_ARN, S3_BUCKET_NAME (~~S3_BUCKET~~: renamed 2026-11-17, nothing read it, so every Lambda used the default bucket name `logistics-assets`, which is not this deployment's bucket), EVENT_BUS_NAME, COGNITO_USER_POOL_ID, ENVIRONMENT
  - reserved_concurrent_executions = null (no limit for v1)

- `aws_lambda_layer_version` — "logistics-shared-{env}" (the shared/ code as a layer)

- `aws_iam_role` per Lambda with:
  - AWSLambdaBasicExecutionRole (CloudWatch Logs)
  - AWSLambdaVPCAccessExecutionRole (for VPC Lambdas)
  - Custom policy for each service's specific needs

**IAM Policies per Lambda group:**

| Lambda | Permissions Needed |
|---|---|
| All VPC Lambdas | Secrets Manager (read DB password), RDS Proxy connect |
| tenant_management | Cognito (AdminCreateUser, AdminAddUserToGroup, AdminDisableUser, etc.) |
| claims | S3 (PutObject, GetObject for presigned URLs — scoped to bucket) |
| notification (SMS) | External API access (Africa's Talking) |
| notification (WhatsApp) | External API access (Meta Cloud API) |
| notification (email) | SES (SendEmail) |
| all API Lambdas | EventBridge (PutEvents) |
| metering | SQS (ReceiveMessage, DeleteMessage on metering queue) |
| scheduled jobs | EventBridge, same as their respective service |

- `aws_lambda_event_source_mapping` for SQS-triggered Lambdas
- `aws_lambda_permission` for API Gateway to invoke API Lambdas
- `aws_lambda_permission` for EventBridge to invoke scheduled Lambdas

### CloudWatch Resources:

- `aws_cloudwatch_log_group` per Lambda — retention = 30 days (dev), 90 days (prod)
- `aws_cloudwatch_dashboard` — "logistics-{env}" with key metrics
- `aws_cloudwatch_metric_alarm`:

| Alarm | Metric | Threshold | Action |
|---|---|---|---|
| Lambda Errors | Errors > 5 in 5 min | > 5 | SNS topic |
| API 5xx | 5XXError > 1% | > 1% | SNS topic |
| Aurora Connections | DatabaseConnections > 80% | > 40 | SNS topic |
| SQS DLQ Messages | ApproximateNumberOfMessagesVisible > 0 | > 0 | SNS topic |
| Lambda Duration P95 | Duration p95 > 5000ms | > 5000 | SNS topic |

- `aws_sns_topic` — "logistics-alerts-{env}" (email subscription for dev team)

## Lambda module corrections (2026-09-23)

A code-vs-Terraform audit found the module had drifted well behind the application. Fixed in
`modules/lambda`, `modules/iam-oidc`, root `main.tf`:

1. **Notification handlers pointed at a function that doesn't exist.** All three SQS consumers had
   `handler = "notification.handler.lambda_handler"`; `services/notification/handler.py` defines
   `sms_handler`, `whatsapp_handler`, `email_handler`, `http_handler`, `webhook_handler` — no
   `lambda_handler`. Every invocation would have failed with `Runtime.HandlerNotFound`.
2. **No Lambda served the notification HTTP API.** Added VPC-attached `notif-api` (`http_handler`) and
   `notif-webhook` (`webhook_handler`); the WhatsApp webhook was previously routed to an SQS consumer.
   Both need only Aurora + SQS (reachable in-VPC via the interface endpoint), so neither needs NAT.
3. **Producers could never enqueue.** `SQS_SMS/WHATSAPP/EMAIL_QUEUE_URL` were never set (so
   `enqueue_notification` logged "Queue URL env var not set — notification dropped" and returned), and no
   role had `sqs:SendMessage`. Root now passes `module.sqs.queue_urls` → `var.sqs_queue_urls` → the common
   env; `sqs_send_notifications` grants send on the three notification queues to every API, scheduled and
   consumer Lambda (the WhatsApp consumer falls back to the SMS queue).
4. **`metering` unreachable from API Gateway** — added to `api_lambda_arns` + `aws_lambda_permission.apigw_metering`.
5. **Missing IAM grants, derived from the code's actual boto3 calls:**
   - `s3_documents` — `tracking`, `payment_release`, `manifest`, `excel` presign uploads/downloads (only
     `claims` had S3 access; a presigned URL is authorised as the signing role).
   - `data_cleanup_purge` — S3 list/version/delete + Cognito `ListUsers`/`AdminDeleteUser` for tenant offboarding.
   - `cognito_admin` — added `AdminRemoveUserFromGroup`, `AdminUpdateUserAttributes`, `AdminResetUserPassword`,
     `AdminSetUserPassword`, `AdminUserGlobalSignOut`, `CreateGroup` (used by `cognito_client.py`).
   - `kms_field_encryption` — added `tenant_management` (encrypts each tenant's Paystack secret key).
6. **Permissions boundary (`modules/iam-oidc`)** is an allow-list intersection, so the above would have been
   silently ineffective for actions it lacked. Added `s3:DeleteObjectVersion`, `s3:ListBucketVersions`,
   `cognito-idp:AdminSetUserPassword|AdminUserGlobalSignOut|CreateGroup`, and replaced the KMS condition
   `kms:RequestAlias` (only present when a request names an alias — the code uses a key ARN for
   `GenerateDataKey` and no key for `Decrypt`, so it could never match) with
   `ForAnyValue:StringLike kms:ResourceAliases`.

**Verification limits.** `terraform validate` passes and `tests/unit/test_infrastructure_contracts.py` asserts the
route/handler/service-key contracts, but no `terraform plan`/`apply` has been run against AWS. After applying,
confirm with `aws iam simulate-principal-policy` (KMS and S3-version actions especially) and a smoke call to
`GET /v1/notifications/staff/unread-count`.

**Not changed (still open — see `docs/runbook.md`):** NAT/egress for Paystack, Bybit and the SMS/WhatsApp
providers; adopting the custom Lambda authorizer (`services/authorizer`, needed for impersonation); provisioning
of provider credentials (`AFRICASTALKING_*`, `META_WHATSAPP_*`, `WHATSAPP_VERIFY_TOKEN`), which are env-only and
set nowhere in Terraform.

## Acceptance Criteria

- [x] All Lambda functions created with correct runtime, memory, timeout
- [x] VPC-attached Lambdas in private subnets with Lambda security group
- [ ] ~~Notification Lambdas outside VPC (no NAT Gateway needed)~~ — the SQS consumers still are, but they need Aurora for `notification_log`/metering; see the Known gap above. The notification *HTTP* Lambdas are VPC-attached by design
- [x] Shared Lambda Layer created and attached to all functions
- [x] IAM roles follow least-privilege (each Lambda gets only needed permissions)
- [x] SQS event source mappings for notification + metering Lambdas
- [x] EventBridge scheduled rule targets for cron job Lambdas
- [x] CloudWatch log groups with appropriate retention
- [x] 5 CloudWatch alarms configured
- [x] SNS topic for alerts
- [ ] `terraform plan` succeeds — **`terraform validate` passes (audited 2026-11-11); a real `plan` needs AWS credentials this environment does not have, so the stronger claim is unverified.** Same caveat as `04c_terraform_api_gateway.md`.

## Database credential split (2026-11-08, migration 060)

**Phase 1 (current).** `common_env_vars` still sets
`DATABASE_USER = "postgres"` with the master secret, and the service role's IAM
reads the master secret. Nothing is repointed yet.

**Phase 2** flips `DATABASE_USER` to `logistics_app`, `DB_SECRET_ARN` to
`var.db_app_secret_arn`, and narrows the IAM to the app secret alone.

The phases are separate because on AWS the env flip and the migration are in
**different pipelines**: `terraform.yml` applies infrastructure, `deploy.yml`
runs migrations and then deploys code. A Terraform apply on its own would
repoint every Lambda at a role that migration 060 has not yet given a password
to, and that pipeline contains no migration step to repair it. Phase 1 makes the
credential exist and work; phase 2 is then a two-line change against a role that
already authenticates.

The **migrate** Lambda is deliberately different: it keeps
`DATABASE_USER = "postgres"` because DDL must be owner-run and `logistics_app`
holds only DML. It also receives `APP_DB_SECRET_ARN` and reads *both* secrets,
because migration 060 is what sets the app role's password.

`APP_DB_SECRET_ARN` is an ARN, not a value: `services/migrate/handler.py`
fetches it at runtime via `_inject_app_db_password()`, so the plaintext never
enters a Lambda environment variable or Terraform state.

## Notification channel env + plan-time guard (2026-11-13)

An audit comparing the env vars the notification code reads against the ones
Terraform sets found that **neither cloud wired SMS or WhatsApp at all**. An
earlier pass appeared to show AWS as wired; those matches came from
`infrastructure/aws/modules/lambda/.builds/package/`, an **untracked local build
artifact** that is a copy of the source tree — not Terraform. Worth remembering
when grepping `infrastructure/aws/`: exclude `.builds/`.

Added to `modules/lambda` `common_env_vars` (so every Lambda has them, since
`shared/notifications.py` enqueues from any service):

- `APP_BASE_URL`, `CUSTOMER_PORTAL_BASE_URL` — link bases. Previously **neither**
  was set on AWS, so activation links were empty and invite links relative.
- `SES_FROM_ADDRESS` — verified sender.
- `AFRICASTALKING_API_KEY` (sensitive), `AFRICASTALKING_USERNAME`,
  `AFRICASTALKING_SENDER_ID`.
- `META_WHATSAPP_ACCESS_TOKEN` (sensitive), `META_WHATSAPP_PHONE_ID`,
  `META_WHATSAPP_TEMPLATE_LANG`, `WHATSAPP_VERIFY_TOKEN` (sensitive).
- `NOTIFICATION_ALLOWLIST` — fails closed outside production.

All default to `""`, which the code treats as unconfigured (see below).

### `terraform_data.notification_config_guard`

Modelled on the existing `auth_config_guard`, and for the same reason: these
values cannot be derived from Terraform, which is exactly why they are easy to
forget, and the failure mode is invisible — every send path logs
"not configured" and returns, so the deploy is healthy, the API returns 200, and
customers are simply never told anything. The guard fails the **plan** instead.

- A link base is required in **every** environment (a relative link is worse
  than no message — it burns the token and reports success).
- In **prod** only: `ses_from_address`, the Africa's Talking key + username, and
  all three WhatsApp values. Non-prod may run with channels off.

The Azure twin lives in `infrastructure/azure/main.tf`; it omits the email check
because `module.acs` always derives a sender from its managed domain, so
`SES_FROM_ADDRESS` is never the application's placeholder there.

### Note on empty strings

Terraform sets `""` for an unconfigured variable, and `""` is "set" as far as
`os.environ.get(name, default)` is concerned — so a `get()` default is bypassed
and the provider receives a blank value. `send_email` and `send_sms` therefore
use `os.environ.get(...).strip() or DEFAULT`. A unit test caught this after the
guard was first written against the `get()` default and silently did nothing.

## Environment added by audit Phase 2 (2026-11-15)

- `ALLOWED_ORIGINS` (every Lambda, from `var.cors_allow_origins`, comma-separated): the origins the auth Lambda accepts on its
  cookie endpoints (`shared/origin_guard.py`). It also trusts the origins of `APP_BASE_URL` and
  `CUSTOMER_PORTAL_BASE_URL`. With none of the three set it refuses every request, so do not drop them.
- `RATE_LIMIT_ENABLED=false` on the **non-VPC** `auth` Lambda only: it cannot reach ElastiCache, and a connection
  attempt would add a timeout to every request. Its public routes are throttled per route at API Gateway.
- Azure container app (2026-11-17): `AZURE_FRONT_DOOR_ID` is set by Terraform from the Front Door profile's
  `resource_guid`, and the app takes the client address from Front Door's own stamp on requests carrying it, so
  there is no hop count to measure. `REQUIRE_FRONT_DOOR` (variable `require_front_door`, default false) refuses
  requests that go around Front Door. `TRUSTED_PROXY_HOPS` (default 0) is now only a fallback for a deployment
  with no Front Door. The Front Door profile resource moved from `module.frontend` to the root (with a `moved`
  block) to break the dependency cycle this would otherwise create. No new Azure resource, no added cost.

## `PICKUP_CODE_PEPPER` (2026-11-16)

`random_password.pickup_code_pepper` (48 characters, in the lambda module; the same in `infrastructure/azure/modules/container_app`, as a Container App secret) is injected into every function as `PICKUP_CODE_PEPPER`. It keys the hash of release-note pickup codes (ADR-008). It lives in Terraform state like the other generated secrets. Do not rotate it casually: every outstanding code stops verifying.

**Offboarding export (audit BE-10, 2026-11-17).** New scheduled Lambda `offboarding_export` (`scheduled.offboarding_export.lambda_handler`, 1024 MB, 900 s, VPC). IAM: `aws_iam_role_policy.offboarding_export` (`s3:PutObject` on `{bucket}/*/exports/offboarding/*` only; `kms:Decrypt` on the field-encryption key, no `GenerateDataKey`) and `tenant_management_export_download` (`s3:GetObject` on the same path, so tenant_management can sign the download link). Azure: Container App Job `offboarding_export` (`30 * * * *`, the shared job image and identity; `job_timeout_seconds` 600). `terraform validate` passes for both roots; not applied.

**Platform approvals (platform audit Phase 1, 2026-11-28).** New scheduled Lambda `platform_approvals` (`scheduled.platform_approvals.lambda_handler`, 256 MB, 300 s, VPC; rule `platform-approvals`, `rate(15 minutes)`); no extra IAM beyond the shared scheduled role. Azure: Container App Job `platform_approvals` (`*/15 * * * *`). `COGNITO_CLIENT_ID` is now in the common Lambda environment: tenant_management's step-up re-authentication signs in through the public app client (`initiate_auth`, which needs no IAM permission).

**Failure alarms (audit OPS-04, 2026-11-17).** `modules/monitoring` adds `aws_cloudwatch_metric_alarm.failures` (for_each: `invoice-generation` and `audit-write`, any failure in 5 min; `scheduled-job-step`, any in 1 hour) and `notification_failure_rate` (metric math `IF(attempts >= 5, 100 * failures / attempts, 0) > 20` over 15 min). They read the `ShipX` namespace that `shared/observability.py` writes as Embedded Metric Format log lines (dimensions `Environment`, `Operation`), so no IAM change and no API call. New variables: `metric_namespace` (default `ShipX`), `notification_failure_rate_percent` (20), `notification_rate_min_attempts` (5). Cost: about USD 0.30 a month per counted operation (six) plus USD 0.10 per alarm (four). Azure: `modules/monitoring` adds an action group and four scheduled-query alert rules over `ContainerAppConsoleLogs_CL`, every 15 minutes, created only when `alerts_email` is set (root variable, default empty). `terraform validate` passes for both roots; not applied, and no alarm has been seen to fire (runbook: "Failure alarms" has the check). The Azure KQL has not been run against real logs.
