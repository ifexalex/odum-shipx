"""Pricing settings.

The dollar-rate markup and CBM rates (with their history), custom charge types, and container capacity presets.

Split out of ``service.py`` (audit BE-13); ``service`` re-exports every public function, so callers are unchanged.
"""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from shared.audit import log_audit
from shared.cbm_rate import get_cbm_rate_config, get_min_cbm_per_item
from shared.exceptions import (
    BusinessRuleViolationError,
    DuplicateResourceError,
    ResourceNotFoundError,
    ValidationError,
)
from shared.fx_rate import get_effective_dollar_rate

from . import repository as repo
from .models import (
    UpdateDollarRateMarkupRequest,
)

if TYPE_CHECKING:
    from .models import UpdateCbmRateRequest


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dollar rate
# ---------------------------------------------------------------------------


def get_dollar_rate(tenant_id: str) -> dict[str, Any]:
    """The effective USD/NGN rate: Bybit's live P2P base rate plus this
    tenant's markup (shared/fx_rate.py). `effective_from` is the markup's
    own last-changed timestamp (the stable, admin-controlled part);
    `fetched_at` separately reports how fresh the underlying market data is.
    """
    effective = get_effective_dollar_rate(tenant_id)
    return {
        "rate": effective["rate"],
        "base_rate": effective["base_rate"],
        "markup_type": effective["markup_type"],
        "markup_value": effective["markup_value"],
        "source": effective["source"],
        "rate_source": effective["rate_source"],
        "fetched_at": effective["fetched_at"],
        "currency_pair": "USD_NGN",
        "effective_from": effective["markup_updated_at"] or "",
    }


def update_dollar_rate(
    tenant_id: str,
    req: UpdateDollarRateMarkupRequest,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Update this tenant's markup on the Bybit-sourced base rate (the rate
    itself is no longer set directly — see get_dollar_rate)."""
    current = get_dollar_rate(tenant_id)

    new_markup = {
        "markup_type": req.markup_type.value,
        "markup_value": float(req.markup_value),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "dollar_rate_markup", new_markup, updated_by=actor_id)

    # Effective rate *after* the markup change — this, not the raw markup
    # value, is what rate_history/RateHistoryTable charts (unchanged
    # frontend component; it just reads rate_value.rate as a plain number).
    # Cast every Decimal to float here — get_dollar_rate/get_effective_dollar_rate
    # return Decimal, but repo.append_rate_history's json.dumps() has no
    # `default=str` (unlike log_audit's) and raises on a raw Decimal; found
    # live (rate_history silently stopped recording anything after this
    # feature shipped, swallowed by this function's own try/except below).
    updated = get_dollar_rate(tenant_id)
    new_value = {
        "rate": float(updated["rate"]),
        "base_rate": float(updated["base_rate"]),
        "markup_type": updated["markup_type"],
        "markup_value": float(updated["markup_value"]),
    }

    try:
        repo.append_rate_history(
            tenant_id=tenant_id,
            rate_type="dollar_rate",
            rate_value=new_value,
            previous_value={
                "rate": float(current["rate"]),
                "markup_type": current["markup_type"],
                "markup_value": float(current["markup_value"]),
            },
            changed_by=actor_id,
        )
    except Exception as exc:
        logger.warning("rate_history append failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"dollar_rate_markup": {"markup_type": current["markup_type"], "markup_value": current["markup_value"]}},
        after_state={"dollar_rate_markup": new_markup},
        ip_address=ip_address,
    )
    return {**updated, "previous_rate": current["rate"]}


def list_rate_history(
    tenant_id: str,
    rate_type: str | None = None,
    limit: int = 50,
    cursor: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return paginated rate history for a tenant."""
    return repo.list_rate_history(tenant_id, rate_type=rate_type, limit=limit, cursor=cursor)


def get_cbm_rate(tenant_id: str) -> dict[str, Any]:
    """This tenant's CBM rate config: currency + carton/bag/bale rates.

    "flat" (the common case) is just carton_rate == bag_rate == bale_rate —
    see shared/cbm_rate.py for the backward-compat normalization of the
    pre-2026-09-20 single-rate shape.

    Rates are cast to float here, for this API response only — the shared
    config resolver itself must keep returning Decimal (services/billing
    does real money arithmetic with it), but this repository's `success()`
    response helper (shared/responses.py) serializes anything it doesn't
    recognize via `json.dumps(..., default=str)`, which would otherwise
    turn every rate into a JSON string here — inconsistent with
    update_cbm_rate's response (already float-cast) and, found live, a
    frontend crash (`config.carton_rate.toFixed is not a function`) since
    the frontend types these fields as `number`.
    """
    config = get_cbm_rate_config(tenant_id)
    return {
        **config,
        "carton_rate": float(config["carton_rate"]),
        "bag_rate": float(config["bag_rate"]),
        "bale_rate": float(config["bale_rate"]),
        "min_cbm_per_item": float(get_min_cbm_per_item(tenant_id)),
    }


