# Operational Runbook

Logistics & Cargo Management System — platform operations guide.

## Environments

| Environment | AWS Account | Region | Notes |
|---|---|---|---|
| dev | — | eu-west-1 | Aurora auto-pause enabled |
| staging | — | eu-west-1 | Aurora auto-pause enabled |
| prod | — | eu-west-1 | No auto-pause; DR replication to eu-central-1 |

---

## Common Operations

- **Tail Lambda logs:** `aws logs tail /aws/lambda/logistics-<service>-prod --follow`
- **Check alarms:** AWS CloudWatch → Alarms → `logistics-*`
- **Dashboard:** CloudWatch → Dashboards → `logistics-prod-overview`

---

## Release Procedures

### Normal release to staging

Create and push an RC tag from a commit that has a green CI run on `main`:

```bash
git tag v1.2.3-rc1 <sha>
git push origin v1.2.3-rc1
```

Only members of `@{org}/release-managers` can push `v*` tags (GitHub tag protection ruleset).
The deploy pipeline resolves the CI artifact for the tagged commit SHA — the tag push will fail
at the `resolve-artifact` step if no successful CI run exists for that commit.

### Normal release to prod

After staging smoke tests pass, push the stable tag:

```bash
git tag v1.2.3 <sha>
git push origin v1.2.3
```

The `deploy-prod` job requires `smoke-staging` to have passed on the same workflow run.

### Post-prod observation window

After every prod deploy, watch CloudWatch for **5 minutes**:

1. Open the `logistics-prod-overview` CloudWatch dashboard
2. Check: Lambda Errors (all functions) — should remain at 0
3. Check: API Gateway 5xx Errors — should remain at 0
4. Check: SQS DLQ — all queues should have 0 visible messages

If alarms fire within the window, initiate rollback immediately (see below).
If all metrics are green at 5 minutes, deployment is complete — no further action needed.

---

## Hotfix Procedure (break-glass)

Use when a critical bug is in prod and cannot wait for the normal tag-based release cycle.

**Prerequisites:** You must be a member of `@{org}/release-managers`.

### Option A — Tag the hotfix commit directly (preferred)

1. Create and push the hotfix on a branch, get it reviewed and merged to `main`
2. Confirm CI passes on the merge commit
3. Tag directly for prod:
   ```bash
   git tag v1.2.4 <hotfix-sha>
   git push origin v1.2.4
   ```
4. Pipeline deploys; observe the 5-minute window (above)

### Option B — `workflow_dispatch` (last resort, when Option A cannot be used)

This is a break-glass procedure. A **post-incident review is required** after any `workflow_dispatch`
to prod.

1. Go to **Actions → Deploy Pipeline → Run workflow**
2. Select `environment: prod`
3. Provide `run_id`: find the CI Pipeline run ID for the commit you want to deploy
   (Actions tab URL contains the run ID, or use `gh run list --workflow=ci.yml`)
4. Run workflow
5. Observe the 5-minute window (above)
6. File a post-incident review in `docs/adr/` documenting why the normal path was bypassed

---

## Rollback Procedure

### Lambda rollback — re-deploy a previous tag

```bash
# Re-tag the last known-good commit as a new patch release
git tag v1.2.4 <prev-sha>
git push origin v1.2.4
```

Or use `workflow_dispatch` with the run ID from a previous successful CI run (see Option B above).

### Lambda rollback — direct AWS CLI (fastest, if artifact is unavailable)

```bash
# Re-deploy a specific service from a previously uploaded zip (if stored in S3):
aws lambda update-function-code \
  --function-name logistics-billing-prod \
  --s3-bucket logistics-artifacts-<account-id> \
  --s3-key previous/billing.zip

# Wait for propagation:
aws lambda wait function-updated --function-name logistics-billing-prod
```

### Terraform rollback

Re-apply the previous infrastructure state:

```bash
cd infrastructure
terraform apply -var-file=environments/prod.tfvars -target=module.lambda
```

### Database rollback

Run an Alembic downgrade **only if** the migration must be reverted. Coordinate with all
service owners before downgrading — code must be rolled back first.

```bash
# Invoke the migration Lambda with a downgrade payload:
aws lambda invoke \
  --function-name logistics-migrate-prod \
  --payload '{"command": "downgrade", "target": "-1"}' \
  /tmp/migrate-out.json
cat /tmp/migrate-out.json
```

Or connect directly via bastion/Session Manager and run:
```bash
alembic -c migrations/alembic.ini downgrade -1
```

