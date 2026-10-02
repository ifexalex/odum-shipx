variable "project_name" {
  description = "Project name used in resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "cognito_user_pool_id" {
  description = "Cognito User Pool ID for the JWT authorizer"
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito App Client ID used as the JWT audience"
  type        = string
}

variable "cognito_issuer_url" {
  description = "Cognito issuer URL (https://cognito-idp.{region}.amazonaws.com/{pool_id})"
  type        = string
}

variable "lambda_arns" {
  description = "Map of service_name → Lambda invoke ARN. Integrations and routes are only created for keys present in this map."
  type        = map(string)
  default     = {}
}

variable "cors_allow_origins" {
  description = "List of allowed CORS origins for the API"
  type        = list(string)
  default     = ["http://localhost:3000"]

  # A wildcard origin combined with allow_credentials = true (set unconditionally
  # below, for the /v1/auth/* httpOnly session cookie) is rejected by browsers at
  # runtime anyway — fail the plan instead of shipping a CORS config that quietly
  # never works.
  validation {
    condition     = !contains(var.cors_allow_origins, "*")
    error_message = "cors_allow_origins must not contain \"*\" — this API sets allow_credentials = true, which browsers refuse to honor alongside a wildcard origin."
  }
}
