# Task 01 — Project Setup & Repository Structure

> **Prerequisite:** Read `00_CROSS_CUTTING_STANDARDS.md` before starting.

## Objective

Set up the monorepo structure, Python project configuration, dependency management, and foundational config files for the Logistics & Cargo Management System backend.

## Context

- **Runtime:** Python 3.12 on ARM64 (Graviton2)
- **Framework:** AWS Lambda handlers (no web framework — raw event/context pattern)
- **Validation:** Pydantic v2
- **Database Driver:** psycopg2 (via psycopg2-binary for Lambda)
- **Tracing:** AWS X-Ray SDK
- **IaC:** Terraform (>= 1.7, AWS provider ~> 5.40)
- **Testing:** pytest
- **Linting:** ruff, mypy
- **Security Scanning:** bandit, safety, trivy
- **Region:** eu-west-1

## Deliverables

Create the following directory structure and files:

```
logistics-system/
├── infrastructure/                 # Terraform (built in tasks 04a–04e)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── providers.tf
│   ├── versions.tf                 # Terraform + provider version constraints
│   ├── backend.tf                  # S3 + DynamoDB remote state config
│   ├── locals.tf                   # Common tags, naming conventions
│   ├── modules/
│   │   ├── networking/
│   │   ├── aurora/
│   │   ├── cognito/
│   │   ├── api-gateway/
│   │   ├── lambda/
│   │   ├── s3/
│   │   ├── sqs/
│   │   ├── eventbridge/
│   │   └── monitoring/
│   └── environments/
│       ├── dev.tfvars
│       ├── dev.backend.hcl
│       ├── staging.tfvars
│       ├── staging.backend.hcl
│       ├── prod.tfvars
│       └── prod.backend.hcl
├── services/                       # Lambda functions
│   ├── tenant_management/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   ├── cognito_client.py
│   │   └── models.py
│   ├── packing_list/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── manifest/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── tracking/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── billing/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── claims/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── payment_release/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── notification/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── tenant_branding.py
│   │   └── models.py
│   ├── metering/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── excel/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── export_packing_list.py
│   │   ├── export_manifest.py
│   │   ├── export_billing.py
│   │   ├── import_packing_list.py
│   │   ├── repository.py
│   │   └── models.py
│   ├── refunds/
│   │   ├── __init__.py
│   │   ├── handler.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── models.py
│   └── scheduled/
│       ├── __init__.py
│       ├── storage_fee.py
│       ├── dispute_escalation.py
│       ├── sla_check.py
│       ├── storage_reminders.py
│       ├── data_cleanup.py
│       ├── usage_aggregation.py
│       └── release_expiry.py
├── shared/                         # Lambda layer (shared code)
│   ├── __init__.py
│   ├── db.py
│   ├── auth.py
│   ├── tenant_context.py
│   ├── events.py
│   ├── responses.py
│   ├── models.py
│   ├── exceptions.py
│   ├── pagination.py
│   ├── audit.py
│   ├── cache.py                    # In-memory TTL cache for tenant config
│   ├── idempotency.py             # Idempotency-Key support
│   ├── circuit_breaker.py         # Circuit breaker for external APIs
│   ├── logging_config.py          # Structured JSON logging setup
│   ├── metering.py                # record_usage() helper
│   └── notifications.py           # enqueue_notifications() helper
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   └── __init__.py
│   ├── integration/
│   │   └── __init__.py
│   ├── e2e/
│   │   └── __init__.py
│   ├── tenant_isolation/
│   │   └── __init__.py
│   └── load/
│       └── __init__.py
├── scripts/
│   ├── migrate.py
│   ├── seed.py
│   ├── onboard_tenant.py
│   └── backup_verify.py           # DR backup verification script
├── docs/
│   ├── runbook.md                  # Operational runbook
│   ├── adr/                        # Architecture Decision Records
│   │   ├── 001-serverless-over-ecs.md
│   │   ├── 002-shared-db-rls.md
│   │   └── ...
│   └── api-spec/                   # OpenAPI spec fragments per service
├── migrations/                     # Alembic migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── pyproject.toml                  # deps (uv): [project] runtime, [optional].azure, [dependency-groups] dev/layer
├── uv.lock                         # fully-resolved, hash-locked dependency lock (source of truth)
├── Dockerfile.lambda               # Optional: Lambda container image build
├── Makefile
├── .env.example
├── .gitignore
├── .editorconfig
└── README.md
```

