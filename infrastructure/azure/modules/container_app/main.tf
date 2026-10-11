# ---------------------------------------------------------------------------
# Container Apps — the Azure compute plane (ADR-005), the analogue of AWS
# Lambda + API Gateway + SQS event sources + EventBridge schedules. One image
# (the repo-root Dockerfile) runs four workload shapes, all selected by the
# entrypoint arg:
#   - api       : one Container App with external HTTPS ingress (= API Gateway)
#   - worker    : one Container App per queue, KEDA-scaled on Service Bus depth
#                 (= the SQS event-source Lambdas)
#   - scheduled : one Container App Job per cron job (= the EventBridge rules)
#   - migrate   : a manually-triggered Container App Job (alembic)
#
# The image, env, and secrets are identical across all four; CLOUD_PROVIDER=azure
# makes the app resolve the Azure adapters built in Phases 1–2.
#
# Bootstrap note: the ACR image does not exist on the first apply. `container_image`
# defaults to a public placeholder so the resources provision cleanly; the Phase-5
# deploy workflow pushes the real image to ACR and updates the apps. image changes
# are ignored by Terraform so CI owns the running tag.
# ---------------------------------------------------------------------------

locals {
  # Non-secret env — plain values. CLOUD_PROVIDER=azure drives adapter selection.
  plain_env = {
    CLOUD_PROVIDER              = "azure"
    AUTH_PROVIDER               = var.auth_provider
    DATABASE_HOST               = var.db_host
    DATABASE_PORT               = tostring(var.db_port)
    DATABASE_NAME               = var.db_name
    DATABASE_USER               = var.db_user
    DATABASE_SSLMODE            = "require"
    REDIS_HOST                  = var.redis_host
    REDIS_PORT                  = tostring(var.redis_port)
    REDIS_SSL                   = "true"
    AZURE_EVENT_GRID_ENDPOINT   = var.event_grid_endpoint
    AZURE_KEY_VAULT_URL         = var.key_vault_url
    ENCRYPTION_KEY_VAULT_KEY_ID = var.encryption_key_id
    BLOB_CONTAINER_NAME         = var.blob_container_name
    SES_FROM_ADDRESS            = var.acs_sender_address
    # OIDC token verification — Entra values wired in Phase 4 (empty until then).
    OIDC_JWKS_URL     = var.oidc_jwks_url
    OIDC_AUDIENCE     = var.oidc_audience
    ENTRA_USER_DOMAIN = var.entra_user_domain
    # Backend httpOnly-cookie session refresh when AUTH_PROVIDER=azure (services/auth/entra_refresh.py).
    ENTRA_TOKEN_ENDPOINT = var.entra_token_endpoint
    ENTRA_CLIENT_ID      = var.entra_client_id
    ENTRA_SCOPE          = var.entra_scope
    # Browser origins allowed to call the API (the frontend URL).
    CORS_ALLOW_ORIGINS = var.cors_allow_origins
    # Per-channel queue names (the opaque queue reference on Azure).
    SQS_SMS_QUEUE_URL      = lookup(var.queue_names, "sms", "")
    SQS_WHATSAPP_QUEUE_URL = lookup(var.queue_names, "whatsapp", "")
    SQS_EMAIL_QUEUE_URL    = lookup(var.queue_names, "email", "")
    SQS_METERING_QUEUE_URL = lookup(var.queue_names, "metering", "")
  }

  # Container App secret name (lowercase alnum + '-') → value. Optional secrets
  # are gated by NON-SENSITIVE flags (var.enable_redis), not by inspecting the
  # sensitive values — a predicate over a sensitive value would mark the whole
  # map sensitive and break `for_each`. Azure also rejects an empty-valued
  # secret, which is why the disabled entry is omitted entirely rather than "".
  secret_values = merge(
    {
      database-password      = var.db_password
      service-bus-connection = var.service_bus_connection_string
      event-grid-key         = var.event_grid_key
      acs-connection         = var.acs_connection_string
      storage-connection     = var.storage_connection_string
      appinsights-connection = var.app_insights_connection_string
    },
    var.enable_redis ? { redis-password = var.redis_password } : {},
  )

  # Env var name → secret name. The redis mapping is included only when Redis is
  # enabled, so a disabled service never references a non-existent secret.
  # tomap(): the conditional fragment makes this an object; for_each needs a map.
  secret_env = tomap(merge(
    {
      DATABASE_PASSWORD                     = "database-password"
      AZURE_SERVICE_BUS_CONNECTION_STRING   = "service-bus-connection"
      AZURE_EVENT_GRID_KEY                  = "event-grid-key"
      AZURE_COMMUNICATION_CONNECTION_STRING = "acs-connection"
      AZURE_STORAGE_CONNECTION_STRING       = "storage-connection"
      APPLICATIONINSIGHTS_CONNECTION_STRING = "appinsights-connection"
    },
    var.enable_redis ? { REDIS_PASSWORD = "redis-password" } : {},
  ))

  image = var.container_image

  # Scheduled jobs → cron expression, mirroring the AWS EventBridge rules.
  scheduled_jobs = {
    storage_fee        = "0 0 * * *"   # midnight UTC daily
    storage_reminders  = "0 8 * * *"   # 08:00 UTC daily
    data_cleanup       = "0 2 * * *"   # 02:00 UTC daily
    release_expiry     = "0 0 * * *"   # midnight UTC daily
    dispute_escalation = "0 */6 * * *" # every 6 hours
    sla_check          = "0 */4 * * *" # every 4 hours
    usage_aggregation  = "0 * * * *"   # hourly
  }

  # Workers → the Service Bus queue each consumes (for the KEDA scaler).
  workers = {
    sms      = lookup(var.queue_names, "sms", "")
    whatsapp = lookup(var.queue_names, "whatsapp", "")
    email    = lookup(var.queue_names, "email", "")
    metering = lookup(var.queue_names, "metering", "")
  }
}

