# Operational Runbook

Logistics & Cargo Management System — platform operations guide.

## Environments

| Environment | AWS Account | Region | Notes |
|---|---|---|---|
| dev | — | eu-west-1 | Aurora auto-pause enabled |
| staging | — | eu-west-1 | Aurora auto-pause enabled |
| prod | — | eu-west-1 | No auto-pause; DR replication to eu-central-1 |

---

## Common Operations

- **Tail Lambda logs:** `aws logs tail /aws/lambda/logistics-<service>-prod --follow`
- **Check alarms:** AWS CloudWatch → Alarms → `logistics-*`
- **Dashboard:** CloudWatch → Dashboards → `logistics-prod-overview`

---

## Release Procedures

### Normal release to staging

Create and push an RC tag from a commit that has a green CI run on `main`:

```bash
git tag v1.2.3-rc1 <sha>
git push origin v1.2.3-rc1
```

Only members of `@{org}/release-managers` can push `v*` tags (GitHub tag protection ruleset).
The deploy pipeline resolves the CI artifact for the tagged commit SHA — the tag push will fail
at the `resolve-artifact` step if no successful CI run exists for that commit.

### Normal release to prod

After staging smoke tests pass, push the stable tag:

```bash
git tag v1.2.3 <sha>
git push origin v1.2.3
```

The `deploy-prod` job requires `smoke-staging` to have passed on the same workflow run.

### Post-prod observation window

After every prod deploy, watch CloudWatch for **5 minutes**:

1. Open the `logistics-prod-overview` CloudWatch dashboard
2. Check: Lambda Errors (all functions) — should remain at 0
3. Check: API Gateway 5xx Errors — should remain at 0
4. Check: SQS DLQ — all queues should have 0 visible messages

If alarms fire within the window, initiate rollback immediately (see below).
If all metrics are green at 5 minutes, deployment is complete — no further action needed.

---

## Hotfix Procedure (break-glass)

Use when a critical bug is in prod and cannot wait for the normal tag-based release cycle.

**Prerequisites:** You must be a member of `@{org}/release-managers`.

### Option A — Tag the hotfix commit directly (preferred)

1. Create and push the hotfix on a branch, get it reviewed and merged to `main`
2. Confirm CI passes on the merge commit
3. Tag directly for prod:
   ```bash
   git tag v1.2.4 <hotfix-sha>
   git push origin v1.2.4
   ```
4. Pipeline deploys; observe the 5-minute window (above)

### Option B — `workflow_dispatch` (last resort, when Option A cannot be used)

This is a break-glass procedure. A **post-incident review is required** after any `workflow_dispatch`
to prod.

1. Go to **Actions → Deploy Pipeline → Run workflow**
2. Select `environment: prod`
3. Provide `run_id`: find the CI Pipeline run ID for the commit you want to deploy
   (Actions tab URL contains the run ID, or use `gh run list --workflow=ci.yml`)
4. Run workflow
5. Observe the 5-minute window (above)
6. File a post-incident review in `docs/adr/` documenting why the normal path was bypassed

---

## Rollback Procedure

### Lambda rollback — re-deploy a previous tag

```bash
# Re-tag the last known-good commit as a new patch release
git tag v1.2.4 <prev-sha>
git push origin v1.2.4
```

Or use `workflow_dispatch` with the run ID from a previous successful CI run (see Option B above).

### Lambda rollback — direct AWS CLI (fastest, if artifact is unavailable)

```bash
# Re-deploy a specific service from a previously uploaded zip (if stored in S3):
aws lambda update-function-code \
  --function-name logistics-billing-prod \
  --s3-bucket logistics-artifacts-<account-id> \
  --s3-key previous/billing.zip

# Wait for propagation:
aws lambda wait function-updated --function-name logistics-billing-prod
```

### Terraform rollback

Re-apply the previous infrastructure state:

```bash
cd infrastructure
terraform apply -var-file=environments/prod.tfvars -target=module.lambda
```

### Database rollback

Run an Alembic downgrade **only if** the migration must be reverted. Coordinate with all
service owners before downgrading — code must be rolled back first.

```bash
# Invoke the migration Lambda with a downgrade payload:
aws lambda invoke \
  --function-name logistics-migrate-prod \
  --payload '{"command": "downgrade", "target": "-1"}' \
  /tmp/migrate-out.json
cat /tmp/migrate-out.json
```

Or connect directly via bastion/Session Manager and run:
```bash
alembic -c migrations/alembic.ini downgrade -1
```

**Important:** Migrations must be backward-compatible (additive only). Never drop columns or rename
in the same release as code changes. Use a 2-phase strategy:
- Phase 1: Add new column (nullable), deploy code that writes to both
- Phase 2: Backfill, deploy code reads from new column, drop old column in a follow-up release

---

## Incident Response

### Alarm fired — Lambda Errors > 5 in 5 minutes

1. Check CloudWatch Logs Insights for the affected function:
   ```
   fields @timestamp, @message
   | filter @message like /ERROR/
   | sort @timestamp desc
   | limit 50
   ```
2. Check if a deploy occurred in the last 30 minutes (Actions → Deploy Pipeline)
3. If deploy-related: initiate rollback (see above)
4. If not deploy-related: investigate in logs, page on-call if customer-facing

### Alarm fired — SQS DLQ depth > 0

1. Identify which DLQ: `logistics-{dlq-name}-prod`
2. Check the DLQ message body for the failure reason
3. Fix the root cause, then re-drive messages:
   ```bash
   aws sqs start-message-move-task \
     --source-arn arn:aws:sqs:eu-west-1:<account>:logistics-<name>-dlq-prod \
     --destination-arn arn:aws:sqs:eu-west-1:<account>:logistics-<name>-prod
   ```

### Alarm fired — API Gateway 5xx > 1%

1. Check `logistics-prod-overview` dashboard for which Lambda(s) are erroring
2. Correlate with recent deploys or traffic spikes
3. If deploy-related: rollback; if traffic-related: check Aurora connection alarm

### Alarm fired — Aurora connections > 40

Connection pool (RDS Proxy) is near its limit. Investigate:
1. Check for long-running queries: connect via Session Manager and run `pg_stat_activity`
2. Check for Lambda concurrency spike in CloudWatch
3. If sustained: consider reducing Lambda reserved concurrency temporarily

---

## Severity SLA

| Severity | Patch Within |
|---|---|
| CRITICAL | 24 hours |
| HIGH | 72 hours |
| MEDIUM | 2 weeks |
| LOW | Next sprint |

See Architecture Decision Records in `docs/adr/` for system design context.
