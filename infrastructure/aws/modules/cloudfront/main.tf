locals {
  name_prefix = "${var.project_name}-${var.environment}"
  # FQDN aliases: apex + wildcard for tenant subdomains (see 06_routing_rbac_and_navigation.md)
  domain_aliases = [var.domain_name, "*.${var.domain_name}"]
}

# ---------------------------------------------------------------------------
# S3 bucket — private, serves as the CloudFront origin
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "frontend" {
  # Account ID suffix prevents global name collision without being guessable.
  bucket = "${local.name_prefix}-frontend-${data.aws_caller_identity.current.account_id}"
  tags   = var.common_tags
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration { status = "Enabled" }
}

# All public access blocked — CloudFront reads via OAC, never directly.
resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------------------------------------------------------
# Origin Access Control — modern replacement for OAI
# ---------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-oac"
  description                       = "OAC for ShipX frontend (${var.environment})"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Bucket policy: allow CloudFront OAC to GetObject
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCloudFrontOACReadOnly"
      Effect = "Allow"
      Principal = {
        Service = "cloudfront.amazonaws.com"
      }
      Action   = "s3:GetObject"
      Resource = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
        }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# ACM certificate — must be in us-east-1 for CloudFront
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "frontend" {
  provider                  = aws.us_east_1
  domain_name               = var.domain_name
  subject_alternative_names = ["*.${var.domain_name}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = var.common_tags
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.frontend.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 60
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "frontend" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.frontend.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# ---------------------------------------------------------------------------
# CloudFront response-headers policy — CSP + security headers (Task 11)
# ---------------------------------------------------------------------------

resource "aws_cloudfront_response_headers_policy" "frontend" {
  name    = "${local.name_prefix}-frontend-headers"
  comment = "Security headers for ShipX frontend (${var.environment})"

  security_headers_config {
    content_type_options {
      override = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    xss_protection {
      mode_block = true
      protection = true
      override   = true
    }
    content_security_policy {
      content_security_policy = join("; ", [
        # Only scripts from this origin and the Cognito hosted UI
        "default-src 'self'",
        "script-src 'self'",
        # Styles: self + inline (Vite injects some at build time) + Google Fonts stylesheet
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        # Images from self and S3 (for tenant branding assets)
        "img-src 'self' data: https://*.amazonaws.com",
        # Fonts from self + Google Fonts files (fonts.gstatic.com)
        "font-src 'self' https://fonts.gstatic.com",
        # API calls: API Gateway + Cognito
        "connect-src 'self' https://${var.api_gateway_domain} https://${var.cognito_domain}",
        # No frames, objects, or base-tag overrides
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ])
      override = true
    }
  }
}

# ---------------------------------------------------------------------------
# Cache policies
# ---------------------------------------------------------------------------

# Hashed assets: cache a full year — content-addressed filenames (Vite default)
# make this safe; a new deploy produces new filenames.
resource "aws_cloudfront_cache_policy" "hashed_assets" {
  name        = "${local.name_prefix}-hashed-assets"
  default_ttl = 31536000
  max_ttl     = 31536000
  min_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }
  }
}

# index.html: never cached — always revalidate so new deploys propagate immediately.
resource "aws_cloudfront_cache_policy" "no_cache" {
  name        = "${local.name_prefix}-no-cache"
  default_ttl = 0
  max_ttl     = 0
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }
  }
}

# ---------------------------------------------------------------------------
# WAFv2 Web ACL — layer-7 protection for the CloudFront distribution.
# Scope CLOUDFRONT ⇒ must live in us-east-1 (same constraint as the ACM cert).
# CloudFront also gets AWS Shield Standard automatically (free L3/L4 DDoS);
# this adds the application layer: a per-IP rate limit + AWS-managed rule sets.
# ---------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "frontend" {
  provider    = aws.us_east_1
  name        = "${local.name_prefix}-frontend-waf"
  description = "ShipX frontend CloudFront protection (${var.environment})"
  scope       = "CLOUDFRONT"
  tags        = var.common_tags

  default_action {
    allow {}
  }

  # 1. Per-IP rate limit — the primary layer-7 DDoS / brute-force control.
  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # 2. Amazon IP reputation list — blocks IPs AWS tracks as bots / recon /
  #    DDoS sources before they consume any further rules.
  rule {
    name     = "aws-ip-reputation"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  # 3. Core rule set — common web exploits (XSS, LFI, protocol/size abuse).
  #    Safe on a static-asset origin (GET/HEAD/OPTIONS only; no large POSTs).
  rule {
    name     = "aws-common"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-common"
      sampled_requests_enabled   = true
    }
  }

  # 4. Known bad inputs — known exploit signatures (e.g. Log4Shell, path
  #    traversal, host-header injection).
  rule {
    name     = "aws-known-bad-inputs"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name_prefix}-waf-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name_prefix}-frontend-waf"
    sampled_requests_enabled   = true
  }
}

# ---------------------------------------------------------------------------
# CloudFront distribution
# ---------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  default_root_object = "index.html"
  price_class         = var.price_class
  aliases             = local.domain_aliases
  web_acl_id          = aws_wafv2_web_acl.frontend.arn
  comment             = "ShipX frontend (${var.environment})"
  tags                = var.common_tags

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Default behavior — serves everything from S3 with long-term cache.
  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "s3-frontend"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.hashed_assets.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id
    compress                   = true
  }

  # index.html — never cached so deploys propagate without manual invalidation
  ordered_cache_behavior {
    path_pattern               = "/index.html"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    target_origin_id           = "s3-frontend"
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.no_cache.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id
    compress                   = true
  }

  # SPA routing fallback — client-side routes like /admin/users/123 don't
  # exist as S3 keys. S3 returns 403 (NoSuchKey with a private bucket).
  # CloudFront intercepts and serves index.html with 200 so React Router
  # handles the path.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.frontend.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  depends_on = [aws_acm_certificate_validation.frontend]
}

# ---------------------------------------------------------------------------
# Route 53 records — apex + wildcard → CloudFront
# ---------------------------------------------------------------------------

resource "aws_route53_record" "apex" {
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "wildcard" {
  zone_id = var.route53_zone_id
  name    = "*.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}
