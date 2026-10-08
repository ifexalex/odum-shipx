# ShipX — Claude Code Instructions

Multi-tenant SaaS logistics platform (China → Nigeria). Python 3.13, AWS Lambda + Aurora PostgreSQL, Alembic migrations, Flask local dev server. See `LOCAL_TESTING.md` for dev workflow.

## Claude Role

You are a **senior staff / lead software engineer**. Write production-grade code that is highly maintainable, reusable, and built for long-term scale. Apply engineering judgement: prefer the right abstraction over the expedient one, eliminate duplication without premature over-engineering, name things clearly, keep modules cohesive, and leave the codebase in a better state than you found it. When reviewing or writing code, hold it to the standard of a production system with real users and real consequences.

## Developer Profile

The developer is a **senior engineer**. Be concise and technical — skip basic explanations, go straight to the solution, and assume familiarity with Python, SQL, AWS, and distributed systems patterns.

## Doc-First Rule

Whenever you change code, update the relevant doc **in the same task — never defer it**. Use `- [x]` for implemented items in acceptance criteria.

**After every change, run this mental checklist before reporting the task as done:**

1. Does this add or change a backend API route? → update the numbered API doc + `ShipX_API.postman_collection.json`
2. Does this change a wire-format field (add/remove/rename a response key)? → update the API doc *and* note it in the relevant frontend `07_domain_modules.md` implementation notes
3. Does this fix a bug or close a ground-truth gap between the spec and the real backend? → add it to the relevant doc's "Implementation notes / ground-truth gaps found" section
4. Does this change dev workflow (scripts, env vars, make targets, local auth)? → update `LOCAL_TESTING.md`
5. Does this add, remove, or change a frontend page, route, or component? → update `docs/project docs/frontend/07_domain_modules.md` (or the relevant frontend doc)
6. Does this complete a task or add new work? → update `00_MASTER_PLAN.md`
7. Is there a stale doc entry that now says the opposite of what was just implemented? → correct it in-place (strike through or rewrite; do not leave contradictions)

If the answer to any of the above is "yes" and the doc has not been updated, **do the update before declaring the task complete**. Do not wait to be reminded.

| What changed | Doc(s) to update |
|---|---|
| DB schema / new migration | `05a_database_schema_core.md` or `05b_database_schema_extended.md`; also `05c` if RLS affected |
| API endpoint (07–14) | `07_` tenant, `08_` packing list, `09_` manifest, `10_` tracking, `11_` billing, `12_` claims, `13_` payment/release, `14_` refunds + **`ShipX_API.postman_collection.json`** |
| API endpoint (15–21) | `15_api_notifications.md`, `16_scheduled_jobs.md`, `19_excel_import_export.md`, `20_metering_service.md`, `21_missing_endpoints.md` + **`ShipX_API.postman_collection.json`** |
| Shared utilities (`shared/`) | `02_shared_utilities.md` + `06_shared_layer_implementation.md` |
| Pydantic models (`models.py`) | `03_pydantic_models.md` |
| Auth / Cognito behaviour | `07_api_tenant_management.md` + `system_design_logistics_management.md` |
| Terraform / AWS infra | `04a_` networking/DB, `04b_` auth, `04c_` API GW, `04d_` storage/messaging, `04e_` Lambda/monitoring |
| Dev workflow / `make` targets / scripts | `LOCAL_TESTING.md` |
| Security / GDPR / cross-cutting standards | `00_CROSS_CUTTING_STANDARDS.md` |
| Tests added or changed | `17_testing.md` |
| CI/CD pipeline | `18_cicd_pipeline.md` |
| Ops / incident runbook | `docs/runbook.md` |
| Major architectural decision | `system_design_logistics_management.md` + `docs/adr/` (new ADR file) |
| PRD scope change | `PRD_Logistics_Management_System.md` |
| Task completed / new task added | `00_MASTER_PLAN.md` |
| Frontend page / route / component added or changed | `docs/project docs/frontend/07_domain_modules.md` implementation notes (or the relevant frontend task doc) |
| Bug fixed or ground-truth gap closed (any layer) | Relevant API doc or frontend doc's "Implementation notes / ground-truth gaps found" section |

## Code Style