**Important:** Migrations must be backward-compatible (additive only). Never drop columns or rename
in the same release as code changes. Use a 2-phase strategy:
- Phase 1: Add new column (nullable), deploy code that writes to both
- Phase 2: Backfill, deploy code reads from new column, drop old column in a follow-up release

---

## Incident Response

### Alarm fired — Lambda Errors > 5 in 5 minutes

1. Check CloudWatch Logs Insights for the affected function:
   ```
   fields @timestamp, @message
   | filter @message like /ERROR/
   | sort @timestamp desc
   | limit 50
   ```
2. Check if a deploy occurred in the last 30 minutes (Actions → Deploy Pipeline)
3. If deploy-related: initiate rollback (see above)
4. If not deploy-related: investigate in logs, page on-call if customer-facing

### Alarm fired — SQS DLQ depth > 0

1. Identify which DLQ: `logistics-{dlq-name}-prod`
2. Check the DLQ message body for the failure reason
3. Fix the root cause, then re-drive messages:
   ```bash
   aws sqs start-message-move-task \
     --source-arn arn:aws:sqs:eu-west-1:<account>:logistics-<name>-dlq-prod \
     --destination-arn arn:aws:sqs:eu-west-1:<account>:logistics-<name>-prod
   ```

### Alarm fired — API Gateway 5xx > 1%

1. Check `logistics-prod-overview` dashboard for which Lambda(s) are erroring
2. Correlate with recent deploys or traffic spikes
3. If deploy-related: rollback; if traffic-related: check Aurora connection alarm

### Alarm fired — Aurora connections > 40

Connection pool (RDS Proxy) is near its limit. Investigate:
1. Check for long-running queries: connect via Session Manager and run `pg_stat_activity`
2. Check for Lambda concurrency spike in CloudWatch
3. If sustained: consider reducing Lambda reserved concurrency temporarily

---

## Security & Reliability Findings Log

Per the SSDLC policy in `CLAUDE.md`, findings and fixes are recorded here.

### 2026-09-23 — full-project debugging pass

