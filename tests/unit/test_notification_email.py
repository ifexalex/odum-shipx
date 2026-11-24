"""Tenant branding and email rendering for outbound notifications.

The bug these pin: `get_company_name` read `branding.get("company_name")`, but
the canonical `branding_config` shape (written by `PUT /v1/tenant/config
{branding}`) has **`display_name`** — `company_name` lives on the `tenant` row,
which the producer never selected. Acme's `branding_config` is `{}` outright. So
every email header, every `{company_name}:` SMS prefix and every WhatsApp
parameter was the literal word "Logistics".
"""

from unittest.mock import MagicMock, patch

from services.notification import service
from services.notification.tenant_branding import get_company_name, get_primary_color

_TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

_BRANDING = {
    "company_name": "Acme Shipping Ltd",
    "display_name": "Acme Cargo",
    "primary_color": "#0A6E4A",
    "tagline": "China to Nigeria, on time",
    "support_email": "help@acme.test",
    "support_whatsapp": "+2348000000000",
    "document_footer": "Acme Shipping Ltd · RC 123456",
}


class TestCompanyName:
    def test_display_name_wins(self):
        """A tenant that set a trading name meant customers to see it."""
        assert get_company_name(_BRANDING) == "Acme Cargo"

    def test_falls_back_to_the_tenant_rows_company_name(self):
        """The common case: branding_config is `{}` and only the producer's
        `company_name` is present. This used to yield "Logistics"."""
        assert get_company_name({"company_name": "Acme Shipping Ltd"}) == "Acme Shipping Ltd"

    def test_blank_values_are_not_treated_as_set(self):
        assert get_company_name({"display_name": "   ", "company_name": "Acme Shipping Ltd"}) == "Acme Shipping Ltd"

    def test_last_resort_fallback(self):
        """Only reachable if the tenant row had no company name, which the
        NOT NULL constraint on `tenant.company_name` should prevent."""
        assert get_company_name({}) == "Logistics"

    def test_primary_color_default(self):
        assert get_primary_color({}) == "#1A5276"
        assert get_primary_color(_BRANDING) == "#0A6E4A"


class TestProducerEmbedsCompanyName:
    def test_company_name_is_selected_and_embedded(self):
        """The consumer Lambdas run outside the VPC with no DB access, so the
        name has to travel in the message. The query used to select only
        `branding_config`."""
        from shared import notifications

        rows = [{"company_name": "Acme Shipping Ltd", "branding_config": {}}]
        with patch.object(notifications, "execute_with_tenant", return_value=rows) as mock_q:
            branding = notifications._tenant_branding(_TENANT)

        assert branding["company_name"] == "Acme Shipping Ltd"
        assert "company_name" in mock_q.call_args.kwargs["query"]

    def test_display_name_is_not_overwritten(self):
        from shared import notifications

        rows = [{"company_name": "Acme Shipping Ltd", "branding_config": {"display_name": "Acme Cargo"}}]
        with patch.object(notifications, "execute_with_tenant", return_value=rows):
            branding = notifications._tenant_branding(_TENANT)

        assert branding["display_name"] == "Acme Cargo"
        assert branding["company_name"] == "Acme Shipping Ltd"

    def test_db_failure_degrades_to_defaults_rather_than_raising(self):
        """Notifications are best-effort everywhere else in this codebase."""
        from shared import notifications

        with patch.object(notifications, "execute_with_tenant", side_effect=RuntimeError("no db")):
            assert notifications._tenant_branding(_TENANT) == {}


