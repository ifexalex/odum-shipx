# Short-lived demo environment — a lean, standalone deployment for a live link
# (e.g. a Founders Hub / investor demo), then `terraform destroy`. Dispatch-only:
# not in the dev→staging→prod promotion chain. Same schema as the other envs;
# kept cheap via max_acu=1, deletion_protection=false, and route53_zone_id="" (its
# default) → the CloudFront/WAF frontend module is count-gated off for the demo.
project_name          = "logistics"
environment           = "demo"
aws_region            = "eu-west-1"
min_acu               = 0.5
max_acu               = 1
deletion_protection   = false
elasticache_node_type = "cache.t4g.micro"
github_repo           = "ifexalex/odum-shipx"