def update_cbm_rate(
    tenant_id: str,
    req: "UpdateCbmRateRequest",
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    current = get_cbm_rate(tenant_id)
    # bag_rate/bale_rate are always set by this point — the request's own
    # model_validator (_resolve_per_type_rates) guarantees it — but narrowed
    # explicitly here since the field type itself is still `Decimal | None`.
    bag_rate = req.bag_rate if req.bag_rate is not None else req.carton_rate
    bale_rate = req.bale_rate if req.bale_rate is not None else req.carton_rate
    new_value = {
        "currency": req.currency.value,
        "rate_mode": req.rate_mode.value,
        "carton_rate": float(req.carton_rate),
        "bag_rate": float(bag_rate),
        "bale_rate": float(bale_rate),
        "effective_from": datetime.now(UTC).isoformat(),
    }
    repo.upsert_config(tenant_id, "cbm_rate_per_unit", new_value, updated_by=actor_id)

    # Minimum billable CBM floor — its own config key, updated only when supplied.
    if req.min_cbm_per_item is not None:
        repo.upsert_config(
            tenant_id,
            "min_cbm_per_item",
            {"value": float(req.min_cbm_per_item)},
            updated_by=actor_id,
        )

    try:
        repo.append_rate_history(
            tenant_id=tenant_id,
            rate_type="cbm_rate",
            rate_value=new_value,
            previous_value={
                "currency": current["currency"],
                "rate_mode": current["rate_mode"],
                "carton_rate": float(current["carton_rate"]),
                "bag_rate": float(current["bag_rate"]),
                "bale_rate": float(current["bale_rate"]),
            },
            changed_by=actor_id,
        )
    except Exception as exc:
        logger.warning("rate_history append failed: %s", exc)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"cbm_rate_per_unit": current},
        after_state={"cbm_rate_per_unit": new_value},
        ip_address=ip_address,
    )
    return {**new_value, "min_cbm_per_item": float(get_min_cbm_per_item(tenant_id))}


# ---------------------------------------------------------------------------
# Charge types
# ---------------------------------------------------------------------------


def _serialize_charge_type(row: dict[str, Any]) -> dict[str, Any]:
    """Map a charge_type DB row to the wire shape.

    The column is `default_amount_ngn`; the wire (frontend) contract is
    `amount_ngn`. `usage_count` is present only on list rows (correlated
    count) — default to 0 for single-row create/update responses.
    """
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "amount_ngn": row.get("default_amount_ngn"),
        "is_active": row.get("is_active", True),
        "usage_count": int(row.get("usage_count") or 0),
        "created_at": row.get("created_at"),
    }


