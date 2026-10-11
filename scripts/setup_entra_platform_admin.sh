#!/usr/bin/env bash
#
# setup_entra_platform_admin.sh — provision a ShipX platform admin in Microsoft
# Entra (External ID / CIAM) and configure the SPA app registration so the
# issued token resolves to PLATFORM_ADMIN in the backend.
#
# This automates the manual bring-up steps (ADR-004 Phase 5) and is idempotent:
# re-running reconciles state rather than failing on existing objects.
#
# The platform admin resolves purely from `platform_admin` group membership
# (backend ENTRA_PLATFORM_ADMIN_GROUP_ID → platform_admin, tenant_id derived as
# PLATFORM), so this script only needs the app + group + user + the group claim.
# Tenant users' tenant_id/role come from the DB-backed claims provider via the
# custom authentication extension — a separate, one-time binding documented in
# docs/runbook.md ("Azure deployment — required one-time setup"); this script
# does NOT register directory extensions or a Graph permission (none are needed).
#
# What it does
#   1. Resolves the tenant's verified default domain (or honours TENANT_DOMAIN).
#   2. Creates/updates the SPA app registration as a PUBLIC client (ROPC-capable,
#      matching frontend/src/auth/EntraClient.ts).
#   3. Ensures its service principal and admin-consents the OIDC delegated scopes
#      (openid / profile / offline_access) so ROPC needs no interactive consent.
#   4. Enables the security-group claim on the app (so the admin's group GUID is
#      in the token).
#   5. Ensures the prefixless `platform_admin` security group.
#   6. Creates the admin user under the verified domain, sets a permanent
#      password + contact email, and adds it to the group.
#   7. Prints the exact backend + frontend env wiring.
#
# Requirements: az CLI, logged in (`az login`) as a user with permission to
# create app registrations, grant admin consent, and manage users/groups.
#
# Usage:
#   ADMIN_EMAIL=you@example.com ./scripts/setup_entra_platform_admin.sh
#
# Env (all optional except where noted):
#   ADMIN_EMAIL      required — the admin's real email (becomes `mail`/`otherMails`)
#   ADMIN_NAME       display name                         (default: "Platform Admin")
#   ADMIN_PASSWORD   permanent password                   (default: generated + printed)
#   SPA_APP_NAME     app registration display name        (default: "shipx-spa")
#   TENANT_DOMAIN    verified domain for the UPN suffix   (default: tenant's default)
#   GROUP_NAME       platform-admin group display name    (default: "platform_admin")
#   GRAPH            Graph base URL                        (default: v1.0 public cloud)

set -euo pipefail

GRAPH="${GRAPH:-https://graph.microsoft.com/v1.0}"
ADMIN_NAME="${ADMIN_NAME:-Platform Admin}"
SPA_APP_NAME="${SPA_APP_NAME:-shipx-spa}"
GROUP_NAME="${GROUP_NAME:-platform_admin}"

# Well-known Microsoft Graph delegated-permission (scope) ids.
GRAPH_API_ID="00000003-0000-0000-c000-000000000000"
SCOPE_OPENID="37f7f235-527c-4136-accd-4a02d197296e"
SCOPE_PROFILE="14dad69e-099b-42c9-810b-d002981feec1"
SCOPE_OFFLINE="7427e0e9-2fba-42fe-b0c0-848c9e6a8182"

log() { printf '\033[1;34m[setup-entra]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[setup-entra] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

command -v az >/dev/null 2>&1 || die "az CLI not found. Install it and run 'az login'."
az account show >/dev/null 2>&1 || die "Not logged in. Run 'az login' first."

[ -n "${ADMIN_EMAIL:-}" ] || die "ADMIN_EMAIL is required (e.g. ADMIN_EMAIL=you@example.com $0)."

# ── 1. Verified domain ───────────────────────────────────────────────────────
if [ -z "${TENANT_DOMAIN:-}" ]; then
  log "Resolving the tenant's verified default domain…"
  TENANT_DOMAIN="$(az rest --method GET \
    --url "${GRAPH}/domains?\$select=id,isVerified,isDefault" \
    --query "value[?isDefault && isVerified].id | [0]" -o tsv)"
  [ -n "${TENANT_DOMAIN}" ] || die "Could not resolve a verified default domain; set TENANT_DOMAIN explicitly."
fi
log "Tenant domain: ${TENANT_DOMAIN}"

# UPN must live under a verified domain; rewrite foreign-domain emails (mirrors
# shared/providers/azure/entra.py::_upn).
case "${ADMIN_EMAIL}" in
  *@"${TENANT_DOMAIN}") UPN="${ADMIN_EMAIL}" ;;
  *) UPN="$(printf '%s' "${ADMIN_EMAIL}" | tr '@' '_')@${TENANT_DOMAIN}" ;;
esac
log "Admin UPN: ${UPN}"

# ── 2. SPA app registration (public client) ──────────────────────────────────
APP_ID="$(az ad app list --display-name "${SPA_APP_NAME}" --query "[0].appId" -o tsv)"
if [ -z "${APP_ID}" ]; then
  log "Creating public-client app registration '${SPA_APP_NAME}'…"
  APP_ID="$(az ad app create --display-name "${SPA_APP_NAME}" \
    --is-fallback-public-client true --query appId -o tsv)"
else
  log "Reusing app registration '${SPA_APP_NAME}' (${APP_ID}); ensuring public-client flow…"
  az ad app update --id "${APP_ID}" --is-fallback-public-client true
fi
APP_OBJECT_ID="$(az ad app show --id "${APP_ID}" --query id -o tsv)"
log "SPA app id (client id): ${APP_ID}"

