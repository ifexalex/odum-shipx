#!/usr/bin/env bash
# =============================================================================
# ShipX — AWS One-Time Bootstrap Script
# =============================================================================
# Creates the pre-Terraform foundation resources that Terraform cannot manage
# before `terraform init` (chicken-and-egg):
#   1. S3 state bucket  (versioned, AES256, public-access blocked)
#   2. DynamoDB lock table  (PAY_PER_REQUEST, PITR enabled)
#   3. GitHub Actions OIDC provider
#   4. IAM permissions-boundary policy  (caps Lambda execution role blast radius)
#   5. IAM deploy roles  (one per environment, OIDC-trusted, scoped operator policy)
#   6. Patches infrastructure/aws/environments/*.backend.hcl with real account ID
#
# USAGE:
#   ./scripts/bootstrap_aws.sh GITHUB_ORG/REPO [AWS_REGION]
#   Example: ./scripts/bootstrap_aws.sh ifexalex/odum-shipx eu-west-1
#
# PREREQUISITES:
#   - AWS CLI v2 configured with credentials that have IAM full access
#     (AdministratorAccess or a custom policy with iam:*, s3:*, dynamodb:*)
#   - jq installed
#   - Run from the repository root
#
# IDEMPOTENT: Safe to re-run — each resource is checked for existence first.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Args + config
# ---------------------------------------------------------------------------
GITHUB_REPO="${1:?Usage: $0 OWNER/REPO [aws-region]}"
AWS_REGION="${2:-eu-west-1}"
PROJECT="logistics"

# GitHub OIDC thumbprints (valid as of 2025; rotate if GitHub rotates their cert)
# Source: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect
OIDC_THUMBPRINTS=(
  "6938fd4d98bab03faadb97b34396831e3780aea1"
  "1c58a3a8518e8759bf075b76b750d4f2df264fcd"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "  [$(date +%H:%M:%S)] $*" >&2; }
info() { echo >&2; echo "▶ $*" >&2; }
ok()   { echo "  ✓ $*" >&2; }
warn() { echo "  ⚠ $*" >&2; }

assert_commands() {
  for cmd in aws jq sed; do
    command -v "$cmd" &>/dev/null || { echo "ERROR: '$cmd' not found in PATH"; exit 1; }
  done
  # Require AWS CLI v2
  AWS_VERSION=$(aws --version 2>&1 | cut -d/ -f2 | cut -d. -f1)
  [[ "${AWS_VERSION}" -ge 2 ]] || { echo "ERROR: AWS CLI v2 required (found: $(aws --version 2>&1))"; exit 1; }
}

# ---------------------------------------------------------------------------
# Step 0 — Validate + resolve account
# ---------------------------------------------------------------------------
assert_commands

info "Resolving AWS identity..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
log "Account ID : ${ACCOUNT_ID}"
log "Caller ARN : ${CALLER_ARN}"
log "Region     : ${AWS_REGION}"
log "GitHub repo: ${GITHUB_REPO}"

BUCKET="${PROJECT}-terraform-state-${ACCOUNT_ID}"
DYNAMO_TABLE="${PROJECT}-terraform-locks"
BOUNDARY_POLICY_NAME="${PROJECT}-lambda-permissions-boundary"
OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
BOUNDARY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${BOUNDARY_POLICY_NAME}"

# ---------------------------------------------------------------------------
# Step 1 — Patch backend.hcl files with real account ID
# ---------------------------------------------------------------------------
info "Step 1/6 — Patching backend.hcl files..."
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for env in dev staging prod demo; do
  file="${REPO_ROOT}/infrastructure/aws/environments/${env}.backend.hcl"
  if grep -q "ACCOUNT_ID" "${file}" 2>/dev/null; then
    sed -i.bak "s/ACCOUNT_ID/${ACCOUNT_ID}/g" "${file}" && rm -f "${file}.bak"
    ok "Patched ${env}.backend.hcl"
  else
    ok "${env}.backend.hcl already patched (skipping)"
  fi
done

