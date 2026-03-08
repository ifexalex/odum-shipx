# infrastructure/tests/networking.tftest.hcl
# Run: cd infrastructure && terraform test
# Validates networking module structure without touching real AWS.

mock_provider "aws" {}

variables {
  project_name       = "shipx"
  environment        = "test"
  availability_zones = ["eu-west-1a", "eu-west-1b"]
}

run "creates_vpc_and_subnets" {
  command = plan

  module {
    source = "./modules/networking"
  }

  assert {
    condition     = aws_vpc.main.enable_dns_hostnames == true
    error_message = "VPC must have DNS hostnames enabled"
  }

  assert {
    condition     = length(aws_subnet.private) == 2
    error_message = "Expected 2 private subnets (one per AZ)"
  }

  assert {
    condition     = length(aws_subnet.public) == 2
    error_message = "Expected 2 public subnets (one per AZ)"
  }
}

run "creates_security_groups" {
  command = plan

  module {
    source = "./modules/networking"
  }

  assert {
    condition     = aws_security_group.lambda.name == "shipx-test-sg-lambda"
    error_message = "Lambda SG name must follow naming convention"
  }

  assert {
    condition     = aws_security_group.aurora.name == "shipx-test-sg-aurora"
    error_message = "Aurora SG name must follow naming convention"
  }
}

run "creates_vpc_endpoints" {
  command = plan

  module {
    source = "./modules/networking"
  }

  assert {
    condition     = aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway"
    error_message = "S3 endpoint must be a Gateway type (free)"
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface) == 5
    error_message = "Expected 5 interface endpoints: sqs, events, email-smtp, secretsmanager, logs"
  }
}
