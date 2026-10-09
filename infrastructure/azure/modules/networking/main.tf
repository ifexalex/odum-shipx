# ---------------------------------------------------------------------------
# Networking — the Azure analogue of the AWS `networking` module (VPC).
#
# A VNet with three purpose-built subnets:
#   - container_apps   : delegated to Microsoft.App/environments (the Phase-3
#                        Container Apps Environment injects here). /23 is the
#                        Container Apps minimum.
#   - postgres         : delegated to the Flexible Server service for VNet
#                        integration (private DB — no public endpoint).
#   - private_endpoints: for private endpoints (Redis/Service Bus/etc. later);
#                        network policies disabled so PEs can bind.
#
# Only Postgres + Container Apps are VNet-coupled; Service Bus / Event Grid /
# ACS / Redis(Basic) use keyed public endpoints like the storage/keyvault
# modules, so they need nothing here.
# ---------------------------------------------------------------------------

resource "azurerm_virtual_network" "main" {
  name                = "${var.name_prefix}-vnet"
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = [var.vnet_cidr]
  tags                = var.common_tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "container-apps"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.container_apps_subnet_cidr]

  delegation {
    name = "container-apps-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.postgres_subnet_cidr]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                              = "private-endpoints"
  resource_group_name               = var.resource_group_name
  virtual_network_name              = azurerm_virtual_network.main.name
  address_prefixes                  = [var.private_endpoints_subnet_cidr]
  private_endpoint_network_policies = "Disabled"
}
