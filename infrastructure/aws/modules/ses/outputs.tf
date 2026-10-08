output "ses_identity_arn" {
  description = "SES email identity ARN — used for IAM policy grants"
  value       = aws_ses_email_identity.from.arn
}
