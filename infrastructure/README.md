# ShipX Infrastructure

Multi-cloud Terraform. ShipX runs on **one** cloud at a time; both targets are
kept so you can port between them with low effort (see the cloud-portability
notes in `docs/runbook.md`).

```
infrastructure/
  aws/        # AWS deployment (primary, production-ready) — root stack + modules/
  azure/      # Azure deployment (portability target; being built out) — root + modules/
  common/     # Cross-cloud shared Terraform (naming + tagging) — no cloud resources
```

| Folder | What it is | State |
|---|---|---|
| **`aws/`** | The full AWS stack: VPC, Aurora Serverless v2, Lambda, API Gateway, Cognito, S3+CloudFront(+WAF), ElastiCache, SQS, EventBridge, SES, KMS, Secrets Manager, VPC endpoints. Root `*.tf` + `modules/` + `environments/` + `tests/`. | Production-ready (not yet applied) |
| **`azure/`** | The Azure stack, built incrementally. Today: frontend (Blob + Front Door Standard). See `azure/README.md` for the per-service status matrix. | In progress |
| **`common/`** | The only thing identical across clouds — the standard tag set + `<project>-<environment>` name prefix (`common/naming`), consumed by both roots so conventions can't drift. | Stable |

## Deploy

Each cloud is a separate Terraform root with its own state — `cd` into one and
apply. **Do not** apply both; pick the cloud you're running on.

```bash
# AWS
cd infrastructure/aws
terraform init -backend-config=environments/prod.backend.hcl
terraform apply -var-file=environments/prod.tfvars

# Azure (see azure/README.md for the frontend publish/purge steps)
cd infrastructure/azure
terraform init
terraform apply -var 'environment=prod' -var 'api_base_url=https://<api-host>'
```

CI: `.github/workflows/terraform.yml` drives the AWS stack (triggered on
`infrastructure/aws/**` + `infrastructure/common/**`). An Azure workflow is a
follow-up.
