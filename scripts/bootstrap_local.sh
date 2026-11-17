#!/usr/bin/env bash
# bootstrap_local.sh — create all AWS resources in Moto server for local development
# Run once after: docker compose -f docker-compose.local.yml up -d
# Usage: bash scripts/bootstrap_local.sh

set -euo pipefail

ENDPOINT="http://localhost:5100"
REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
ACCOUNT="123456789012"   # Moto default account ID

# This script talks only to Moto on localhost, but botocore still needs *some*
# credentials to sign every request — without them every `aws` call fails with
# NoCredentials. `make bootstrap` does not source .env.local (unlike `make dev`),
# so provide Moto's dummy creds here. Any real value already in the env wins, so
# this never overrides a developer's own setup. Moto accepts any credentials.
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-testing}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-testing}"
export AWS_DEFAULT_REGION="${REGION}"

echo "==> Waiting for Moto to be ready..."
until curl -sf -X POST "${ENDPOINT}/moto-api/reset" > /dev/null 2>&1; do
  echo "    ... still waiting"
  sleep 2
done
echo "    Moto is ready."

# ─── SQS Queues ───────────────────────────────────────────────────────────────
echo ""
echo "==> Creating SQS queues..."

for QUEUE in logistics-sms logistics-whatsapp logistics-email logistics-metering; do
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    sqs create-queue --queue-name "${QUEUE}" \
    --output text --query 'QueueUrl' 2>/dev/null \
    && echo "    Created: ${QUEUE}" || echo "    Already exists: ${QUEUE}"
done

for DLQ in logistics-sms-dlq logistics-whatsapp-dlq logistics-email-dlq logistics-metering-dlq; do
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    sqs create-queue --queue-name "${DLQ}" \
    --output text --query 'QueueUrl' 2>/dev/null \
    && echo "    Created: ${DLQ}" || echo "    Already exists: ${DLQ}"
done

# ─── EventBridge Event Bus ────────────────────────────────────────────────────
echo ""
echo "==> Creating EventBridge event bus..."
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events create-event-bus --name logistics-events \
  --output text --query 'EventBusArn' 2>/dev/null \
  && echo "    Created: logistics-events" || echo "    Already exists: logistics-events"

# ─── EventBridge Rules → SQS Targets ─────────────────────────────────────────
echo ""
echo "==> Creating EventBridge metering rule..."

# Only the metering queue is fed from the bus. The sms, whatsapp and email queues are not: services enqueue
# notifications directly in the shape the consumers read, and a raw event has no recipient (audit BE-09).
METERING_QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:logistics-metering"

# Rules from before BE-09: delete them if a long-lived local stack still has them.
for OLD_RULE in route-sms route-whatsapp route-email; do
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    events remove-targets --rule "${OLD_RULE}" --event-bus-name "logistics-events" \
    --ids sms-target whatsapp-target email-target > /dev/null 2>&1 || true
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    events delete-rule --name "${OLD_RULE}" --event-bus-name "logistics-events" > /dev/null 2>&1 \
    && echo "    Deleted old rule: ${OLD_RULE}" || true
done

# Metering rule (catches everything)
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-rule \
  --name "route-metering" \
  --event-bus-name "logistics-events" \
  --event-pattern '{"source":[{"prefix":"logistics."}]}' \
  --state ENABLED > /dev/null 2>&1 && echo "    Created rule: route-metering"

aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-targets \
  --rule "route-metering" \
  --event-bus-name "logistics-events" \
  --targets "Id=metering-target,Arn=${METERING_QUEUE_ARN}" > /dev/null 2>&1 || true

# ─── S3 Bucket ────────────────────────────────────────────────────────────────
echo ""
echo "==> Creating S3 bucket..."
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  s3 mb s3://logistics-assets 2>/dev/null \
  && echo "    Created: s3://logistics-assets" || echo "    Already exists: s3://logistics-assets"

# CORS — required, not cosmetic. Every file upload in this app is a *browser*
# PUT straight to object storage against a presigned URL (the API only mints
# the URL; the bytes never pass through it). Without a CORS rule the browser
# blocks that PUT before it is sent — net::ERR_FAILED, no server-side trace —
# so manifest/packing-list import and all evidence uploads fail locally while
# working perfectly under curl, which ignores CORS. This mirrors the real
# bucket's cors_rule in infrastructure/aws/modules/s3/main.tf; keep the two in
# step. Origins are the local frontends only: Vite's dev server and the
# preview/ container ports.
echo "    Applying CORS (browser presigned PUT)..."
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  s3api put-bucket-cors --bucket logistics-assets \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
      "AllowedOrigins": [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://localhost:8080"
      ],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3600
    }]
  }' && echo "    CORS applied." || echo "    WARNING: could not apply CORS — browser uploads will fail."

