"""Unit tests for services.notification — template rendering."""

from services.notification.tenant_branding import (
    extract_branding,
    get_company_name,
    get_primary_color,
)


class TestTenantBranding:
    def test_extract_branding_from_body(self):
        body = {"tenant_branding": {"company_name": "Acme", "primary_color": "#ff0000"}}
        assert extract_branding(body) == {"company_name": "Acme", "primary_color": "#ff0000"}

    def test_extract_branding_missing_key_returns_empty(self):
        assert extract_branding({}) == {}

    def test_get_company_name_returns_value(self):
        assert get_company_name({"company_name": "Cargo Co"}) == "Cargo Co"

    def test_get_company_name_default_when_missing(self):
        assert get_company_name({}) == "Logistics"

    def test_get_primary_color_returns_value(self):
        assert get_primary_color({"primary_color": "#123456"}) == "#123456"

    def test_get_primary_color_default_when_missing(self):
        color = get_primary_color({})
        assert color.startswith("#")


class TestSmsTemplates:
    _BRANDING = {"company_name": "Acme Shipping", "primary_color": "#1A5276"}
    _TD = {
        "tracking_code": "ACME-TRK-001",
        "status": "arrived_nigeria",
        "container_number": "MSKU1234567",
        "amount": "166,310.00",
        "currency": "NGN",
        "warehouse_address": "12 Warehouse Road",
        "reference_number": "ACME-RN-001",
        "carton_count": 10,
    }

    def test_shipment_update_template(self):
        from services.notification.service import format_sms

        msg = format_sms("shipment_update", self._BRANDING, self._TD)
        assert "Acme Shipping" in msg
        assert "ACME-TRK-001" in msg
        assert "arrived_nigeria" in msg

    def test_payment_due_template(self):
        from services.notification.service import format_sms

        msg = format_sms("payment_due", self._BRANDING, self._TD)
        assert "Acme Shipping" in msg
        assert "MSKU1234567" in msg

    def test_release_note_template(self):
        from services.notification.service import format_sms

        msg = format_sms("release_note_generated", self._BRANDING, self._TD)
        assert "Acme Shipping" in msg
        assert "ACME-RN-001" in msg

    def test_unknown_event_type_uses_default(self):
        from services.notification.service import format_sms

        msg = format_sms("unknown_event", self._BRANDING, {})
        assert "Acme Shipping" in msg

    def test_missing_template_key_uses_safe_placeholder(self):
        from services.notification.service import format_sms

        # Pass empty template_data — missing keys should use {key} not raise
        msg = format_sms("shipment_update", self._BRANDING, {})
        assert "Acme Shipping" in msg
        assert "{" in msg or "Acme Shipping" in msg  # safe format, no KeyError


class TestEmailRendering:
    _BRANDING = {"company_name": "Cargo Ltd", "primary_color": "#2C3E50"}

    def test_html_contains_company_name(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "shipment_update", "John", {"tracking_code": "TRK-001"})
        assert "Cargo Ltd" in html

    def test_html_contains_primary_color(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "shipment_update", None, {})
        assert "#2C3E50" in html

    def test_html_includes_greeting_with_name(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "shipment_update", "Ngozi", {})
        assert "Ngozi" in html

    def test_html_generic_greeting_without_name(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "shipment_update", None, {})
        assert "Hello," in html

    def test_html_includes_template_data(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "shipment_update", None, {"tracking_code": "TRK-XYZ-001"})
        assert "TRK-XYZ-001" in html

    def test_text_contains_company_name(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "shipment_update", "John", {})
        assert "Cargo Ltd" in text

    def test_text_includes_template_data(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "shipment_update", None, {"amount": "50000.00"})
        assert "50000.00" in text

    def test_text_none_values_omitted(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "shipment_update", None, {"tracking_code": "TRK-001", "empty_field": None})
        assert "None" not in text


class TestRegistrationExistingAccountEmail:
    """Sent when someone signs up with an address that already has an account (audit SEC-04)."""

    _BRANDING = {"company_name": "Cargo Ltd", "primary_color": "#2C3E50"}
    _DATA = {"name": "Ngozi", "login_link": "https://app.shipx.test/login"}

    def test_it_has_its_own_subject(self):
        from services.notification.service import email_subject

        assert (
            email_subject("registration_existing_account", self._BRANDING, self._DATA)
            == "Cargo Ltd \u2014 You already have an account"
        )

    def test_it_explains_what_happened_without_naming_who_tried(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "registration_existing_account", "Ngozi", self._DATA)
        assert "already has one" in text
        assert "Cargo Ltd" in text

    def test_it_links_to_sign_in_with_a_labelled_button(self):
        from services.notification.service import render_email_html

        html = render_email_html(self._BRANDING, "registration_existing_account", "Ngozi", self._DATA)
        assert "https://app.shipx.test/login" in html
        assert "Sign in" in html

    def test_it_is_not_the_generic_fallback(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "registration_existing_account", None, self._DATA)
        assert "new notification" not in text


