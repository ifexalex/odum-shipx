"""Unit tests for shared.origin_guard and its use by the cookie endpoints (audit SEC-05).

The attack: where the refresh cookie is sent cross-site, a third-party page can post its own
refresh token to /v1/auth/session (signing the victim's browser into the attacker's account) or
post to /v1/auth/logout (forcing a logout). A page cannot forge the Origin a browser sends, so
the endpoints refuse any request whose Origin is not one of ours.
"""

import json

import pytest

from services.auth import handler
from shared.exceptions import UnsupportedMediaTypeError, UntrustedOriginError
from shared.origin_guard import assert_json_content_type, assert_trusted_origin, trusted_origins
from tests.browser import BROWSER_HEADERS, BROWSER_ORIGIN

_CONFIG_VARS = ("ALLOWED_ORIGINS", "CORS_ALLOW_ORIGINS", "APP_BASE_URL", "CUSTOMER_PORTAL_BASE_URL", "ENTRA_REDIRECT_URI")


@pytest.fixture
def no_origins(monkeypatch):
    """Start from nothing configured, so a test names exactly the origins it trusts."""
    for name in _CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)


def _event(origin: str | None = BROWSER_ORIGIN, content_type: str | None = "application/json") -> dict:
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    if content_type is not None:
        headers["content-type"] = content_type
    return {"headers": headers}