def _charge_type_write_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Translate inbound wire fields to DB column names (amount_ngn -> default_amount_ngn)."""
    mapped = {k: v for k, v in data.items() if k in ("name", "description", "is_active")}
    if "amount_ngn" in data:
        mapped["default_amount_ngn"] = data["amount_ngn"]
    return mapped


def create_charge_type(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    charge_type = repo.create_charge_type(tenant_id, {**_charge_type_write_fields(data), "created_by": actor_id})
    if charge_type is None:
        raise RuntimeError("create_charge_type returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=str(charge_type["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=charge_type,
        ip_address=ip_address,
    )
    return _serialize_charge_type(charge_type)


def list_charge_types(tenant_id: str) -> list[dict[str, Any]]:
    return [_serialize_charge_type(row) for row in repo.list_charge_types(tenant_id)]


def update_charge_type(
    tenant_id: str,
    charge_type_id: str,
    updates: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = repo.get_charge_type_by_id(tenant_id, charge_type_id)
    if not existing:
        raise ResourceNotFoundError("charge_type", charge_type_id)
    updated = repo.update_charge_type(tenant_id, charge_type_id, _charge_type_write_fields(updates))
    if updated is None:
        raise RuntimeError("update_charge_type returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=charge_type_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state=existing,
        after_state=updated,
        ip_address=ip_address,
    )
    return _serialize_charge_type(updated)


def deactivate_charge_type(
    tenant_id: str,
    charge_type_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    existing = repo.get_charge_type_by_id(tenant_id, charge_type_id)
    if not existing:
        raise ResourceNotFoundError("charge_type", charge_type_id)
    result = repo.update_charge_type(tenant_id, charge_type_id, {"is_active": False})
    if result is None:
        raise RuntimeError("update_charge_type returned None unexpectedly")

    # Ground-truth gap found while auditing log coverage: create/update both
    # log this; deactivate was the one silently missing.
    log_audit(
        tenant_id=tenant_id,
        entity_type="charge_type",
        entity_id=charge_type_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        before_state={"is_active": existing.get("is_active")},
        after_state={"is_active": False},
        ip_address=ip_address,
    )
    return _serialize_charge_type(result)


# ---------------------------------------------------------------------------
# Container capacity presets
#
# Ten well-known shipping-container capacities ship as read-only defaults
# (internal usable volumes; recommended load ≈ 92% of capacity, the practical
# fill target). Tenants add their own custom presets on top via the admin
# config page — those persist in container_capacity. The list endpoint merges
# defaults + custom so the create-container picker shows everything.
# ---------------------------------------------------------------------------

DEFAULT_CONTAINER_CAPACITIES: list[dict[str, Any]] = [
    {"name": "45' High Cube (HC)", "capacity_cbm": 86.0, "recommended_cbm": 79.0},
    {"name": "40' High Cube (HC)", "capacity_cbm": 76.0, "recommended_cbm": 70.0},
    {"name": "40' Standard (GP)", "capacity_cbm": 67.0, "recommended_cbm": 62.0},
    {"name": "40' Open Top", "capacity_cbm": 66.0, "recommended_cbm": 60.0},
    {"name": "40' Reefer (HC)", "capacity_cbm": 67.0, "recommended_cbm": 60.0},
    {"name": "20' High Cube (HC)", "capacity_cbm": 37.0, "recommended_cbm": 34.0},
    {"name": "20' Standard (GP)", "capacity_cbm": 33.0, "recommended_cbm": 30.0},
    {"name": "20' Open Top", "capacity_cbm": 32.0, "recommended_cbm": 29.0},
    {"name": "20' Reefer", "capacity_cbm": 28.0, "recommended_cbm": 25.0},
    {"name": "10' Standard", "capacity_cbm": 16.0, "recommended_cbm": 14.0},
]

_CAPACITY_NAME_MAX = 100


def _serialize_container_capacity(row: dict[str, Any], *, is_custom: bool) -> dict[str, Any]:
    """Map a capacity (default dict or DB row) to the wire shape, CBM as floats
    so the frontend can call toFixed without the Decimal-as-string trap."""
    rec = row.get("recommended_cbm")
    return {
        "id": str(row["id"]) if is_custom else f"default:{row['name']}",
        "name": row["name"],
        "capacity_cbm": float(row["capacity_cbm"]),
        "recommended_cbm": float(rec) if rec is not None else None,
        "is_custom": is_custom,
    }


_CAPACITY_OVERRIDES_KEY = "container_capacity_overrides"


def _default_recommended_overrides(tenant_id: str) -> dict[str, float]:
    """Per-tenant admin overrides of the built-in defaults' recommended load,
    stored in tenant_config (no table needed) as {default name: recommended}."""
    for row in repo.get_all_configs(tenant_id):
        if row["config_key"] == _CAPACITY_OVERRIDES_KEY:
            raw = row.get("config_value") or {}
            return {k: float(v) for k, v in raw.items() if v is not None}
    return {}


def list_container_capacities(tenant_id: str) -> list[dict[str, Any]]:
    custom = [_serialize_container_capacity(row, is_custom=True) for row in repo.list_container_capacities(tenant_id)]
    overrides = _default_recommended_overrides(tenant_id)
    defaults = []
    for row in DEFAULT_CONTAINER_CAPACITIES:
        item = _serialize_container_capacity(row, is_custom=False)
        if row["name"] in overrides:
            item["recommended_cbm"] = overrides[row["name"]]
        defaults.append(item)
    # Largest first, so the create-container picker leads with 40'/45' HC.
    return sorted(custom + defaults, key=lambda c: c["capacity_cbm"], reverse=True)


def update_container_capacity(
    tenant_id: str,
    capacity_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    rec_raw = data.get("recommended_cbm")
    rec_cleared = rec_raw in (None, "")
    recommended = None if rec_cleared else _positive_cbm(rec_raw, "recommended_cbm")

    # --- Default preset: only recommended_cbm is tunable (capacity/name are
    # physical constants). Persisted as an override in tenant_config. ---
    if capacity_id.startswith("default:"):
        name = capacity_id[len("default:") :]
        default = next((d for d in DEFAULT_CONTAINER_CAPACITIES if d["name"] == name), None)
        if default is None:
            raise ResourceNotFoundError("container_capacity", capacity_id)
        if recommended is not None and recommended > float(default["capacity_cbm"]):
            raise ValidationError("recommended_cbm cannot exceed capacity_cbm")
        overrides = _default_recommended_overrides(tenant_id)
        if rec_cleared:
            overrides.pop(name, None)  # revert to the built-in recommended
        else:
            overrides[name] = recommended  # type: ignore[assignment]
        repo.upsert_config(tenant_id, _CAPACITY_OVERRIDES_KEY, overrides, updated_by=actor_id)
        log_audit(
            tenant_id=tenant_id,
            entity_type="container_capacity",
            entity_id=capacity_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"recommended_cbm": recommended},
            ip_address=ip_address,
        )
        item = _serialize_container_capacity(default, is_custom=False)
        item["recommended_cbm"] = (
            recommended
            if recommended is not None
            else (float(default["recommended_cbm"]) if default["recommended_cbm"] else None)
        )
        return item

    # --- Custom preset: name / capacity / recommended all editable. ---
    existing = repo.get_container_capacity_by_id(tenant_id, capacity_id)
    if not existing:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    updates: dict[str, Any] = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("name is required")
        if len(name) > _CAPACITY_NAME_MAX:
            raise ValidationError(f"name must be at most {_CAPACITY_NAME_MAX} characters")
        updates["name"] = name
    if data.get("capacity_cbm") not in (None, ""):
        updates["capacity_cbm"] = _positive_cbm(data.get("capacity_cbm"), "capacity_cbm")
    if "recommended_cbm" in data:
        updates["recommended_cbm"] = recommended
    effective_capacity = updates.get("capacity_cbm", float(existing["capacity_cbm"]))
    if updates.get("recommended_cbm") is not None and updates["recommended_cbm"] > effective_capacity:
        raise ValidationError("recommended_cbm cannot exceed capacity_cbm")

    try:
        row = repo.update_container_capacity(tenant_id, capacity_id, updates)
    except Exception as exc:  # UNIQUE (tenant_id, name)
        if "container_capacity" in str(exc) and ("unique" in str(exc).lower() or "duplicate" in str(exc).lower()):
            raise DuplicateResourceError("container_capacity", updates.get("name", "")) from exc
        raise
    if row is None:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=capacity_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state=updates,
        ip_address=ip_address,
    )
    return _serialize_container_capacity(row, is_custom=True)


def create_container_capacity(
    tenant_id: str,
    data: dict[str, Any],
    actor_id: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationError("name is required")
    if len(name) > _CAPACITY_NAME_MAX:
        raise ValidationError(f"name must be at most {_CAPACITY_NAME_MAX} characters")
    capacity_cbm = _positive_cbm(data.get("capacity_cbm"), "capacity_cbm")
    recommended = data.get("recommended_cbm")
    recommended_cbm = _positive_cbm(recommended, "recommended_cbm") if recommended not in (None, "") else None
    if recommended_cbm is not None and recommended_cbm > capacity_cbm:
        raise ValidationError("recommended_cbm cannot exceed capacity_cbm")

    try:
        row = repo.create_container_capacity(
            tenant_id,
            {"name": name, "capacity_cbm": capacity_cbm, "recommended_cbm": recommended_cbm, "created_by": actor_id},
        )
    except Exception as exc:  # UNIQUE (tenant_id, name)
        if "container_capacity" in str(exc) and ("unique" in str(exc).lower() or "duplicate" in str(exc).lower()):
            raise DuplicateResourceError("container_capacity", name) from exc
        raise
    if row is None:
        raise RuntimeError("create_container_capacity returned None unexpectedly")
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=str(row["id"]),
        action="CREATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"name": name, "capacity_cbm": capacity_cbm, "recommended_cbm": recommended_cbm},
        ip_address=ip_address,
    )
    return _serialize_container_capacity(row, is_custom=True)


def delete_container_capacity(
    tenant_id: str,
    capacity_id: str,
    actor_id: str,
    ip_address: str | None = None,
) -> None:
    # Only custom presets are deletable; defaults are code constants with a
    # synthetic "default:" id that never reaches a DB row.
    if capacity_id.startswith("default:"):
        raise BusinessRuleViolationError("Default container capacities cannot be deleted", rule_id="CAPACITY_DEFAULT_IMMUTABLE")
    deleted = repo.delete_container_capacity(tenant_id, capacity_id)
    if deleted is None:
        raise ResourceNotFoundError("container_capacity", capacity_id)
    log_audit(
        tenant_id=tenant_id,
        entity_type="container_capacity",
        entity_id=capacity_id,
        action="DELETE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        ip_address=ip_address,
    )


def _positive_cbm(value: Any, field: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a number") from exc
    if num <= 0:
        raise ValidationError(f"{field} must be greater than 0")
    if num > 1000:
        raise ValidationError(f"{field} is unrealistically large")
    return num
