"""Tenant business policies with effective dates and append-only history (Phase 1, TC-01, D4).

Manages:
  - ``storage_fee``          (enabled, grace_period_days, daily_fee_per_carton_ngn)
  - ``refund_threshold_usd`` (staff_limit, requires_manager_above)
  - ``credit_defaults``      (default_credit_limit_ngn, default_credit_terms_days)
  - ``dispute_escalation``   (enabled, auto_escalate_days)
  - ``reminder_days``        (storage_first_reminder, storage_final_reminder)

Every save writes an append-only row to ``tenant_policy_history`` with a chosen
``effective_date`` (default tomorrow UTC) and audits the change with before/after states.
If ``effective_date <= today``, ``tenant_config`` is also kept in sync immediately.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from shared.audit import log_audit
from shared.db import execute_with_tenant, execute_write_with_tenant, tenant_transaction
from shared.exceptions import ValidationError
from shared.tenant_policies import POLICY_DEFAULTS, POLICY_KEYS, resolve_policy_for_date

from . import repository as repo

logger = logging.getLogger(__name__)


def _validate_policy_value(policy_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a policy payload by key (strict fail-closed)."""
    if policy_key not in POLICY_DEFAULTS:
        raise ValidationError(
            f"Unknown policy_key '{policy_key}'",
            field_errors={"policy_key": f"Must be one of: {', '.join(POLICY_KEYS)}"},
        )

    if policy_key == "storage_fee":
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationError("storage_fee.enabled must be boolean", field_errors={"value.enabled": "Required boolean"})
        try:
            grace = int(raw.get("grace_period_days", 14))
            daily = Decimal(str(raw.get("daily_fee_per_carton_ngn", 500)))
        except Exception as exc:
            raise ValidationError("Invalid storage_fee numbers", field_errors={"value": "Invalid numeric values"}) from exc
        if grace < 0 or grace > 365:
            raise ValidationError(
                "grace_period_days must be between 0 and 365",
                field_errors={"value.grace_period_days": "Must be between 0 and 365"},
            )
        if not daily.is_finite() or daily < Decimal("0") or daily > Decimal("1000000"):
            raise ValidationError(
                "daily_fee_per_carton_ngn must be between 0 and 1,000,000",
                field_errors={"value.daily_fee_per_carton_ngn": "Must be >= 0 and <= 1,000,000"},
            )
        return {
            "enabled": enabled,
            "grace_period_days": grace,
            "daily_fee_per_carton_ngn": float(daily) if daily % 1 else int(daily),
        }

    if policy_key == "refund_threshold_usd":
        try:
            staff_limit = Decimal(str(raw.get("staff_limit", 50)))
        except Exception as exc:
            raise ValidationError("Invalid staff_limit", field_errors={"value.staff_limit": "Must be a number"}) from exc
        if not staff_limit.is_finite() or staff_limit < Decimal("0") or staff_limit > Decimal("100000"):
            raise ValidationError(
                "staff_limit must be between 0 and 100,000 USD",
                field_errors={"value.staff_limit": "Must be >= 0 and <= 100,000"},
            )
        limit_num = float(staff_limit) if staff_limit % 1 else int(staff_limit)
        return {
            "staff_limit": limit_num,
            "requires_manager_above": limit_num,
        }

    if policy_key == "credit_defaults":
        try:
            limit_ngn = Decimal(str(raw.get("default_credit_limit_ngn", 0)))
            terms_days = int(raw.get("default_credit_terms_days", 14))
        except Exception as exc:
            raise ValidationError("Invalid credit_defaults values", field_errors={"value": "Invalid numeric values"}) from exc
        if not limit_ngn.is_finite() or limit_ngn < Decimal("0") or limit_ngn > Decimal("1000000000"):
            raise ValidationError(
                "default_credit_limit_ngn must be >= 0",
                field_errors={"value.default_credit_limit_ngn": "Must be >= 0"},
            )
        if terms_days < 0 or terms_days > 365:
            raise ValidationError(
                "default_credit_terms_days must be between 0 and 365",
                field_errors={"value.default_credit_terms_days": "Must be between 0 and 365"},
            )
        return {
            "default_credit_limit_ngn": float(limit_ngn) if limit_ngn % 1 else int(limit_ngn),
            "default_credit_terms_days": terms_days,
        }

    if policy_key == "dispute_escalation":
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationError(
                "dispute_escalation.enabled must be boolean",
                field_errors={"value.enabled": "Required boolean"},
            )
        try:
            days = int(raw.get("auto_escalate_days", 5))
        except Exception as exc:
            raise ValidationError(
                "Invalid auto_escalate_days",
                field_errors={"value.auto_escalate_days": "Must be an integer"},
            ) from exc
        if days < 1 or days > 90:
            raise ValidationError(
                "auto_escalate_days must be between 1 and 90",
                field_errors={"value.auto_escalate_days": "Must be between 1 and 90"},
            )
        return {
            "enabled": enabled,
            "auto_escalate_days": days,
        }

    if policy_key == "reminder_days":
        try:
            first_day = int(raw.get("storage_first_reminder", 7))
            final_day = int(raw.get("storage_final_reminder", 13))
        except Exception as exc:
            raise ValidationError("Invalid reminder_days values", field_errors={"value": "Must be integers"}) from exc
        if first_day < 1 or first_day > 365 or final_day < 1 or final_day > 365:
            raise ValidationError(
                "Reminder days must be between 1 and 365",
                field_errors={"value": "Days must be between 1 and 365"},
            )
        if first_day >= final_day:
            raise ValidationError(
                "First reminder day must be earlier than final reminder day",
                field_errors={"value.storage_first_reminder": "Must be less than storage_final_reminder"},
            )
        return {
            "storage_first_reminder": first_day,
            "storage_final_reminder": final_day,
        }

    raise ValidationError(f"Unsupported policy_key '{policy_key}'")