# ─── Container registry (private) ───────────────────────────────────────────
# Two pull modes, chosen by `grant_acr_pull`:
#   true  (default) — managed-identity pull + an AcrPull role assignment. The
#                     secure path; needs the deploy identity to have rights to
#                     write role assignments (User Access Administrator/Owner).
#   false           — enable the ACR admin user and pull with admin creds. Use
#                     when the deploy identity is Contributor-only (can't create
#                     role assignments — e.g. a restricted/Free-Trial account).
resource "azurerm_container_registry" "acr" {
  # ACR names: 5–50 chars, alphanumeric only, globally unique.
  name                = substr(lower(replace("${var.name_prefix}acr", "-", "")), 0, 40)
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.acr_sku
  admin_enabled       = !var.grant_acr_pull
  tags                = var.common_tags
}

# The app identity pulls images from ACR (secure path).
resource "azurerm_role_assignment" "acr_pull" {
  count                = var.grant_acr_pull ? 1 : 0
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = var.identity_principal_id
}

locals {
  # Registry auth: managed identity, or ACR admin creds when role assignment
  # isn't permitted. The non-chosen fields are null (unset).
  acr_identity        = var.grant_acr_pull ? var.identity_id : null
  acr_username        = var.grant_acr_pull ? null : azurerm_container_registry.acr.admin_username
  acr_password_secret = var.grant_acr_pull ? null : "acr-admin-password"

  # The ACR admin password is a Container App secret only in admin-creds mode.
  acr_secret = var.grant_acr_pull ? {} : { acr-admin-password = azurerm_container_registry.acr.admin_password }
  # Full secret map every app/job uses (base + optional ACR admin password).
  # tomap(): merge()/conditional fragments yield an object type, but for_each
  # requires a map — coerce it (all values are strings).
  all_secrets = tomap(merge(local.secret_values, local.acr_secret))
}

# ─── Container Apps Environment (VNet-integrated, logs → Log Analytics) ──────
resource "azurerm_container_app_environment" "main" {
  name                       = "${var.name_prefix}-cae"
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  infrastructure_subnet_id   = var.subnet_id
  tags                       = var.common_tags
}

