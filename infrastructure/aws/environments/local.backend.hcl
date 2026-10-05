# LocalStack S3 backend config for tflocal
# Usage: tflocal init -backend-config=environments/local.backend.hcl
bucket                      = "logistics-terraform-state-local"
key                         = "logistics/local/terraform.tfstate"
region                      = "eu-west-1"
endpoint                    = "http://localhost:4566"
skip_credentials_validation = true
skip_metadata_api_check     = true
force_path_style            = true
access_key                  = "test"
secret_key                  = "test"