class TestTrustedOrigins:
    def test_nothing_configured_trusts_nothing(self, no_origins):
        assert trusted_origins() == frozenset()

    def test_the_app_url_contributes_its_origin_only(self, no_origins, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://app.shipx.co/some/path/")
        assert trusted_origins() == {"https://app.shipx.co"}

    def test_a_separate_customer_portal_is_trusted_too(self, no_origins, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://app.shipx.co")
        monkeypatch.setenv("CUSTOMER_PORTAL_BASE_URL", "https://my.shipx.co")
        assert trusted_origins() == {"https://app.shipx.co", "https://my.shipx.co"}

    def test_the_entra_redirect_uri_contributes_its_origin(self, no_origins, monkeypatch):
        monkeypatch.setenv("ENTRA_REDIRECT_URI", "https://fd.example.net/auth/callback")
        assert trusted_origins() == {"https://fd.example.net"}

    def test_comma_separated_lists_are_split_and_trimmed(self, no_origins, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", " https://a.shipx.co , https://b.shipx.co/ ,, ")
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://c.shipx.co")
        assert trusted_origins() == {"https://a.shipx.co", "https://b.shipx.co", "https://c.shipx.co"}

    def test_origins_are_lowercased(self, no_origins, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://App.ShipX.co")
        assert trusted_origins() == {"https://app.shipx.co"}

    def test_a_relative_or_junk_value_is_ignored_not_trusted(self, no_origins, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "/portal")
        monkeypatch.setenv("ALLOWED_ORIGINS", "not-a-url, *")
        assert trusted_origins() == frozenset()

    def test_a_port_is_part_of_the_origin(self, no_origins, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
        assert trusted_origins() == {"http://localhost:5173"}


class TestAssertTrustedOrigin:
    @pytest.fixture(autouse=True)
    def _app(self, no_origins, monkeypatch):
        monkeypatch.setenv("APP_BASE_URL", "https://app.shipx.co")

    def test_our_own_origin_passes(self):
        assert_trusted_origin(_event("https://app.shipx.co"))

    def test_the_comparison_ignores_case(self):
        assert_trusted_origin(_event("HTTPS://APP.SHIPX.CO"))

    def test_a_foreign_origin_is_refused(self):
        with pytest.raises(UntrustedOriginError) as exc:
            assert_trusted_origin(_event("https://evil.example"))
        assert exc.value.status_code == 403

    def test_a_missing_origin_is_refused(self):
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin(_event(origin=None))

    def test_a_blank_origin_is_refused(self):
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin(_event(origin="  "))

    def test_the_opaque_null_origin_is_refused(self):
        """Sent by sandboxed iframes and some redirects, so it proves nothing about the caller."""
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin(_event("null"))

    @pytest.mark.parametrize(
        "lookalike",
        [
            "https://app.shipx.co.evil.example",  # our host as a prefix of theirs
            "https://evil-app.shipx.co",  # a different subdomain
            "https://shipx.co",  # the parent domain
            "http://app.shipx.co",  # wrong scheme
            "https://app.shipx.co:8443",  # wrong port
            "https://app.shipx.co@evil.example",  # userinfo trick
            "https://evil.example/https://app.shipx.co",  # ours smuggled into a path
        ],
    )
    def test_lookalike_origins_are_refused(self, lookalike):
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin(_event(lookalike))

    def test_with_nothing_configured_every_request_is_refused(self, monkeypatch):
        """Fail closed: a missing setting must not quietly switch the check off."""
        monkeypatch.delenv("APP_BASE_URL")
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin(_event("https://app.shipx.co"))

    def test_a_request_with_no_headers_at_all_is_refused(self):
        with pytest.raises(UntrustedOriginError):
            assert_trusted_origin({})


class TestAssertJsonContentType:
    @pytest.mark.parametrize(
        "value", ["application/json", "application/json; charset=utf-8", "Application/JSON", " application/json "]
    )
    def test_json_passes(self, value):
        assert_json_content_type(_event(content_type=value))

    @pytest.mark.parametrize(
        "value",
        [
            "text/plain",  # what a cross-site HTML form can send without a preflight
            "application/x-www-form-urlencoded",
            "multipart/form-data; boundary=x",
            "application/jsonp",
            "application/json-patch+json",
            "",
            None,
        ],
    )
    def test_anything_else_is_refused(self, value):
        with pytest.raises(UnsupportedMediaTypeError) as exc:
            assert_json_content_type(_event(content_type=value))
        assert exc.value.status_code == 415


# ---------------------------------------------------------------------------
# The endpoints themselves
# ---------------------------------------------------------------------------

_COOKIE_ROUTES = [
    "/v1/auth/session",
    "/v1/auth/refresh",
    "/v1/auth/logout",
    "/v1/auth/authorize-url",
    "/v1/auth/callback",
]


def _request(path: str, headers: dict | None, body: dict | None = None, cookies: list[str] | None = None) -> dict:
    event: dict = {
        "requestContext": {"requestId": "r1", "http": {"method": "POST", "path": path}},
        "headers": headers if headers is not None else {},
        "cookies": cookies or [],
        "body": json.dumps(body) if body is not None else "",
    }
    return event


class TestCookieEndpointsRefuseForeignRequests:
    @pytest.mark.parametrize("path", _COOKIE_ROUTES)
    def test_a_foreign_origin_gets_403_and_no_cookie(self, path):
        headers = {"origin": "https://evil.example", "content-type": "application/json"}
        resp = handler.lambda_handler(_request(path, headers, {"refresh_token": "x" * 40}), None)

        assert resp["statusCode"] == 403
        assert "cookies" not in resp
        assert json.loads(resp["body"])["error_code"] == "ORIGIN_NOT_ALLOWED"

    @pytest.mark.parametrize("path", _COOKIE_ROUTES)
    def test_a_missing_origin_gets_403_and_no_cookie(self, path):
        resp = handler.lambda_handler(_request(path, {"content-type": "application/json"}, {"refresh_token": "x" * 40}), None)

        assert resp["statusCode"] == 403
        assert "cookies" not in resp

    def test_the_login_hijack_is_closed(self):
        """The finding's scenario: a hostile page posts its own refresh token to /session."""
        headers = {"origin": "https://evil.example", "content-type": "application/json"}
        resp = handler.lambda_handler(
            _request("/v1/auth/session", headers, {"refresh_token": "attacker-token-" + "x" * 30}), None
        )

        assert resp["statusCode"] == 403
        assert "cookies" not in resp, "no Set-Cookie may reach the victim's browser"

    def test_a_forced_logout_is_refused_and_does_not_revoke_the_victims_token(self, monkeypatch):
        revoked: list[str] = []
        monkeypatch.setattr(handler, "_refresher", lambda: type("R", (), {"revoke_refresh_token": staticmethod(revoked.append)}))

        headers = {"origin": "https://evil.example"}
        resp = handler.lambda_handler(_request("/v1/auth/logout", headers, cookies=["shipx_rt=" + "v" * 40]), None)

        assert resp["statusCode"] == 403
        assert revoked == []

    @pytest.mark.parametrize("path", ["/v1/auth/session", "/v1/auth/callback", "/v1/auth/authorize-url"])
    def test_a_text_plain_body_is_refused_even_from_our_own_origin(self, path):
        """A cross-site form can post text/plain without a preflight; these routes parse the body as JSON regardless."""
        headers = {"origin": BROWSER_ORIGIN, "content-type": "text/plain"}
        resp = handler.lambda_handler(_request(path, headers, {"refresh_token": "x" * 40}), None)

        assert resp["statusCode"] == 415
        assert "cookies" not in resp

    @pytest.mark.parametrize("path", ["/v1/auth/refresh", "/v1/auth/logout"])
    def test_bodiless_routes_need_no_content_type(self, path, monkeypatch):
        """The SPA sends these with no Content-Type; the Origin check is what protects them."""
        monkeypatch.setattr(
            handler,
            "_refresher",
            lambda: type(
                "R",
                (),
                {
                    "revoke_refresh_token": staticmethod(lambda token, **_: None),
                    "refresh_id_token": staticmethod(lambda token, **_: {"id_token": "a.b.c", "expires_in": 3600}),
                },
            ),
        )
        resp = handler.lambda_handler(_request(path, {"origin": BROWSER_ORIGIN}, cookies=["shipx_rt=" + "r" * 40]), None)

        assert resp["statusCode"] in (200, 204)

    def test_our_own_frontend_still_works(self):
        resp = handler.lambda_handler(_request("/v1/auth/session", dict(BROWSER_HEADERS), {"refresh_token": "x" * 40}), None)

        assert resp["statusCode"] == 204
        assert resp["cookies"], "the session cookie is set for a trusted origin"

    def test_login_carries_no_cookie_and_is_not_origin_gated(self, monkeypatch):
        """/login takes credentials in the body and sets no cookie; it is rate-limited, not origin-checked."""
        monkeypatch.setattr(
            handler,
            "_refresher",
            lambda: type(
                "R",
                (),
                {
                    "password_grant": staticmethod(
                        lambda u, p: {"id_token": "i", "access_token": "a", "refresh_token": "r", "expires_in": 1}
                    )
                },
            ),
        )
        event = _request("/v1/auth/login", {}, {"username": "a@example.test", "password": "pw"})
        assert handler.lambda_handler(event, None)["statusCode"] == 200