# ── 3. Service principal + admin consent for OIDC scopes ─────────────────────
az ad sp show --id "${APP_ID}" >/dev/null 2>&1 || { log "Creating service principal…"; az ad sp create --id "${APP_ID}" >/dev/null; }
log "Registering + admin-consenting OIDC delegated scopes…"
az ad app permission add --id "${APP_ID}" --api "${GRAPH_API_ID}" \
  --api-permissions "${SCOPE_OPENID}=Scope" "${SCOPE_PROFILE}=Scope" "${SCOPE_OFFLINE}=Scope" >/dev/null 2>&1 || true
# Consent can lag app propagation; retry briefly.
for attempt in 1 2 3 4 5; do
  if az ad app permission admin-consent --id "${APP_ID}" 2>/dev/null; then break; fi
  log "admin-consent not ready yet (attempt ${attempt}); retrying in 10s…"; sleep 10
done

# ── 4. Security-group claim ──────────────────────────────────────────────────
# Emit security-group object ids in the token so the platform admin's
# `platform_admin` group GUID is present; the backend maps it via
# ENTRA_PLATFORM_ADMIN_GROUP_ID and derives tenant_id=PLATFORM. No directory
# extensions / optional claims — tenant users' claims come from the claims
# provider (DB-backed), not from this app's token config.
log "Enabling the security-group claim on the app…"
az rest --method PATCH --url "${GRAPH}/applications/${APP_OBJECT_ID}" \
  --headers "Content-Type=application/json" \
  --body '{"groupMembershipClaims": "SecurityGroup"}'

# ── 5. platform_admin security group ─────────────────────────────────────────
GROUP_ID="$(az ad group list --display-name "${GROUP_NAME}" --query "[0].id" -o tsv)"
if [ -z "${GROUP_ID}" ]; then
  log "Creating security group '${GROUP_NAME}'…"
  GROUP_ID="$(az ad group create --display-name "${GROUP_NAME}" --mail-nickname "${GROUP_NAME}" --query id -o tsv)"
else
  log "Reusing security group '${GROUP_NAME}' (${GROUP_ID})."
fi

# ── 6. The platform admin user ───────────────────────────────────────────────
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 18)A1!}"
USER_ID="$(az ad user show --id "${UPN}" --query id -o tsv 2>/dev/null || true)"
if [ -z "${USER_ID}" ]; then
  log "Creating user ${UPN}…"
  USER_ID="$(az ad user create \
    --display-name "${ADMIN_NAME}" \
    --user-principal-name "${UPN}" \
    --mail-nickname "$(printf '%s' "${ADMIN_EMAIL%@*}" | tr -cd 'A-Za-z0-9._-')" \
    --password "${ADMIN_PASSWORD}" \
    --force-change-password-next-sign-in false \
    --query id -o tsv)"
else
  log "Reusing user ${UPN} (${USER_ID}); setting a permanent password…"
  az ad user update --id "${UPN}" --password "${ADMIN_PASSWORD}" --force-change-password-next-sign-in false
fi

log "Setting the contact email (otherMails)…"
az rest --method PATCH --url "${GRAPH}/users/${USER_ID}" \
  --headers "Content-Type=application/json" \
  --body "{\"otherMails\":[\"${ADMIN_EMAIL}\"]}"

# ── 7. Group membership ──────────────────────────────────────────────────────
if az ad group member check --group "${GROUP_ID}" --member-id "${USER_ID}" --query value -o tsv 2>/dev/null | grep -qi true; then
  log "User already in '${GROUP_NAME}'."
else
  log "Adding user to '${GROUP_NAME}'…"
  az ad group member add --group "${GROUP_ID}" --member-id "${USER_ID}"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
TOKEN_ENDPOINT="https://${TENANT_DOMAIN%%.*}.ciamlogin.com/${TENANT_DOMAIN}/oauth2/v2.0/token"
cat <<SUMMARY

============================================================
 ShipX platform admin provisioned in Entra
============================================================
  UPN (login)        : ${UPN}
  Contact email      : ${ADMIN_EMAIL}
  Password           : ${ADMIN_PASSWORD}
  Group              : ${GROUP_NAME} (${GROUP_ID})
  SPA client id      : ${APP_ID}
  Token endpoint     : ${TOKEN_ENDPOINT}

 Backend API env (the platform admin resolves via this group GUID):
   AUTH_PROVIDER=azure
   OIDC_AUDIENCE=${APP_ID}
   ENTRA_PLATFORM_ADMIN_GROUP_ID=${GROUP_ID}
   # ENTRA_TENANT_ID_CLAIM / ENTRA_ROLE_CLAIM stay at their tenant_id / role
   # defaults — only set them if the claims provider emits different names.

 Frontend build env:
   VITE_AUTH_PROVIDER=entra
   VITE_ENTRA_CLIENT_ID=${APP_ID}
   VITE_ENTRA_TOKEN_ENDPOINT=${TOKEN_ENDPOINT}

 Verify (expect groups to contain ${GROUP_ID}):
   curl -s -X POST "${TOKEN_ENDPOINT}" \\
     -d grant_type=password -d "client_id=${APP_ID}" \\
     -d "username=${UPN}" -d "password=<password>" \\
     -d "scope=openid profile offline_access" | python3 -m json.tool
   # decode the id_token; groups should include the platform_admin group id.

 NOTE: tenant users (customer/staff/tenant_admin) also need the DB-backed claims
 provider + its custom-auth-extension binding — see docs/runbook.md
 ("Azure deployment — required one-time setup"). The platform admin does not.
============================================================
SUMMARY
