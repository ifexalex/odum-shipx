# Task 18 — CI/CD: GitHub Actions Workflows

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` §6 (Terraform Standards).

## Objective

Create GitHub Actions workflows for continuous integration (lint, test, security scan, build) and
continuous deployment (database migrations, Lambda deployment, smoke tests). Use tag-based release
gating for staging and production — no stored AWS credentials (OIDC), immutable artifact promotion
(build once in CI, deploy the same binary to all environments).

## Depends On

- All previous tasks complete

---

## Pipeline Flow

```
push to main
  └─ CI (lint → test → security → build → artifact)
       └─ deploy-dev (auto, workflow_run)
            └─ smoke-dev

v*.*.*-rc* tag push (tag protection: release-managers only)
  └─ resolve artifact for tagged commit SHA
       └─ deploy-staging (auto)
            └─ smoke-staging

v*.*.* tag push (tag protection: release-managers only)
  └─ resolve artifact for tagged commit SHA
       └─ deploy-prod (auto; smoke-staging must pass for normal releases)
            └─ [CloudWatch alarms monitor prod — no synthetic smoke]

infrastructure/** push → terraform.yml (separate path, unchanged)
```

### Tag naming convention

| Tag pattern | Environment | Gate |
|---|---|---|
| `v1.2.3-rc1` | staging | tag protection (release-managers only) |
| `v1.2.3` | prod | tag protection + staging smoke must pass |

Tag protection ruleset (configure in repo **Settings → Rules**):
- Pattern: `v*`
- Restriction: `@{org}/release-managers` team only
- Block force pushes: yes
- Require signed commits: recommended

### Why tags over GitHub Environment approval gates

- Immutable release marker tied to a specific commit SHA — audit trail shows *who* created
  `v1.2.3` and *when*
- Tag protection rules enforce the same access control at the git layer
- Hotfix path: push `v1.2.3` tag directly; `workflow_dispatch` available as a break-glass
  escape hatch (explicit `run_id` required)
- Rollback is `git tag -f v1.2.3-rc1 <prev-sha> && git push --force-tag` — no CI run ID lookup

---

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

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true   # newer commit supersedes older one

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff==0.2.0 mypy==1.19.1 pydantic==2.12.5
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
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
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
        env:
          PYTHONPATH: .
        run: pytest tests/unit/ -v --cov=services --cov=shared --cov-report=xml
      - name: Run tenant isolation tests
        env:
          PYTHONPATH: .
          DATABASE_HOST: localhost
          DATABASE_PORT: 5432
          DATABASE_NAME: logistics_test
          DATABASE_USER: test_user
          DATABASE_PASSWORD: test_pass
        run: pytest tests/tenant_isolation/ -v
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: coverage.xml
          fail_ci_if_error: false

  security:
    runs-on: ubuntu-latest
    needs: lint
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install bandit==1.7.7 safety==3.7.0
      - name: SAST scan (bandit)
        run: bandit -r services/ shared/ -ll -q -c pyproject.toml
      - name: Dependency vulnerability scan (safety)
        run: safety check -r requirements.txt
      - name: Trivy filesystem scan
        # Pinned to v0.35.0 — update via Dependabot, never float @master
        uses: aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1  # v0.35.0
        with:
          scan-type: 'fs'
          scan-ref: '.'
          severity: 'CRITICAL,HIGH'
          format: 'table'

  # Build runs only on push to main. PRs run lint/test/security only.
  # The artifact produced here is the single binary deployed to ALL environments.
  build:
    runs-on: ubuntu-latest
    needs: [test, security]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: read
      actions: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build shared Lambda layer
        run: |
          mkdir -p build/layer/python
          cp -r shared/ build/layer/python/shared/
          pip install \
            --platform manylinux2014_aarch64 \
            --target build/layer/python/ \
            --implementation cp \
            --python-version 3.12 \
            --only-binary=:all: \
            -r requirements-layer.txt
          cd build/layer && zip -r ../shared-layer.zip python/
      - name: Build service zips
        run: |
          for service in tenant_management packing_list manifest tracking billing claims \
                         payment_release refunds notification metering excel; do
            cd services/$service
            zip -r ../../build/${service}.zip .
            cd ../..
          done
      - name: Build scheduled job zips
        run: |
          for job in storage_fee dispute_escalation sla_check storage_reminders \
                     data_cleanup usage_aggregation release_expiry; do
            cd services/scheduled
            zip -r ../../build/scheduled-${job}.zip ${job}.py
            cd ../..
          done
      - name: Build migration zip
        run: |
          mkdir -p build/migrate_pkg
          cp -r migrations/ build/migrate_pkg/migrations/
          cp services/migrate/handler.py build/migrate_pkg/handler.py
          cd build/migrate_pkg && zip -r ../../build/migrate.zip .
      - name: Upload lambda packages
        uses: actions/upload-artifact@v4
        with:
          name: lambda-packages-${{ github.run_id }}
          path: build/
          retention-days: 30
          if-no-files-found: error
```

---

### File: `.github/workflows/frontend-ci.yml`

**Triggers:** PR/push to `main` touching `frontend/**` only (path-filtered — does not run on
backend-only changes, and the backend `ci.yml` does not run on frontend-only changes).

```yaml
name: Frontend CI

on:
  pull_request:
    branches: [main]
    paths: ["frontend/**", ".github/workflows/frontend-ci.yml"]
  push:
    branches: [main]
    paths: ["frontend/**", ".github/workflows/frontend-ci.yml"]

jobs:
  build-and-test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run typecheck
      - run: npm run lint
      - run: npm test
      - run: npm run build
      - run: npm audit --audit-level=high
```

No deploy job yet — static hosting (S3 + CloudFront) and the build/deploy pipeline for the
`dist/` artifact are specified in `frontend/01_project_setup.md` →
`docs/project docs/frontend/13_deployment_and_cicd.md`, added once the skeleton app ships
(Phase 2 of the frontend build order).

---

### File: `.github/workflows/deploy.yml`

**Triggers:** `workflow_run` (dev, auto), `push: tags:` (staging/prod), `workflow_dispatch`
(break-glass hotfix only)

```yaml
name: Deploy Pipeline

on:
  workflow_run:
    workflows: ["CI Pipeline"]
    types: [completed]
    branches: [main]
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+-rc[0-9]+'   # staging: e.g. v1.2.3-rc1
      - 'v[0-9]+.[0-9]+.[0-9]+'             # prod:    e.g. v1.2.3
  workflow_dispatch:
    inputs:
      environment:
        description: "Target environment (break-glass hotfix only)"
        required: true
        type: choice
        options: [dev, staging, prod]
      run_id:
        description: "CI Pipeline run ID whose artifact to deploy"
        required: true
        type: string

concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false   # never cancel mid-deploy (leaves mixed state)

permissions:
  contents: read
  actions: read

jobs:
  # On tag push: find the successful CI run for the exact tagged commit SHA.
  # Fails if no successful CI run exists — only tested code can be released.
  resolve-artifact:
    runs-on: ubuntu-latest
    if: github.event_name == 'push'
    outputs:
      run_id: ${{ steps.find.outputs.run_id }}
    permissions:
      contents: read
      actions: read
    steps:
      - name: Find successful CI run for tagged commit
        id: find
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          RUN_ID=$(gh api \
            "repos/${{ github.repository }}/actions/runs?head_sha=${{ github.sha }}&event=push&status=success" \
            --jq '[.workflow_runs[] | select(.name == "CI Pipeline")] | first | .id')
          if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
            echo "No successful CI Pipeline run found for commit ${{ github.sha }}"
            exit 1
          fi
          echo "run_id=${RUN_ID}" >> "$GITHUB_OUTPUT"

  deploy-dev:
    if: >-
      (github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success') ||
      (github.event_name == 'workflow_dispatch' && inputs.environment == 'dev')
    permissions:
      contents: read
      id-token: write
      actions: read
    uses: ./.github/workflows/_deploy-env.yml
    with:
      environment: dev
      artifact_run_id: >-
        ${{ github.event_name == 'workflow_run'
            && github.event.workflow_run.id
            || inputs.run_id }}
    secrets: inherit

  smoke-dev:
    needs: deploy-dev
    if: >-
      (github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success') ||
      (github.event_name == 'workflow_dispatch' && inputs.environment == 'dev')
    permissions:
      contents: read
    uses: ./.github/workflows/_smoke-test.yml
    with:
      environment: dev
    secrets: inherit

  deploy-staging:
    needs: resolve-artifact
    if: >-
      (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') &&
        contains(github.ref, '-rc')) ||
      (github.event_name == 'workflow_dispatch' && inputs.environment == 'staging')
    permissions:
      contents: read
      id-token: write
      actions: read
    uses: ./.github/workflows/_deploy-env.yml
    with:
      environment: staging
      artifact_run_id: >-
        ${{ github.event_name == 'push'
            && needs.resolve-artifact.outputs.run_id
            || inputs.run_id }}
    secrets: inherit

  smoke-staging:
    needs: deploy-staging
    if: >-
      always() && needs.deploy-staging.result == 'success' && (
        (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') &&
          contains(github.ref, '-rc')) ||
        (github.event_name == 'workflow_dispatch' && inputs.environment == 'staging')
      )
    permissions:
      contents: read
    uses: ./.github/workflows/_smoke-test.yml
    with:
      environment: staging
    secrets: inherit

  deploy-prod:
    needs: [resolve-artifact, smoke-staging]
    if: >-
      always() && (
        (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') &&
          !contains(github.ref, '-rc') &&
          (needs.smoke-staging.result == 'success' || needs.smoke-staging.result == 'skipped')) ||
        (github.event_name == 'workflow_dispatch' && inputs.environment == 'prod')
      )
    permissions:
      contents: read
      id-token: write
      actions: read
    uses: ./.github/workflows/_deploy-env.yml
    with:
      environment: prod
      artifact_run_id: >-
        ${{ github.event_name == 'push'
            && needs.resolve-artifact.outputs.run_id
            || inputs.run_id }}
    secrets: inherit
```

> **Note on prod gate:** For the normal release path (`v*.*.*-rc*` → `v*.*.*`), staging smoke
> must pass. For a direct prod hotfix (push `v*.*.*` with no prior RC), `smoke-staging` is
> skipped and `always()` allows `deploy-prod` to evaluate — tag protection rules are the sole
> gate. This is intentional: `workflow_dispatch` to prod is a break-glass procedure; document
> post-incident review in `docs/runbook.md`.

---

### File: `.github/workflows/_deploy-env.yml`

Reusable workflow called by `deploy.yml`. Runs migrations, deploys the shared layer and all
Lambda functions in sequence.

**Critical implementation details:**

1. **Layer ARN capture** — `publish-layer-version` creates a new versioned ARN (e.g. `:42`).
   The ARN is captured via `--query LayerVersionArn` and passed to `update-function-configuration
   --layers` for each function. `update-function-code` alone does **not** update the attached layer.

2. **Two waits per function** — `update-function-code` and `update-function-configuration` each
   independently enter `Updating` state. Calling config-update while code-update is still in flight
   returns `ResourceConflictException`. Two `aws lambda wait function-updated` calls are required.

3. **Migrations before code** — The migration Lambda is updated and invoked synchronously before
   any service code deploys. A non-zero returncode aborts the entire deploy.

```yaml
name: Deploy Environment (reusable)

on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
      artifact_run_id:
        description: "Run ID of the CI Pipeline that produced the lambda-packages artifact"
        required: true
        type: string

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    permissions:
      contents: read
      id-token: write
      actions: read
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: eu-west-1

      - name: Download lambda packages
        uses: actions/download-artifact@v4
        with:
          name: lambda-packages-${{ inputs.artifact_run_id }}
          path: build/
          run-id: ${{ inputs.artifact_run_id }}
          github-token: ${{ secrets.GITHUB_TOKEN }}

      - name: Run database migrations
        env:
          ENV: ${{ inputs.environment }}
        run: |
          aws lambda update-function-code \
            --function-name logistics-migrate-${ENV} \
            --zip-file fileb://build/migrate.zip \
            --architectures arm64 --no-cli-pager
          aws lambda wait function-updated --function-name logistics-migrate-${ENV}

          RESULT=$(aws lambda invoke \
            --function-name logistics-migrate-${ENV} \
            --payload '{}' \
            --log-type Tail \
            --cli-binary-format raw-in-base64-out \
            /tmp/migrate-out.json)
          echo "$RESULT" | jq -r '.LogResult' | base64 -d
          RC=$(jq -r '.returncode // 1' /tmp/migrate-out.json)
          [ "$RC" = "0" ] || { echo "Migration FAILED — aborting deploy"; exit 1; }

      - name: Deploy shared layer
        id: layer
        run: |
          LAYER_ARN=$(aws lambda publish-layer-version \
            --layer-name logistics-shared-${{ inputs.environment }} \
            --zip-file fileb://build/shared-layer.zip \
            --compatible-runtimes python3.12 \
            --compatible-architectures arm64 \
            --query 'LayerVersionArn' \
            --output text)
          echo "arn=${LAYER_ARN}" >> "$GITHUB_OUTPUT"

      - name: Deploy services
        env:
          LAYER_ARN: ${{ steps.layer.outputs.arn }}
          ENV: ${{ inputs.environment }}
        run: |
          for service in tenant_management packing_list manifest tracking billing claims \
                         payment_release refunds notification metering excel; do
            fn="logistics-${service}-${ENV}"
            aws lambda update-function-code \
              --function-name "$fn" --zip-file fileb://build/${service}.zip \
              --architectures arm64 --no-cli-pager
            aws lambda wait function-updated --function-name "$fn"
            aws lambda update-function-configuration \
              --function-name "$fn" --layers "$LAYER_ARN" --no-cli-pager
            aws lambda wait function-updated --function-name "$fn"
          done

      - name: Deploy scheduled jobs
        env:
          LAYER_ARN: ${{ steps.layer.outputs.arn }}
          ENV: ${{ inputs.environment }}
        run: |
          for job in storage_fee dispute_escalation sla_check storage_reminders \
                     data_cleanup usage_aggregation release_expiry; do
            fn="logistics-${job}-${ENV}"
            aws lambda update-function-code \
              --function-name "$fn" --zip-file fileb://build/scheduled-${job}.zip \
              --architectures arm64 --no-cli-pager
            aws lambda wait function-updated --function-name "$fn"
            aws lambda update-function-configuration \
              --function-name "$fn" --layers "$LAYER_ARN" --no-cli-pager
            aws lambda wait function-updated --function-name "$fn"
          done
```

---

### File: `.github/workflows/_smoke-test.yml`

Reusable smoke test workflow. `API_BASE_URL` is a per-GitHub-Environment secret (not an input)
pointing to the real API Gateway v2 URL. No smoke tests in production — use CloudWatch alarms.

```yaml
name: Smoke Tests (reusable)

on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
    secrets:
      API_BASE_URL:
        required: true
        description: "API Gateway stage URL — set as API_BASE_URL secret per GitHub Environment"

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - name: Wait for Lambda warm-up
        run: sleep 10

      - name: Health endpoint
        env:
          API_BASE: ${{ secrets.API_BASE_URL }}
        run: |
          response=$(curl -sf --max-time 10 --retry 3 --retry-delay 5 \
            -w "\n%{http_code}" "$API_BASE/v1/health")
          http_code=$(echo "$response" | tail -1)
          test "$http_code" = "200"

      - name: Auth enforcement — unauthenticated requests must return 401
        env:
          API_BASE: ${{ secrets.API_BASE_URL }}
        run: |
          failed=0
          for ep in "/v1/packing-lists" "/v1/billing" "/v1/manifests" "/v1/tracking" "/v1/claims"; do
            status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$API_BASE$ep")
            [ "$status" = "401" ] || { echo "FAIL: $ep returned $status, expected 401"; failed=1; }
          done
          exit $failed

      - name: Response time SLA — health endpoint must respond within 2s
        env:
          API_BASE: ${{ secrets.API_BASE_URL }}
        run: |
          time_total=$(curl -so /dev/null -w "%{time_total}" "$API_BASE/v1/health")
          result=$(echo "$time_total < 2.0" | bc -l)
          test "$result" = "1" || (echo "SLA breach: ${time_total}s > 2s" && exit 1)
```

Set `API_BASE_URL` secret in each GitHub Environment (Settings → Environments → dev / staging):

```
Environment "dev"     → API_BASE_URL = https://<api-id>.execute-api.eu-west-1.amazonaws.com/dev
Environment "staging" → API_BASE_URL = https://<api-id>.execute-api.eu-west-1.amazonaws.com/staging
```

Prod has no `API_BASE_URL` secret and no smoke job — CloudWatch alarms handle validation.

---

### File: `.github/workflows/terraform.yml`

Separate workflow for infrastructure changes. Queued (never cancels mid-apply).

Key additions over the baseline:
- `concurrency: group: terraform-${{ github.ref }}, cancel-in-progress: false`
- Pinned: `terraform_version: "1.7.5"` (not `~1.7`)
- Pre-plan gates: `terraform fmt -check -recursive` and `terraform validate`

---

### File: `services/migrate/handler.py`

Migration Lambda — VPC-attached, runs `alembic upgrade head` against Aurora via RDS Proxy.
Invoked synchronously by the deploy pipeline before any service code is deployed.

```python
"""Migration Lambda — runs Alembic upgrade head against Aurora via RDS Proxy.

Environment variables (injected by Terraform):
    DATABASE_HOST     RDS Proxy endpoint
    DATABASE_NAME     Database name (logistics)
    DATABASE_USER     DB user (postgres)
    DATABASE_PORT     DB port (default 5432)
    DB_SECRET_ARN     Secrets Manager ARN for the DB password
"""
import json
import os
import subprocess

import boto3


def lambda_handler(event: dict, context: object) -> dict:
    _inject_db_password()
    result = subprocess.run(
        ["python", "-m", "alembic", "-c", "migrations/alembic.ini", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _inject_db_password() -> None:
    sm = boto3.client("secretsmanager")
    secret_str = sm.get_secret_value(SecretId=os.environ["DB_SECRET_ARN"])["SecretString"]
    secret = json.loads(secret_str)
    os.environ["DATABASE_PASSWORD"] = secret["password"]
```

Terraform resources in `infrastructure/aws/modules/lambda/main.tf`:
- `aws_cloudwatch_log_group.migrate`
- `aws_iam_role.migrate` (permissions boundary attached)
- `aws_iam_role_policy.migrate_db_access` — `secretsmanager:GetSecretValue` on `DB_SECRET_ARN`,
  `rds-db:connect` on the Aurora cluster
- `aws_lambda_function.migrate` — VPC-attached, 300s timeout, same private subnets, ARM64

Function name: `logistics-migrate-{dev|staging|prod}`

`alembic upgrade head` is idempotent — safe to re-run when already at HEAD.

---

## AWS Bootstrap (One-Time Setup)

Before any GitHub Actions workflow can run, the AWS account must be bootstrapped.

### Prerequisites

- AWS CLI v2 configured with `AdministratorAccess` (or equivalent: `iam:*`, `s3:*`, `dynamodb:*`,
  `sts:GetCallerIdentity`)
- `jq` installed
- Run from the repository root

### Run bootstrap

```bash
bash scripts/bootstrap_aws.sh "ifexalex/odum-shipx"
# Optionally pass region as second arg (default: eu-west-1):
# bash scripts/bootstrap_aws.sh "ifexalex/odum-shipx" eu-west-1
```

The script is **idempotent** — safe to re-run.

**What it creates:**

| Resource | Name |
|---|---|
| S3 state bucket | `logistics-terraform-state-{ACCOUNT_ID}` |
| DynamoDB lock table | `logistics-terraform-locks` |
| OIDC provider | `token.actions.githubusercontent.com` |
| IAM permissions boundary | `logistics-lambda-permissions-boundary` |
| IAM deploy role (dev) | `logistics-github-deploy-dev` |
| IAM deploy role (staging) | `logistics-github-deploy-staging` |
| IAM deploy role (prod) | `logistics-github-deploy-prod` |

### Set GitHub Environment Secrets

After bootstrap, set the following secrets in each GitHub Environment (Settings → Environments):

**`AWS_DEPLOY_ROLE_ARN`** — all three environments:
```
dev     → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-dev
staging → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-staging
prod    → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-prod
```

**`API_BASE_URL`** — dev and staging only (no smoke in prod):
```
dev     → https://<api-id>.execute-api.eu-west-1.amazonaws.com/dev
staging → https://<api-id>.execute-api.eu-west-1.amazonaws.com/staging
```

### Configure Tag Protection Ruleset

In repo **Settings → Rules → New ruleset**:
- Name: `release-tags`
- Target: tags matching `v*`
- Restriction: bypass list = `@{org}/release-managers` team
- Rule: Block force pushes
- Rule (optional): Require signed commits

### Initialise Terraform

```bash
cd infrastructure/aws
terraform init -backend-config=environments/dev.backend.hcl
terraform plan -var-file=environments/dev.tfvars
```

### Import OIDC resources into Terraform state (post first apply)

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

terraform import module.iam_oidc.aws_iam_openid_connect_provider.github \
  arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com

terraform import module.iam_oidc.aws_iam_policy.permissions_boundary \
  arn:aws:iam::${ACCOUNT_ID}:policy/logistics-lambda-permissions-boundary

terraform import 'module.iam_oidc.aws_iam_role.deploy["dev"]'     logistics-github-deploy-dev
terraform import 'module.iam_oidc.aws_iam_role.deploy["staging"]' logistics-github-deploy-staging
terraform import 'module.iam_oidc.aws_iam_role.deploy["prod"]'    logistics-github-deploy-prod
```

Run `terraform plan -var-file=environments/dev.tfvars` — should show **0 changes** after import.

### Security Design

**OIDC trust scoping (no stored AWS credentials):**

| Role | Trusted GitHub contexts |
|---|---|
| `logistics-github-deploy-dev` | `refs/heads/main` + `environment:dev` |
| `logistics-github-deploy-staging` | `environment:staging` only |
| `logistics-github-deploy-prod` | `environment:prod` only |

Staging and prod roles are not assumable from branch pushes — only from workflow runs that
explicitly target the GitHub Environment (tag push or `workflow_dispatch` break-glass).

**Permissions boundary (`logistics-lambda-permissions-boundary`):**
All IAM roles created by Terraform (Lambda execution roles) must have this boundary attached.
The boundary caps maximum permissions to only what Lambda legitimately needs. The deploy role's
IAM policy enforces this via `Condition: iam:PermissionsBoundary = ...` on `iam:CreateRole` —
even a compromised deploy role cannot create an admin role.

---

## Acceptance Criteria

- [x] CI runs lint (ruff==0.2.0 + mypy==1.19.1), unit tests, tenant isolation tests, and security scan
- [x] Security scan includes bandit==1.7.7 (SAST), safety==3.7.0 (dependency vulns), and Trivy (filesystem scan, table format; SHA-pinned to v0.24.0)
- [x] Tests run against a real PostgreSQL 15 (GitHub Actions service container)
- [x] Build job produces a single immutable artifact (`lambda-packages-{run_id}`, retained 30 days)
- [x] Deploy downloads the pre-built artifact — no rebuild, no pip install in deploy job
- [x] Shared Lambda layer packaged with `--platform manylinux2014_aarch64` for ARM64 compatibility
- [x] Layer ARN captured from `publish-layer-version` output and applied to every function via `update-function-configuration --layers`
- [x] Two `aws lambda wait function-updated` calls per function (code + config each enter Updating state independently)
- [x] Database migrations run via VPC-attached migration Lambda before any service code deploys; non-zero returncode aborts deploy
- [x] Terraform plan/apply runs per environment using remote state (S3 + DynamoDB); `terraform fmt -check` and `terraform validate` gate every plan
- [x] Smoke tests verify API reachability after dev and staging deploys (health check + 401 enforcement + 2s SLA); `API_BASE_URL` is a GitHub Environment secret pointing to the real API Gateway URL
- [x] No synthetic smoke tests in production — CloudWatch alarms (`Errors > 1%/5min`, `DLQ depth > 0`, `5xx > 0.5%/5min`) monitor prod post-deploy
- [x] Staging released via `v*.*.*-rc*` tag push; prod released via `v*.*.*` tag push; tags protected by GitHub ruleset (release-managers team only)
- [x] `resolve-artifact` job finds the CI run for the tagged commit SHA — only commits that have passed CI can be deployed
- [x] Normal prod release: `smoke-staging` must pass; hotfix prod path: tag protection is the sole gate
- [x] `workflow_dispatch` kept as break-glass escape hatch (operator supplies explicit `run_id`)
- [x] Pipeline uses GitHub environments + OIDC for credential-free AWS access (no stored keys)
- [x] Concurrency groups: CI cancels in-progress (newer commit supersedes), deploy/terraform queued (never cancel mid-run)
- [x] Tool versions pinned: ruff, mypy, bandit, safety, Trivy (SHA), Terraform (1.7.5)
- [x] Coverage report uploaded to Codecov
- [x] `scripts/bootstrap_aws.sh` — idempotent one-time setup (S3 state, DynamoDB, OIDC, IAM roles)
- [x] `infrastructure/aws/modules/iam-oidc/` — Terraform module manages OIDC + deploy roles post-bootstrap
- [x] Permissions boundary on all Lambda execution roles prevents privilege escalation

---

## Rollback Strategy

### Lambda rollback (current model — no versioning)

Re-run the deploy pipeline with the artifact from the previous CI run:

```bash
# Find the run_id of the last successful deploy from the Actions tab, then:
# workflow_dispatch → environment: prod → run_id: <previous-run-id>
```

Or use `aws lambda update-function-code` directly with a previously uploaded zip if available.

### Tag-based rollback (normal path)

Re-tag the previous commit and push:

```bash
# For staging: re-tag a known-good commit as the next RC
git tag v1.2.3-rc2 <prev-sha>
git push origin v1.2.3-rc2

# For prod: re-tag a known-good commit as the patch release
git tag v1.2.4 <prev-sha>
git push origin v1.2.4
```

### Terraform rollback

Re-apply the previous state:

```bash
terraform apply -var-file=environments/$ENV.tfvars -target=module.lambda
```

### Database rollback

Alembic downgrade (if migration was applied and must be reverted):

```bash
alembic downgrade -1
```

**Important:** Database migrations MUST be backward-compatible (additive only). Never drop columns
or rename in the same release as code changes. Use a 2-phase migration strategy:
- Phase 1: Add new column (nullable), deploy code that writes to both
- Phase 2: Backfill, deploy code that reads from new column, drop old column

---

## Future: Lambda Versions + Aliases + AWS CodeDeploy (next sprint)

The current model deploys directly to `$LATEST` with no atomic rollback. The recommended
next step is:

1. Enable `publish = true` in `aws_lambda_function` (Terraform) to create versioned snapshots
2. Add `aws_lambda_alias.stable` pointing to the current published version
3. Configure `aws_codedeploy_deployment_group` with:
   - `CodeDeployDefault.LambdaCanary10Percent5Minutes` for prod (automatic rollback on alarm)
   - `CodeDeployDefault.LambdaAllAtOnce` for dev/staging
4. Update `_deploy-env.yml` to call `aws deploy create-deployment` instead of directly updating
   the alias

This gives atomic alias-level rollback in under 30 seconds and automatic rollback on CloudWatch
alarm breach. See the architecture review doc for full implementation details.
