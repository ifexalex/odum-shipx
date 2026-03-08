# ADR-002: Shared Database with RLS over DB-per-Tenant

**Status:** Accepted

**Decision:** Use a single Aurora cluster with PostgreSQL Row-Level Security (RLS) for tenant isolation.

**Rationale:** 60–80% cheaper than DB-per-tenant, simpler operations, sufficient isolation for SMB target market.

**Tradeoff:** Noisy-neighbor risk mitigated by per-tenant connection limits at RDS Proxy.
