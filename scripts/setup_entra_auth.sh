#!/usr/bin/env bash
#
# setup_entra_auth.sh — the Entra-tenant configuration that cannot live in
# Terraform, as one idempotent, re-runnable script.
#
# WHY THIS EXISTS
# Everything the *application* needs is already Terraform-managed (the
# entra_* variables in infrastructure/azure → the container_app module's env).
# What is NOT is the state inside the Entra tenant itself: app registrations,
# Graph permissions, admin consent and the sign-in user flow. Terraform cannot
# own them here because:
#   - the azuread provider would need directory-admin rights, while the deploy
#     identity is deliberately a subscription Contributor, and
#   - the CIAM tenant (062cb98d…) is a DIFFERENT tenant from the one holding the
#     subscription (a59c21d1…), so a single provider config cannot reach both.
# Every one of these was applied by hand during the dev auth build-out. This
# script is how staging and prod get the same state without repeating that.
#
# WHAT IT DOES (each step checks first; re-running reconciles)
#   1. Guard: refuse to run unless the logged-in tenant is the intended one.
#   2. Graph provisioning app ("shipx-graph-provisioner") — the confidential app
#      EntraIdentityProvider uses to create tenant users and set their initial
#      password. Ensures the three APPLICATION permissions and admin consent.
#   3. Mints a client secret and prints how to store it (never written to disk).
#   4. Turns OFF self-service sign-up, so the hosted sign-in page stops offering
#      "Create account". Signup must go through the ShipX onboarding form; Entra
#      only authenticates.
#   5. Reports whether self-service password reset is available to local accounts.
#
# NOT DONE HERE (on purpose)
#   - The redirect URI + claims provider: scripts/setup_entra_claims_provider.sh.
#   - The platform_admin group: scripts/setup_entra_platform_admin.sh.
#   - Sign-in page branding: no stable Graph surface; portal-only (see runbook).
#
# Usage:
#   ENTRA_TENANT_ID=062cb98d-8990-4947-81c4-223cb1e9b8f3 \
#     ./scripts/setup_entra_auth.sh
#
#   az login --tenant <ENTRA_TENANT_ID> --allow-no-subscriptions   # first, if needed
#
# Env:
#   ENTRA_TENANT_ID   (required) the Entra tenant to configure. Compared against
#                     the logged-in tenant; a mismatch aborts. Required rather
#                     than defaulted because the wrong tenant here silently
#                     configures the subscription's workforce directory.
#   GRAPH_APP_NAME    provisioning app display name (default shipx-graph-provisioner)
#   SECRET_YEARS      client-secret lifetime in years (default 1)
#   SKIP_SECRET       set to 1 to reconcile permissions without minting a secret
#   DRY_RUN           set to 1 to report intended changes without making them

set -euo pipefail

GRAPH_V1="https://graph.microsoft.com/v1.0"
GRAPH_BETA="https://graph.microsoft.com/beta"
GRAPH_APP_NAME="${GRAPH_APP_NAME:-shipx-graph-provisioner}"
SECRET_YEARS="${SECRET_YEARS:-1}"
MS_GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"

# Microsoft Graph APPLICATION permission ids. Hardcoded because they are stable
# well-known GUIDs and resolving them by name at runtime is an extra failure mode.
#   User.ReadWrite.All                  — create/update the tenant user
#   Group.ReadWrite.All                 — add them to the {tenant}:{role} group
#   User-PasswordProfile.ReadWrite.All  — set the initial password. Separated out
#     by Microsoft from User.ReadWrite.All; without it, set_password fails with
#     403 Authorization_RequestDenied and activation cannot complete.
declare -a REQUIRED_PERMS=(
  "741f803b-c850-494e-b5df-cde7c675a1ca:User.ReadWrite.All"
  "62a82d76-70ea-41e2-9197-370581804d09:Group.ReadWrite.All"
  "cc117bb9-00cf-4eb8-b580-ea2a878fe8f7:User-PasswordProfile.ReadWrite.All"
)

