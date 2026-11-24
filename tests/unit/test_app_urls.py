"""Absolute-URL resolution for links sent to people outside the system.

The bug these pin: `CUSTOMER_PORTAL_BASE_URL` was read with an empty default and
set in no environment — not AWS Terraform, not Azure Terraform, not .env.local —
so every customer invite link was the relative path "/invite/<token>", which no
mail or messaging client can open.
"""

from unittest.mock import patch

import pytest

from shared.app_urls import MissingBaseUrlError, activation_url, app_base_url, invite_url

_CLEAR = {"APP_BASE_URL": "", "CUSTOMER_PORTAL_BASE_URL": "", "ENTRA_REDIRECT_URI": ""}


def _env(**kw: str) -> dict[str, str]:
    return {**_CLEAR, **kw}


class TestAppBaseUrl:
    def test_uses_app_base_url(self):
        with patch.dict("os.environ", _env(APP_BASE_URL="https://app.test"), clear=False):
            assert app_base_url() == "https://app.test"

    def test_strips_trailing_slash(self):
        """ "https://app.test//invite/t" is a different path, and some routers 404 it."""
        with patch.dict("os.environ", _env(APP_BASE_URL="https://app.test/"), clear=False):
            assert app_base_url() == "https://app.test"

    def test_falls_back_to_redirect_uri_origin(self):
        with patch.dict("os.environ", _env(ENTRA_REDIRECT_URI="https://fd.test/auth/callback"), clear=False):
            assert app_base_url() == "https://fd.test"

    def test_override_env_wins(self):
        with patch.dict(
            "os.environ",
            _env(APP_BASE_URL="https://staff.test", CUSTOMER_PORTAL_BASE_URL="https://my.test"),
            clear=False,
        ):
            assert app_base_url(override_env="CUSTOMER_PORTAL_BASE_URL") == "https://my.test"

    def test_override_env_unset_falls_through_to_app_base(self):
        with patch.dict("os.environ", _env(APP_BASE_URL="https://staff.test"), clear=False):
            assert app_base_url(override_env="CUSTOMER_PORTAL_BASE_URL") == "https://staff.test"

    def test_nothing_configured_raises(self):
        with patch.dict("os.environ", _env(), clear=False):
            with pytest.raises(MissingBaseUrlError):
                app_base_url()

    def test_relative_value_raises_rather_than_falling_through(self):
        """A variable that is set but relative is a misconfiguration.

        Falling through to the next candidate would silently send links to
        whichever host happened to be configured elsewhere — the failure would
        then be a working link to the wrong environment, which is worse than an
        error because nothing reports it.
        """
        with patch.dict(
            "os.environ",
            _env(CUSTOMER_PORTAL_BASE_URL="/portal", APP_BASE_URL="https://app.test"),
            clear=False,
        ):
            with pytest.raises(MissingBaseUrlError) as exc:
                app_base_url(override_env="CUSTOMER_PORTAL_BASE_URL")
        # The message names the offending variable — the whole point of failing
        # here rather than moving on.
        assert "CUSTOMER_PORTAL_BASE_URL" in str(exc.value)

    def test_scheme_without_host_is_not_absolute(self):
        with patch.dict("os.environ", _env(APP_BASE_URL="https://"), clear=False):
            with pytest.raises(MissingBaseUrlError):
                app_base_url()


class TestLinkBuilders:
    def test_invite_url(self):
        with patch.dict("os.environ", _env(APP_BASE_URL="https://app.test"), clear=False):
            assert invite_url("tok-1") == "https://app.test/invite/tok-1"

    def test_activation_url(self):
        with patch.dict("os.environ", _env(APP_BASE_URL="https://app.test"), clear=False):
            assert activation_url("tok-2") == "https://app.test/activate/tok-2"

    def test_activation_ignores_the_customer_portal_override(self):
        """Staff activation must not follow a separately hosted customer portal."""
        with patch.dict(
            "os.environ",
            _env(APP_BASE_URL="https://staff.test", CUSTOMER_PORTAL_BASE_URL="https://my.test"),
            clear=False,
        ):
            assert activation_url("t") == "https://staff.test/activate/t"
            assert invite_url("t") == "https://my.test/invite/t"

    def test_paths_match_the_frontend_routes(self):
        """Both routes live in frontend/src/shell/routes.tsx: /invite/:token and
        /activate/:token. A link whose path does not match renders the SPA's
        not-found page, which looks identical to a broken link."""
        with patch.dict("os.environ", _env(APP_BASE_URL="https://app.test"), clear=False):
            assert invite_url("t").endswith("/invite/t")
            assert activation_url("t").endswith("/activate/t")
