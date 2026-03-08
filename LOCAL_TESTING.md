# Local Development Guide

Run the full ShipX platform on your laptop — no AWS account needed.

---

## Table of Contents

1. [How it works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [First-time setup](#3-first-time-setup)
4. [Start the stack](#4-start-the-stack)
5. [Test with Postman](#5-test-with-postman)
6. [Typical development workflow](#6-typical-development-workflow)
7. [Inspect SQS queues and S3](#7-inspect-sqs-queues-and-s3)
8. [Simulate EventBridge events](#8-simulate-eventbridge-events)
9. [Validate Terraform modules](#9-validate-terraform-modules)
10. [Run the test suite](#10-run-the-test-suite)
11. [View the database (Adminer)](#11-view-the-database-adminer)
12. [Troubleshooting](#12-troubleshooting)
13. [Quick-start checklist](#13-quick-start-checklist)

---

## 1. How it works

In production the platform runs on AWS. Locally each AWS service is replaced:

| Production (AWS) | Local replacement | Port |
|---|---|---|
| Aurora PostgreSQL | PostgreSQL 15 (Docker) | 5432 |
| SQS, EventBridge, S3, Secrets Manager, Cognito | **Moto server** (Docker) | 5100 |
| ElastiCache Redis | **Redis 7 Alpine** (Docker) | 6379 |
| API Gateway + Lambda | **`local_server.py`** (Flask) | 3000 |
| AWS Cognito JWT | `X-Role` / `X-User-ID` request headers | — |
| AWS X-Ray | Disabled via env var | — |
| Adminer (DB UI) | Adminer (Docker) | 8080 |

```
Postman / curl
      │
      ▼
local_server.py :3000     ← Flask app that routes HTTP → Lambda handler functions
      │
      ├── services/billing/handler.py
      ├── services/claims/handler.py
      ├── services/packing_list/handler.py
      └── ... (all other handlers)
            │
            ├── PostgreSQL :5432    ← all DB queries
            ├── Moto :5100          ← SQS, S3, EventBridge, Secrets Manager
            └── Redis :6379         ← tenant status distributed cache
```

---

## 2. Prerequisites

Install these tools before starting:

| Tool | Minimum version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Docker Desktop | 24+ | [docker.com](https://www.docker.com/products/docker-desktop/) |
| AWS CLI v2 | 2.x | [aws.amazon.com/cli](https://aws.amazon.com/cli/) |
| Terraform | 1.7+ | `brew install hashicorp/tap/terraform` |

Verify:

```bash
python3 --version     # 3.11+
docker --version      # 24+
aws --version         # aws-cli/2.x
terraform version     # 1.7+
```

---

## 3. First-time setup

### 3.1 Clone and enter the project

```bash
cd /path/to/shipx
```

### 3.2 Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows
```

### 3.3 Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install flask                  # needed only for local_server.py
```

If you also run tests:

```bash
pip install -r requirements-dev.txt
```

### 3.4 Create your local env file

`.env.local` is already in the repo and pre-configured for the local stack. Load it into your shell:

```bash
set -a; source .env.local; set +a
```

> **Tip:** Add this line to your `.zshrc` / `.bashrc` so it loads automatically when you `cd` into the project.

---

## 4. Start the stack

### Makefile reference

All local dev commands are in the `Makefile`:

| Command | What it does |
|---|---|
| `make stack` | **Full reset + setup** — starts containers, bootstraps Moto, **drops and recreates the DB**, runs migrations and seed. Safe to re-run at any time. |
| `make up` | Start Docker containers and wait until all healthy |
| `make down` | Stop all containers |
| `make bootstrap` | Create SQS queues, EventBridge, S3, Secrets Manager in Moto |
| `make migrate` | Apply database migrations |
| `make seed` | Seed the database with sample data |
| `make dev` | Start the local Flask API server on `:3000` |
| `make test-unit` | Run unit tests (no containers needed) |
| `make test-integration` | Run integration tests (containers must be running) |

---

### 4.1 First-time setup (one command)

```bash
make stack
```

This runs in sequence: `make up` → `make bootstrap` → **DB reset** → `make migrate` → `make seed`.

`make stack` is idempotent — it drops and recreates the database every time, so you can safely re-run it to get a clean state without any manual steps.

Expected output:
```
All containers ready.
==> Waiting for Moto to be ready...
    Moto is ready.
==> Creating SQS queues...
    Created: logistics-sms
    ...
==> Bootstrap complete.
==> Resetting database...
Database 'logistics' reset complete.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, ...
...
Stack is ready. Run 'make dev' to start the API server on http://localhost:3000
```

### 4.2 Start the API server

```bash
make dev
```

You should see:

```
╔══════════════════════════════════════════════════════════════╗
║           ShipX Local API Server  →  http://localhost:3000   ║
╚══════════════════════════════════════════════════════════════╝
```

Keep this terminal open. The server stays running while you use Postman.

**Containers started by `make up`:**

| Container | Purpose | Port |
|---|---|---|
| `shipx_postgres` | Database | 5432 |
| `shipx_moto` | AWS services emulator (SQS, S3, EventBridge, SM) | 5100 |
| `shipx_adminer` | Web-based DB viewer | 8080 |

> **Note:** Moto is stateless — SQS queues and S3 buckets are lost when the container restarts. Re-run `make bootstrap` (or `make stack`) after every `make up`.
>
> **Note:** `make up` does **not** reset Moto state — it only waits for the container to be reachable. Moto state is only cleared when the container itself is stopped and restarted.

### 4.3 Verify migrations manually (optional)

```bash
psql -h 127.0.0.1 -U postgres -d logistics -c "\dt"
# Should list ~25 tables: tenant, billing, packing_list, damage_claim, platform_settings, etc.
```

---

## 5. Test with Postman

### 5.1 Import the collection

1. Open Postman → **Import**
2. Select `ShipX_API.postman_collection.json` from the project root
3. The collection appears with 10 folders and 92 pre-built requests

### 5.2 Auth headers

The local server does not validate JWTs. Instead, it reads three headers to simulate auth:

| Header | Purpose | Default |
|---|---|---|
| `X-Tenant-ID` | Which tenant to act as | `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa` |
| `X-Role` | User's role | `nigeria_office_staff` |
| `X-User-ID` | User's ID (used as `actor_id`) | `local-user-001` |

These are already set as collection variables in the Postman collection.

### 5.3 Available roles

| Role | `X-Tenant-ID` header | Access |
|---|---|---|
| `nigeria_office_staff` | `{{tenant_id}}` | Create/read most resources, process payments |
| `tenant_admin` | `{{tenant_id}}` | Full tenant access, approve high-value refunds |
| `warehouse_attendant` | `{{tenant_id}}` | Record pickups |
| `china_office_staff` | `{{tenant_id}}` | Create packing lists |
| `customer` | `{{tenant_id}}` | Read own shipments and billing |
| `platform_admin` | `PLATFORM` | Cross-tenant management (suspend/activate tenants, view dashboard) |

Change the `role` collection variable to switch between roles. For `platform_admin` requests, the Postman collection uses `{{platform_tenant_id}}` (set to `PLATFORM`) as the `X-Tenant-ID`.

> **Note:** Platform admin JWT structure uses `"platform_admin"` as the Cognito group (no tenant prefix) and `custom:tenant_id = "PLATFORM"`. This is handled automatically by `local_server.py`.

### 5.4 Recommended first flow

Run requests in this order to walk through a full shipment lifecycle:

```
1.  Customers → Create Customer            (save customer_id)
2.  Containers → Create Container          (save container_id)
3.  Packing Lists → Create Packing List    (save packing_list_id)
4.  Packing Lists → Submit Packing List
5.  Packing Lists → Approve Packing List   (manifest is auto-created)
6.  Manifests → List Manifests             (save manifest_id)
7.  Manifests → Verify Manifest
8.  Billing → Generate Billing             (save billing_id)
9.  Payment & Release → Confirm Payment
10. Payment & Release → Generate Release Note  (save release_note_id)
11. Payment & Release → Record Pickup
```

After each create request, copy the returned `id` into the matching Postman collection variable.

---

## 6. Typical development workflow

**During active development:**

```bash
# Terminal 1 — keep running
make dev

# Terminal 2 — edit code, then test in Postman
# No restart needed — Flask reloads the handler module on each request
```

**After changing a migration:**

```bash
# Ctrl+C the server, apply migration, restart
make migrate
make dev
```

**After restarting Docker:**

```bash
make up          # restart containers (Postgres data is persisted in Docker volume)
make bootstrap   # recreate Moto resources (SQS/S3/EventBridge are lost on restart)
make dev
```

**Wipe everything and start fresh:**

```bash
make stack   # drops + recreates DB, re-runs migrations and seed
make dev
```

If you also want to wipe the Docker volume (e.g. after a PostgreSQL version change):

```bash
make down
docker volume rm shipx_pgdata
make stack
make dev
```

---

## 7. Inspect SQS queues and S3

After actions that publish events (approve packing list, generate release note, etc.), inspect the queues:

```bash
# Check the SMS queue
aws --endpoint-url http://localhost:5100 sqs receive-message \
    --queue-url http://localhost:5100/123456789012/logistics-sms \
    --max-number-of-messages 5

# Check queue depth
aws --endpoint-url http://localhost:5100 sqs get-queue-attributes \
    --queue-url http://localhost:5100/123456789012/logistics-email \
    --attribute-names ApproximateNumberOfMessages

# List S3 objects (claim evidence uploads)
aws --endpoint-url http://localhost:5100 s3 ls s3://logistics-assets --recursive
```

---

## 8. Simulate EventBridge events

Some handlers react to EventBridge events rather than HTTP calls (e.g., billing is auto-created when a `PaymentDue` event fires). Test these by sending a shaped payload directly to the handler:

```python
# Quick test in Python shell
import json, os
os.environ.update({
    "DATABASE_HOST": "127.0.0.1", "DATABASE_PORT": "5432",
    "DATABASE_NAME": "logistics", "DATABASE_USER": "postgres",
    "DATABASE_PASSWORD": "localpassword", "DATABASE_HOST": "127.0.0.1",
    "AWS_DEFAULT_REGION": "eu-west-1", "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test", "AWS_ENDPOINT_URL": "http://localhost:5100",
    "EVENT_BUS_NAME": "logistics-events", "ENVIRONMENT": "local",
})

from services.billing.handler import lambda_handler

event = {
    "source": "logistics.tracking",
    "detail-type": "PaymentDue",
    "detail": {
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "event_id": "local-evt-001",
        "occurred_at": "2026-02-28T12:00:00Z",
        "request_id": "local-req-001",
        "payload": {
            "container_id": "REPLACE_WITH_REAL_ID",
            "customer_id": "REPLACE_WITH_REAL_ID",
            "container_number": "MSCU1234567",
        },
    },
}

response = lambda_handler(event, {})
print(json.dumps(response, indent=2, default=str))
```

To fire a real event through Moto's EventBridge and confirm it routes to SQS:

```bash
aws --endpoint-url http://localhost:5100 events put-events \
  --region eu-west-1 \
  --entries '[{
    "Source": "logistics.tracking",
    "DetailType": "PaymentDue",
    "EventBusName": "logistics-events",
    "Detail": "{\"tenant_id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\",\"payload\":{\"container_id\":\"c1\"}}"
  }]'

# Confirm it landed in the metering queue
aws --endpoint-url http://localhost:5100 sqs receive-message \
    --queue-url http://localhost:5100/123456789012/logistics-metering
```

---

## 9. Validate Terraform modules

Run `terraform test` to validate module structure without touching real AWS. Tests use Terraform's built-in `mock_provider` — no AWS credentials needed.

```bash
cd infrastructure
terraform test
```

Expected output:
```
tests/networking.tftest.hcl... pass
tests/sqs.tftest.hcl... pass

Success! 5 passed, 0 failed.
```

Test files live in `infrastructure/tests/`. Add new `.tftest.hcl` files for any module you want to validate.

---

## 10. Run the test suite

### Unit tests (no containers required)

```bash
PYTHONPATH=. python3 -m pytest tests/unit/ -v
```

All unit tests use `unittest.mock` — no database or Moto needed. Should show 356 passed.

### Integration tests (containers must be running)

```bash
set -a; source .env.local; set +a
PYTHONPATH=. python3 -m pytest tests/integration/ -v
```

### With coverage report

```bash
PYTHONPATH=. python3 -m pytest tests/unit/ \
    --cov=services --cov=shared \
    --cov-report=term-missing \
    --cov-report=html:coverage_html
open coverage_html/index.html
```

---

## 11. View the database (Adminer)

Open [http://localhost:8080](http://localhost:8080) in your browser:

| Field | Value |
|---|---|
| System | PostgreSQL |
| Server | `host.docker.internal` |
| Username | `postgres` |
| Password | `localpassword` |
| Database | `logistics` |

You can run SQL, browse tables, and inspect row-level security in action.

---

## 12. Troubleshooting

### `ECONNREFUSED 127.0.0.1:3000` in Postman

The local server is not running. Start it:

```bash
set -a; source .env.local; set +a
PYTHONPATH=. python3 scripts/local_server.py
```

### `KeyError: 'DATABASE_HOST'`

Environment variables are not loaded. The server requires them at startup:

```bash
set -a; source .env.local; set +a
PYTHONPATH=. python3 scripts/local_server.py
```

### `Port 3000 is already in use`

A previous server process is still running. Kill it:

```bash
lsof -ti :3000 | xargs kill -9
```

### `No handler registered for path: /v1/...`

The path prefix is not in `_ROUTES` inside `scripts/local_server.py`. Add it:

```python
("/v1/your-new-path", "your_service_module"),
```

### `Address already in use` — Postgres port 5432

Your Mac has a local Postgres installation. Either stop it (`brew services stop postgresql`) or set `DATABASE_HOST=127.0.0.1` in `.env.local` (forces IPv4, bypasses the Docker container).

### Moto resources disappear after restart

Moto is stateless. Re-run bootstrap after every container restart:

```bash
bash scripts/bootstrap_local.sh
```

### `botocore.exceptions.EndpointResolutionError`

`AWS_ENDPOINT_URL` is not set. Load `.env.local`:

```bash
set -a; source .env.local; set +a
```

### `psycopg2.OperationalError: database "logistics" does not exist`

The `make stack` command creates the database automatically via `scripts/reset_db.py`. If you see this outside of `make stack`:

```bash
make stack   # recreates the DB and runs all migrations
```

### `DuplicateTable: relation "tenant" already exists`

This happens when migrations are run against a database that already has tables (stale state). Fix with:

```bash
make stack   # drops and recreates the DB cleanly before migrating
```

### Migration fails partway through

Connect and inspect:

```bash
psql -h 127.0.0.1 -U postgres -d logistics
\dt              # list tables
\d refund_request   # inspect a specific table
```

For a clean slate: `make stack` resets and re-migrates everything.

### X-Ray `SegmentNotFoundException` warnings

Disable X-Ray — it is already set in `.env.local`:

```bash
export AWS_XRAY_SDK_ENABLED=false
```

---

## 13. Quick-start checklist

Copy this checklist for a fresh machine setup:

```
Prerequisites
[ ] Docker Desktop installed and running
[ ] Python 3.11+ installed
[ ] AWS CLI v2 installed
[ ] Terraform >= 1.7 installed

First-time setup
[ ] cd /path/to/shipx
[ ] python3 -m venv .venv && source .venv/bin/activate
[ ] pip install -r requirements.txt && pip install flask
[ ] pip install -r requirements-dev.txt       ← for running tests

Start the stack (one command)
[ ] make stack                                ← up + bootstrap + migrate + seed

Verify
[ ] make test-unit                            ← 356 passed (no containers needed)
[ ] make dev                                  ← server starts on :3000
[ ] Import ShipX_API.postman_collection.json into Postman
[ ] Send GET /v1/customers → 200 OK

Daily dev
[ ] make up && make bootstrap                 ← if containers were stopped overnight
[ ] make dev                                  ← start the API server
[ ] Use Postman collection to test endpoints
```

---

## Architecture reference

```
┌─────────────────── docker compose ──────────────────────┐
│  shipx_postgres :5432   shipx_moto :5000   adminer :8080 │
└──────────────────────────────────────────────────────────┘
                │                │
         DB queries         SQS / S3 / EB / SM
                │                │
         ┌──────▼────────────────▼──────┐
         │   PYTHONPATH=. python3        │
         │   scripts/local_server.py     │  :3000
         │   (Flask → Lambda handlers)   │
         └───────────────────────────────┘
                         ▲
                    Postman / curl
```

### What Moto emulates

- **SQS** — logistics-sms, logistics-whatsapp, logistics-email, logistics-metering + DLQs
- **EventBridge** — `logistics-events` bus + routing rules
- **S3** — `logistics-assets` bucket (claim evidence uploads)
- **Secrets Manager** — `logistics/db/password` secret

### What is deliberately not emulated

- **Cognito JWT validation** — replaced by `X-Role` header in `local_server.py`
- **Lambda runtime** — handlers are called as plain Python functions
- **API Gateway** — replaced by Flask routing in `local_server.py`
- **RDS Proxy** — not needed; Python connects to Postgres directly
