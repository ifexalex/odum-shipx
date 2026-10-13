# ShipX — Azure stack (portability target)

This is the **Azure** deployment of ShipX, kept alongside the AWS stack in `../aws`
so the app can be deployed to either cloud. You run **one** cloud at a time (see
the cloud-portability notes in `docs/runbook.md`); this stack lets you move to
Azure (e.g. to use Founders Hub credits) without re-architecting.

> **Setting up a fresh Azure subscription?** Follow **[`SETUP.md`](SETUP.md)** —
> the ordered, copy-pasteable bootstrap (subscription upgrade → resource providers
> → tfstate → Contributor-only OIDC identity → GitHub config → auth → first deploy)
> with a troubleshooting table for every gotcha. This README is the architecture
> reference; SETUP.md is the runbook.

**Status:** incremental build-out. Implemented so far:

| Piece | AWS (`../aws`) | Azure (here) | Status |
|---|---|---|---|
| Frontend hosting / CDN | S3 + CloudFront | **Blob static website + Front Door Standard** | ✅ |
| WAF / DDoS | CloudFront WAF | Cloudflare (recommended) / Front Door Premium | ⏳ |
| Backend compute | Lambda | **Container Apps** (`Dockerfile` + `modules/container_app`) | ✅ Terraform (image pushed by CI) |
| Networking | VPC + subnets | **VNet + delegated subnets (`modules/networking`)** | ✅ Terraform |
| Object storage | S3 | **Blob (`BlobStorageProvider`)** — adapter + `modules/storage` Terraform; Azurite- & real-account-testable | ✅ |
| Queue | SQS | **Service Bus (`ServiceBusQueueProvider`)** — adapter + `modules/servicebus` Terraform | ✅ |
| Database | Aurora Serverless v2 | **PostgreSQL Flexible Server (`modules/postgres`)** — VNet-integrated, private | ✅ Terraform |
| Cache | ElastiCache | **Azure Cache for Redis (`modules/redis`)** | ✅ Terraform |
| Auth | Cognito | **Entra External ID** (`EntraIdentityProvider` + `EntraClaimsMapper`) | 🔨 adapters + migration script done; tenant setup manual |
| Events | EventBridge | **Event Grid (`EventGridProvider`)** — adapter + `modules/eventgrid` Terraform | ✅ |
| Email | SES | **ACS Email (`AcsEmailProvider`)** — adapter + `modules/acs` Terraform | ✅ |
| Monitoring | CloudWatch | **Log Analytics + App Insights (`modules/monitoring`)** | ✅ Terraform |
| Secrets / crypto | Secrets Manager + KMS | **Key Vault (`KeyVaultSecretsProvider` + `KeyVaultKeyProvider`)** — adapters + `modules/keyvault` Terraform; real-account-verifiable | 🔨 |

## Subscription prerequisites & capability toggles

**1. Register resource providers** (one-time per subscription — the apply fails with
`... is not registered for the Microsoft.X resource provider` otherwise):

```bash
for rp in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights \
          Microsoft.Insights Microsoft.DBforPostgreSQL Microsoft.Cache \
          Microsoft.ServiceBus Microsoft.EventGrid Microsoft.Communication \
          Microsoft.KeyVault Microsoft.Storage Microsoft.Network \
          Microsoft.ManagedIdentity Microsoft.Cdn; do az provider register -n "$rp"; done
az provider show -n Microsoft.App --query registrationState   # wait for "Registered"
```

**2. Capability toggles** (tfvars) — some services are restricted on **Free Trial / Student**
subscriptions. `dev.tfvars` ships with all three off for exactly that case; defaults are `true`
for pay-as-you-go subs:

| Variable | Default | Set `false` when | Effect when `false` |
|---|---|---|---|
| `enable_frontend` | `true` | Front Door is forbidden (Free Trial/Student) | skip the Blob+Front Door module (backend-only) |
| `enable_redis` | `true` | classic Redis is retiring/blocked | skip Redis; the cache degrades to DB lookups (still functional) |
| `grant_acr_pull` | `true` | the deploy identity is Contributor-only (can't write role assignments) | pull images from ACR with **admin creds** instead of a managed-identity AcrPull role |

For the **secure** path (`grant_acr_pull = true`) the deploy identity needs role-assignment
rights — grant it **User Access Administrator** on the subscription/RG:
```bash
az role assignment create --assignee "$APP_ID" --role "User Access Administrator" \
  --scope "/subscriptions/$SUB"
```

## Frontend module (what's here now)

`modules/frontend` = Blob storage `$web` static site behind **Front Door
Standard** (CDN, HTTPS with a free managed cert on the `*.azurefd.net` endpoint,
SPA 404→index fallback, gzip, and a security-headers rule set mirroring the AWS
CloudFront response-headers policy). Front Door **Standard** has no WAF — add
Cloudflare at the edge (cheap, cloud-neutral) or move to Front Door Premium
later. Custom domain is a follow-up; the default endpoint gives a working HTTPS
URL immediately.

## Deploy

Two ways: the **CI pipeline** (recommended for dev/staging/prod) or a **manual apply** (ad-hoc).

### CI pipeline — `.github/workflows/terraform-azure.yml`

Mirrors the AWS `terraform.yml`: push to `main` touching `infrastructure/azure/**` runs
dev → staging → prod (each gated by its GitHub Environment), or run it on demand from
**Actions → "Terraform (Azure)"**. Auth is OIDC federated creds (no secrets). State lives in an
azurerm backend (per-env `environments/*.backend.hcl`). **One-time state bootstrap + the Entra
OIDC app + GitHub secrets are in `docs/project docs/18_cicd_pipeline.md` → "Azure deployment
pipeline".** Terraform state backend configs: `environments/{dev,staging,prod}.backend.hcl`;
per-env vars: `environments/{dev,staging,prod}.tfvars`.

### Manual apply

Prereqs: `az login` (or set `ARM_SUBSCRIPTION_ID` / SP env vars), Terraform ≥ 1.7.

```bash
cd infrastructure/azure
terraform init -backend-config=environments/dev.backend.hcl   # or -backend=false for a throwaway
terraform apply -var-file=environments/dev.tfvars
terraform output                       # frontend_url, storage account, Front Door names
```

Publish the SPA (build once, upload to `$web`, purge the CDN):

```bash
cd ../../frontend
npm run build

ACCT=$(terraform -chdir=../infrastructure/azure output -raw frontend_storage_account)
PROFILE=$(terraform -chdir=../infrastructure/azure output -raw frontend_frontdoor_profile)
ENDPOINT=$(terraform -chdir=../infrastructure/azure output -raw frontend_frontdoor_endpoint)
RG=$(terraform -chdir=../infrastructure/azure output -raw resource_group)

# Hashed assets: long cache. index.html: no-cache (upload last).
az storage blob upload-batch \
  --account-name "$ACCT" --auth-mode login \
  --destination '$web' --source dist \
  --content-cache 'public, max-age=31536000, immutable' \
  --overwrite

az storage blob upload \
  --account-name "$ACCT" --auth-mode login \
  --container-name '$web' --name index.html --file dist/index.html \
  --content-cache 'no-cache, no-store, must-revalidate' --overwrite

# Purge the edge so the new index.html propagates immediately.
az afd endpoint purge \
  --resource-group "$RG" --profile-name "$PROFILE" \
  --endpoint-name "$ENDPOINT" --content-paths '/index.html'
```

The build (`frontend/dist/`) is identical to the AWS deploy — same artifact,
different target.

### Cloud-selectable CI deploy

`.github/workflows/frontend-deploy.yml` deploys the frontend to **either** cloud,
chosen by a pipeline variable:

- **Actions → "Frontend Deploy (AWS or Azure)" → Run workflow →** pick
  `cloud = aws | azure` and an environment. Same `dist/` → S3+CloudFront or
  Blob+Front Door. Required secrets are listed at the top of that workflow
  (`AZURE_*` come from `terraform -chdir=infrastructure/azure output`).

## Data + messaging layer (Phase 2)

Seven modules mirror the AWS data/messaging stack. Each output maps 1:1 to an adapter env var;
the Phase-3 Container Apps module wires them (secrets via Key Vault references). All provision
from one `terraform apply` on the root.

| Module | Azure resource | Mirrors AWS | Outputs → env |
|---|---|---|---|
| `networking` | VNet + 3 subnets (container-apps + postgres delegated, private-endpoints) | `networking` (VPC) | subnet ids (consumed by postgres + Phase-3 compute) |
| `postgres` | PostgreSQL Flexible Server (VNet-integrated, private DNS) + DB `logistics` | `aurora` | `DATABASE_HOST/PORT/NAME/USER/PASSWORD` (password also in Key Vault `postgres-admin-password`) |
| `redis` | Azure Cache for Redis (Basic C0 default) | `elasticache` | `REDIS_HOST` / `REDIS_PORT` (6380, TLS) / `REDIS_PASSWORD` |
| `servicebus` | Service Bus namespace + queues sms/whatsapp/email/metering (built-in DLQ) | `sqs` | `AZURE_SERVICE_BUS_CONNECTION_STRING` + `SQS_*_QUEUE_URL` (queue names) |
| `eventgrid` | Event Grid custom topic | `eventbridge` | `AZURE_EVENT_GRID_ENDPOINT` / `AZURE_EVENT_GRID_KEY` |
| `acs` | Communication Services + Email (Azure-managed domain) | `ses` | `AZURE_COMMUNICATION_CONNECTION_STRING` + sender address |
| `monitoring` | Log Analytics workspace + Application Insights | `monitoring` | `APPLICATIONINSIGHTS_CONNECTION_STRING`; workspace id (Container Apps log sink) |

**Two runtime portability fixes (done in Phase 3, keep AWS unchanged):**
- `shared/db.py` honours a generic `DATABASE_SSLMODE` (Container Apps sets `require` for the
  Flexible Server, which mandates TLS) — falls back to the old `DB_SECRET_ARN`-based default.
- `shared/distributed_cache.py` honours `REDIS_PASSWORD` + `REDIS_SSL=true` (Azure Redis needs
  both) — defaults to no-auth plain TCP, so AWS/local is unchanged.

Read the wired values after an apply with `terraform output` (sensitive ones via
`terraform output -raw <name>`), e.g. `terraform output -raw database_password`.

## Compute layer (Phase 3)

`modules/container_app` is the Lambda-free compute plane (ADR-005). One image, four workload
shapes, each the entrypoint arg from the Dockerfile:

| Resource | Workload | Replaces (AWS) |
|---|---|---|
| `azurerm_container_app.api` | `api` — gunicorn, external HTTPS ingress on :8080 | API Gateway + HTTP Lambdas |
| `azurerm_container_app.worker["*"]` | `worker --queue <k>` — one per queue, **KEDA**-scaled 0→N on Service Bus depth | SQS → consumer Lambdas |
| `azurerm_container_app_job.scheduled["*"]` | `job --job <n>` — 7 cron jobs (schedules mirror the EventBridge rules) | EventBridge → scheduled Lambdas |
| `azurerm_container_app_job.migrate` | `migrate` — manual trigger (alembic) | the migrate Lambda |

Plus an **ACR** (private registry, image pulled via the app's managed identity) and the
**Container Apps Environment** (VNet-integrated on the `container-apps` subnet, logs → Log
Analytics). The root creates one **user-assigned managed identity** (granted ACR pull + Key
Vault wrap/unwrap + secret read) shared by all apps/jobs; `CLOUD_PROVIDER=azure` plus every
Phase-2 output is injected as env (secrets as Container App secrets).

**Bootstrap / image flow (chicken-and-egg):** the ACR image doesn't exist on the first apply, so
`container_image` defaults to a public placeholder and Terraform **ignores image drift**. The
Phase-5 deploy workflow builds + pushes the real image to ACR and runs
`az containerapp update --image` (and the migrate job). Sequence for a manual first bring-up:

```bash
terraform apply                       # provisions ACR + env + apps (placeholder image)
az acr login -n "$(terraform output -raw acr_name)"
docker build -t "$(terraform output -raw acr_login_server)/shipx-backend:latest" .
docker push "$(terraform output -raw acr_login_server)/shipx-backend:latest"
az containerapp job start -g <rg> -n "$(terraform output -raw migrate_job_name)"   # migrate
az containerapp update -g <rg> -n "$(terraform output -raw api_app_name)" \
  --image "$(terraform output -raw acr_login_server)/shipx-backend:latest"
curl "$(terraform output -raw api_url)/health"                                      # 200
```

**`deploy-azure.yml`** automates all of this on every push (gated `DEPLOY_CLOUD=azure`) and runs
`terraform apply` as its **first step**, so you don't have to apply infra separately — the deploy
reconciles infra + state, then builds + pushes the image to ACR, runs the migration job, rolls the
Container Apps, and smoke-tests. The manual sequence above is only for a local/first bring-up before
CI is wired. `terraform-azure.yml` is plan-only (infra review); the deploy owns the apply, so a
single workflow owns the state.

## Running the full app on Azure — auth is the deciding piece

Compute + data + frontend hosting are all on Azure. **Auth** is the one thing
with a choice, because the SPA logs in via **Cognito** today
(`frontend/src/auth/CognitoClient.ts`) — so a working end-to-end login needs one of:

**Path A — Cognito bridge (fastest; no frontend change, no Entra tenant).** Keep the
existing AWS Cognito pool as the identity authority; the Azure-hosted API validates
Cognito JWTs. Everything else runs on Azure. Set on the Azure API (Container Apps env):

```
AUTH_PROVIDER   = aws                                   # use the Cognito claims mapper even though CLOUD_PROVIDER=azure
OIDC_JWKS_URL   = https://cognito-idp.<region>.amazonaws.com/<pool-id>/.well-known/jwks.json
OIDC_AUDIENCE   = <cognito app client id>
```
and build the SPA with `VITE_API_BASE_URL=<azure api_url>` + the **existing** `VITE_COGNITO_*`.
`AUTH_PROVIDER` defaults to `CLOUD_PROVIDER`, so this is the only override needed. Result: the
full app runs on Azure with auth federated to Cognito (the ADR-004 dual-run posture) — no Entra
tenant, no frontend rewrite.

**Path B — native Entra (no AWS dependency).** The SPA has an Entra login path
(`frontend/src/auth/EntraClient.ts`, selected by `VITE_AUTH_PROVIDER=entra`) using the OAuth2 ROPC
grant, so the existing email/password login works against Entra for **local accounts** — no
redirect-UX rewrite. Set up the Entra tenant (below), point the API's `OIDC_*` at Entra, and migrate
users. Backend auth is already native (`auth_provider="azure"` default → Entra verify + claims
mapper). Frontend build env for Azure:

```
VITE_AUTH_PROVIDER = entra
VITE_API_BASE_URL  = <azure api_url>
```

> **Login is proxied through the backend (don't send ROPC from the browser).** Entra's token
> endpoint returns **no CORS header for the password grant**, so a browser `fetch` to it is blocked
> (`No 'Access-Control-Allow-Origin'`). `EntraClient.signIn` therefore calls `POST /v1/auth/login`,
> which runs the ROPC exchange server-side. The `VITE_ENTRA_*` build vars are **no longer needed on
> the frontend** — the backend container holds `ENTRA_TOKEN_ENDPOINT`/`ENTRA_CLIENT_ID`/`ENTRA_SCOPE`
> (set via the `entra_token_endpoint`/`entra_client_id`/`entra_scope` tfvars). If you deployed an
> older build and login fails with that CORS error, redeploy the SPA from this revision.

> **Users log in with their email**, not the managed-domain UPN. The backend maps
> `alex@gmail.com` → `alex_gmail.com@<tenant>.onmicrosoft.com` (`email_to_upn` + `ENTRA_USER_DOMAIN`,
> the `entra_user_domain` tfvar) before the ROPC call. Set `entra_user_domain` to your tenant's
> initial domain (e.g. `ifexalexoutlook.onmicrosoft.com`); if it's unset, users must type the full
> UPN (no breakage, just no email convenience). Idempotent — a full UPN still works.

Reload-persistence works on Entra too: the backend httpOnly-cookie refresh (`services/auth`) is
provider-aware — `AUTH_PROVIDER=azure` exchanges the cookie via `entra_refresh.py` (OAuth2
refresh-token grant), so a page reload silently restores the session exactly as on Cognito.

Caveat (validate against your tenant): ROPC covers local accounts only (no social/MFA — swap to
an MSAL redirect flow behind the same `authClient` seam if those are needed).

Recommended: **Path A to get it live instantly**; Path B for the AWS-free end-state.

### Entra tenant setup (for Path B)

The identity adapters are code (`shared/providers/azure/entra.py` +
`entra_claims.py`) and the bulk migration is `scripts/migrate_users_to_entra.py`, but the Entra
**tenant** itself is set up by hand (an External ID / CIAM tenant can't be fully Terraformed). One
time, per the ADR-004 decision (External ID + roles as security groups):

1. **Create the External ID tenant** (portal) and an **app registration** for the SPA + API.
   Note the tenant id, app (client) id, and the token/issuer URLs.
2. **Graph permissions** for the deploy/migration identity (the one `migrate_users_to_entra.py`
   and the Container Apps managed identity use): application permissions **User.ReadWrite.All** +
   **Group.ReadWrite.All**, admin-consented.
3. **Token config so the API can authorize.** On CIAM the **claims provider** (see "Token claims on
   CIAM" below) is what puts `tenant_id` + `role` into the token — that's the path this deployment
   uses, and it needs no claims-mapping policy. The backend's `EntraClaimsMapper` is deliberately
   tolerant of three shapes, so it also works if you feed claims another way:
   - **tenant_id + role claims** (what the claims provider injects; default claim names `tenant_id` /
     `role`, overridable via `ENTRA_TENANT_ID_CLAIM` / `ENTRA_ROLE_CLAIM`). The mapper synthesizes the
     canonical `platform_admin` / `{tenant_id}:{role}` group from them.
   - **Group object ids.** Set `groupMembershipClaims=SecurityGroup` (token carries group GUIDs)
     and map the ones that matter with `ENTRA_PLATFORM_ADMIN_GROUP_ID` / `ENTRA_GROUP_ID_MAP`.
   - **Display names.** If you *do* have on-prem-synced groups or a claims-mapping policy emitting
     `{tenant_id}:{role}` names, they pass through unchanged.

   > **Fastest path — one script.** `scripts/setup_entra_platform_admin.sh` does the SPA app
   > registration (public client + OIDC consent), the security-group claim, the `platform_admin`
   > group, and the admin user in one idempotent run, then prints the exact backend/frontend env.
   > The platform admin resolves from its group GUID alone (no claims provider needed). Run it
   > instead of steps 1 + 3 for the platform admin:
   > ```bash
   > ADMIN_EMAIL=you@example.com ./scripts/setup_entra_platform_admin.sh
   > ```
4. **Wire the API** (Container Apps env / tfvars): `OIDC_JWKS_URL` + `OIDC_AUDIENCE` →
   the Entra app's JWKS + client id (the authorizer verifies RS256 against these);
   `ENTRA_USER_DOMAIN` → the tenant's managed domain (e.g. `yourtenant.onmicrosoft.com`).
5. **Migrate users** (Cognito can't export password hashes, so re-provision with a forced reset):
   ```bash
   CLOUD_PROVIDER=azure ENTRA_USER_DOMAIN=yourtenant.onmicrosoft.com \
     python scripts/migrate_users_to_entra.py --dry-run     # preview
   CLOUD_PROVIDER=azure ENTRA_USER_DOMAIN=yourtenant.onmicrosoft.com \
     python scripts/migrate_users_to_entra.py               # provision + reconcile groups
   ```
   Idempotent — re-runs skip existing users but still reconcile their groups.

Cutover is a config flip (`DEPLOY_CLOUD`/`CLOUD_PROVIDER` + the `OIDC_*` env); rollback is flipping
them back. AWS continues to use Cognito unchanged throughout.

### Token claims on CIAM — the custom authentication extension (all roles)

Entra **External ID (CIAM, `*.ciamlogin.com`) does not emit app-manifest `optionalClaims` for
directory extensions** — a real token carries only the `groups` object ids. The platform admin
survives this (its `tenant_id=PLATFORM` is derived from `platform_admin` membership), but
**tenant-scoped users (customer / staff / tenant_admin) need a real `tenant_id` claim that can't be
derived.** The fix is a **custom authentication extension** (OnTokenIssuanceStart claims provider)
that injects `tenant_id` + `role` into every token at sign-in.

- **Compute (Terraformed):** the claims provider runs as its **own Container App** (`*-entra-claims`)
  on the **shared backend image** via the `claims` entrypoint — in the `container_app` module, not a
  separate Function. This is deliberate: App Service (Functions) VM quota is **0** on this
  subscription (both Y1 and B1), while Container Apps has quota; it's always-on (`claims_min_replicas`
  defaults to 1) because Entra's extension call times out ~2s. Code is `services/entra_token_claims/`
  (`app.py` Flask WSGI → reads the user's `tenant_id` / `role` from **`tenant_user` in the ShipX DB**,
  keyed on the Entra `oid` against the globally-unique `cognito_sub`, and returns them as the
  `tenant_id` / `role` claims). **No Microsoft Graph permission** is required (email isn't a safe key
  — it's unique only per tenant — so the oid/`cognito_sub` is used). The deploy's
  `az containerapp update --image` loop rolls it like any other app — no dedicated step. The claims
  config is passed via the `entra_claims_*` tfvars.
- **Provisioning:** `scripts/migrate_users_to_entra.py` stamps each provisioned user's Entra `oid`
  into `tenant_user.cognito_sub`, which is how the claims provider resolves them. No directory
  extension attributes are involved.
- **Manual (Graph / portal — not Terraformable; required before go-live — the authoritative
  checklist is `docs/runbook.md` → "Azure deployment — required one-time setup"):** register the
  custom authentication extension against the endpoint (`terraform output -raw entra_claims_endpoint_url`)
  and bind it to the SPA app's token-issuance event — `customAuthenticationExtensions` +
  `authenticationEventListeners` via Graph (`/beta`) or the portal — mapping the returned `tenant_id`
  + `role` into the token. This is the one step with no azurerm/azuread resource.
- **Backend env it enables:** with the extension live, every token carries `tenant_id` + `role`, so
  the `EntraClaimsMapper` synthesize path resolves **all** roles — `ENTRA_TENANT_ID_CLAIM` /
  `ENTRA_ROLE_CLAIM` stay at their `tenant_id` / `role` defaults (matching `OUT_TENANT_CLAIM` /
  `OUT_ROLE_CLAIM`).

## Replica roadmap (toward a full AWS→Azure mirror)

The goal is a complete Azure mirror of the AWS stack, deployable instead of AWS.
Built in order of tractability (infra-only first; app-coupled pieces last):

| # | AWS module | Azure target | Depends on | Status |
|---|---|---|---|---|
| 1 | S3 + CloudFront | Blob + Front Door Standard | — | ✅ done |
| 2 | KMS + Secrets Manager | Key Vault | — | ✅ adapters + Terraform |
| 3 | ElastiCache | Azure Cache for Redis (`modules/redis`) | — | ✅ Terraform (client TLS/pwd in Phase 3) |
| 4 | Aurora Serverless v2 | PostgreSQL Flexible Server (`modules/postgres`) | networking | ✅ Terraform (client sslmode in Phase 3) |
| 5 | VPC + endpoints | VNet + delegated subnets (`modules/networking`) | — | ✅ Terraform |
| 6 | SQS / EventBridge / SES | Service Bus / Event Grid / Communication Services | — | ✅ adapters + Terraform (`modules/{servicebus,eventgrid,acs}`) |
| 7 | Monitoring (CloudWatch) | Log Analytics + App Insights (`modules/monitoring`) | — | ✅ workspace + APM (alert rules in Phase 3) |
| 8 | Lambda + API Gateway | **Container Apps** (`modules/container_app`) | backend containerized | ✅ Terraform (CI pushes image — Phase 5) |
| 9 | Cognito | Entra External ID (`shared/providers/azure/entra*`) | app claim-mapping behind an interface | 🔨 adapters + migration done; tenant setup manual |

**Application portability (already landed, cloud-agnostic — not Terraform):** the
backend now uses a **ports-and-adapters layer** (`shared/providers/`) so business
logic never imports a cloud SDK. six ports already have AWS adapters and are selected by `CLOUD_PROVIDER`:
`KeyProvider` (crypto → `aws/kms.py`), `StorageProvider` (object storage →
`aws/s3.py`), `SecretsProvider` (→ `aws/secrets.py`), `EventProvider` (domain
events → `aws/eventbridge.py`), `QueueProvider` (async messages → `aws/sqs.py`),
and `EmailProvider` (transactional email → `aws/ses.py`). Presigned uploads use a
**cloud-neutral PUT contract** that both S3 and Azure Blob satisfy. The matching
Azure adapters (`azure/{keyvault,blob,keyvault_secrets,eventgrid,servicebus,acs_email}.py`)
are built alongside their Terraform modules (#2, #6). See
`docs/project docs/02_shared_utilities.md` → "shared/providers/". X-Ray tracing
is likewise behind a shim (`shared/observability.py::init_tracing`, a no-op off
AWS). The one remaining boto3 touchpoint is **Cognito** (auth), the stickiest —
token claims + user migration to Entra, not a clean adapter swap.

**Key dependency:** #8 (compute) needs the backend packaged as a **container** —
**done** (ADR-005). The repo-root `Dockerfile` builds one image whose entrypoint
(`docker-entrypoint.sh`) selects the workload: `api` (gunicorn → `services/http_app`),
`worker --queue <k>` (Service Bus consumer → `services/queue_worker`), `job --job <n>`
(cron → `services/scheduled/run.py`), or `migrate`. The HTTP app verifies real tokens
in-process via `shared/auth_verify.py` (the same code the AWS authorizer runs) and routes
via `shared/http_routing.py` (shared with the dev server + mirrored by API Gateway). What
remains for #8 is the **Terraform** — Container Apps Environment + ACR + the three
workloads + env wiring (`CLOUD_PROVIDER=azure` + the adapter connection strings). #9 (auth)
is the stickiest (token claims + user migration); the IdP is behind the `IdentityProvider`
port already (ADR-004).

### Backend container (local build/run)

```bash
docker build -t shipx-backend .
docker run -p 8080:8080 -e CLOUD_PROVIDER=azure shipx-backend api   # → GET /health 200
docker run shipx-backend worker --queue sms                          # Service Bus consumer
docker run shipx-backend job --job release_expiry                    # one cron job, then exit
```

gunicorn runs **processes, 1 thread each** (the `shared/db.py` connection singleton is not
thread-safe — same reason the dev server is single-threaded). Scale with replicas, not threads.

## Local testing (Azurite — the Azure "local stack")

There's no single LocalStack-for-Azure, but the pieces with official emulators are
wired into the same dev stack as `moto`:

```bash
docker compose -f docker-compose.local.yml up -d azurite   # Blob/Queue/Table on :10000-2
```

The **pytest suite is fully mocked** and never touches Azurite or a real cloud —
`tests/unit/test_azure_blob_provider.py` uses an in-memory SDK fake. Azurite (and
a real account) are exercised only by **`scripts/azure_smoke.py`**, which does
live SAS PUT/GET round-trips when pointed at either (via
`AZURE_STORAGE_CONNECTION_STRING`). The Azure SDKs are the `azure` extra in
`pyproject.toml` — install with `uv sync --extra azure`.

What has a local emulator: Blob/Queue/Table (**Azurite**), Postgres (plain
Postgres, already in the stack), Functions (`func` core tools). What does **not**
and needs a free test resource/tenant: Key Vault, Event Grid, ACS email, and —
critically — **Entra** (identity). See ADR-004.

## Backend adapter targets — provision + verify against real Azure

The `storage` and `keyvault` modules create the real resources behind
`shared/providers/azure/{blob,keyvault,keyvault_secrets}.py`. Sized to free/cheap
tiers (Standard LRS storage; Standard Key Vault — per-op pennies). Provision and
then run the **same adapter tests** against the real resources (no emulator):

```bash
az login                      # DefaultAzureCredential + Terraform auth
cd infrastructure/azure
terraform init
# Just the adapter targets (skips Front Door):
terraform apply -target=module.storage -target=module.keyvault

# Point the adapters at the real resources:
export AZURE_STORAGE_CONNECTION_STRING=$(terraform output -raw storage_connection_string)
export BLOB_CONTAINER_NAME=$(terraform output -raw blob_container_name)
export AZURE_KEY_VAULT_URL=$(terraform output -raw key_vault_url)
export ENCRYPTION_KEY_VAULT_KEY_ID=$(terraform output -raw encryption_key_vault_key_id)

# Verify against YOUR Azure — the pytest suite is fully mocked and never calls a
# real cloud, so real-resource proof is this standalone script (not pytest):
cd ../..
python scripts/azure_smoke.py
```

`scripts/azure_smoke.py` runs whatever its env is configured for and prints each
real call: a live SAS **PUT→201** then **GET→200** against your storage account,
real RSA **wrap/unwrap** against your Key Vault key, and a **secret read**
(`shipx-smoke-secret` → `ok`). Checks whose env vars are absent are skipped, not
failed. Tear down with `terraform destroy` when done (the test vault has
purge-protection off so it fully deletes).

## Notes
- Storage account names are globally unique, lowercase, ≤24 chars — the module
  derives one from the prefix + a random suffix.
- `.terraform/` (downloaded providers) is gitignored; `.terraform.lock.hcl`
  (provider pins) is committed.
- Cost at 300 MAU ≈ the figures in `docs/azure_cost_model.md` (Front Door
  Standard base ~$35/mo; add ~$25 for Cloudflare WAF when you want it).