log()  { printf '\033[1;34m[entra-auth]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[entra-auth]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[entra-auth] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[entra-auth] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }
would() { [ "${DRY_RUN:-0}" = "1" ] && { log "DRY_RUN: would $*"; return 0; } || return 1; }

command -v az >/dev/null 2>&1 || die "az CLI not found."
command -v python3 >/dev/null 2>&1 || die "python3 not found."

# ── 1. Tenant guard ──────────────────────────────────────────────────────────
# ShipX spans two tenants: the subscription/workforce tenant and the CIAM tenant
# that holds the users. Running this against the former would add Graph
# permissions and disable sign-up in the wrong directory, so require the caller
# to state the target and verify it.
[ -n "${ENTRA_TENANT_ID:-}" ] || die \
  "ENTRA_TENANT_ID is required (the CIAM tenant id). Refusing to guess — the
  subscription lives in a different tenant and configuring that one by mistake
  is not obviously recoverable."

az account show >/dev/null 2>&1 || die "Not logged in. Run: az login --tenant ${ENTRA_TENANT_ID} --allow-no-subscriptions"
CURRENT_TENANT="$(az account show --query tenantId -o tsv)"
if [ "${CURRENT_TENANT}" != "${ENTRA_TENANT_ID}" ]; then
  die "Logged into tenant ${CURRENT_TENANT}, but ENTRA_TENANT_ID=${ENTRA_TENANT_ID}.
  Re-login against the target tenant:
    az login --tenant ${ENTRA_TENANT_ID} --allow-no-subscriptions"
fi
ok "Tenant confirmed: ${ENTRA_TENANT_ID}"

# ── 2. Graph provisioning app + permissions + consent ────────────────────────
APP_ID="$(az ad app list --display-name "${GRAPH_APP_NAME}" --query "[?displayName=='${GRAPH_APP_NAME}'].appId | [0]" -o tsv 2>/dev/null || true)"
if [ -z "${APP_ID}" ] || [ "${APP_ID}" = "None" ]; then
  if ! would "create app registration '${GRAPH_APP_NAME}'"; then
    log "Creating app registration '${GRAPH_APP_NAME}'…"
    APP_ID="$(az ad app create --display-name "${GRAPH_APP_NAME}" \
      --sign-in-audience AzureADMyOrg --query appId -o tsv)"
    ok "Created ${APP_ID}"
  fi
else
  ok "App registration exists: ${APP_ID}"
fi
[ -n "${APP_ID:-}" ] || { log "DRY_RUN: stopping (nothing further to inspect)."; exit 0; }

# A service principal must exist before app-role assignments (consent) can be made.
az ad sp show --id "${APP_ID}" >/dev/null 2>&1 || {
  would "create service principal for ${APP_ID}" || {
    log "Creating service principal…"
    az ad sp create --id "${APP_ID}" >/dev/null
  }
}

log "Reconciling Graph application permissions…"
for ENTRY in "${REQUIRED_PERMS[@]}"; do
  PERM_ID="${ENTRY%%:*}"
  PERM_NAME="${ENTRY#*:}"
  HAS="$(az ad app show --id "${APP_ID}" \
    --query "requiredResourceAccess[?resourceAppId=='${MS_GRAPH_APP_ID}'].resourceAccess[] | [?id=='${PERM_ID}'] | length(@)" \
    -o tsv 2>/dev/null || echo 0)"
  if [ "${HAS}" != "0" ]; then
    ok "  ${PERM_NAME} already requested"
    continue
  fi
  would "add ${PERM_NAME}" && continue
  log "  adding ${PERM_NAME}…"
  az ad app permission add --id "${APP_ID}" \
    --api "${MS_GRAPH_APP_ID}" --api-permissions "${PERM_ID}=Role" >/dev/null
done

# Admin consent. Requested permissions do nothing until consented — this is the
# step whose absence produced "403 Authorization_RequestDenied / Insufficient
# privileges" when provisioning tried to set a password.
if ! would "grant admin consent"; then
  log "Granting admin consent (requires Privileged Role Administrator or Global Administrator)…"
  if az ad app permission admin-consent --id "${APP_ID}" 2>/dev/null; then
    ok "Admin consent granted."
  else
    warn "Automatic consent failed — grant it in the portal, then re-run to verify:"
    warn "  Entra admin center → App registrations → ${GRAPH_APP_NAME}"
    warn "  → API permissions → Grant admin consent for <tenant>"
  fi
fi

# Verify consent rather than trusting the command's exit code: the three roles
# must appear as appRoleAssignments on the service principal.
SP_OBJECT_ID="$(az ad sp show --id "${APP_ID}" --query id -o tsv 2>/dev/null || true)"
if [ -n "${SP_OBJECT_ID}" ]; then
  GRANTED="$(az rest --method GET \
    --url "${GRAPH_V1}/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
    --query 'value[].appRoleId' -o json 2>/dev/null || echo '[]')"
  MISSING=""
  for ENTRY in "${REQUIRED_PERMS[@]}"; do
    printf '%s' "${GRANTED}" | grep -qF "${ENTRY%%:*}" || MISSING="${MISSING} ${ENTRY#*:}"
  done
  if [ -n "${MISSING}" ]; then
    warn "Consent still MISSING for:${MISSING}"
    warn "User provisioning will fail until these are consented."
  else
    ok "All three Graph permissions are consented."
  fi
fi

# ── 3. Client secret ─────────────────────────────────────────────────────────
# Printed once, never written to disk. It belongs in the GitHub Environment
# secret ENTRA_GRAPH_CLIENT_SECRET, which the deploy injects as
# TF_VAR_entra_graph_client_secret; Terraform then stores it as a Container App
# secret. It is deliberately NOT in tfvars (those are committed).
if [ "${SKIP_SECRET:-0}" = "1" ]; then
  log "SKIP_SECRET=1 — not minting a new secret."
