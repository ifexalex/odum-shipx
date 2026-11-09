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
   - [File uploads in local dev (`/__storage` proxy)](#file-uploads-in-local-dev-__storage-proxy)
   - [Seeing a notification actually send](#seeing-a-notification-actually-send)
   - [Test manifest for notification testing](#test-manifest-for-notification-testing)
8. [Simulate EventBridge events](#8-simulate-eventbridge-events)
9. [Validate Terraform modules](#9-validate-terraform-modules)
10. [Run the test suite](#10-run-the-test-suite)
11. [View the database (Adminer)](#11-view-the-database-adminer)
12. [Troubleshooting](#12-troubleshooting)
13. [Quick-start checklist](#13-quick-start-checklist)
14. [Frontend dev server](#14-frontend-dev-server)
15. [Testing the real Microsoft Entra integration locally](#15-testing-the-real-microsoft-entra-integration-locally)

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

`local_server.py` resolves HTTP paths to handlers via `shared/http_routing.py` — the same
route table the production container (`services/http_app`) and API Gateway use. It differs from
production only in auth: it trusts `X-Role`/`X-User-ID` headers, whereas the container verifies a
real token with the same code the AWS authorizer runs (`shared/auth_verify.py`).

**Running the backend as a container (the Azure compute path, ADR-005):** the repo-root `Dockerfile`
builds one image whose entrypoint selects the workload. Useful for verifying the production HTTP app
locally (real token verification, not the `X-Role` shim):

```bash
docker build -t shipx-backend .
docker run -p 8080:8080 -e CLOUD_PROVIDER=azure shipx-backend api   # gunicorn; GET /health → 200
docker run shipx-backend worker --queue sms                          # Service Bus consumer
docker run shipx-backend job --job release_expiry                    # one cron job, then exit
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
| Node.js | **22.x exactly** (see `frontend/.nvmrc`) | `nvm install` from `frontend/` |

Verify:

```bash
python3 --version     # 3.11+
docker --version      # 24+
aws --version         # aws-cli/2.x
terraform version     # 1.7+
node --version        # must be v22.x — see below
```

### Node.js version

The frontend is pinned to the Node major in **`frontend/.nvmrc`** (`22.23.4`), and CI reads that
same file via `node-version-file:` — so local and CI run the same major. `frontend/package.json`
declares `"engines": { "node": "22.x" }`, so `npm ci` prints an `EBADENGINE` warning on any other
version. The warning is **not** fatal (`engine-strict` is deliberately off, so a contributor
without a version manager is never hard-blocked), but do not ignore it: a different major silently
changes test behaviour.

Concretely, Node 26 defines its own global `localStorage`, which **shadows jsdom's** inside Vitest
and is `undefined` unless `--localstorage-file` is passed. That made 7 frontend tests fail locally
while CI was green, and cost real debugging time before the cause was found. `src/test/setup.ts`
now installs an in-memory `Storage` fallback so those tests pass on either major, but the pin is
the actual fix.

```bash
cd frontend && nvm use     # reads .nvmrc
```

If you have no version manager installed, `brew install node@22` and put it on `PATH` ahead of any
newer Node.

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

Dependencies are managed with **uv** (install it once: `pip install uv` or
`curl -LsSf https://astral.sh/uv/install.sh | sh`). `uv sync` creates a `.venv`
and installs the locked deps — runtime + dev tools + flask (for `local_server.py`):

```bash
uv sync --extra azure        # runtime + dev group + azure SDKs — keep the extra, see the note below
```

Then either prefix commands with `uv run` (e.g. `uv run pytest`, `uv run python scripts/...`)
or activate the venv: `source .venv/bin/activate`.

**Do not omit `--extra azure`.** A plain `uv sync` *prunes* the azure extra, and
`tests/unit/test_entra_identity_provider.py` then fails with
`ModuleNotFoundError: No module named 'azure'` — which looks like a code regression and is not
one. CI always runs `uv sync --extra azure`, so match it locally.

**Install the pre-commit hooks** (once per clone). They are what gate a commit locally, and they
are *not* the same checks as CI:

```bash
uv run pre-commit install
```

| Hook | Scope | Notes |
|---|---|---|
| `ruff-check` (`--fix --exit-non-zero-on-fix`) | staged `*.py` | auto-fixes, then fails so you can inspect the fix |
| `ruff-format` | staged `*.py` | CI does **not** run the formatter — only this hook does |
| `mypy` | `shared/ services/` | `always_run`, so it ignores which files you staged |

`ruff` is pinned in **two** places and both must move together: `pyproject.toml`
(`ruff==0.17.3`, what CI runs via `uv run ruff check .`) and `.pre-commit-config.yaml`
(`rev: v0.17.3`, what the hook runs). Dependabot only ever bumps the first, so a ruff PR from it
is incomplete — bump the `rev` in the same change or local and CI silently diverge.

### 3.4 Create your local env file

**Two files, not one.** The backend and the frontend each need their own, both
copied from tracked samples:

```bash
cp .env.local.sample .env.local                    # backend (Flask, scripts)
cp frontend/.env.local.sample frontend/.env.local  # frontend (Vite)
```

Copy the frontend one **before** running `make bootstrap` / `make stack`: the
bootstrap script rewrites its `VITE_COGNITO_USER_POOL_ID` /
`VITE_COGNITO_CLIENT_ID` lines with the IDs Moto generates, but only if the file
already exists. Skip it and `VITE_API_BASE_URL` is undefined, so
`src/api/client.ts` throws before any request is sent and **every** API call
fails — pages render but all data is missing, which is confusing to debug.

Note the `.sample` suffix: the root `.gitignore` ignores `.env.*` and negates
only `!.env.example` and `!.env.local.sample`, so a `.env.local.example` file is
untracked and exists only on the machine that made it.


`.env.local` is **gitignored** (it once held live Cognito IDs — commit 6c0f955), so a fresh
checkout has none. Create it from the tracked, non-secret template:

```bash
cp .env.local.sample .env.local
```

`make dev`, `make bootstrap`, and `make stack` also create it from the sample automatically if it's
missing, and `scripts/bootstrap_local.sh` rewrites the `COGNITO_*` / `SQS_*` values in it each run.
Load it into your shell for ad-hoc commands:

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
| `make dev` | Start the local Flask API server on `:3000` | Single-threaded (`threaded=False`) — see note below.
| `make test-unit` | Run unit tests (no containers needed) |
| `make test-integration` | Run integration tests (containers must be running) |

---

> **Why the dev server is single-threaded.** Flask's `app.run()` defaults to
> `threaded=True`, but `shared/db.py`'s module-level `_connection` (the
> warm-Lambda-container reuse pattern) has no lock — two concurrent requests
> sharing it can corrupt its transaction state, breaking arbitrary *other*
> requests with `psycopg2.errors.InFailedSqlTransaction`. Real Lambda never
> has this hazard (one container, one invocation at a time), so
> `threaded=False` also matches production's actual execution model. One
> practical effect: a page that fires several fetches at once now serves
> them one at a time rather than in parallel — noticeably slower on
> data-heavy dashboards, but correct. See `02_shared_utilities.md`'s
> "Local dev server made single-threaded" for the full incident.

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
| `shipx_azurite` | Azure Storage emulator (Blob/Queue/Table) — portability tests | 10000-10002 |
| `shipx_adminer` | Web-based DB viewer | 8080 |

> **Azurite (Azure portability):** optional — the **pytest suite is fully mocked and
> does not need it**. It's used only by `scripts/azure_smoke.py` for live SAS
> round-trips against a local Azure Storage emulator. Start it with
> `docker compose -f docker-compose.local.yml up -d azurite`; see
> `infrastructure/azure/README.md` → "Local testing".

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
| `X-Role` | User's **primary/active** role | `nigeria_office_staff` |
| `X-Roles` | (optional, migration 039) Comma-separated list of *every* role the user holds — multi-role staff support. Omit for a single-role user; defaults to `[X-Role]` when absent. | — |
| `X-User-ID` | User's ID (used as `actor_id`) | `local-user-001` |

These are already set as collection variables in the Postman collection. `X-Roles` isn't
wired into the collection's default variables (no multi-role request needs it out of the
box) — add it manually to a request's headers to test as a multi-role user, e.g.
`X-Role: nigeria_office_staff` + `X-Roles: nigeria_office_staff,warehouse_attendant`.

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

## File uploads in local dev (`/__storage` proxy)

Every upload in this app is a **browser `PUT` straight to object storage** against
a presigned URL (`frontend/src/api/uploads.ts`) — the API only mints the URL, the
bytes never pass through it. That path needs two things locally that you get for
free in a deployed environment:

1. **A CORS rule on the bucket.** `make bootstrap` now applies one to the Moto
   bucket, mirroring the real bucket's `cors_rule` in
   `infrastructure/aws/modules/s3/main.tf`.
2. **A same-origin route to storage.** Necessary because Moto validates the
   presigned signature on the CORS **preflight** `OPTIONS` and rejects it with
   `SignatureDoesNotMatch` — the signature was computed for the `PUT`. Real S3
   answers preflight unauthenticated, so this is Moto-only, but it means no
   browser upload can succeed against Moto directly.

So `vite.config.ts` proxies `/__storage` → the storage endpoint, and
`scripts/local_server.py` rewrites the presigned URLs it returns onto that
prefix. The `PUT` becomes same-origin and no preflight is sent. The signature
still validates: SigV2's string-to-sign covers the object path, which the proxy
preserves, not the host.

| Env var | Default | Purpose |
|---|---|---|
| `LOCAL_UPLOAD_PROXY_BASE` | `http://localhost:5173/__storage` | Prefix the dev server rewrites presigned URLs onto. **Set it empty to disable the rewrite** and get raw Moto URLs back. |
| `VITE_STORAGE_PROXY_TARGET` | `http://localhost:5100` | Where Vite forwards `/__storage`. |

**From curl or Postman, set `LOCAL_UPLOAD_PROXY_BASE=` (empty).** Those clients
ignore CORS and need no proxy, and with the rewrite on they would be sent through
Vite, which must then be running.

Note that both the Flask server and Vite must be **restarted** after changing
either variable — the rewrite is read at import time and the proxy at startup.

---

## Seeing a notification actually send

In AWS an SQS event-source mapping feeds the notification Lambdas. Nothing plays
that role against Moto, so a locally enqueued notification sits in the queue and no
provider is ever called — which looks identical to a silent failure.
`scripts/drain_notifications.py` is that missing link: it dispatches queued messages
through the real `sms_handler` / `whatsapp_handler` / `email_handler`, so the
recipient allowlist, template rendering, and provider responses are all exercised
for real.

**`make dev` / `python3 scripts/local_server.py` now runs this automatically** —
the server spawns `scripts/drain_notifications.py --watch` as a background
**process** on startup (terminated when the server stops), so a locally
enqueued notification is drained within a couple of seconds with nothing to run
by hand. Ground-truth gap found live: a user rejected a payment claim, checked
as both the staff account and the customer account, and saw no notification
either way — the enqueue itself had worked correctly, but nothing ever drained
the queue, so it looked exactly like a silent bug. Deliberately a **process**,
not a thread: `local_server.py`'s `app.run(..., threaded=False)` exists because
`shared/db.py`'s module-level connection singleton isn't thread-safe, and a
poller thread sharing the server's own connection would reintroduce that exact
hazard. Set `DISABLE_NOTIFICATION_DRAIN=true` to turn it off and go back to
draining by hand:

```bash
python3 scripts/drain_notifications.py            # drain once and exit
python3 scripts/drain_notifications.py --watch    # poll until interrupted
python3 scripts/drain_notifications.py --peek     # show messages, consume none
python3 scripts/drain_notifications.py --channel whatsapp
```

Then read the outcome from the log, which now records *why* a send failed:

```sql
SELECT channel, status, locale, retry_of, error_detail
FROM notification_log ORDER BY created_at DESC LIMIT 5;
```

A WhatsApp row followed by an SMS row whose `retry_of` points at it is the
fallback working.

`CUSTOMER_PORTAL_BASE_URL` must be set or invite links render as a bare
`/invite/{token}`.

## Test manifest for notification testing

`scripts/make_test_manifest.py` writes a forwarder-shaped workbook (metadata block,
two-row header, totals footer, one carton row and one bale row) containing a single
consignee — the tester's own contact. Imported manifests hold **real customer phone
numbers**, so never re-import one to test notifications.

```bash
python3 scripts/make_test_manifest.py --out /tmp/test_manifest.xlsx --container TEST001
```

Note that invites are auto-issued only for customers an import *creates*. Re-importing
a manifest whose consignee already exists issues nothing; use
`POST /v1/customers/{id}/invite` to trigger the notification in that case.

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
cd infrastructure/aws
terraform test
```

Expected output:
```
tests/networking.tftest.hcl... pass
tests/sqs.tftest.hcl... pass

Success! 5 passed, 0 failed.
```

Test files live in `infrastructure/aws/tests/`. Add new `.tftest.hcl` files for any module you want to validate.

---

## 10. Run the test suite

### Unit tests (no containers required)

```bash
PYTHONPATH=. python3 -m pytest tests/unit/ -v
```

All unit tests use `unittest.mock` — no database or Moto needed. Should show **1400 passed** (this read 356 until 2026-11-07, which had been stale for a long time).

### Integration tests (containers must be running)

```bash
set -a; source .env.local; set +a
PYTHONPATH=. python3 -m pytest tests/integration/ -v
```

### Two database credentials (since migration 060)

`.env.local` now carries both, and they are not interchangeable:

| variable | role | used by |
|---|---|---|
| `DATABASE_USER` / `DATABASE_PASSWORD` | `logistics_app` | the application (`shared/db.py`) |
| `DATABASE_ADMIN_USER` / `DATABASE_ADMIN_PASSWORD` | `postgres` (owner) | `reset_db.py`, alembic, `seed.py` |
| `APP_DB_PASSWORD` | — | migration 060, which sets it on `logistics_app` |

`APP_DB_PASSWORD` **must equal** `DATABASE_PASSWORD`. If they drift, the stack
builds fine and then every request fails with
`password authentication failed for user "logistics_app"`. Migration 060 prints
a `WARNING:` naming the mismatch when it sees one, so the failure is no longer
silent until the first request.

`.env.local.sample` pre-fills both with the **same** local-only literal, so a
verbatim copy works — which is how it is used: `make env` and
`.github/workflows/frontend-ci.yml` both copy it unedited. It briefly shipped two
*different* placeholders (`paste-the-generated-value-here` vs
`paste-the-same-generated-value-here`), which broke every fresh clone and the
`e2e-local-stack` job. To use your own value, change both.

Why the split: `logistics_app` holds only SELECT/INSERT/UPDATE/DELETE and has no
`BYPASSRLS`, so the row-level-security policies are actually enforced against
it. DDL and the cross-tenant fixture writes in `seed.py` need the owner.
`shared/db_credentials.py` resolves the admin pair and **falls back** to
`DATABASE_*`, so an old `.env.local` without the new variables keeps working
exactly as before — it simply runs everything as the owner, with RLS inert.

To check enforcement is real:

```bash
set -a; source .env.local; set +a
PGPASSWORD=$DATABASE_PASSWORD psql -h $DATABASE_HOST -U $DATABASE_USER -d $DATABASE_NAME -tAc "
SET app.current_tenant_id = '10000000-0000-0000-0000-000000000001';
SELECT count(*), count(DISTINCT tenant_id) FROM billing;"
# expected: one tenant only. As DATABASE_ADMIN_USER you get every tenant's rows,
# because the local superuser has BYPASSRLS.
```

An unscoped connection returning **0 rows is correct** — the policy fails
closed. It is not an empty database.

### Frontend checks

```bash
cd frontend
npm run typecheck   # tsc -b --noEmit
npm run lint        # 0 errors, 6 known warnings
npx vitest run      # 958 passed / 145 files
```

**Use `npm run typecheck`, never a bare `npx tsc --noEmit`.** `frontend/tsconfig.json`
is a solution-style config — `"files": []` plus references to `tsconfig.app.json`
and `tsconfig.node.json` — so plain `tsc` resolves **zero input files**, prints
nothing and exits 0. It looks exactly like a clean typecheck while having checked
nothing at all. Only build mode (`tsc -b`) follows project references, which is
what the npm script and CI (`frontend-ci.yml`) both run.

Two follow-on traps worth knowing:

- `tsc -b` is **incremental**. After fixing an error it may report success from
  cache without re-reading the file. Add `--force` when you need certainty.
- `npm run typecheck | tail` reports **`tail`'s** exit code, not tsc's. Redirect
  to a file and check `$?` directly, or read the output.

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

### `ResourceNotFoundException: User pool ... does not exist`

The root `.env.local`'s `COGNITO_USER_POOL_ID`/`COGNITO_CLIENT_ID` don't match
what Moto currently has — `bootstrap_local.sh` writes both automatically on
every run, but anything that later **overwrites `.env.local` from an older
version** (a `git checkout`, a stash pop, restoring a backup) silently
reverts them back to stale values without touching Moto, which still has
the pool bootstrap actually created. Frontend auth can still work fine (it
reads `frontend/.env.local`'s `VITE_COGNITO_*`, a separate file) while every
*backend* Cognito call — `AdminCreateUser` on invite accept/self-register
being the one this actually breaks — fails.

Confirm the mismatch, then fix and restart:

```bash
aws --endpoint-url http://localhost:5100 --region eu-west-1 cognito-idp list-user-pools --max-results 10
grep COGNITO_USER_POOL_ID .env.local frontend/.env.local
```

If they disagree, either re-run `bash scripts/bootstrap_local.sh` (creates a
fresh pool and rewrites both files) or manually copy the pool/client id Moto
actually has into `.env.local`, then restart the server.

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

### `NoCredentials: Unable to locate credentials` during `make bootstrap`

Fixed — `scripts/bootstrap_local.sh` now exports Moto's dummy credentials
itself (any real `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` already in your
env still wins). If you hit this on an older checkout: `make bootstrap` runs the
script without sourcing `.env.local`, so botocore had no credentials to sign
with. Note the earlier steps misreported this as `Already exists` — they pipe
`2>/dev/null || echo "Already exists"`, which also swallows a `NoCredentials`
failure; the Cognito step was just the first one to surface the real error. On
an old checkout, either pull this fix or run `set -a; source .env.local; set +a`
first (needs AWS vars present in `.env.local`).

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

### A file upload fails in the browser with `net::ERR_FAILED` / a CORS error

The browser blocked the `PUT` to storage before sending it. Check, in order:

```bash
# 1. Does the bucket have a CORS rule? (make bootstrap applies one)
aws --endpoint-url http://localhost:5100 s3api get-bucket-cors --bucket logistics-assets

# 2. Is the presigned URL being rewritten onto the proxy?
#    Expect http://localhost:5173/__storage/... — NOT http://localhost:5100/...
curl -s -X POST http://localhost:3000/v1/packing-lists/import/presigned-url \
     -H "X-Tenant-ID: 10000000-0000-0000-0000-000000000001" \
     -H "X-Role: china_office_staff" -H "Content-Type: application/json" \
     -d '{"content_type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}'
```

If the URL still points at `:5100`, the Flask server predates the rewrite or
`LOCAL_UPLOAD_PROXY_BASE` is empty — restart it. If it points at `/__storage` but
the request 404s, Vite predates the proxy config — restart Vite. See
"File uploads in local dev" above for why this is needed.

Note that `curl` ignores CORS, so an upload succeeding under curl tells you
nothing about whether the browser path works.

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
[ ] pip install uv                            ← once (or the astral install script)
[ ] uv sync --extra azure                     ← creates .venv + installs locked deps (runtime + dev + azure)

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

---

## 14. Frontend dev server

The React SPA lives in `frontend/`. It has two auth modes, controlled by `VITE_ENVIRONMENT` in `frontend/.env.local`:

### 14.1 Dev shim (default — fastest for backend testing)

```
VITE_ENVIRONMENT=local
```

`App.tsx` mounts `LocalAuthProvider`, which skips Cognito for the role-switcher dropdown in the bottom-right — flip between all 6 single-role dev identities **plus one multi-role identity, `nigeria_warehouse`** (`nigeria_office_staff` + `warehouse_attendant`, migration 039 — multi-role staff support), instantly. Auth headers (`X-Tenant-ID`, `X-Role`, `X-Roles`, `X-User-ID`) are set from `tokenStore.ts` and sent on every API request to `local_server.py`; `X-Roles` is only sent when the active dev identity holds more than one role.

**The real `/login` screen also works here, with no env-var switch** — `LocalAuthProvider.login()` calls real Cognito (via Moto, same `VITE_COGNITO_*` vars as §14.2) and overlays that session on top of the role switcher (found and fixed 2026-09-06: it previously threw unconditionally, so no email/password login — including a customer who'd just claimed a real invite link — could ever succeed here; see `04_auth_and_session.md`'s ground-truth gaps). Use this to test the customer-invite claim → login → portal flow end-to-end without leaving the default dev mode. Switch away from the role switcher back to it any time by logging out.

**Seeded tenant UUIDs are deterministic** — `scripts/seed.py` always inserts Acme Shipping Ltd with `id = 10000000-0000-0000-0000-000000000001` and its staff with matching fixed IDs (`0011`–`0014`, plus `0015` for the multi-role user below). `LocalAuthProvider.tsx`'s `DEMO_TENANT_ID` and `local_server.py`'s `DEFAULT_TENANT_ID` are hardcoded to this value — they survive `make stack` resets without needing manual updates.

**Role-switch toggle (multi-role staff, migration 039):** selecting `nigeria_warehouse` in the dev role-switcher logs you in as a dev identity holding both roles. A second, separate control appears in the TopBar user menu (a `<select>` next to the notification bell, only rendered when `session.roles.length > 1`) — this is the *active/display* role toggle a real multi-role user gets, purely client-side (no request, no new token; see `06_routing_rbac_and_navigation.md`). Don't confuse the two: the dev role-switcher picks *which dev user you're logged in as* (changes `X-Role`/`X-Roles` sent to the backend); the TopBar toggle picks *which of that user's roles is active for nav/display* (backend never sees it change).

#### 14.1.1 Volume/UI testing at scale

`scripts/seed.py` only creates 2 containers for Acme — enough for auth testing, not enough to see how list/dashboard views behave under real load. For that, run:

```bash
make seed-stress
# or: python scripts/seed_stress.py
```

This adds ~200 containers across ~50 customers to Acme Shipping Ltd, spanning the full container lifecycle (`loading` → `fully_released`, plus `cancelled`) and every billing status (`unpaid`, `partially_paid`, `paid`, `overpaid`, `waived`, `released_with_outstanding`), weighted toward the mid-pipeline stages for a realistic operational spread. It's additive — run `make seed` (or `make stack`) first — and safe to re-run (no-ops if the marker container `ACME9001` already exists). It also bumps Acme's `subscription_tier` to `enterprise` so the metering container-cap check doesn't block further container creation from the UI afterward. Since the dev role-switcher (§14.1) is hardcoded to Acme, the populated data is visible immediately after refreshing — no extra Cognito setup needed.

#### 14.1.2 Running the Playwright e2e suite (`frontend/e2e/flows/`)

Prerequisites, in order — each one bit a fresh checkout on 2026-09-23:

1. `make up && make bootstrap` (Moto is stateless: without the `logistics-*` queues and the `logistics-events` bus every flow that publishes an event 500s — payment recording, release-note generation, claim filing, PDF export). `bootstrap` also rewrites the Cognito IDs in `.env.local` and `frontend/.env.local`, so **restart both dev servers afterwards**.
2. `make stack` (or `make migrate seed` on an empty DB) **and `make seed-stress`** — the specs assume more than `seed.py`'s curated data: `container-list.spec.ts` expects ≥ 5 containers, the bulk packing-list specs need `draft`/`pending_approval` lists, and `manifest-verify-and-advance.spec.ts` needs a container with an approved packing list (otherwise the advance dialog correctly stays open showing "Container must have at least 1 approved packing list before sealing").
3. API on `:3000` (`make dev`) and Vite on `:5173` (`cd frontend && npm run dev`).
4. From `frontend/`, **source the root env** (the real-login specs shell out to `scripts/mint_test_invite.py`, which needs the DB vars) and **set `PW_E2E=local-stack`** (otherwise `playwright.config.ts` also tries to start `npm run preview` on `:4173` and fails with "Timed out waiting 60000ms from config.webServer"):

```bash
cd frontend
set -a; source ../.env.local; set +a
PW_E2E=local-stack npx playwright test --project=local-stack
```

Known noise: Moto doesn't implement Cognito `RevokeToken`, so the logout specs log `POST / 500` from `localhost:5100` — the auth handler treats revocation as best-effort and the specs still pass. `mint_test_invite.py` intermittently fails under 4-way parallelism (shared DB/Moto setup); re-run `auth-logout.spec.ts` / `customer-invite.spec.ts` with `--workers=1` before treating a failure there as real. Specs mobile-viewport (`responsive_smoke.spec.ts`) navigate with `page.goto()` — `goToViaNav()` clicks the staff sidebar, which is behind the hamburger at ≤ 860px.

### 14.2 Real Cognito-via-Moto login (exercises the actual /login screen)

```
VITE_ENVIRONMENT=staging   # any value ≠ 'local'
VITE_COGNITO_USER_POOL_ID=<copy from backend .env.local COGNITO_USER_POOL_ID>
VITE_COGNITO_CLIENT_ID=<copy from backend .env.local COGNITO_CLIENT_ID>
VITE_COGNITO_ENDPOINT=http://localhost:5100
```

These values regenerate every `make bootstrap` / `make stack` — re-copy them each time.

To create a tenant and admin user for real login:

```bash
# Provision tenant + admin user + cognito group
python scripts/onboard_tenant.py \
  --company-name "Demo Shipping Co" \
  --email "admin@demo.com" \
  --tier starter

# Set a permanent password (the onboarding script prints a temp password;
# the /login screen has no force-change-password UI yet)
aws --endpoint-url=http://localhost:5100 cognito-idp admin-set-user-password \
  --user-pool-id $COGNITO_USER_POOL_ID \
  --username admin@demo.com \
  --password 'DemoPass123!' --permanent
```

After that, `POST /v1/tenant/users` (authenticated as tenant_admin) can add staff with any role. Set permanent passwords for each with the same `admin-set-user-password` command.

**Pre-seeded accounts** — `scripts/bootstrap_local.sh` already creates real Cognito logins for 3 tenants, each with a full staff set + 5 customers, plus one cross-tenant platform admin and one multi-role Acme staff member (29 accounts total). No `onboard_tenant.py` step needed for any of them. Password for every account is `Test1234!` (platform admin excepted — see below). Re-run `bash scripts/bootstrap_local.sh` after any Moto restart to recreate them all (Moto state is wiped every time, same as `make bootstrap` / `make stack`).

Every tenant's staff **and** customers share that tenant's own email domain, so you can log in as any specific tenant, role, or customer and know at a glance which company they belong to:

| Tenant | Domain | tenant_admin | china_office_staff | nigeria_office_staff | warehouse_attendant |
|---|---|---|---|---|---|
| Acme Shipping Ltd | `acmeshipping.com` | admin@ (Chidi Okafor) | china@ (Li Wei) | lagos@ (Emeka Eze) | warehouse@ (Tunde Bello) |
| Global Cargo Co | `globalcargo.com` | admin@ (Aisha Suleiman) | china@ (Zhang Wei) | lagos@ (Ade Bankole) | warehouse@ (Ngozi Kalu) |
| Demo Shipping Ltd | `demoshipping.com` | admin@ (Amara Okafor) | china@ (Kwame Asante) | lagos@ (Fatima Bello) | warehouse@ (Segun Dada) |

**Multi-role staff (migration 039)** — one additional Acme account exercises real
Cognito-login multi-role support (the fixed dev identity `nigeria_warehouse` in §14.1
covers the header-shim path; this covers the real-JWT path): `amaka@acmeshipping.com`
(Amaka Nwachukwu, password `Test1234!`) belongs to **both** the
`{tenant_id}:nigeria_office_staff` and `{tenant_id}:warehouse_attendant` Cognito groups
(`custom:role` = `nigeria_office_staff`, the primary). `scripts/seed.py` inserts the
matching `tenant_user` row (fixed id `...-0015`) plus two `tenant_user_role` rows
(`nigeria_office_staff` primary, `warehouse_attendant` secondary).

5 customers per tenant (all `@`-suffixed with the tenant's domain, all with a linked `customer` row so the portal isn't empty):

| Acme | Global Cargo | Demo Shipping |
|---|---|---|
| ngozi@ (Ngozi Adeyemi) | olumide@ (Olumide Adebayo) | funmi@ (Funmilayo Adeyemi) |
| ibrahim@ (Ibrahim Musa) | chinwe@ (Chinwe Okoro) | emeka@ (Emeka Obi) |
| chioma@ (Chioma Eze) | tunji@ (Tunji Bakare) | amaka@ (Amaka Chukwu) |
| yusuf@ (Yusuf Musa) | grace@ (Grace Eze) | david@ (David Okon) |
| blessing@ (Blessing Nwosu) | halima@ (Halima Yusuf) | zainab@ (Zainab Bello) |

Fixed `tenant_user.id` UUIDs in `scripts/seed.py` match these emails 1:1 with the Cognito accounts (`10000000-…` for Acme, `30000000-…` for Global Cargo, `20000000-…` for Demo Shipping — see the ID scheme comment at the top of `seed.py`), so `local_server.py`'s `_resolve_user_id_by_email()` always resolves a real-Cognito login to the correct seeded DB row, and every `created_by`/`FK` write succeeds.

**Impersonation ("Impersonate" on a platform tenant-detail page)** works in both auth modes — the backend mints a real HS256 token signed with `IMPERSONATION_SECRET` (set in `.env.local`; production uses `IMPERSONATION_SECRET_ARN` → Secrets Manager), and `local_server.py` maps the token's claims the same way the production REQUEST authorizer does. Impersonated sessions are read-only (mutations 422) and expire after 30 minutes.

**Platform admin login** — one cross-tenant account, no tenant scope:

| Email | Password | Cognito group |
|---|---|---|
| `platform-admin@shipx.co` | `Test1234!` | `platform_admin` (no tenant prefix) |

There is deliberately no `tenant_user` row for this account — `tenant_user.tenant_id` is a `NOT NULL` FK to `tenant(id)` and its `role` CHECK constraint doesn't include `platform_admin`, so platform admins exist only as Cognito identities (`custom:tenant_id = "PLATFORM"` + `platform_admin` group), never as DB rows.

**Why `VITE_COGNITO_ENDPOINT` is needed:** `CognitoClient.ts` points `amazon-cognito-identity-js` at Moto instead of real AWS, and switches the auth flow from `USER_SRP_AUTH` (default; Moto doesn't reliably emulate SRP) to `USER_PASSWORD_AUTH` (only when this env var is set — production is unaffected).

**After `make bootstrap` / `make stack`:** re-copy `VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_CLIENT_ID` from the backend `.env.local`, re-run `onboard_tenant.py`, and re-set permanent passwords. Moto state is wiped on every bootstrap.

### 14.3 Start the frontend

```bash
cd frontend
npm install
npm run dev   # → http://localhost:5173
```

The dev server proxies nothing — it calls `http://localhost:3000` (local_server.py) directly via the API client's base URL config.


## 15. Testing the real Microsoft Entra integration locally

**There is no 1:1 Entra emulator.** Microsoft ships none, and the community ones
([entra-emulator](https://github.com/calvinchengx/entra-emulator),
[entra-local](https://github.com/cmaneu/entra-local)) expose only a *minimal, read-only*
Microsoft Graph — so they cannot exercise our Graph **writes** (`POST /users`,
`POST /groups`, `POST /groups/{id}/members/$ref`, `PATCH /users/{id}` passwordProfile,
the `identities` `$filter`), nor the `OnTokenIssuanceStart` custom-claims webhook. Every
Entra bug found so far has been in exactly those places, so an emulator would not have
caught them. They remain useful for minting tokens with arbitrary `tenant_id`/`role`
claims when you only need to exercise the *consumption* side (`buildSession` →
`auth_verify` → `EntraClaimsMapper` → `RoleGuard`).

Instead, point the **local** backend at the **real** CIAM tenant. The Graph provisioning
app uses client-credentials, which work from anywhere — no deploy needed.

> **These are real directory writes against the shared CIAM tenant.** Use a dedicated
> test email per run (`tenant_user.id` IS the Entra `oid`, so one identity can only ever
> belong to one tenant — reusing an email now returns a clean 409) and delete the test
> user + tenant afterwards. Never commit the client secret; `.env.local` is gitignored.

### 15.1 Configure
Uncomment the "Real Microsoft Entra integration" block in `.env.local` (template in
`.env.local.sample`) and paste the `shipx-graph-provisioner` client secret into
`ENTRA_GRAPH_CLIENT_SECRET`. Then restart `scripts/local_server.py`.

> Flask does **not** autoreload env changes — restart the server or you will keep
> testing the old config (this has bitten us before; see §12).

### 15.2 What works immediately — Graph provisioning
With the block enabled, provisioning against the local API performs **real** Graph writes
while persisting to your **local** Postgres:

```bash
curl -X POST http://localhost:3000/v1/platform/tenants \
  -H "X-Tenant-ID: PLATFORM" -H "X-Role: platform_admin" \
  -H "Content-Type: application/json" \
  -d '{"company_name":"Local Test Co","primary_contact_email":"ops@local.test",
       "subscription_tier":"business",
       "initial_admin":{"email":"local-test-1@yourdomain.com","full_name":"Local Admin"}}'
```
This is the fastest way to validate the whole provisioning chain (create user → group
reconcile → `tenant_user` insert → activation link) in seconds. Check the Entra user in
the portal, or via Graph:
```bash
TOKEN=$(az account get-access-token --tenant $ENTRA_GRAPH_TENANT_ID --resource-type ms-graph --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://graph.microsoft.com/v1.0/users?\$filter=identities/any(c:c/issuerAssignedId eq 'local-test-1@yourdomain.com')&\$select=id,displayName"
```
(No `ConsistencyLevel` header — see the `ObjectIdentity` note in `07_api_tenant_management.md`.)

### 15.3 Browser login from localhost
Register `http://localhost:5173/auth/callback` as an additional redirect URI on the
`shipx-spa` app (the **publicClient** platform permits `http://localhost`), then set
`ENTRA_REDIRECT_URI=http://localhost:5173/auth/callback` locally. Real interactive login
then runs end-to-end from localhost. Build the SPA with `VITE_AUTH_PROVIDER=entra` (not
`VITE_ENVIRONMENT=local`, which activates the dev shim instead).

### 15.4 The claims extension — no longer a gap
Entra calls the custom-claims provider at a **public HTTPS URL**, so it can never reach
`localhost`. That used to break local login. It no longer does.

On an Entra External ID (CIAM) tenant the claims provider's output is **discarded by Entra
anyway** (see `docs/runbook.md` → "On CIAM the claims provider's output never reaches the
token"), so `shared/auth.py::resolve_identity_from_db` resolves `tenant_id` + `role` from
`tenant_user` by the token's `oid`. Locally that reads **your local database**, which is
exactly what you want.

So local login works provided the local DB has a matching row:

```sql
-- tenant_user.id IS the Entra oid, and status must be 'active'.
SELECT id, tenant_id, role, status FROM tenant_user WHERE id = '<oid>';
```

If sign-in fails with `JWT is missing required claims`, that row is missing or inactive —
not a tunnelling problem. Tunnelling the claims app (`docker-entrypoint.sh claims`, port
8080) is now only useful if you are specifically working **on the claims provider itself**;
if you do, remember to point `targetUrl` back, since the extension is shared with the
deployed environment.

### 15.4b One-time tenant setup

Everything the *app* needs is in Terraform (the `entra_*` tfvars). Everything inside the
Entra tenant is in two idempotent scripts — never portal clicks, so staging and prod get
the same state:

```bash
az login --tenant <CIAM tenant id> --allow-no-subscriptions

# Graph provisioning app + the 3 app permissions + consent + disable self-signup
ENTRA_TENANT_ID=<CIAM tenant id> ./scripts/setup_entra_auth.sh
#   DRY_RUN=1     report intended changes only
#   SKIP_SECRET=1 reconcile permissions without rotating the client secret

# Redirect URI (publicClient!) + claims provider; prints the issuer/JWKS to use
./scripts/setup_entra_claims_provider.sh

# platform_admin group
./scripts/setup_entra_platform_admin.sh
```

`setup_entra_auth.sh` aborts unless the logged-in tenant matches `ENTRA_TENANT_ID` — ShipX
spans two tenants (the subscription's workforce tenant and the CIAM tenant), and
configuring the wrong one is not obviously recoverable.

### 15.5 Cleanup
```bash
# Delete the test Entra user (oid from 15.2), then the local tenant rows.
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "https://graph.microsoft.com/v1.0/users/<oid>"
```

---

## Customer self-registration in local dev

`POST /v1/register` resolves the tenant from the **Host header** (custom domain, then subdomain slug). On `localhost:5173` neither resolves, so registration 404s locally unless you map a host alias to a seeded tenant slug (e.g. add `127.0.0.1 acme-shipping.localhost` to `/etc/hosts` and browse via that host) or test via Postman with an explicit `Host: acme-shipping.example.com` header matching the seeded tenant's slug.

(Previously this route also 404'd everywhere, including here, because it was missing from `scripts/local_server.py`'s route table — fixed 2026-07-11; see below.)

## Session persistence (page-reload-doesn't-log-you-out) in local dev

`services/auth/handler.py`'s httpOnly-cookie refresh flow (`POST /v1/auth/session` / `/refresh` / `/logout`, see [docs/project docs/frontend/04_auth_and_session.md](docs/project%20docs/frontend/04_auth_and_session.md)) is exercised by any real Cognito login, in either auth mode: the real-Cognito-only path (`SessionProvider`, `VITE_ENVIRONMENT != local`), and — since the 2026-09-06 fix above — a real login through `LocalAuthProvider` (`VITE_ENVIRONMENT=local`) too, which now overlays a real `cognitoSession` and runs the identical `establishServerSession`/`silentRefresh` calls. The dev-identity role switcher itself still bypasses all of this and hardcodes `status: 'authenticated'` with no persistence step, same as before.

To test the cookie flow itself locally, either log in with real credentials on the default `/login` screen (§14.1) or follow "Real Cognito-via-Moto Login" in `04_auth_and_session.md` (`VITE_ENVIRONMENT=staging` + Moto-backed Cognito), then:
- `scripts/local_server.py` now routes `/v1/auth/*` to `services/auth/handler.py` (added alongside the `/v1/register` fix above) and translates Flask's request cookies into the `event["cookies"]` array the handler reads, and the handler's `cookies` response field into real `Set-Cookie` headers — the same payload-format-2.0 shape API Gateway v2 uses in production.
- Reloading `http://localhost:5173` after logging in should silently restore the session rather than bouncing to `/login`; DevTools → Application → Cookies should show `shipx_rt` scoped to `localhost:3000` with the `HttpOnly` flag set (`Secure` will still be set even over local `http://` — browsers accept `Secure` cookies on `localhost` as a documented exception, so this doesn't need disabling for local testing).

## Online payments (Paystack) in local dev

**Multi-tenant (2026-07-19):** there is no `PAYSTACK_SECRET_KEY` env var anymore — each tenant connects their own key through the app itself, same as a real tenant admin would. One-time setup per tenant you want to test payments against:

```bash
# As that tenant's admin (role-switcher or real login) — or via curl:
curl -X PUT http://localhost:3000/v1/tenant/config/paystack \
  -H "X-Tenant-ID: <tenant_id>" -H "X-Role: tenant_admin" -H "X-User-ID: <admin_user_id>" \
  -H "Content-Type: application/json" \
  -d '{"secret_key":"sk_test_…"}'
```

Or from the UI: sign in as that tenant's admin → **Admin → Config → Payments** → paste the key → **Connect Paystack**. Use **Test connection** to confirm Paystack actually accepts it (a real, harmless `GET /transaction` call — not just a shape check) before trying a real checkout.

Once configured, that tenant's customer portal "Pay online" button (`/my-billing/{id}`) creates a real Paystack **test-mode** checkout and redirects to it. Pay with Paystack's standard test card `4084 0840 8408 4081` (any future expiry, CVV `408`, PIN `0000`, OTP `123456`). A tenant with nothing configured gets a clear `PAYMENT_GATEWAY_NOT_CONFIGURED` error instead — bank transfer stays available either way.

**Webhook (payment confirmation):** Paystack can't reach `localhost`, so either simulate the callback (POST to `/v1/webhooks/payment` with `X-Paystack-Signature` = HMAC-SHA512 of the raw body using **that tenant's own** secret key — see the Postman request) or tunnel (e.g. `ngrok http 3000`) and set the tunnel URL + `/v1/webhooks/payment` as the webhook URL in the Paystack test dashboard. The webhook is the source of truth — the browser redirect to payment-success never records money. The handler resolves which tenant a webhook belongs to (via the billing reference) *before* checking the signature, then verifies against that specific tenant's key — see `07_api_tenant_management.md`'s "Multi-Tenant Paystack" design note if you're testing more than one tenant's payments side by side.
