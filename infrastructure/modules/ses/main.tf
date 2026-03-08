locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }
}

# ---------------------------------------------------------------------------
# Email identity — AWS sends a verification email on first apply.
# Used by Notification Lambda to send outbound emails via SES.
# ---------------------------------------------------------------------------

resource "aws_ses_email_identity" "from" {
  email = var.from_email
}