# ─── Secrets Manager ──────────────────────────────────────────────────────────
echo ""
echo "==> Creating Secrets Manager secret..."
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  secretsmanager create-secret \
  --name "logistics/db/password" \
  --secret-string '{"password":"localpassword"}' > /dev/null 2>&1 \
  && echo "    Created: logistics/db/password" || echo "    Already exists: logistics/db/password"

# ─── Cognito User Pool ────────────────────────────────────────────────────────
echo ""
echo "==> Creating Cognito user pool..."
POOL_ID=$(aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  cognito-idp create-user-pool \
  --pool-name "logistics-local" \
  --output text --query 'UserPool.Id' | tr -d '[:space:]')
echo "    Created user pool: ${POOL_ID}"

CLIENT_ID=$(aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  cognito-idp create-user-pool-client \
  --user-pool-id "${POOL_ID}" \
  --client-name "logistics-local-client" \
  --no-generate-secret \
  --output text --query 'UserPoolClient.ClientId' | tr -d '[:space:]')
echo "    Created app client: ${CLIENT_ID}"

# Patch both .env.local files with the freshly generated IDs:
#   - root .env.local      → COGNITO_* vars read by local_server.py
#   - frontend/.env.local  → VITE_COGNITO_* vars read by Vite
python3 - "${POOL_ID}" "${CLIENT_ID}" <<'PYEOF'
import sys, re, pathlib
pool_id, client_id = sys.argv[1], sys.argv[2]

# Backend (root)
root_env = pathlib.Path(".env.local")
if root_env.exists():
    text = root_env.read_text()
    text = re.sub(r"(?m)^COGNITO_USER_POOL_ID=.*$", f"COGNITO_USER_POOL_ID={pool_id}", text)
    text = re.sub(r"(?m)^COGNITO_CLIENT_ID=.*$",    f"COGNITO_CLIENT_ID={client_id}",    text)
    root_env.write_text(text)

# Frontend (Vite)
fe_env = pathlib.Path("frontend/.env.local")
if fe_env.exists():
    text = fe_env.read_text()
    text = re.sub(r"(?m)^VITE_COGNITO_USER_POOL_ID=.*$", f"VITE_COGNITO_USER_POOL_ID={pool_id}", text)
    text = re.sub(r"(?m)^VITE_COGNITO_CLIENT_ID=.*$",    f"VITE_COGNITO_CLIENT_ID={client_id}",    text)
    fe_env.write_text(text)

print(f"    Updated .env.local + frontend/.env.local")
print(f"      COGNITO_USER_POOL_ID / VITE_COGNITO_USER_POOL_ID = {pool_id}")
print(f"      COGNITO_CLIENT_ID    / VITE_COGNITO_CLIENT_ID    = {client_id}")
PYEOF

# ─── Seed Cognito users ───────────────────────────────────────────────────────
echo ""
echo "==> Creating Cognito test users..."

create_cognito_user() {
  local EMAIL="$1" NAME="$2" ROLE="$3"
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    cognito-idp admin-create-user \
    --user-pool-id "${POOL_ID}" \
    --username "${EMAIL}" \
    --temporary-password "Test1234!" \
    --message-action SUPPRESS \
    --user-attributes \
      Name=email,Value="${EMAIL}" \
      Name=email_verified,Value=true \
      Name=name,Value="${NAME}" \
      "Name=custom:tenant_id,Value=${TENANT_ID}" \
      "Name=custom:role,Value=${ROLE}" \
    > /dev/null 2>&1 && \
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    cognito-idp admin-set-user-password \
    --user-pool-id "${POOL_ID}" \
    --username "${EMAIL}" \
    --password "Test1234!" \
    --permanent > /dev/null 2>&1 && \
  echo "    Created: ${EMAIL} (${ROLE})" || \
  echo "    Already exists: ${EMAIL}"
}

add_to_group() {
  local EMAIL="$1" GROUP="$2"
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    cognito-idp create-group \
    --user-pool-id "${POOL_ID}" \
    --group-name "${GROUP}" > /dev/null 2>&1 || true
  aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
    cognito-idp admin-add-user-to-group \
    --user-pool-id "${POOL_ID}" \
    --username "${EMAIL}" \
    --group-name "${GROUP}" > /dev/null 2>&1
}

