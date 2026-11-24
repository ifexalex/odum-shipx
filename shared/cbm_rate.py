"""CBM (cubic-metre) freight rate: tenant-configured, currency + per-package-type.

Historically `tenant_config['cbm_rate_per_unit']` held a single flat USD
number (`{"rate_usd": 45.00}`) applied uniformly to every packing-list item
regardless of what it actually was. This module lets a tenant admin instead
choose: (1) which currency the rate is denominated in (USD or NGN), and
(2) whether it's one flat rate or three separate rates for carton/bag/bale
package types — modeled as a *single* code path, not two: "flat" is simply
the state where all three rates happen to be equal, so
`compute_cbm_charge()` never branches on mode, only on the actual rate
values and each item's `package_unit`.

Mirrors `shared/fx_rate.py`'s role as the one place billing reads tenant
pricing config from, and its direct-SQL-against-tenant_config pattern
(avoids services/billing importing services/tenant_management's repository).
"""

import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from shared.db import execute_with_tenant

logger = logging.getLogger(__name__)

_KNOWN_BUCKETS = ("carton", "bag", "bale")
_BAG_UNITS = frozenset({"bag", "bags"})
_BALE_UNITS = frozenset({"bale", "bales", "big bale", "small bale"})

_DEFAULT_CONFIG: dict[str, Any] = {
    "currency": "usd",
    "rate_mode": "flat",
    "carton_rate": Decimal("0"),
    "bag_rate": Decimal("0"),
    "bale_rate": Decimal("0"),
    "effective_from": "",
}


def _safe_decimal(raw: Any, fallback: Decimal) -> Decimal:
    if raw is None:
        return fallback
    try:
        val = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    return val if val.is_finite() and val >= Decimal("0") else fallback


def normalize_package_unit(package_unit: str | None) -> str:
    """Map a free-text `packing_list_item.package_unit` to a billable bucket.

    Recognises singular/plural/sized variants for "bag" and "bale"; everything
    else — carton, pallet, item, mixed, unspecified, null, or any future
    free-text value — falls back to "carton".
    """
    normalized = (package_unit or "").strip().lower()
    if normalized in _BAG_UNITS:
        return "bag"
    if normalized in _BALE_UNITS:
        return "bale"
    return "carton"


def get_cbm_rate_config(tenant_id: str) -> dict[str, Any]:
    """Read + normalize this tenant's CBM rate config.

    Returns:
        {"currency": "usd"|"ngn", "rate_mode": "flat"|"per_package_type",
         "carton_rate": Decimal, "bag_rate": Decimal, "bale_rate": Decimal,
         "effective_from": str}

    Backward-compatible with the pre-existing single-rate shape
    (`{"rate_usd": 45.00}`) and with a missing/empty config row — neither
    requires a data migration; both are normalized here at read time.
    """
    rows = execute_with_tenant(
        tenant_id,
        "SELECT config_value FROM tenant_config WHERE tenant_id = %s AND config_key = 'cbm_rate_per_unit' LIMIT 1",
        (tenant_id,),
    )
    raw = rows[0]["config_value"] if rows and isinstance(rows[0]["config_value"], dict) else {}

    if "carton_rate" in raw:
        carton_rate = _safe_decimal(raw.get("carton_rate"), Decimal("0"))
        raw_currency = str(raw.get("currency") or "usd").strip().lower()
        currency = raw_currency if raw_currency in ("usd", "ngn") else "usd"
        return {
            "currency": currency,
            "rate_mode": str(raw.get("rate_mode") or "flat").strip().lower(),
            "carton_rate": carton_rate,
            "bag_rate": _safe_decimal(raw.get("bag_rate"), carton_rate),
            "bale_rate": _safe_decimal(raw.get("bale_rate"), carton_rate),
            "effective_from": raw.get("effective_from") or "",
        }

    if "rate_usd" in raw:
        # Pre-2026-09-20 shape: one flat USD rate, no currency/mode/per-type fields.
        flat = _safe_decimal(raw.get("rate_usd"), Decimal("0"))
        return {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": flat,
            "bag_rate": flat,
            "bale_rate": flat,
            "effective_from": raw.get("effective_from") or "",
        }

    # Never configured (missing/empty row) — all-zero rates, which the
    # caller's skip-guard treats the same way a missing rate always has:
    # skip billing and log a warning rather than charging nothing silently.
    return dict(_DEFAULT_CONFIG)


# Minimum billable CBM per line item. Tiny parcels measured below this floor
# are billed at the floor (a half-carton still occupies handling space). Stored
# per-tenant in its own tenant_config key so admins can tune it; defaults to 0.1.
DEFAULT_MIN_CBM = Decimal("0.1")


def get_min_cbm_per_item(tenant_id: str) -> Decimal:
    """Read the tenant's minimum-CBM-per-item floor (default 0.1)."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT config_value FROM tenant_config WHERE tenant_id = %s AND config_key = 'min_cbm_per_item' LIMIT 1",
        (tenant_id,),
    )
    raw = rows[0]["config_value"] if rows and isinstance(rows[0]["config_value"], dict) else {}
    try:
        value = Decimal(str(raw.get("value", DEFAULT_MIN_CBM)))
    except (ArithmeticError, TypeError, ValueError):
        return DEFAULT_MIN_CBM
    return value if value > 0 else DEFAULT_MIN_CBM


def apply_min_cbm(cbm: Decimal | None, min_cbm: Decimal) -> Decimal:
    """Floor a computed line-item CBM at the tenant's minimum."""
    if cbm is None:
        return min_cbm
    return cbm if cbm >= min_cbm else min_cbm


def compute_cbm_charge(cbm_by_unit: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Price a customer's CBM, grouped by package type, against `config`.

    Args:
        cbm_by_unit: raw `package_unit` (as stored, not yet normalized) -> CBM.
        config: as returned by `get_cbm_rate_config`.

    Returns:
        {"amount": Decimal, "currency": str,
         "breakdown": {"carton": {"cbm": Decimal, "rate": Decimal, "subtotal": Decimal}, "bag": {...}, "bale": {...}}}

    Each bucket's subtotal is rounded to 2dp independently, then summed for
    `amount` — so a displayed breakdown always sums exactly to the
    displayed total (never off by a cent from rounding a combined total).
    """
    buckets: dict[str, Decimal] = {b: Decimal("0") for b in _KNOWN_BUCKETS}
    for unit, cbm in cbm_by_unit.items():
        buckets[normalize_package_unit(unit)] += Decimal(str(cbm))

    rate_by_bucket = {b: Decimal(str(config[f"{b}_rate"])) for b in _KNOWN_BUCKETS}

    breakdown: dict[str, dict[str, Decimal]] = {}
    amount = Decimal("0")
    for bucket in _KNOWN_BUCKETS:
        cbm = buckets[bucket]
        rate = rate_by_bucket[bucket]
        subtotal = (cbm * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        breakdown[bucket] = {"cbm": cbm, "rate": rate, "subtotal": subtotal}
        amount += subtotal

    return {"amount": amount, "currency": config.get("currency", "usd"), "breakdown": breakdown}
