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
| Backend compute | Lambda | Container Apps / Functions | ⏳ |
| Database | Aurora Serverless v2 | PostgreSQL Flexible Server | ⏳ |
| Cache | ElastiCache | Azure Cache for Redis | ⏳ |
| Auth | Cognito | Entra External ID | ⏳ |
| Queues / events / email | SQS / EventBridge / SES | Service Bus / Event Grid / ACS | ⏳ |
| Secrets / crypto | Secrets Manager + KMS | Key Vault | ⏳ |

## Frontend module (what's here now)

`modules/frontend` = Blob storage `$web` static site behind **Front Door
Standard** (CDN, HTTPS with a free managed cert on the `*.azurefd.net` endpoint,
SPA 404→index fallback, gzip, and a security-headers rule set mirroring the AWS
CloudFront response-headers policy). Front Door **Standard** has no WAF — add
Cloudflare at the edge (cheap, cloud-neutral) or move to Front Door Premium
later. Custom domain is a follow-up; the default endpoint gives a working HTTPS
URL immediately.

## Deploy

Prereqs: `az login` (or set `ARM_SUBSCRIPTION_ID` / SP env vars), Terraform ≥ 1.7.

```bash
cd infrastructure/azure
terraform init
terraform apply -var 'environment=prod' -var 'api_base_url=https://<your-api-host>'
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

## Replica roadmap (toward a full AWS→Azure mirror)

The goal is a complete Azure mirror of the AWS stack, deployable instead of AWS.
Built in order of tractability (infra-only first; app-coupled pieces last):

| # | AWS module | Azure target | Depends on | Status |
|---|---|---|---|---|
| 1 | S3 + CloudFront | Blob + Front Door Standard | — | ✅ done |
| 2 | KMS + Secrets Manager | Key Vault | — | 🔨 app side done |
| 3 | ElastiCache | Azure Cache for Redis | networking | ⏳ |
| 4 | Aurora Serverless v2 | PostgreSQL Flexible Server | networking | ⏳ |
| 5 | VPC + endpoints | VNet + subnets + Private/Service Endpoints | — | ⏳ |
| 6 | SQS / EventBridge / SES | Service Bus / Event Grid / Communication Services | — | 🔨 app side done (ports in place); Azure adapters + Terraform pending |
| 7 | Monitoring (CloudWatch) | Log Analytics + App Insights + alerts | — | ⏳ |
| 8 | Lambda + API Gateway | **Container Apps** (ingress = API) | **backend containerized** | ⏳ |
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

**Key dependency:** #8 (compute) needs the backend packaged as a **container**
(it already runs under Flask in `scripts/local_server.py`, so this is a wrapper,
not a rewrite). Containerizing is what lets the same image run on Azure Container
Apps *and* AWS Fargate — the move that makes the backend as portable as the
frontend already is. #9 (auth) is the stickiest (token claims + user migration);
keep the IdP behind an interface so it's swappable.

## Notes
- Storage account names are globally unique, lowercase, ≤24 chars — the module
  derives one from the prefix + a random suffix.
- `.terraform/` (downloaded providers) is gitignored; `.terraform.lock.hcl`
  (provider pins) is committed.
- Cost at 300 MAU ≈ the figures in `docs/azure_cost_model.md` (Front Door
  Standard base ~$35/mo; add ~$25 for Cloudflare WAF when you want it).
