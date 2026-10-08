# ---------------------------------------------------------------------------
# GitHub Actions OIDC — Terraform-managed representation
#
# bootstrap_aws.sh creates these resources on first boot so that terraform init
# can run. After the first `terraform apply`, import them into state:
#
#   ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
#   terraform import module.iam_oidc.aws_iam_openid_connect_provider.github \
#     arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com
#   terraform import 'module.iam_oidc.aws_iam_role.deploy["dev"]'     logistics-github-deploy-dev
#   terraform import 'module.iam_oidc.aws_iam_role.deploy["staging"]' logistics-github-deploy-staging
#   terraform import 'module.iam_oidc.aws_iam_role.deploy["prod"]'    logistics-github-deploy-prod
#   terraform import module.iam_oidc.aws_iam_policy.permissions_boundary \
#     arn:aws:iam::${ACCOUNT}:policy/logistics-lambda-permissions-boundary
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  region       = data.aws_region.current.name
  name_prefix  = var.project_name
  bucket_name  = "${local.name_prefix}-terraform-state-${local.account_id}"
  dynamo_table = "${local.name_prefix}-terraform-locks"
  boundary_arn = "arn:aws:iam::${local.account_id}:policy/${local.name_prefix}-lambda-permissions-boundary"
  oidc_arn     = "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"

  # Trust subjects per environment:
  # dev   — trusted from main branch push OR GitHub Environment "dev"
  # staging/prod/demo — only from their respective GitHub Environments (manual dispatch)
  env_trust_subjects = {
    dev = [
      "repo:${var.github_repo}:ref:refs/heads/main",
      "repo:${var.github_repo}:environment:dev",
    ]
    staging = ["repo:${var.github_repo}:environment:staging"]
    prod    = ["repo:${var.github_repo}:environment:prod"]
    demo    = ["repo:${var.github_repo}:environment:demo"]
  }
}

# ---------------------------------------------------------------------------
# GitHub OIDC provider
# Thumbprints: rotate if GitHub rotates the cert for token.actions.githubusercontent.com
# ---------------------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1c58a3a8518e8759bf075b76b750d4f2df264fcd"]

  tags = {
    Name      = "github-actions-oidc"
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Permissions boundary
# Caps the maximum permissions any Terraform-created Lambda execution role
# can ever have — prevents privilege escalation even if the deploy role is
# compromised and attempts to create an overpowered Lambda role.
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "permissions_boundary" {
  name        = "${local.name_prefix}-lambda-permissions-boundary"
  description = "Permissions boundary for all ${local.name_prefix} Lambda execution roles"
  policy      = data.aws_iam_policy_document.lambda_boundary.json

  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

data "aws_iam_policy_document" "lambda_boundary" {
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["arn:aws:logs:*:${local.account_id}:log-group:/aws/lambda/${local.name_prefix}-*"]
  }

  statement {
    sid    = "VpcAccess"
    effect = "Allow"
    actions = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses",
      "ec2:UnassignPrivateIpAddresses",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "XRayTracing"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "SecretsManagerDbPassword"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:${local.account_id}:secret:${local.name_prefix}-*"]
  }

  statement {
    sid    = "S3Assets"
    effect = "Allow"
    # DeleteObjectVersion: data_cleanup purges a tenant's versioned objects on
    # offboarding (delete_objects on list_object_versions results).
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetObjectVersion", "s3:DeleteObjectVersion"]
    resources = ["arn:aws:s3:::${local.name_prefix}-assets-*/*"]
  }

  statement {
    sid       = "S3AssetsList"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${local.name_prefix}-assets-*"]
  }

  statement {
    sid    = "SqsQueues"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ChangeMessageVisibility",
    ]
    resources = ["arn:aws:sqs:*:${local.account_id}:${local.name_prefix}-*"]
  }

  statement {
    sid       = "EventBridgePutEvents"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = ["arn:aws:events:*:${local.account_id}:event-bus/${local.name_prefix}-events-*"]
  }

  statement {
    sid       = "KmsFieldEncryption"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = ["*"]
    # kms:ResourceAliases matches on the key's aliases however the request
    # references it. The previous kms:RequestAlias condition is only present
    # when a request *names an alias*: shared/encryption.py passes the key ARN
    # to GenerateDataKey and passes no key at all to Decrypt (the ciphertext
    # embeds it), so that condition could never match and the boundary would
    # have denied every field encrypt/decrypt in AWS.
    condition {
      test     = "ForAnyValue:StringLike"
      variable = "kms:ResourceAliases"
      values   = ["alias/${local.name_prefix}-field-encryption-*"]
    }
  }

  statement {
    sid    = "CognitoAdminOps"
    effect = "Allow"
    actions = [
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
      "cognito-idp:AdminSetUserPassword",
      "cognito-idp:AdminUserGlobalSignOut",
      "cognito-idp:CreateGroup",
      "cognito-idp:AdminInitiateAuth",
      "cognito-idp:AdminRespondToAuthChallenge",
      "cognito-idp:ListUsersInGroup",
      "cognito-idp:ListUsers",
    ]
    resources = ["arn:aws:cognito-idp:*:${local.account_id}:userpool/*"]
  }

  statement {
    sid       = "SesSendEmail"
    effect    = "Allow"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["arn:aws:ses:*:${local.account_id}:identity/*"]
  }

  statement {
    sid       = "RdsDbConnect"
    effect    = "Allow"
    actions   = ["rds-db:connect"]
    resources = ["arn:aws:rds-db:*:${local.account_id}:dbuser:*/*"]
  }

  statement {
    sid       = "ElastiCacheConnect"
    effect    = "Allow"
    actions   = ["elasticache:Connect"]
    resources = ["arn:aws:elasticache:*:${local.account_id}:*:${local.name_prefix}-*"]
  }
}