## File Contents to Create

### `pyproject.toml`

```toml
[project]
name = "logistics-system"
version = "1.0.0"
description = "Multi-tenant Logistics & Cargo Management System"
requires-python = ">=3.13"

[tool.ruff]
target-version = "py313"
line-length = 130

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "S"]  # S = bandit rules

[tool.mypy]
python_version = "3.13"
strict = true
plugins = ["pydantic.mypy"]
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: Unit tests (no external dependencies)",
    "integration: Integration tests (requires database)",
    "isolation: Tenant isolation tests (requires database)",
    "load: Load/performance tests",
]
```

### Dependencies — `pyproject.toml` + `uv.lock` (managed with uv)

Dependencies live in `pyproject.toml` and are locked in `uv.lock` (the source of
truth — fully resolved + hash-locked). There are no `requirements*.txt` files.

- `[project].dependencies` — runtime deps bundled into the shared Lambda layer
  (boto3, pydantic, psycopg2-binary, cryptography, aws-xray-sdk, openpyxl, redis, reportlab).
- `[project.optional-dependencies].azure` — Azure portability SDKs (`uv sync --extra azure`).
- `[dependency-groups].dev` — test/lint/local tooling (pytest, ruff, mypy, bandit, safety, moto, flask, …).
- `[dependency-groups].layer` — extras the layer bundles beyond runtime (alembic for the migrate Lambda).

Common commands:

```bash
uv sync --extra azure                 # create .venv + install runtime + dev + azure
uv run pytest tests/unit              # run in the managed env
uv lock                               # re-resolve after editing pyproject
# Lambda layer (arm64, python3.13): export the locked layer deps, then install for the target
uv export --frozen --no-hashes --no-emit-project --no-default-groups --group layer -o build/layer-reqs.txt
uv pip install --python-platform aarch64-manylinux_2_28 --python-version 3.13 --only-binary :all: --target build/layer/python -r build/layer-reqs.txt
```

### `infrastructure/aws/versions.tf`

```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

### `infrastructure/aws/backend.tf`

```hcl
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
```

### `infrastructure/aws/environments/dev.backend.hcl`

```hcl
bucket         = "logistics-terraform-state-ACCOUNT_ID"
key            = "logistics/dev/terraform.tfstate"
region         = "eu-west-1"
dynamodb_table = "logistics-terraform-locks"
encrypt        = true
```

### `infrastructure/aws/locals.tf`

```hcl
locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "logistics-platform"
    Owner       = "platform-engineering"
  }

  name_prefix = "${var.project_name}-${var.environment}"
}
```

### `.env.example`

```bash
# Database
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=logistics
DATABASE_USER=logistics_app
DATABASE_PASSWORD=changeme
DB_SECRET_ARN=arn:aws:secretsmanager:eu-west-1:000000000000:secret:logistics-db-password

# AWS
AWS_REGION=eu-west-1
COGNITO_USER_POOL_ID=eu-west-1_XXXXXXX
COGNITO_CLIENT_ID=xxxxxxxxxxxx

# S3
S3_BUCKET_NAME=logistics-assets

# EventBridge
EVENT_BUS_NAME=logistics-events

# Service
SERVICE_NAME=logistics-unknown
ENVIRONMENT=dev
LOG_LEVEL=DEBUG

# Tracing
AWS_XRAY_TRACING_NAME=logistics
_X_AMZN_TRACE_ID=Root=1-00000000-000000000000000000000000
```

### `.editorconfig`

```ini
root = true