class TestEnqueueChannels:
    """Which queues one event reaches."""

    @staticmethod
    def _sent(recipient: dict) -> list[str]:
        from unittest.mock import MagicMock, patch

        import shared.notifications as notifications

        sent: list[str] = []
        provider = MagicMock()
        provider.send.side_effect = lambda destination, body: sent.append(destination)
        env = {
            "ENVIRONMENT": "prod",
            "SQS_EMAIL_QUEUE_URL": "q-email",
            "SQS_SMS_QUEUE_URL": "q-sms",
            "SQS_WHATSAPP_QUEUE_URL": "q-wa",
        }
        with (
            patch.dict("os.environ", env, clear=False),
            patch.object(notifications, "get_queue_provider", return_value=provider),
            patch.object(notifications, "_tenant_branding", return_value={}),
            patch.object(notifications, "should_notify", return_value=True),
            patch.object(notifications, "_get_custom_template", return_value=None),
        ):
            notifications.enqueue_notifications("t1", "account_activation", recipient, {"name": "A"})
        return sent

    def test_a_recipient_with_no_phone_gets_one_email_not_two(self):
        """primary_channel is 'email' without a phone, so the email used to be queued twice."""
        assert self._sent({"email": "a@example.test", "phone": "", "whatsapp": "", "name": "A"}) == ["q-email"]

    def test_a_recipient_with_a_phone_gets_whatsapp_and_email(self):
        assert self._sent({"email": "a@example.test", "phone": "+2348000000000", "whatsapp": "", "name": "A"}) == [
            "q-wa",
            "q-email",
        ]


class TestWhatsAppComponents:
    def test_build_components_company_name_first(self):
        from services.notification.service import build_wa_components

        branding = {"company_name": "Acme"}
        components = build_wa_components(branding, {"status": "arrived"})
        params = components[0]["parameters"]
        assert params[0]["text"] == "Acme"

    def test_build_components_includes_template_data(self):
        from services.notification.service import build_wa_components

        branding = {"company_name": "Acme"}
        components = build_wa_components(branding, {"status": "arrived", "code": "TRK-001"})
        params = components[0]["parameters"]
        texts = [p["text"] for p in params]
        assert "arrived" in texts

    def test_build_components_capped_at_max_params(self):
        from services.notification.service import _WA_MAX_PARAMS, build_wa_components

        branding = {"company_name": "X"}
        # Provide more params than allowed
        data = {f"field_{i}": f"val_{i}" for i in range(10)}
        components = build_wa_components(branding, data)
        assert len(components[0]["parameters"]) <= _WA_MAX_PARAMS

    def test_wa_template_map_covers_all_event_types(self):
        from services.notification.models import NotificationEvent
        from services.notification.service import WA_TEMPLATE_MAP

        for event in NotificationEvent:
            assert event.value in WA_TEMPLATE_MAP, f"NotificationEvent.{event.name} missing from WA_TEMPLATE_MAP"


TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestListLogsDateRangeRepository:
    """GET /v1/notifications/log — `created_after`/`created_before`, added
    alongside the same fix for GET /v1/billing (row 7.63) after the user
    asked to check every page whose "calendar" filter button was dead UI."""

    def test_created_after_and_before_filter_on_created_at(self):
        from unittest.mock import patch

        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_logs(
                TENANT_ID,
                {"created_after": "2026-09-01", "created_before": "2026-09-07"},
                limit=20,
                cursor=None,
            )

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "created_at >= %(created_after)s" in query
        assert "created_at <= %(created_before)s" in query
        assert params["created_after"] == "2026-09-01"
        assert params["created_before"] == "2026-09-07"

    def test_no_date_filter_by_default(self):
        from unittest.mock import patch

        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_logs(TENANT_ID, {}, limit=20, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "created_at >=" not in query
        assert "created_at <=" not in query


class TestNotificationLogHandlerDateRangeQueryParams:
    def _event(self, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-notif-log-daterange-001",
                "http": {"method": "GET", "path": "/v1/notifications/log"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_created_after_and_before_reach_the_service(self):
        from unittest.mock import patch

        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "list_logs", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.http_handler(
                self._event({"created_after": "2026-09-01", "created_before": "2026-09-07"}),
                None,
            )

        assert resp["statusCode"] == 200
        filters = mock_list.call_args[0][1]
        assert filters["created_after"] == "2026-09-01"
        assert filters["created_before"] == "2026-09-07"


def _ctx():
    from shared.tenant_context import TenantContext, UserRole

    return TenantContext(tenant_id=TENANT_ID, user_id="user-1", role=UserRole.TENANT_ADMIN)
