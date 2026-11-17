"""Unit tests for shared.rate_limit and the endpoints it protects (audit SEC-03).

The counter is an in-memory stand-in with the same fixed-window contract as the Redis one, so these tests
cover the limiter's logic and where it is applied. The Redis script itself is exercised against a real
server in tests/redis/test_rate_limit_redis.py.
"""

import contextlib
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from shared import rate_limit
from shared.exceptions import AuthenticationRequiredError, RateLimitExceededError, ResourceNotFoundError
from shared.tenant_context import UserRole
from tests.browser import BROWSER_HEADERS
from tests.patching import patch_tenant_management


class FakeWindowCache:
    """Fixed-window counters, as `DistributedCache.incr_window` / `window_state` / `delete` behave."""

    def __init__(self, ttl: int = 42) -> None:
        self.counts: dict[str, int] = {}
        self.ttl = ttl
        self.down = False

    def incr_window(self, key: str, window_seconds: int):
        if self.down:
            return None
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key], self.ttl

    def window_state(self, key: str):
        if self.down:
            return None
        count = self.counts.get(key, 0)
        return (count, self.ttl if count else 0)

    def delete(self, key: str) -> None:
        self.counts.pop(key, None)


@pytest.fixture
def cache(monkeypatch) -> FakeWindowCache:
    """The limiter switched on, counting in memory."""
    fake = FakeWindowCache()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setattr(rate_limit, "_cache", fake)
    monkeypatch.setattr(rate_limit, "_last_unavailable_log", 0.0)
    return fake


def _event(ip: str | None, method: str = "POST", path: str = "/", **extra) -> dict:
    context: dict = {"requestId": "r1", "http": {"method": method, "path": path}}
    if ip:
        context["http"]["sourceIp"] = ip
    return {"requestContext": context, "headers": {}, "cookies": [], **extra}


# ---------------------------------------------------------------------------
# The limiter
# ---------------------------------------------------------------------------


class TestHit:
    def test_requests_up_to_the_limit_pass_and_the_next_is_refused(self, cache):
        for _ in range(rate_limit.LOGIN_IP.limit):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        with pytest.raises(RateLimitExceededError) as exc:
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        assert exc.value.status_code == 429
        assert exc.value.error_code == "RATE_LIMIT_EXCEEDED"

    def test_the_refusal_says_how_long_to_wait(self, cache):
        for _ in range(rate_limit.REGISTER_IP.limit):
            rate_limit.hit(rate_limit.REGISTER_IP, "10.0.0.1")
        with pytest.raises(RateLimitExceededError) as exc:
            rate_limit.hit(rate_limit.REGISTER_IP, "10.0.0.1")
        assert exc.value.retry_after == cache.ttl

    def test_clients_are_counted_separately(self, cache):
        for _ in range(rate_limit.LOGIN_IP.limit):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.2")  # a different client is untouched

    def test_policies_are_counted_separately(self, cache):
        for _ in range(rate_limit.LOGIN_IP.limit):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        rate_limit.hit(rate_limit.TRACKING_IP, "10.0.0.1")  # same client, another route

    def test_a_blank_identifier_is_not_limited(self, cache):
        """No address means no way to tell clients apart; one shared bucket would lock everybody out."""
        for _ in range(rate_limit.LOGIN_IP.limit + 5):
            rate_limit.hit(rate_limit.LOGIN_IP, "")
        assert cache.counts == {}


class TestGuessLimits:
    """peek + record_failure + clear: only wrong guesses count."""

    def test_failures_up_to_the_limit_are_tolerated_and_the_next_attempt_is_refused_before_it_is_tried(self, cache):
        for _ in range(rate_limit.LOGIN_FAILURES.limit):
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")
            rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        with pytest.raises(RateLimitExceededError):
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")

    def test_peeking_alone_never_counts(self, cache):
        for _ in range(rate_limit.LOGIN_FAILURES.limit * 3):
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")
        assert cache.counts == {}

    def test_a_success_forgets_the_failures(self, cache):
        for _ in range(rate_limit.LOGIN_FAILURES.limit - 1):
            rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        rate_limit.clear(rate_limit.LOGIN_FAILURES, "ada@example.test")
        for _ in range(rate_limit.LOGIN_FAILURES.limit - 1):
            rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")  # still under the limit

    def test_the_refusal_always_carries_a_wait_even_if_the_window_just_ended(self, cache):
        cache.counts[rate_limit._key(rate_limit.LOGIN_FAILURES, "ada@example.test")] = 99
        cache.ttl = 0
        with pytest.raises(RateLimitExceededError) as exc:
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "ada@example.test")
        assert exc.value.retry_after >= 1