elif ! would "mint a client secret"; then
  log "Minting a client secret (${SECRET_YEARS}y)…"
  SECRET="$(az ad app credential reset --id "${APP_ID}" \
    --display-name "shipx-provisioner-$(date -u +%Y%m%d)" \
    --years "${SECRET_YEARS}" --query password -o tsv)"
  cat <<SECRETOUT

  ─────────────────────────────────────────────────────────────────────────────
  Client secret minted. It is shown ONCE and is not stored by this script.

    ENTRA_GRAPH_CLIENT_SECRET = ${SECRET}

  Store it as a GitHub Environment secret (per environment), NOT in tfvars:
    gh secret set ENTRA_GRAPH_CLIENT_SECRET --env <dev|staging|demo|prod>

  Note: 'credential reset' REPLACES existing secrets for this app, so any
  environment still using an older secret must be updated and redeployed.
  ─────────────────────────────────────────────────────────────────────────────

SECRETOUT
fi

# ── 4. Disable self-service sign-up ("Create account") ───────────────────────
# ShipX owns signup: a company requests onboarding through the ShipX form and a
# platform admin provisions them. Entra must only AUTHENTICATE. Left on, the
# hosted sign-in page offers "Create account" and a stranger can mint a
# directory user with no tenant_user row — an account that authenticates but
# resolves to nothing.
log "Checking self-service sign-up on the sign-in user flow(s)…"
FLOWS="$(az rest --method GET --url "${GRAPH_BETA}/identity/authenticationEventsFlows" \
  --query 'value' -o json 2>/dev/null || true)"
if [ -z "${FLOWS}" ] || [ "${FLOWS}" = "null" ]; then
  warn "Could not read user flows. This API is External-ID-only and needs"
  warn "directory-admin rights; it 403s on a workforce tenant."
  warn "Turn it off in the portal instead:"
  warn "  Entra admin center → External Identities → User flows → <flow>"
  warn "  → Settings → uncheck/disable account creation (sign-up), Save."
else
  printf '%s' "${FLOWS}" | python3 -c '
import json, sys
flows = json.load(sys.stdin) or []
found = False
for f in flows:
    start = f.get("onInteractiveAuthFlowStart") or {}
    if "isSignUpAllowed" in start:
        found = True
        state = "ALLOWED" if start.get("isSignUpAllowed") else "disabled"
        print(f"  flow {f.get('displayName','?')} ({f.get('id','?')}): sign-up {state}")
if not found:
    print("  no flow exposes isSignUpAllowed — nothing to change here.")
' || warn "Could not parse the user flow list."

  # Patch any flow that still allows sign-up.
  printf '%s' "${FLOWS}" | python3 -c '
import json, sys
flows = json.load(sys.stdin) or []
ids = [f["id"] for f in flows
       if (f.get("onInteractiveAuthFlowStart") or {}).get("isSignUpAllowed") is True]
print("\n".join(ids))
' | while read -r FLOW_ID; do
    [ -n "${FLOW_ID}" ] || continue
    would "disable sign-up on flow ${FLOW_ID}" && continue
    log "  disabling sign-up on flow ${FLOW_ID}…"
    if az rest --method PATCH \
      --url "${GRAPH_BETA}/identity/authenticationEventsFlows/${FLOW_ID}" \
      --headers "Content-Type=application/json" \
      --body '{"@odata.type":"#microsoft.graph.externalUsersSelfServiceSignUpEventsFlow","onInteractiveAuthFlowStart":{"@odata.type":"#microsoft.graph.onInteractiveAuthFlowStartExternalUsersSelfServiceSignUp","isSignUpAllowed":false}}' \
      >/dev/null 2>&1; then
      ok "  sign-up disabled on ${FLOW_ID}."
    else
      warn "  could not patch ${FLOW_ID}. Disable sign-up for it in the portal."
    fi
  done
fi

# ── 5. Password reset ────────────────────────────────────────────────────────
# Reported, not changed. For External ID local accounts the "Forgot password?"
# link on the hosted page is driven by the tenant's authentication methods
# (email OTP as a reset method), and flipping that from a script would change
# tenant-wide authentication behaviour as a side effect of running a setup
# script. Surface the state and let an operator decide.
log "Password reset (report only)…"
EMAIL_METHOD="$(az rest --method GET \
  --url "${GRAPH_V1}/policies/authenticationMethodsPolicy/authenticationMethodConfigurations/Email" \
  --query 'state' -o tsv 2>/dev/null || true)"
if [ -n "${EMAIL_METHOD}" ]; then
  ok "  Email OTP authentication method: ${EMAIL_METHOD}"
  [ "${EMAIL_METHOD}" = "enabled" ] || warn \
    "  Email OTP is ${EMAIL_METHOD} — self-service password reset will not be
  offered to local accounts. Enable it under Entra admin center →
  Authentication methods → Email OTP if you want the 'Forgot password?' flow."
else
  warn "  Could not read the authentication methods policy (needs directory-admin)."
  warn "  Check: Entra admin center → Authentication methods → Email OTP."
fi

cat <<DONE

$(ok 'Done.')

Terraform-side values for this tenant (set in the environment's tfvars):
  entra_graph_tenant_id = "${ENTRA_TENANT_ID}"
  entra_graph_client_id = "${APP_ID}"

Then, for the redirect URI and claims provider:
  ./scripts/setup_entra_claims_provider.sh
And for the platform_admin group:
  ./scripts/setup_entra_platform_admin.sh

DONE
