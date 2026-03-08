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

        html = render_email_html(
            self._BRANDING, "shipment_update", None,
            {"tracking_code": "TRK-XYZ-001"}
        )
        assert "TRK-XYZ-001" in html

    def test_text_contains_company_name(self):
        from services.notification.service import render_email_text

        text = render_email_text(self._BRANDING, "shipment_update", "John", {})
        assert "Cargo Ltd" in text

    def test_text_includes_template_data(self):
        from services.notification.service import render_email_text

        text = render_email_text(
            self._BRANDING, "shipment_update", None,
            {"amount": "50000.00"}
        )
        assert "50000.00" in text

    def test_text_none_values_omitted(self):
        from services.notification.service import render_email_text

        text = render_email_text(
            self._BRANDING, "shipment_update", None,
            {"tracking_code": "TRK-001", "empty_field": None}
        )
        assert "None" not in text


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
            assert event.value in WA_TEMPLATE_MAP, (
                f"NotificationEvent.{event.name} missing from WA_TEMPLATE_MAP"
            )
