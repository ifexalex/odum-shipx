"""The message that carries a release note's pickup code (audit UX-09), and keeping the code out of the log."""

import json
from unittest.mock import patch

import pytest

from services.notification import service
from shared import notification_consent
from shared.exceptions import BusinessRuleViolationError

BRANDING = {"company_name": "Acme Shipping"}
DATA = {"reference_number": "ACME-RN-1", "pickup_code": "048213"}
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestTheMessage:
    def test_the_sms_carries_the_code_and_says_to_keep_it_private(self):
        text = service.format_sms("pickup_code_issued", BRANDING, DATA)
        assert "048213" in text and "ACME-RN-1" in text
        assert "Do not share" in text

    def test_the_chinese_sms_carries_the_code(self):
        assert "048213" in service.format_sms("pickup_code_issued", BRANDING, DATA, locale="zh")

    def test_the_email_has_a_subject_and_shows_the_code(self):
        assert service.email_subject("pickup_code_issued", BRANDING, DATA, None, "en").endswith("Your pickup code")
        html = service.render_email_html(BRANDING, "pickup_code_issued", "Ngozi", DATA)
        assert "048213" in html and "Pickup code" in html
        assert "we will never ask you for it" in html

    def test_the_email_text_part_carries_it_too(self):
        assert "048213" in service.render_email_text(BRANDING, "pickup_code_issued", "Ngozi", DATA, "en")

    def test_the_chinese_email_is_translated_not_the_generic_fallback(self):
        subject = service.email_subject("pickup_code_issued", BRANDING, DATA, None, "zh")
        assert "取货码" in subject
        html = service.render_email_html(BRANDING, "pickup_code_issued", "Ngozi", DATA, "zh")
        assert "取货码" in html and "048213" in html

    def test_a_hostile_reference_cannot_inject_markup(self):
        html = service.render_email_html(BRANDING, "pickup_code_issued", "N", {**DATA, "reference_number": "<script>x</script>"})
        assert "<script>" not in html

    def test_it_is_always_sent_whatever_the_customers_preferences(self):
        assert not notification_consent.is_consent_bound("pickup_code_issued")


class TestRedaction:
    def test_the_code_is_masked_in_the_stored_data_and_the_stored_body(self):
        body = service.format_sms("pickup_code_issued", BRANDING, DATA)
        data, stored_body = service.redact_secrets(DATA, body)
        assert data["pickup_code"] == service.REDACTED and data["reference_number"] == "ACME-RN-1"
        assert "048213" not in str(stored_body) and service.REDACTED in str(stored_body)
        assert "ACME-RN-1" in str(stored_body), "the rest of the message is kept"

    def test_every_occurrence_is_masked(self):
        _, body = service.redact_secrets({"pickup_code": "111111"}, "code 111111, again 111111")
        assert "111111" not in str(body)

    def test_the_callers_dict_is_not_mutated(self):
        original = dict(DATA)
        service.redact_secrets(DATA, "x")
        assert original == DATA

    def test_a_message_with_no_secret_is_stored_as_it_is(self):
        data = {"reference_number": "R1"}
        assert service.redact_secrets(data, "hello") == (data, "hello")

    def test_log_queued_never_hands_the_code_to_the_database(self):
        body = service.format_sms("pickup_code_issued", BRANDING, DATA)
        with patch("services.notification.repository.insert_log", return_value={"id": "log-1"}) as insert:
            service.log_queued(TENANT, "sms", "pickup_code_issued", "+2348012345678", "Ngozi", "c1", DATA, message_body=body)
        stored = insert.call_args.args[1]
        assert "048213" not in json.dumps(stored, default=str)
        assert json.loads(stored["template_data"])["pickup_code"] == service.REDACTED
        assert service.REDACTED in stored["message_body"]


class TestNoRetry:
    def test_a_failed_code_message_cannot_be_retried_because_the_code_is_not_kept(self):
        original = {"id": "log-1", "status": "failed", "event_type": "pickup_code_issued", "channel": "sms"}
        with (
            patch("services.notification.repository.get_log_by_id", return_value=original),
            patch.object(service, "get_queue_provider") as queue,
        ):
            with pytest.raises(BusinessRuleViolationError) as caught:
                service.retry_notification(TENANT, "log-1", actor_id="u")
        assert caught.value.rule_id == "NOTIFICATION_NOT_RETRYABLE"
        assert "Reissue the code" in caught.value.message
        assert not queue.called, "nothing may be enqueued: it would send a mask"
