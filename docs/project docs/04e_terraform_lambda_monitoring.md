# Task 04e — Terraform: Lambda Functions, IAM, CloudWatch, Alarms

## Objective

Create Terraform modules for all Lambda functions, their IAM roles/policies, Lambda Layer, CloudWatch dashboards, and alerting.

## Depends On

- Tasks 04a (VPC, subnets, security groups), 04b (Cognito), 04c (API Gateway), 04d (S3, SQS, EventBridge)

## Lambda Functions to Create

### VPC-Attached Lambdas (need database access):

| Function Name | Runtime | Memory | Timeout | Trigger | VPC |
|---|---|---|---|---|---|
| `logistics-tenant-mgmt-{env}` | python3.12 | 512MB | 30s | API Gateway | Yes |
| `logistics-packing-list-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-manifest-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-tracking-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-billing-{env}` | python3.12 | 512MB | 30s | API Gateway | Yes |
| `logistics-claims-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-payment-release-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-refunds-{env}` | python3.12 | 256MB | 30s | API Gateway | Yes |
| `logistics-metering-{env}` | python3.12 | 256MB | 60s | SQS (metering queue) | Yes |

### Non-VPC Lambdas (external API calls, no DB):

| Function Name | Runtime | Memory | Timeout | Trigger |
|---|---|---|---|---|
| `logistics-notif-sms-{env}` | python3.12 | 256MB | 60s | SQS (sms queue) |
| `logistics-notif-whatsapp-{env}` | python3.12 | 256MB | 60s | SQS (whatsapp queue) |
| `logistics-notif-email-{env}` | python3.12 | 256MB | 60s | SQS (email queue) |

### Scheduled Lambdas (cron jobs, need DB):

| Function Name | Trigger | VPC |
|---|---|---|
| `logistics-storage-fee-{env}` | EventBridge schedule (daily 00:00) | Yes |
| `logistics-dispute-escalation-{env}` | EventBridge schedule (every 6h) | Yes |
| `logistics-sla-check-{env}` | EventBridge schedule (every 4h) | Yes |
| `logistics-storage-reminders-{env}` | EventBridge schedule (daily 08:00) | Yes |
| `logistics-data-cleanup-{env}` | EventBridge schedule (daily 02:00) | Yes |
| `logistics-usage-aggregation-{env}` | EventBridge schedule (hourly) | Yes |
| `logistics-release-expiry-{env}` | EventBridge schedule (daily 00:00) | Yes |

## Deliverables

### Module: `infrastructure/modules/lambda/main.tf`

**For each Lambda:**
- `aws_lambda_function` with:
  - runtime = "python3.12"
  - handler = "{service}.handler.lambda_handler"
  - layers = [shared_layer_arn]
  - VPC config (where applicable): subnet_ids, security_group_ids
  - Environment variables: DATABASE_HOST (RDS Proxy endpoint), DATABASE_NAME, DATABASE_USER, DB_SECRET_ARN, S3_BUCKET, EVENT_BUS_NAME, COGNITO_USER_POOL_ID, ENVIRONMENT
  - reserved_concurrent_executions = null (no limit for v1)

- `aws_lambda_layer_version` — "logistics-shared-{env}" (the shared/ code as a layer)

- `aws_iam_role` per Lambda with:
  - AWSLambdaBasicExecutionRole (CloudWatch Logs)
  - AWSLambdaVPCAccessExecutionRole (for VPC Lambdas)
  - Custom policy for each service's specific needs

**IAM Policies per Lambda group:**

| Lambda | Permissions Needed |
|---|---|
| All VPC Lambdas | Secrets Manager (read DB password), RDS Proxy connect |
| tenant_management | Cognito (AdminCreateUser, AdminAddUserToGroup, AdminDisableUser, etc.) |
| claims | S3 (PutObject, GetObject for presigned URLs — scoped to bucket) |
| notification (SMS) | External API access (Africa's Talking) |
| notification (WhatsApp) | External API access (Meta Cloud API) |
| notification (email) | SES (SendEmail) |
| all API Lambdas | EventBridge (PutEvents) |
| metering | SQS (ReceiveMessage, DeleteMessage on metering queue) |
| scheduled jobs | EventBridge, same as their respective service |

- `aws_lambda_event_source_mapping` for SQS-triggered Lambdas
- `aws_lambda_permission` for API Gateway to invoke API Lambdas
- `aws_lambda_permission` for EventBridge to invoke scheduled Lambdas

### CloudWatch Resources:

- `aws_cloudwatch_log_group` per Lambda — retention = 30 days (dev), 90 days (prod)
- `aws_cloudwatch_dashboard` — "logistics-{env}" with key metrics
- `aws_cloudwatch_metric_alarm`:

| Alarm | Metric | Threshold | Action |
|---|---|---|---|
| Lambda Errors | Errors > 5 in 5 min | > 5 | SNS topic |
| API 5xx | 5XXError > 1% | > 1% | SNS topic |
| Aurora Connections | DatabaseConnections > 80% | > 40 | SNS topic |
| SQS DLQ Messages | ApproximateNumberOfMessagesVisible > 0 | > 0 | SNS topic |
| Lambda Duration P95 | Duration p95 > 5000ms | > 5000 | SNS topic |

- `aws_sns_topic` — "logistics-alerts-{env}" (email subscription for dev team)

## Acceptance Criteria

- [ ] All Lambda functions created with correct runtime, memory, timeout
- [ ] VPC-attached Lambdas in private subnets with Lambda security group
- [ ] Notification Lambdas outside VPC (no NAT Gateway needed)
- [ ] Shared Lambda Layer created and attached to all functions
- [ ] IAM roles follow least-privilege (each Lambda gets only needed permissions)
- [ ] SQS event source mappings for notification + metering Lambdas
- [ ] EventBridge scheduled rule targets for cron job Lambdas
- [ ] CloudWatch log groups with appropriate retention
- [ ] 5 CloudWatch alarms configured
- [ ] SNS topic for alerts
- [ ] `terraform plan` succeeds
