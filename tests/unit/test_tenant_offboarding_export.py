"""Offboarding queues the tenant's data export; platform admins follow it and download it (audit BE-10)."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from services.tenant_management import handler, service
from shared import tenant_export
from shared.exceptions import BusinessRuleViolationError
from shared.tenant_context import PLATFORM_TENANT_ID, TenantContext, UserRole
from tests.patching import patch_tenant_management

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
EXPORT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OFFBOARDED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _tenant(**kw) -> dict:
    return {
        "id": TENANT,
        "slug": "acme",
        "status": "offboarded",
        "offboarded_at": OFFBOARDED_AT,
        "deletion_scheduled_at": OFFBOARDED_AT + timedelta(days=90),
        **kw,
    }


def _export(**kw) -> dict:
    return {
        "id": EXPORT,
        "tenant_id": TENANT,
        "status": "completed",
        "requested_at": OFFBOARDED_AT,
        "completed_at": datetime(2026, 11, 1, 10, 0, tzinfo=UTC),
        "attempts": 1,
        "object_key": f"{TENANT}/exports/offboarding/{EXPORT}.zip",
        "size_bytes": 2048,
        "sha256": "c" * 64,
        "row_counts": {"billing": 3, "customer": 4},
        **kw,
    }


class TestOffboardingQueuesTheExport:
    def test_the_status_change_and_the_export_commit_together(self):
        order: list[str] = []

        @contextmanager
        def transaction(tenant_id):
            assert tenant_id == PLATFORM_TENANT_ID
            order.append("begin")
            yield
            order.append("commit")

        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=_tenant(status="active")),
            patch("services.tenant_management.tenants.tenant_transaction", transaction),
            patch.object(service.repo, "set_tenant_status", side_effect=lambda *a: order.append("status") or _tenant()),
            patch.object(
                tenant_export, "queue_export", side_effect=lambda *a, **k: order.append("queue") or {"id": EXPORT}
            ) as queue,
            patch.object(service.repo, "list_users", return_value=[]),
            patch.object(service.repo, "insert_platform_audit") as audit,
        ):
            service.offboard_tenant(TENANT, actor_id="admin-1", reason="Contract ended")

        assert order == ["begin", "status", "queue", "commit"]
        queue.assert_called_once_with(TENANT, requested_by="admin-1")
        assert audit.call_args.kwargs["details"] == {"reason": "Contract ended", "export_id": EXPORT}

    def test_reactivation_drops_an_export_that_has_not_been_written(self):
        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=_tenant()),
            patch.object(service.repo, "reactivate_tenant", return_value=_tenant(status="active")),
            patch.object(tenant_export, "cancel_open_exports") as cancel,
            patch.object(service.repo, "insert_platform_audit"),
            patch("services.tenant_management.tenants.publish_event"),
        ):
            service.reactivate_tenant(TENANT, actor_id="admin-1")
        cancel.assert_called_once_with(TENANT)


class TestExportStatus:
    def _status(self, export, tenant=None):
        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant or _tenant()),
            patch.object(tenant_export, "latest_export", return_value=export),
        ):
            return service.get_offboarding_export(TENANT)

    def test_a_completed_export_says_how_big_it_is_and_when_the_data_goes(self):
        status = self._status(_export())
        assert status["status"] == "completed" and status["export_id"] == EXPORT
        assert status["size_bytes"] == 2048 and status["row_count"] == 7 and status["sha256"] == "c" * 64
        assert status["deletion_scheduled_at"] == OFFBOARDED_AT + timedelta(days=90)
        assert status["can_queue"] is False

    def test_an_export_from_an_earlier_offboarding_does_not_count(self):
        status = self._status(_export(requested_at=OFFBOARDED_AT - timedelta(days=200)))
        assert status["status"] == "none" and status["can_queue"] is True

    def test_a_failed_export_with_attempts_left_is_retrying_and_cannot_be_requeued(self):
        status = self._status(_export(status="failed", attempts=1, object_key=None))
        assert status["retrying"] is True and status["can_queue"] is False

    def test_a_failed_export_that_gave_up_can_be_queued_again(self):
        status = self._status(_export(status="failed", attempts=3, object_key=None))
        assert status["retrying"] is False and status["can_queue"] is True

    def test_an_active_tenant_has_no_export(self):
        status = self._status(_export(), tenant=_tenant(status="active"))
        assert status["status"] == "none" and status["can_queue"] is False


class TestQueueingAnExport:
    def _queue(self, status: dict, tenant=None, queued=None):
        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=tenant or _tenant()),
            patch(
                "services.tenant_management.offboarding_export.get_offboarding_export",
                side_effect=[status, {**status, "status": "pending"}],
            ),
            patch.object(tenant_export, "queue_export", return_value=queued) as queue,
            patch.object(tenant_export, "mark_cancelled") as cancelled,
            patch.object(service.repo, "insert_platform_audit") as audit,
        ):
            result = service.queue_offboarding_export(TENANT, actor_id="admin-1")
        return result, queue, cancelled, audit

    def test_a_tenant_with_none_gets_one_and_it_is_audited(self):
        result, queue, cancelled, audit = self._queue(
            {"status": "none", "can_queue": True, "export_id": None}, queued={"id": EXPORT}
        )
        assert result["status"] == "pending"
        queue.assert_called_once_with(TENANT, requested_by="admin-1")
        cancelled.assert_not_called()
        assert audit.call_args.kwargs["action"] == "TENANT_EXPORT_QUEUED"

    def test_an_export_that_gave_up_is_closed_before_the_new_one(self):
        _, _, cancelled, _ = self._queue({"status": "failed", "can_queue": True, "export_id": EXPORT}, queued={"id": "new"})
        cancelled.assert_called_once_with(EXPORT)

    @pytest.mark.parametrize("status", ["pending", "running", "completed"])
    def test_one_in_progress_or_done_is_not_queued_again(self, status):
        with pytest.raises(BusinessRuleViolationError) as raised:
            self._queue({"status": status, "can_queue": False, "export_id": EXPORT})
        assert raised.value.rule_id == "OFFBOARDING_EXPORT_IN_PROGRESS"

    def test_an_active_tenant_cannot_have_one(self):
        with pytest.raises(BusinessRuleViolationError) as raised:
            self._queue({"status": "none", "can_queue": False, "export_id": None}, tenant=_tenant(status="active"))
        assert raised.value.rule_id == "OFFBOARDING_EXPORT_NOT_OFFBOARDED"


class TestDownloadLink:
    def _link(self, export, audit_fails: bool = False):
        storage = MagicMock()
        storage.presigned_get_url.return_value = "https://storage.test/signed"
        audit = patch.object(service.repo, "insert_platform_audit", side_effect=RuntimeError("db down") if audit_fails else None)
        with (
            patch.object(service.repo, "get_tenant_by_id", return_value=_tenant()),
            patch.object(tenant_export, "latest_export", return_value=export),
            patch("services.tenant_management.offboarding_export.get_storage_provider", return_value=storage),
            audit as audit_mock,
        ):
            result = service.create_offboarding_export_link(TENANT, actor_id="admin-1", ip_address="203.0.113.9")
        return result, storage, audit_mock

    def test_the_link_lasts_five_minutes_downloads_as_a_file_and_is_audited(self):
        result, storage, audit = self._link(_export())
        storage.presigned_get_url.assert_called_once_with(
            f"{TENANT}/exports/offboarding/{EXPORT}.zip",
            expires_in=300,
            response_content_disposition='attachment; filename="shipx-export-acme-20261101.zip"',
        )
        assert result["download_url"] == "https://storage.test/signed" and result["sha256"] == "c" * 64
        kwargs = audit.call_args.kwargs
        assert kwargs["action"] == "TENANT_EXPORT_LINK_ISSUED" and kwargs["actor_id"] == "admin-1"
        assert kwargs["details"] == {"export_id": EXPORT} and kwargs["ip_address"] == "203.0.113.9"

    @pytest.mark.parametrize("status", ["pending", "running", "failed", "cancelled"])
    def test_there_is_no_link_before_the_export_completes(self, status):
        with pytest.raises(BusinessRuleViolationError) as raised:
            self._link(_export(status=status))
        assert raised.value.rule_id == "OFFBOARDING_EXPORT_NOT_READY"

    @pytest.mark.parametrize(
        "key",
        [
            f"cccccccc-cccc-cccc-cccc-cccccccccccc/exports/offboarding/{EXPORT}.zip",  # another tenant's folder
            f"{TENANT}/claims/x.jpg",  # outside the export folder
            f"{TENANT}/exports/offboarding/../../other/file.zip",
        ],
    )
    def test_a_key_outside_this_tenants_export_folder_is_never_signed(self, key):
        with pytest.raises(BusinessRuleViolationError):
            _, storage, _ = self._link(_export(object_key=key))

    def test_no_audit_record_means_no_link(self):
        with pytest.raises(RuntimeError):
            self._link(_export(), audit_fails=True)


def _event(method: str, path: str) -> dict:
    return {
        "requestContext": {"requestId": "r1", "http": {"method": method, "path": path}},
        "headers": {},
        "body": json.dumps({}) if method == "POST" else None,
        "cookies": [],
    }


def _ctx(role: UserRole) -> TenantContext:
    platform = role == UserRole.PLATFORM_ADMIN
    return TenantContext(
        tenant_id=PLATFORM_TENANT_ID if platform else TENANT,
        user_id="admin-1",
        role=role,
        platform_user_id="pu-1" if platform else None,
        platform_role="owner" if platform else None,
    )


class TestRoutes:
    BASE = f"/v1/platform/tenants/{TENANT}/offboarding-export"

    @pytest.mark.parametrize(
        ("method", "path", "function"),
        [
            ("GET", BASE, "get_offboarding_export"),
            ("POST", BASE, "queue_offboarding_export"),
            ("POST", f"{BASE}/link", "create_offboarding_export_link"),
        ],
    )
    def test_each_route_reaches_its_service_function_for_a_platform_admin(self, method, path, function):
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(UserRole.PLATFORM_ADMIN)),
            patch.object(service, function, return_value={"status": "completed"}) as call,
        ):
            response = handler.lambda_handler(_event(method, path), None)
        assert response["statusCode"] == 200
        assert call.call_args.args[0] == TENANT

    @pytest.mark.parametrize("role", [UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF, UserRole.CUSTOMER])
    def test_nobody_else_can_reach_them(self, role):
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(role)),
            patch_tenant_management("create_offboarding_export_link") as link,
        ):
            response = handler.lambda_handler(_event("POST", f"{self.BASE}/link"), None)
        assert response["statusCode"] == 403
        link.assert_not_called()

    def test_a_tenant_id_that_is_not_a_uuid_is_a_404(self):
        with (
            patch.object(handler, "get_tenant_context", return_value=_ctx(UserRole.PLATFORM_ADMIN)),
            patch_tenant_management("get_offboarding_export") as status,
        ):
            response = handler.lambda_handler(_event("GET", "/v1/platform/tenants/not-a-uuid/offboarding-export"), None)
        assert response["statusCode"] == 404
        status.assert_not_called()
