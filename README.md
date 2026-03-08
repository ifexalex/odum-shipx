# Logistics & Cargo Management System

Multi-tenant SaaS backend for logistics and cargo management, built on AWS serverless infrastructure.

## Tech Stack

- **Runtime:** Python 3.12 on AWS Lambda (ARM64/Graviton2)
- **Database:** Aurora Serverless v2 (PostgreSQL 15.4) with row-level security
- **Auth:** AWS Cognito
- **IaC:** Terraform >= 1.7
- **Region:** eu-west-1 (DR: eu-central-1)

## Quick Start

```bash
# Install dev dependencies
make install

# Run linting
make lint

# Run security scan
make security-scan

# Run unit tests
make test-unit

# Package shared Lambda layer (ARM64)
make package-layer
```

## Project Structure

- `services/` — Lambda function handlers (one directory per microservice)
- `shared/` — Shared Lambda layer code (auth, db, exceptions, logging, etc.)
- `infrastructure/` — Terraform IaC modules
- `tests/` — Unit, integration, tenant isolation, and load tests
- `scripts/` — Database migration, seeding, and operational scripts
- `migrations/` — Alembic database migrations
- `docs/` — Runbook, ADRs, and OpenAPI spec fragments

## Documentation

See `00_MASTER_PLAN.md` for the full architecture and task roadmap.
See `00_CROSS_CUTTING_STANDARDS.md` for mandatory engineering standards.
