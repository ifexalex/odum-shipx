output "subscription_name" {
  description = "Logical name of the subscription this state owns."
  value       = var.subscription_name
}

output "subscription_id" {
  description = "The subscription actually configured by this apply."
  value       = data.azurerm_subscription.current.subscription_id
}

output "defender_tier" {
  description = "Tier applied to every Defender plan (Standard = billable, Free = off)."
  value       = local.defender_tier
}

output "defender_plans_enabled" {
  description = "Defender plans this root owns, with the reason each is enabled."
  value       = local.defender_plans
}

data "azurerm_subscription" "current" {}