# Every tenant gets the same shape: 1 tenant_admin + 1 china_office_staff +
# 1 nigeria_office_staff + 1 warehouse_attendant + 5 customers — all sharing
# that tenant's own email domain. Fixed tenant_user UUIDs in scripts/seed.py
# match these emails 1:1, so _resolve_user_id_by_email() in local_server.py
# links each Cognito login to the correct seeded DB row.

# Acme Shipping Ltd (Tenant A) — acmeshipping.com
TENANT_ID="10000000-0000-0000-0000-000000000001"
create_cognito_user "admin@acmeshipping.com"     "Chidi Okafor"     "tenant_admin"
create_cognito_user "china@acmeshipping.com"     "Li Wei"           "china_office_staff"
create_cognito_user "lagos@acmeshipping.com"     "Emeka Eze"        "nigeria_office_staff"
create_cognito_user "warehouse@acmeshipping.com" "Tunde Bello"      "warehouse_attendant"
# Multi-role staff member (migration 039) — custom:role carries the primary
# role only; both groups below are what actually grant nigeria_office_staff
# AND warehouse_attendant permissions (see shared/auth.py::_parse_roles).
create_cognito_user "amaka@acmeshipping.com"     "Amaka Nwachukwu"  "nigeria_office_staff"
create_cognito_user "ngozi@acmeshipping.com"     "Ngozi Adeyemi"    "customer"
create_cognito_user "ibrahim@acmeshipping.com"   "Ibrahim Musa"     "customer"
create_cognito_user "chioma@acmeshipping.com"    "Chioma Eze"       "customer"
create_cognito_user "yusuf@acmeshipping.com"     "Yusuf Musa"       "customer"
create_cognito_user "blessing@acmeshipping.com"  "Blessing Nwosu"   "customer"

add_to_group "admin@acmeshipping.com"     "${TENANT_ID}:tenant_admin"
add_to_group "china@acmeshipping.com"     "${TENANT_ID}:china_office_staff"
add_to_group "lagos@acmeshipping.com"     "${TENANT_ID}:nigeria_office_staff"
add_to_group "warehouse@acmeshipping.com" "${TENANT_ID}:warehouse_attendant"
add_to_group "amaka@acmeshipping.com"     "${TENANT_ID}:nigeria_office_staff"
add_to_group "amaka@acmeshipping.com"     "${TENANT_ID}:warehouse_attendant"
add_to_group "ngozi@acmeshipping.com"     "${TENANT_ID}:customer"
add_to_group "ibrahim@acmeshipping.com"   "${TENANT_ID}:customer"
add_to_group "chioma@acmeshipping.com"    "${TENANT_ID}:customer"
add_to_group "yusuf@acmeshipping.com"     "${TENANT_ID}:customer"
add_to_group "blessing@acmeshipping.com"  "${TENANT_ID}:customer"

# Global Cargo Co (Tenant B) — globalcargo.com
GCCO_TENANT_ID="30000000-0000-0000-0000-000000000001"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "admin@globalcargo.com"     "Aisha Suleiman"  "tenant_admin"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "china@globalcargo.com"     "Zhang Wei"       "china_office_staff"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "lagos@globalcargo.com"     "Ade Bankole"     "nigeria_office_staff"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "warehouse@globalcargo.com" "Ngozi Kalu"      "warehouse_attendant"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "olumide@globalcargo.com"   "Olumide Adebayo" "customer"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "chinwe@globalcargo.com"    "Chinwe Okoro"    "customer"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "tunji@globalcargo.com"     "Tunji Bakare"    "customer"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "grace@globalcargo.com"     "Grace Eze"       "customer"
TENANT_ID="${GCCO_TENANT_ID}" create_cognito_user "halima@globalcargo.com"    "Halima Yusuf"    "customer"

add_to_group "admin@globalcargo.com"     "${GCCO_TENANT_ID}:tenant_admin"
add_to_group "china@globalcargo.com"     "${GCCO_TENANT_ID}:china_office_staff"
add_to_group "lagos@globalcargo.com"     "${GCCO_TENANT_ID}:nigeria_office_staff"
add_to_group "warehouse@globalcargo.com" "${GCCO_TENANT_ID}:warehouse_attendant"
add_to_group "olumide@globalcargo.com"   "${GCCO_TENANT_ID}:customer"
add_to_group "chinwe@globalcargo.com"    "${GCCO_TENANT_ID}:customer"
add_to_group "tunji@globalcargo.com"     "${GCCO_TENANT_ID}:customer"
add_to_group "grace@globalcargo.com"     "${GCCO_TENANT_ID}:customer"
add_to_group "halima@globalcargo.com"    "${GCCO_TENANT_ID}:customer"