| # | Finding | Severity | Status |
|---|---|---|---|
| 0 | **SQL injection via `?sort=`** on `GET /v1/billing`, `/v1/claims`, `/v1/containers`. `shared/pagination.py::build_paginated_query` validated only the segment after the last `.` of the sort field against an allowlist but interpolated the whole string into `ORDER BY`, so `sort=id,(select pg_sleep(5))::text,b.created_at` (or a stacked `id;UPDATE …;--.created_at`) passed as `created_at` and executed — confirmed against Postgres (2.2s vs 0.1s). Reachable by every role that can list, **including customers** (billing list). All other dynamic SQL (46 bandit B608 sites) was audited: constant fragments plus bound parameters — this was the only injectable site. Patched the same day (CRITICAL SLA: 24h). | **CRITICAL** | **Fixed** at the choke point (`fullmatch` of `identifier[.identifier]` + allowlisted column → `422`); `tests/unit/test_sort_injection.py` drives all three endpoints end-to-end with the DB wired to fail. **Because this was live for every deployed build, review `audit_log`/DB logs for unusual `sort=` values if any environment was internet-facing.** |
| 0b | **Unsanitised upload file names** in four presigned-upload flows (claims, manifest evidence, container documents, payment-claim evidence): the raw client `filename` went into the S3 key and, on download, into `Content-Disposition: … filename="{name}"` — a `"` breaks out of the quoted string, and a bidi-override character spoofs the extension staff see. S3 keys are literal so `../` did not traverse tenants (every key still starts with the caller's `tenant_id`; downloads also re-check the prefix). | LOW–MEDIUM | **Fixed** — `shared.validation.safe_filename()` at upload and again at download (legacy rows). 33 tests. |
| 0c | **Dependency advisories.** `safety` reports 6 advisories against the pinned `cryptography==46.0.5` (X.509 path-building DoS `CVE-2026-69249`, improper certificate validation `CVE-2026-69248` / `CVE-2026-34073`, non-contiguous-buffer overflow `CVE-2026-39892`, RSA PKCS#1 v1.5 Bleichenbacher oracle `CVE-2026-69247`, an information-disclosure advisory); the fixed release covering all of them is **≥ 50.0.0**. Exposure here looks low: the app uses `cryptography` for Fernet field encryption (`shared/encryption.py`) and, via PyJWT, RS256 signature *verification* — not X.509 chain validation (TLS is the stdlib `ssl`) or RSA decryption. `npm audit --omit=dev`: 2 moderate `react-router` advisories (open redirect via backslash in `<Link>`/`useNavigate`; SSR-only constructor injection) — not reachable: every `navigate()`/`<Navigate>` target is a fixed path, a role-home mapping or a server-issued id (no `?next=`/`returnTo`), and the app is an SPA. | MEDIUM (unassessed by the tool; low exposure) | **Not changed** — `CLAUDE.md` requires dependency bumps in a dedicated PR with changelog review. **Verified safe to take:** in a clean virtualenv with the exact pins, the full backend suite passes (1141) on `46.0.5` *and* with `cryptography==50.0.1` (`pip check` clean, Fernet round-trip OK) — so the PR is `cryptography==50.0.1` in `requirements.txt` plus a re-run of CI. (`safety` reads `requirements.txt`, so it will keep reporting until the pin moves.) For the frontend, `react-router-dom` ^6.28 → the fixed line is a major bump; schedule it deliberately. Also note `PyJWT` is imported by `services/authorizer` and `services/tenant_management/impersonation.py` but is not in `requirements.txt` — add it (pinned) when the authorizer is adopted (finding: Open decisions #3). |
| 1 | **SSRF in tenant webhooks.** `webhook_config.endpoint_url` was validated only by `^https://` and fetched with `urllib` from inside the VPC: reachable targets included `https://169.254.169.254/…`, RFC1918 addresses (Aurora/Redis/RDS Proxy), `https://localhost/…`, hostnames resolving to those, and public servers redirecting to them; `POST /v1/tenant/config/webhook/test` echoed raw connect errors (internal port-scan oracle). Requires a tenant_admin account. | HIGH | **Fixed** — `shared/url_safety.py` (save-time validator, delivery-time DNS check, pinned-IP connection, no redirects). 70 new tests. Previously-saved internal URLs are inert because delivery re-checks. |
| 2 | **~80 served routes absent from API Gateway** (every `/v1/notifications/*`, warehouses, CBM rate, PDFs, quota, plans, Paystack config, container documents, bulk packing-list actions, …). Worked locally, would 404 in AWS. | HIGH (functional) | **Fixed** — declared in `modules/api-gateway/main.tf`; guarded by `test_infrastructure_contracts.py`. |
| 3 | **All notification Lambdas pointed at a nonexistent handler** (`notification.handler.lambda_handler`) → `Runtime.HandlerNotFound` on every invocation. | HIGH (functional) | **Fixed** — per-channel handlers; contract test added. |
| 4 | **Notifications could never be enqueued in AWS**: `SQS_*_QUEUE_URL` env vars unset (messages silently dropped) and no Lambda role had `sqs:SendMessage`. | HIGH (functional) | **Fixed** — `queue_urls` wired through; `sqs_send_notifications` policy. |
| 5 | **Permissions boundary would have denied all field-level KMS encryption** (`kms:RequestAlias` condition can't match a key-ARN `GenerateDataKey` or a keyless `Decrypt`) → PII (pickup ID numbers, refund bank details) and per-tenant Paystack keys unreadable/unwritable. | HIGH (functional) | **Fixed** — `kms:ResourceAliases`. **Verify after apply** with `aws iam simulate-principal-policy`. |
| 6 | IAM gaps: S3 for tracking/payment_release/manifest/excel (presigned URLs), tenant offboarding purge (S3 versions + Cognito), 6 Cognito admin actions used by `cognito_client.py`, KMS for `tenant_management`. | MEDIUM (functional) | **Fixed** (role policies + boundary). |
| 7 | `GET /v1/platform/tenants/{id}/usage` silently dropped: `metering` never exposed to API Gateway (`active_routes` filter has no error). | MEDIUM | **Fixed.** |
| 8 | `npm run build` (`tsc -b`) failed on 4 type errors — production frontend build was broken. | MEDIUM | **Fixed.** |
| 9 | `TenantReports` had no request cancellation: changing the date range mid-flight let a slower stale response overwrite the newer one. | LOW | **Fixed.** |
| 10 | Tenant-isolation tests had rotted (4 failing) — the suite meant to prove `tenant_id` scoping wasn't running green. | MEDIUM | **Fixed.** |
| 11 | 89 ruff / 31 mypy findings, incl. an unguarded `None` dereference in the payment-verify race path. | LOW | **Fixed.** |

**Verified live** against the real local stack with real seeded data (not just unit tests): every injection payload
(staff, **customer**, stacked statement, claims, containers) returns `422` in ~0.0s with nothing executed and no rows
tampered; legitimate `?sort=` still returns data; the four SSRF targets are refused at save; a legitimate public
webhook saves and the real `webhook/test` endpoint delivers through the hardened opener (`200`); all 50 migrations run
cleanly from an empty database; `make check` (ruff/mypy) and 1141 backend + 799 frontend unit tests are green.

All fixes are covered by tests except the AWS-side behaviour (findings 2–7), which is asserted structurally and by
`terraform validate` but has **not been through `terraform plan`/`apply`**.

### Open infrastructure decisions (not changed — need an owner)

1. **Outbound internet egress from the VPC.** The VPC has no NAT ("no NAT in v1", `modules/networking`); only S3
   (gateway) and SQS, EventBridge, SES-SMTP, Secrets Manager, Logs, Cognito-IDP, KMS (interface) endpoints exist.
   VPC-attached Lambdas therefore cannot reach: **Paystack** (`payment_release` initialize/verify,
   `tenant_management` test-connection — online payment would fail), **Bybit** (`billing` FX rate — degrades to the
   persisted fallback), and, if the notification consumers were moved into the VPC, **Africa's Talking** and
   **Meta**. Options: (a) one NAT Gateway (~$32/month + data) and move the consumers into the VPC — restores
   `notification_log` + metering writes; (b) keep consumers outside the VPC and decouple their DB writes through a
   queue consumed by a VPC Lambda; (c) a small non-VPC egress-proxy Lambda for Paystack/Bybit. Recommendation: (a)
   — a single dependency-free fix, and Paystack cannot be done any other cheap way.
2. **Notification consumers and the database.** Until (1) is decided, `notif-sms|whatsapp|email` still send but their
   `notification_log`/metering writes fail after 5s each; with `batch_size = 10` and a 60s timeout, a slow batch can be
   redelivered (duplicate sends). Interim mitigation **applied**: `batch_size = 1` on the three notification event-source mappings (raise back to 10 once the consumers have DB access).
3. **Custom Lambda authorizer not adopted.** `services/authorizer/handler.py` (Cognito JWT *and* ShipX impersonation
   tokens) is documented but not wired; API Gateway still uses the native JWT authorizer, which rejects HS256
   impersonation tokens, so platform-admin impersonation cannot work in AWS. Requires the checklist at the top of
   that file plus an `IMPERSONATION_SECRET` Secrets Manager secret (also needed by `tenant_management` to sign).
4. **Provider credentials are unprovisioned.** `AFRICASTALKING_API_KEY|USERNAME|SENDER_ID`, `META_WHATSAPP_PHONE_ID|
   ACCESS_TOKEN`, `WHATSAPP_VERIFY_TOKEN`, `SES_FROM_ADDRESS` are read from env vars no Terraform sets. Provision via
   Secrets Manager (per `00_CROSS_CUTTING_STANDARDS.md` §8.1) before go-live.
5. **Lambdas connect to Aurora as `postgres`, not the RLS role — verify RLS is actually enforced in AWS.**
   Migration 005 creates `logistics_app` and applies `FORCE ROW LEVEL SECURITY` so tenant isolation is enforced by
   PostgreSQL itself (defence layer 3), but `modules/lambda` sets `DATABASE_USER = "postgres"` for every Lambda (and the
   migrate Lambda). On RDS/Aurora the master user is typically created with `BYPASSRLS`, in which case RLS is inert
   and isolation rests only on the application's `tenant_id` predicates — meaning an injection or a missed predicate
   (like finding #0) would not be contained by the database. Check with
   `SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname IN ('postgres','logistics_app');` on the real cluster;
   if `postgres` bypasses, connect the API Lambdas as `logistics_app` (rotate the placeholder password in migration
   005 into Secrets Manager first) and keep `postgres` for migrations only. Not changed here: it needs the RDS Proxy
   auth configuration and a real credential, neither of which can be verified locally.
6. **Frontend bundle is a single 937 kB chunk (258 kB gzip)** — every page, including the marketing landing page and
   login, ships together. Route-level `React.lazy` code-splitting would cut first load materially for the
   mobile-heavy Nigerian audience. Not a bug; recorded because the responsive pass made mobile first-load matter more.

## Severity SLA

| Severity | Patch Within |
|---|---|
| CRITICAL | 24 hours |
| HIGH | 72 hours |
| MEDIUM | 2 weeks |
| LOW | Next sprint |

See Architecture Decision Records in `docs/adr/` for system design context.