# ─── API ─────────────────────────────────────────────────────────────────────
resource "azurerm_container_app" "api" {
  name                         = "${var.name_prefix}-api"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = var.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    identity             = local.acr_identity
    username             = local.acr_username
    password_secret_name = local.acr_password_secret
  }

  dynamic "secret" {
    for_each = local.all_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.api_min_replicas
    max_replicas = var.api_max_replicas

    container {
      name   = "api"
      image  = local.image
      cpu    = var.api_cpu
      memory = var.api_memory
      args   = ["api"]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    # CI owns the running image tag (pushes to ACR + updates the app).
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# ─── Queue workers (one per queue, KEDA-scaled on Service Bus depth) ─────────
resource "azurerm_container_app" "worker" {
  for_each = local.workers

  name                         = "${var.name_prefix}-worker-${each.key}"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = var.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    identity             = local.acr_identity
    username             = local.acr_username
    password_secret_name = local.acr_password_secret
  }

  dynamic "secret" {
    for_each = local.all_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  template {
    min_replicas = 0
    max_replicas = var.worker_max_replicas

    container {
      name   = "worker"
      image  = local.image
      cpu    = var.worker_cpu
      memory = var.worker_memory
      args   = ["worker", "--queue", each.key]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }

    # Scale 0→N on Service Bus queue depth (the KEDA azure-servicebus scaler).
    custom_scale_rule {
      name             = "sb-${each.key}"
      custom_rule_type = "azure-servicebus"
      metadata = {
        queueName    = each.value
        messageCount = "5"
      }
      authentication {
        secret_name       = "service-bus-connection"
        trigger_parameter = "connection"
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# ─── Scheduled jobs (cron) ───────────────────────────────────────────────────
resource "azurerm_container_app_job" "scheduled" {
  for_each = local.scheduled_jobs

  name                         = "${var.name_prefix}-job-${replace(each.key, "_", "-")}"
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = var.job_timeout_seconds
  replica_retry_limit        = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    identity             = local.acr_identity
    username             = local.acr_username
    password_secret_name = local.acr_password_secret
  }

  dynamic "secret" {
    for_each = local.all_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  schedule_trigger_config {
    cron_expression          = each.value
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "job"
      image  = local.image
      cpu    = var.job_cpu
      memory = var.job_memory
      args   = ["job", "--job", each.key]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# ─── Migration job (manual trigger) ─────────────────────────────────────────
resource "azurerm_container_app_job" "migrate" {
  name                         = "${var.name_prefix}-job-migrate"
  resource_group_name          = var.resource_group_name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = var.job_timeout_seconds
  replica_retry_limit        = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    identity             = local.acr_identity
    username             = local.acr_username
    password_secret_name = local.acr_password_secret
  }

  dynamic "secret" {
    for_each = local.all_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "migrate"
      image  = local.image
      cpu    = var.job_cpu
      memory = var.job_memory
      args   = ["migrate"]

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# ─── Entra custom-claims provider (OnTokenIssuanceStart) ────────────────────
# Own Container App (not the api) so token issuance is isolated from the API's
# availability, on the same shared image via the `claims` entrypoint. External
# ingress because Entra calls it from the internet; always-on (min 1) because
# the extension call times out ~2s. Reads users' tenant_id/role extension attrs
# from Graph with the shared managed identity (grant it User.Read.All — manual).
locals {
  claims_env = {
    CALLER_JWKS_URL      = var.claims_caller_jwks_url
    CALLER_AUDIENCE      = var.claims_caller_audience
    CALLER_ISSUER        = var.claims_caller_issuer
    ENTRA_TENANT_ID_ATTR = var.claims_tenant_id_attr
    ENTRA_ROLE_ATTR      = var.claims_role_attr
    OUT_TENANT_CLAIM     = var.claims_out_tenant_claim
    OUT_ROLE_CLAIM       = var.claims_out_role_claim
  }
}

resource "azurerm_container_app" "claims" {
  name                         = "${var.name_prefix}-entra-claims"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = var.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    identity             = local.acr_identity
    username             = local.acr_username
    password_secret_name = local.acr_password_secret
  }

  dynamic "secret" {
    for_each = local.all_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.claims_min_replicas
    max_replicas = var.claims_max_replicas

    container {
      name   = "claims"
      image  = local.image
      cpu    = var.claims_cpu
      memory = var.claims_memory
      args   = ["claims"]

      dynamic "env" {
        for_each = local.claims_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  lifecycle {
    # CI owns the running image tag (pushes to ACR + `az containerapp update`).
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}
