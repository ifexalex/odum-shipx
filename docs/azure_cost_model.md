# ShipX — Azure Cost Model (Founders Hub)

**Purpose:** projected Azure spend for the ShipX multi-tenant logistics SaaS, to size usage against Microsoft for Startups **Founders Hub** credits.

**Assumptions:** North/West Europe region, single production environment, pay-as-you-go **list** prices (~2026; estimates, not a quote). Baseline load = **3 tenants × 100 MAU = 300 MAU**, ~1–3M API requests/month (back-office logistics usage).

---

## Monthly cost — baseline (300 MAU)

Each line maps the equivalent AWS service (the app's current cloud) to its Azure counterpart.

| Component | AWS today | Azure equivalent | Azure ~$/mo |
|---|---|---|---:|
| Backend compute | Lambda | **Container Apps** (as built — ADR-005; one image, api + workers + jobs) | 5–30 |
| API routing | API Gateway (HTTP) | Container Apps external ingress (not APIM) | ~0 |
| Database | Aurora Serverless v2 | PostgreSQL Flexible Server (Burstable B2s + 32 GB) | 25–40 |
| Cache | ElastiCache Redis | Azure Cache for Redis (Basic C0) | ~16 |
| Auth / identity | Cognito | Entra External ID — **free ≤ 50k MAU** | **0** |
| Auth claims extension | (n/a — Cognito carries claims) | Entra claims provider — a small **always-on Container App** (0.25 vCPU, min 1) on the shared image; CIAM can't emit the claims any other way, and it must stay warm (extension call times out ~2s). Not an Azure Function: App Service quota is 0 on this sub | ~10–14 |
| Object storage | S3 | Blob Storage | 1–5 |
| Frontend / CDN | CloudFront | Static Web Apps (free tier) **or** Front Door Standard | 0–35 |
| Private networking | 7× VPC interface endpoints (~$112) | VNet integration + private DNS (Postgres) — **~free** (DNS zone pennies) | **0–1** |
| Queues | SQS | **Service Bus** (as built — Standard, ~$10 base + usage) | 10–15 |
| Scheduler / events | EventBridge | Timer Functions / Event Grid | 0–2 |
| Email | SES | Communication Services Email / SendGrid | 1–5 |
| Secrets + crypto | Secrets Manager + KMS | Key Vault | 2–5 |
| Monitoring | CloudWatch | Azure Monitor + Log Analytics | 5–20 |
| DDoS (L3/L4) | Shield Standard (free) | DDoS Basic (**free / automatic**) | 0 |
| **Subtotal (no L7 WAF)** | | | **≈ $73–188** |
| L7 WAF + DDoS **(recommended)** | CloudFront WAF (~$10) | **Cloudflare (Free → Pro)** — cloud-neutral edge in front of the app | **0–25** |
| L7 WAF (Azure-native alt) | — | Front Door Premium (WAF requires Premium) | ~330 |
| **Total (with Cloudflare WAF)** | | | **≈ $98–213** |

### Why Azure is cheaper at the base
- **VNet Service Endpoints are free** — erases the ~$112/mo that AWS interface endpoints cost (the single biggest AWS fixed cost).
- **Static Web Apps free tier** for the SPA; **Entra External ID free ≤ 50k MAU**.
- Burstable Postgres + Basic Redis are cheaper than Aurora Serverless v2 + ElastiCache.

### WAF / DDoS — use a cloud-neutral edge, not Front Door Premium
- Azure-native L7 WAF is expensive — it requires **Front Door Premium (~$330/mo)** (AWS gives the same on CloudFront for ~$10). **AWS WAF cannot be attached to Azure resources.**
- **Recommended:** front the app with **Cloudflare** (Free → **Pro ~$25/mo**) — a provider-independent edge that gives managed-rule **WAF + unmetered DDoS + CDN** in front of an Azure *or* AWS origin. ~13× cheaper than Front Door Premium, and it's the one layer that **doesn't change when you switch clouds** (a portability win).
- **DDoS L3/L4** is free on both Azure (DDoS Basic) and Cloudflare, so network-layer DDoS is covered at $0 regardless.
- Reserve Front Door Premium only if a customer/compliance requirement specifically mandates Azure-native WAF (and under credits the $330 is absorbed anyway).

---

## Growth projection (Azure, pay-as-you-go)

Cost is dominated by a fixed infra floor, so it scales **sub-linearly** with users.

| Scale | Compute | Postgres | Cache | Requests/other | **~$/mo (no WAF)** | **+ Cloudflare WAF** |
|---|---:|---:|---:|---:|---:|---:|
| 300 MAU (3 tenants) | 5–30 | 25–40 | 16 | 15–60 | **73–188** | 98–213 |
| ~1,000 MAU (10 tenants) | 20–60 | 40–70 (B4ms) | 16–55 | 30–90 | **120–280** | 145–305 |
| ~5,000 MAU (50 tenants) | 60–150 | 120–250 (GP D2–D4) | 55–110 | 80–200 | **350–750** | 375–775 |

Identity stays **free to 50,000 MAU**; adding tenants is nearly free until real scale. The Entra claims provider adds **~$10–14/mo** (one always-on 0.25-vCPU Container App replica beyond the free grant) at every scale — included in the totals above; it's in the fixed floor, not per-user. (Azure-native Front Door Premium WAF would instead add ~$330/mo flat at any scale — see the WAF note above.) The 1,000 / 5,000 MAU rows' ranges already absorb it.

---

## Credit runway (Founders Hub)

Founders Hub grants up to **$150,000** in Azure credits (tiered over the program window).

| Scenario | Burn / mo | $150k lasts* |
|---|---:|---|
| Baseline, no WAF | ~$133 | effectively the entire program |
| Baseline + Cloudflare WAF | ~$158 | effectively the entire program |
| Growth to 5,000 MAU + Cloudflare WAF | ~$615 | many years of runtime-equivalent |
| (If Azure-native Front Door Premium WAF) | +~$330 flat | still covered by credits |

\* Runway is capped by the credit eligibility window, not spend — the point is that **out-of-pocket Azure cost is ~$0 for the foreseeable future**, and even post-credits the baseline ($60–175) + Cloudflare (~$25) is very manageable.

---

## Notes
- The app is portable by design: **PostgreSQL + Alembic** run identically on Azure; the backend runs as a **container on Azure Container Apps** while **AWS keeps Lambda unchanged** (ADR-005 — same `shared/` business logic, thin per-cloud edge), selected by the `DEPLOY_CLOUD`/`CLOUD_PROVIDER` switches. The SPA deploys to Blob + Front Door. See `infrastructure/azure/README.md` for the full Azure stack + bring-up and `docs/runbook.md` for the cloud-portability approach.
- Numbers are list-price estimates; actual spend varies with log volume, Postgres load, and whether Premium WAF is enabled.
