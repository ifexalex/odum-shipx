# Local / LocalStack environment overrides
# Apply with: tflocal apply -var-file=environments/dev.tfvars -var-file=environments/local.tfvars

project_name = "logistics"
environment  = "dev"
aws_region   = "eu-west-1"

# Override Lambda env vars so they connect to the local Postgres instead of
# the mock Aurora endpoint that LocalStack creates.
# host.docker.internal resolves to the host machine from inside Lambda's Docker container.
local_env_overrides = {
  DATABASE_HOST        = "host.docker.internal"
  DATABASE_PORT        = "5432"
  DATABASE_NAME        = "logistics"
  DATABASE_USER        = "postgres"
  DATABASE_PASSWORD    = "localpassword"
  DB_SECRET_ARN        = "" # disables Secrets Manager lookup
  ENVIRONMENT          = "local"
  LOG_LEVEL            = "DEBUG"
  AWS_XRAY_SDK_ENABLED = "false"
  _X_AMZN_TRACE_ID     = "Root=1-00000000-000000000000000000000000"
}
