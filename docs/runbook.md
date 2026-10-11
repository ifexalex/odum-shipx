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

The `deploy-prod` job requires `smoke-staging` to have passed on the same workflow run. A
read-only `smoke-prod` job (GET /health + unauthenticated-401 checks + 2s SLA) then runs after
the prod deploy and fails the pipeline loudly if prod came up unhealthy.

> **Azure infra** has its own pipeline (`terraform-azure.yml`, dev→staging→prod, OIDC) — see
> `docs/project docs/18_cicd_pipeline.md` → "Azure deployment pipeline".

### Post-prod observation window

After every prod deploy, watch CloudWatch for **5 minutes**:

1. Open the `logistics-prod-overview` CloudWatch dashboard
2. Check: Lambda Errors (all functions) — should remain at 0
3. Check: API Gateway 5xx Errors — should remain at 0
4. Check: SQS DLQ — all queues should have 0 visible messages

If alarms fire within the window, initiate rollback immediately (see below).
If all metrics are green at 5 minutes, deployment is complete — no further action needed.

---

## Frontend Deployment & Go-Live

The frontend is a static Vite/React SPA served as **S3 (private) + CloudFront (CDN)** — the cost-effective, scalable, resilient, highly-available pattern. All of it is in Terraform (`infrastructure/aws/modules/cloudfront/`) and CI (`.github/workflows/frontend-ci.yml`); the design is complete, so go-live is **provisioning + DNS/cert + secrets**, not new code.

> **Azure alternative:** the same SPA can deploy to **Blob static site + Front Door Standard** — see `infrastructure/azure/` (root stack + `modules/frontend`) and its `README.md`. Same `frontend/dist/` artifact, different target cloud. Cost: `docs/azure_cost_model.md`.