class TestKeys:
    def test_no_identifier_is_stored_in_the_clear(self, cache):
        rate_limit.hit(rate_limit.LOGIN_IP, "203.0.113.9")
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "ada@example.test")
        rate_limit.record_failure(rate_limit.TRACKING_FAILURES, "ACME-TRK-0001")

        stored = " ".join(cache.counts)
        assert "203.0.113.9" not in stored
        assert "ada@example.test" not in stored
        assert "ACME-TRK-0001" not in stored

    def test_an_email_is_the_same_account_whatever_its_case_or_padding(self, cache):
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "Ada@Example.Test")
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "  ada@example.test ")
        assert len(cache.counts) == 1
        assert next(iter(cache.counts.values())) == 2


class TestConfiguration:
    def test_a_policy_can_be_overridden_by_environment(self, cache, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_LOGIN_IP", "2/30")
        rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        with pytest.raises(RateLimitExceededError):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")

    def test_one_policy_can_be_switched_off(self, cache, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_LOGIN_IP", "off")
        for _ in range(100):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        assert cache.counts == {}

    @pytest.mark.parametrize("bad", ["lots", "10", "0/60", "10/0", "-1/60", "10/sixty"])
    def test_an_unusable_override_falls_back_to_the_default(self, cache, monkeypatch, bad, caplog):
        monkeypatch.setenv("RATE_LIMIT_LOGIN_IP", bad)
        with caplog.at_level(logging.WARNING):
            for _ in range(rate_limit.LOGIN_IP.limit):
                rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
            with pytest.raises(RateLimitExceededError):
                rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        assert "Ignoring RATE_LIMIT_LOGIN_IP" in caplog.text

    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "off", "no"])
    def test_the_whole_limiter_can_be_switched_off_and_then_never_touches_redis(self, cache, monkeypatch, value):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", value)
        for _ in range(100):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
            rate_limit.peek(rate_limit.LOGIN_FAILURES, "a@b.test")
            rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "a@b.test")
        assert cache.counts == {}

    def test_it_is_on_by_default(self, cache, monkeypatch):
        monkeypatch.delenv("RATE_LIMIT_ENABLED")
        assert rate_limit.enabled() is True


class TestFailOpen:
    """An unreachable Redis must not take sign-in down; it must be loud."""

    def test_requests_pass_when_redis_is_down(self, cache):
        cache.down = True
        for _ in range(rate_limit.LOGIN_IP.limit * 5):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        rate_limit.peek(rate_limit.LOGIN_FAILURES, "a@b.test")
        rate_limit.record_failure(rate_limit.LOGIN_FAILURES, "a@b.test")

    def test_the_outage_is_logged_at_error_with_a_stable_alarm_string(self, cache, caplog):
        cache.down = True
        with caplog.at_level(logging.ERROR):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("rate_limiter_unavailable" in r.getMessage() for r in errors)

    def test_a_long_outage_is_one_alarm_not_a_flood_of_lines(self, cache, caplog):
        cache.down = True
        with caplog.at_level(logging.ERROR):
            for _ in range(50):
                rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        assert len([r for r in caplog.records if "rate_limiter_unavailable" in r.getMessage()]) == 1

    def test_counting_resumes_when_redis_is_back(self, cache):
        cache.down = True
        rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        cache.down = False
        for _ in range(rate_limit.LOGIN_IP.limit):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")
        with pytest.raises(RateLimitExceededError):
            rate_limit.hit(rate_limit.LOGIN_IP, "10.0.0.1")


