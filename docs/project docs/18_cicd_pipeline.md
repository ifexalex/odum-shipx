# Task 18 — CI/CD: GitHub Actions Workflows

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` §6 (Terraform Standards).

## Objective

Create GitHub Actions workflows for continuous integration (lint, test, security scan, vulnerability scan) and continuous deployment (Terraform plan/apply, Lambda deployment, smoke tests, rollback).

## Depends On

- All previous tasks complete

## Deliverables

### File: `.github/workflows/ci.yml`

**Triggers:** Pull request to `main`, push to `main`

```yaml
name: CI Pipeline

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy pydantic
      - run: ruff check .
      - run: mypy shared/ services/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: logistics_test
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements-dev.txt
      - name: Run migrations
        env:
          DATABASE_HOST: localhost
          DATABASE_PORT: 5432
          DATABASE_NAME: logistics_test
          DATABASE_USER: test_user
          DATABASE_PASSWORD: test_pass
        run: python scripts/migrate.py
      - name: Run unit tests
        run: pytest tests/unit/ -v --cov=services --cov=shared --cov-report=xml
      - name: Run tenant isolation tests
        env:
          DATABASE_HOST: localhost
          # ... same DB config
        run: pytest tests/tenant_isolation/ -v
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  security:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install bandit safety
      - name: SAST scan (bandit)
        run: bandit -r services/ shared/ -ll -q
      - name: Dependency vulnerability scan (safety)
        run: safety check -r requirements.txt
      - name: Trivy filesystem scan
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          severity: 'CRITICAL,HIGH'
          format: 'sarif'
          output: 'trivy-results.sarif'
      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: 'trivy-results.sarif'
```

### File: `.github/workflows/deploy.yml`

**Triggers:** Push to `main` (after CI passes), manual dispatch

```yaml
name: Deploy Pipeline

on:
  workflow_run:
    workflows: ["CI Pipeline"]
    types: [completed]
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: "Target environment"
        required: true
        type: choice
        options: [dev, staging, prod]

jobs:
  terraform:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment || 'dev' }}
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - name: Terraform Init
        working-directory: infrastructure
        run: terraform init -backend-config=environments/${{ env.ENVIRONMENT }}.backend.hcl
      - name: Terraform Plan
        working-directory: infrastructure
        run: terraform plan -var-file=environments/${{ env.ENVIRONMENT }}.tfvars -out=tfplan
      - name: Terraform Apply (dev auto, staging/prod manual)
        if: env.ENVIRONMENT == 'dev' || github.event_name == 'workflow_dispatch'
        working-directory: infrastructure
        run: terraform apply tfplan

  package-and-deploy:
    runs-on: ubuntu-latest
    needs: terraform
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      # Package shared layer
      - name: Package shared Lambda layer
        run: |
          mkdir -p build/layer/python
          cp -r shared/ build/layer/python/shared/
          pip install -r requirements-layer.txt -t build/layer/python/
          cd build/layer && zip -r ../shared-layer.zip python/
      - name: Deploy shared layer
        run: |
          aws lambda publish-layer-version \
            --layer-name logistics-shared-${{ env.ENVIRONMENT }} \
            --zip-file fileb://build/shared-layer.zip \
            --compatible-runtimes python3.12
      # Package and deploy each service
      - name: Deploy services
        run: |
          for service in tenant_management packing_list manifest tracking billing claims payment_release refunds notification metering; do
            cd services/$service
            zip -r ../../build/$service.zip .
            cd ../..
            aws lambda update-function-code \
              --function-name logistics-$service-${{ env.ENVIRONMENT }} \
              --zip-file fileb://build/$service.zip
          done
      # Deploy scheduled job Lambdas
      - name: Deploy scheduled jobs
        run: |
          for job in storage_fee dispute_escalation sla_check storage_reminders data_cleanup usage_aggregation release_expiry; do
            cd services/scheduled
            zip -r ../../build/scheduled-$job.zip $job.py
            cd ../..
            aws lambda update-function-code \
              --function-name logistics-$job-${{ env.ENVIRONMENT }} \
              --zip-file fileb://build/scheduled-$job.zip
          done

  smoke-tests:
    runs-on: ubuntu-latest
    needs: package-and-deploy
    if: inputs.environment != 'prod'
    steps:
      - uses: actions/checkout@v4
      - name: Run smoke tests
        run: |
          # Health check API
          curl -f https://api-${{ env.ENVIRONMENT }}.logistics.example.com/v1/health
          # Verify key endpoints return 401 without auth
          curl -s -o /dev/null -w "%{http_code}" \
            https://api-${{ env.ENVIRONMENT }}.logistics.example.com/v1/packing-lists | grep 401

  promote:
    runs-on: ubuntu-latest
    needs: smoke-tests
    if: inputs.environment == 'staging'
    environment: prod
    steps:
      - name: Manual approval gate
        run: echo "Approved for production deployment"
```

## Acceptance Criteria

- [ ] CI runs lint (ruff + mypy), unit tests, tenant isolation tests, and security scan
- [ ] Security scan includes bandit (SAST), safety (dependency vulns), and Trivy (filesystem scan)
- [ ] Trivy SARIF results uploaded to GitHub Security tab
- [ ] Tests run against a real PostgreSQL (GitHub Actions service container)
- [ ] Deploy packages shared layer (ARM64 compatible) and all Lambda functions
- [ ] Terraform plan/apply runs per environment using remote state (S3 + DynamoDB)
- [ ] Smoke tests verify API is reachable after deploy (health check + 401 on protected endpoints)
- [ ] Staging → prod requires manual approval via GitHub environment protection rules
- [ ] Pipeline uses GitHub environments for secrets management (AWS credentials per environment)
- [ ] Coverage report uploaded to Codecov
- [ ] Lambda layer packaged with `--platform manylinux2014_aarch64` for ARM64 compatibility

## Rollback Strategy

If smoke tests fail after deployment:

1. **Lambda rollback**: Re-deploy the previous function version:
   ```bash
   aws lambda update-function-code --function-name $FUNC --s3-bucket $BUCKET --s3-key previous/$FUNC.zip
   ```
2. **Terraform rollback**: Re-apply the previous state:
   ```bash
   terraform apply -var-file=environments/$ENV.tfvars -target=module.lambda
   ```
3. **Database rollback**: Alembic downgrade (if migration was applied):
   ```bash
   alembic downgrade -1
   ```

**Important:** Database migrations MUST be backward-compatible (additive only). Never drop columns or rename in the same release as code changes. Use a 2-phase migration strategy:
- Phase 1: Add new column (nullable), deploy code that writes to both
- Phase 2: Backfill, deploy code that reads from new column, drop old column
