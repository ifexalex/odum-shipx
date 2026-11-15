"""Customer notification consent against a real database (audit SEC-01).

The mocked tests cover the policy and every channel path. What only a database can show: that the
preference query reads the real columns, that a `suppressed` row is accepted by notification_log's CHECK
(migration 064), and that saving preferences through the service is what makes them bind.
"""

from unittest.mock import MagicMock, patch

import pytest

import shared.notifications as notifications
from shared import notification_consent as consent

pytestmark = pytest.mark.db


def _set(admin, customer_id: str, consent_list: list[str], recorded: bool) -> None:
    with admin.cursor() as cur:
        cur.execute(
            "UPDATE customer SET notification_consent = %s, consent_given_at = CASE WHEN %s THEN NOW() ELSE NULL END WHERE id = %s",
            (consent_list, recorded, customer_id),
        )


def _log_rows(admin, tenant: str) -> list[tuple]:
    with admin.cursor() as cur:
        cur.execute(
            "SELECT event_type, channel, status, error_detail, customer_id::text FROM notification_log "
            "WHERE tenant_id = %s ORDER BY created_at",
            (tenant,),
        )
        return cur.fetchall()


@pytest.fixture
def queues(monkeypatch):
    sent: list[str] = []
    provider = MagicMock()
    provider.send.side_effect = lambda destination, body: sent.append(destination)
    for name, url in (("SQS_EMAIL_QUEUE_URL", "q-email"), ("SQS_SMS_QUEUE_URL", "q-sms"), ("SQS_WHATSAPP_QUEUE_URL", "q-wa")):
        monkeypatch.setenv(name, url)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setattr(notifications, "get_queue_provider", lambda: provider)
    monkeypatch.setattr(notifications, "_get_notification_prefs", lambda tenant_id: {})
    return sent


_RECIPIENT = {"phone": "+2348012345678", "email": "ada@example.test", "whatsapp": "", "name": "Ada"}


def _send(world, customer_id: str, event: str) -> None:
    notifications.enqueue_notifications(world["tenant"], event, _RECIPIENT, {"name": "Ada"}, customer_id=customer_id)


class TestConsentOnRealData:
    def test_a_customer_who_chose_email_only_is_not_sent_sms_or_whatsapp(self, world, admin, queues):
        _set(admin, world["customers"][0], ["email"], recorded=True)
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"shipment_update"})):
            _send(world, world["customers"][0], "shipment_update")

        assert queues == ["q-email"]
        assert _log_rows(admin, world["tenant"]) == [
            ("shipment_update", "whatsapp", "suppressed", "customer has not agreed to whatsapp", world["customers"][0])
        ]

    def test_an_imported_customer_with_no_recorded_choice_is_still_messaged(self, world, admin, queues):
        """The default row, as every one of the dev database's customers is: empty list, never asked."""
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"shipment_update"})):
            _send(world, world["customers"][1], "shipment_update")

        assert queues == ["q-wa", "q-email"]
        assert _log_rows(admin, world["tenant"]) == []

    def test_a_customer_who_opted_out_of_everything_gets_nothing(self, world, admin, queues):
        _set(admin, world["customers"][2], [], recorded=True)
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"shipment_update"})):
            _send(world, world["customers"][2], "shipment_update")

        assert queues == []
        assert sorted(row[1] for row in _log_rows(admin, world["tenant"])) == ["email", "whatsapp"]

    def test_the_same_opt_out_does_not_stop_an_operational_message(self, world, admin, queues):
        """The owner's decision: operational messages are sent whatever a customer chose."""
        _set(admin, world["customers"][3], [], recorded=True)
        _send(world, world["customers"][3], "payment_due")

        assert queues == ["q-wa", "q-email"]
        assert _log_rows(admin, world["tenant"]) == []

    def test_an_unclassified_event_type_is_held_back_for_an_opted_out_customer(self, world, admin, queues):
        _set(admin, world["customers"][4], [], recorded=True)
        _send(world, world["customers"][4], "weekly_offers")

        assert queues == []
        assert len(_log_rows(admin, world["tenant"])) == 2

    def test_a_suppressed_row_is_accepted_by_the_log(self, world, admin):
        notifications.record_suppressed(
            world["tenant"], "weekly_offers", "sms", world["customers"][5], "+2348012345678", "customer has not agreed to sms"
        )
        (row,) = _log_rows(admin, world["tenant"])
        assert row[2] == "suppressed"


class TestSavingPreferencesMakesThemBind:
    def _save(self, world, customer_id: str, preferences: list[str]) -> None:
        from services.tenant_management import service

        with patch.object(service, "log_audit"):
            service.update_customer(world["tenant"], customer_id, {"notification_consent": preferences}, actor_id=world["user"])

    def test_before_saving_nothing_binds_and_after_saving_it_does(self, world, admin, queues):
        customer = world["customers"][6]
        with patch.object(consent, "CONSENT_BOUND_EVENTS", frozenset({"shipment_update"})):
            _send(world, customer, "shipment_update")
            assert queues == ["q-wa", "q-email"], "no choice recorded yet"

            queues.clear()
            self._save(world, customer, ["email"])
            _send(world, customer, "shipment_update")
            assert queues == ["q-email"], "the saved choice now binds"

    def test_saving_an_empty_list_is_recorded_as_a_choice(self, world, admin):
        customer = world["customers"][7]
        self._save(world, customer, [])
        with admin.cursor() as cur:
            cur.execute("SELECT notification_consent, consent_given_at IS NOT NULL FROM customer WHERE id = %s", (customer,))
            assert cur.fetchone() == ([], True)

    def test_editing_something_else_does_not_record_a_choice(self, world, admin):
        from services.tenant_management import service

        customer = world["customers"][8]
        with patch.object(service, "log_audit"):
            service.update_customer(world["tenant"], customer, {"name": "Renamed"}, actor_id=world["user"])
        with admin.cursor() as cur:
            cur.execute("SELECT consent_given_at FROM customer WHERE id = %s", (customer,))
            assert cur.fetchone() == (None,)
