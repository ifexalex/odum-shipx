"""WhatsApp-first delivery with SMS fallback."""

import os
from unittest.mock import patch

import pytest

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_ENV = {
    "ENVIRONMENT": "production",  # bypass the non-prod recipient guard
    "SQS_SMS_QUEUE_URL": "http://q/sms",
    "SQS_WHATSAPP_QUEUE_URL": "http://q/whatsapp",
    "SQS_EMAIL_QUEUE_URL": "http://q/email",
}


def _queued_channels(mock_sqs) -> list[str]:
    import json

    return [json.loads(c.kwargs["body"])["channel"] for c in mock_sqs.return_value.send.call_args_list]


class TestWhatsAppFirstRouting:
    def test_phone_contact_goes_to_whatsapp_not_sms(self):
        from shared import notifications

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch.object(notifications, "should_notify", return_value=True),
            patch.object(notifications, "_get_custom_template", return_value=None),
            patch.object(notifications, "execute_with_tenant", return_value=[]),
            patch.object(notifications, "get_queue_provider") as mock_sqs,
        ):
            notifications.enqueue_notifications(
                TENANT_ID,
                "customer_invite",
                {"phone": "+2348031234567", "email": "a@b.com", "name": "X"},
                {},
            )
        channels = _queued_channels(mock_sqs)
        # SMS must not be sent up-front — it is the fallback, not a parallel send.
        assert "whatsapp" in channels
        assert "sms" not in channels
        assert "email" in channels  # a different medium, still parallel

    def test_falls_back_to_sms_when_whatsapp_cannot_be_attempted(self):
        """No WhatsApp queue configured — SMS is queued immediately instead,
        because there is no WhatsApp send that could later fail."""
        from shared import notifications

        env = {**_ENV, "SQS_WHATSAPP_QUEUE_URL": ""}
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(notifications, "should_notify", return_value=True),
            patch.object(notifications, "_get_custom_template", return_value=None),
            patch.object(notifications, "execute_with_tenant", return_value=[]),
            patch.object(notifications, "get_queue_provider") as mock_sqs,
        ):
            notifications.enqueue_notifications(
                TENANT_ID,
                "customer_invite",
                {"phone": "+2348031234567", "name": "X"},
                {},
            )
        assert "sms" in _queued_channels(mock_sqs)

    def test_whatsapp_muted_by_tenant_falls_back_to_sms(self):
        from shared import notifications

        def _only_whatsapp_muted(_tenant, _event, channel):
            return channel != "whatsapp"

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch.object(notifications, "should_notify", side_effect=_only_whatsapp_muted),
            patch.object(notifications, "_get_custom_template", return_value=None),
            patch.object(notifications, "execute_with_tenant", return_value=[]),
            patch.object(notifications, "get_queue_provider") as mock_sqs,
        ):
            notifications.enqueue_notifications(
                TENANT_ID,
                "customer_invite",
                {"phone": "+2348031234567", "name": "X"},
                {},
            )
        channels = _queued_channels(mock_sqs)
        assert "sms" in channels and "whatsapp" not in channels


