# ---------------------------------------------------------------------------
# ShipX — Azure root stack (portability target; alongside the AWS stack in
# ../). Build out incrementally; the frontend (Blob static site + Front Door
# Standard) is the first module, mirroring the AWS CloudFront module.
# ---------------------------------------------------------------------------

resource "azurerm_resource_group" "main" {
  name     = "${local.name_prefix}-rg"
  location = var.location
  tags     = local.common_tags
}

module "frontend" {
  source = "./modules/frontend"

  name_prefix             = local.name_prefix
  resource_group_name     = azurerm_resource_group.main.name
  location                = var.location
  common_tags             = local.common_tags
  content_security_policy = local.content_security_policy
}