> **Backend cloud portability (`CLOUD_PROVIDER`):** the backend selects its cloud at runtime via the `CLOUD_PROVIDER` env var (`aws` default | `azure`). Cloud SDKs live only behind the ports in `shared/providers/` — `KeyProvider` (crypto/KMS), `StorageProvider` (object storage), `SecretsProvider` (Secrets Manager), `EventProvider` (EventBridge), `QueueProvider` (SQS), `EmailProvider` (SES) — each with an AWS adapter today. Presigned uploads use a cloud-neutral **PUT** contract (`{ upload_url, upload_method, upload_headers }`) that both S3 and Azure Blob satisfy. X-Ray tracing is behind a shim (`shared/observability.py::init_tracing`, called at each Lambda's module load; no-op when `CLOUD_PROVIDER != "aws"`). To port a touchpoint to Azure: add the `shared/providers/azure/*` adapter and set `CLOUD_PROVIDER=azure` + the Azure-side env vars (`ENCRYPTION_KEY_VAULT_KEY_ID`, `BLOB_CONTAINER_NAME`, …). The one remaining boto3 touchpoint is **Cognito** (auth) — migrated behind the same pattern, but it also needs a token-claim mapping + user migration to Entra, so it's scoped separately rather than a drop-in adapter. See `docs/project docs/02_shared_utilities.md` → "shared/providers/" and `infrastructure/azure/README.md`.

```
Browser ──TLS──▶ CloudFront (global edge, PriceClass_100)
                   │  OAC (signed origin reads)
                   ▼
                 S3 bucket (private, versioned, SSE)  ← CI `aws s3 sync dist/`
```

**Why this meets the four goals** (for reference):
- **Cost** — no servers; S3 pennies/GB + CloudFront egress; `PriceClass_100` (US/EU edges only); hashed assets cached `immutable` for 1 year so origin GETs + invalidations are near-zero (only `/index.html` is invalidated per deploy). Scales to ~$0 at idle.
- **Scalable** — CloudFront absorbs any spike with no capacity planning; S3 throughput is effectively unlimited.
- **Resilient** — S3 11-nines durability + versioning (instant rollback); CI uploads hashed assets first and `index.html` last so no user ever gets a half-updated app; private bucket + OAC (no public exposure).
- **HA** — S3 + CloudFront are multi-AZ/global managed services; no single server to fail. SPA deep-links survive via `custom_error_response` 403/404 → `/index.html` (200).

### What's already implemented (verified)
- Private, versioned, SSE-encrypted S3 origin; all public access blocked; CloudFront reads via **OAC**.
- CloudFront: HTTP/2+3, IPv6, `redirect-to-https`, TLS1.2_2021, compression, security-headers policy incl. CSP (`connect-src` scoped to the API Gateway + Cognito domains), cache policies (immutable assets vs. no-cache `index.html`), SPA fallback.
- **ACM cert in us-east-1** (CloudFront requirement) via the `aws.us_east_1` provider alias, DNS-validated through Route 53 — handled automatically by the module.
- Route 53 apex + `*.domain` wildcard A-alias records (wildcard backs tenant subdomains).
- **WAFv2 Web ACL** attached to the distribution (rate limit + AWS IP reputation + common rule set + known-bad-inputs) — see "DDoS & attack protection" below.
- CI deploy job (`deploy`): OIDC auth (no static keys), gated to `push` on `main` + the `prod` GitHub Environment (approval-capable; shared with the backend so one set of reviewers gates both), builds with prod `VITE_*`, syncs assets `immutable`, uploads `index.html` `no-cache`, invalidates `/index.html`.
- Module outputs: `distribution_id`, `distribution_domain`, `s3_bucket_name`, `s3_bucket_arn`, `waf_web_acl_arn`.

> **Note:** the Terraform has **not been `apply`'d** yet (see "Open infrastructure decisions"), and the CloudFront module is **gated on `route53_zone_id`** (`count = var.route53_zone_id != "" ? 1 : 0`) — it creates nothing until a hosted zone is supplied.

### One-time go-live — prerequisites
1. **Register / delegate the domain** and create a **Route 53 hosted zone** for it. Note the zone ID.
2. Set these in the prod tfvars (or TF Cloud/CI variables):
   - `domain_name` = e.g. `app.shipx.example`
   - `route53_zone_id` = the hosted-zone ID from step 1
   - `frontend_price_class` = `PriceClass_100` (default; bump to `PriceClass_200/All` only if you need edges beyond US/EU)
3. **OIDC deploy role** (`infrastructure/aws/modules/iam-oidc`): ensure the GitHub Actions deploy role used for the frontend has `s3:PutObject`/`s3:DeleteObject` on the frontend bucket and `cloudfront:CreateInvalidation` on the distribution. (The frontend workflow reads `FRONTEND_DEPLOY_ROLE_ARN` separately from the backend's `AWS_DEPLOY_ROLE_ARN` — either extend the existing role's policy to cover the frontend bucket/distribution, or add a dedicated role.)

### One-time go-live — provision
```bash
cd infrastructure/aws
terraform plan  -var-file=prod.tfvars   # review: S3 bucket, CloudFront dist, ACM cert, Route53 records
terraform apply -var-file=prod.tfvars   # ACM DNS validation can take a few minutes
terraform output                        # grab cloudfront distribution_id + s3_bucket_name
```

### One-time go-live — CI secrets (GitHub → repo/Environment `production`)
| Secret | Value |
|---|---|
| `FRONTEND_DEPLOY_ROLE_ARN` | OIDC role ARN (s3:PutObject + cloudfront:CreateInvalidation) |
| `FRONTEND_S3_BUCKET` | `terraform output … s3_bucket_name` |
| `FRONTEND_CLOUDFRONT_ID` | `terraform output … distribution_id` |
| `VITE_API_BASE_URL` | prod API Gateway URL |
| `VITE_COGNITO_USER_POOL_ID` / `VITE_COGNITO_CLIENT_ID` | prod Cognito |
| `VITE_ENVIRONMENT` | `production` |

### First + ongoing deploys
- **First deploy:** push to `main` (or re-run the `frontend-ci` workflow). The `deploy` job builds with the prod `VITE_*`, syncs to S3, invalidates `/index.html`. Verify at `https://<domain_name>` — hard-refresh, confirm a deep link (e.g. `/admin/users`) loads, and that API/Cognito calls succeed (CSP allows only the configured domains).
- **Ongoing:** every push to `main` touching `frontend/**` redeploys automatically (path-filtered; backend-only changes don't trigger it).

### Rollback
- Fastest: re-run the `frontend-ci` workflow on the last-good commit (rebuilds + re-syncs).
- Or restore prior object versions from the versioned bucket, then `aws cloudfront create-invalidation --paths "/index.html"`.

### DDoS & attack protection (what's in place)
The frontend has defence in depth across layers:
- **AWS Shield Standard** — automatic + free on every CloudFront distribution; absorbs L3/L4 (network/transport) DDoS (SYN floods, reflection, etc.). No config needed.
- **WAFv2 Web ACL** (`aws_wafv2_web_acl.frontend`, scope `CLOUDFRONT`, us-east-1) — now attached via `web_acl_id`. Rules, in order:
  1. **Rate limit** (`var.waf_rate_limit`, default 2000 req/IP/5min) → **block** — the primary layer-7 DDoS / brute-force control. Raise for offices behind a shared NAT; lower to tighten.
  2. **Amazon IP reputation list** — blocks known bot/recon/DDoS source IPs.
  3. **Common rule set** — XSS, LFI, protocol/size abuse (safe on this static-asset origin).
  4. **Known bad inputs** — known exploit signatures (Log4Shell, path traversal, host-header injection).
  - Each rule + the ACL emit CloudWatch metrics with sampled requests (tune thresholds / spot false positives from the WAF console). Cost ≈ $5/mo (ACL) + ~$1/rule/mo + $0.60 per million requests.
- **Private origin** — S3 is reachable only via CloudFront OAC; there is no public bucket URL to attack directly.

**API layer (API Gateway + Lambda):** the API is an **HTTP API (v2)**, which **cannot take a WAFv2 ACL directly** (WAF supports REST/v1 APIs, ALB, AppSync, Cognito, CloudFront — not HTTP APIs). Its protections today: **Shield Standard** (automatic), **stage throttling** (`throttling_rate_limit = 50` req/s, `throttling_burst_limit = 100` in `api-gateway/main.tf`), Lambda reserved-concurrency ceilings, and per-tenant metering/quota. If you later want full L7 WAF on the API, the standard pattern is to **front API Gateway with its own CloudFront distribution** and attach a `REGIONAL`→`CLOUDFRONT` WAF there (a deliberate follow-up, not required for launch).

**Monitoring:** add a CloudWatch alarm on the WAF `BlockedRequests` metric (sudden spikes = an active attack or a too-tight rate limit); sampled requests in the WAF console show what's being blocked.

### Other hardening (optional)
- Code-split the ~937 kB single JS chunk for faster first paint (known item, not a blocker).
- For high-value launches under sustained attack, **AWS Shield Advanced** (paid) adds L7 DDoS cost protection + a response team.

---

## Azure deployment — required one-time setup (Entra auth)

**Applies only when `DEPLOY_CLOUD=azure`.** The Azure pipeline deploys everything except two
Entra-tenant steps that have **no Terraform/azuread resource** and that the Contributor deploy
identity cannot perform. **Login is broken until both are done** — the deploy succeeds (the claims
provider runs as a Container App on the shared image), but tokens carry no `tenant_id`/`role`, so
every request resolves as an unprivileged `customer` (platform admin included). Run these once per
Entra tenant, after the first `deploy-azure.yml` run has created the resources. Full context:
`infrastructure/azure/README.md`
→ "Entra tenant setup" + "Token claims on CIAM".

**Prerequisite (done by the tenant admin, before any of the below):** an Entra External ID tenant +
SPA app registration exist, and `scripts/setup_entra_platform_admin.sh` has been run (creates the
`platform_admin` group, the `tenant_id`/`role` directory extensions, and the first admin). Set the
matching tfvars (`entra_claims_*`, `entra_tenant_id_attr`, `entra_role_attr`) and the API env
(`AUTH_PROVIDER=azure`, `OIDC_*`, `ENTRA_TENANT_ID_CLAIM`/`ENTRA_ROLE_CLAIM`,
`ENTRA_PLATFORM_ADMIN_GROUP_ID`) so a deploy picks them up.

1. **Grant the claims provider's managed identity Graph `User.Read.All`** (the shared app managed
   identity the claims Container App runs as; it reads users' extension attributes). Needs a
   Graph-admin / Privileged Role Admin — not the deploy identity:
   ```bash
   cd infrastructure/azure
   PRINCIPAL=$(terraform output -raw entra_claims_principal_id)
   GRAPH_SP=$(az ad sp list --filter "appId eq '00000003-0000-0000-c000-000000000000'" --query '[0].id' -o tsv)
   ROLE=$(az ad sp show --id "$GRAPH_SP" --query "appRoles[?value=='User.Read.All'].id | [0]" -o tsv)
   az rest --method POST \
     --url "https://graph.microsoft.com/v1.0/servicePrincipals/$PRINCIPAL/appRoleAssignments" \
     --body "{\"principalId\":\"$PRINCIPAL\",\"resourceId\":\"$GRAPH_SP\",\"appRoleId\":\"$ROLE\"}"
   ```
2. **Register + bind the custom authentication extension** to the SPA app's token-issuance event,
   pointing it at `terraform output -raw entra_claims_endpoint_url` — `customAuthenticationExtensions`
   + `authenticationEventListeners` via Graph `/beta` (or the portal: Enterprise apps → Custom
   authentication extensions). This is what makes Entra call the claims provider on every sign-in.

**Verify:** sign in (ROPC or the SPA), decode the **id_token**, and confirm it carries `tenant_id` +
`role` (and `groups`). If they're missing: step 2 isn't bound (or propagation lag); if the claims
provider 500s: step 1's Graph grant is missing (check the `*-entra-claims` Container App logs). These
two steps persist across deploys and do not need repeating.

**Rollback / cloud switch:** flipping `DEPLOY_CLOUD` back to `aws` returns auth to Cognito with no
Entra dependency; the Entra objects can stay in place, dormant.

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
cd infrastructure/aws
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
| 0c | **Dependency advisories.** `safety` reports 6 advisories against the pinned `cryptography==46.0.5` (X.509 path-building DoS `CVE-2026-69249`, improper certificate validation `CVE-2026-69248` / `CVE-2026-34073`, non-contiguous-buffer overflow `CVE-2026-39892`, RSA PKCS#1 v1.5 Bleichenbacher oracle `CVE-2026-69247`, an information-disclosure advisory); the fixed release covering all of them is **≥ 50.0.0**. Exposure here looks low: the app uses `cryptography` for Fernet field encryption (`shared/encryption.py`) and, via PyJWT, RS256 signature *verification* — not X.509 chain validation (TLS is the stdlib `ssl`) or RSA decryption. `npm audit --omit=dev`: 2 moderate `react-router` advisories (open redirect via backslash in `<Link>`/`useNavigate`; SSR-only constructor injection) — not reachable: every `navigate()`/`<Navigate>` target is a fixed path, a role-home mapping or a server-issued id (no `?next=`/`returnTo`), and the app is an SPA. | MEDIUM (unassessed by the tool; low exposure) | **FIXED (2026-10-08):** bumped `cryptography==46.0.5 → 50.0.2` in `requirements.txt` + `requirements-layer.txt` (≥50.0.0 clears the binding CVE-2026-69247 and all six); `safety check` now reports 0. Encryption round-trip + Key Vault wrap/unwrap tests pass on 50.0.2. **Verified safe to take:** in a clean virtualenv with the exact pins, the full backend suite passes (1141) on `46.0.5` *and* with `cryptography==50.0.1` (`pip check` clean, Fernet round-trip OK) — the applied pin is `cryptography==50.0.2`. (`safety` reads `requirements.txt`, so it will keep reporting until the pin moves.) For the frontend, `react-router-dom` ^6.28 → the fixed line is a major bump; schedule it deliberately. Also note `PyJWT` is imported by `services/authorizer` and `services/tenant_management/impersonation.py` but is not in `requirements.txt` — add it (pinned) when the authorizer is adopted (finding: Open decisions #3). |
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
