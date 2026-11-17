"""Unit tests for customer notification consent (audit SEC-01).

The owner's decisions (2026-11-15), which these tests pin:

* A customer who has *recorded* preferences is held to them; one with none recorded is not restricted.
* Operational messages (shipment, money, claims) and account links go out whatever the preferences say, so
  today no event type is actually held back; announcements are in-app only.
* An event type nobody has classified is consent-bound, so a new kind of message errs toward the customer.

Most enforcement tests bind a real event type (`shipment_update`) for the test's duration to show the
machinery working, since none is bound in production.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import shared.notifications as notifications
from shared import notification_consent as consent
from tests.patching import patch_tenant_management

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CUSTOMER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
RECORDED = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


class TestPermits:
    def test_no_recorded_choice_means_no_restriction(self):
        """Staff-created and imported customers were never asked, so an empty list is not a refusal."""
        for channel in ("sms", "whatsapp", "email"):
            assert consent.permits([], None, channel)
            assert consent.permits(None, None, channel)

    def test_a_recorded_choice_is_followed(self):
        assert consent.permits(["email"], RECORDED, "email")
        assert not consent.permits(["email"], RECORDED, "sms")
        assert not consent.permits(["email"], RECORDED, "whatsapp")

    def test_a_recorded_empty_choice_means_none(self):
        """The customer opted out of everything: that is a choice, unlike a blank."""
        for channel in ("sms", "whatsapp", "email"):
            assert not consent.permits([], RECORDED, channel)
            assert not consent.permits(None, RECORDED, channel)


class TestClassification:
    @pytest.mark.parametrize("event", sorted(consent.ACCOUNT_EVENTS))
    def test_account_links_are_never_bound(self, event):
        assert not consent.is_consent_bound(event)

    @pytest.mark.parametrize("event", sorted(consent.OPERATIONAL_EVENTS))
    def test_operational_events_are_not_bound(self, event):
        assert not consent.is_consent_bound(event)

    @pytest.mark.parametrize("event", ["weekly_offers", "new_year_promo", "test_template", ""])
    def test_an_unclassified_event_defaults_to_bound(self, event):
        """A new kind of message forgotten here errs toward the customer's choice."""
        assert consent.is_consent_bound(event)

    def test_binding_an_operational_event_is_a_one_line_change(self):
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"payment_due"})):
            assert consent.is_consent_bound("payment_due")

    def test_the_sets_do_not_overlap(self):
        assert not consent.ACCOUNT_EVENTS & consent.OPERATIONAL_EVENTS
        assert not consent.CONSENT_BOUND_EVENTS & (consent.ACCOUNT_EVENTS | consent.OPERATIONAL_EVENTS)

    def test_nothing_is_bound_today(self):
        """The owner's decision: all operational messages bypass an opt-out. Change this test with that decision."""
        assert frozenset() == consent.CONSENT_BOUND_EVENTS


class TestEveryEventTypeIsClassified:
    """Adding a message without deciding whether an opt-out governs it must fail here, not in production."""

    @staticmethod
    def _known_event_types() -> set[str]:
        from services.notification import service as notification_service

        names: set[str] = set()
        for table in (
            "_SMS_TEMPLATES",
            "_SMS_TEMPLATES_ZH",
            "EMAIL_SUBJECTS",
            "EMAIL_SUBJECTS_ZH",
            "_EMAIL_BODIES",
            "_EMAIL_BODIES_ZH",
            "WA_TEMPLATE_PARAMS",
            "WA_TEMPLATE_MAP",
        ):
            names |= set(getattr(notification_service, table, {}))

        # Every event_type / template_id literal passed to the enqueue functions.
        call = re.compile(r"enqueue_notifications?\(((?:.|\n){0,1200}?)\n\s*\)", re.M)
        literal = re.compile(r"(?:event_type|template_id)\s*=\s*\"([a-z_]+)\"")
        for path in Path("services").rglob("*.py"):
            for match in call.finditer(path.read_text()):
                names |= set(literal.findall(match.group(1)))
        # The event_type variable in payment_release's claim notifications is resolved from these two.
        return names

    def test_every_known_event_type_has_been_classified(self):
        classified = consent.ACCOUNT_EVENTS | consent.OPERATIONAL_EVENTS | consent.CONSENT_BOUND_EVENTS
        unclassified = self._known_event_types() - classified
        assert not unclassified, (
            f"Classify {sorted(unclassified)} in shared/notification_consent.py: is it an account link, an operational "
            "message, or one a customer's opt-out should govern?"
        )

    def test_the_scan_actually_finds_event_types(self):
        """Guard the guard: a regex that matched nothing would make the test above pass for nothing."""
        found = self._known_event_types()
        assert {"payment_due", "container_arrived", "account_activation", "registration_existing_account"} <= found


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


