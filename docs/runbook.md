# Operational Runbook

Logistics & Cargo Management System — platform operations guide.

## Environments

| Environment | AWS Account | Region | Notes |
|---|---|---|---|
| dev | — | eu-west-1 | Aurora auto-pause enabled |
| staging | — | eu-west-1 | Aurora auto-pause enabled |
| prod | — | eu-west-1 | No auto-pause; DR replication to eu-central-1 |

## Common Operations

- **Deploy:** `gh workflow run deploy.yml -f environment=prod`
- **Run migrations:** `make migrate`
- **Tail Lambda logs:** `aws logs tail /aws/lambda/logistics-<service>-prod --follow`
- **Check alarms:** AWS CloudWatch → Alarms → logistics-*

## Incident Response

See Architecture Decision Records in `docs/adr/` for system design context.
