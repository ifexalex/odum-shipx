output "distribution_id" {
  description = "CloudFront distribution ID — used by CI to run invalidations."
  value       = aws_cloudfront_distribution.frontend.id
}

output "distribution_domain" {
  description = "CloudFront distribution domain name."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "s3_bucket_name" {
  description = "Frontend S3 bucket name — used by CI to sync dist/."
  value       = aws_s3_bucket.frontend.bucket
}

output "s3_bucket_arn" {
  description = "Frontend S3 bucket ARN."
  value       = aws_s3_bucket.frontend.arn
}

output "certificate_arn" {
  description = "ACM certificate ARN (us-east-1)."
  value       = aws_acm_certificate.frontend.arn
}

output "waf_web_acl_arn" {
  description = "WAFv2 Web ACL ARN protecting the CloudFront distribution."
  value       = aws_wafv2_web_acl.frontend.arn
}