[*]
indent_style = space
indent_size = 4
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true

[*.{tf,hcl}]
indent_size = 2

[*.{yml,yaml}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false
```

### `.gitignore`

```
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.env
.terraform/
*.tfstate*
.terraform.lock.hcl
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/
*.zip
node_modules/
.venv/
.ruff_cache/
```

### `Makefile`

```makefile
.PHONY: install lint test test-unit test-integration test-isolation migrate seed deploy clean security-scan

install:
	uv sync --extra azure

lint:
	uv run ruff check .
	uv run mypy shared/ services/ --ignore-missing-imports

security-scan:
	uvx bandit@1.9.4 -r services/ shared/ -ll -q -c pyproject.toml
	uv export --frozen --no-hashes --no-emit-project --no-default-groups --extra azure -o requirements-scan.txt
	uv run safety check -r requirements-scan.txt

test: test-unit

test-unit:
	uv run pytest tests/unit/ -v --cov=services --cov=shared --cov-report=term-missing -m unit

test-integration:
	uv run pytest tests/integration/ -v -m integration

test-isolation:
	uv run pytest tests/tenant_isolation/ -v -m isolation

test-all:
	uv run pytest tests/ -v --cov=services --cov=shared --cov-report=xml

migrate:
	uv run python scripts/migrate.py

seed:
	uv run python scripts/seed.py

package-layer:
	mkdir -p build/layer/python
	uv export --frozen --no-hashes --no-emit-project --no-default-groups --group layer -o build/layer-reqs.txt
	uv pip install --python-platform aarch64-manylinux_2_28 --python-version 3.13 --only-binary :all: -t build/layer/python -r build/layer-reqs.txt
	cp -r shared/ build/layer/python/shared/
	cd build/layer && zip -r ../shared-layer.zip python/

clean:
	rm -rf build/ dist/ *.egg-info __pycache__ .pytest_cache .mypy_cache .ruff_cache
```

### `shared/exceptions.py`

```python
"""Custom exceptions for the logistics system.

Every exception maps to an RFC 7807 error response with a unique error_code.
See 00_CROSS_CUTTING_STANDARDS.md §1.5 for the full error catalog.
"""


class LogisticsBaseError(Exception):
    """Base exception for all logistics system errors."""
    def __init__(self, message: str, error_code: str, status_code: int = 500):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationRequiredError(LogisticsBaseError):
    def __init__(self) -> None:
        super().__init__(
            message="Authentication required",
            error_code="AUTHENTICATION_REQUIRED",
            status_code=401,
        )


class TenantSuspendedError(LogisticsBaseError):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            message=f"Tenant {tenant_id} is suspended",
            error_code="TENANT_SUSPENDED",
            status_code=403,
        )


class ResourceNotFoundError(LogisticsBaseError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            error_code="RESOURCE_NOT_FOUND",
            status_code=404,
        )


class DuplicateResourceError(LogisticsBaseError):
    def __init__(self, resource_type: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource_type} with identifier '{identifier}' already exists",
            error_code="DUPLICATE_RESOURCE",
            status_code=409,
        )


class IllegalTransitionError(LogisticsBaseError):
    def __init__(self, entity: str, current_state: str, requested_state: str, allowed: list[str]) -> None:
        super().__init__(
            message=f"Cannot transition {entity} from '{current_state}' to '{requested_state}'. Allowed: {allowed}",
            error_code="ILLEGAL_TRANSITION",
            status_code=409,
        )
        self.current_state = current_state
        self.requested_state = requested_state
        self.allowed_transitions = allowed


class BusinessRuleViolationError(LogisticsBaseError):
    def __init__(self, message: str, rule_id: str | None = None) -> None:
        super().__init__(message=message, error_code="BUSINESS_RULE_VIOLATION", status_code=422)
        self.rule_id = rule_id


class SelfApprovalForbiddenError(LogisticsBaseError):
    def __init__(self) -> None:
        super().__init__(
            message="You cannot approve your own submission",
            error_code="SELF_APPROVAL_FORBIDDEN",
            status_code=422,
        )


