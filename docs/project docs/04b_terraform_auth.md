# Task 04b — Terraform: Cognito User Pool & Multi-Tenant Auth

## Objective

Create the Terraform module for Amazon Cognito — the single shared User Pool for all tenants with `custom:tenant_id` as an immutable custom attribute.

## Depends On

- Task 01 (Terraform directory structure)

## Architecture Context

- **Single Cognito User Pool** for all tenants (up to 50K MAU free tier)
- Custom attributes: `custom:tenant_id` (immutable after creation), `custom:role`
- Cognito Groups prefixed with tenant_id: `{tenant_id}:china_office_staff`
- Platform Admin has `custom:tenant_id = PLATFORM`
- JWT tokens include `custom:tenant_id` and `cognito:groups`
- Password policy: min 8 chars, requires uppercase, lowercase, numbers

## Deliverables

### File: `infrastructure/aws/modules/cognito/main.tf`

**Resources:**
- `aws_cognito_user_pool` — "logistics-users-{env}"
  - Custom attributes:
    - `custom:tenant_id` — string, mutable = false (immutable after set)
    - `custom:role` — string, mutable = true
  - Password policy: min_length=8, require_lowercase=true, require_uppercase=true, require_numbers=true, require_symbols=false
  - MFA: optional (for admin roles)
  - Auto-verified attributes: email
  - Schema: email (required, mutable), name (required, mutable)
  - Account recovery: email
  - admin_create_user_config: allow_admin_create_user_only = true (users can't self-register in v1)
  - Invite message: customized for logistics platform

- `aws_cognito_user_pool_client` — "logistics-web-client"
  - explicit_auth_flows: ADMIN_NO_SRP_AUTH, USER_PASSWORD_AUTH, ALLOW_REFRESH_TOKEN_AUTH
  - token_validity: access_token = 1 hour, id_token = 1 hour, refresh_token = 30 days
  - read_attributes: all standard + custom:tenant_id + custom:role
  - write_attributes: standard only (NOT custom:tenant_id — prevents user modification)

- `aws_cognito_user_pool_domain` — "{project}-{env}" (Cognito hosted UI domain)

**Outputs:** user_pool_id, user_pool_arn, client_id, user_pool_domain

### File: `infrastructure/aws/modules/cognito/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "callback_urls" { type = list(string), default = ["http://localhost:3000/callback"] }
variable "logout_urls" { type = list(string), default = ["http://localhost:3000/logout"] }
```

## Roles & Group Naming Convention

When a tenant user is created, they are added to a Cognito group with the naming pattern:
```
{tenant_id}:{role}
```

Example groups for tenant `abc-123`:
- `abc-123:tenant_admin`
- `abc-123:china_office_staff`
- `abc-123:nigeria_office_staff`
- `abc-123:warehouse_attendant`
- `abc-123:customer`

Platform Admin group: `PLATFORM:platform_admin`

Groups are created dynamically by the Tenant Management Lambda when users are provisioned (not in Terraform).

## Acceptance Criteria

- [x] User Pool has `custom:tenant_id` as immutable custom attribute
- [x] User Pool Client cannot write `custom:tenant_id` (prevents user self-modification)
- [x] Admin-only user creation (no self-registration)
- [x] Token validity: 1h access, 1h id, 30d refresh
- [x] Password policy: min 8 chars, upper+lower+numbers required
- [ ] `terraform plan` succeeds — **`terraform validate` passes (audited 2026-11-11); a real `plan` needs AWS credentials this environment does not have, so the stronger claim is unverified.** Same caveat as `04c_terraform_api_gateway.md`.
