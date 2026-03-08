# ADR-001: Serverless Lambda over ECS/Fargate

**Status:** Accepted

**Decision:** Use AWS Lambda for all compute instead of ECS/Fargate.

**Rationale:** Zero idle cost, auto-scaling, native event-driven integration with EventBridge and SQS.

**Tradeoff:** Cold starts mitigated by provisioned concurrency on critical paths (tenant management, billing).
