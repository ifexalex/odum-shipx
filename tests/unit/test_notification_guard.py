"""Non-production recipient guard — shared/notifications.py."""

import os
from unittest.mock import patch


def _guard():
    from shared.notifications import is_recipient_allowed

    return is_recipient_allowed


class TestRecipientGuard:
    def test_non_production_with_empty_allowlist_sends_nothing(self):
        """Fails closed. A dev database holds real imported customer numbers,
        so an unset allowlist must suppress everything, not allow everything."""
        with patch.dict(os.environ, {"ENVIRONMENT": "local", "NOTIFICATION_ALLOWLIST": ""}, clear=False):
            assert _guard()({"phone": "+2348031234567"}) is False

    def test_non_production_allows_only_listed_contacts(self):
        env = {"ENVIRONMENT": "local", "NOTIFICATION_ALLOWLIST": "+2348169760253,dev@example.com"}
        with patch.dict(os.environ, env, clear=False):
            allowed = _guard()
            assert allowed({"phone": "+2348169760253"}) is True
            assert allowed({"email": "dev@example.com"}) is True
            # A real customer imported from a manifest must never match.
            assert allowed({"phone": "+2348031234567"}) is False

    def test_matching_is_case_insensitive_and_whitespace_tolerant(self):
        env = {"ENVIRONMENT": "staging", "NOTIFICATION_ALLOWLIST": " Dev@Example.COM "}
        with patch.dict(os.environ, env, clear=False):
            assert _guard()({"email": "dev@example.com"}) is True

    def test_production_always_sends(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "NOTIFICATION_ALLOWLIST": ""}, clear=False):
            assert _guard()({"phone": "+2348031234567"}) is True

    def test_prod_spelling_also_counts_as_production(self):
        """Regression: every tfvars file (AWS + Azure) sets environment = "prod",
        and that value also feeds resource name prefixes so it cannot be renamed.
        Matching only "production" meant the guard could never switch off in any
        deployed environment — silently suppressing every customer notification
        in production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "prod", "NOTIFICATION_ALLOWLIST": ""}, clear=False):
            assert _guard()({"phone": "+2348031234567"}) is True

    def test_prod_spelling_is_case_and_whitespace_tolerant(self):
        with patch.dict(os.environ, {"ENVIRONMENT": " PROD ", "NOTIFICATION_ALLOWLIST": ""}, clear=False):
            assert _guard()({"phone": "+2348031234567"}) is True

    def test_other_environments_still_fail_closed(self):
        """demo/staging/dev are NOT production — they must keep failing closed."""
        for env_name in ("demo", "staging", "dev", "", "productionish"):
            with patch.dict(os.environ, {"ENVIRONMENT": env_name, "NOTIFICATION_ALLOWLIST": ""}, clear=False):
                assert _guard()({"phone": "+2348031234567"}) is False, env_name

    def test_enqueue_returns_early_for_a_blocked_recipient(self):
        from shared import notifications

        with (
            patch.dict(os.environ, {"ENVIRONMENT": "local", "NOTIFICATION_ALLOWLIST": ""}, clear=False),
            patch.object(notifications, "get_queue_provider") as mock_sqs,
        ):
            notifications.enqueue_notifications(
                tenant_id="t-1",
                event_type="customer_invite",
                recipient={"phone": "+2348031234567", "name": "Real Customer"},
                template_data={},
            )
        mock_sqs.assert_not_called()


class TestProviderLevelGuard:
    """Defence in depth: even a direct send_* call cannot reach a real customer."""

    def test_send_whatsapp_refuses_a_non_allowlisted_number(self):
        from services.notification import service

        env = {
            "ENVIRONMENT": "local",
            "NOTIFICATION_ALLOWLIST": "+2348169760253",
            "META_WHATSAPP_PHONE_ID": "123",
            "META_WHATSAPP_ACCESS_TOKEN": "tok",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch("urllib.request.urlopen") as mock_http,
        ):
            # A real customer number imported from a manifest.
            assert service.send_whatsapp("+2348031234567", "t", [], "tenant-1") == ""
        mock_http.assert_not_called()  # no network call was made at all

    def test_send_whatsapp_allows_the_allowlisted_number(self):
        from services.notification import service

        env = {
            "ENVIRONMENT": "local",
            "NOTIFICATION_ALLOWLIST": "+2348169760253",
            "META_WHATSAPP_PHONE_ID": "",
            "META_WHATSAPP_ACCESS_TOKEN": "",
        }
        with patch.dict(os.environ, env, clear=False):
            # Passes the guard, then stops on missing credentials — proving the
            # guard is not what blocked it.
            assert service.send_whatsapp("+2348169760253", "t", [], "tenant-1") == ""

    def test_send_sms_refuses_a_non_allowlisted_number(self):
        from services.notification import service

        env = {"ENVIRONMENT": "local", "NOTIFICATION_ALLOWLIST": "+2348169760253", "AFRICASTALKING_API_KEY": "key"}
        with (
            patch.dict(os.environ, env, clear=False),
            patch("urllib.request.urlopen") as mock_http,
        ):
            assert service.send_sms("+2348031234567", "hello", "tenant-1") is False
        mock_http.assert_not_called()
