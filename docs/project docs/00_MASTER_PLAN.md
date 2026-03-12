# Master Build Plan — Logistics & Cargo Management System

## Overview

This document is the **roadmap** for building the full backend of a multi-tenant SaaS Logistics & Cargo Management System on AWS serverless infrastructure. The work has been broken into independently executable task files, each small enough for an AI to process within context limits.

**Tech Stack:** Python 3.12 · AWS Lambda (ARM64/Graviton2) · API Gateway (HTTP API) · Aurora Serverless v2 (PostgreSQL 15.4) · Cognito · S3 · SQS · EventBridge · Terraform · GitHub Actions

**Architecture:** Serverless-first, multi-tenant with shared-database row-level isolation, event-driven async notifications.

> **IMPORTANT:** Before implementing ANY task, read `00_CROSS_CUTTING_STANDARDS.md`. It contains mandatory conventions (idempotency, structured logging, correlation IDs, security headers, Terraform standards, etc.) that apply to every task.

---

## Architecture Decision Records (ADRs)

| ADR | Decision | Rationale | Tradeoff |
|---|---|---|---|
| ADR-001 | Serverless Lambda over ECS/Fargate | Zero idle cost, auto-scaling, event-driven fit | Cold starts (mitigated by provisioned concurrency on critical paths) |
| ADR-002 | Shared DB with RLS over DB-per-tenant | 60-80% cheaper, simpler ops, sufficient isolation for SMB target | Noisy-neighbor risk (mitigated by per-tenant connection limits at RDS Proxy) |
| ADR-003 | Cognito over custom auth | Managed service, free tier 50K MAU, JWT integration with API Gateway | Limited customization, vendor lock-in |
| ADR-004 | EventBridge + SQS over direct invocation | Decoupled services, built-in retry, DLQ for poison messages | Eventual consistency for notifications (~1-5s delay) |
| ADR-005 | Cursor-based over offset pagination | Stable pagination under concurrent writes, no performance cliff at high offsets | Slightly more complex client implementation |
| ADR-006 | Python over Node.js/Go | Team expertise, Pydantic validation, psycopg2 maturity | Slower cold starts vs Go (acceptable with provisioned concurrency) |
| ADR-007 | Aurora Serverless v2 over standard RDS | Auto-scaling ACUs, auto-pause in dev, pay-per-use | ~15% premium over provisioned RDS at steady-state |
| ADR-008 | ARM64/Graviton2 Lambda | 20% cost reduction, better performance | All dependencies must support ARM (psycopg2-binary does) |

---

## Task Dependency Graph

```
Phase 1 — Foundation (sequential)
  00_CROSS_CUTTING_STANDARDS (read first)
  01 → 02 → 03

Phase 2 — Infrastructure (parallelizable after Phase 1)
  04a, 04b, 04c, 04d → 04e
  (apply 04c_PATCH after 04c + when Tasks 19/21 scope is clear)

Phase 3 — Database (after 04a Aurora module)
  05a → 05b → 05c

Phase 4 — Shared Application Layer (after Phase 1 + Phase 3)
  06

Phase 5 — API Services (after Phase 3 + 06, parallelizable)
  07, 08, 09, 10, 11, 12, 13, 14, 15

Phase 6 — Gap Closures (after Phase 5, parallelizable)
  19 (Excel import/export — after 08, 09, 11)
  20 (Metering service — after 06, 04d)
  21 (Missing endpoints — after 07, 10, 11, 12, 15)

Phase 7 — Scheduled Jobs & Events (after Phase 5+6)
  16

Phase 8 — Testing (after all services)
  17

Phase 9 — CI/CD (after everything)
  18
```

---

## Task File Index

