variable "subscription_name" {
  description = <<-EOT
    Logical name of the subscription this root is managing ("dev" or "hardened").
    Used only in outputs/plan readability — the subscription actually changed is
    the one in ARM_SUBSCRIPTION_ID. Kept explicit so a plan states, in words,
    which subscription it believes it is touching.
  EOT
  type        = string

  validation {
    condition     = contains(["dev", "hardened"], var.subscription_name)
    error_message = "subscription_name must be \"dev\" or \"hardened\"."
  }
}

variable "enable_paid_defender_plans" {
  description = <<-EOT
    Turn on the billable Microsoft Defender for Cloud plans.

    Defender is priced and enabled PER SUBSCRIPTION, not per resource group, so
    this cannot be scoped to one environment: every resource in the subscription
    is covered and billed. That is why dev must live in its own subscription —
    see README.md. Keep false for the dev subscription, true for the one holding
    staging/demo/prod.
  EOT
  type        = bool
  default     = false
}

variable "security_contact_email" {
  description = <<-EOT
    Address that receives Defender for Cloud alerts and the security-contact
    notices (Defender recommendations 77758c9d / 3869fbd7 / 9f97e78d). Required:
    an empty value leaves high-severity alerts going nowhere, which is the exact
    finding this closes.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.security_contact_email))
    error_message = "security_contact_email must be a single valid email address."
  }
}

variable "security_contact_phone" {
  description = "Optional E.164 phone number for the security contact. Empty = omit."
  type        = string
  default     = ""
}

variable "malware_scanning_cap_gb_per_month" {
  description = <<-EOT
    Per-storage-account monthly cap, in GB, on Defender for Storage malware
    scanning. Scanning is billed per GB scanned, so this is the blast-radius
    limit on an unexpected upload spike. Only applied when
    enable_paid_defender_plans is true.
  EOT
  type        = number
  default     = 500

  validation {
    condition     = var.malware_scanning_cap_gb_per_month > 0
    error_message = "malware_scanning_cap_gb_per_month must be greater than zero."
  }
}
