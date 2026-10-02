# Task FE-13 — Deployment & CI/CD

## Objective

Deploy the SPA cost-effectively and scalably (S3 + CloudFront, as decided earlier — see [00_frontend_master_plan.md](00_frontend_master_plan.md) Architecture Decision), and wire it into the existing CI/CD pipeline (`18_cicd_pipeline.md`).

## Depends On

Task 01.

## Why S3 + CloudFront (recap)

Near-zero infra cost (S3 storage in cents, CloudFront's request pricing has a generous free tier), no servers to size or patch, scales globally at the edge by default, and integrates with what already exists: Cognito for auth, API Gateway for all data, GitHub Actions for the pipeline. No SSR requirement (Task 00) means no Lambda@Edge/Amplify Hosting complexity is needed.

## Terraform Additions

New module, sibling to the existing `04a`–`04e` infra modules (`infrastructure/` — confirm exact path against current Terraform layout before creating):

| Resource | Purpose |
|---|---|
| `aws_s3_bucket` (private) | Hosts the built `dist/` — never made public directly |
| `aws_cloudfront_origin_access_control` | Lets CloudFront read the private bucket without the bucket being public |
| `aws_cloudfront_distribution` | Two behaviors: default → S3 origin (static assets + SPA fallback to `index.html` for client-side routing); `/v1/*` (if proxying API same-origin) or a separate API Gateway custom domain — decide based on whether the team wants the API on the same apex domain or a separate `api.shipx.co` (simpler, recommended — avoids CloudFront-to-API-Gateway proxying entirely) |
| `aws_cloudfront_response_headers_policy` | CSP, `X-Content-Type-Options`, `Strict-Transport-Security`, `Referrer-Policy` (Task 11) |
| `aws_acm_certificate` (us-east-1, regardless of app region — CloudFront requirement) | TLS for `shipx.co`, `*.shipx.co` (covers tenant subdomains, Task 06) |
| `aws_route53_record` (alias) | `shipx.co` and `*.shipx.co` → CloudFront distribution |

**SPA routing fallback:** configure a CloudFront custom error response — 403/404 from S3 (object not found, since client-side routes like `/admin/users/123` don't exist as S3 keys) → serve `/index.html` with a 200, so react-router can take over.

**Tenant subdomain wildcard:** a single `*.shipx.co` CNAME/alias pointed at the same CloudFront distribution serves every tenant from the same static bundle — the JS reads the hostname only for branding (Task 02/06), so no per-tenant infrastructure is needed despite the wildcard subdomain pattern.

## Environments

Mirror the backend's environment split (confirm exact names against `18_cicd_pipeline.md`): `dev`, `staging`, `production` — each gets its own S3 bucket + CloudFront distribution + `.env` build (Task 01's `VITE_*` vars), pointing at that environment's API Gateway/Cognito pool.

## CI/CD Pipeline

Extend the existing GitHub Actions pipeline rather than standing up a parallel one:

```
on PR touching frontend/:
  - npm ci
  - npm run lint
  - npm run typecheck
  - npm run test (Vitest, Task 12)
  - npm run build (catches build-time errors early)

on merge to main (or environment branch):
  - npm run build
  - aws s3 sync dist/ s3://<env-bucket> --delete
  - aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
  - npm run test:e2e (Playwright, against the freshly-deployed environment or local stack — decide based on how fast the team wants merge-to-deploy feedback)
```

**Cache headers:** set long `Cache-Control: max-age=31536000, immutable` on hashed asset filenames (Vite's default content-hashed output makes this safe) and `Cache-Control: no-cache` on `index.html` itself, so deploys are picked up immediately without needing a full CloudFront invalidation on every deploy (only invalidate `/index.html` and any non-hashed paths, not the whole distribution, once this is confirmed working — full invalidation is fine to start with and optimize later).

## Rollback

Since deploys are just an S3 sync, rollback is: re-deploy the previous build artifact (keep the last N `dist/` builds as CI artifacts, or version them in the S3 bucket with a `current` pointer) — no blue/green or canary infrastructure needed at this scale. If the team wants safer rollouts later, CloudFront supports weighted origin groups, but that's a future optimization, not a v1 requirement.

## Implementation Notes

### Terraform module: `infrastructure/modules/cloudfront/`
- Private S3 bucket with versioning + AES256 SSE; public access blocked entirely.
- `aws_cloudfront_origin_access_control` (OAC, not the deprecated OAI) — S3 bucket policy grants `s3:GetObject` only to the distribution.
- ACM wildcard cert (`shipx.co` + `*.shipx.co`) provisioned in `us-east-1` with DNS validation via Route 53.
- Response-headers policy: `Content-Security-Policy`, `Strict-Transport-Security` (preload, `max-age=31536000`), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`, `X-XSS-Protection`.
- Two cache policies: `max-age=31536000,immutable` for hashed assets; `max-age=0` for `index.html`. The `index.html` is served via a separate `ordered_cache_behavior` on `/index.html`.
- SPA routing: `custom_error_response` for both 403 and 404 → serve `/index.html` with HTTP 200 so React Router handles the path. S3 returns 403 (not 404) for missing keys in private buckets.
- Route 53: apex A-record alias + `*.shipx.co` wildcard alias → same CloudFront distribution.
- Module is gated by `count = var.route53_zone_id != "" ? 1 : 0` — skipped cleanly in local dev where no domain is registered.

### Provider alias for us-east-1
`infrastructure/providers.tf` now includes `provider "aws" { alias = "us_east_1" }`. The cloudfront module declares `configuration_aliases = [aws.us_east_1]` and the root wires it with `providers = { aws.us_east_1 = aws.us_east_1 }`.

### CI/CD pipeline: `.github/workflows/frontend-ci.yml`
**PR (build-and-test job):** `npm ci` → typecheck → lint → test → build → `npm audit --audit-level=high` → security greps. Uploads `dist/` as a numbered artifact (30-day retention) for rollback.

**Merge to main (deploy job):** Rebuilds with production `VITE_*` secrets → `aws s3 sync` hashed assets with `max-age=31536000,immutable` → uploads `index.html` separately with `no-cache` → invalidates `/index.html` only (not `/*` — hashed filenames make full invalidation unnecessary and expensive).

### Required GitHub Actions secrets
| Secret | Source |
|---|---|
| `FRONTEND_DEPLOY_ROLE_ARN` | IAM role ARN with `s3:PutObject`, `s3:DeleteObject`, `cloudfront:CreateInvalidation` |
| `FRONTEND_S3_BUCKET` | Terraform output `frontend_bucket_name` |
| `FRONTEND_CLOUDFRONT_ID` | Terraform output `cloudfront_distribution_id` |
| `VITE_API_BASE_URL` | API Gateway invoke URL |
| `VITE_COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `VITE_COGNITO_CLIENT_ID` | Cognito App Client ID |
| `VITE_ENVIRONMENT` | `"staging"` or `"production"` |

### Rollback procedure
1. Find the `frontend-dist-{sha}` artifact for the last good commit in GitHub Actions.
2. Download and re-upload: `aws s3 sync dist/ s3://{FRONTEND_S3_BUCKET} --delete`.
3. Upload `index.html` with `--cache-control "no-cache,no-store,must-revalidate"`.
4. Run `aws cloudfront create-invalidation --distribution-id {ID} --paths "/index.html"`.
5. Verify by hitting `https://shipx.co` with a hard refresh.

No blue/green infrastructure needed — S3 sync is atomic enough at this traffic scale.

## Acceptance Criteria

- [x] Terraform module creates the S3 bucket (private, OAC-only), CloudFront distribution, response-headers policy (CSP + security headers), ACM cert, and Route 53 records. Module gated by `route53_zone_id` variable — skips safely in local dev.
- [x] SPA client-side routing: 403/404 from S3 → 200 + `/index.html` via `custom_error_response` — deep links work on fresh page load.
- [x] `*.shipx.co` wildcard alias on the distribution; single bundle serves all tenant subdomains; branding applied client-side from hostname.
- [x] CI: every PR runs typecheck + lint + test + build + audit + security greps; merge to main triggers the deploy job.
- [x] Hashed assets: `max-age=31536000,immutable` via separate cache policy. `index.html`: `no-cache` via ordered behavior + cache policy. Only `/index.html` is invalidated per deploy.
- [x] Rollback procedure documented above; re-deploys from CI artifacts (30-day retention).
