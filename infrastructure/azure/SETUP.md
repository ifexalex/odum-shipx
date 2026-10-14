# ShipX on Azure — one-time setup (fresh subscription)

End-to-end bootstrap for deploying ShipX to a brand-new Azure subscription. Follow
top to bottom once; after that, `deploy-azure.yml` (backend) and
`frontend-deploy.yml` (SPA) run everything automatically.

## Roles / who does what

- **You (Owner / admin)** run the privileged, one-time steps below (subscription
  upgrade, resource providers, state account, the OIDC app + its role grants,
  GitHub config, Entra tenant). These need Owner — they can't be Terraformed,
  because you can't bootstrap an identity's permissions with that same identity.
- **The CI deploy identity stays Contributor-only.** Terraform and the deploy
  workflows run as it. It never needs User Access Administrator: the pipelines
  avoid RBAC role assignments by using **ACR admin creds** and **storage account
  keys** (`listKeys`, which Contributor already allows) instead. So the only
  roles you grant it are **Contributor** + **Storage Blob Data Contributor on the
  tfstate RG** (state access). Nothing else.

Prerequisites: `az` CLI logged in as an Owner (`az login`), `gh` CLI (or the
GitHub UI), and the repo cloned.

---

## 0. Set your variables (once, in this shell)

```bash
export SUB=$(az account show --query id -o tsv)
export TENANT=$(az account show --query tenantId -o tsv)
export LOCATION=northeurope
export SUFFIX=$(openssl rand -hex 3)          # for globally-unique names
export REPO=ifexalex/odum-shipx               # owner/repo
export TFSTATE_RG=shipx-tfstate-rg
export TFSTATE_SA=shipxtfstate${SUFFIX}       # 3–24 lowercase alnum, globally unique
echo "SUB=$SUB TENANT=$TENANT TFSTATE_SA=$TFSTATE_SA"
```

## 1. Upgrade the subscription to Pay-As-You-Go

Azure **Free Trial / Student forbids Front Door** (and blocks some SKUs) *regardless
of credit balance* — it's a subscription-type policy. In the portal:
**Subscriptions → (your sub) → Upgrade**. This keeps any remaining credit. Skip only
if you'll run with `enable_frontend=false` + `enable_redis=false` forever.

## 2. Register resource providers

The apply fails with `... is not registered for the Microsoft.X resource provider`
otherwise. One-time per subscription (async — a few minutes):

```bash
for rp in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL \
          Microsoft.ServiceBus Microsoft.EventGrid Microsoft.Communication \
          Microsoft.KeyVault Microsoft.Storage Microsoft.Network \
          Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.Insights \
          Microsoft.Cache Microsoft.Cdn; do
  az provider register -n "$rp"
done
az provider show -n Microsoft.App --query registrationState -o tsv   # wait for "Registered"
```
(`Microsoft.Cache`/`Microsoft.Cdn` are only needed if `enable_redis`/`enable_frontend` are true.)

## 3. Terraform state backend

```bash
az group create -n "$TFSTATE_RG" -l "$LOCATION"
az storage account create -n "$TFSTATE_SA" -g "$TFSTATE_RG" -l "$LOCATION" \
  --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false
az storage container create -n tfstate --account-name "$TFSTATE_SA" --auth-mode login
```
Set `storage_account_name = "<$TFSTATE_SA>"` in **all four**
`infrastructure/azure/environments/{dev,staging,prod,demo}.backend.hcl`, commit, push.

## 4. OIDC deploy identity (Contributor-only)

An Entra app registration + a federated credential per GitHub Environment, so CI
authenticates with no stored secret.

```bash
APP_ID=$(az ad app create --display-name shipx-github-deploy --query appId -o tsv)
az ad sp create --id "$APP_ID"

# Federated credential per environment (subject must match exactly).
for env in dev staging prod demo; do
  az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"gh-$env\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:${REPO}:environment:$env\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
done

# The ONLY two role grants the deploy identity ever needs:
az role assignment create --assignee "$APP_ID" --role Contributor \
  --scope "/subscriptions/$SUB"
az role assignment create --assignee "$APP_ID" --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/$TFSTATE_RG"
```

> Deliberately **no** User Access Administrator. That's why the stack uses ACR
> admin creds (`grant_acr_pull=false`) and storage-key uploads (`listKeys`) instead
> of RBAC role assignments — so a Contributor identity is sufficient. Scope
> Contributor to a resource group instead of the whole subscription for tighter
> least-privilege if you prefer.

## 5. GitHub configuration

```bash
# One repo variable selects the cloud (unset/aws => AWS; azure => Azure).
gh variable set DEPLOY_CLOUD --body azure --repo "$REPO"

# Per-environment OIDC secrets (dev/staging/prod/demo).
for env in dev staging prod demo; do
  gh api -X PUT "repos/$REPO/environments/$env" >/dev/null
  gh secret set AZURE_CLIENT_ID       --env "$env" --repo "$REPO" --body "$APP_ID"
  gh secret set AZURE_TENANT_ID       --env "$env" --repo "$REPO" --body "$TENANT"
  gh secret set AZURE_SUBSCRIPTION_ID --env "$env" --repo "$REPO" --body "$SUB"
done
```
Frontend build secrets (per env, for `frontend-deploy.yml` — `VITE_API_BASE_URL`
is read from Terraform on Azure, so you only need the auth ones):
`VITE_AUTH_PROVIDER`, and either `VITE_COGNITO_USER_POOL_ID`/`VITE_COGNITO_CLIENT_ID`
(Cognito) or `VITE_ENTRA_TOKEN_ENDPOINT`/`VITE_ENTRA_CLIENT_ID` (Entra).

