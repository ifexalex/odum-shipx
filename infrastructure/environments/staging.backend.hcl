bucket         = "logistics-terraform-state-ACCOUNT_ID"
key            = "logistics/staging/terraform.tfstate"
region         = "eu-west-1"
dynamodb_table = "logistics-terraform-locks"
encrypt        = true