class TestSmsFallback:
    def _log_row(self):
        return {
            "id": "log-wa-1",
            "event_type": "customer_invite",
            "customer_id": "cust-1",
            "recipient_name": "X",
            "template_data": {},
            "locale": "en",
        }

    def test_queues_sms_for_an_undelivered_whatsapp(self):
        from services.notification import service

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch("services.notification.repository.get_log_for_fallback", return_value=self._log_row()),
            patch("services.notification.repository.fallback_already_sent", return_value=False),
            patch("services.notification.repository.get_customer_phone", return_value="+2348031234567"),
            patch("services.notification.service.get_queue_provider") as mock_sqs,
        ):
            assert service.trigger_sms_fallback(TENANT_ID, "log-wa-1", "whatsapp_undelivered") is True
        import json

        body = json.loads(mock_sqs.return_value.send.call_args.kwargs["body"])
        assert body["channel"] == "sms"
        # retry_of links the SMS to the WhatsApp row it replaces — this is the
        # double-send guard's key.
        assert body["_retry_of_log_id"] == "log-wa-1"

    def test_does_not_send_twice_when_both_paths_fire(self):
        """The consumer's rejection path and the delivery webhook can both fire
        for one message; the customer must not get two texts."""
        from services.notification import service

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch("services.notification.repository.get_log_for_fallback", return_value=self._log_row()),
            patch("services.notification.repository.fallback_already_sent", return_value=True),
            patch("services.notification.repository.get_customer_phone", return_value="+2348031234567"),
            patch("services.notification.service.get_queue_provider") as mock_sqs,
        ):
            assert service.trigger_sms_fallback(TENANT_ID, "log-wa-1", "whatsapp_rejected") is False
        mock_sqs.return_value.send.assert_not_called()

    def test_fallback_still_respects_the_non_production_guard(self):
        from services.notification import service

        env = {**_ENV, "ENVIRONMENT": "local", "NOTIFICATION_ALLOWLIST": ""}
        with (
            patch.dict(os.environ, env, clear=False),
            patch("services.notification.repository.get_log_for_fallback", return_value=self._log_row()),
            patch("services.notification.repository.fallback_already_sent", return_value=False),
            patch("services.notification.repository.get_customer_phone", return_value="+2348031234567"),
            patch("services.notification.service.get_queue_provider") as mock_sqs,
        ):
            assert service.trigger_sms_fallback(TENANT_ID, "log-wa-1", "whatsapp_rejected") is False
        mock_sqs.return_value.send.assert_not_called()

    def test_no_phone_on_the_customer_is_handled_quietly(self):
        from services.notification import service

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch("services.notification.repository.get_log_for_fallback", return_value=self._log_row()),
            patch("services.notification.repository.fallback_already_sent", return_value=False),
            patch("services.notification.repository.get_customer_phone", return_value=None),
            patch("services.notification.service.get_queue_provider") as mock_sqs,
        ):
            assert service.trigger_sms_fallback(TENANT_ID, "log-wa-1", "whatsapp_rejected") is False
        mock_sqs.return_value.send.assert_not_called()


class TestUnconfiguredWhatsAppIsNotReportedAsSent:
    """`send_whatsapp` returns "" without raising when the Meta credentials are
    missing or the recipient is suppressed.

    That used to fall straight through to `log_sent` + `record_usage`, so: the
    log said "sent" when nothing was sent, the tenant was metered for a message
    that never left, and — because no exception was raised — the SMS fallback
    never fired, so the customer got nothing on either channel while the
    staff-facing invite screen reported success.
    """

    def _body(self):
        return {
            "tenant_id": TENANT_ID,
            "event_type": "customer_invite",
            "recipient": {"phone": "+2348031234567", "name": "Ngozi"},
            "template_data": {"name": "Ngozi", "invite_link": "https://app.test/invite/t"},
            "tenant_branding": {"company_name": "Acme Shipping Ltd"},
            "locale": "en",
        }

    def test_logs_failed_and_falls_back_to_sms(self):
        from services.notification import handler

        with (
            patch.object(handler.service, "send_whatsapp", return_value=""),
            patch.object(handler.service, "log_queued", return_value="log-wa-9"),
            patch.object(handler.service, "log_sent") as log_sent,
            patch.object(handler.service, "log_failed") as log_failed,
            patch.object(handler.service, "trigger_sms_fallback", return_value=True) as fallback,
            patch.object(handler, "record_usage") as usage,
        ):
            handler._process_whatsapp(self._body())

        log_sent.assert_not_called()
        usage.assert_not_called()
        log_failed.assert_called_once()
        assert "unconfigured" in log_failed.call_args[0][2] or "not sent" in log_failed.call_args[0][2]
        fallback.assert_called_once()
        assert fallback.call_args[0][2] == "whatsapp_unconfigured"

    def test_a_real_message_id_still_records_a_send(self):
        from services.notification import handler

        with (
            patch.object(handler.service, "send_whatsapp", return_value="wamid.ABC"),
            patch.object(handler.service, "log_queued", return_value="log-wa-10"),
            patch.object(handler.service, "log_sent") as log_sent,
            patch.object(handler.service, "log_failed") as log_failed,
            patch.object(handler.service, "trigger_sms_fallback") as fallback,
            patch.object(handler, "record_usage") as usage,
        ):
            handler._process_whatsapp(self._body())

        log_sent.assert_called_once()
        assert log_sent.call_args[0][3] == "wamid.ABC"
        usage.assert_called_once()
        log_failed.assert_not_called()
        fallback.assert_not_called()

    def test_a_failing_fallback_does_not_mask_the_original_outcome(self):
        from services.notification import handler

        with (
            patch.object(handler.service, "send_whatsapp", return_value=""),
            patch.object(handler.service, "log_queued", return_value="log-wa-11"),
            patch.object(handler.service, "log_failed") as log_failed,
            patch.object(handler.service, "trigger_sms_fallback", side_effect=RuntimeError("queue down")),
            patch.object(handler, "record_usage"),
        ):
            # Must not raise: an SQS retry would re-send the WhatsApp message
            # that is already known to be unsendable.
            handler._process_whatsapp(self._body())

        log_failed.assert_called_once()