# ---------------------------------------------------------------------------
# Step 2 — S3 state bucket
# ---------------------------------------------------------------------------
info "Step 2/6 — S3 Terraform state bucket..."

if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  ok "Bucket '${BUCKET}' already exists"
else
  log "Creating bucket '${BUCKET}'..."
  if [[ "${AWS_REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${AWS_REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${AWS_REGION}" \
      --create-bucket-configuration LocationConstraint="${AWS_REGION}" >/dev/null
  fi
  ok "Bucket created"
fi

log "Enabling versioning..."
aws s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

log "Enabling AES256 SSE..."
aws s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
      "BucketKeyEnabled": true
    }]
  }'

log "Blocking public access..."
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

log "Adding lifecycle rule (abort incomplete multipart after 7 days)..."
aws s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "abort-incomplete-multipart",
      "Status": "Enabled",
      "Filter": {},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }]
  }'

ok "S3 state bucket ready: ${BUCKET}"

# ---------------------------------------------------------------------------
# Step 3 — DynamoDB lock table
# ---------------------------------------------------------------------------
info "Step 3/6 — DynamoDB lock table..."

TABLE_STATUS=$(aws dynamodb describe-table --table-name "${DYNAMO_TABLE}" \
  --region "${AWS_REGION}" --query 'Table.TableStatus' --output text 2>/dev/null || echo "NOT_FOUND")

if [[ "${TABLE_STATUS}" != "NOT_FOUND" ]]; then
  ok "Table '${DYNAMO_TABLE}' already exists (status: ${TABLE_STATUS})"
else
  log "Creating table '${DYNAMO_TABLE}'..."
  aws dynamodb create-table \
    --table-name "${DYNAMO_TABLE}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "${AWS_REGION}" >/dev/null

  log "Waiting for table to become ACTIVE..."
  aws dynamodb wait table-exists --table-name "${DYNAMO_TABLE}" --region "${AWS_REGION}"
  ok "Table created"
fi

log "Enabling point-in-time recovery..."
aws dynamodb update-continuous-backups \
  --table-name "${DYNAMO_TABLE}" \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region "${AWS_REGION}" >/dev/null
ok "DynamoDB lock table ready: ${DYNAMO_TABLE}"

# ---------------------------------------------------------------------------
# Step 4 — GitHub Actions OIDC provider
# ---------------------------------------------------------------------------
info "Step 4/6 — GitHub OIDC provider..."

if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${OIDC_ARN}" &>/dev/null; then
  ok "OIDC provider already exists"
else
  log "Creating OIDC provider for ${OIDC_URL}..."
  aws iam create-open-id-connect-provider \
    --url "${OIDC_URL}" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "${OIDC_THUMBPRINTS[0]}" "${OIDC_THUMBPRINTS[1]}" >/dev/null
  ok "OIDC provider created"
fi

# ---------------------------------------------------------------------------
# Step 5 — Permissions boundary policy
# ---------------------------------------------------------------------------
info "Step 5/6 — Permissions boundary policy..."

