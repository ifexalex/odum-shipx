# ADR-005: Compute portability — Lambda on AWS, Container Apps on Azure

**Status:** Accepted (2026-10-09). Phase 1 (containerization) implemented.
**Related:** [ADR-001](001-serverless-over-ecs.md) (serverless over ECS — AWS),
[ADR-004](004-cognito-to-entra-portability.md) (Cognito→Entra), the
`shared/providers/` ports (see `02_shared_utilities.md`).

## Context

ShipX must deploy to **either** AWS or Azure, selected by the `DEPLOY_CLOUD` CI
variable (which pipeline deploys) and `CLOUD_PROVIDER` at runtime (which adapter
set the app uses). Every cloud touchpoint except compute and auth already sits
behind a port/adapter. Compute was the gap: on AWS the backend is 19 Lambda
functions behind API Gateway + SQS/EventBridge event sources (ADR-001). Azure
has no Lambda, and the Azure Terraform root declared no compute at all.

Two options for making compute portable:

1. **Converge both clouds on one container** (Fargate/Lambda-Web-Adapter on AWS,
   Container Apps on Azure). Maximum symmetry, but re-architects the **live,
   revenue-earning** AWS compute — new scaling/billing profile, API Gateway → container
   rework, and a migration of a working production system.
2. **Keep AWS on Lambda unchanged; containerize for Azure Container Apps.** The
   business logic is shared verbatim (`shared/`, `services/`); only the thin
   per-cloud *edge* (packaging, request ingress, trigger glue, deploy pipeline)
   differs.

## Decision

**Option 2.** AWS keeps the Lambda zip path (ADR-001 stands); Azure runs the same
code as a container on Azure Container Apps. The shared core is identical; the
edge is per-cloud and small:

| Concern | AWS edge (unchanged) | Azure edge (new) |
|---|---|---|
| HTTP API | API Gateway → 19 Lambda | Container App `api` (gunicorn) ← HTTPS ingress |
| AuthZ | REQUEST authorizer Lambda | in-process middleware — **same verify code** |
| Async | SQS → consumer Lambda | Container App `worker` ← Service Bus (KEDA) |
| Cron | EventBridge → 7 Lambda | Container App Jobs (cron) |

### Why this is low-risk

The container entry point already existed in spirit: `scripts/local_server.py`
translates HTTP → the API-Gateway-v2 event the handlers expect. Phase 1 promoted
that routing into `shared/http_routing.py` (now the single source for the dev
server, the container, and — by mirroring — API Gateway) and added a production
HTTP app (`services/http_app/app.py`) that differs from the dev server in exactly
one way: it verifies a real bearer token instead of trusting an `X-Role` header.

Token verification was extracted from the Lambda authorizer into
`shared/auth_verify.py`, so the **identical** logic backs both the AWS authorizer
Lambda and the container's in-process middleware — no second auth implementation
to drift. The AWS authorizer is now a thin adapter over it; its behavior is
unchanged.

The async + cron handlers are invoked with the same SQS-shaped event on both
clouds (`services/queue_worker/worker.py`, `services/scheduled/run.py`), so the
handler bodies are byte-identical across clouds.

## Consequences

**Positive**
- AWS production is untouched — zero risk to the live system; all Azure work is additive.
- One codebase, two thin edges; the `DEPLOY_CLOUD`/`CLOUD_PROVIDER` switches already route correctly.
- The container (`Dockerfile`, one image, workload chosen by entrypoint arg) runs api/worker/job/migrate.

**Negative / trade-offs**
- Two packaging + deploy paths to maintain (Lambda zip on AWS, container on Azure). Bounded: the divergence is edge-only.
- Container Apps is always-on per min-replica (no Lambda scale-to-zero); sized small, acceptable for the Azure target. Cost compared in `docs/azure_cost_model.md`.
- gunicorn runs **processes, 1 thread each** — `shared/db.py` holds a per-process, non-thread-safe connection singleton (the same reason the dev server is `threaded=False`). Each worker process is its own connection, mirroring a Lambda execution environment.

## Alternatives considered

- **Option 1 (converge on containers everywhere):** rejected for now — it migrates a
  working production system for symmetry we don't need. Can be revisited later by
  running the *same image* on AWS via the Lambda Web Adapter or Fargate; nothing
  here precludes it.
- **Azure Functions instead of Container Apps:** Functions' Python model would
  reintroduce a per-trigger handler shape and a second web framework; Container
  Apps runs the gunicorn image as-is and gives HTTP/Service-Bus/cron from one
  artifact.