class TestRenderEmailHtml:
    def _html(self, event: str = "customer_invite", **data) -> str:
        return service.render_email_html(_BRANDING, event, "Ngozi", {"name": "Ngozi", **data})

    def test_header_carries_the_tenants_name_and_colour(self):
        html = self._html()
        assert "Acme Cargo" in html
        assert "#0A6E4A" in html
        assert "Logistics" not in html

    def test_tagline_rendered_when_set(self):
        assert "China to Nigeria, on time" in self._html()

    def test_body_explains_why_the_message_arrived(self):
        """Email used to be a greeting, a button and the single row
        "Name: Ngozi" — nothing saying what it was about."""
        html = self._html(invite_link="https://app.test/invite/t")
        assert "created an account for you" in html
        assert "expires in 48 hours" in html

    def test_link_becomes_a_button_and_a_pasteable_url(self):
        html = self._html(invite_link="https://app.test/invite/t")
        assert 'href="https://app.test/invite/t"' in html
        assert "Create your account" in html
        # Some clients strip or mangle styled anchors.
        assert "Or paste this link into your browser" in html

    def test_support_contacts_rendered_when_published(self):
        html = self._html()
        assert "help@acme.test" in html
        assert "+2348000000000" in html

    def test_support_block_omitted_when_tenant_published_none(self):
        html = service.render_email_html({"company_name": "Acme"}, "customer_invite", "N", {"name": "N"})
        assert "Need help?" not in html

    def test_document_footer_rendered(self):
        assert "RC 123456" in self._html()

    def test_values_are_html_escaped(self):
        """Values come from customer records and imported manifests, and were
        previously interpolated raw — so a name containing markup could alter
        a message sent under the tenant's name."""
        html = service.render_email_html(_BRANDING, "shipment_update", "<script>x</script>", {"container_number": '"><b>hi</b>'})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "<b>hi</b>" not in html

    def test_plumbing_fields_are_not_shown_as_rows(self):
        html = self._html(invite_link="https://app.test/invite/t")
        # `name` is already in the greeting; `company_name` is the header.
        assert ">Name<" not in html
        assert ">Company name<" not in html

    def test_detail_rows_get_readable_labels(self):
        html = self._html("shipment_update", container_number="ACME001")
        assert "Container number" in html
        assert "ACME001" in html

    def test_unknown_event_falls_back_to_generic_copy(self):
        html = service.render_email_html(_BRANDING, "no_such_event", "N", {"foo": "bar"})
        assert "You have a new notification" in html

    def test_unresolved_placeholder_falls_back_to_generic_copy(self):
        """A half-substituted sentence reads as a bug to the recipient. The
        generic lead plus the details table is always accurate."""
        with patch.dict(service._EMAIL_BODIES, {"customer_invite": "Hello {missing_key} from {company_name}"}):
            html = service.render_email_html(_BRANDING, "customer_invite", "N", {"name": "N"})
        assert "{missing_key}" not in html
        assert "You have a new notification" in html

    def test_zh_locale_renders_chinese_copy(self):
        html = service.render_email_html(
            _BRANDING, "customer_invite", "李伟", {"name": "李伟", "invite_link": "https://app.test/invite/t"}, "zh"
        )
        assert "已为您创建账户" in html
        assert "创建账户" in html
        assert "created an account for you" not in html


class TestRenderEmailText:
    def test_carries_the_same_prose_and_link_as_the_html_part(self):
        """A text-only client previously received an unexplained list of field
        names with no explanation and no link label."""
        text = service.render_email_text(
            _BRANDING, "customer_invite", "Ngozi", {"name": "Ngozi", "invite_link": "https://app.test/invite/t"}
        )
        assert "created an account for you" in text
        assert "https://app.test/invite/t" in text
        assert "Acme Cargo" in text

    def test_support_contacts_included(self):
        text = service.render_email_text(_BRANDING, "customer_invite", "N", {"name": "N"})
        assert "help@acme.test" in text

    def test_derived_from_the_override_when_one_is_set(self):
        """Otherwise the two MIME parts of one message disagree about what was
        sent — the HTML part the tenant wrote, the text part the default."""
        text = service.render_email_text(
            _BRANDING,
            "customer_invite",
            "N",
            {"name": "N", "invite_link": "https://app.test/invite/t"},
            body_override="<p>Welcome {name}</p><p>Go to {invite_link}</p>",
        )
        assert "Welcome N" in text
        assert "https://app.test/invite/t" in text
        assert "<p>" not in text