# ---------------------------------------------------------------------------
# IAM deploy roles — one per environment
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "trust" {
  for_each = local.env_trust_subjects

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = each.value
    }
  }
}

resource "aws_iam_role" "deploy" {
  for_each           = local.env_trust_subjects
  name               = "${local.name_prefix}-github-deploy-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.trust[each.key].json
  # No permissions_boundary — the boundary is for Lambda execution roles only.
  # Deploy roles are constrained by OIDC trust + scoped inline policy.
  # Attaching the Lambda boundary would block access to the Terraform state bucket.
  description = "GitHub Actions OIDC deploy role for ${local.name_prefix} ${each.key}"

  tags = {
    Project     = var.project_name
    Environment = each.key
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy" "terraform_operator" {
  for_each = local.env_trust_subjects
  name     = "${local.name_prefix}-terraform-operator"
  role     = aws_iam_role.deploy[each.key].id
  policy   = data.aws_iam_policy_document.terraform_operator.json
}

data "aws_iam_policy_document" "terraform_operator" {
  statement {
    sid    = "TerraformState"
    effect = "Allow"
    actions = [
      "s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:HeadObject",
      "s3:ListBucket", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration",
    ]
    resources = [
      "arn:aws:s3:::${local.bucket_name}",
      "arn:aws:s3:::${local.bucket_name}/*",
    ]
  }

  statement {
    sid    = "TerraformLock"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
      "dynamodb:DescribeTable", "dynamodb:CreateTable",
    ]
    resources = ["arn:aws:dynamodb:${local.region}:${local.account_id}:table/${local.dynamo_table}"]
  }

  statement {
    sid     = "LambdaAndLayer"
    effect  = "Allow"
    actions = ["lambda:*"]
    resources = [
      "arn:aws:lambda:*:${local.account_id}:function:${local.name_prefix}-*",
      "arn:aws:lambda:*:${local.account_id}:layer:${local.name_prefix}-*",
      "arn:aws:lambda:*:${local.account_id}:event-source-mapping:*",
    ]
  }

  statement {
    sid       = "ApiGateway"
    effect    = "Allow"
    actions   = ["apigateway:*"]
    resources = ["arn:aws:apigateway:${local.region}::/*"]
  }

  statement {
    sid     = "EventBridgeAndSqs"
    effect  = "Allow"
    actions = ["events:*", "sqs:*"]
    resources = [
      "arn:aws:events:*:${local.account_id}:*",
      "arn:aws:sqs:*:${local.account_id}:${local.name_prefix}-*",
    ]
  }

  statement {
    sid    = "RdsGlobalDescribe"
    effect = "Allow"
    actions = [
      "rds:DescribeGlobalClusters",
      "rds:DescribeEngineDefaultParameters",
      "rds:DescribeEngineDefaultClusterParameters",
      "rds:DescribeDBEngineVersions",
      "rds:DescribeOrderableDBInstanceOptions",
      "rds:DescribeDBProxyTargets",
    ]
    # Global cluster ARNs have no region component; can't be scoped to logistics-*
    resources = ["*"]
  }

  statement {
    sid     = "DataLayer"
    effect  = "Allow"
    actions = ["rds:*", "rds-data:*"]
    resources = [
      "arn:aws:rds:*:${local.account_id}:cluster:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:db:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:db-proxy:*",
      "arn:aws:rds:*:${local.account_id}:subgrp:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:cluster-pg:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:og:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:pg:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:target-group:${local.name_prefix}-*",
      "arn:aws:rds:*:${local.account_id}:*:${local.name_prefix}-*",
    ]
  }

  statement {
    sid       = "ElastiCache"
    effect    = "Allow"
    actions   = ["elasticache:*"]
    resources = ["*"]
    # Tag conditions can't be used on resource creation (default parameter groups
    # and subnet groups have no project tags at the time of the API call).
  }

  statement {
    sid    = "SecretsAndKms"
    effect = "Allow"
    actions = [
      "secretsmanager:*",
      "kms:Describe*", "kms:Get*", "kms:List*",
      "kms:Create*", "kms:Delete*", "kms:Update*",
      "kms:Enable*", "kms:Disable*", "kms:Put*",
      "kms:Schedule*", "kms:Cancel*", "kms:Tag*", "kms:Untag*",
      "kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*",
      "kms:ReEncrypt*", "kms:Sign", "kms:Verify",
    ]
    resources = [
      "arn:aws:secretsmanager:*:${local.account_id}:secret:${local.name_prefix}-*",
      "arn:aws:kms:*:${local.account_id}:key/*",
      "arn:aws:kms:*:${local.account_id}:alias/${local.name_prefix}-*",
    ]
  }

  statement {
    sid     = "KmsGlobalActions"
    effect  = "Allow"
    actions = ["kms:CreateKey", "kms:ListAliases", "kms:ListKeys"]
    # These KMS actions apply to the entire service, not a specific key/alias ARN
    resources = ["*"]
  }

  statement {
    sid       = "IamServiceLinkedRoles"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/*"]
  }

  statement {
    sid     = "S3Assets"
    effect  = "Allow"
    actions = ["s3:*"]
    resources = [
      "arn:aws:s3:::${local.name_prefix}-assets-*",
      "arn:aws:s3:::${local.name_prefix}-assets-*/*",
    ]
  }

  statement {
    sid    = "Networking"
    effect = "Allow"
    actions = [
      "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute", "ec2:DescribeVpcs",
      "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute", "ec2:DescribeSubnets",
      "ec2:CreateInternetGateway", "ec2:DeleteInternetGateway",
      "ec2:AttachInternetGateway", "ec2:DetachInternetGateway", "ec2:DescribeInternetGateways",
      "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute",
      "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable", "ec2:DescribeRouteTables",
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
      "ec2:UpdateSecurityGroupRuleDescriptionsIngress", "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
      "ec2:DescribeSecurityGroups", "ec2:DescribeSecurityGroupRules", "ec2:ModifySecurityGroupRules",
      "ec2:CreateVpcEndpoint", "ec2:DeleteVpcEndpoints", "ec2:DescribeVpcEndpoints", "ec2:ModifyVpcEndpoint",
      "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface",
      "ec2:DescribeNetworkInterfaces", "ec2:ModifyNetworkInterfaceAttribute",
      "ec2:DescribeAvailabilityZones", "ec2:DescribeAccountAttributes",
      "ec2:DescribePrefixLists", "ec2:DescribeVpcAttribute",
      "ec2:CreateTags", "ec2:DeleteTags", "ec2:DescribeTags",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "Cognito"
    effect  = "Allow"
    actions = ["cognito-idp:*"]
    # DescribeUserPoolDomain and similar global APIs require "*" resource
    resources = [
      "arn:aws:cognito-idp:*:${local.account_id}:userpool/*",
      "*",
    ]
  }

  statement {
    sid     = "Ses"
    effect  = "Allow"
    actions = ["ses:*"]
    # VerifyEmailIdentity (SES v1) and sending-quota APIs require "*" resource
    resources = [
      "arn:aws:ses:*:${local.account_id}:identity/*",
      "arn:aws:ses:*:${local.account_id}:configuration-set/${local.name_prefix}-*",
      "*",
    ]
  }

  statement {
    sid     = "ObservabilityAndAlerts"
    effect  = "Allow"
    actions = ["logs:*", "cloudwatch:*", "sns:*", "xray:*"]
    resources = [
      "arn:aws:logs:*:${local.account_id}:log-group:*${local.name_prefix}*",
      "arn:aws:logs:*:${local.account_id}:log-group:*${local.name_prefix}*:*",
      "arn:aws:cloudwatch:*:${local.account_id}:alarm:${local.name_prefix}-*",
      "arn:aws:cloudwatch::${local.account_id}:dashboard/${local.name_prefix}-*",
      "arn:aws:sns:*:${local.account_id}:${local.name_prefix}-*",
      "*",
    ]
  }

  statement {
    sid    = "IamReadOnly"
    effect = "Allow"
    actions = [
      "iam:GetRole", "iam:ListRoles", "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies", "iam:GetRolePolicy",
      "iam:GetPolicy", "iam:GetPolicyVersion",
      "iam:ListPolicies", "iam:ListPolicyVersions",
      "iam:ListInstanceProfilesForRole", "iam:GetInstanceProfile",
      "iam:ListOpenIDConnectProviders", "iam:GetOpenIDConnectProvider",
      "iam:PassRole",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "IamCreateRolesWithBoundary"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:AttachRolePolicy",
      "iam:PutRolePolicy",
      "iam:TagRole",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/${local.name_prefix}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_arn]
    }
  }

  statement {
    sid    = "IamManageExistingRoles"
    effect = "Allow"
    actions = [
      "iam:DeleteRole", "iam:DetachRolePolicy", "iam:DeleteRolePolicy",
      "iam:UpdateRole", "iam:UpdateRoleDescription",
      "iam:TagRole", "iam:UntagRole",
      # PutRolePolicy on existing roles (e.g. updating deploy role inline policy
      # after import) — cannot use PermissionsBoundary condition here since
      # deploy roles deliberately have no boundary.
      "iam:PutRolePolicy",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/${local.name_prefix}-*"]
  }

  statement {
    sid    = "IamManagePolicies"
    effect = "Allow"
    actions = [
      "iam:CreatePolicy", "iam:DeletePolicy",
      "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
      "iam:TagPolicy", "iam:UntagPolicy",
    ]
    resources = ["arn:aws:iam::${local.account_id}:policy/${local.name_prefix}-*"]
  }

  statement {
    sid    = "IamOidcProvider"
    effect = "Allow"
    actions = [
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
    ]
    resources = [aws_iam_openid_connect_provider.github.arn]
  }
}
