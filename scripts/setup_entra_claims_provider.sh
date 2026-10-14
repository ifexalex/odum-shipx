#!/usr/bin/env bash
#
# setup_entra_claims_provider.sh — the one-time Entra-tenant setup the Azure
# deploy pipeline can't do (no Terraform/azuread resource; the Contributor
# deploy identity can't touch the tenant). Run it once per Entra tenant AFTER a
# `deploy-azure.yml` run has created the resources. Idempotent: re-running
# reconciles existing objects instead of failing.
#
# Login is broken until this runs — the claims Container App is deployed and
# healthy, but Entra never calls it, so tokens carry no tenant_id/role and every
# user resolves as an unprivileged `customer` (platform admin included). See
# docs/runbook.md → "Azure deployment — required one-time setup (Entra auth)".
#
# What it does
#   1. Adds the SPA callback as a Single-page-application redirect URI on the SPA
#      app registration (interactive auth-code + PKCE login, frontend/src/auth).
#   2. Ensures the "resource" app registration the custom extension authenticates
#      to (Entra mints a token with aud = this app; the claims provider validates
#      it — services/entra_token_claims/security.py). Exposes the
#      CustomAuthenticationExtensions.Receive.Payload app role Entra consumes.
#   3. Creates/reconciles the onTokenIssuanceStart custom authentication
#      extension pointing at the claims Container App endpoint, emitting the
#      tenant_id + role claims.
#   4. Binds it to the SPA app via an authenticationEventListener, so Entra calls
#      it on every interactive sign-in.
#   5. Best-effort admin-consent for the extension's permission; prints the
#      portal fallback if that needs a click.
#   6. Prints the exact `entra_claims_caller_*` tfvars to set (so the deployed
#      claims container validates the inbound token), and a verify command.
#
# Requirements: az CLI, logged in (`az login`) as a user able to manage app
# registrations, service principals, grant admin consent, and create
# authentication event extensions/listeners. Needs Graph /beta.
#
# Usage (values auto-read from Terraform when run from a configured checkout):
#   ./scripts/setup_entra_claims_provider.sh
# or pass explicitly:
#   SPA_APP_ID=<client id> \
#   CLAIMS_ENDPOINT=https://<app>.azurecontainerapps.io/ \
#   FRONTEND_URL=https://<frontdoor-host> \
#   ./scripts/setup_entra_claims_provider.sh
#
# Env (all optional unless noted; the script auto-resolves what it can):
#   SPA_APP_ID        SPA app registration client id   (default: resolve by SPA_APP_NAME)
#   SPA_APP_NAME      SPA app display name              (default: "shipx-spa")
#   CLAIMS_ENDPOINT   claims Container App URL          (default: terraform output entra_claims_endpoint_url)
#   FRONTEND_URL      SPA origin for the redirect URI   (default: terraform output frontend_url)
#   RESOURCE_APP_ID   existing audience app client id   (default: create "shipx-token-claims-api")
#   EXT_NAME          custom-extension display name     (default: "shipx-token-claims")
#   TENANT_ID         Entra directory (tenant) id       (default: az account tenantId)
#   TF_DIR            Terraform dir for auto-read        (default: infrastructure/azure)
#   GRAPH_BETA        Graph beta base URL               (default: https://graph.microsoft.com/beta)

set -euo pipefail

GRAPH_BETA="${GRAPH_BETA:-https://graph.microsoft.com/beta}"
SPA_APP_NAME="${SPA_APP_NAME:-shipx-spa}"
EXT_NAME="${EXT_NAME:-shipx-token-claims}"
RESOURCE_APP_NAME="shipx-token-claims-api"
TF_DIR="${TF_DIR:-infrastructure/azure}"
# App role Entra's custom-extension caller is granted on the resource app.
PROVISIONED_ROLE_VALUE="CustomAuthenticationExtensions.Receive.Payload"