class _Sent:
    """Records what reached the queues and what was written to notification_log."""

    def __init__(self) -> None:
        self.queues: list[str] = []
        self.suppressed: list[dict] = []
        self.prefs_lookups = 0


@pytest.fixture
def world(monkeypatch):
    """A prod-like environment whose queues, tenant lookups and customer preferences are faked."""
    state = _Sent()
    state.prefs = {"notification_consent": ["email"], "consent_given_at": RECORDED}  # type: ignore[attr-defined]

    provider = MagicMock()
    provider.send.side_effect = lambda destination, body: state.queues.append(destination)

    def fake_read(tenant_id, query, params=None):
        state.prefs_lookups += 1
        return [state.prefs] if state.prefs is not None else []  # type: ignore[attr-defined]

    def fake_write(tenant_id, query, params=None):
        state.suppressed.append(params)
        return [{"id": "log-1"}]

    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SQS_EMAIL_QUEUE_URL", "q-email")
    monkeypatch.setenv("SQS_SMS_QUEUE_URL", "q-sms")
    monkeypatch.setenv("SQS_WHATSAPP_QUEUE_URL", "q-wa")
    monkeypatch.setattr(notifications, "get_queue_provider", lambda: provider)
    monkeypatch.setattr(notifications, "_tenant_branding", lambda tenant_id: {})
    monkeypatch.setattr(notifications, "should_notify", lambda *a, **k: True)
    monkeypatch.setattr(notifications, "_get_custom_template", lambda *a, **k: None)
    monkeypatch.setattr(notifications, "_get_notification_prefs", lambda tenant_id: {})
    monkeypatch.setattr(notifications, "execute_with_tenant", fake_read)
    monkeypatch.setattr(notifications, "execute_write_with_tenant", fake_write)
    return state


_RECIPIENT = {"phone": "+2348012345678", "email": "ada@example.test", "whatsapp": "", "name": "Ada"}


def _send(event: str = "weekly_offers", customer_id: str | None = CUSTOMER, recipient: dict | None = None) -> None:
    notifications.enqueue_notifications(TENANT, event, recipient or _RECIPIENT, {"name": "Ada"}, customer_id=customer_id)