def get_tenant_policies(tenant_id: str) -> dict[str, Any]:
    """Return current effective policies, upcoming scheduled changes, and change history."""
    today = datetime.now(UTC).date()
    effective: dict[str, dict[str, Any]] = {key: resolve_policy_for_date(tenant_id, key, as_of_date=today) for key in POLICY_KEYS}

    history_rows = execute_with_tenant(
        tenant_id,
        """
        SELECT h.id,
               h.policy_key,
               h.old_value,
               h.new_value,
               h.effective_date,
               h.changed_by,
               tu.full_name AS changed_by_name,
               h.created_at
        FROM tenant_policy_history h
        LEFT JOIN tenant_user tu
          ON tu.id = h.changed_by AND tu.tenant_id = h.tenant_id
        WHERE h.tenant_id = %s
        ORDER BY h.created_at DESC
        LIMIT 50
        """,
        (tenant_id,),
    )

    scheduled: dict[str, dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for row in history_rows:
        eff_date = row["effective_date"]
        item = {
            "id": str(row["id"]),
            "policy_key": row["policy_key"],
            "old_value": row["old_value"],
            "new_value": row["new_value"],
            "effective_date": eff_date.isoformat() if hasattr(eff_date, "isoformat") else str(eff_date),
            "changed_by": str(row["changed_by"]) if row.get("changed_by") else None,
            "changed_by_name": row.get("changed_by_name"),
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        }
        history.append(item)
        # Keep the latest scheduled entry per key when effective_date > today
        key = row["policy_key"]
        parsed_eff = eff_date if isinstance(eff_date, date) else date.fromisoformat(str(eff_date))
        if parsed_eff > today and key not in scheduled:
            scheduled[key] = item

    return {
        "policies": effective,
        "scheduled": scheduled,
        "history": history,
        "default_effective_date": (today + timedelta(days=1)).isoformat(),
    }


def update_tenant_policy(
    tenant_id: str,
    policy_key: str,
    value: dict[str, Any],
    effective_date: date | None,
    *,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Record a new effective-dated policy value and audit the change."""
    today = datetime.now(UTC).date()
    chosen_date = effective_date or (today + timedelta(days=1))
    if chosen_date < today:
        raise ValidationError(
            "Policy changes cannot be backdated — choose today or a future date so past fees are never repriced.",
            field_errors={"effective_date": "Must be today or a future date"},
        )

    normalized = _validate_policy_value(policy_key, value)
    previous = resolve_policy_for_date(tenant_id, policy_key, as_of_date=today)

    with tenant_transaction(tenant_id):
        inserted = execute_write_with_tenant(
            tenant_id,
            """
            INSERT INTO tenant_policy_history (
                tenant_id, policy_key, old_value, new_value, effective_date, changed_by
            ) VALUES (
                %(tenant_id)s, %(policy_key)s, %(old_value)s::jsonb, %(new_value)s::jsonb,
                %(effective_date)s, %(changed_by)s
            )
            RETURNING id, policy_key, old_value, new_value, effective_date, changed_by, created_at
            """,
            {
                "tenant_id": tenant_id,
                "policy_key": policy_key,
                "old_value": json.dumps(previous),
                "new_value": json.dumps(normalized),
                "effective_date": chosen_date,
                "changed_by": actor_id,
            },
        )
        if inserted is None:
            raise RuntimeError("insert tenant_policy_history returned None unexpectedly")

        if chosen_date <= today:
            repo.upsert_config(tenant_id, policy_key, normalized, updated_by=actor_id)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_policy",
        entity_id=str(inserted["id"]),
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"policy_key": policy_key, **previous},
        after_state={
            "policy_key": policy_key,
            "effective_date": chosen_date.isoformat(),
            **normalized,
        },
        ip_address=ip_address,
    )

    return get_tenant_policies(tenant_id)