BOUNDARY_DOC=$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:*:${ACCOUNT_ID}:log-group:/aws/lambda/${PROJECT}-*"
    },
    {
      "Sid": "VpcAccess",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
        "ec2:AssignPrivateIpAddresses",
        "ec2:UnassignPrivateIpAddresses"
      ],
      "Resource": "*"
    },
    {
      "Sid": "XRayTracing",
      "Effect": "Allow",
      "Action": [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SecretsManagerDbPassword",
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:*:${ACCOUNT_ID}:secret:${PROJECT}-*"
    },
    {
      "Sid": "S3Assets",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::${PROJECT}-assets-*/*"
    },
    {
      "Sid": "S3AssetsList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::${PROJECT}-assets-*"
    },
    {
      "Sid": "SqsQueues",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:*:${ACCOUNT_ID}:${PROJECT}-*"
    },
    {
      "Sid": "EventBridgePutEvents",
      "Effect": "Allow",
      "Action": ["events:PutEvents"],
      "Resource": "arn:aws:events:*:${ACCOUNT_ID}:event-bus/${PROJECT}-events-*"
    },
    {
      "Sid": "KmsFieldEncryption",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
      "Resource": "*",
      "Condition": {
        "StringLike": {
          "kms:RequestAlias": "alias/${PROJECT}-field-encryption-*"
        }
      }
    },
    {
      "Sid": "CognitoAdminOps",
      "Effect": "Allow",
      "Action": [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminDeleteUser",
        "cognito-idp:AdminDisableUser",
        "cognito-idp:AdminEnableUser",
        "cognito-idp:AdminGetUser",
        "cognito-idp:AdminListGroupsForUser",
        "cognito-idp:AdminAddUserToGroup",
        "cognito-idp:AdminRemoveUserFromGroup",
        "cognito-idp:AdminUpdateUserAttributes",
        "cognito-idp:AdminResetUserPassword",
        "cognito-idp:AdminInitiateAuth",
        "cognito-idp:AdminRespondToAuthChallenge",
        "cognito-idp:ListUsersInGroup",
        "cognito-idp:ListUsers"
      ],
      "Resource": "arn:aws:cognito-idp:*:${ACCOUNT_ID}:userpool/*"
    },
    {
      "Sid": "SesSendEmail",
      "Effect": "Allow",
      "Action": ["ses:SendEmail", "ses:SendRawEmail"],
      "Resource": "arn:aws:ses:*:${ACCOUNT_ID}:identity/*"
    },
    {
      "Sid": "RdsDbConnect",
      "Effect": "Allow",
      "Action": ["rds-db:connect"],
      "Resource": "arn:aws:rds-db:*:${ACCOUNT_ID}:dbuser:*/*"
    },
    {
      "Sid": "ElastiCacheConnect",
      "Effect": "Allow",
      "Action": ["elasticache:Connect"],
      "Resource": "arn:aws:elasticache:*:${ACCOUNT_ID}:*:${PROJECT}-*"
    }
  ]
}
POLICY
)

if aws iam get-policy --policy-arn "${BOUNDARY_ARN}" &>/dev/null; then
  log "Permissions boundary '${BOUNDARY_POLICY_NAME}' already exists — updating to latest version..."
  aws iam create-policy-version \
    --policy-arn "${BOUNDARY_ARN}" \
    --policy-document "${BOUNDARY_DOC}" \
    --set-as-default >/dev/null
  # Clean up old non-default versions (IAM max 5 versions)
  OLD_VERSIONS=$(aws iam list-policy-versions --policy-arn "${BOUNDARY_ARN}" \
    --query 'Versions[?!IsDefaultVersion].VersionId' --output text)
  for v in ${OLD_VERSIONS}; do
    aws iam delete-policy-version --policy-arn "${BOUNDARY_ARN}" --version-id "${v}" 2>/dev/null || true
  done
  ok "Permissions boundary updated"
else
  log "Creating permissions boundary policy '${BOUNDARY_POLICY_NAME}'..."
  aws iam create-policy \
    --policy-name "${BOUNDARY_POLICY_NAME}" \
    --description "Permissions boundary for all ${PROJECT} Lambda execution roles - caps blast radius" \
    --policy-document "${BOUNDARY_DOC}" >/dev/null
  ok "Permissions boundary created: ${BOUNDARY_ARN}"
fi

# ---------------------------------------------------------------------------
# Step 6 — IAM deploy roles (one per environment)
# ---------------------------------------------------------------------------
info "Step 6/6 — IAM deploy roles (dev / staging / prod)..."