class TestWhatsAppTemplateLanguage:
    """Meta templates are approved per language and the request must match."""

    def test_english_maps_to_the_configured_default_not_bare_en(self):
        from services.notification import service

        # Regression: the code hardcoded "en", so Meta's own en_US templates
        # returned 132001 "Template name does not exist in the translation".
        assert service.wa_language_code("en") == "en_US"
        assert service.wa_language_code(None) == "en_US"

    def test_chinese_maps_to_zh_cn(self):
        from services.notification import service

        # WA_TEMPLATE_MAP_ZH existed but was unreachable while the language
        # code was pinned to English.
        assert service.wa_language_code("zh") == "zh_CN"

    def test_language_code_is_sent_in_the_payload(self):
        import json

        from services.notification import service

        env = {"ENVIRONMENT": "production", "META_WHATSAPP_PHONE_ID": "123", "META_WHATSAPP_ACCESS_TOKEN": "tok"}
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps({"messages": [{"id": "wamid.TEST"}]}).encode()

        def _fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _Resp()

        with (
            patch.dict(os.environ, env, clear=False),
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            mid = service.send_whatsapp("+2348169760253", "hello_world", [], "t-1", "zh_CN")

        assert mid == "wamid.TEST"  # Meta's id is returned, not discarded
        assert captured["body"]["template"]["language"]["code"] == "zh_CN"


class TestTemplateParameterMapping:
    """Parameters are a property of the template, not of caller dict order."""

    def _texts(self, components):
        return [p["text"] for p in components[0]["parameters"]]

    def test_declared_order_wins_over_dict_insertion_order(self):
        from services.notification import service

        branding = {"company_name": "Acme Shipping Ltd"}
        # Keys deliberately in the "wrong" order — the template still gets
        # name then invite_link, because that is what customer_invite declares.
        data = {"invite_link": "https://x/i/abc", "name": "Ify"}
        texts = self._texts(service.build_wa_components(branding, data, "customer_invite"))
        assert texts == ["Acme Shipping Ltd", "Ify", "https://x/i/abc"]

    def test_an_extra_key_does_not_change_the_parameter_count(self):
        """Regression: an added template_data key used to shift the count and
        make Meta reject the send with 132000, breaking WhatsApp only."""
        from services.notification import service

        branding = {"company_name": "Acme"}
        base = service.build_wa_components(branding, {"name": "Ify", "invite_link": "L"}, "customer_invite")
        extended = service.build_wa_components(
            branding, {"name": "Ify", "invite_link": "L", "debug_flag": "x"}, "customer_invite"
        )
        assert len(base[0]["parameters"]) == len(extended[0]["parameters"]) == 3

    def test_a_missing_key_becomes_blank_rather_than_shortening_the_message(self):
        from services.notification import service

        texts = self._texts(service.build_wa_components({"company_name": "Acme"}, {"name": "Ify"}, "customer_invite"))
        assert texts == ["Acme", "Ify", ""]  # count preserved, so Meta accepts it

    def test_undeclared_event_keeps_the_previous_behaviour(self):
        from services.notification import service

        texts = self._texts(service.build_wa_components({"company_name": "Acme"}, {"a": "1", "b": "2"}, "not_declared"))
        assert texts == ["Acme", "1", "2"]

    def test_every_mapped_template_declares_its_parameters(self):
        """A new event added to WA_TEMPLATE_MAP must declare its parameters, or
        it silently falls back to fragile dict ordering."""
        from services.notification import service

        undeclared = set(service.WA_TEMPLATE_MAP) - set(service.WA_TEMPLATE_PARAMS)
        assert not undeclared, f"missing WA_TEMPLATE_PARAMS entries: {sorted(undeclared)}"

    def test_no_template_exceeds_metas_parameter_budget(self):
        from services.notification import service

        for event, keys in service.WA_TEMPLATE_PARAMS.items():
            # +1 for the company name in {{1}}
            assert len(keys) + 1 <= service._WA_MAX_PARAMS, event


class TestFallbackInputsArePersisted:
    """The fallback reads `customer_id` and `locale` back off notification_log.

    Every existing fallback test stubs `get_log_for_fallback` to return those
    fields, so the suite stayed green while the producer never sent them and the
    column did not exist. These assert the *inputs* instead of the stub.
    """

    def test_enqueued_message_carries_customer_id(self):
        from shared import notifications

        with (
            patch.dict(os.environ, _ENV, clear=False),
            patch.object(notifications, "should_notify", return_value=True),
            patch.object(notifications, "_get_custom_template", return_value=None),
            patch.object(notifications, "execute_with_tenant", return_value=[]),
            patch.object(notifications, "get_queue_provider") as mock_sqs,
        ):
            notifications.enqueue_notifications(
                TENANT_ID,
                "customer_invite",
                {"phone": "+2348031234567", "email": "a@b.com", "name": "X"},
                {},
                customer_id="cust-42",
            )
        import json

        bodies = [json.loads(c.kwargs["body"]) for c in mock_sqs.return_value.send.call_args_list]
        # Without this the WhatsApp consumer writes a notification_log row with
        # customer_id NULL, and trigger_sms_fallback cannot resolve a phone —
        # the fallback gives up silently and the customer gets nothing.
        assert bodies, "no notification was enqueued"
        assert all(b["customer_id"] == "cust-42" for b in bodies)

    def test_log_queued_persists_locale(self):
        from services.notification import service

        with patch("services.notification.repository.insert_log", return_value={"id": "log-1"}) as mock_insert:
            service.log_queued(
                TENANT_ID,
                "whatsapp",
                "customer_invite",
                "+2348031234567",
                "X",
                "cust-42",
                {},
                None,
                message_body="customer_invite",
                locale="zh",
            )
        data = mock_insert.call_args.args[1]
        # A fallback SMS is rendered from the locale stored here; losing it sends
        # a Chinese-locale customer an English text.
        assert data["locale"] == "zh"
        assert data["customer_id"] == "cust-42"


class TestSendResultsAreHonoured:
    def _body(self) -> dict:
        return {
            "tenant_id": TENANT_ID,
            "event_type": "customer_invite",
            "channel": "sms",
            "recipient": {"phone": "+2348031234567", "name": "X"},
            "tenant_branding": {},
            "template_data": {},
            "customer_id": "cust-42",
        }

    def test_unsent_sms_is_not_logged_as_sent_or_metered(self):
        """send_sms returns False when unconfigured or suppressed.

        The result was discarded, so notification_log claimed "sent" and usage
        was metered for a message that never left the process — staff saw a
        delivered invite that no one received, and the tenant was billed.
        """
        from services.notification import handler

        with (
            patch.object(handler.service, "send_sms", return_value=False),
            patch.object(handler.service, "log_queued", return_value="log-1"),
            patch.object(handler.service, "log_sent") as mock_sent,
            patch.object(handler.service, "log_failed") as mock_failed,
            patch.object(handler, "record_usage") as mock_usage,
        ):
            handler._process_sms(self._body())

        mock_sent.assert_not_called()
        mock_usage.assert_not_called()
        mock_failed.assert_called_once()

    def test_whatsapp_failure_detail_names_metas_reason(self):
        """error_detail must say *why*, not "raised an exception".

        Every WhatsApp failure looked identical in the log, so an unapproved
        template was indistinguishable from a wrong number or a dead token.
        """
        from services.notification import handler, service

        body = {**self._body(), "channel": "whatsapp"}
        err = service.WhatsAppSendError("Meta 132001: template name (customer_invite) does not exist in en_US")
        with (
            patch.object(handler.service, "build_wa_components", return_value=[]),
            patch.object(handler.service, "send_whatsapp", side_effect=err),
            patch.object(handler.service, "log_queued", return_value="log-1"),
            patch.object(handler.service, "log_failed") as mock_failed,
            patch.object(handler.service, "trigger_sms_fallback", return_value=True),
            patch.object(handler, "record_usage"),
            pytest.raises(service.WhatsAppSendError),
        ):
            handler._process_whatsapp(body)

        assert "132001" in mock_failed.call_args.args[2]