class TestHitForClient:
    def test_it_counts_by_the_requests_address(self, cache):
        for _ in range(rate_limit.LOGIN_IP.limit):
            rate_limit.hit_for_client(rate_limit.LOGIN_IP, _event("10.0.0.1"))
        with pytest.raises(RateLimitExceededError):
            rate_limit.hit_for_client(rate_limit.LOGIN_IP, _event("10.0.0.1"))

    def test_a_request_with_no_address_is_not_counted(self, cache):
        for _ in range(100):
            rate_limit.hit_for_client(rate_limit.LOGIN_IP, _event(None))
        assert cache.counts == {}


# ---------------------------------------------------------------------------
# The response
# ---------------------------------------------------------------------------


class TestResponse:
    def test_a_429_carries_retry_after(self):
        from shared.responses import error_response

        resp = error_response(RateLimitExceededError(37))
        assert resp["statusCode"] == 429
        assert resp["headers"]["Retry-After"] == "37"
        assert json.loads(resp["body"])["error_code"] == "RATE_LIMIT_EXCEEDED"

    def test_other_errors_have_no_retry_after(self):
        from shared.exceptions import ResourceNotFoundError
        from shared.responses import error_response

        assert "Retry-After" not in error_response(ResourceNotFoundError("x", "y"))["headers"]


# ---------------------------------------------------------------------------
# Where it is applied
# ---------------------------------------------------------------------------


def _assert_limited(resp: dict) -> None:
    assert resp["statusCode"] == 429
    assert int(resp["headers"]["Retry-After"]) >= 1
    assert json.loads(resp["body"])["error_code"] == "RATE_LIMIT_EXCEEDED"


class TestRegistrationRoutes:
    def _register(self, ip: str) -> dict:
        from services.tenant_management import handler

        event = _event(
            ip,
            path="/v1/register/acme",
            body=json.dumps({"name": "Ngozi", "email": "ngozi@example.test", "phone": "08012345678"}),
        )
        return handler.lambda_handler(event, None)

    def test_registration_is_limited_per_address(self, cache):

        with patch_tenant_management("self_register_customer", return_value=None):
            for _ in range(rate_limit.REGISTER_IP.limit):
                assert self._register("203.0.113.5")["statusCode"] == 202
            _assert_limited(self._register("203.0.113.5"))
            assert self._register("203.0.113.6")["statusCode"] == 202, "another address is unaffected"

    def test_onboarding_requests_are_limited_per_address(self, cache):
        from services.tenant_management import handler

        lead = {"company_name": "Acme Freight", "contact_name": "Ada Obi", "contact_email": "ops@acme.com"}

        def post(ip: str) -> dict:
            return handler.lambda_handler(_event(ip, path="/v1/onboarding-requests", body=json.dumps(lead)), None)

        with patch_tenant_management("create_onboarding_request", return_value={"id": "x", "status": "new"}):
            for _ in range(rate_limit.ONBOARDING_IP.limit):
                assert post("203.0.113.5")["statusCode"] == 201
            _assert_limited(post("203.0.113.5"))
            assert post("203.0.113.6")["statusCode"] == 201

    def test_a_refused_registration_creates_nothing(self, cache):

        with patch_tenant_management("self_register_customer", return_value=None) as register:
            for _ in range(rate_limit.REGISTER_IP.limit + 3):
                self._register("203.0.113.5")
        assert register.call_count == rate_limit.REGISTER_IP.limit