# Terraform operator policy document — same for all environments
# Split across 6 statements to stay readable; resource ARNs scoped to logistics-*
OPERATOR_DOC=$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TerraformState",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:HeadObject",
        "s3:ListBucket", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET}",
        "arn:aws:s3:::${BUCKET}/*"
      ]
    },
    {
      "Sid": "TerraformLock",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
        "dynamodb:DescribeTable", "dynamodb:CreateTable"
      ],
      "Resource": "arn:aws:dynamodb:${AWS_REGION}:${ACCOUNT_ID}:table/${DYNAMO_TABLE}"
    },
    {
      "Sid": "LambdaAndLayer",
      "Effect": "Allow",
      "Action": ["lambda:*"],
      "Resource": [
        "arn:aws:lambda:*:${ACCOUNT_ID}:function:${PROJECT}-*",
        "arn:aws:lambda:*:${ACCOUNT_ID}:layer:${PROJECT}-*"
      ]
    },
    {
      "Sid": "ApiGateway",
      "Effect": "Allow",
      "Action": ["apigateway:*"],
      "Resource": "arn:aws:apigateway:${AWS_REGION}::/*"
    },
    {
      "Sid": "EventBridgeAndSqs",
      "Effect": "Allow",
      "Action": ["events:*", "sqs:*", "scheduler:*"],
      "Resource": [
        "arn:aws:events:*:${ACCOUNT_ID}:*",
        "arn:aws:sqs:*:${ACCOUNT_ID}:${PROJECT}-*"
      ]
    },
    {
      "Sid": "DataLayer",
      "Effect": "Allow",
      "Action": [
        "rds:*",
        "rds-data:*"
      ],
      "Resource": [
        "arn:aws:rds:*:${ACCOUNT_ID}:*:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:cluster:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:db:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:db-proxy:*",
        "arn:aws:rds:*:${ACCOUNT_ID}:subgrp:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:cluster-pg:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:og:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:pg:${PROJECT}-*",
        "arn:aws:rds:*:${ACCOUNT_ID}:target-group:${PROJECT}-*"
      ]
    },
    {
      "Sid": "RdsGlobalDescribe",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeGlobalClusters",
        "rds:DescribeEngineDefaultParameters",
        "rds:DescribeEngineDefaultClusterParameters",
        "rds:DescribeDBEngineVersions",
        "rds:DescribeOrderableDBInstanceOptions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ElastiCache",
      "Effect": "Allow",
      "Action": ["elasticache:*"],
      "Resource": "*"
    },
    {
      "Sid": "SecretsAndKms",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:*",
        "kms:Describe*", "kms:Get*", "kms:List*",
        "kms:Create*", "kms:Delete*", "kms:Update*",
        "kms:Enable*", "kms:Disable*", "kms:Put*",
        "kms:Schedule*", "kms:Cancel*", "kms:Tag*", "kms:Untag*",
        "kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*",
        "kms:ReEncrypt*", "kms:Sign", "kms:Verify"
      ],
      "Resource": [
        "arn:aws:secretsmanager:*:${ACCOUNT_ID}:secret:${PROJECT}-*",
        "arn:aws:kms:*:${ACCOUNT_ID}:key/*",
        "arn:aws:kms:*:${ACCOUNT_ID}:alias/${PROJECT}-*"
      ]
    },
    {
      "Sid": "KmsGlobalActions",
      "Effect": "Allow",
      "Action": ["kms:CreateKey", "kms:ListAliases", "kms:ListKeys"],
      "Resource": "*"
    },
    {
      "Sid": "IamServiceLinkedRoles",
      "Effect": "Allow",
      "Action": ["iam:CreateServiceLinkedRole"],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/aws-service-role/*"
    },
    {
      "Sid": "S3Assets",
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": [
        "arn:aws:s3:::${PROJECT}-assets-*",
        "arn:aws:s3:::${PROJECT}-assets-*/*"
      ]
    },
    {
      "Sid": "Networking",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute", "ec2:DescribeVpcs",
        "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute", "ec2:DescribeSubnets",
        "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway", "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway", "ec2:DescribeInternetGateways",
        "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute",
        "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable", "ec2:DescribeRouteTables",
        "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup", "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress", "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
        "ec2:UpdateSecurityGroupRuleDescriptionsEgress", "ec2:DescribeSecurityGroups",
        "ec2:DescribeSecurityGroupRules", "ec2:ModifySecurityGroupRules",
        "ec2:CreateVpcEndpoint", "ec2:DeleteVpcEndpoints", "ec2:DescribeVpcEndpoints",
        "ec2:ModifyVpcEndpoint",
        "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface",
        "ec2:DescribeNetworkInterfaces", "ec2:ModifyNetworkInterfaceAttribute",
        "ec2:DescribeAvailabilityZones", "ec2:DescribeAccountAttributes",
        "ec2:DescribePrefixLists", "ec2:DescribeVpcAttribute",
        "ec2:CreateTags", "ec2:DeleteTags", "ec2:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Cognito",
      "Effect": "Allow",
      "Action": ["cognito-idp:*"],
      "Resource": [
        "arn:aws:cognito-idp:*:${ACCOUNT_ID}:userpool/*",
        "*"
      ]
    },
    {
      "Sid": "Ses",
      "Effect": "Allow",
      "Action": ["ses:*"],
      "Resource": [
        "arn:aws:ses:*:${ACCOUNT_ID}:identity/*",
        "arn:aws:ses:*:${ACCOUNT_ID}:configuration-set/${PROJECT}-*",
        "*"
      ]
    },
    {
      "Sid": "ObservabilityAndAlerts",
      "Effect": "Allow",
      "Action": [
        "logs:*",
        "cloudwatch:*",
        "sns:*",
        "xray:*"
      ],
      "Resource": [
        "arn:aws:logs:*:${ACCOUNT_ID}:log-group:*${PROJECT}*",
        "arn:aws:logs:*:${ACCOUNT_ID}:log-group:*${PROJECT}*:*",
        "arn:aws:cloudwatch:*:${ACCOUNT_ID}:alarm:${PROJECT}-*",
        "arn:aws:cloudwatch::${ACCOUNT_ID}:dashboard/${PROJECT}-*",
        "arn:aws:sns:*:${ACCOUNT_ID}:${PROJECT}-*",
        "*"
      ]
    },
    {
      "Sid": "IamReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole", "iam:ListRoles", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:GetRolePolicy",
        "iam:GetPolicy", "iam:GetPolicyVersion",
        "iam:ListPolicies", "iam:ListPolicyVersions",
        "iam:ListInstanceProfilesForRole", "iam:GetInstanceProfile",
        "iam:ListOpenIDConnectProviders", "iam:GetOpenIDConnectProvider",
        "iam:PassRole"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IamCreateRolesWithBoundary",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:TagRole"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/${PROJECT}-*",
      "Condition": {
        "StringEquals": {
          "iam:PermissionsBoundary": "${BOUNDARY_ARN}"
        }
      }
    },
    {
      "Sid": "IamManageExistingRoles",
      "Effect": "Allow",
      "Action": [
        "iam:DeleteRole",
        "iam:DetachRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:UpdateRole",
        "iam:UpdateRoleDescription",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:PutRolePolicy"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/${PROJECT}-*"
    },
    {
      "Sid": "IamManagePolicies",
      "Effect": "Allow",
      "Action": [
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:CreatePolicyVersion",
        "iam:DeletePolicyVersion",
        "iam:TagPolicy",
        "iam:UntagPolicy"
      ],
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:policy/${PROJECT}-*"
    },
    {
      "Sid": "IamOidcProvider",
      "Effect": "Allow",
      "Action": [
        "iam:CreateOpenIDConnectProvider",
        "iam:DeleteOpenIDConnectProvider",
        "iam:UpdateOpenIDConnectProviderThumbprint",
        "iam:AddClientIDToOpenIDConnectProvider",
        "iam:RemoveClientIDFromOpenIDConnectProvider",
        "iam:TagOpenIDConnectProvider"
      ],
      "Resource": "${OIDC_ARN}"
    }
  ]
}
POLICY
)

