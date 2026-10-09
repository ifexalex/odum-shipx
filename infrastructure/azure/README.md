# ShipX — Azure stack (portability target)

This is the **Azure** deployment of ShipX, kept alongside the AWS stack in `../aws`
so the app can be deployed to either cloud. You run **one** cloud at a time (see
the cloud-portability notes in `docs/runbook.md`); this stack lets you move to
Azure (e.g. to use Founders Hub credits) without re-architecting.

**Status:** incremental build-out. Implemented so far:

| Piece | AWS (`../aws`) | Azure (here) | Status |
|---|---|---|---|
| Frontend hosting / CDN | S3 + CloudFront | **Blob static website + Front Door Standard** | ✅ |
| WAF / DDoS | CloudFront WAF | Cloudflare (recommended) / Front Door Premium | ⏳ |
| Backend compute | Lambda | **Container Apps** (`Dockerfile` — api/worker/job) | 🔨 container built; Terraform pending |
| Networking | VPC + subnets | **VNet + delegated subnets (`modules/networking`)** | ✅ Terraform |
| Object storage | S3 | **Blob (`BlobStorageProvider`)** — adapter + `modules/storage` Terraform; Azurite- & real-account-testable | ✅ |
| Queue | SQS | **Service Bus (`ServiceBusQueueProvider`)** — adapter + `modules/servicebus` Terraform | ✅ |
| Database | Aurora Serverless v2 | **PostgreSQL Flexible Server (`modules/postgres`)** — VNet-integrated, private | ✅ Terraform |
| Cache | ElastiCache | **Azure Cache for Redis (`modules/redis`)** | ✅ Terraform |
| Auth | Cognito | Entra External ID | ⏳ |
| Events | EventBridge | **Event Grid (`EventGridProvider`)** — adapter + `modules/eventgrid` Terraform | ✅ |
| Email | SES | **ACS Email (`AcsEmailProvider`)** — adapter + `modules/acs` Terraform | ✅ |
| Monitoring | CloudWatch | **Log Analytics + App Insights (`modules/monitoring`)** | ✅ Terraform |
| Secrets / crypto | Secrets Manager + KMS | **Key Vault (`KeyVaultSecretsProvider` + `KeyVaultKeyProvider`)** — adapters + `modules/keyvault` Terraform; real-account-verifiable | 🔨 |

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

**Two portability notes for Phase 3 (runtime config, not provisioning):**
- **Postgres requires TLS** (Flexible Server enforces `require_secure_transport`). `shared/db.py`
  currently keys `sslmode=require` on the AWS-specific `DB_SECRET_ARN`; Phase 3 adds a generic
  `DATABASE_SSLMODE` override so Azure sets `require` without that AWS env.
- **Redis Basic/Standard requires TLS + an access key** (no VNet injection below Premium).
  `shared/distributed_cache.py` currently reads only `REDIS_HOST`/`REDIS_PORT`; Phase 3 adds
  `REDIS_PASSWORD` + `REDIS_SSL` support (defaults keep AWS unchanged).

Read the wired values after an apply with `terraform output` (sensitive ones via
`terraform output -raw <name>`), e.g. `terraform output -raw database_password`.

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
| 8 | Lambda + API Gateway | **Container Apps** (ingress = API) | **backend containerized** | 🔨 image done (ADR-005); Terraform pending |
| 9 | Cognito | Entra External ID | app claim-mapping behind an interface | ⏳ |

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
