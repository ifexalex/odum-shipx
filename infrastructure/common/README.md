# infrastructure/common

Cross-cloud shared Terraform — only things that are **genuinely identical** on
every cloud live here, so AWS and Azure can't drift on conventions.

| Module | Purpose |
|---|---|
| `naming` | Standard tag set (Project / Environment / ManagedBy / CostCenter / Owner / Cloud) + the `<project>-<environment>` name prefix. Both the `../aws` and `../azure` roots call it. No resources — pure inputs → outputs. |

Cloud-specific resources never go here — they live in `../aws/modules/*` and
`../azure/modules/*`.