log()  { printf '\033[1;34m[entra-claims]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[entra-claims] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[entra-claims] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v az >/dev/null 2>&1 || die "az CLI not found. Install it and run 'az login'."
az account show >/dev/null 2>&1 || die "Not logged in. Run 'az login' first."

TENANT_ID="${TENANT_ID:-$(az account show --query tenantId -o tsv)}"

# ── Auto-read Terraform outputs when values weren't passed ────────────────────
tf_out() { terraform -chdir="${TF_DIR}" output -raw "$1" 2>/dev/null || true; }
if [ -z "${CLAIMS_ENDPOINT:-}" ] && command -v terraform >/dev/null 2>&1; then
  CLAIMS_ENDPOINT="$(tf_out entra_claims_endpoint_url)"
fi
if [ -z "${FRONTEND_URL:-}" ] && command -v terraform >/dev/null 2>&1; then
  FRONTEND_URL="$(tf_out frontend_url)"
fi
[ -n "${CLAIMS_ENDPOINT:-}" ] || die "CLAIMS_ENDPOINT not set and not readable from Terraform ('entra_claims_endpoint_url')."
[ -n "${FRONTEND_URL:-}" ]    || die "FRONTEND_URL not set and not readable from Terraform ('frontend_url')."
REDIRECT_URI="${FRONTEND_URL%/}/auth/callback"

# ── Resolve the SPA app ───────────────────────────────────────────────────────
if [ -z "${SPA_APP_ID:-}" ]; then
  log "Resolving SPA app '${SPA_APP_NAME}'…"
  SPA_APP_ID="$(az ad app list --display-name "${SPA_APP_NAME}" --query '[0].appId' -o tsv)"
  [ -n "${SPA_APP_ID}" ] || die "Could not find SPA app '${SPA_APP_NAME}'. Pass SPA_APP_ID=<client id>."
fi
SPA_OBJECT_ID="$(az ad app show --id "${SPA_APP_ID}" --query id -o tsv)" \
  || die "SPA app ${SPA_APP_ID} not found."
log "SPA app: ${SPA_APP_ID} (object ${SPA_OBJECT_ID})"

# ── 1. SPA redirect URI (interactive auth-code callback) ──────────────────────
log "Ensuring SPA redirect URI: ${REDIRECT_URI}"
EXISTING_SPA_URIS="$(az ad app show --id "${SPA_APP_ID}" --query 'spa.redirectUris' -o json)"
if printf '%s' "${EXISTING_SPA_URIS}" | grep -qF "${REDIRECT_URI}"; then
  log "  already present."
else
  MERGED="$(printf '%s' "${EXISTING_SPA_URIS}" | python3 -c \
    "import sys,json; a=json.load(sys.stdin) or []; a.append(sys.argv[1]); print(json.dumps(sorted(set(a))))" \
    "${REDIRECT_URI}")"
  az rest --method PATCH \
    --url "${GRAPH_BETA}/applications/${SPA_OBJECT_ID}" \
    --headers "Content-Type=application/json" \
    --body "{\"spa\": {\"redirectUris\": ${MERGED}}}"
  log "  added."
fi

# ── 2. Resource app the custom extension authenticates to ─────────────────────
# Entra mints a token (aud = this app) when calling the extension; the claims
# provider validates aud == CALLER_AUDIENCE (services/entra_token_claims).
if [ -z "${RESOURCE_APP_ID:-}" ]; then
  RESOURCE_APP_ID="$(az ad app list --display-name "${RESOURCE_APP_NAME}" --query '[0].appId' -o tsv)"
fi
if [ -z "${RESOURCE_APP_ID:-}" ]; then
  log "Creating resource app '${RESOURCE_APP_NAME}'…"
  RESOURCE_APP_ID="$(az ad app create --display-name "${RESOURCE_APP_NAME}" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
fi
RESOURCE_OBJECT_ID="$(az ad app show --id "${RESOURCE_APP_ID}" --query id -o tsv)"
log "Resource (audience) app: ${RESOURCE_APP_ID}"

# Identifier URI api://<appId> so the token aud is stable & addressable.
RESOURCE_URI="api://${RESOURCE_APP_ID}"
CUR_URIS="$(az ad app show --id "${RESOURCE_APP_ID}" --query 'identifierUris' -o json)"
if ! printf '%s' "${CUR_URIS}" | grep -qF "${RESOURCE_URI}"; then
  az ad app update --id "${RESOURCE_APP_ID}" --identifier-uris "${RESOURCE_URI}" || \
    warn "Could not set identifier URI (${RESOURCE_URI}); the appId is still a valid resourceId."
fi

# Expose the app role Entra's custom-extension caller receives, if missing.
HAS_ROLE="$(az ad app show --id "${RESOURCE_APP_ID}" \
  --query "appRoles[?value=='${PROVISIONED_ROLE_VALUE}'] | length(@)" -o tsv)"
if [ "${HAS_ROLE}" = "0" ]; then
  log "Exposing app role ${PROVISIONED_ROLE_VALUE} on the resource app…"
  ROLE_ID="$(python3 -c 'import uuid;print(uuid.uuid4())')"
  az rest --method PATCH \
    --url "${GRAPH_BETA}/applications/${RESOURCE_OBJECT_ID}" \
    --headers "Content-Type=application/json" \
    --body "{\"appRoles\": [ {
      \"id\": \"${ROLE_ID}\",
      \"allowedMemberTypes\": [\"Application\"],
      \"displayName\": \"Receive token-issuance payload\",
      \"description\": \"Entra custom authentication extensions call this API.\",
      \"value\": \"${PROVISIONED_ROLE_VALUE}\",
      \"isEnabled\": true } ]}" \
    || warn "Could not add the app role; add it in the portal if consent fails below."
fi
# Ensure a service principal exists for the resource app (needed for consent).
az ad sp show --id "${RESOURCE_APP_ID}" >/dev/null 2>&1 || az ad sp create --id "${RESOURCE_APP_ID}" >/dev/null

# ── 3. Custom authentication extension (onTokenIssuanceStart) ─────────────────
EXT_BODY="$(cat <<JSON
{
  "@odata.type": "#microsoft.graph.onTokenIssuanceStartCustomExtension",
  "displayName": "${EXT_NAME}",
  "description": "ShipX DB-backed tenant_id/role claims provider.",
  "endpointConfiguration": { "@odata.type": "#microsoft.graph.httpRequestEndpoint", "targetUrl": "${CLAIMS_ENDPOINT}" },
  "authenticationConfiguration": { "@odata.type": "#microsoft.graph.azureAdTokenAuthentication", "resourceId": "${RESOURCE_APP_ID}" },
  "claimsForTokenConfiguration": [ { "claimIdInApiResponse": "tenant_id" }, { "claimIdInApiResponse": "role" } ]
}
JSON
)"
EXT_ID="$(az rest --method GET \
  --url "${GRAPH_BETA}/identity/customAuthenticationExtensions?\$filter=displayName eq '${EXT_NAME}'" \
  --query 'value[0].id' -o tsv 2>/dev/null || true)"