# Demo Shipping Ltd (Tenant C) — demoshipping.com
DEMO_TENANT_ID="20000000-0000-0000-0000-000000000001"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "admin@demoshipping.com"     "Amara Okafor"      "tenant_admin"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "china@demoshipping.com"     "Kwame Asante"      "china_office_staff"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "lagos@demoshipping.com"     "Fatima Bello"      "nigeria_office_staff"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "warehouse@demoshipping.com" "Segun Dada"        "warehouse_attendant"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "funmi@demoshipping.com"     "Funmilayo Adeyemi" "customer"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "emeka@demoshipping.com"     "Emeka Obi"         "customer"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "amaka@demoshipping.com"     "Amaka Chukwu"      "customer"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "david@demoshipping.com"     "David Okon"        "customer"
TENANT_ID="${DEMO_TENANT_ID}" create_cognito_user "zainab@demoshipping.com"    "Zainab Bello"      "customer"

add_to_group "admin@demoshipping.com"     "${DEMO_TENANT_ID}:tenant_admin"
add_to_group "china@demoshipping.com"     "${DEMO_TENANT_ID}:china_office_staff"
add_to_group "lagos@demoshipping.com"     "${DEMO_TENANT_ID}:nigeria_office_staff"
add_to_group "warehouse@demoshipping.com" "${DEMO_TENANT_ID}:warehouse_attendant"
add_to_group "funmi@demoshipping.com"     "${DEMO_TENANT_ID}:customer"
add_to_group "emeka@demoshipping.com"     "${DEMO_TENANT_ID}:customer"
add_to_group "amaka@demoshipping.com"     "${DEMO_TENANT_ID}:customer"
add_to_group "david@demoshipping.com"     "${DEMO_TENANT_ID}:customer"
add_to_group "zainab@demoshipping.com"    "${DEMO_TENANT_ID}:customer"

# Platform Admin (cross-tenant — custom:tenant_id = "PLATFORM", no tenant prefix
# on the Cognito group; see shared/auth.py's _parse_role()). There is no
# tenant_user row for this account by design — tenant_user.tenant_id is a
# NOT NULL FK to tenant(id) and its role CHECK constraint has no
# 'platform_admin' value, so platform admins are Cognito-only identities.
TENANT_ID="PLATFORM" create_cognito_user "platform-admin@shipx.co" "Ada Nwachukwu" "platform_admin"
add_to_group "platform-admin@shipx.co" "platform_admin"

# ─── SES sender identity ──────────────────────────────────────────────────────
# Moto enforces SES's verified-identity rule, so an unverified sender is
# rejected exactly as it would be in AWS:
#   MessageRejected: Email address not verified notifications@logistics.example.com
# That is the application's placeholder default, which is what every local
# notification email was sent from — so local email delivery failed outright
# while SMS and WhatsApp appeared to work. Verifying the address .env.local
# actually uses makes local email behave like the real thing.
echo ""
echo "==> Verifying SES sender identity"
SES_SENDER="${SES_FROM_ADDRESS:-notifications@shipx.local}"
aws --endpoint-url "${ENDPOINT}" ses verify-email-identity \
  --email-address "${SES_SENDER}" >/dev/null 2>&1 \
  && echo "    verified ${SES_SENDER}" \
  || echo "    WARNING: could not verify ${SES_SENDER} — local email sends will be rejected"

# ─── Print queue URLs ─────────────────────────────────────────────────────────
echo ""
echo "==> Queue URLs (already set in .env.local):"
echo "    SQS_SMS_QUEUE_URL=${ENDPOINT}/${ACCOUNT}/logistics-sms"
echo "    SQS_WHATSAPP_QUEUE_URL=${ENDPOINT}/${ACCOUNT}/logistics-whatsapp"
echo "    SQS_EMAIL_QUEUE_URL=${ENDPOINT}/${ACCOUNT}/logistics-email"
echo "    SQS_METERING_QUEUE_URL=${ENDPOINT}/${ACCOUNT}/logistics-metering"

echo ""
echo "==> Bootstrap complete. Start the dev server:"
echo "    set -a; source .env.local; set +a"
echo "    PYTHONPATH=. python3 scripts/local_server.py"
echo ""
echo "==> Or run tests:"
echo "    PYTHONPATH=. python3 -m pytest tests/unit/ -q"
echo "    PYTHONPATH=. python3 -m pytest tests/integration/ -q"
