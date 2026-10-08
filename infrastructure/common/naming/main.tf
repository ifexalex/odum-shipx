# ---------------------------------------------------------------------------
# Shared naming + tagging — the one thing that is genuinely identical across
# clouds. Both the AWS (../../aws) and Azure (../../azure) roots call this so
# tag keys, cost-centre, and the "<project>-<environment>" name prefix stay
# consistent wherever ShipX is deployed. (No resources, no provider — pure
# inputs → outputs.)
# ---------------------------------------------------------------------------

locals {
  base_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }
}
