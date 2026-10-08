resource_group_name  = "shipx-tfstate-rg"
storage_account_name = "shipxtfstate" # globally-unique; set to your bootstrap account (see README)
container_name       = "tfstate"
key                  = "azure/demo/terraform.tfstate"
use_azuread_auth     = true
