# Shared naming + tagging comes from ../common/naming so AWS and Azure stay
# consistent. local.common_tags / local.name_prefix are kept as aliases so the
# rest of this stack is unchanged.
module "naming" {
  source       = "../common/naming"
  project_name = var.project_name
  environment  = var.environment
  cloud        = "aws"
}

locals {
  common_tags = module.naming.common_tags
  name_prefix = module.naming.name_prefix
}
