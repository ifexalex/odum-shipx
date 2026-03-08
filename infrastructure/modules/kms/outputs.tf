output "field_encryption_key_arn" {
  description = "KMS key ARN for field-level PII encryption"
  value       = aws_kms_key.field_encryption.arn
}

output "field_encryption_key_id" {
  description = "KMS key ID for field-level PII encryption"
  value       = aws_kms_key.field_encryption.key_id
}
