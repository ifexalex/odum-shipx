# infrastructure/tests/sqs.tftest.hcl
# Validates SQS module creates the expected queues and DLQs.

mock_provider "aws" {}

variables {
  project_name = "shipx"
  environment  = "test"
}

run "creates_queues_with_dlqs" {
  command = plan

  module {
    source = "./modules/sqs"
  }

  assert {
    condition     = length(aws_sqs_queue.queues) > 0
    error_message = "Expected at least one SQS queue"
  }

  assert {
    condition     = length(aws_sqs_queue.dlqs) == length(aws_sqs_queue.queues)
    error_message = "Every queue must have a matching DLQ"
  }
}

run "dlq_redrive_policy_set" {
  command = plan

  module {
    source = "./modules/sqs"
  }

  assert {
    condition     = alltrue([for q in aws_sqs_queue.queues : q.redrive_policy != null])
    error_message = "Every main queue must have a redrive policy pointing at its DLQ"
  }
}
