bucket         = "logistics-terraform-state-ACCOUNT_ID"
key            = "logistics/dev/terraform.tfstate"
region         = "eu-west-1"
dynamodb_table = "logistics-terraform-locks"
encrypt        = true