class TestEmailSubject:
    def test_prefixed_with_the_company_name(self):
        """A bare "Create your account to track your shipment" in an inbox
        tells the recipient nothing about who is writing."""
        subject = service.email_subject("customer_invite", _BRANDING, {})
        assert subject.startswith("Acme Cargo")
        assert "Create your account" in subject

    def test_zh_subject(self):
        assert "创建账户" in service.email_subject("customer_invite", _BRANDING, {}, None, "zh")

    def test_override_is_used_verbatim_but_substituted(self):
        subject = service.email_subject(
            "customer_invite", _BRANDING, {"container_number": "ACME001"}, "Your container {container_number}"
        )
        assert subject == "Your container ACME001"

    def test_malformed_override_is_still_sent(self):
        subject = service.email_subject("customer_invite", _BRANDING, {}, "Broken {")
        assert subject == "Broken {"


class TestRenderEmailOverride:
    def test_placeholders_are_substituted(self):
        """A tenant's custom body was previously used as-is, so the link
        arrived as the literal twelve characters "{invite_link}"."""
        out = service.render_email_override(
            "<p>Hi {name}, click <a href='{invite_link}'>here</a></p>",
            _BRANDING,
            {"name": "Ngozi", "invite_link": "https://app.test/invite/t"},
        )
        assert "Hi Ngozi" in out
        assert "https://app.test/invite/t" in out
        assert "{invite_link}" not in out

    def test_tenant_markup_is_kept_but_values_escaped(self):
        out = service.render_email_override("<p><b>{name}</b></p>", _BRANDING, {"name": "<script>x</script>"})
        assert "<b>" in out
        assert "<script>" not in out

    def test_malformed_template_returns_empty_so_the_caller_can_fall_back(self):
        assert service.render_email_override("<p>{", _BRANDING, {}) == ""


class TestProductionConfigGuards:
    """Config mistakes that otherwise look like transient provider faults."""

    def test_placeholder_sender_refused_in_production(self):
        with (
            patch.dict("os.environ", {"SES_FROM_ADDRESS": "", "ENVIRONMENT": "prod"}, clear=False),
            patch.object(service, "_assert_deliverable", return_value=True),
            patch("services.notification.service.get_email_provider") as provider,
        ):
            assert service.send_email("a@b.test", "A", "s", "<p>h</p>", "t", _TENANT) is False
        provider.assert_not_called()

    def test_placeholder_sender_allowed_outside_production(self):
        """Local and dev use Moto, which accepts whatever has been verified."""
        sender = MagicMock()
        with (
            patch.dict("os.environ", {"SES_FROM_ADDRESS": "", "ENVIRONMENT": "local"}, clear=False),
            patch.object(service, "_assert_deliverable", return_value=True),
            patch("services.notification.service.get_email_provider", return_value=sender),
        ):
            assert service.send_email("a@b.test", "A", "s", "<p>h</p>", "t", _TENANT) is True
        sender.send.assert_called_once()

    def test_sandbox_sms_username_refused_in_production(self):
        """Africa's Talking accepts sandbox traffic and delivers none of it,
        with a success-shaped response."""
        with (
            patch.dict(
                "os.environ",
                {"AFRICASTALKING_API_KEY": "key", "AFRICASTALKING_USERNAME": "sandbox", "ENVIRONMENT": "prod"},
                clear=False,
            ),
            patch.object(service, "_assert_deliverable", return_value=True),
            patch("urllib.request.urlopen") as urlopen,
        ):
            assert service.send_sms("+2348000000000", "hi", _TENANT) is False
        urlopen.assert_not_called()

    def test_missing_sms_key_returns_false(self):
        with (
            patch.dict("os.environ", {"AFRICASTALKING_API_KEY": ""}, clear=False),
            patch.object(service, "_assert_deliverable", return_value=True),
        ):
            assert service.send_sms("+2348000000000", "hi", _TENANT) is False

    def test_provider_error_bodies_are_stripped_of_phone_numbers(self):
        """Africa's Talking echoes the recipient MSISDN in its error payloads,
        and a phone number must never reach CloudWatch."""
        redacted = service._redact_provider_error('{"error":"bad number +2348169760253 rejected"}')
        assert "2348169760253" not in redacted
        assert "[redacted]" in redacted

    def test_provider_error_bodies_are_truncated(self):
        assert len(service._redact_provider_error("x" * 5000)) <= 400
