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

    def test_past_grace_period_with_unreleased_accrues_fee(self):
        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        inserted = {"id": "fee-log-001"}

        with (
            patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3),
            patch(
                "services.scheduled.storage_fee.execute_write_with_tenant",
                return_value=inserted,
            ),
            patch("services.scheduled.storage_fee.publish_event"),
        ):
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
            assert result is True

    def test_fee_calculation_correct(self):
        """7 unreleased cartons × 500 NGN = 3500 NGN."""
        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        captured_calls = []

        def _capture_write(tenant_id, query, params=None):
            captured_calls.append(params)
            return {"id": "log-001"}

        with (
            patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3),
            patch(
                "services.scheduled.storage_fee.execute_write_with_tenant",
                side_effect=_capture_write,
            ),
            patch("services.scheduled.storage_fee.publish_event"),
        ):
            _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())

        # First write is the storage_fee_log INSERT
        insert_params = captured_calls[0]
        assert insert_params["cartons_in_storage"] == 7
        assert insert_params["amount_ngn"] == Decimal("3500")
        assert insert_params["daily_rate_ngn"] == _DAILY_RATE

    def test_idempotent_on_conflict(self):
        """If log already exists for today (ON CONFLICT DO NOTHING → None returned), no billing update."""
        from services.scheduled.storage_fee import _accrue_for_note

        note = self._note(created_days_ago=20, total_cartons=10)
        with (
            patch("services.scheduled.storage_fee._sum_cartons_picked", return_value=3),
            patch(
                "services.scheduled.storage_fee.execute_write_with_tenant",
                return_value=None,  # conflict → no row returned
            ),
        ):
            result = _accrue_for_note(TENANT_ID, note, _GRACE_PERIOD, _DAILY_RATE, date.today())
            assert result is False


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
        # Use real "now" so that (date.today() - created_at.date()).days == days_old
        created_at = datetime.now(UTC) - timedelta(days=days_old)
        return {
            "id": "note-001",
            "customer_id": "customer-001",
            "reference_number": "RN-001",
            "total_cartons": 10,
            "created_at": created_at,
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
