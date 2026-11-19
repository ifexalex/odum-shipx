variable "name_prefix" {
  description = "Resource name prefix (e.g. shipx-prod)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}

variable "retention_in_days" {
  description = "Log Analytics retention."
  type        = number
  default     = 30
}

variable "alerts_email" {
  description = "Where failure alerts go. Empty (the default) creates no alert rules and no action group, at no cost."
  type        = string
  default     = ""
}

variable "notification_failure_rate_percent" {
  description = "Alert when more than this percentage of notification sends fail in 15 minutes."
  type        = number
  default     = 20
}

variable "notification_rate_min_attempts" {
  description = "Sends needed in the 15-minute window before the failure rate is judged."
  type        = number
  default     = 5
}
