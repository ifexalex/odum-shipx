output "common_tags" {
  description = "Standard tag set applied to all resources."
  value       = var.cloud == "" ? local.base_tags : merge(local.base_tags, { Cloud = var.cloud })
}

output "name_prefix" {
  description = "Resource name prefix: <project>-<environment>."
  value       = "${var.project_name}-${var.environment}"
}