class PaymentRequiredError(LogisticsBaseError):
    def __init__(self, billing_id: str, outstanding_ngn: float) -> None:
        super().__init__(
            message=f"Payment required. Outstanding: ₦{outstanding_ngn:,.2f}",
            error_code="PAYMENT_REQUIRED",
            status_code=422,
        )
        self.billing_id = billing_id
        self.outstanding_ngn = outstanding_ngn


class UsageLimitExceededError(LogisticsBaseError):
    def __init__(self, limit_type: str, current: int, maximum: int) -> None:
        super().__init__(
            message=f"Usage limit exceeded for {limit_type}: {current}/{maximum}",
            error_code="USAGE_LIMIT_EXCEEDED",
            status_code=429,
        )
        self.limit_type = limit_type
        self.current = current
        self.maximum = maximum


class InsufficientPermissionsError(LogisticsBaseError):
    def __init__(self, action: str, required_role: str) -> None:
        super().__init__(
            message=f"Insufficient permissions for {action}. Required role: {required_role}",
            error_code="INSUFFICIENT_PERMISSIONS",
            status_code=403,
        )


class ApprovalThresholdExceededError(LogisticsBaseError):
    def __init__(self, amount: float, threshold: float, required_role: str) -> None:
        super().__init__(
            message=f"Amount ${amount} exceeds threshold ${threshold}. Requires {required_role}.",
            error_code="APPROVAL_THRESHOLD_EXCEEDED",
            status_code=403,
        )


class ExternalServiceError(LogisticsBaseError):
    def __init__(self, service_name: str, detail: str = "") -> None:
        super().__init__(
            message=f"External service '{service_name}' unavailable. {detail}".strip(),
            error_code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
        )


class IdempotencyConflictError(LogisticsBaseError):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            message=f"Request with idempotency key '{idempotency_key}' is already being processed",
            error_code="IDEMPOTENCY_CONFLICT",
            status_code=409,
        )
```

### `shared/logging_config.py`

```python
"""Structured JSON logging configuration.

See 00_CROSS_CUTTING_STANDARDS.md §3 for the logging standard.
"""
import json
import logging
import os
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """Emit logs as single-line JSON for CloudWatch Insights queries."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": os.environ.get("SERVICE_NAME", "unknown"),
            "environment": os.environ.get("ENVIRONMENT", "unknown"),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging() -> logging.Logger:
    """Configure the root logger with structured JSON output."""
    logger = logging.getLogger()
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

    # Remove default Lambda handler if present
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)
    return logger
```

## Acceptance Criteria

- [x] All directories and `__init__.py` files exist
- [x] `pyproject.toml` configured with ruff (including bandit rules via S selector), mypy, pytest with markers
- [x] `pyproject.toml` has exactly-pinned dependencies (incl. `aws-xray-sdk`) + committed `uv.lock`
- [x] `.env.example` has all environment variables documented including `SERVICE_NAME`, `DB_SECRET_ARN`
- [x] `Makefile` has targets for install, lint, security-scan, test-unit, test-integration, test-isolation, test-all, migrate, seed, package-layer (ARM64), clean
- [x] `shared/exceptions.py` error types match the catalog in `00_CROSS_CUTTING_STANDARDS.md` — **corrected 2026-11-11: 17 classes, not 13.** The catalog itself now lists 18 rows. The "13" was accurate when written and both have grown since; the figure is dropped from the criterion so it cannot go stale again.
- [x] `shared/logging_config.py` emits structured JSON logs
- [x] `infrastructure/aws/versions.tf` pins Terraform >= 1.7 and AWS provider ~> 5.40
- [x] `infrastructure/aws/backend.tf` configured for S3 + DynamoDB remote state
- [x] `infrastructure/aws/locals.tf` has common_tags and name_prefix
- [x] `.editorconfig` enforces consistent formatting
- [x] `ruff check .` passes with no errors on the scaffolding
