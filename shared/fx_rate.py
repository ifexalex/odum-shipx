"""USD→NGN "black market" rate: Bybit P2P base + per-tenant markup.

Replaces the old model (a tenant_admin typed a fixed NGN/USD number into
`tenant_config['dollar_rate']`) with a computed one: a platform-wide base
rate sourced live from Bybit's P2P USDT/NGN order book, plus a per-tenant
markup (percentage or a flat NGN amount) layered on top at read time.

The base rate is *not* tenant data — the black market doesn't vary by
tenant — so it's cached/persisted at the platform level (Redis + the
existing `platform_settings` table, migration 011), while each tenant's
markup stays in their own `tenant_config` under the `dollar_rate_markup` key.

This module is the single place every consumer (services/tenant_management,
services/billing, services/claims, services/refunds — previously four
independent `tenant_config['dollar_rate']` readers) should call through;
see get_effective_dollar_rate().

Bybit endpoint note: this is the same undocumented, unauthenticated call
bybit.com's own P2P page makes (verified live against the real API while
designing this) — not part of Bybit's official signed v5 API, which is
scoped to a merchant managing their own ads, not reading the public order
book. `side="1"` returns sell-USDT ads sorted ascending by price (cheapest
first) — confirmed live this is the lower of the two sides, i.e. the rate at
which Naira converts to dollars, which is the rate this platform needs for
pricing USD-denominated shipments in NGN.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from shared.circuit_breaker import get_circuit_breaker
from shared.db import execute_with_tenant, execute_write_with_tenant
from shared.distributed_cache import DistributedCache
from shared.exceptions import ExternalServiceError
from shared.ssl_context import verified_ssl_context
from shared.tenant_context import PLATFORM_TENANT_ID

logger = logging.getLogger(__name__)

_BYBIT_URL = "https://api2.bybit.com/fiat/otc/item/online"
_TIMEOUT_SECONDS = 10
_SAMPLE_SIZE = 5  # average of the top N (cheapest) online ads

_CACHE_TTL_SECONDS = 600  # ~10 minutes — confirmed with the user
_CACHE_KEY = "ngn_usdt"
_cache = DistributedCache(default_ttl=_CACHE_TTL_SECONDS, key_prefix="fx_rate:")

_PLATFORM_SETTING_KEY = "fx_bybit_ngn_rate"

# Last resort only — hit when Bybit is unreachable AND no rate has ever been
# successfully fetched and persisted (e.g. a brand new platform). Existing
# consumers (billing/claims/refunds) previously hard-skipped or defaulted to
# 1550 when tenant_config was simply empty; this constant plays the same
# "never let a missing rate silently corrupt a calculation" role.
_HARDCODED_FALLBACK_RATE = Decimal("1600")

#: Where a base rate came from (audit BE-11). Invoices record it (`billing.exchange_rate_source`, migration 068).
#: ``live`` - fetched from Bybit within the cache window (10 minutes).
#: ``last_known`` - Bybit could not be reached; the last rate that was fetched, however old (see ``fetched_at``).
#: ``hardcoded`` - no rate has ever been fetched; ``_HARDCODED_FALLBACK_RATE``. Invoicing refuses it.
RATE_SOURCE_LIVE = "live"
RATE_SOURCE_LAST_KNOWN = "last_known"
RATE_SOURCE_HARDCODED = "hardcoded"

_DEFAULT_MARKUP: dict[str, Any] = {"markup_type": "percentage", "markup_value": 0}


def fetch_bybit_ngn_rate() -> Decimal:
    """Fetch the current USDT/NGN P2P rate directly from Bybit.

    Returns the mean of the cheapest `_SAMPLE_SIZE` online sell-USDT ads
    (Bybit returns them pre-sorted ascending by price for side="1") — a
    single ad's price would be one merchant's opportunistic outlier; a
    5-ad average tracks the prevailing rate without needing a volume-
    weighted model.

    Raises:
        ExternalServiceError: HTTP/network failure, malformed response, an
            explicit API-level error (`ret_code != 0`), or no ads returned.
    """
    body = {
        "tokenId": "USDT",
        "currencyId": "NGN",
        "payment": [],
        "side": "1",
        "size": str(_SAMPLE_SIZE * 2),
        "page": "1",
        "amount": "",
        "vaMaker": False,
        "bulkMaker": False,
        "canTrade": False,
        "verificationFilter": 0,
        "sortType": "OVERALL_RANKING",
        "paymentPeriod": [],
        "itemRegion": 1,
    }
    req = urllib.request.Request(
        _BYBIT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.bybit.com",
            # Cloudflare (and similar CDNs) reject urllib's default
            # "Python-urllib/…" UA — same gotcha as paystack.py.
            "User-Agent": "ShipX-Logistics/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS, context=verified_ssl_context()) as resp:  # noqa: S310 — fixed https URL
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("Bybit P2P rate fetch rejected (%s): %s", exc.code, detail)
        raise ExternalServiceError("Bybit P2P", f"rate fetch failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        logger.warning("Bybit P2P unreachable: %s", exc)
        raise ExternalServiceError("Bybit P2P", "unreachable") from exc
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("Bybit P2P returned an unparseable response: %s", exc)
        raise ExternalServiceError("Bybit P2P", "malformed response") from exc

    if payload.get("ret_code") != 0:
        raise ExternalServiceError("Bybit P2P", payload.get("ret_msg", "non-zero ret_code"))

    items = (payload.get("result") or {}).get("items") or []
    if not items:
        raise ExternalServiceError("Bybit P2P", "no online ads returned")

    sample = items[:_SAMPLE_SIZE]
    prices = [Decimal(str(item["price"])) for item in sample]
    return (sum(prices, Decimal("0")) / len(prices)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _read_persisted_fallback() -> dict[str, Any] | None:
    rows = execute_with_tenant(
        PLATFORM_TENANT_ID,
        "SELECT value FROM platform_settings WHERE key = %s LIMIT 1",
        (_PLATFORM_SETTING_KEY,),
    )
    if not rows:
        return None
    value = rows[0]["value"]
    return value if isinstance(value, dict) else None


def _persist_fallback(rate: Decimal, fetched_at: str) -> None:
    """Best-effort — a failure here must never break the caller, which
    already has the rate it needs; this only affects future fallback
    quality if Bybit later becomes unreachable."""
    try:
        execute_write_with_tenant(
            PLATFORM_TENANT_ID,
            """
            INSERT INTO platform_settings (key, value, updated_at)
            VALUES (%(key)s, %(value)s::jsonb, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            RETURNING key
            """,
            {"key": _PLATFORM_SETTING_KEY, "value": json.dumps({"rate": str(rate), "fetched_at": fetched_at})},
        )
    except Exception:
        logger.warning("Failed to persist fx_bybit_ngn_rate fallback", exc_info=True)


def get_base_market_rate() -> dict[str, Any]:
    """Return the current platform-wide base rate: {"rate": Decimal, "fetched_at": str | None, "rate_source": str}.

    ``rate_source`` is one of ``RATE_SOURCE_*``; ``fetched_at`` is when that rate was really fetched, and None for the
    hard-coded value, which was never fetched.

    Priority: warm Redis cache (10 min TTL) -> live Bybit fetch (circuit-
    breaker guarded) -> last successfully-fetched rate persisted in
    `platform_settings` (however old) -> a hardcoded constant, logged at
    ERROR, if literally no rate has ever been fetched. Billing/claims/
    refunds must never hard-block on a missing rate the way they silently
    did when tenant_config was simply empty.
    """
    cached = _cache.get(_CACHE_KEY)
    if cached:
        try:
            data = json.loads(cached)
            return {"rate": Decimal(str(data["rate"])), "fetched_at": data["fetched_at"], "rate_source": RATE_SOURCE_LIVE}
        except (ValueError, KeyError, TypeError):
            logger.warning("Discarding unparseable cached fx rate: %r", cached)

    try:
        cb = get_circuit_breaker("bybit_p2p", failure_threshold=5, recovery_timeout=60)
        rate = cb.call(fetch_bybit_ngn_rate)
        fetched_at = datetime.now(UTC).isoformat()
        _cache.set(_CACHE_KEY, json.dumps({"rate": str(rate), "fetched_at": fetched_at}), ttl=_CACHE_TTL_SECONDS)
        _persist_fallback(rate, fetched_at)
        return {"rate": rate, "fetched_at": fetched_at, "rate_source": RATE_SOURCE_LIVE}
    except ExternalServiceError as exc:
        logger.warning("Bybit P2P fetch failed, falling back to last known rate: %s", exc)

    fallback = _read_persisted_fallback()
    if fallback:
        return {
            "rate": Decimal(str(fallback["rate"])),
            "fetched_at": fallback["fetched_at"],
            "rate_source": RATE_SOURCE_LAST_KNOWN,
        }

    logger.error("No Bybit rate has ever been successfully fetched — using hardcoded fallback %s", _HARDCODED_FALLBACK_RATE)
    # Not stamped "now": this value was never fetched, and a fresh timestamp made it look live.
    return {"rate": _HARDCODED_FALLBACK_RATE, "fetched_at": None, "rate_source": RATE_SOURCE_HARDCODED}


def compute_effective_rate(base_rate: Decimal, markup_type: str, markup_value: Decimal) -> Decimal:
    """Apply a tenant's markup to the base rate. Pure — no I/O."""
    if markup_type == "flat":
        result = base_rate + markup_value
    else:
        result = base_rate * (Decimal("1") + markup_value / Decimal("100"))
    return result.quantize(Decimal("0.01"), ROUND_HALF_UP)


def get_tenant_markup(tenant_id: str) -> dict[str, Any]:
    """Return this tenant's markup config, defaulting to zero markup
    (pass Bybit's raw rate through) if never configured — same
    default-if-missing pattern the old dollar_rate reads used."""
    rows = execute_with_tenant(
        tenant_id,
        "SELECT config_value FROM tenant_config WHERE tenant_id = %s AND config_key = 'dollar_rate_markup' LIMIT 1",
        (tenant_id,),
    )
    if not rows or not isinstance(rows[0]["config_value"], dict):
        return dict(_DEFAULT_MARKUP)
    cfg = rows[0]["config_value"]
    return {
        "markup_type": cfg.get("markup_type", "percentage"),
        "markup_value": cfg.get("markup_value", 0),
        "updated_at": cfg.get("updated_at"),
    }


def get_effective_dollar_rate(tenant_id: str) -> dict[str, Any]:
    """The one function every consumer should call for "the dollar rate".

    Returns:
        {"rate": Decimal, "base_rate": Decimal, "markup_type": str,
         "markup_value": Decimal, "source": "bybit_p2p", "rate_source": "live" | "last_known" | "hardcoded",
         "fetched_at": str | None, "markup_updated_at": str | None}
    """
    base = get_base_market_rate()
    markup = get_tenant_markup(tenant_id)
    markup_type = markup.get("markup_type", "percentage")
    markup_value = Decimal(str(markup.get("markup_value", 0)))
    effective = compute_effective_rate(base["rate"], markup_type, markup_value)
    return {
        "rate": effective,
        "base_rate": base["rate"],
        "markup_type": markup_type,
        "markup_value": markup_value,
        "source": "bybit_p2p",
        "rate_source": base["rate_source"],
        "fetched_at": base["fetched_at"],
        "markup_updated_at": markup.get("updated_at"),
    }


def rate_age_minutes(fetched_at: str | None, now: datetime | None = None) -> float | None:
    """How old a rate is, in minutes; None when it was never fetched (the hard-coded value) or the time is unreadable."""
    if not fetched_at:
        return None
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return ((now or datetime.now(UTC)) - fetched).total_seconds() / 60