if [ -z "${EXT_ID}" ]; then
  log "Creating custom authentication extension '${EXT_NAME}' → ${CLAIMS_ENDPOINT}"
  EXT_ID="$(az rest --method POST \
    --url "${GRAPH_BETA}/identity/customAuthenticationExtensions" \
    --headers "Content-Type=application/json" --body "${EXT_BODY}" --query id -o tsv)"
else
  log "Reconciling existing custom authentication extension ${EXT_ID}…"
  az rest --method PATCH \
    --url "${GRAPH_BETA}/identity/customAuthenticationExtensions/${EXT_ID}" \
    --headers "Content-Type=application/json" --body "${EXT_BODY}" >/dev/null
fi
log "Extension: ${EXT_ID}"

# ── 4. Bind it to the SPA app's token-issuance event ──────────────────────────
LISTENER_ID="$(az rest --method GET \
  --url "${GRAPH_BETA}/identity/authenticationEventListeners" \
  --query "value[?handler.customExtension.id=='${EXT_ID}'] | [0].id" -o tsv 2>/dev/null || true)"
if [ -z "${LISTENER_ID}" ]; then
  log "Binding the extension to SPA app ${SPA_APP_ID} (onTokenIssuanceStart)…"
  az rest --method POST \
    --url "${GRAPH_BETA}/identity/authenticationEventListeners" \
    --headers "Content-Type=application/json" \
    --body "{
      \"@odata.type\": \"#microsoft.graph.onTokenIssuanceStartListener\",
      \"conditions\": { \"applications\": { \"includeApplications\": [ { \"appId\": \"${SPA_APP_ID}\" } ] } },
      \"handler\": { \"@odata.type\": \"#microsoft.graph.onTokenIssuanceStartCustomExtensionHandler\",
                     \"customExtension\": { \"id\": \"${EXT_ID}\" } }
    }" >/dev/null
  log "  bound."
else
  log "Listener already bound (${LISTENER_ID})."
fi

# ── 5. Admin consent (best-effort) ────────────────────────────────────────────
# Entra's first-party custom-extensions caller must hold the Receive.Payload role
# on the resource app. The portal "Grant permission" button is the reliable path;
# attempt it here but don't fail the run if the directory requires the click.
log "Granting admin consent to the resource app (best-effort)…"
if ! az ad app permission admin-consent --id "${RESOURCE_APP_ID}" 2>/dev/null; then
  warn "Automatic consent didn't complete. Grant it in the portal:"
  warn "  Entra admin center → Enterprise applications → Custom authentication extensions"
  warn "  → ${EXT_NAME} → Grant permission."
fi

# ── 6. Print the tfvars + verify ──────────────────────────────────────────────
ISSUER="https://login.microsoftonline.com/${TENANT_ID}/v2.0"
JWKS="https://login.microsoftonline.com/${TENANT_ID}/discovery/v2.0/keys"
cat <<DONE

$(log 'Done.')

Set these in your Azure tfvars so the deployed claims container validates the
inbound Entra token, then re-run deploy-azure.yml (the claims app reads them):

  entra_claims_caller_audience = "${RESOURCE_APP_ID}"
  entra_claims_caller_issuer   = "${ISSUER}"
  entra_claims_caller_jwks_url = "${JWKS}"

Also confirm these are already set (platform-admin + interactive login):
  entra_platform_admin_group_id = "<platform_admin group object id>"
  entra_redirect_uri            = "${REDIRECT_URI}"   (Terraform derives this)

Verify: sign in via the SPA, decode the id_token, and confirm tenant_id + role:
  python3 -c "import sys,json,base64; p=sys.argv[1].split('.')[1]; p+='='*(-len(p)%4); \
print(sorted(json.loads(base64.urlsafe_b64decode(p)).keys()))" '<id_token>'

If tenant_id/role are missing: allow a few minutes for propagation; check the
*-entra-claims Container App logs; confirm the user's Entra oid matches their
tenant_user.cognito_sub (scripts/migrate_users_to_entra.py).
DONE
