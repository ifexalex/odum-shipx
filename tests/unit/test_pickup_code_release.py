"""A release note's pickup code: issuing it, checking it at pickup, locking after wrong guesses, reissuing (audit UX-09)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from services.payment_release import handler, service
from shared import pickup_code
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError, ServiceUnavailableError
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NOTE_ID = "11111111-1111-1111-1111-111111111111"
PEPPER = "unit-test-pepper-0123456789"


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("PICKUP_CODE_PEPPER", PEPPER)


def _ctx(role=UserRole.NIGERIA_OFFICE_STAFF) -> TenantContext:
    return TenantContext(tenant_id=TENANT, user_id="user-1", role=role)


def _note(**kw) -> dict:
    return {
        "id": NOTE_ID,
        "customer_id": "cust-1",
        "reference_number": "ACME-RN-1",
        "status": "active",
        "total_cartons": 4,
        "container_id": "k1",
        **kw,
    }


CONTACT = {"id": "cust-1", "name": "Ngozi", "phone": "+2348012345678", "email": "n@example.test", "locale": "en"}


class TestIssuing:
    @staticmethod
    def _issue(contact=CONTACT, *, enqueue_returns=True, enqueue_side_effect=None, note=None):
        note = note if note is not None else _note()
        with (
            patch.object(service.repo, "get_customer_contact", return_value=contact),
            patch.object(service.repo, "set_pickup_code", return_value={"id": NOTE_ID}) as store,
            patch.object(service, "enqueue_notification", return_value=enqueue_returns, side_effect=enqueue_side_effect) as send,
        ):
            channels = service._issue_pickup_code(TENANT, note)
        return channels, note, store, send

    def test_the_code_goes_to_the_customer_by_sms_and_email(self):
        channels, _, _, send = self._issue()
        assert channels == ["sms", "email"]
        assert {c.kwargs["channel"] for c in send.call_args_list} == {"sms", "email"}
        assert {c.kwargs["recipient"] for c in send.call_args_list} == {"+2348012345678", "n@example.test"}
        assert all(c.kwargs["template_id"] == "pickup_code_issued" for c in send.call_args_list)

    def test_what_is_stored_is_the_keyed_hash_of_what_was_sent_never_the_code(self):
        _, note, store, send = self._issue()
        code = send.call_args_list[0].kwargs["template_vars"]["pickup_code"]
        stored = store.call_args.args[2]
        assert code not in stored and len(code) == 6
        assert pickup_code.matches(NOTE_ID, code, stored)
        assert note["pickup_code_hash"] == stored and note["pickup_code_failed_attempts"] == 0

    def test_both_messages_carry_the_same_code(self):
        _, _, _, send = self._issue()
        assert len({c.kwargs["template_vars"]["pickup_code"] for c in send.call_args_list}) == 1

    def test_a_customer_with_only_a_phone_gets_an_sms(self):
        channels, _, _, send = self._issue({**CONTACT, "email": None})
        assert channels == ["sms"] and send.call_count == 1

    def test_a_customer_with_only_an_email_gets_an_email(self):
        channels, _, _, _ = self._issue({**CONTACT, "phone": ""})
        assert channels == ["email"]

    def test_the_customers_language_is_used(self):
        _, _, _, send = self._issue({**CONTACT, "locale": "zh"})
        assert all(c.kwargs["locale"] == "zh" for c in send.call_args_list)

    def test_with_nobody_to_send_it_to_the_note_gets_no_code(self):
        channels, note, store, send = self._issue({**CONTACT, "phone": None, "email": None})
        assert channels == [] and not store.called and not send.called
        assert "pickup_code_hash" not in note

    def test_no_customer_record_means_no_code(self):
        channels, _, store, _ = self._issue(contact=None)
        assert channels == [] and not store.called

    def test_when_nothing_could_be_enqueued_the_note_is_put_back_without_a_code(self):
        """Requiring a code nobody received would only stop the collection."""
        channels, note, store, _ = self._issue(enqueue_returns=False)
        assert channels == []
        assert store.call_args_list[-1].args[2] is None, "the hash must be cleared again"
        assert "pickup_code_hash" not in note

    def test_a_failing_queue_never_breaks_the_release_note(self):
        channels, _, store, _ = self._issue(enqueue_side_effect=RuntimeError("queue down"))
        assert channels == [] and store.call_args_list[-1].args[2] is None

    def test_a_failure_anywhere_is_swallowed(self):
        with patch.object(service.repo, "get_customer_contact", side_effect=RuntimeError("db down")):
            assert service._issue_pickup_code(TENANT, _note()) == []

    def test_without_a_pepper_nothing_is_issued_and_nothing_is_stored(self, monkeypatch):
        monkeypatch.delenv("PICKUP_CODE_PEPPER")
        with (
            patch.object(service.repo, "get_customer_contact") as contact,
            patch.object(service.repo, "set_pickup_code") as store,
            patch.object(service, "enqueue_notification") as send,
        ):
            assert service._issue_pickup_code(TENANT, _note()) == []
        assert not contact.called and not store.called and not send.called

    def test_the_code_is_never_logged_or_audited(self, caplog):
        with caplog.at_level("DEBUG"), patch.object(service, "log_audit") as audit:
            _, _, _, send = self._issue()
        code = send.call_args_list[0].kwargs["template_vars"]["pickup_code"]
        assert code not in caplog.text
        assert not audit.called


class TestIssuedAtCreation:
    """Every way a release note comes into being gives it a code."""

    def test_generate_split_and_reissue_each_issue_one(self):
        import inspect

        for fn in (service.generate_release_note, service.split_release_note, service.reissue_release_note):
            assert "_issue_pickup_code(" in inspect.getsource(fn), fn.__name__


class TestVerifyAtPickup:
    @staticmethod
    def _note_with_code(code="048213", failed=0, **kw):
        return _note(pickup_code_hash=pickup_code.hash_code(NOTE_ID, code), pickup_code_failed_attempts=failed, **kw)

    def _verify(self, note, entered):
        with (
            patch.object(
                service.repo,
                "record_failed_pickup_code",
                side_effect=lambda t, n: int(note.get("pickup_code_failed_attempts") or 0) + 1,
            ) as failed,
            patch.object(service.repo, "reset_pickup_code_attempts") as reset,
            patch.object(service, "log_audit") as audit,
            patch.object(service, "notify_staff") as notify,
        ):
            try:
                service._verify_pickup_code(TENANT, note, entered, "u", _ctx(UserRole.WAREHOUSE_ATTENDANT))
                outcome = None
            except BusinessRuleViolationError as exc:
                outcome = exc
        return outcome, failed, reset, audit, notify

    def test_the_right_code_passes(self):
        outcome, failed, _, _, _ = self._verify(self._note_with_code(), "048213")
        assert outcome is None and not failed.called

    @pytest.mark.parametrize("typed", ["048 213", "048-213"])
    def test_however_the_attendant_typed_it(self, typed):
        assert self._verify(self._note_with_code(), typed)[0] is None

    def test_a_wrong_code_is_refused_counted_and_audited_without_the_code(self):
        outcome, failed, _, audit, _ = self._verify(self._note_with_code(), "987654")
        assert outcome.rule_id == "PICKUP_CODE_INVALID"
        assert "4 tries left" in outcome.message
        assert failed.call_count == 1
        assert audit.call_args.kwargs["after_state"] == {"pickup_code_failed_attempts": 1}
        assert "987654" not in str(audit.call_args) and "987654" not in outcome.message

    def test_no_code_at_all_is_asked_for_and_does_not_count_as_a_guess(self):
        outcome, failed, _, _, _ = self._verify(self._note_with_code(), "")
        assert outcome.rule_id == "PICKUP_CODE_REQUIRED" and not failed.called

    def test_the_last_try_says_so(self):
        outcome, _, _, _, _ = self._verify(self._note_with_code(failed=3), "987654")
        assert "1 try left" in outcome.message

    def test_the_fifth_wrong_code_locks_the_note_and_tells_staff(self):
        outcome, _, _, _, notify = self._verify(self._note_with_code(failed=4), "987654")
        assert outcome.rule_id == "PICKUP_CODE_LOCKED"
        assert {c.kwargs["target_role"] for c in notify.call_args_list} == {"nigeria_office_staff", "tenant_admin"}
        assert notify.call_args.kwargs["event_type"] == "pickup_code_locked"

    def test_a_locked_note_refuses_even_the_right_code(self):
        outcome, failed, _, _, _ = self._verify(self._note_with_code(failed=5), "048213")
        assert outcome.rule_id == "PICKUP_CODE_LOCKED" and not failed.called

    def test_a_right_code_forgets_earlier_wrong_ones(self):
        _, _, reset, _, _ = self._verify(self._note_with_code(failed=2), "048213")
        reset.assert_called_once()

    def test_a_note_with_a_clean_record_is_not_written_to(self):
        _, _, reset, _, _ = self._verify(self._note_with_code(), "048213")
        assert not reset.called

    def test_a_code_for_another_note_does_not_work(self):
        note = _note(pickup_code_hash=pickup_code.hash_code("22222222-2222-2222-2222-222222222222", "048213"))
        assert self._verify(note, "048213")[0].rule_id == "PICKUP_CODE_INVALID"

    def test_if_the_system_cannot_check_codes_the_pickup_is_refused_not_waved_through(self, monkeypatch):
        note = self._note_with_code()  # hashed while the pepper is still set
        monkeypatch.delenv("PICKUP_CODE_PEPPER")
        with pytest.raises(ServiceUnavailableError):
            service._verify_pickup_code(TENANT, note, "048213", "u", _ctx())


class TestRecordPickupUsesIt:
    @staticmethod
    def _req(code):
        req = MagicMock()
        req.is_delegate = False
        req.collected_by_name = "Baba Sunny"
        req.delegate_name = req.delegate_phone = req.delegate_id_type = req.delegate_id_number = None
        req.cartons_released = 2
        req.carton_tags_picked = []
        req.warehouse_id = req.customer_service_officer_id = req.accounting_officer_id = req.warehouse_attendant_id = None
        req.notes = None
        req.pickup_code = code
        return req

    def _pickup(self, note, code):
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=note),
            patch.object(
                service.repo, "create_pickup_record", return_value={"id": "pu-1", "pickup_date": "2026-11-16", "created_at": None}
            ) as create,
            patch.object(service.repo, "sum_cartons_picked_for_release_note", return_value=2),
            patch.object(service.repo, "update_release_note_status"),
            patch.object(service.repo, "sum_cartons_released_for_customer", return_value=0),
            patch.object(service.repo, "sum_total_cartons_from_billing", return_value=0),
            patch.object(service.repo, "sum_cartons_released_for_container", return_value=0),
            patch.object(service.repo, "update_container_status"),
            patch.object(service.repo, "get_tenant_user_name", return_value="Attendant"),
            patch.object(service.repo, "record_failed_pickup_code", return_value=1),
            patch.object(service.repo, "reset_pickup_code_attempts"),
            patch.object(service, "log_audit") as audit,
            patch.object(service, "notify_staff"),
        ):
            try:
                result = service.record_pickup(
                    TENANT, NOTE_ID, self._req(code), actor_id="u", ctx=_ctx(UserRole.WAREHOUSE_ATTENDANT)
                )
            except BusinessRuleViolationError as exc:
                result = exc
        return result, create, audit

    def test_a_note_with_a_code_needs_it_and_nothing_is_recorded_without_it(self):
        note = _note(total_cartons=2, pickup_code_hash=pickup_code.hash_code(NOTE_ID, "048213"), pickup_code_failed_attempts=0)
        result, create, _ = self._pickup(note, None)
        assert result.rule_id == "PICKUP_CODE_REQUIRED" and not create.called

    def test_a_wrong_code_records_no_pickup(self):
        note = _note(total_cartons=2, pickup_code_hash=pickup_code.hash_code(NOTE_ID, "048213"), pickup_code_failed_attempts=0)
        result, create, _ = self._pickup(note, "999999")
        assert result.rule_id == "PICKUP_CODE_INVALID" and not create.called

    def test_the_right_code_records_the_pickup_and_the_audit_says_it_was_checked(self):
        note = _note(total_cartons=2, pickup_code_hash=pickup_code.hash_code(NOTE_ID, "048213"), pickup_code_failed_attempts=0)
        result, create, audit = self._pickup(note, "048213")
        assert result["release_note_status"] == "picked_up" and create.called
        pickup_audit = next(c for c in audit.call_args_list if c.kwargs["entity_type"] == "pickup_record")
        assert pickup_audit.kwargs["after_state"]["pickup_code_verified"] is True
        assert "048213" not in str(audit.call_args_list)

    def test_a_note_issued_before_codes_still_needs_none(self):
        result, create, audit = self._pickup(_note(total_cartons=2), None)
        assert result["release_note_status"] == "picked_up" and create.called
        pickup_audit = next(c for c in audit.call_args_list if c.kwargs["entity_type"] == "pickup_record")
        assert pickup_audit.kwargs["after_state"]["pickup_code_verified"] is False


class TestReissue:
    @staticmethod
    def _reissue(note, *, channels=("sms", "email")):
        with (
            patch.object(service.repo, "get_release_note_by_id", return_value=note),
            patch.object(service, "_issue_pickup_code", return_value=list(channels)) as issue,
            patch.object(service, "log_audit") as audit,
        ):
            try:
                result = service.reissue_pickup_code(TENANT, NOTE_ID, "u", _ctx())
            except (BusinessRuleViolationError, ResourceNotFoundError) as exc:
                result = exc
        return result, issue, audit

    def test_it_says_where_the_new_code_went_and_never_what_it_is(self):
        result, _, audit = self._reissue(_note())
        assert result == {"release_note_id": NOTE_ID, "sent_via": ["sms", "email"]}
        assert audit.call_args.kwargs["after_state"] == {"pickup_code_reissued": True, "sent_via": ["sms", "email"]}

    @pytest.mark.parametrize("status", ["picked_up", "expired", "cancelled"])
    def test_only_an_active_note_can_have_a_code_reissued(self, status):
        result, issue, _ = self._reissue(_note(status=status))
        assert result.rule_id == "RELEASE_NOTE_NOT_ACTIVE" and not issue.called

    def test_a_note_that_does_not_exist_is_a_404(self):
        with patch.object(service.repo, "get_release_note_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.reissue_pickup_code(TENANT, NOTE_ID, "u", _ctx())

    def test_if_the_code_cannot_be_delivered_that_is_an_error_not_a_silent_success(self):
        result, _, audit = self._reissue(_note(), channels=())
        assert result.rule_id == "PICKUP_CODE_NOT_DELIVERABLE" and not audit.called

    def test_without_a_pepper_it_says_codes_are_not_set_up(self, monkeypatch):
        monkeypatch.delenv("PICKUP_CODE_PEPPER")
        with pytest.raises(BusinessRuleViolationError) as caught:
            service.reissue_pickup_code(TENANT, NOTE_ID, "u", _ctx())
        assert caught.value.rule_id == "PICKUP_CODES_NOT_CONFIGURED"


class TestWhatTheApiShows:
    def test_a_note_with_a_code_says_it_needs_one_but_never_shows_it(self):
        body = service._fmt_release_note(
            _note(pickup_code_hash="abc", pickup_code_failed_attempts=2, created_at="x", is_partial=False), {"status": "paid"}, 4
        )
        assert body["pickup_code_required"] is True and body["pickup_code_locked"] is False
        assert "abc" not in json.dumps(body, default=str)
        assert not any("hash" in key for key in body)

    def test_a_locked_note_says_so(self):
        body = service._fmt_release_note(_note(pickup_code_hash="abc", pickup_code_failed_attempts=5, created_at="x"), {}, 4)
        assert body["pickup_code_locked"] is True

    def test_a_note_without_a_code_needs_none(self):
        body = service._fmt_release_note(_note(created_at="x"), {}, 4)
        assert body["pickup_code_required"] is False and body["pickup_code_locked"] is False

    def test_a_finished_note_no_longer_asks_for_one(self):
        body = service._fmt_release_note(_note(status="picked_up", pickup_code_hash="abc", created_at="x"), {}, 4)
        assert body["pickup_code_required"] is False


class TestRoute:
    @staticmethod
    def _call(role):
        event = {
            "requestContext": {
                "requestId": "r1",
                "http": {"method": "POST", "path": f"/v1/release-notes/{NOTE_ID}/pickup-code"},
                "authorizer": {"claims": {"sub": "user-1", "custom:tenant_id": TENANT}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": None,
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(role)),
            patch.object(
                service, "reissue_pickup_code", return_value={"release_note_id": NOTE_ID, "sent_via": ["sms"]}
            ) as reissue,
        ):
            return handler.lambda_handler(event, None), reissue

    @pytest.mark.parametrize("role", [UserRole.NIGERIA_OFFICE_STAFF, UserRole.TENANT_ADMIN])
    def test_staff_who_can_reissue_a_note_can_reissue_its_code(self, role):
        response, reissue = self._call(role)
        assert response["statusCode"] == 200 and reissue.called

    @pytest.mark.parametrize("role", [UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER, UserRole.CHINA_OFFICE_STAFF])
    def test_nobody_else_can(self, role):
        response, reissue = self._call(role)
        assert response["statusCode"] == 403 and not reissue.called