create_or_update_role() {
  local env="$1"
  local role_name="${PROJECT}-github-deploy-${env}"
  local role_arn="arn:aws:iam::${ACCOUNT_ID}:role/${role_name}"

  # Trust subjects: dev trusts main branch + environment; staging/prod trust environment only
  if [[ "${env}" == "dev" ]]; then
    local trust_subjects="\"repo:${GITHUB_REPO}:ref:refs/heads/main\", \"repo:${GITHUB_REPO}:environment:dev\""
  else
    local trust_subjects="\"repo:${GITHUB_REPO}:environment:${env}\""
  fi

  local trust_doc
  trust_doc=$(cat <<TRUST
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "${OIDC_ARN}"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": [${trust_subjects}]
      }
    }
  }]
}
TRUST
)

  if aws iam get-role --role-name "${role_name}" &>/dev/null; then
    log "Role '${role_name}' already exists — updating trust policy and inline policy..."
    aws iam update-assume-role-policy \
      --role-name "${role_name}" \
      --policy-document "${trust_doc}" >/dev/null
    # Remove permissions boundary if previously set — deploy roles must not have it
    # (the boundary is for Lambda execution roles only; it would block state bucket access)
    aws iam delete-role-permissions-boundary \
      --role-name "${role_name}" 2>/dev/null || true
  else
    log "Creating role '${role_name}'..."
    aws iam create-role \
      --role-name "${role_name}" \
      --assume-role-policy-document "${trust_doc}" \
      --description "GitHub Actions OIDC deploy role for ${PROJECT} ${env} - managed by bootstrap_aws.sh" \
      --tags Key=ManagedBy,Value=bootstrap_aws.sh Key=Project,Value="${PROJECT}" Key=Environment,Value="${env}" \
      >/dev/null
  fi

  log "Upserting inline operator policy on '${role_name}'..."
  aws iam put-role-policy \
    --role-name "${role_name}" \
    --policy-name "${PROJECT}-terraform-operator" \
    --policy-document "${OPERATOR_DOC}" >/dev/null

  ok "Role ready: ${role_arn}"
  echo "${role_arn}"
}

