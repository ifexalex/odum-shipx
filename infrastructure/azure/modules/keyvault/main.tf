# ---------------------------------------------------------------------------
# Key Vault — the Azure analogue of KMS + Secrets Manager, and the target of
# shared/providers/azure/keyvault.py (KeyVaultKeyProvider, RSA wrap/unwrap) and
# keyvault_secrets.py (KeyVaultSecretsProvider).
#
# Standard SKU (per-operation pricing — pennies at test volume). Access is
# granted to the deploying principal via an access policy so Terraform can
# create the key/secret in the same apply (simpler + more reliable for a test
# account than RBAC role-assignment propagation); the app's managed identity is
# added to `extra_object_ids` once the compute module exists.
# ---------------------------------------------------------------------------

data "azurerm_client_config" "current" {}

resource "random_string" "kv_suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_key_vault" "main" {
  # Vault names: 3–24 chars, start with a letter, alphanumeric + hyphens, global.
  name                = substr("${var.name_prefix}-kv-${random_string.kv_suffix.result}", 0, 24)
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # Test-friendly: soft-delete is always on; leave purge protection off so a
  # test vault can be fully removed. Turn purge_protection ON for prod.
  purge_protection_enabled = false

  # Deploying principal: manage keys + secrets (so the resources below apply).
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    key_permissions = [
      "Create", "Get", "List", "Delete", "Purge", "Update",
      "WrapKey", "UnwrapKey", "GetRotationPolicy",
    ]
    secret_permissions = ["Set", "Get", "List", "Delete", "Purge"]
  }

  # Additional principals (e.g. the app's managed identity) — wrap/unwrap keys
  # and read secrets at runtime. Empty until the compute module supplies one.
  dynamic "access_policy" {
    for_each = toset(var.extra_object_ids)
    content {
      tenant_id          = data.azurerm_client_config.current.tenant_id
      object_id          = access_policy.value
      key_permissions    = ["Get", "WrapKey", "UnwrapKey"]
      secret_permissions = ["Get"]
    }
  }

  tags = var.common_tags
}

# Envelope-encryption key: KeyVaultKeyProvider wraps a 32-byte data key with
# this via RSA-OAEP-256.
resource "azurerm_key_vault_key" "data_key" {
  name         = "shipx-data-key"
  key_vault_id = azurerm_key_vault.main.id
  key_type     = "RSA"
  key_size     = 2048
  key_opts     = ["wrapKey", "unwrapKey", "encrypt", "decrypt"]
}

# Smoke secret so the SecretsProvider can be verified end-to-end against the
# real vault (get_secret("shipx-smoke-secret") -> "ok").
resource "azurerm_key_vault_secret" "smoke" {
  name         = "shipx-smoke-secret"
  value        = "ok"
  key_vault_id = azurerm_key_vault.main.id
}