class TestPublicTracking:
    def _lookup(self, ip: str, code: str = "ACME-TRK-1", phone: str = "08012345678") -> dict:
        from services.tracking import handler

        event = _event(ip, method="GET", path=f"/v1/shipments/{code}", queryStringParameters={"phone": phone})
        return handler.lambda_handler(event, None)

    def test_lookups_are_limited_per_address(self, cache):
        from services.tracking import service

        with patch.object(service, "get_shipment_by_code_and_phone", return_value={"tracking_code": "x"}):
            for i in range(rate_limit.TRACKING_IP.limit):
                assert self._lookup("203.0.113.5", code=f"C{i}")["statusCode"] == 200
            _assert_limited(self._lookup("203.0.113.5", code="C-next"))
            assert self._lookup("203.0.113.6")["statusCode"] == 200

    def test_wrong_guesses_at_one_code_lock_it_out_from_every_address(self, cache):
        """The phone is the only secret, so guessing it is limited per code, not only per address."""
        from services.tracking import service

        with patch.object(service, "get_shipment_by_code_and_phone", side_effect=ResourceNotFoundError("shipment", "x")):
            for i in range(rate_limit.TRACKING_FAILURES.limit):
                assert self._lookup(f"198.51.100.{i}")["statusCode"] == 404
        with patch.object(service, "get_shipment_by_code_and_phone", return_value={"tracking_code": "x"}) as lookup:
            _assert_limited(self._lookup("198.51.100.200"))  # a fresh address, even with the right phone
            lookup.assert_not_called()

    def test_correct_lookups_are_not_counted_as_failures(self, cache):
        from services.tracking import service

        with patch.object(service, "get_shipment_by_code_and_phone", return_value={"tracking_code": "x"}):
            for i in range(rate_limit.TRACKING_FAILURES.limit + 5):
                self._lookup(f"198.51.100.{i}")
        with patch.object(service, "get_shipment_by_code_and_phone", return_value={"tracking_code": "x"}):
            assert self._lookup("198.51.100.250")["statusCode"] == 200

    def test_another_code_is_not_affected(self, cache):
        from services.tracking import service

        with patch.object(service, "get_shipment_by_code_and_phone", side_effect=ResourceNotFoundError("shipment", "x")):
            for i in range(rate_limit.TRACKING_FAILURES.limit):
                self._lookup(f"198.51.100.{i}", code="TARGET")
        with patch.object(service, "get_shipment_by_code_and_phone", return_value={"tracking_code": "x"}):
            assert self._lookup("198.51.100.99", code="OTHER")["statusCode"] == 200


class TestAuthRoutes:
    def _post(self, path: str, ip: str, body: dict | None = None, cookies: list[str] | None = None) -> dict:
        from services.auth import handler

        event = _event(ip, path=path, body=json.dumps(body) if body is not None else "")
        event["headers"] = dict(BROWSER_HEADERS)
        if cookies:
            event["cookies"] = cookies
        return handler.lambda_handler(event, None)

    def _login(self, ip: str, username: str = "ada@example.test") -> dict:
        return self._post("/v1/auth/login", ip, {"username": username, "password": "pw"})

    @staticmethod
    def _grant(**behaviour):
        refresher = MagicMock()
        refresher.password_grant.configure_mock(**behaviour)
        return patch("services.auth.handler._refresher", return_value=refresher), refresher

    def test_login_is_limited_per_address(self, cache):
        patcher, _ = self._grant(return_value={"id_token": "i", "access_token": "a", "refresh_token": "r", "expires_in": 1})
        with patcher:
            for i in range(rate_limit.LOGIN_IP.limit):
                assert self._login("203.0.113.5", username=f"u{i}@example.test")["statusCode"] == 200
            _assert_limited(self._login("203.0.113.5", username="another@example.test"))

    def test_wrong_passwords_lock_the_username_out_from_every_address(self, cache):
        patcher, refresher = self._grant(side_effect=AuthenticationRequiredError())
        with patcher:
            for i in range(rate_limit.LOGIN_FAILURES.limit):
                assert self._login(f"198.51.100.{i}")["statusCode"] == 401
            calls_so_far = refresher.password_grant.call_count
            _assert_limited(self._login("198.51.100.200"))
            assert refresher.password_grant.call_count == calls_so_far, (
                "a locked-out username is refused before the password is tried"
            )

    def test_a_correct_password_resets_the_count(self, cache):
        patcher, refresher = self._grant(side_effect=AuthenticationRequiredError())
        with patcher:
            for i in range(rate_limit.LOGIN_FAILURES.limit - 1):
                self._login(f"198.51.100.{i}")
            refresher.password_grant.side_effect = None
            refresher.password_grant.return_value = {"id_token": "i", "access_token": "a", "refresh_token": "r", "expires_in": 1}
            assert self._login("198.51.100.100")["statusCode"] == 200
            refresher.password_grant.side_effect = AuthenticationRequiredError()
            for i in range(rate_limit.LOGIN_FAILURES.limit - 1):
                assert self._login(f"198.51.100.{110 + i}")["statusCode"] == 401  # the count started again

    def test_an_identity_provider_outage_is_not_counted_against_the_user(self, cache):
        from shared.exceptions import ExternalServiceError

        patcher, _ = self._grant(side_effect=ExternalServiceError("Entra", "down"))
        with patcher:
            for i in range(rate_limit.LOGIN_FAILURES.limit + 2):
                assert self._login(f"198.51.100.{i}")["statusCode"] == 502

    @pytest.mark.parametrize("path", ["/v1/auth/refresh", "/v1/auth/logout", "/v1/auth/session", "/v1/auth/authorize-url"])
    def test_the_cookie_routes_share_a_per_address_limit(self, cache, path):
        body = {"refresh_token": "x" * 40}
        patcher, _ = self._grant(return_value={})
        with patcher:
            for _ in range(rate_limit.SESSION_IP.limit):
                self._post(path, "203.0.113.5", body)
            _assert_limited(self._post(path, "203.0.113.5", body))
            assert self._post(path, "203.0.113.6", body)["statusCode"] != 429

    def test_a_foreign_origin_is_refused_before_it_is_counted(self, cache):
        """The origin check comes first, so a hostile page cannot use up a real user's budget."""
        from services.auth import handler

        event = _event("203.0.113.5", path="/v1/auth/refresh")
        event["headers"] = {"origin": "https://evil.example"}
        for _ in range(rate_limit.SESSION_IP.limit + 5):
            assert handler.lambda_handler(event, None)["statusCode"] == 403
        assert cache.counts == {}