DEV_ROLE=$(create_or_update_role "dev")
STAGING_ROLE=$(create_or_update_role "staging")
PROD_ROLE=$(create_or_update_role "prod")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
cat <<SUMMARY

╔══════════════════════════════════════════════════════════════════════════════╗
║                     Bootstrap Complete — ShipX AWS Setup                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

  Account ID   : ${ACCOUNT_ID}
  Region       : ${AWS_REGION}
  GitHub repo  : ${GITHUB_REPO}

  S3 state bucket : ${BUCKET}
    Versioning  : enabled
    Encryption  : AES256
    Public access: blocked

  DynamoDB lock table : ${DYNAMO_TABLE}
    Billing : PAY_PER_REQUEST
    PITR    : enabled

  GitHub OIDC provider : ${OIDC_ARN}

  Permissions boundary : ${BOUNDARY_ARN}

  IAM Deploy Roles:
    dev     → ${DEV_ROLE}
             (trusted: refs/heads/main + environment:dev)
    staging → ${STAGING_ROLE}
             (trusted: environment:staging only)
    prod    → ${PROD_ROLE}
             (trusted: environment:prod only)

────────────────────────────────────────────────────────────────────────────

  NEXT STEPS:

  1. Commit the patched backend configs:
       git add infrastructure/aws/environments/{dev,staging,prod}.backend.hcl
       git commit -m "chore: bootstrap AWS account ID in backend configs"

  2. Set GitHub Environment secrets (Settings → Environments):
       Environment "dev"     → AWS_DEPLOY_ROLE_ARN = ${DEV_ROLE}
       Environment "staging" → AWS_DEPLOY_ROLE_ARN = ${STAGING_ROLE}
       Environment "prod"    → AWS_DEPLOY_ROLE_ARN = ${PROD_ROLE}

  3. Initialise Terraform:
       cd infrastructure/aws
       terraform init -backend-config=environments/dev.backend.hcl
       terraform plan -var-file=environments/dev.tfvars

  4. Apply (dev auto-deploys from main; staging/prod require workflow_dispatch):
       terraform apply -var-file=environments/dev.tfvars

  5. After first apply, import OIDC resources into Terraform state:
       See docs/project docs/18_cicd_pipeline.md — Bootstrap section

────────────────────────────────────────────────────────────────────────────
SUMMARY
