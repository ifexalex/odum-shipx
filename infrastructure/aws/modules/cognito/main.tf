locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }
}

# ---------------------------------------------------------------------------
# User Pool
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users-${var.environment}"

  # Users identify with email address
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Password policy
  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # MFA optional (for admin roles)
  mfa_configuration = "OPTIONAL"
  software_token_mfa_configuration {
    enabled = true
  }

  # Standard required attributes
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = true
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  schema {
    name                     = "name"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = true
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  # Custom attributes
  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = false # Immutable after creation
    required                 = false
    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  schema {
    name                     = "role"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  # Admin-only user creation — no self-registration
  admin_create_user_config {
    allow_admin_create_user_only = true
    invite_message_template {
      email_subject = "Welcome to the Logistics Platform"
      email_message = "Welcome to the Logistics Platform. Your username is {username} and your temporary password is {####}. Please sign in and change your password."
      sms_message   = "Logistics Platform: username {username}, temporary password {####}"
    }
  }

  # Account recovery via email
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Use Cognito default email sender for now (SES configured in 04d)
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# App Client (web / Lambda admin flows)
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name_prefix}-web-client"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false # Public client — no client secret

  explicit_auth_flows = [
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Token validity
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Read all standard attributes + custom claims
  read_attributes = [
    "email",
    "email_verified",
    "name",
    "phone_number",
    "phone_number_verified",
    "sub",
    "updated_at",
    "custom:tenant_id",
    "custom:role",
  ]

  # Write standard attributes only — custom:tenant_id intentionally excluded
  # to prevent users from modifying their own tenant association
  write_attributes = [
    "email",
    "name",
    "phone_number",
  ]

  prevent_user_existence_errors = "ENABLED"

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls
}

# ---------------------------------------------------------------------------
# Hosted UI domain (Cognito-managed prefix domain)
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# ---------------------------------------------------------------------------
# Platform admins' pool (platform audit Phase 1b, decision D3)
#
# Platform admins sign in here, never in the tenant pool above. MFA is ON for every user (TOTP only: no SMS, so no
# SIM-swap path), and the password policy is stricter. A token from this pool is a platform admin by issuer alone
# (shared/platform_identity.py); the platform directory (platform_user) decides who they are and what they may do.
# Sessions are short: 15-minute ID tokens and an 8-hour refresh token, so a stolen session dies within a working day.
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "platform" {
  name = "${var.project_name}-platform-admins-${var.environment}"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 2
  }

  mfa_configuration = "ON"
  software_token_mfa_configuration {
    enabled = true
  }

  schema {
    name                     = "email"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = true
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  schema {
    name                     = "name"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = true
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  # Kept so the shared provisioning code (shared/providers/aws/cognito.py create_user) works unchanged; the backend
  # never reads these from a platform-pool token.
  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = false
    required                 = false
    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  schema {
    name                     = "role"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
    invite_message_template {
      email_subject = "Your ShipX platform admin account"
      email_message = "You have been made a ShipX platform admin. Your username is {username} and your temporary password is {####}. Sign in through the platform admin sign-in; you will set a new password and an authenticator app."
      sms_message   = "ShipX platform admin: username {username}, temporary password {####}"
    }
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  deletion_protection = "ACTIVE"

  tags = merge(local.common_tags, { Purpose = "platform-admins" })
}

resource "aws_cognito_user_pool_client" "platform_web" {
  name         = "${local.name_prefix}-platform-web-client"
  user_pool_id = aws_cognito_user_pool.platform.id

  generate_secret = false

  # SRP for the console's sign-in; USER_PASSWORD_AUTH for the server-side step-up re-authentication
  # (services/tenant_management/step_up.py), which signs in as the caller with password + TOTP.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  access_token_validity  = 15
  id_token_validity      = 15
  refresh_token_validity = 8
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }

  read_attributes  = ["email", "email_verified", "name", "sub", "updated_at"]
  write_attributes = ["name"]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}