| # | File | Title | Depends On | Est. Complexity |
|---|---|---|---|---|
| — | `00_CROSS_CUTTING_STANDARDS.md` | **Mandatory standards for ALL tasks** | None | Read first |
| 01 | `01_project_setup.md` | Project Setup & Repository Structure | Standards | Low |
| 02 | `02_shared_utilities.md` | Shared Lambda Layer Interfaces | 01 | Medium |
| 03 | `03_pydantic_models.md` | Pydantic Models & Validation (All Entities) | 01 | Medium |
| 04a | `04a_terraform_networking_database.md` | Terraform: VPC, Aurora Serverless v2, RDS Proxy | 01 | Medium |
| 04b | `04b_terraform_auth.md` | Terraform: Cognito User Pool & Groups | 01 | Medium |
| 04c | `04c_terraform_api_gateway.md` | Terraform: API Gateway, Routes, Authorizer | 01 | Medium |
| 04c-P | `04c_PATCH_additional_routes.md` | PATCH: 22 additional API routes + Excel Lambda | 04c, 19, 21 | Low |
| 04d | `04d_terraform_storage_messaging.md` | Terraform: S3, SQS, EventBridge, SES | 01 | Medium |
| 04e | `04e_terraform_lambda_monitoring.md` | Terraform: Lambda Functions, CloudWatch, Alarms | 04a–04d | Medium |
| 05a | `05a_database_schema_core.md` | Database DDL: Core Tables | 04a | Medium |
| 05b | `05b_database_schema_extended.md` | Database DDL: Extended Tables + Audit | 05a | Medium |
| 05c | `05c_database_rls_indexes_seed.md` | Database: RLS Policies, Indexes, Seed Data | 05b | Medium |
| 06 | `06_shared_layer_implementation.md` | Shared Layer Full Implementation | 02, 03, 04a | High |
| 07 | `07_api_tenant_management.md` | API: Tenant Management + User Provisioning | 06 | High |
| 08 | `08_api_packing_list.md` | API: Packing List CRUD + Approval Workflow | 06 | High |
| 09 | `09_api_manifest.md` | API: Manifest Generation + Verification | 06, 08 | Medium |
| 10 | `10_api_tracking.md` | API: Shipment Tracking + Stage Transitions | 06 | Medium |
| 11 | `11_api_billing.md` | API: Billing Calculation + CBM Disputes | 06 | High |
| 12 | `12_api_claims.md` | API: Damage Claims + Resolution Workflow | 06 | High |
| 13 | `13_api_payment_release.md` | API: Payment Confirmation + Release Notes + Pickup | 06, 11 | High |
| 14 | `14_api_refunds.md` | API: Refund Requests + Approval Workflow | 06, 11, 12 | High |
| 15 | `15_api_notifications.md` | API: Notification Service (SMS, WhatsApp, Email) | 06 | Medium |
| 16 | `16_scheduled_jobs.md` | Scheduled Jobs: Storage Fees, Escalation, Cleanup | 06, 11 | Medium |
| 17 | `17_testing.md` | Testing: Unit, Integration, Tenant Isolation, Load | All services | High |
| 18 ✅ | `18_cicd_pipeline.md` | CI/CD: GitHub Actions + Rollback + Security Scanning | All | Medium |
| 19 | `19_excel_import_export.md` | Excel Import/Export (4 formats) | 08, 09, 11 | High |
| 20 | `20_metering_service.md` | Metering SQS Consumer + Tier Limits | 06, 04d | Medium |
| 21 | `21_missing_endpoints.md` | Gap Closures: Carryovers, Misc Charges, Public Tracking, etc. | 07, 10, 11, 12, 15 | High |

---

## How to Use These Task Files

1. **Read `00_CROSS_CUTTING_STANDARDS.md` first** — it contains mandatory conventions for ALL tasks
2. **Read the task file** — each contains all context needed (architecture excerpt, DDL, API contracts, business rules)
3. **Check dependencies** — ensure prerequisite tasks are completed
4. **Build the deliverables** — each file specifies exact files to create with paths
5. **Reference constants** — shared types, error codes, and patterns are in tasks 02, 03, and 06
6. **Follow conventions** — all services follow the same handler → service → repository pattern
7. **Validate** — each task has specific acceptance criteria; check all boxes before moving on

---

## Key Architecture Decisions (Context for All Tasks)

- **Multi-tenancy:** Shared database with `tenant_id` row-level isolation on every table
- **Auth:** Single Cognito User Pool; `custom:tenant_id` in JWT; Platform Admin has `tenant_id = PLATFORM`
- **4-Layer Isolation:** JWT claims → Application layer → PostgreSQL RLS → S3 prefix
- **Async:** EventBridge for domain events → SQS queues → Lambda consumers (notifications)
- **API Style:** REST, JSON, RFC 7807 errors, cursor-based pagination, `Idempotency-Key` for POST
- **IaC:** Terraform with modules per AWS service, S3 + DynamoDB remote state locking
- **Observability:** Structured JSON logging, X-Ray tracing, CloudWatch Embedded Metrics
- **Compute:** ARM64/Graviton2 Lambda for 20% cost reduction
- **Region:** eu-west-1 (Ireland), DR backup to eu-central-1 (Frankfurt)
