variable "project_name" {
  description = "Project name used in resource naming and tagging"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "common_tags" {
  description = "Tags applied to all resources"
  type        = map(string)
}

variable "domain_name" {
  description = "Root domain (e.g. shipx.co). CloudFront will serve shipx.co and *.shipx.co."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone ID for the domain in Route 53."
  type        = string
}

variable "api_gateway_domain" {
  description = "API Gateway domain used in the CSP connect-src directive (e.g. abc123.execute-api.eu-west-1.amazonaws.com)."
  type        = string
}

variable "cognito_domain" {
  description = "Cognito domain used in the CSP connect-src directive (e.g. cognito-idp.eu-west-1.amazonaws.com)."
  type        = string
}

variable "price_class" {
  description = "CloudFront price class. PriceClass_100 (US/EU only) keeps costs low for a Nigeria-China logistics app whose ops staff are in those regions."
  type        = string
  default     = "PriceClass_100"
}

variable "waf_rate_limit" {
  description = "WAF rate-based rule: max requests per IP per 5-minute window before blocking (layer-7 DDoS / brute-force). Raise for offices behind a shared NAT IP; lower to tighten."
  type        = number
  default     = 2000
}
