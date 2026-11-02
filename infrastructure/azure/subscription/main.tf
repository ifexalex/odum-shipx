# ---------------------------------------------------------------------------
# ShipX — Azure SUBSCRIPTION-scoped security baseline.
#
# Separate from the per-environment roots (../) on purpose. Defender for Cloud
# plans and the security contact are properties of a SUBSCRIPTION, not of a
# resource group, so they cannot be owned by an environment stack: three
# environments sharing one subscription would each try to own the same settings
# and fight over them on every apply.
#
# Apply once per subscription:
#   terraform init  -backend-config=environments/hardened.backend.hcl
#   terraform apply -var-file=environments/hardened.tfvars
#
# Closes these Defender for Cloud recommendations:
#   f0fb2a7e  Defender for Resource Manager                     (High,  paid)
#   e599a9fe  Defender for Containers                           (High,  paid)
#   e0e431eb  Defender CSPM                                     (High,  paid)
#   b6a28450  Defender for open-source relational databases     (High,  paid)
#   b1af52e4  Defender for Key Vault                            (High,  paid)
#   26f0d5bb  Defender for Storage + malware/sensitive data     (High,  paid)
#   9f97e78d  Email notification to subscription owner          (Medium, free)
#   3869fbd7  Email notification for high severity alerts       (Low,   free)
#   77758c9d  Subscription security contact address             (Low,   free)
#
# NOT closed here (deliberately — they are not subscription settings):
#   2c79b4af  "More than one owner assigned to subscriptions" (High). This needs
#             a second human being granted Owner. Terraform could assign the
#             role, but hardcoding a person's object id into version control is
#             worse than an operator action — see docs/runbook.md.
# ---------------------------------------------------------------------------

locals {
  # Explicit tiering rather than only creating resources when paid: writing
  # "Free" into state makes the dev subscription's exemption an asserted fact
  # that drifts loudly if someone enables a plan in the portal, instead of an
  # absence Terraform would silently ignore.
  defender_tier = var.enable_paid_defender_plans ? "Standard" : "Free"

  # resource_type → why this plan exists for ShipX. for_each keeps the six
  # plans one block; StorageAccounts is separate below (it needs sub-plan
  # extensions that the others do not have).
  defender_plans = {
    # Watches control-plane operations — the plan that catches a compromised
    # deploy identity doing something it has never done before.
    Arm = "resource-manager control-plane threat detection"

    # Container Apps run every ShipX service; this covers image vulnerability
    # assessment and runtime detections for them.
    Containers = "container image + runtime protection for the Container Apps"

    # The posture/attack-path engine. This is the plan that actually moves the
    # secure score, as opposed to only alerting.
    CloudPosture = "posture management + attack-path analysis"

    # Postgres Flexible Server holds every tenant's data, including the
    # KMS-encrypted PII columns. Also closes bf2541d8 at the resource level.
    OpenSourceRelationalDatabases = "anomalous-access detection on Postgres Flexible Server"

    # The vault holds the envelope-encryption key for pickup_record.id_number
    # and refund_request.account_*; unusual access to it is a breach signal.
    KeyVaults = "unusual key/secret access detection"
  }
}

resource "azurerm_security_center_subscription_pricing" "plan" {
  for_each = local.defender_plans

  tier          = local.defender_tier
  resource_type = each.key
}

# Storage is the one plan with sub-plan extensions. DefenderForStorageV2 is the
# per-account-priced plan (the classic per-transaction plan is retired); malware
# scanning and sensitive-data discovery are the two extensions recommendation
# 26f0d5bb explicitly requires, so enabling the plan without them would leave
# the finding Unhealthy.
resource "azurerm_security_center_subscription_pricing" "storage" {
  tier          = local.defender_tier
  resource_type = "StorageAccounts"
  subplan       = var.enable_paid_defender_plans ? "DefenderForStorageV2" : null

  # Extensions are only meaningful on the Standard tier; on Free the plan is off
  # and Azure rejects extension configuration.
  dynamic "extension" {
    for_each = var.enable_paid_defender_plans ? [1] : []
    content {
      name = "OnUploadMalwareScanning"
      additional_extension_properties = {
        # Billed per GB scanned — cap it so a runaway upload cannot produce a
        # surprise invoice.
        CapGBPerMonthPerStorageAccount = tostring(var.malware_scanning_cap_gb_per_month)
      }
    }
  }

  dynamic "extension" {
    for_each = var.enable_paid_defender_plans ? [1] : []
    content {
      name = "SensitiveDataDiscovery"
    }
  }
}

# ─── Security contact + alert routing (free, every subscription) ─────────────
# Azure supports exactly one contact per subscription and it must be named
# "default1". alerts_to_admins routes to subscription owners (9f97e78d); email
# routes to the platform address (77758c9d); together they satisfy 3869fbd7.
resource "azurerm_security_center_contact" "default" {
  name  = "default1"
  email = var.security_contact_email
  phone = var.security_contact_phone != "" ? var.security_contact_phone : null

  alert_notifications = true
  alerts_to_admins    = true
}