## 6. Auth

Pick one (see the README "Running the full app on Azure" for detail):

- **Cognito bridge** (fastest; no Entra tenant): backend tfvars `auth_provider="aws"`,
  `oidc_jwks_url`/`oidc_audience` → your existing Cognito pool; frontend
  `VITE_AUTH_PROVIDER=cognito` + `VITE_COGNITO_*`.
- **Native Entra**: create an Entra External ID tenant + app registration (local
  accounts), grant it MS Graph `User.ReadWrite.All` + `Group.ReadWrite.All`; carry
  the ShipX tenant id + role into the token as `tenant_id`/`role` optional claims
  (extension attributes) — the backend's `EntraClaimsMapper` synthesizes the
  canonical role group from them, so no claims-mapping policy is needed (set
  `groupMembershipClaims=SecurityGroup` + `ENTRA_PLATFORM_ADMIN_GROUP_ID` if you
  prefer the group route). Backend `auth_provider="azure"` + `oidc_jwks_url`/
  `oidc_audience` + `entra_token_endpoint` + `entra_client_id` + `entra_user_domain`
  (+ `ENTRA_TENANT_ID_CLAIM`/`ENTRA_ROLE_CLAIM` if you renamed the claims); frontend
  `VITE_AUTH_PROVIDER=entra` + `VITE_ENTRA_*`; then run
  `scripts/migrate_users_to_entra.py`. For the first platform admin, run
  `scripts/setup_entra_platform_admin.sh` (does the app registration, claims, group,
  and user in one idempotent pass and prints the env wiring). For **tenant-scoped
  users on CIAM** (customer/staff/tenant_admin, whose tenant id can't be derived),
  deploy the custom authentication extension — a Container App on the shared image
  (`services/entra_token_claims/` via the `claims` entrypoint, in `modules/container_app`,
  reading tenant_id/role from the ShipX DB by the Entra oid — no Graph permission) —
  then run **`./scripts/setup_entra_claims_provider.sh`** (idempotent) to bind it to the SPA app's
  token-issuance event and add the `/auth/callback` redirect URI; it injects `tenant_id`+`role` into
  every token so all roles resolve. See `docs/runbook.md` → "Azure deployment — required one-time setup".

## 7. First deploy

```bash
# Backend: infra apply + image build/push + migrate + roll (runs terraform apply first).
gh workflow run deploy-azure.yml -f environment=dev --repo "$REPO"
#   (or push to main / open a PR per the promotion model)

# Frontend SPA: build + upload to $web + Front Door purge.
gh workflow run frontend-deploy.yml -f cloud=azure -f environment=dev --repo "$REPO"
```

Verify:
```bash
cd infrastructure/azure && terraform init -backend-config=environments/dev.backend.hcl
API=$(terraform output -raw api_url);  FE=$(terraform output -raw frontend_url)
curl "$API/health"                                   # {"status":"ok",...}
curl -o /dev/null -w "%{http_code}\n" "$API/v1/billing"   # 401
echo "SPA: $FE"                                      # open in a browser
```

---

## Troubleshooting (gotchas this setup already handles)

| Symptom | Cause / fix |
|---|---|
| `... not registered for the Microsoft.X resource provider` | Run step 2's `az provider register` loop. |
| `Free Trial ... forbidden for Azure Frontdoor` (400) | Subscription type — upgrade (step 1), or set `enable_frontend=false` in the env tfvars. |
| `Azure Cache for Redis is retiring` (400) | Classic Redis is blocked — `enable_redis=false` (cache falls back to DB). |
| ACR role assignment `AuthorizationFailed` (403) | Expected with Contributor-only — the stack uses ACR admin creds (`grant_acr_pull=false`), not a role. |
| Front Door `404 WebContentNotFound` | The SPA isn't uploaded yet — run `frontend-deploy.yml` (cloud=azure). |
| `az storage blob upload ... do not have the required permissions` | You're on `--auth-mode login`; the workflow uses `--account-key` via `listKeys` (Contributor) — re-run the updated workflow. |
| `Service Bus "name" cannot end with -sb` | Fixed in code (namespace is `-bus`). |
| Migration job stuck `Running` then times out | Fixed — the poll uses `execution list` and dumps logs on failure. |
| Deploy says `Output "api_url" not found` | Infra not applied yet — `deploy-azure.yml` runs `terraform apply` first; let it finish. |
| `azure/login` "client-id not present" | The env's `AZURE_*` secrets aren't set (step 5). |

See `README.md` (this folder) for the architecture, module list, and auth detail.