class TestEnqueueNotificationsHonoursPreferences:
    def test_a_customer_who_agreed_to_email_only_gets_no_whatsapp_or_sms(self, world):
        _send()
        assert world.queues == ["q-email"]

    def test_the_held_back_channel_is_recorded_with_a_reason(self, world):
        _send()
        assert [(r["channel"], r["event_type"], r["customer_id"], r["reason"]) for r in world.suppressed] == [
            ("whatsapp", "weekly_offers", CUSTOMER, "customer has not agreed to whatsapp")
        ]

    def test_the_recorded_contact_is_masked(self, world):
        _send()
        assert "+2348012345678" not in str(world.suppressed)

    def test_a_customer_who_opted_out_of_everything_gets_nothing(self, world):
        world.prefs = {"notification_consent": [], "consent_given_at": RECORDED}
        _send()
        assert world.queues == []
        assert sorted(r["channel"] for r in world.suppressed) == ["email", "whatsapp"]

    def test_a_customer_with_no_recorded_choice_is_not_restricted(self, world):
        world.prefs = {"notification_consent": [], "consent_given_at": None}
        _send()
        assert world.queues == ["q-wa", "q-email"]
        assert world.suppressed == []

    def test_a_customer_who_agreed_to_sms_but_not_whatsapp_is_texted_instead(self, world):
        world.prefs = {"notification_consent": ["sms", "email"], "consent_given_at": RECORDED}
        _send()
        assert world.queues == ["q-sms", "q-email"]

    def test_a_customer_who_agreed_to_whatsapp_gets_whatsapp(self, world):
        world.prefs = {"notification_consent": ["whatsapp"], "consent_given_at": RECORDED}
        _send()
        assert world.queues == ["q-wa"]

    def test_a_recipient_with_no_phone_is_only_ever_offered_email(self, world):
        world.prefs = {"notification_consent": ["sms"], "consent_given_at": RECORDED}
        _send(recipient={**_RECIPIENT, "phone": ""})
        assert world.queues == []
        assert [r["channel"] for r in world.suppressed] == ["email"]

    def test_without_a_customer_id_nothing_is_sent(self, world):
        """Fail closed: there is nobody's preferences to check, and the message may be one they declined."""
        _send(customer_id=None)
        assert world.queues == []
        assert world.prefs_lookups == 0

    def test_a_failed_preference_lookup_sends_nothing(self, world, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("database unreachable")

        monkeypatch.setattr(notifications, "execute_with_tenant", boom)
        _send()
        assert world.queues == []

    def test_an_unknown_customer_gets_nothing(self, world):
        world.prefs = None
        _send()
        assert world.queues == []

    def test_a_failure_to_record_the_suppression_does_not_send_the_message(self, world, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("log unavailable")

        monkeypatch.setattr(notifications, "execute_write_with_tenant", boom)
        _send()
        assert world.queues == ["q-email"], "only the allowed channel went out; the log failure changed nothing else"


class TestWhatIsNotHeldBack:
    @pytest.mark.parametrize("event", sorted(consent.OPERATIONAL_EVENTS | consent.ACCOUNT_EVENTS))
    def test_operational_and_account_messages_ignore_an_explicit_opt_out(self, world, event):
        world.prefs = {"notification_consent": [], "consent_given_at": RECORDED}
        _send(event=event)
        assert world.queues == ["q-wa", "q-email"]
        assert world.suppressed == []

    def test_they_do_not_even_read_the_preferences(self, world):
        _send(event="payment_due")
        assert world.prefs_lookups == 0

    def test_they_need_no_customer_id(self, world):
        """Staff-facing events such as tenant_suspended have no customer; account links may predate the record."""
        _send(event="account_activation", customer_id=None)
        assert world.queues == ["q-wa", "q-email"]

    def test_an_event_can_be_bound_by_listing_it(self, world):
        world.prefs = {"notification_consent": ["email"], "consent_given_at": RECORDED}
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"payment_due"})):
            _send(event="payment_due")
        assert world.queues == ["q-email"]


class TestSingleChannelSends:
    """enqueue_notification, used by the scheduled reminders."""

    def test_a_bound_message_to_a_channel_the_customer_declined_is_dropped_and_recorded(self, world):
        sent = notifications.enqueue_notification(TENANT, "sms", "+2348012345678", "weekly_offers", {}, customer_id=CUSTOMER)
        assert sent is False
        assert world.queues == []
        assert [r["channel"] for r in world.suppressed] == ["sms"]

    def test_a_bound_message_to_a_channel_the_customer_accepted_is_sent(self, world):
        assert notifications.enqueue_notification(TENANT, "email", "ada@example.test", "weekly_offers", {}, customer_id=CUSTOMER)
        assert world.queues == ["q-email"]

    def test_a_bound_message_with_no_customer_is_dropped(self, world):
        assert notifications.enqueue_notification(TENANT, "email", "ada@example.test", "weekly_offers", {}) is False

    def test_an_operational_reminder_is_sent_regardless(self, world):
        world.prefs = {"notification_consent": [], "consent_given_at": RECORDED}
        assert notifications.enqueue_notification(
            TENANT, "sms", "+2348012345678", "storage_first_reminder", {}, customer_id=CUSTOMER
        )
        assert world.queues == ["q-sms"]


