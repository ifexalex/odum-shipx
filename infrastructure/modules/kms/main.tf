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
# KMS key for application-level field encryption
# Encrypts highly sensitive PII columns that require enhanced protection:
#   - pickup_record.id_number       (passport / national ID numbers)
#   - refund_request.account_number (bank account numbers)
#   - refund_request.account_name   (bank account holder names)
#
# Each field uses envelope encryption: KMS generates a unique AES-256 data
# key per value; the encrypted data key is stored alongside the ciphertext
# so no plaintext key material is ever stored in the database.
# ---------------------------------------------------------------------------

resource "aws_kms_key" "field_encryption" {
  description             = "Field-level encryption for sensitive PII (${var.project_name} ${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.common_tags
}

resource "aws_kms_alias" "field_encryption" {
  name          = "alias/${var.project_name}-field-encryption-${var.environment}"
  target_key_id = aws_kms_key.field_encryption.key_id
}
