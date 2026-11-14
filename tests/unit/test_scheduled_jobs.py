"""Unit tests for services.scheduled — storage fee, escalation, expiry logic."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_GRACE_PERIOD = 14
_DAILY_RATE = Decimal("500")
TODAY = date(2026, 2, 15)
NOW = datetime(2026, 2, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# storage_fee._accrue_for_note
# ---------------------------------------------------------------------------


class TestStorageFeeAccrual:
    """Test the core fee-per-note logic in isolation."""

    def _note(self, created_days_ago: int, total_cartons: int = 10) -> dict:
        created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=max(0, (TODAY - date(2026, 1, 1)).days - created_days_ago))
        # Simpler: created_at = NOW - timedelta(days=created_days_ago)
        created_at = datetime.now(UTC) - timedelta(days=created_days_ago)
        return {
            "id": "note-001",
            "billing_id": "billing-001",
            "customer_id": "customer-001",
            "container_id": "container-001",
            "total_cartons": total_cartons,
            "created_at": created_at,
        }

    def test_within_grace_period_no_fee(self):
        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=7)  # only 7 days, grace=14
        with (
            patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=0),
            patch("services.scheduled.storage_fee.execute_write_with_tenant"),
            patch("services.scheduled.storage_fee.publish_event"),
        ):
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
            assert result is False

    def test_all_cartons_picked_no_fee(self):
        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        with patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=10):
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
            assert result is False

    def _patches(self, insert_result, adjust_result=None):
        """The fee insert and the invoice update run inside one `tenant_transaction`.

        The transaction is stubbed to a no-op context manager here; that the two
        writes really commit or roll back together is covered against a real
        database in tests/db/.
        """
        from contextlib import nullcontext

        return (
            patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3),
            patch("services.scheduled.storage_fee.tenant_transaction", return_value=nullcontext()),
            patch("services.scheduled.storage_fee.execute_write_with_tenant", return_value=insert_result),
            patch("services.scheduled.storage_fee.adjust_billing", return_value=adjust_result or {"id": "billing-001"}),
            patch("services.scheduled.storage_fee.publish_event"),
        )

    def test_past_grace_period_with_unreleased_accrues_fee(self):
        from contextlib import ExitStack

        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        with ExitStack() as stack:
            for p in self._patches({"id": "fee-log-001"}):
                stack.enter_context(p)
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
        assert result is True

    def test_fee_calculation_correct(self):
        """7 unreleased cartons × 500 NGN = 3500 NGN, added to the invoice in the same step."""
        from contextlib import ExitStack, nullcontext

        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        captured_calls = []

        def _capture_write(tenant_id, query, params=None):
            captured_calls.append(params)
            return {"id": "log-001"}

        with ExitStack() as stack:
            stack.enter_context(patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3))
            stack.enter_context(patch("services.scheduled.storage_fee.tenant_transaction", return_value=nullcontext()))
            stack.enter_context(patch("services.scheduled.storage_fee.execute_write_with_tenant", side_effect=_capture_write))
            mock_adjust = stack.enter_context(
                patch("services.scheduled.storage_fee.adjust_billing", return_value={"id": "billing-001"})
            )
            stack.enter_context(patch("services.scheduled.storage_fee.publish_event"))
            _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())

        insert_params = captured_calls[0]
        assert insert_params["cartons_in_storage"] == 7
        assert insert_params["amount_ngn"] == Decimal("3500")
        assert insert_params["daily_rate_ngn"] == _DAILY_RATE
        mock_adjust.assert_called_once_with(TENANT_ID, "billing-001", Decimal("3500"))

    def test_idempotent_on_conflict(self):
        """If log already exists for today (ON CONFLICT DO NOTHING → None returned), the invoice is not touched."""
        from contextlib import ExitStack, nullcontext

        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        with ExitStack() as stack:
            stack.enter_context(patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3))
            stack.enter_context(patch("services.scheduled.storage_fee.tenant_transaction", return_value=nullcontext()))
            stack.enter_context(patch("services.scheduled.storage_fee.execute_write_with_tenant", return_value=None))
            mock_adjust = stack.enter_context(patch("services.scheduled.storage_fee.adjust_billing"))
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
        assert result is False
        mock_adjust.assert_not_called()

    def test_a_failed_invoice_update_raises_so_the_log_row_rolls_back(self):
        from contextlib import ExitStack

        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        with ExitStack() as stack:
            for p in self._patches({"id": "fee-log-001"}, adjust_result=None):
                stack.enter_context(p)
            stack.enter_context(patch("services.scheduled.storage_fee.adjust_billing", return_value=None))
            try:
                _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
            except RuntimeError as exc:
                assert "not found" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("expected RuntimeError so the transaction rolls back")


# ---------------------------------------------------------------------------
# dispute_escalation
# ---------------------------------------------------------------------------


class TestDisputeEscalation:
    def _dispute(self, days_old: int) -> dict:
        updated_at = NOW - timedelta(days=days_old)
        return {
            "id": "dispute-001",
            "billing_id": "billing-001",
            "customer_id": "customer-001",
            "disputed_cbm": Decimal("10.5"),
            "updated_at": updated_at,
        }

    def test_within_escalation_days_no_action(self):
        from services.scheduled.dispute_escalation import _process_tenant

        dispute = self._dispute(days_old=3)  # 3 days, threshold=5
        config = {"enabled": True, "auto_escalate_days": 5}
        with (
            patch(
                "services.scheduled.dispute_escalation._get_dispute_escalation_config",
                return_value=config,
            ),
            patch(
                "services.scheduled.dispute_escalation._get_investigating_disputes",
                return_value=[dispute],
            ),
        ):
            result = _process_tenant(TENANT_ID)
            assert result == 0

    def test_past_escalation_days_escalates(self):
        from services.scheduled.dispute_escalation import _process_tenant

        dispute = self._dispute(days_old=6)  # 6 days > threshold=5
        config = {"enabled": True, "auto_escalate_days": 5}
        with (
            patch(
                "services.scheduled.dispute_escalation._get_dispute_escalation_config",
                return_value=config,
            ),
            patch(
                "services.scheduled.dispute_escalation._get_investigating_disputes",
                return_value=[dispute],
            ),
            patch("services.scheduled.dispute_escalation._escalate_dispute") as mock_escalate,
        ):
            result = _process_tenant(TENANT_ID)
            assert result == 1
            mock_escalate.assert_called_once()

    def test_disabled_config_skips_all(self):
        from services.scheduled.dispute_escalation import _process_tenant

        config = {"enabled": False}
        with patch(
            "services.scheduled.dispute_escalation._get_dispute_escalation_config",
            return_value=config,
        ):
            result = _process_tenant(TENANT_ID)
            assert result == 0


# ---------------------------------------------------------------------------
# release_expiry
# ---------------------------------------------------------------------------


class TestReleaseExpiry:
    def test_expired_note_is_updated(self):
        from services.scheduled.release_expiry import _process_tenant

        note = {
            "id": "note-001",
            "customer_id": "customer-001",
            "reference_number": "RN-001",
            "valid_until": date(2026, 1, 1),  # past
        }
        with (
            patch(
                "services.scheduled.release_expiry._get_expired_notes",
                return_value=[note],
            ),
            patch("services.scheduled.release_expiry._expire_note") as mock_expire,
        ):
            result = _process_tenant(TENANT_ID)
            assert result == 1
            mock_expire.assert_called_once()

    def test_no_expired_notes_returns_zero(self):
        from services.scheduled.release_expiry import _process_tenant

        with patch("services.scheduled.release_expiry._get_expired_notes", return_value=[]):
            result = _process_tenant(TENANT_ID)
            assert result == 0


# ---------------------------------------------------------------------------
# storage_reminders
# ---------------------------------------------------------------------------


class TestStorageReminders:
    def _note(self, days_old: int) -> dict:
        # Anchor to local date.today() (what _maybe_send_reminder receives as
        # `today`) — deriving from now(UTC) overshoots days_since by one when
        # the local date is ahead of UTC (00:00–01:00 WAT nightly flake).
        from datetime import time

        created_date = date.today() - timedelta(days=days_old)
        return {
            "id": "note-001",
            "customer_id": "customer-001",
            "reference_number": "RN-001",
            "total_cartons": 10,
            "created_at": datetime.combine(created_date, time(12, 0), tzinfo=UTC),
        }

    def test_first_reminder_sent_on_day_7(self):
        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=7)
        customer = {"id": "customer-001", "phone": "+2348012345678", "email": "c@example.com"}
        with (
            patch("services.scheduled.storage_reminders._sum_cartons_picked", return_value=0),
            patch("services.scheduled.storage_reminders._get_customer_contact", return_value=customer),
            patch("services.scheduled.storage_reminders.enqueue_notification", return_value=True),
        ):
            sent = _maybe_send_reminder(TENANT_ID, note, date.today(), 7, 13, 14)
            assert sent > 0

    def test_no_reminder_on_wrong_day(self):
        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=5)  # not day 7 or 13
        sent = _maybe_send_reminder(TENANT_ID, note, date.today(), 7, 13, 14)
        assert sent == 0

    def test_no_reminder_when_all_cartons_picked(self):
        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=7)
        with patch("services.scheduled.storage_reminders._sum_cartons_picked", return_value=10):
            sent = _maybe_send_reminder(TENANT_ID, note, date.today(), 7, 13, 14)
            assert sent == 0


# ---------------------------------------------------------------------------
# Locale forwarding in scheduled notifications
# ---------------------------------------------------------------------------


class TestScheduledLocaleForwarding:
    """Verify that scheduled jobs pass the recipient's locale to enqueue_notification."""

    def _note(self, days_old: int, customer_id: str = "cust-001") -> dict:
        from datetime import UTC, date, datetime, time, timedelta

        # Anchor to the same clock the assertions use (local date.today(), which
        # _maybe_send_reminder receives as `today`). Deriving from
        # datetime.now(UTC) made days_since come out one day high whenever the
        # local date was ahead of UTC (e.g. 00:00–01:00 WAT) — a nightly flake.
        created_date = date.today() - timedelta(days=days_old)
        return {
            "id": "note-001",
            "customer_id": customer_id,
            "reference_number": "ACME-RN-001",
            "total_cartons": 5,
            "valid_until": "2026-01-01",
            "created_at": datetime.combine(created_date, time(12, 0), tzinfo=UTC),
        }

    def test_storage_reminder_sends_zh_locale_for_zh_customer(self):
        from unittest.mock import patch

        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=7)
        customer = {"id": "cust-001", "email": "ng@example.com", "phone": "+2348012345678", "locale": "zh"}

        enqueued = []

        def capture_enqueue(**kwargs):
            enqueued.append(kwargs)
            return True

        with (
            patch("services.scheduled.storage_reminders._get_customer_contact", return_value=customer),
            patch("services.scheduled.storage_reminders._sum_cartons_picked", return_value=0),
            patch("services.scheduled.storage_reminders.enqueue_notification", side_effect=capture_enqueue),
        ):
            _maybe_send_reminder(TENANT_ID, note, __import__("datetime").date.today(), 7, 13, 14)

        assert len(enqueued) == 2
        for call_kwargs in enqueued:
            assert call_kwargs["locale"] == "zh", f"Expected locale='zh', got {call_kwargs.get('locale')!r}"

    def test_storage_reminder_sends_en_locale_for_en_customer(self):
        from unittest.mock import patch

        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=7)
        customer = {"id": "cust-001", "email": "ng@example.com", "phone": "", "locale": "en"}
        enqueued = []

        with (
            patch("services.scheduled.storage_reminders._get_customer_contact", return_value=customer),
            patch("services.scheduled.storage_reminders._sum_cartons_picked", return_value=0),
            patch(
                "services.scheduled.storage_reminders.enqueue_notification", side_effect=lambda **kw: enqueued.append(kw) or True
            ),
        ):
            _maybe_send_reminder(TENANT_ID, note, __import__("datetime").date.today(), 7, 13, 14)

        for call_kwargs in enqueued:
            assert call_kwargs["locale"] == "en"

    def test_storage_reminder_defaults_locale_to_en_when_missing(self):
        from unittest.mock import patch

        from services.scheduled.storage_reminders import _maybe_send_reminder

        note = self._note(days_old=7)
        # Customer row without locale key
        customer = {"id": "cust-001", "email": "ng@example.com", "phone": ""}
        enqueued = []

        with (
            patch("services.scheduled.storage_reminders._get_customer_contact", return_value=customer),
            patch("services.scheduled.storage_reminders._sum_cartons_picked", return_value=0),
            patch(
                "services.scheduled.storage_reminders.enqueue_notification", side_effect=lambda **kw: enqueued.append(kw) or True
            ),
        ):
            _maybe_send_reminder(TENANT_ID, note, __import__("datetime").date.today(), 7, 13, 14)

        for call_kwargs in enqueued:
            assert call_kwargs.get("locale", "en") == "en"

    def test_release_expiry_sends_zh_locale_for_zh_customer(self):
        from unittest.mock import patch

        from services.scheduled.release_expiry import _notify_customer

        note = self._note(days_old=0)
        customer = {"id": "cust-001", "email": "cn@example.com", "phone": "+8613012345678", "locale": "zh"}
        enqueued = []

        with (
            patch("services.scheduled.release_expiry._get_customer_contact", return_value=customer),
            patch("services.scheduled.release_expiry.enqueue_notification", side_effect=lambda **kw: enqueued.append(kw) or True),
        ):
            _notify_customer(TENANT_ID, note)

        assert len(enqueued) == 2
        for call_kwargs in enqueued:
            assert call_kwargs["locale"] == "zh"

    def test_dispute_escalation_sends_zh_locale_for_zh_admin(self):
        from unittest.mock import patch

        from services.scheduled.dispute_escalation import _notify_escalation

        dispute = {
            "id": "dispute-001",
            "billing_id": "billing-001",
            "customer_id": "cust-001",
            "disputed_cbm": "10.5",
        }
        admins = [{"email": "admin@acme.com", "locale": "zh"}]
        enqueued = []

        with (
            patch("services.scheduled.dispute_escalation.execute_with_tenant", return_value=admins),
            patch(
                "services.scheduled.dispute_escalation.enqueue_notification", side_effect=lambda **kw: enqueued.append(kw) or True
            ),
        ):
            _notify_escalation(TENANT_ID, dispute)

        assert len(enqueued) == 1
        assert enqueued[0]["locale"] == "zh"

    def test_dispute_escalation_also_writes_the_in_app_staff_notification(self):
        """Ground-truth follow-up to the payment-claim-rejection notification
        bug: this event previously only sent an email — no signal in the
        TopBar bell, which now exists as a real feed."""
        from unittest.mock import patch

        from services.scheduled.dispute_escalation import _notify_escalation

        dispute = {"id": "dispute-001", "billing_id": "billing-001", "customer_id": "cust-001", "disputed_cbm": "10.5"}

        with (
            patch("services.scheduled.dispute_escalation.execute_with_tenant", return_value=[]),
            patch("services.scheduled.dispute_escalation.notify_staff") as mock_notify,
        ):
            _notify_escalation(TENANT_ID, dispute)

        assert mock_notify.call_count == 2
        roles = {c.kwargs["target_role"] for c in mock_notify.call_args_list}
        assert roles == {"china_office_staff", "tenant_admin"}
        assert all(c.kwargs["event_type"] == "cbm_dispute_escalated" for c in mock_notify.call_args_list)
        assert all(c.kwargs["entity_id"] == "dispute-001" for c in mock_notify.call_args_list)

    def test_sla_check_sends_locale_for_nigeria_staff(self):
        from unittest.mock import patch

        from services.scheduled.sla_check import _notify_nigeria_staff

        dispute = {
            "id": "dispute-001",
            "billing_id": "billing-001",
            "customer_id": "cust-001",
            "disputed_cbm": "10.5",
        }
        staff = [{"email": "nigstaff@acme.com", "locale": "en"}]
        enqueued = []

        with (
            patch("services.scheduled.sla_check.execute_with_tenant", return_value=staff),
            patch("services.scheduled.sla_check.enqueue_notification", side_effect=lambda **kw: enqueued.append(kw) or True),
        ):
            _notify_nigeria_staff(TENANT_ID, dispute)

        assert len(enqueued) == 1
        assert enqueued[0]["locale"] == "en"

    def test_sla_breach_also_writes_the_in_app_staff_notification(self):
        """Ground-truth follow-up to the payment-claim-rejection notification
        bug: this event previously only sent an email — no signal in the
        TopBar bell, which now exists as a real feed."""
        from unittest.mock import patch

        from services.scheduled.sla_check import _notify_nigeria_staff

        dispute = {"id": "dispute-001", "billing_id": "billing-001", "customer_id": "cust-001", "disputed_cbm": "10.5"}

        with (
            patch("services.scheduled.sla_check.execute_with_tenant", return_value=[]),
            patch("services.scheduled.sla_check.notify_staff") as mock_notify,
        ):
            _notify_nigeria_staff(TENANT_ID, dispute)

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["event_type"] == "cbm_dispute_sla_breach"
        assert mock_notify.call_args.kwargs["target_role"] == "nigeria_office_staff"
        assert mock_notify.call_args.kwargs["entity_id"] == "dispute-001"

    def test_customer_contact_query_includes_locale(self):
        """Regression: _get_customer_contact must SELECT locale."""
        import inspect

        from services.scheduled.release_expiry import _get_customer_contact as expiry_contact
        from services.scheduled.storage_reminders import _get_customer_contact

        for fn in (_get_customer_contact, expiry_contact):
            source = inspect.getsource(fn)
            assert "locale" in source, f"{fn.__module__}._get_customer_contact must SELECT locale"

    def test_staff_query_includes_locale_in_escalation(self):
        """Regression: _notify_escalation must SELECT tu.locale from tenant_user."""
        import inspect

        from services.scheduled.dispute_escalation import _notify_escalation

        source = inspect.getsource(_notify_escalation)
        assert "locale" in source

    def test_staff_query_includes_locale_in_sla(self):
        """Regression: _notify_nigeria_staff must SELECT tu.locale from tenant_user."""
        import inspect

        from services.scheduled.sla_check import _notify_nigeria_staff

        source = inspect.getsource(_notify_nigeria_staff)
        assert "locale" in source

    def test_enqueue_notification_includes_locale_in_sqs_payload(self):
        """enqueue_notification must include locale in the SQS message body."""
        import json
        from unittest.mock import MagicMock, patch

        captured = {}

        def fake_send(*, destination, body):
            captured["body"] = json.loads(body)

        mock_queue = MagicMock()
        mock_queue.send.side_effect = fake_send

        import os

        os.environ["SQS_EMAIL_QUEUE_URL"] = "https://sqs.test/email"

        with (
            patch("shared.notifications._get_notification_prefs", return_value={}),
            patch("shared.notifications.get_queue_provider", return_value=mock_queue),
        ):
            from shared.notifications import enqueue_notification

            enqueue_notification(
                tenant_id=TENANT_ID,
                channel="email",
                recipient="test@example.com",
                template_id="test_template",
                template_vars={},
                locale="zh",
            )

        assert captured["body"]["locale"] == "zh"