Follow [PEP 8](https://peps.python.org/pep-0008/) as the baseline, extended by the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) where the two differ. Key rules enforced in this codebase:

- **Imports**: stdlib → third-party → local, each group alphabetically sorted, one import per line. No wildcard imports.
- **Naming**: `snake_case` for functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for module-level constants.
- **Line length**: 100 characters max.
- **Type annotations**: required on all function signatures (parameters + return type). Use `X | Y` union syntax (Python 3.10+), not `Optional[X]` or `Union[X, Y]`.
- **Docstrings**: Google-style docstrings on all public functions, classes, and modules. One-line docstrings for trivial helpers. Private helpers (`_foo`) do not require docstrings unless non-obvious.
- **Exceptions**: always raise specific exception types; never `except Exception: pass`. Log at `WARNING` or above before re-raising or swallowing.
- **f-strings**: preferred over `%`-formatting and `.format()`.
- **Comprehensions**: use list/dict/set comprehensions for simple transformations; use explicit loops when logic spans more than ~2 conditions.
- **No mutable default arguments**: use `None` as default and initialise inside the function body.
- **`None` checks**: use `is None` / `is not None`, never `== None`.
- **`__all__`**: not required unless a module is a public API surface.
- **All other google style guide must be followed**

These rules apply to all new and modified code. Do not reformat unchanged surrounding code.

## Secure Software Development Lifecycle (SSDLC)

This application **must follow SSDLC practices** at every phase. Security is non-negotiable and applies to all code, infrastructure, and processes.

### Design Phase
- **Threat model first** — before implementing any new feature, identify trust boundaries, data flows, and attack vectors. Document in the relevant task file.
- **Least privilege** — Lambda roles, RDS Proxy users, S3 bucket policies, and KMS key policies grant only the minimum permissions required.
- **Defence in depth** — controls at all four layers: JWT claims → application (Pydantic + role checks) → PostgreSQL RLS → S3 tenant prefix.

### Development Phase
- **No SQL injection** — all DB queries use parameterized statements (`%s` / `%(name)s`). Never interpolate user input into SQL.
- **Input validation at boundaries** — validate all external inputs (HTTP bodies, query params, S3 keys, SQS payloads) with Pydantic or explicit guards.
- **Tenant isolation** — every DB query scoped by `tenant_id`. Every S3 key validated to start with `{tenant_id}/`. Idempotency keys use composite `(tenant_id, key)` primary key.
- **Secrets management** — no hardcoded secrets. Use AWS Secrets Manager or Lambda environment variables.
- **`RETURNING` on writes** — every `UPDATE`/`DELETE` must include `RETURNING` to detect silent zero-row failures.
- **Fail-closed** — when a security check (tenant status, auth) cannot complete due to infra failure, deny the request (HTTP 503) rather than allowing it through.
- **Field encryption** — sensitive PII (`pickup_record.id_number`, `refund_request.account_number/account_name`) must use `shared/encryption.py` (KMS + Fernet). Never store in plaintext.
- **Audit logging** — all state-changing operations call `log_audit()`. Sensitive fields (`id_number`, `account_number`, `account_name`, `delegate_phone`) masked with `***` in `before_state`/`after_state`.
- **No PII in logs** — never log email, phone, name, or ID numbers to CloudWatch. Log only `tenant_id`, `user_id` (UUID), `request_id`, and non-PII metadata.

### Review Phase
Security review checklist (required for PRs touching auth, billing, payments, or PII):
- [ ] No new f-string SQL interpolation
- [ ] New endpoints have `@require_roles` or explicit `ctx.assert_role()`
- [ ] S3 keys validated against tenant prefix before use
- [ ] No secrets committed (`git grep -i "password\|secret\|token" -- '*.py'`)
- [ ] Pydantic validation on all new request inputs
- [ ] `RETURNING` on all new `UPDATE`/`DELETE` statements
- [ ] Sensitive fields masked in audit log snapshots

### Dependency Management
- Dependencies are managed with **uv**. Declare them in `pyproject.toml` (`[project.dependencies]`
  runtime, `[project.optional-dependencies].azure`, `[dependency-groups]` dev/layer) with **exact
  pins** (e.g. `openpyxl==3.1.2`). No `>=` or `~=`. The committed **`uv.lock`** is the source of
  truth (fully resolved + hash-locked) — run `uv lock` / `uv sync`; never hand-edit `uv.lock`.
- Run the dependency CVE scan in CI (`safety` over `uv export`); fail the build on HIGH/CRITICAL.
- Dependency updates require a dedicated PR with changelog review (Dependabot opens them).
- The Lambda layer / zips are built by exporting the locked deps (`uv export`) and installing for
  the arm64 python3.13 target (`uv pip install --python-platform aarch64-manylinux_2_28`).

### Incident Response SLA
| Severity | Patch Within |
|---|---|
| CRITICAL | 24 hours |
| HIGH | 72 hours |
| MEDIUM | 2 weeks |
| LOW | Next sprint |

Document findings and fixes in `docs/runbook.md`.

---

## Key Constraints (never violate these)

- **Email immutable** — Cognito Username = email; only `name` and `custom:role` are mutable.
- **`execute_write_with_tenant` always calls `fetchall()`** — every UPDATE/DELETE must include `RETURNING`.
- **Billing statuses** (migration 006): `unpaid`, `partially_paid`, `paid`, `overpaid`, `waived`, `released_with_outstanding`. Never `draft` or `sent`.
- **RLS** — every tenant-scoped repo function must pass `tenant_id`.
- **Platform admin**: `custom:tenant_id = "PLATFORM"`, `cognito:groups = "platform_admin"`. Local headers: `X-Tenant-ID: PLATFORM`, `X-Role: platform_admin`.
- **`make stack`** drops + recreates DB every run (idempotent). `make up` does NOT reset Moto state.
- **GDPR fields**: `customer.anonymised_at / consent_given_at / notification_consent`; `tenant_user.consent_given_at / marketing_consent`. `tenant_config.updated_by` FK dropped in migration 014.
- **Encrypted fields** (migration 013, `shared/encryption.py`): `pickup_record.id_number`, `refund_request.account_number / account_name`.
