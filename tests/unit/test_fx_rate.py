"""Unit tests for shared.fx_rate — the Bybit P2P base rate + per-tenant markup
that replaces the old "tenant_admin types a fixed NGN/USD number" model.

fetch_bybit_ngn_rate() is tested by mocking urllib.request.urlopen directly —
the actual live endpoint/request-shape was verified by hand against the real
Bybit API while designing this feature (see 07_api_tenant_management.md).
"""

import json
import urllib.error
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from shared.circuit_breaker import CircuitBreaker
from shared.exceptions import ExternalServiceError
from shared.fx_rate import (
    compute_effective_rate,
    fetch_bybit_ngn_rate,
    get_base_market_rate,
    get_effective_dollar_rate,
    get_tenant_markup,
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _bybit_response(prices: list[str], ret_code: int = 0) -> bytes:
    return json.dumps(
        {
            "ret_code": ret_code,
            "ret_msg": "SUCCESS" if ret_code == 0 else "error",
            "result": {"count": len(prices), "items": [{"price": p, "minAmount": "5000", "maxAmount": "10000"} for p in prices]},
        }
    ).encode("utf-8")


def _urlopen_returning(body: bytes):
    """A context-manager mock matching `with urlopen(...) as resp: resp.read()`."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestComputeEffectiveRate:
    def test_percentage_markup(self):
        assert compute_effective_rate(Decimal("1550"), "percentage", Decimal("2")) == Decimal("1581.00")

    def test_flat_markup(self):
        assert compute_effective_rate(Decimal("1550"), "flat", Decimal("15")) == Decimal("1565.00")

    def test_zero_markup_passes_base_rate_through(self):
        assert compute_effective_rate(Decimal("1373.20"), "percentage", Decimal("0")) == Decimal("1373.20")
        assert compute_effective_rate(Decimal("1373.20"), "flat", Decimal("0")) == Decimal("1373.20")

    def test_rounds_to_two_decimal_places(self):
        # 1550 * 1.033 = 1601.15 exactly, but exercise a case that needs
        # ROUND_HALF_UP: 1550 * 1.0333 = 1601.615 -> 1601.62.
        assert compute_effective_rate(Decimal("1550"), "percentage", Decimal("3.33")) == Decimal("1601.62")

    def test_fractional_percentage_markup(self):
        assert compute_effective_rate(Decimal("1550"), "percentage", Decimal("0.1")) == Decimal("1551.55")


class TestFetchBybitNgnRate:
    def test_averages_the_top_five_cheapest_ads(self):
        body = _bybit_response(["1373.20", "1373.35", "1373.35", "1373.40", "1373.45", "1400.00"])
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(body)):
            rate = fetch_bybit_ngn_rate()
        # Mean of the first 5 (the 6th, higher-priced ad is not in the top-5 sample).
        assert rate == Decimal("1373.35")

    def test_sends_the_correct_request_shape(self):
        body = _bybit_response(["1373.20"])
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(body)) as mock_urlopen:
            fetch_bybit_ngn_rate()

        request = mock_urlopen.call_args[0][0]
        assert request.full_url == "https://api2.bybit.com/fiat/otc/item/online"
        sent_body = json.loads(request.data.decode("utf-8"))
        assert sent_body["tokenId"] == "USDT"
        assert sent_body["currencyId"] == "NGN"
        # side="1" == sell-USDT ads, the cheaper/best-first side (verified live).
        assert sent_body["side"] == "1"

    def test_http_error_raises_external_service_error(self):
        err = urllib.error.HTTPError(url="", code=403, msg="Forbidden", hdrs=None, fp=None)
        err.read = lambda: b"blocked"
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(ExternalServiceError):
                fetch_bybit_ngn_rate()

    def test_network_unreachable_raises_external_service_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            with pytest.raises(ExternalServiceError):
                fetch_bybit_ngn_rate()

    def test_empty_items_raises_external_service_error(self):
        body = _bybit_response([])
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(body)):
            with pytest.raises(ExternalServiceError):
                fetch_bybit_ngn_rate()

    def test_non_zero_ret_code_raises_external_service_error(self):
        body = _bybit_response(["1373.20"], ret_code=10001)
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(body)):
            with pytest.raises(ExternalServiceError):
                fetch_bybit_ngn_rate()

    def test_malformed_json_raises_external_service_error(self):
        with patch("urllib.request.urlopen", return_value=_urlopen_returning(b"not json")):
            with pytest.raises(ExternalServiceError):
                fetch_bybit_ngn_rate()


class TestGetBaseMarketRate:
    """get_circuit_breaker is always patched to return a *fresh* CircuitBreaker
    per test — the real one is a process-wide singleton keyed by name, and
    letting one test's failures leak into another's CLOSED-state assumption
    would make these tests order-dependent."""

    def test_cache_hit_returns_cached_value_without_fetching(self):
        cached = json.dumps({"rate": "1373.35", "fetched_at": "2026-09-19T00:00:00+00:00"})
        with (
            patch("shared.fx_rate._cache.get", return_value=cached),
            patch("shared.fx_rate.fetch_bybit_ngn_rate") as mock_fetch,
        ):
            result = get_base_market_rate()

        mock_fetch.assert_not_called()
        assert result == {"rate": Decimal("1373.35"), "fetched_at": "2026-09-19T00:00:00+00:00", "rate_source": "live"}

    def test_cache_miss_fetches_and_populates_both_caches(self):
        with (
            patch("shared.fx_rate._cache.get", return_value=None),
            patch("shared.fx_rate._cache.set") as mock_cache_set,
            patch("shared.fx_rate.get_circuit_breaker", return_value=CircuitBreaker("test")),
            patch("shared.fx_rate.fetch_bybit_ngn_rate", return_value=Decimal("1373.35")),
            patch("shared.fx_rate._persist_fallback") as mock_persist,
        ):
            result = get_base_market_rate()

        assert result["rate"] == Decimal("1373.35")
        mock_cache_set.assert_called_once()
        mock_persist.assert_called_once_with(Decimal("1373.35"), result["fetched_at"])

    def test_fetch_failure_falls_back_to_persisted_last_known_good_rate(self):
        with (
            patch("shared.fx_rate._cache.get", return_value=None),
            patch("shared.fx_rate.get_circuit_breaker", return_value=CircuitBreaker("test")),
            patch("shared.fx_rate.fetch_bybit_ngn_rate", side_effect=ExternalServiceError("Bybit P2P", "down")),
            patch("shared.fx_rate._read_persisted_fallback", return_value={"rate": "1400.00", "fetched_at": "yesterday"}),
        ):
            result = get_base_market_rate()

        assert result == {"rate": Decimal("1400.00"), "fetched_at": "yesterday", "rate_source": "last_known"}

    def test_fetch_failure_with_no_persisted_fallback_uses_hardcoded_constant(self):
        with (
            patch("shared.fx_rate._cache.get", return_value=None),
            patch("shared.fx_rate.get_circuit_breaker", return_value=CircuitBreaker("test")),
            patch("shared.fx_rate.fetch_bybit_ngn_rate", side_effect=ExternalServiceError("Bybit P2P", "down")),
            patch("shared.fx_rate._read_persisted_fallback", return_value=None),
        ):
            result = get_base_market_rate()

        # Never raises, never returns a non-positive/missing rate — billing/
        # claims/refunds must always get *something* usable back.
        assert result["rate"] > 0
        # Labelled as what it is, and not stamped "now" (audit BE-11): it was never fetched.
        assert result["rate_source"] == "hardcoded"
        assert result["fetched_at"] is None

    def test_unparseable_cache_entry_is_discarded_and_falls_through_to_fetch(self):
        with (
            patch("shared.fx_rate._cache.get", return_value="not valid json"),
            patch("shared.fx_rate.get_circuit_breaker", return_value=CircuitBreaker("test")),
            patch("shared.fx_rate.fetch_bybit_ngn_rate", return_value=Decimal("1373.35")),
            patch("shared.fx_rate._cache.set"),
            patch("shared.fx_rate._persist_fallback"),
        ):
            result = get_base_market_rate()

        assert result["rate"] == Decimal("1373.35")


class TestGetTenantMarkup:
    def test_defaults_to_zero_percentage_markup_when_never_configured(self):
        with patch("shared.fx_rate.execute_with_tenant", return_value=[]):
            markup = get_tenant_markup(TENANT_ID)
        assert markup == {"markup_type": "percentage", "markup_value": 0}

    def test_returns_configured_markup(self):
        rows = [{"config_value": {"markup_type": "flat", "markup_value": 15, "updated_at": "t1"}}]
        with patch("shared.fx_rate.execute_with_tenant", return_value=rows):
            markup = get_tenant_markup(TENANT_ID)
        assert markup == {"markup_type": "flat", "markup_value": 15, "updated_at": "t1"}


class TestGetEffectiveDollarRate:
    def test_combines_base_rate_and_tenant_markup(self):
        with (
            patch(
                "shared.fx_rate.get_base_market_rate",
                return_value={"rate": Decimal("1373.20"), "fetched_at": "t0", "rate_source": "live"},
            ),
            patch(
                "shared.fx_rate.get_tenant_markup", return_value={"markup_type": "flat", "markup_value": 15, "updated_at": "t1"}
            ),
        ):
            result = get_effective_dollar_rate(TENANT_ID)

        assert result["base_rate"] == Decimal("1373.20")
        assert result["rate"] == Decimal("1388.20")
        assert result["markup_type"] == "flat"
        assert result["markup_value"] == Decimal("15")
        assert result["source"] == "bybit_p2p"
        assert result["fetched_at"] == "t0"
        assert result["markup_updated_at"] == "t1"

    def test_zero_markup_tenant_gets_the_raw_base_rate(self):
        with (
            patch(
                "shared.fx_rate.get_base_market_rate",
                return_value={"rate": Decimal("1373.20"), "fetched_at": "t0", "rate_source": "live"},
            ),
            patch("shared.fx_rate.get_tenant_markup", return_value={"markup_type": "percentage", "markup_value": 0}),
        ):
            result = get_effective_dollar_rate(TENANT_ID)

        assert result["rate"] == Decimal("1373.20")
