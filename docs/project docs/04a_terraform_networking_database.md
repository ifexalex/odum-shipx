# Task 04a — Terraform: VPC, Networking, Aurora Serverless v2, RDS Proxy

## Objective

Create Terraform modules for the core networking layer (VPC, subnets) and the primary database (Aurora Serverless v2 PostgreSQL) with RDS Proxy for connection pooling.

## Depends On

- Task 01 (Terraform directory structure)

## Architecture Context

```
VPC (10.0.0.0/16)
├── Private Subnets (2 AZs for Aurora + Lambda)
│   ├── 10.0.1.0/24 (eu-west-1a)
│   └── 10.0.2.0/24 (eu-west-1b)
├── Public Subnets (for NAT if needed later)
│   ├── 10.0.101.0/24 (eu-west-1a)
│   └── 10.0.102.0/24 (eu-west-1b)
├── VPC Endpoints (S3, SQS, EventBridge, SES, Secrets Manager)
└── Security Groups
    ├── sg-lambda: allows outbound to Aurora, S3, SQS
    ├── sg-aurora: allows inbound from sg-lambda on port 5432
    └── sg-rds-proxy: allows inbound from sg-lambda
```

**Key decisions:**
- No NAT Gateway in v1 (notification Lambdas run outside VPC)
- VPC Endpoints for AWS services to avoid NAT costs
- Aurora Serverless v2: min 0.5 ACU, max 4 ACU, auto-pause after 10 min
- RDS Proxy for connection pooling (Lambda connections would otherwise exhaust Aurora limits)

## Deliverables

### File: `infrastructure/modules/networking/main.tf`

**Resources to create:**
- `aws_vpc` — 10.0.0.0/16, enable_dns_hostnames = true
- `aws_subnet` (private × 2 AZs) — for Aurora + VPC-attached Lambdas
- `aws_subnet` (public × 2 AZs) — for future NAT or ALB
- `aws_internet_gateway` — for public subnets
- `aws_route_table` (public) — routes to IGW
- `aws_route_table` (private) — local only (no NAT in v1)
- `aws_db_subnet_group` — for Aurora (private subnets)
- VPC Endpoints:
  - `aws_vpc_endpoint` (gateway) for S3
  - `aws_vpc_endpoint` (interface) for SQS, EventBridge, SES, Secrets Manager, CloudWatch Logs
- Security Groups:
  - `aws_security_group` "lambda" — egress to Aurora SG on 5432, egress to VPC endpoints
  - `aws_security_group` "aurora" — ingress from Lambda SG on 5432
  - `aws_security_group` "rds_proxy" — ingress from Lambda SG on 5432, egress to Aurora SG

**Outputs:** vpc_id, private_subnet_ids, public_subnet_ids, lambda_security_group_id, aurora_security_group_id, db_subnet_group_name

### File: `infrastructure/modules/networking/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "vpc_cidr" { type = string, default = "10.0.0.0/16" }
variable "availability_zones" { type = list(string), default = ["eu-west-1a", "eu-west-1b"] }
```

### File: `infrastructure/modules/aurora/main.tf`

**Resources to create:**
- `aws_rds_cluster` — Aurora Serverless v2, PostgreSQL 15.4, engine_mode = "provisioned"
  - serverlessv2_scaling_configuration: min_capacity = 0.5, max_capacity = 4
  - storage_encrypted = true
  - deletion_protection = true (prod), false (dev)
  - database_name = "logistics"
  - master_username = "postgres"
  - master_password from `aws_secretsmanager_secret_version`
  - skip_final_snapshot = false (prod), true (dev)
  - backup_retention_period = 7
- `aws_rds_cluster_instance` — instance_class = "db.serverless"
- `aws_secretsmanager_secret` — "logistics-db-password"
- `aws_secretsmanager_secret_version` — generated random password
- `aws_db_proxy` — RDS Proxy
  - engine_family = "POSTGRESQL"
  - auth: iam_auth = "DISABLED", secret_arn = db password secret
  - vpc_security_group_ids = [rds_proxy_sg_id]
  - vpc_subnet_ids = private_subnet_ids
- `aws_db_proxy_default_target_group` — connection_pool_config max_connections_percent = 80
- `aws_db_proxy_target` — target the Aurora cluster
- `aws_iam_role` for RDS Proxy to access Secrets Manager

**Outputs:** cluster_endpoint, reader_endpoint, rds_proxy_endpoint, db_name, db_secret_arn, cluster_arn

### File: `infrastructure/modules/aurora/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "db_subnet_group_name" { type = string }
variable "aurora_security_group_id" { type = string }
variable "rds_proxy_security_group_id" { type = string }
variable "min_acu" { type = number, default = 0.5 }
variable "max_acu" { type = number, default = 4 }
variable "auto_pause" { type = bool, default = true }
```

### File: `infrastructure/environments/dev.tfvars`

```hcl
project_name       = "logistics"
environment        = "dev"
aws_region         = "eu-west-1"
min_acu            = 0.5
max_acu            = 2
deletion_protection = false
```

### File: `infrastructure/environments/prod.tfvars`

```hcl
project_name       = "logistics"
environment        = "prod"
aws_region         = "eu-west-1"
min_acu            = 0.5
max_acu            = 4
deletion_protection = true
```

## ElastiCache Redis — Distributed Tenant Status Cache

Module: `infrastructure/modules/elasticache/`

| Resource | Detail |
|---|---|
| Cluster | `aws_elasticache_cluster` — single-node Redis 7.1 |
| Node type | `cache.t4g.micro` (~$11.52/month in eu-west-1) — overridable via `elasticache_node_type` tfvar |
| Subnet group | Reuses private subnets (same AZs as Lambda) |
| Security group | `sg-elasticache` — inbound 6379 from Lambda SG only |
| Lambda egress rule | `aws_security_group_rule` on Lambda SG → ElastiCache SG port 6379 |
| Endpoint output | `redis_host` — passed to lambda module as `REDIS_HOST` env var |

**Why single-node for all envs:** Tenant status values are strings with 60s TTL and explicit invalidation on write. A brief cache miss on node replacement causes a DB fallback — acceptable. Upgrade to `aws_elasticache_replication_group` with Multi-AZ for prod HA when needed.

## Acceptance Criteria

- [ ] VPC has DNS hostnames enabled
- [ ] Private subnets span 2 AZs
- [ ] Aurora Serverless v2 with PostgreSQL 15.4, encrypted at rest
- [ ] RDS Proxy configured with connection pooling at 80%
- [ ] VPC Endpoints created for S3, SQS, EventBridge, SES, Secrets Manager
- [ ] Security groups follow least-privilege (Lambda → Aurora only on 5432)
- [ ] DB password stored in Secrets Manager (not hardcoded)
- [ ] Outputs exported for use by other modules
- [ ] `terraform plan` succeeds with no errors
- [x] ElastiCache Redis `cache.t4g.micro` in private subnets — tenant status distributed cache
- [x] Lambda SG egress rule added for port 6379 to ElastiCache SG
