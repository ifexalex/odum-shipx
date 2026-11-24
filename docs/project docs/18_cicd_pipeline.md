# Task 18 — CI/CD: GitHub Actions Workflows

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` §6 (Terraform Standards).

## Objective

Create GitHub Actions workflows for continuous integration (lint, test, security scan, build) and
continuous deployment (database migrations, Lambda deployment, smoke tests). Use tag-based release
gating for staging and production — no stored AWS credentials (OIDC), immutable artifact promotion
(build once in CI, deploy the same binary to all environments).

> **Dependency tooling (2026-10-09):** the pipeline uses **uv** — CI runs `astral-sh/setup-uv` +
> `uv sync`/`uv run`; the Lambda layer/zips are built via `uv export` + `uv pip install
> --python-platform aarch64-manylinux_2_28` (python3.13). Deps live in `pyproject.toml` + `uv.lock`;
> there are no `requirements*.txt` files. The **`.github/workflows/*.yml` files are the source of
> truth** — any YAML inlined in this doc below is illustrative and may show the earlier pip form.
>
> **Python pinned to 3.13 via `.python-version`:** `requires-python = ">=3.13"` would otherwise let
> uv resolve the newest interpreter on the runner (e.g. 3.15), for which native wheels
> (`pydantic-core`) don't exist yet → a from-source build that fails against the installed PyO3. The
> committed `.python-version` (`3.13`) pins every `uv sync` (CI + local) to the project's actual
> runtime, matching the Lambda/Container-Apps runtime + mypy. No `requires-python`/lock change (so
> `uv sync --frozen` in the Dockerfile stays valid).

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

### Environment wiring matrix (at a glance)

| Environment | GitHub Env | Protection | Trigger → deploy | Backend tfstate | Required env secrets |
|---|---|---|---|---|---|
| **dev** | `dev` | none (auto) | CI success on `main` → auto | AWS: `logistics/dev` · Azure: `azure/dev` | `AWS_DEPLOY_ROLE_ARN`, `API_BASE_URL`, `AZURE_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID` |
| **staging** | `staging` | required reviewers | `v*.*.*-rc*` tag | AWS: `logistics/staging` · Azure: `azure/staging` | same set, staging values |
| **prod** | `prod` | required reviewers + tag protection | `v*.*.*` tag | AWS: `logistics/prod` · Azure: `azure/prod` | same set, prod values |
| **demo** | `demo` | none (dispatch-only) | **`workflow_dispatch` only** (standalone, not in the chain) | AWS: `logistics/demo` · Azure: `azure/demo` | same set, demo values |
| **local** | — | — | LocalStack / `make stack` | local | n/a |

- Both clouds use the **same GitHub Environments** (`dev`/`staging`/`prod`/`demo`), so one set of
  protection rules + reviewers gates AWS and Azure alike. The frontend workflows share them too
  (standardized on `prod`, not `production`).
- **demo** is a real, committed, fully-wired environment (`environments/demo.{tfvars,backend.hcl}`
  in both roots, a `logistics-github-deploy-demo` OIDC role, and `demo` jobs in `terraform.yml` /
  `terraform-azure.yml` / `deploy.yml` / `frontend-deploy.yml`) — but kept **out of the automated
  promotion chain**: it only runs via `workflow_dispatch`, for a short-lived link you then
  `terraform destroy`. It is lean (max_acu=1, `route53_zone_id=""` → no CloudFront/WAF) but uses
  the same `logistics` naming + schema as the other envs (no more copy-me `.example`).
- Runtime: **Python 3.13** across CI, the Lambda layer build, the Terraform `runtime`, the
  deploy `--compatible-runtimes`, and mypy (aligned 2026-10-08).

### Choosing the cloud — the `DEPLOY_CLOUD` switch

A single **repository variable** `DEPLOY_CLOUD` selects which cloud's deploy pipelines run.
It is read as `vars.DEPLOY_CLOUD` in every deploy job's `if:`, so exactly one cloud ever
deploys — never both at once.

| `DEPLOY_CLOUD` value | What deploys | What is skipped |
|---|---|---|
| unset / `aws` (default) | `terraform.yml`, `deploy.yml`, `ci.yml` build, `frontend-deploy.yml` (`cloud=aws`) | `terraform-azure.yml`, `deploy-azure.yml` |
| `azure` | `terraform-azure.yml` (plan), `deploy-azure.yml` (apply + image → Container Apps), `frontend-deploy.yml` (`cloud=azure`) | `terraform.yml`, `deploy.yml`, `ci.yml` Lambda build |

The AWS backend deploys as Lambda zips (`deploy.yml`); the Azure backend deploys as a container
image to ACR that rolls the Container Apps (`deploy-azure.yml` → `_deploy-azure-env.yml`). Both
follow the same promotion model (main → dev, `v*-rc*` → staging, `v*` → prod, dispatch → demo).

- **Fail-safe default:** AWS workflows are gated `vars.DEPLOY_CLOUD != 'azure'`, so an unset or
  misspelled value still deploys AWS (the live cloud) rather than silently deploying nothing.
  Azure workflows are gated `vars.DEPLOY_CLOUD == 'azure'` (opt-in).
- The gate is on **deploy/apply jobs only** — CI (lint/test/build), frontend build+test, and all
  Terraform `plan`/`validate` still run on every push regardless of `DEPLOY_CLOUD`.
- Set it once per repo: `gh variable set DEPLOY_CLOUD --body azure` (or `aws`). Flip it to cut
  the whole stack over; there is no per-environment split — all envs follow the one switch.
- It does **not** remove the need for the target cloud's secrets/OIDC to be wired first
  (see the bootstrap checklist below). Switching to `azure` with no `AZURE_*` secrets set will
  fail `azure/login`, not fall back to AWS.

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
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      # uv auto-installs the interpreter pinned by requires-python (3.13).
      - run: uv sync --extra azure
      - run: uv run ruff check .
      - run: uv run mypy shared/ services/ --ignore-missing-imports

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
      # Added 2026-11-14: tests/integration/ (service-level flow, no DB) and tests/db/ (real Postgres as
      # logistics_app: invoice/payment concurrency and atomicity). Same env block as the isolation step.
      - name: Run integration tests
        run: pytest tests/integration/ -v
      - name: Run database integrity tests
        run: pytest tests/db/ -v
      # Added 2026-11-17 (audit OPS-03): fails the build when unit-test line coverage of services/billing,
      # services/payment_release or services/refunds falls below its floor in pyproject.toml.
      - name: Enforce coverage floors
        run: uv run python scripts/check_coverage.py coverage.xml
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
                         payment_release refunds notification metering excel search; do
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
        uses: actions/upload-artifact@v7
        with:
          name: lambda-packages-${{ github.run_id }}
          path: build/
          retention-days: 7            # clamped by the repo setting — see below
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
      - uses: actions/setup-node@v6
        with:
          node-version-file: frontend/.nvmrc   # single source of truth; see LOCAL_TESTING.md §2
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
                         payment_release refunds notification metering excel search; do
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
| IAM deploy role (demo) | `logistics-github-deploy-demo` |

### Set GitHub Environment Secrets

After bootstrap, set the following secrets in each GitHub Environment (Settings → Environments):

**`AWS_DEPLOY_ROLE_ARN`** — one per GitHub Environment:
```
dev     → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-dev
staging → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-staging
prod    → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-prod
demo    → arn:aws:iam::{ACCOUNT_ID}:role/logistics-github-deploy-demo
```

**`API_BASE_URL`** — all three environments (the read-only smoke now runs on prod too, 2026-10-08):
```
dev     → https://<api-id>.execute-api.eu-west-1.amazonaws.com/dev
staging → https://<api-id>.execute-api.eu-west-1.amazonaws.com/staging
prod    → https://<api-id>.execute-api.eu-west-1.amazonaws.com/prod
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

---

## Azure deployment pipeline (`terraform-azure.yml`, added 2026-10-08)

The Azure portability stack (`infrastructure/azure/`) has its own Terraform pipeline: push to
`main` touching `infrastructure/azure/**` or `infrastructure/common/**` runs dev → staging → prod
fmt + validate + **plan** (preview), each gated by its GitHub Environment. Auth is **OIDC
federated credentials** (no stored client secret), same zero-secret posture as AWS.

> **Plan-only (2026-10-10).** `terraform-azure.yml` no longer applies — it is the infra *review*
> check. The **apply is owned by the deploy pipeline**: `_deploy-azure-env.yml` runs
> `terraform apply` as its first step on every deploy, so infra + state are reconciled (and any
> change captured) before the app rolls, and the deploy cannot proceed on failed infra. One
> workflow owns the state → no lock contention. Plans here use `-lock=false` so a preview never
> blocks or is blocked by a concurrent deploy apply.

### 1. One-time Terraform state bootstrap (manual)

The azurerm backend needs a storage account for state. Create it once (names are globally
unique — pick your own and put it in `environments/*.backend.hcl`):

```bash
az group create -n shipx-tfstate-rg -l northeurope
az storage account create -n shipxtfstate<suffix> -g shipx-tfstate-rg -l northeurope \
  --sku Standard_LRS --min-tls-version TLS1_2 --allow-blob-public-access false
az storage container create -n tfstate --account-name shipxtfstate<suffix> --auth-mode login
```

Then set `storage_account_name` in each `infrastructure/azure/environments/{env}.backend.hcl`.

### 2. OIDC federated identity (manual)

Create one Entra app registration for CI and a **federated credential per GitHub Environment
subject**, then grant it rights on the subscription + the tfstate container:

```bash
APP_ID=$(az ad app create --display-name shipx-github-deploy --query appId -o tsv)
az ad sp create --id "$APP_ID"
SUB=$(az account show --query id -o tsv)

for env in dev staging prod; do
  az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"gh-$env\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:ifexalex/odum-shipx:environment:$env\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
done

# Contributor to provision resources + Storage Blob Data Contributor for tfstate.
az role assignment create --assignee "$APP_ID" --role Contributor --scope "/subscriptions/$SUB"
az role assignment create --assignee "$APP_ID" --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/shipx-tfstate-rg"
```

> Scope `Contributor` down to the app's resource groups for prod; subscription-wide is fine for
> a throwaway/free test account.

### 3. GitHub Environment secrets (Azure)

Set in each GitHub Environment (dev/staging/prod) — the same three, pointing at your tenant/sub:

```
AZURE_CLIENT_ID        → <app registration appId>
AZURE_TENANT_ID        → <your Entra tenant id>
AZURE_SUBSCRIPTION_ID  → <your subscription id>
```

(The frontend Azure deploy — `frontend-deploy.yml` with `cloud=azure` — additionally needs the
`AZURE_FRONTEND_*`, `AZURE_RESOURCE_GROUP` secrets from `terraform -chdir=infrastructure/azure
output`.)

**Frontend auth provider (dual-cloud).** The SPA supports both identity backends via one build flag
(`VITE_AUTH_PROVIDER` → `frontend/src/auth/authClient.ts` picks `EntraClient` or `CognitoClient`).
`frontend-deploy.yml` resolves it automatically so it can't drift: on **Azure** it reads
`frontend_auth_provider` (= `entra`), `entra_client_id`, and `entra_token_endpoint` from Terraform
outputs (public ids, so no `VITE_ENTRA_*` secrets); on **AWS** it falls back to the optional
`VITE_AUTH_PROVIDER`/`VITE_ENTRA_*` secrets and defaults to `cognito` (with the `VITE_COGNITO_*`
secrets). Same `dist/` either way.

`workflow_dispatch` on **Actions → "Terraform (Azure)"** applies a chosen env on demand; a push
to `main` touching the Azure infra runs the full dev→staging→prod chain.

### Azure backend deploy (`deploy-azure.yml` + `_deploy-azure-env.yml`, added 2026-10-09)

The Azure analogue of `deploy.yml`, gated `vars.DEPLOY_CLOUD == 'azure'`. Same promotion model
(main → dev, `v*-rc*` → staging, `v*` → prod, dispatch → demo). The reusable
`_deploy-azure-env.yml` per environment, in one job (so order is guaranteed and a failure stops
everything after it):

1. **`terraform apply`** (`init` + `apply -var-file=environments/<env>.tfvars -auto-approve`) —
   **always first**, reconciling infra + state before anything ships, and emitting the infra
   outputs (RG, ACR, migrate-job, api URL) the later steps consume. A no-op when nothing changed;
   a failure aborts the deploy (every later step depends on its outputs). This is the single
   Terraform state-owner (`terraform-azure.yml` is plan-only).
2. `az acr login`, then **build + push** the `Dockerfile` image to ACR tagged with the commit SHA.
3. **Migrate**: point the migration Container App Job at the new image, `az containerapp job start`,
   poll to `Succeeded` (a `Failed` aborts the deploy — idempotent `alembic upgrade head`).
4. **Roll** every Container App (api + workers + the Entra claims provider) and Job (scheduled +
   migrate) onto the new image via `az containerapp update/job update --image` (Terraform ignores
   image drift, so CI owns the tag). The claims provider (`*-entra-claims`, ADR-004) is a Container
   App on the same shared image (`docker-entrypoint.sh claims`), so this loop rolls it too — no
   dedicated deploy step.
5. **Smoke** the live ingress (health 200, unauthenticated `/v1/*` → 401) — read-only, prod-safe.

Because step 1 applies the infra, a first-ever environment stands up from this pipeline alone
(given the tfstate account + secrets + registered resource providers exist). There is no separate
"apply infra first" prerequisite — the deploy *is* the apply-then-ship.

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

- [x] CI runs lint (ruff==0.17.3 + mypy==1.19.1), unit tests, tenant isolation tests, and security scan
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

## Artifact retention and the storage quota (2026-11-04)

**Build artifacts are kept for 7 days, not 30.** The reason is worth recording,
because the symptom looked nothing like the cause.

`ci.yml` uploads `lambda-packages-${{ github.run_id }}` on every push to `main`,
at roughly **105 MB each**. At 30 days' retention that accumulated **4.22 GB
across 40 artifacts** (4.54 GB in total with the frontend bundles) and exhausted
the account's artifact storage quota. Two consequences, neither obviously
related to each other:

- A `main` build failed with `Failed to CreateArtifact: Artifact storage quota
  has been hit` — while `lint`, `test` and `security` all passed. A red build on
  `main` caused by storage, not by code.
- More confusingly, **GitHub stopped creating workflow runs for new pushes
  altogether.** A push to a PR branch produced *zero* runs (verified via
  `/actions/runs?head_sha=…` returning `total_count: 0`), so CI simply went
  quiet rather than reporting anything. Nothing in the PR indicated why.

Cleared by deleting the 40 oldest `lambda-packages-*` artifacts (4.54 GB →
0.32 GB), keeping the three most recent for redeploy, and dropping retention to
7 days here and in `frontend-ci.yml`.

**If CI appears to stop reporting on new pushes, check this first:**

```bash
# Current usage, newest first
gh api --paginate "/repos/<owner>/<repo>/actions/artifacts?per_page=100" \
  -q '.artifacts[] | "\(.size_in_bytes)\t\(.name)\t\(.created_at)"' | sort -rn | head

# Did a push actually create any runs?
gh api "/repos/<owner>/<repo>/actions/runs?head_sha=<sha>" -q '.total_count'
```

A `total_count` of `0` for a pushed commit means the runs were never created —
look at quota and billing, not at the workflow files.

Anything older than the retention window is still reproducible: every artifact
is a build output of a known commit, so a redeploy of an older build means
re-running the build for that commit first.

### `uv.lock` is gated in CI, and Dependabot uses the `uv` ecosystem (2026-11-06)

`uv.lock` is the source of truth (fully resolved + hash-locked) per CLAUDE.md,
but **nothing enforced that**, and five Dependabot PRs in a row — #98, #91, #92,
#93, #94 — bumped `pyproject.toml` alone and left the lockfile stale. It never
surfaced because `uv sync` silently re-resolves when the two disagree, so CI went
green while the committed lock was being ignored.

Two fixes, root cause and guard:

1. **`.github/dependabot.yml` uses `package-ecosystem: "uv"`**, not `"pip"`. The
   pip ecosystem reads `pyproject.toml` but has no concept of `uv.lock`, which is
   precisely why every one of those PRs was incomplete. The uv ecosystem updates
   both in the same PR.
2. **`ci.yml`'s lint job runs `uv lock --check`**, which exits 1 when
   `pyproject.toml` and `uv.lock` disagree (verified both ways: stale → exit 1,
   in sync → exit 0). A bump that forgets the lock now fails the build instead of
   passing quietly.

```bash
uv lock --check   # exit 1 if the lockfile needs regenerating
uv lock           # regenerate it; never hand-edit uv.lock
```

---

### `retention-days` is a ceiling request, not a guarantee (found 2026-11-06)

`retention-days:` **cannot exceed the repository's "Artifact and log retention"
setting, and is silently clamped to it** — no warning in the job log, no
annotation. After the quota incident above that repo setting was 1 day, so every
`retention-days: 7` in `ci.yml` and `frontend-ci.yml` was a **no-op**: artifacts
really lived 1 day.

That is not cosmetic. `Deploy Pipeline` fetches `lambda-packages-{run_id}` **by
run id**, so a 1-day window meant only a build from the last 24 hours could be
redeployed; anything older failed at the *Download lambda packages* step.

It was found by reading an artifact's actual expiry rather than trusting the
workflow, which is the only way to see it:

```bash
# What the repo allows (the real ceiling)
gh api repos/:owner/:repo/actions/permissions/artifact-and-log-retention
# -> {"days":7,"maximum_allowed_days":400}

# What artifacts actually got — compare created_at to expires_at
gh api "repos/:owner/:repo/actions/artifacts?per_page=100" \
  -q '.artifacts[] | "\(.created_at) -> \(.expires_at)  \(.name)"' | sort | tail
```

Raised to 7 on 2026-11-06 so the workflow value is effective. **If artifacts
expire sooner than `retention-days` says, this setting is why** — changing the
workflow will not help. To change it:

```bash
gh api -X PUT repos/:owner/:repo/actions/permissions/artifact-and-log-retention -F days=7
```

Note `-F` (typed) not `-f` (string): `-f days=7` is rejected with
`Invalid property /days: "7" is not of type integer`.

## CI runs the isolation suite as the application role (2026-11-08)

The `test` job sets `APP_DB_PASSWORD` for the migration step and then runs
`tests/tenant_isolation/` with `DATABASE_USER=logistics_app` plus
`DATABASE_ADMIN_USER=test_user`.

That split is the point. With `DATABASE_USER` left as the owner, the three
`TestTheRealApplicationCredentialIsSubjectToRls` cases skip and the suite only
ever proves the *policies* are correct using a synthetic probe role — never that
the credential the application actually uses is subject to them. The fixtures
still need the owner, because they write rows for two tenants on one connection,
which RLS correctly forbids the app role from doing.

The CI password is a throwaway value for an ephemeral container, committed
deliberately and marked as such in the workflow; it is not a secret and never
reaches a deployed environment.

## Smoke tests could not see a broken database credential (2026-11-09)

Both smoke suites — `_smoke-test.yml` (AWS) and the smoke step in
`_deploy-azure-env.yml` — checked exactly two things: `/health` returns 200, and
a handful of authenticated routes return 401.

**Neither touches the database.** `/health` is a static response, and a 401 is
produced by the auth layer *before* any query runs. So a deploy whose
application cannot log in to Postgres at all passes both, and reports green.

Demonstrated rather than reasoned about: a local server started with
`DATABASE_PASSWORD=deliberately_wrong_password` still answered `/health` → **200**,
while `/v1/invites/<bogus>` → **500**.

That gap mattered because of the RLS credential switchover (migrations 059/060,
master plan 7.157–7.159). The entire failure mode of pointing `DATABASE_USER` at
`logistics_app` before migration 060 has given that role a password is *exactly*
"every database query fails, nothing else changes" — invisible to every check
these suites performed.

### The probe

Both suites now call `GET /v1/invites/{token}` with an obviously-absent token:

| result | meaning |
|---|---|
| `404` | the app authenticated to Postgres and found no such token — healthy |
| `5xx` | it could not reach or log in to Postgres — fail the deploy |

`/v1/invites/{token}` is public (`shared/http_routing.PUBLIC_ROUTES`), so it needs
no credentials, and it performs a real `customer_invite` lookup.

**Not `/v1/shipments/{tracking-code}`**, the other obvious candidate: it 404s at
*routing*, without ever reaching the database, so it would pass just as happily.
The two 404s are indistinguishable by status code alone — only the response body
(`"route '...'"` vs `"customer_invite '...'"`) tells them apart. Checked before
choosing, which is the only reason the right one was picked.

## `Terraform (Azure)` was permanently red, and that is why nobody saw it (2026-11-09)

`terraform-azure.yml` failed **12 consecutive runs**, 2026-10-14 → 2026-11-09.
Per-job, every one of them looked like this:

```
terraform-dev:     success
terraform-demo:    skipped
terraform-staging: failure     <- azure/login: "Not all values are present"
terraform-prod:    skipped     <- needs: terraform-staging
```

### What was actually wrong

Only staging. Its GitHub Environment holds no `AZURE_CLIENT_ID` /
`AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID`, because **staging does not exist
yet** — so `azure/login` fails and Terraform never gets `ARM_*` credentials.
`ARM_*` is how the `azurerm` provider authenticates to Azure Resource Manager;
the workflow maps the three `AZURE_*` secrets onto them.

`terraform-dev` succeeded in all 12. The dev plan review was working the entire
time.

### Why it still mattered

The run-level conclusion was `failure`, and that is the only thing anyone reads
— a PR check, a run list, a notification. **A check that is permanently red
carries no information:** it cannot tell you something broke, because it is
already broken. It had also been red long enough to be ambient.

It misled an actual reader: while gating master plan 7.159, this was first
written up as "the Azure infra-review gate has been dead for a month, #128's
Terraform was never reviewed by CI." That was wrong — dev plans had reviewed it
all along. The correction came from reading per-job conclusions instead of the
run's.

### The fix

`terraform-staging` and `terraform-prod` are now gated on repo variables
`AZURE_STAGING_READY` / `AZURE_PROD_READY`. Unset, they skip cleanly and the
workflow is green, so the dev plan is a signal again. Set one to `true` once that
Environment has its three secrets.

Repo **variables**, not a secret-presence check: a job-level `if` cannot see
Environment secrets, because the environment is not resolved until the job
starts.

### Why the deploy pipeline was left alone

`deploy-azure.yml`'s staging/prod jobs fire only on an explicit `-rc`/release tag
or `workflow_dispatch` — never automatically on push, so they never go red
unprompted. And there a hard failure is *correct*: a staging deploy was asked
for and staging is not set up. Silently skipping a requested deploy would be
worse than failing it. The plan job differs precisely because nobody asked for
it.

## Coverage upload had never worked, silently (2026-11-11)

Investigating Dependabot #5 (`codecov/codecov-action` v3 → v7) showed the version
was never the problem. Every CI run on `main` logged:

```
['info'] -> No token specified or token is empty
['error'] There was an error running the uploader: 429 -
         {"message":"Rate limit reached. Please upload with the Codecov
          repository upload token to resolve issue."}
['info'] Codecov will exit with status code 0.
```

This repository is **private**, and Codecov requires an upload token for private
repos. None was configured — `CODECOV_TOKEN` appears nowhere in `.github/`. And
`fail_ci_if_error: false` turned the failure into a green step, so nothing ever
surfaced it.

**The bump alone would not have fixed it.** codecov-action **v4+ makes the token
mandatory**, so v7 without a token fails too — just with a different message.

### What changed

- the step is **skipped** when `CODECOV_TOKEN` is unset, so it stops pretending
  to do something
- it passes the token and uses `@v7` when one is set — no further change needed
  once the secret is added
- `fail_ci_if_error: false` stays, deliberately: coverage reporting being down
  should not fail everyone's build

`CODECOV_TOKEN` is set at **job** level because a step cannot read its own `env:`
in its own `if`, and the `secrets` context is not dependable there.

### To actually get coverage reporting

Add `CODECOV_TOKEN` as a repository secret (Codecov → repo settings → upload
token). Until then the step skips, which is the honest state: **there is no
coverage data in Codecov for this project and there never has been**, so any
coverage figure quoted from it would be wrong.

## The frontend now auto-deploys to dev, like the backend (2026-11-11)

`frontend-deploy.yml` was **`workflow_dispatch`-only** while `deploy-azure.yml`
auto-deploys on every successful CI run on `main`. The asymmetry produced exactly
what it guarantees: the deployed SPA sat at commit `c371280` (2026-10-17) for 25
days — **24 frontend commits behind** — while the backend shipped **17 commits and
20 migrations** past it. A user hit the result as "logged in, nothing loads".

### What changed

```yaml
on:
  workflow_run:
    workflows: ["Frontend CI"]
    types: [completed]
    branches: [main]
  workflow_dispatch: ...
```

- **dev only** is automatic; staging/prod stay deliberate dispatches
- gated on **Frontend CI succeeding**, so a red build is never published
- gated on `vars.DEPLOY_CLOUD == 'azure'` for automatic runs

### The trap this had to avoid

The job's steps are all gated `if: inputs.cloud == 'azure'`, and on a
`workflow_run` event **every `inputs.*` is empty**. Adding the trigger naively
would have produced a job that completed **green having deployed nothing** —
worse than the drift it was fixing, because it would look solved.

So a `resolve` job computes the target once and the deploy job reads
`needs.resolve.outputs.*`. `environment:` can read `needs.*.outputs` where it
cannot read `env`, which is why a plain job-level `env` would not work here.

Workflow-level `concurrency` cannot see `needs` at all, so it keeps
`inputs.* || 'default'` fallbacks.

### Defaults were also inverted

`cloud` defaulted to `aws` (the cloud this project does not deploy) and
`environment` to **`prod`**. An unedited dispatch therefore attempted an AWS
*production* frontend deploy; it failed only because AWS credentials are absent.
Now `azure` / `dev`, with `prod` selectable but never the unchosen default.

## Redis service for the database tests (2026-11-15)

The `test` job now starts a `redis:7` service container beside Postgres, and the "Run database integrity tests" step passes `REDIS_HOST`/`REDIS_PORT`. `tests/db/test_rate_limit_redis.py` exercises the limiter's Lua script and a real outage; without a server those tests skip, so CI fails them outright when `CI` is set and `REDIS_HOST` is not.

## Coverage is enforced, not only reported (audit OPS-03, 2026-11-17)

Before: coverage went to Codecov (and only when a token was set, which it is not), with `fail_ci_if_error: false` and no threshold, so a change could delete the tests of the code that moves money and stay green.

Now `ci.yml` runs `scripts/check_coverage.py coverage.xml` right after the unit tests. It reads the floors in `pyproject.toml` under `[tool.shipx.coverage-floors]` (line coverage, per directory) and fails when one is not met, or when a floored directory has no measured lines (a rename must not switch its floor off). Floors were set at each directory's level on 2026-11-17: `services/billing` 53.8 %, `services/payment_release` 71.6 %, `services/refunds` 40.7 %. The script prints a hint when coverage is a point or more above a floor; raise the floor in the same change. No external service, so no cost and no token.

Shown locally: running the unit tests without `test_billing.py` and `test_invoice_credits.py` drops `services/billing` to 29.6 % and the check exits 1. Not yet seen failing in GitHub Actions itself.

Frontend: there is no coverage number to hold (vitest runs without coverage). Instead `src/pages/untestedPages.test.ts` lists the 18 pages that still have no sibling test and fails when a new untested page appears, or when a listed page gains a test and is not removed from the list. The money-moving pages that had none (`MyBilling`, `RefundRequest`, `CarryoverLedger`) and the platform tenant page now have tests.

## Lambda zips carry the `services` package (2026-11-19)

**Bug found and fixed (HIGH on AWS, before go-live):** each service zip was `services/` flattened at the root, so the handler `tracking.handler` resolved but its `from services.billing.service import …` did not. The tracking and claims Lambdas failed at import (`No module named 'services'`), and lazy cross-service imports (packing-list approval → payment_release, customer invites from the import) would have failed when reached. Azure was not affected (its container image has the whole tree).

- `ci.yml` "Build service zips" and "Build scheduled job zips" now add the `services/` tree a second time, as the package, to each zip; `scripts/build_lambda_zip.sh` does the same for the Terraform-built package. Handler paths are unchanged.
- The offboarding-export Lambda (`scheduled.offboarding_export`, audit BE-10) existed in Terraform but was never built or deployed by CI; it is in both lists now.
- Guarded by `tests/unit/test_infrastructure_contracts.py::TestLambdaPackageLayout`: every Terraform-configured handler is imported, isolated (`python -I`), from a copy of the zip layout; every zip step must add the package; every scheduled Lambda must be built and deployed. Both workflow checks fail on the previous workflows.
- Note: the Terraform fallback (`archive_file` over `services/` when no package was built) is still flattened only; CI's `update-function-code` replaces it on the first deploy.

---

## CI/CD pipeline audit and streamlining (2026-11-23)

A full audit of all 10 workflows, `Dockerfile`, `.pre-commit-config.yaml`, `Makefile`, and contract tests uncovered two critical bugs, five high-severity reliability gaps, and major build/rollout duplication. All fixes are now live in `.github/workflows/` and `.github/actions/` and guarded by `tests/unit/test_infrastructure_contracts.py::TestCiCdWorkflowContracts`.

### Bugs fixed

1. **Three AWS Lambdas were never deployed (`notif-api`, `notif-webhook`, `auth`):** Provisioned by `infrastructure/aws/modules/lambda/main.tf` but omitted from `_deploy-env.yml`. All 25 non-migrate Lambdas now deploy from a single shared `build/services.zip`, guarded by `test_every_lambda_in_terraform_is_deployed`.
2. **Trivy scan never failed CI:** `aquasecurity/trivy-action` defaulted to `exit-code: '0'`. Added `exit-code: '1'` and `ignore-unfixed: true`.
3. **Azure & Frontend untrusted checkout / missing tag CI verification:**
   - `deploy-azure.yml` now runs a `prepare` job verifying that `CI Pipeline` succeeded for tagged commits (`v*-rc*`, `v*`) before allowing staging/prod deploys.
   - `_deploy-azure-env.yml` and `frontend-deploy.yml` now pin `actions/checkout` to the exact resolved `ref:` (`workflow_run.head_sha` on automatic runs, `github.sha` on tag runs, or optional `inputs.ref` on manual rollback dispatches) instead of checking out floating `main`.
4. **Broken `workflow_dispatch` job graphs & `deploy-prod` bypass:**
   - `deploy.yml` unified `resolve-artifact` into a `prepare` job so `workflow_dispatch` to `staging` is no longer silently skipped, and `deploy-prod` explicitly requires `needs.prepare.result == 'success'`.
   - `terraform.yml` and `terraform-azure.yml` fixed `always()` + `needs.*.result` expressions so manual dispatches for `staging` and `prod` execute instead of skipping silently.
5. **Per-ref concurrency races:** Replaced workflow-level `github.ref` concurrency groups in `deploy.yml`, `deploy-azure.yml`, `terraform.yml`, and `terraform-azure.yml` with per-environment job-level concurrency (`deploy-aws-<env>`, `deploy-azure-<env>`, `terraform-aws-<env>`, `terraform-azure-<env>`). Concurrent prod tags now serialize cleanly, and a dev deploy never blocks a prod hotfix.
6. **Migration Lambda version drift & stale layer order:** `_deploy-env.yml` now publishes `shared-layer.zip` first (immutable ARN) and attaches it to `logistics-migrate-<env>` before running migrations; `migrate.zip` drops the hardcoded `alembic==1.13.0 psycopg2-binary==2.9.11` install (which had drifted from `psycopg2-binary==2.9.13` in `uv.lock`) and ships only `migrations/` + `handler.py`.
7. **Pre-merge Terraform validation:** Both `terraform.yml` and `terraform-azure.yml` now run a credential-free `validate` job (`terraform fmt -check -recursive`, `init -backend=false`, `validate`) on `pull_request`.

### Streamlining & performance gains

- **4 local composite actions under `.github/actions/`** eliminate duplicated YAML across workflows:
  - `.github/actions/smoke-test`: shared by AWS (`_smoke-test.yml`) and Azure (`_deploy-azure-env.yml`), restoring the missing 2s SLA probe on Azure.
  - `.github/actions/setup-playwright`: caches `~/.cache/ms-playwright` keyed on the locked `@playwright/test` version across `e2e-smoke`, `e2e-local-stack`, and `visual`.
  - `.github/actions/start-local-stack`: deduplicates local-stack bring-up between `e2e-local-stack` and `visual`, adds `uv sync --frozen`, and replaces `npx --yes wait-on` downloads with native `curl` loops.
  - `.github/actions/terraform-run`: shared init/bootstrap-import/plan/apply runner across all AWS and Azure Terraform jobs.
- **Fast path filtering + parallel backend CI (`ci.yml`):** A 3s fail-open `changes` job skips `lint`, `test`, `security` (and dev redeploys in `deploy.yml`/`deploy-azure.yml`) on docs-only and frontend-UI-only commits while preserving required check names (`frontend/src/api/*` still triggers backend CI for API Gateway contract tests). `lint`, `test`, and `security` now run in parallel, and `lint` enforces `uv run ruff format --check .` alongside `ruff check` and `mypy`.
- **~75% smaller AWS artifact & zero Azure waste:** `ci.yml`'s `build` job is gated on `vars.DEPLOY_CLOUD != 'azure'` and builds **one** `services.zip` instead of 20 identical copies (~25 MB instead of ~105 MB; 0 MB when on Azure).
- **Parallel cloud rollouts + cached Docker builds:** `_deploy-env.yml` rolls Lambdas 6-wide (~45s vs ~4–5 min); `_deploy-azure-env.yml` builds with Docker Buildx + GHA layer cache (`type=gha,scope=backend`), skips double-updating the migrate job, and rolls Container Apps/Jobs 5-wide (~45–60s vs ~4–6 min).
- **Single frontend deploy pipeline + least privilege:** Removed the duplicated AWS prod-on-main `deploy` job, top-level `id-token: write`, and unused `frontend-dist-*` upload from `frontend-ci.yml`. `frontend-deploy.yml` now handles both Azure and AWS (auto-deploying `dev` on `main`, manual dispatch with optional `ref` for rollback) and fixes cache-control headers so only hashed `dist/assets/*` are `immutable` while `theme-init.js`, `favicon.svg`, and `index.html` (uploaded last) stay `no-cache`.
- **Tooling alignment:** `.pre-commit-config.yaml` synced to `ruff-pre-commit v0.17.4` and `uv run mypy`; `Makefile` `lint`/`check` targets now run `uv run ruff format --check .`.
