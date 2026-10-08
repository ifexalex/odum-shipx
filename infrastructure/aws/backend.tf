terraform {
  backend "s3" {
    # Configured per environment via -backend-config=environments/{env}.backend.hcl
    # bucket         = "logistics-terraform-state-{account_id}"
    # key            = "logistics/{environment}/terraform.tfstate"
    # region         = "eu-west-1"
    # dynamodb_table = "logistics-terraform-locks"
    # encrypt        = true
  }
}