class TestPerTenantLimit:
    @staticmethod
    def _context(tenant: str, role: str = "tenant_admin"):
        from shared.auth import get_tenant_context

        claims = {"sub": "user-1", "custom:tenant_id": tenant, "cognito:groups": f"{tenant}:{role}"}
        return get_tenant_context(
            {"requestContext": {"authorizer": {"claims": claims}, "http": {"method": "GET", "path": "/v1/x"}}}
        )

    @pytest.fixture(autouse=True)
    def _checks_stubbed(self, monkeypatch):
        monkeypatch.setattr("shared.auth._check_tenant_active", lambda tenant_id: None)

    def test_a_tenant_past_its_limit_is_refused(self, cache):
        tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        for _ in range(rate_limit.TENANT.limit):
            self._context(tenant)
        with pytest.raises(RateLimitExceededError):
            self._context(tenant)

    def test_one_tenants_traffic_cannot_throttle_another(self, cache):
        """The finding's done-when: one tenant's traffic must not throttle another's."""
        busy, quiet = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        for _ in range(rate_limit.TENANT.limit + 50):
            with contextlib.suppress(RateLimitExceededError):
                self._context(busy)
        assert self._context(quiet).tenant_id == quiet

    def test_the_limit_can_be_tuned_for_a_large_tenant(self, cache, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_TENANT", "5/60")
        tenant = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        for _ in range(5):
            self._context(tenant)
        with pytest.raises(RateLimitExceededError):
            self._context(tenant)

    def test_a_platform_admin_is_not_counted_against_any_tenant(self, cache):
        claims = {"sub": "pa-1", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
        from shared.auth import get_tenant_context

        for _ in range(rate_limit.TENANT.limit + 10):
            ctx = get_tenant_context(
                {"requestContext": {"authorizer": {"claims": claims}, "http": {"method": "GET", "path": "/v1/x"}}}
            )
        assert ctx.role == UserRole.PLATFORM_ADMIN
        assert cache.counts == {}

    def test_a_refused_request_for_a_revoked_user_costs_the_tenant_nothing(self, cache, monkeypatch):
        from shared.exceptions import AuthenticationRequiredError as Denied

        def _revoked(user_id, tenant_id):
            raise Denied()

        monkeypatch.setattr("shared.auth._check_user_active", _revoked)
        with pytest.raises(Denied):
            self._context("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        assert cache.counts == {}

    def test_a_redis_outage_does_not_stop_authenticated_requests(self, cache):
        cache.down = True
        assert self._context("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa").role == UserRole.TENANT_ADMIN
