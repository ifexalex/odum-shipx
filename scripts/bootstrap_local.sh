#!/usr/bin/env bash
# bootstrap_local.sh — create all AWS resources in Moto server for local development
# Run once after: docker compose -f docker-compose.local.yml up -d
# Usage: bash scripts/bootstrap_local.sh

set -euo pipefail

ENDPOINT="http://localhost:5100"
REGION="${AWS_DEFAULT_REGION:-eu-west-1}"
ACCOUNT="123456789012"   # Moto default account ID

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
echo "==> Creating EventBridge routing rules..."

SMS_QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:logistics-sms"
WA_QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:logistics-whatsapp"
EMAIL_QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:logistics-email"
METERING_QUEUE_ARN="arn:aws:sqs:${REGION}:${ACCOUNT}:logistics-metering"

# SMS rule
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-rule \
  --name "route-sms" \
  --event-bus-name "logistics-events" \
  --event-pattern '{"source":["logistics.tracking","logistics.billing","logistics.payment_release"]}' \
  --state ENABLED > /dev/null 2>&1 && echo "    Created rule: route-sms"

aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-targets \
  --rule "route-sms" \
  --event-bus-name "logistics-events" \
  --targets "Id=sms-target,Arn=${SMS_QUEUE_ARN}" > /dev/null 2>&1 || true

# WhatsApp rule
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-rule \
  --name "route-whatsapp" \
  --event-bus-name "logistics-events" \
  --event-pattern '{"source":["logistics.tracking","logistics.billing","logistics.claims","logistics.payment_release"]}' \
  --state ENABLED > /dev/null 2>&1 && echo "    Created rule: route-whatsapp"

aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-targets \
  --rule "route-whatsapp" \
  --event-bus-name "logistics-events" \
  --targets "Id=whatsapp-target,Arn=${WA_QUEUE_ARN}" > /dev/null 2>&1 || true

# Email rule
aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-rule \
  --name "route-email" \
  --event-bus-name "logistics-events" \
  --event-pattern '{"source":["logistics.packing_list","logistics.payment_release","logistics.claims","logistics.tenant_management"]}' \
  --state ENABLED > /dev/null 2>&1 && echo "    Created rule: route-email"

aws --endpoint-url="${ENDPOINT}" --region "${REGION}" \
  events put-targets \
  --rule "route-email" \
  --event-bus-name "logistics-events" \
  --targets "Id=email-target,Arn=${EMAIL_QUEUE_ARN}" > /dev/null 2>&1 || true

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

# Patch .env.local with the freshly generated IDs
python3 - "${POOL_ID}" "${CLIENT_ID}" <<'PYEOF'
import sys, re, pathlib
pool_id, client_id = sys.argv[1], sys.argv[2]
env = pathlib.Path(".env.local")
text = env.read_text()
text = re.sub(r"(?m)^COGNITO_USER_POOL_ID=.*$", f"COGNITO_USER_POOL_ID={pool_id}", text)
text = re.sub(r"(?m)^COGNITO_CLIENT_ID=.*$",    f"COGNITO_CLIENT_ID={client_id}",    text)
env.write_text(text)
print(f"    Updated .env.local  COGNITO_USER_POOL_ID={pool_id}")
print(f"                        COGNITO_CLIENT_ID={client_id}")
PYEOF

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