class TestSmsFallback:
    """When WhatsApp fails, SMS is a new message and needs the same consent."""

    @staticmethod
    def _fallback(event_type: str, prefs: dict | None):
        from services.notification import repository as repo
        from services.notification import service

        suppressed: list[dict] = []
        queue = MagicMock()
        with (
            patch.object(
                repo,
                "get_log_for_fallback",
                return_value={"customer_id": CUSTOMER, "event_type": event_type, "recipient_name": "Ada"},
            ),
            patch.object(repo, "fallback_already_sent", return_value=False),
            patch.object(repo, "get_customer_phone", return_value="+2348012345678"),
            patch.object(repo, "insert_log", return_value={"id": "log-2"}),
            patch("shared.notifications.is_recipient_allowed", return_value=True),
            patch("shared.notifications.execute_with_tenant", return_value=[prefs] if prefs else []),
            patch(
                "shared.notifications.execute_write_with_tenant",
                side_effect=lambda t, q, p=None: suppressed.append(p) or [{"id": "x"}],
            ),
            patch("services.notification.service.get_queue_provider", return_value=queue),
            patch.dict("os.environ", {"SQS_SMS_QUEUE_URL": "q-sms"}),
        ):
            result = service.trigger_sms_fallback(TENANT, "wa-log-1", "failed")
        return result, queue, suppressed

    def test_no_sms_for_a_consent_bound_event_the_customer_did_not_accept(self):
        result, queue, suppressed = self._fallback(
            "weekly_offers", {"notification_consent": ["whatsapp"], "consent_given_at": RECORDED}
        )
        assert result is False
        queue.send.assert_not_called()
        assert [p["channel"] for p in suppressed] == ["sms"]

    def test_an_operational_event_falls_back_as_before(self):
        result, queue, suppressed = self._fallback(
            "payment_due", {"notification_consent": ["whatsapp"], "consent_given_at": RECORDED}
        )
        assert result is True
        queue.send.assert_called_once()
        assert suppressed == []


# ---------------------------------------------------------------------------
# Recording a choice
# ---------------------------------------------------------------------------


class TestRecordingAChoice:
    @staticmethod
    def _update(updates: dict) -> dict:
        from services.tenant_management import service

        saved: dict = {}
        with (
            patch_tenant_management("get_customer", return_value={"id": CUSTOMER}),
            patch("services.tenant_management.customers._normalize_customer_phones", side_effect=lambda t, u: u),
            patch.object(service.repo, "update_customer", side_effect=lambda t, c, u: saved.update(u) or {"id": c, **u}),
            patch_tenant_management("log_audit"),
        ):
            service.update_customer(TENANT, CUSTOMER, updates, actor_id="staff-1")
        return saved

    def test_saving_preferences_records_when(self):
        saved = self._update({"notification_consent": ["email"]})
        assert saved["notification_consent"] == ["email"]
        assert datetime.fromisoformat(saved["consent_given_at"]).tzinfo is not None

    def test_saving_an_empty_list_is_still_recorded(self):
        """Opting out of everything is a choice, and must stop being treated as 'never asked'."""
        saved = self._update({"notification_consent": []})
        assert saved["notification_consent"] == []
        assert "consent_given_at" in saved

    def test_other_edits_do_not_touch_the_record(self):
        assert "consent_given_at" not in self._update({"phone": "+2348012345678"})

    def test_an_explicit_timestamp_is_kept(self):
        saved = self._update({"notification_consent": ["sms"], "consent_given_at": "2026-02-02T00:00:00+00:00"})
        assert saved["consent_given_at"] == "2026-02-02T00:00:00+00:00"

    @pytest.mark.parametrize(("sent", "stored"), [(["sms"], ["sms"]), ([], []), (None, ["email"])])
    def test_a_registrants_own_choice_wins_even_when_empty(self, sent, stored):
        from services.tenant_management import service
        from services.tenant_management.models import CustomerRegistrationRequest

        fields = {"name": "Ada", "email": "ada@example.test", "phone": "08012345678"}
        if sent is not None:
            fields["notification_consent"] = sent
        created: dict = {}
        cognito = MagicMock()
        cognito.create_user.return_value = "cog-1"
        with (
            patch.object(
                service.repo,
                "get_tenant_by_slug",
                return_value={"id": TENANT, "status": "active", "destination_country": "Nigeria"},
            ),
            patch.object(service.repo, "get_customer_by_email", return_value=None),
            patch.object(service.repo, "create_tenant_user", return_value={"id": "tu-1"}),
            patch.object(service.repo, "create_customer", side_effect=lambda t, d: created.update(d) or {"id": "c1"}),
            patch_tenant_management("get_identity_provider", return_value=cognito),
            patch_tenant_management("log_audit"),
            patch("shared.notifications.enqueue_notifications"),
        ):
            service.self_register_customer(CustomerRegistrationRequest(**fields), slug="acme")
        assert created["notification_consent"] == stored
        assert created["consent_given_at"]
