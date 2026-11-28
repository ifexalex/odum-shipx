"""Unit tests for the staff notification bell (migration 046).

Ground-truth gap found live, reported by the user: "a staff rejected a
payment marked as paid, but no notification was showing when I logged into
the staff account." Follow-up: "let's go through the whole notification
including the frontend notification to resolve all" — the TopBar bell icon
was fully built in the frontend but never fed any data, and no backing
table or API existed. `shared/staff_notifications.py::notify_staff` is
modeled directly on `shared/audit.py::log_audit`: it never raises, so every
call site below is safe to call unmocked in its own tests.
"""

import json
from unittest.mock import patch

import pytest

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _ctx(role=None):
    from shared.tenant_context import TenantContext, UserRole

    return TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=role or UserRole.NIGERIA_OFFICE_STAFF)


class TestNotifyStaffNeverRaises:
    """Same contract as log_audit — a failure to write a staff notification
    must never break the primary business operation that triggered it."""

    def test_a_db_failure_is_swallowed(self):
        from shared.staff_notifications import notify_staff

        with patch("shared.db.execute_write_with_tenant", side_effect=RuntimeError("db down")):
            notify_staff(
                tenant_id=TENANT_ID,
                event_type="payment_claim_submitted",
                entity_type="payment_claim",
                title="New payment claim submitted",
                target_role="nigeria_office_staff",
            )
        # No exception propagated — that's the whole test.

    def test_writes_the_expected_row(self):
        from shared.staff_notifications import notify_staff

        with patch("shared.db.execute_write_with_tenant", return_value={"id": "notif-1"}) as mock_write:
            notify_staff(
                tenant_id=TENANT_ID,
                event_type="damage_claim_filed",
                entity_type="damage_claim",
                entity_id="claim-001",
                title="New damage claim filed",
                body="Claim DC-001 needs inspection.",
                target_role="nigeria_office_staff",
            )

        query, params = mock_write.call_args[0][1], mock_write.call_args[0][2]
        assert "INSERT INTO staff_notification" in query
        assert params["tenant_id"] == TENANT_ID
        assert params["event_type"] == "damage_claim_filed"
        assert params["entity_id"] == "claim-001"
        assert params["target_role"] == "nigeria_office_staff"
        assert params["target_user_id"] is None


class TestStaffNotificationRepository:
    def test_list_includes_visibility_filter(self):
        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_staff_notifications(TENANT_ID, USER_ID, "nigeria_office_staff", limit=20, cursor=None)

        query, params = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
        assert "sn.target_user_id = %(user_id)s" in query
        assert "sn.target_role = %(role)s" in query
        assert "sn.target_role IS NULL" in query
        assert params["user_id"] == USER_ID
        assert params["role"] == "nigeria_office_staff"

    def test_unread_only_adds_the_read_join_filter(self):
        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_staff_notifications(
                TENANT_ID,
                USER_ID,
                "nigeria_office_staff",
                limit=20,
                cursor=None,
                unread_only=True,
            )

        query = mock_exec.call_args[0][1]
        assert "r.notification_id IS NULL" in query

    def test_default_list_does_not_filter_by_read_state(self):
        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_staff_notifications(TENANT_ID, USER_ID, "nigeria_office_staff", limit=20, cursor=None)

        query = mock_exec.call_args[0][1]
        # The is_read column is still selected — just not filtered on.
        assert "AS is_read" in query
        assert "unread_clause" not in query  # sanity: no leftover template artifact

    def test_count_unread_uses_the_same_visibility_and_unread_filter(self):
        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[{"cnt": 3}]) as mock_exec:
            result = repository.count_unread_staff_notifications(TENANT_ID, USER_ID, "tenant_admin")

        assert result == 3
        query = mock_exec.call_args[0][1]
        assert "r.notification_id IS NULL" in query
        assert "sn.target_role = %(role)s" in query

    def test_mark_read_is_idempotent_via_on_conflict(self):
        from services.notification import repository

        with patch.object(repository, "execute_write_with_tenant", return_value={"notification_id": "n1"}) as mock_write:
            repository.mark_staff_notification_read(TENANT_ID, "n1", USER_ID)

        query = mock_write.call_args[0][1]
        assert "ON CONFLICT (notification_id, user_id) DO UPDATE" in query

    def test_mark_all_read_only_touches_unread_visible_rows(self):
        from services.notification import repository

        with patch(
            "shared.db.execute_write_with_tenant_many", return_value=[{"notification_id": "n1"}, {"notification_id": "n2"}]
        ) as mock_write:
            count = repository.mark_all_staff_notifications_read(TENANT_ID, USER_ID, "nigeria_office_staff")

        assert count == 2
        query = mock_write.call_args[0][1]
        assert "r.notification_id IS NULL" in query
        assert "ON CONFLICT (notification_id, user_id) DO NOTHING" in query


class TestStaffNotificationService:
    def test_mark_read_404s_for_unknown_notification(self):
        import pytest

        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        with patch("services.notification.repository.get_staff_notification_by_id", return_value=None):
            with pytest.raises(ResourceNotFoundError):
                service.mark_staff_notification_read(TENANT_ID, "missing-id", USER_ID)

    def test_mark_read_returns_the_read_row(self):
        from services.notification import service

        with (
            patch("services.notification.repository.get_staff_notification_by_id", return_value={"id": "n1"}),
            patch(
                "services.notification.repository.mark_staff_notification_read",
                return_value={"notification_id": "n1", "user_id": USER_ID},
            ),
        ):
            result = service.mark_staff_notification_read(TENANT_ID, "n1", USER_ID)

        assert result["notification_id"] == "n1"


class TestStaffNotificationHandler:
    def _event(self, method: str, path: str, query: dict | None = None, role: str = "nigeria_office_staff") -> dict:
        return {
            "requestContext": {
                "requestId": "req-staff-notif-001",
                "http": {"method": method, "path": path},
                "authorizer": {
                    "claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID, "cognito:groups": f"{TENANT_ID}:{role}"}
                },
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def test_list_route_calls_service_with_ctx_identity(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "list_staff_notifications", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/staff"), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[0][0] == TENANT_ID
        assert mock_list.call_args[0][1] == USER_ID

    def test_unread_count_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "count_unread_staff_notifications", return_value={"unread_count": 5}) as mock_count,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/staff/unread-count"), None)

        assert resp["statusCode"] == 200
        mock_count.assert_called_once()

    def test_mark_all_read_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "mark_all_staff_notifications_read", return_value={"marked_read": 2}) as mock_mark,
        ):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/staff/mark-all-read"), None)

        assert resp["statusCode"] == 200
        mock_mark.assert_called_once()

    def test_mark_one_read_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "mark_staff_notification_read", return_value={"notification_id": "n1"}) as mock_mark,
        ):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/staff/n1/read"), None)

        assert resp["statusCode"] == 200
        mock_mark.assert_called_once_with(TENANT_ID, "n1", USER_ID, role="nigeria_office_staff")

    def test_customer_role_is_forbidden(self):
        from services.notification import handler
        from shared.tenant_context import TenantContext, UserRole

        customer_ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.CUSTOMER)
        with patch("services.notification.handler.get_tenant_context", return_value=customer_ctx):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/staff"), None)

        assert resp["statusCode"] == 403


class TestCustomerNotificationHandler:
    """Ground-truth follow-up, reported live by the user: they rejected a
    payment claim and, checking as the customer, "did not see the
    notification when I logged in" — reuses the exact same service
    functions as the staff bell, mounted at /v1/notifications/customer/...
    and role-gated to CUSTOMER only."""

    def _event(self, method: str, path: str, query: dict | None = None) -> dict:
        return {
            "requestContext": {
                "requestId": "req-customer-notif-001",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": query or {},
            "pathParameters": {},
        }

    def _customer_ctx(self):
        from shared.tenant_context import TenantContext, UserRole

        return TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.CUSTOMER)

    def test_list_route_calls_the_same_service_function_as_the_staff_bell(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=self._customer_ctx()),
            patch.object(service, "list_staff_notifications", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/customer"), None)

        assert resp["statusCode"] == 200
        assert mock_list.call_args[0][0] == TENANT_ID
        assert mock_list.call_args[0][1] == USER_ID

    def test_unread_count_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=self._customer_ctx()),
            patch.object(service, "count_unread_staff_notifications", return_value={"unread_count": 1}) as mock_count,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/customer/unread-count"), None)

        assert resp["statusCode"] == 200
        mock_count.assert_called_once()

    def test_mark_one_read_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=self._customer_ctx()),
            patch.object(service, "mark_staff_notification_read", return_value={"notification_id": "n1"}) as mock_mark,
        ):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/customer/n1/read"), None)

        assert resp["statusCode"] == 200
        mock_mark.assert_called_once_with(TENANT_ID, "n1", USER_ID, role="customer")

    def test_mark_all_read_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=self._customer_ctx()),
            patch.object(service, "mark_all_staff_notifications_read", return_value={"marked_read": 3}) as mock_mark,
        ):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/customer/mark-all-read"), None)

        assert resp["statusCode"] == 200
        mock_mark.assert_called_once()

    def test_staff_role_is_forbidden_on_the_customer_route(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/customer"), None)

        assert resp["statusCode"] == 403


class TestStaffNotificationRepositoryDismiss:
    """Ground-truth follow-up, reported directly by the user: "the
    notification should allow clearing." Clearing is per-viewer (like read
    state) — dismissing a role-broadcast notification for one recipient
    must never remove it from any other recipient's list."""

    def test_list_excludes_dismissed_notifications(self):
        from services.notification import repository

        with patch.object(repository, "execute_with_tenant", return_value=[]) as mock_exec:
            repository.list_staff_notifications(TENANT_ID, USER_ID, "nigeria_office_staff", limit=20, cursor=None)

        query = mock_exec.call_args[0][1]
        assert "r.dismissed_at IS NULL" in query

    def test_dismiss_one_sets_both_dismissed_at_and_read_at(self):
        from services.notification import repository

        with patch.object(repository, "execute_write_with_tenant", return_value={"notification_id": "n1"}) as mock_write:
            repository.mark_staff_notification_dismissed(TENANT_ID, "n1", USER_ID)

        query = mock_write.call_args[0][1]
        assert "dismissed_at" in query
        assert "ON CONFLICT (notification_id, user_id) DO UPDATE" in query
        assert "read_at = COALESCE(staff_notification_read.read_at, NOW())" in query

    def test_dismiss_all_only_touches_currently_visible_undismissed_rows(self):
        from services.notification import repository

        with patch("shared.db.execute_write_with_tenant_many", return_value=[{"notification_id": "n1"}]) as mock_write:
            count = repository.dismiss_all_staff_notifications(TENANT_ID, USER_ID, "nigeria_office_staff")

        assert count == 1
        query = mock_write.call_args[0][1]
        assert "r.dismissed_at IS NULL" in query
        assert "ON CONFLICT (notification_id, user_id) DO UPDATE" in query


class TestStaffNotificationHandlerDismiss:
    def _event(self, method: str, path: str) -> dict:
        return {
            "requestContext": {
                "requestId": "req-dismiss-001",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": "{}",
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def test_delete_one_calls_dismiss_staff_notification(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "dismiss_staff_notification", return_value={"notification_id": "n1"}) as mock_dismiss,
        ):
            resp = handler.http_handler(self._event("DELETE", "/v1/notifications/staff/n1"), None)

        assert resp["statusCode"] == 200
        mock_dismiss.assert_called_once_with(TENANT_ID, "n1", USER_ID, role="nigeria_office_staff")

    def test_delete_clear_all_calls_dismiss_all(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "dismiss_all_staff_notifications", return_value={"cleared": 5}) as mock_dismiss,
        ):
            resp = handler.http_handler(self._event("DELETE", "/v1/notifications/staff/clear-all"), None)

        assert resp["statusCode"] == 200
        mock_dismiss.assert_called_once()

    def test_customer_delete_one_calls_the_same_service_function(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        customer_ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.CUSTOMER)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=customer_ctx),
            patch.object(service, "dismiss_staff_notification", return_value={"notification_id": "n1"}) as mock_dismiss,
        ):
            resp = handler.http_handler(self._event("DELETE", "/v1/notifications/customer/n1"), None)

        assert resp["statusCode"] == 200
        mock_dismiss.assert_called_once_with(TENANT_ID, "n1", USER_ID, role="customer")


class TestSendAnnouncement:
    """Direct user request: "tenant admin and nigeria staff should be able
    to send announcements, for example during celebration sessions, or
    import announcements." """

    def test_all_staff_creates_one_row_per_staff_role(self):
        from services.notification import service

        with (
            patch("services.notification.repository.create_staff_notification", return_value={"id": "n1"}) as mock_create,
            patch("services.notification.repository.deactivate_active_banners_for_roles", return_value=0),
            patch("shared.audit.log_audit") as mock_audit,
        ):
            result = service.send_announcement(
                TENANT_ID,
                "Office closed for the holidays",
                "See you in January!",
                "all_staff",
                actor_id=USER_ID,
                actor_role="tenant_admin",
            )

        assert result == {"status": "sent", "audience": "all_staff", "notifications_created": 4}
        roles = {c.kwargs["target_role"] for c in mock_create.call_args_list}
        assert roles == {"tenant_admin", "nigeria_office_staff", "china_office_staff", "warehouse_attendant"}
        assert all(c.kwargs["event_type"] == "announcement" for c in mock_create.call_args_list)
        assert all(c.kwargs["banner_active"] is True for c in mock_create.call_args_list)
        group_ids = {c.kwargs["announcement_group_id"] for c in mock_create.call_args_list}
        assert len(group_ids) == 1  # all 4 role rows share one group
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["entity_type"] == "announcement"

    def test_all_customers_creates_exactly_one_row_targeted_at_the_customer_role(self):
        from services.notification import service

        with (
            patch("services.notification.repository.create_staff_notification", return_value={"id": "n1"}) as mock_create,
            patch("services.notification.repository.deactivate_active_banners_for_roles", return_value=0),
        ):
            result = service.send_announcement(
                TENANT_ID,
                "Import maintenance tonight",
                None,
                "all_customers",
                actor_id=USER_ID,
                actor_role="tenant_admin",
            )

        assert result == {"status": "sent", "audience": "all_customers", "notifications_created": 1}
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["target_role"] == "customer"

    def test_announce_route_is_forbidden_for_china_office_staff(self):
        from services.notification import handler
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.CHINA_OFFICE_STAFF)
        event = {
            "requestContext": {
                "requestId": "req-announce-001",
                "http": {"method": "POST", "path": "/v1/notifications/announce"},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"title": "Hi", "audience": "all_staff"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with patch("services.notification.handler.get_tenant_context", return_value=ctx):
            resp = handler.http_handler(event, None)

        assert resp["statusCode"] == 403

    def test_announce_route_accepts_tenant_admin_sending_to_all_staff_and_calls_the_service(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        event = {
            "requestContext": {
                "requestId": "req-announce-002",
                "http": {"method": "POST", "path": "/v1/notifications/announce"},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"title": "Happy holidays!", "body": "Office reopens Jan 2.", "audience": "all_staff"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(
                service,
                "send_announcement",
                return_value={"status": "sent", "audience": "all_staff", "notifications_created": 4},
            ) as mock_send,
        ):
            resp = handler.http_handler(event, None)

        assert resp["statusCode"] == 201
        assert mock_send.call_args.kwargs["title"] == "Happy holidays!"
        assert mock_send.call_args.kwargs["body"] == "Office reopens Jan 2."
        assert mock_send.call_args.kwargs["audience"] == "all_staff"

    def test_announce_route_forbids_nigeria_office_staff_from_targeting_all_staff(self):
        """Direct user requirement: "the staff can only send to customers"
        — staff-wide announcements are a tenant_admin-only power, not just
        an approval-required one."""
        from services.notification import handler, service

        event = {
            "requestContext": {
                "requestId": "req-announce-003b",
                "http": {"method": "POST", "path": "/v1/notifications/announce"},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"title": "Happy holidays!", "audience": "all_staff"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "send_announcement") as mock_send,
            patch.object(service, "request_announcement") as mock_request,
        ):
            resp = handler.http_handler(event, None)

        assert resp["statusCode"] == 403
        mock_send.assert_not_called()
        mock_request.assert_not_called()

    def test_announce_route_accepts_nigeria_office_staff_targeting_customers_as_a_pending_request(self):
        from services.notification import handler, service

        event = {
            "requestContext": {
                "requestId": "req-announce-004",
                "http": {"method": "POST", "path": "/v1/notifications/announce"},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"title": "Customs delay this week", "audience": "all_customers"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "send_announcement") as mock_send,
            patch.object(
                service,
                "request_announcement",
                return_value={"status": "pending", "request_id": "r1", "audience": "all_customers"},
            ) as mock_request,
        ):
            resp = handler.http_handler(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])["data"]
        assert body == {"status": "pending", "request_id": "r1", "audience": "all_customers"}
        mock_request.assert_called_once_with(
            TENANT_ID,
            title="Customs delay this week",
            body=None,
            audience="all_customers",
            actor_id=USER_ID,
        )
        mock_send.assert_not_called()

    def test_announce_route_rejects_a_missing_title(self):
        from services.notification import handler

        event = {
            "requestContext": {
                "requestId": "req-announce-003",
                "http": {"method": "POST", "path": "/v1/notifications/announce"},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": '{"audience": "all_staff"}',
            "queryStringParameters": {},
            "pathParameters": {},
        }
        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(event, None)

        assert resp["statusCode"] == 422


class TestAnnouncementRequestService:
    """Direct user requirement: "the staff can only send to customers,
    which should be approved by the tenant admins, this is to ensure that a
    compromised staff does not misinformation the customers." """

    def test_request_announcement_creates_a_pending_row_and_notifies_tenant_admins(self):
        from services.notification import service

        request_row = {"id": "req1", "title": "Customs delay", "audience": "all_customers"}
        with (
            patch("services.notification.repository.create_announcement_request", return_value=request_row),
            patch("shared.audit.log_audit") as mock_audit,
            patch("shared.staff_notifications.notify_staff") as mock_notify,
        ):
            result = service.request_announcement(
                TENANT_ID,
                "Customs delay",
                "Expect 2-day delays.",
                "all_customers",
                actor_id=USER_ID,
            )

        assert result == {"status": "pending", "request_id": "req1", "audience": "all_customers"}
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["entity_type"] == "announcement_request"
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["target_role"] == "tenant_admin"

    def test_approve_creates_notifications_and_notifies_the_requester(self):
        from services.notification import service

        pending_row = {
            "id": "req1",
            "title": "Customs delay",
            "body": "Expect 2-day delays.",
            "audience": "all_customers",
            "status": "pending",
            "requested_by": USER_ID,
        }
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=pending_row),
            patch("services.notification.repository.create_staff_notification", return_value={"id": "n1"}) as mock_create,
            patch("services.notification.repository.deactivate_active_banners_for_roles", return_value=0),
            patch(
                "services.notification.repository.mark_announcement_request_reviewed",
                return_value={**pending_row, "status": "approved"},
            ) as mock_reviewed,
            patch("shared.audit.log_audit") as mock_audit,
            patch("shared.staff_notifications.notify_staff") as mock_notify,
        ):
            result = service.approve_announcement_request(TENANT_ID, "req1", "admin1", "tenant_admin")

        assert result == {"status": "approved", "audience": "all_customers", "notifications_created": 1}
        assert mock_create.call_args.kwargs["target_role"] == "customer"
        mock_reviewed.assert_called_once_with(TENANT_ID, "req1", "approved", reviewed_by="admin1")
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "APPROVE"
        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["target_user_id"] == USER_ID

    def test_reject_marks_rejected_and_notifies_the_requester_with_the_reason(self):
        from services.notification import service

        pending_row = {
            "id": "req1",
            "title": "Customs delay",
            "body": None,
            "audience": "all_customers",
            "status": "pending",
            "requested_by": USER_ID,
        }
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=pending_row),
            patch(
                "services.notification.repository.mark_announcement_request_reviewed",
                return_value={**pending_row, "status": "rejected"},
            ) as mock_reviewed,
            patch("shared.audit.log_audit") as mock_audit,
            patch("shared.staff_notifications.notify_staff") as mock_notify,
        ):
            result = service.reject_announcement_request(
                TENANT_ID,
                "req1",
                "admin1",
                "tenant_admin",
                reason="Not accurate",
            )

        assert result == {"status": "rejected"}
        mock_reviewed.assert_called_once_with(
            TENANT_ID,
            "req1",
            "rejected",
            reviewed_by="admin1",
            rejection_reason="Not accurate",
        )
        assert mock_audit.call_args.kwargs["action"] == "REJECT"
        assert "Not accurate" in mock_notify.call_args.kwargs["body"]

    def test_approve_a_non_pending_request_raises_illegal_transition(self):
        from services.notification import service
        from shared.exceptions import IllegalTransitionError

        already_approved = {"id": "req1", "status": "approved"}
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=already_approved),
            pytest.raises(IllegalTransitionError),
        ):
            service.approve_announcement_request(TENANT_ID, "req1", "admin1", "tenant_admin")

    def test_approve_a_missing_request_raises_not_found(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=None),
            pytest.raises(ResourceNotFoundError),
        ):
            service.approve_announcement_request(TENANT_ID, "missing", "admin1", "tenant_admin")


class TestAnnouncementRequestHandler:
    def _event(self, method: str, path: str, body: str = "{}") -> dict:
        return {
            "requestContext": {
                "requestId": "req-announcement-review-001",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": body,
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def test_pending_list_route_requires_tenant_admin(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/announcements/pending"), None)

        assert resp["statusCode"] == 403

    def test_pending_list_route_calls_service_for_tenant_admin(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(service, "list_pending_announcement_requests", return_value=([], None, False)) as mock_list,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/announcements/pending"), None)

        assert resp["statusCode"] == 200
        mock_list.assert_called_once()

    def test_approve_route_requires_tenant_admin(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/announcements/requests/req1/approve"), None)

        assert resp["statusCode"] == 403

    def test_approve_route_calls_service_for_tenant_admin(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(
                service,
                "approve_announcement_request",
                return_value={"status": "approved", "audience": "all_customers", "notifications_created": 1},
            ) as mock_approve,
        ):
            resp = handler.http_handler(self._event("PATCH", "/v1/notifications/announcements/requests/req1/approve"), None)

        assert resp["statusCode"] == 200
        mock_approve.assert_called_once_with(TENANT_ID, "req1", USER_ID, "tenant_admin")

    def test_reject_route_passes_the_optional_reason_through(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(service, "reject_announcement_request", return_value={"status": "rejected"}) as mock_reject,
        ):
            resp = handler.http_handler(
                self._event(
                    "PATCH",
                    "/v1/notifications/announcements/requests/req1/reject",
                    body='{"reason": "Not accurate"}',
                ),
                None,
            )

        assert resp["statusCode"] == 200
        mock_reject.assert_called_once_with(TENANT_ID, "req1", USER_ID, "tenant_admin", reason="Not accurate")


class TestAnnouncementBanner:
    """Direct user follow-up, sent mid-review of the approval feature:
    "annoucement should be a banner on the target user's web page, with this
    they won't miss it. It can be enabled or disabled, more can be created
    but only one can be visible per time. with this. we can add amination to
    it, so that it is obvious to the target user." """

    def test_creating_an_announcement_deactivates_the_previous_banner_for_the_same_audience(self):
        from services.notification import service

        with (
            patch("services.notification.repository.create_staff_notification", return_value={"id": "n2"}),
            patch(
                "services.notification.repository.deactivate_active_banners_for_roles",
                return_value=1,
            ) as mock_deactivate,
        ):
            service.send_announcement(
                TENANT_ID,
                "Second notice",
                None,
                "all_customers",
                actor_id=USER_ID,
                actor_role="tenant_admin",
            )

        mock_deactivate.assert_called_once_with(TENANT_ID, ["customer"])

    def test_all_staff_send_deactivates_banners_for_every_staff_role(self):
        from services.notification import service

        with (
            patch("services.notification.repository.create_staff_notification", return_value={"id": "n2"}),
            patch(
                "services.notification.repository.deactivate_active_banners_for_roles",
                return_value=0,
            ) as mock_deactivate,
        ):
            service.send_announcement(
                TENANT_ID,
                "Second notice",
                None,
                "all_staff",
                actor_id=USER_ID,
                actor_role="tenant_admin",
            )

        called_roles = set(mock_deactivate.call_args.args[1])
        assert called_roles == {"tenant_admin", "nigeria_office_staff", "china_office_staff", "warehouse_attendant"}

    def test_get_active_banner_returns_none_when_nothing_is_active(self):
        from services.notification import service

        with patch("services.notification.repository.get_active_banner", return_value=None):
            result = service.get_active_banner(TENANT_ID, USER_ID, "nigeria_office_staff")

        assert result is None

    def test_get_active_banner_route_returns_the_active_row(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(
                service,
                "get_active_banner",
                return_value={"id": "n1", "title": "Customs delay", "body": None},
            ) as mock_banner,
        ):
            resp = handler.http_handler(
                {
                    "requestContext": {
                        "requestId": "req-banner-001",
                        "http": {"method": "GET", "path": "/v1/notifications/staff/banner"},
                        "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                        "identity": {"sourceIp": "127.0.0.1"},
                    },
                    "headers": {},
                    "body": None,
                    "queryStringParameters": {},
                    "pathParameters": {},
                },
                None,
            )

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"]["title"] == "Customs delay"
        mock_banner.assert_called_once_with(TENANT_ID, USER_ID, "nigeria_office_staff")

    def test_deactivate_announcement_flips_the_whole_group(self):
        from services.notification import service

        with (
            patch("services.notification.repository.set_banner_active_for_group", return_value=4) as mock_set,
            patch("shared.audit.log_audit") as mock_audit,
        ):
            result = service.deactivate_announcement(TENANT_ID, "group1", "admin1", "tenant_admin")

        assert result == {"announcement_group_id": "group1", "banner_active": False}
        mock_set.assert_called_once_with(TENANT_ID, "group1", active=False)
        assert mock_audit.call_args.kwargs["action"] == "DEACTIVATE"

    def test_deactivate_a_missing_group_raises_not_found(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        with (
            patch("services.notification.repository.set_banner_active_for_group", return_value=0),
            pytest.raises(ResourceNotFoundError),
        ):
            service.deactivate_announcement(TENANT_ID, "missing", "admin1", "tenant_admin")

    def test_activate_announcement_dedupes_against_the_same_audience_first(self):
        from services.notification import service

        with (
            patch(
                "services.notification.repository.get_announcement_group_target_roles",
                return_value=["customer"],
            ),
            patch(
                "services.notification.repository.deactivate_active_banners_for_roles",
                return_value=1,
            ) as mock_deactivate,
            patch("services.notification.repository.set_banner_active_for_group", return_value=1) as mock_set,
            patch("shared.audit.log_audit"),
        ):
            result = service.activate_announcement(TENANT_ID, "group1", "admin1", "tenant_admin")

        assert result == {"announcement_group_id": "group1", "banner_active": True}
        mock_deactivate.assert_called_once_with(TENANT_ID, ["customer"])
        mock_set.assert_called_once_with(TENANT_ID, "group1", active=True)

    def test_list_announcements_route_requires_tenant_admin(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(
                {
                    "requestContext": {
                        "requestId": "req-announcements-list-001",
                        "http": {"method": "GET", "path": "/v1/notifications/announcements"},
                        "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                        "identity": {"sourceIp": "127.0.0.1"},
                    },
                    "headers": {},
                    "body": None,
                    "queryStringParameters": {},
                    "pathParameters": {},
                },
                None,
            )

        assert resp["statusCode"] == 403

    def test_activate_and_deactivate_routes_require_tenant_admin(self):
        from services.notification import handler

        for action in ("activate", "deactivate"):
            with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
                resp = handler.http_handler(
                    {
                        "requestContext": {
                            "requestId": f"req-{action}-001",
                            "http": {"method": "PATCH", "path": f"/v1/notifications/announcements/group1/{action}"},
                            "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                            "identity": {"sourceIp": "127.0.0.1"},
                        },
                        "headers": {},
                        "body": "{}",
                        "queryStringParameters": {},
                        "pathParameters": {},
                    },
                    None,
                )
            assert resp["statusCode"] == 403


class TestAnnouncementCrud:
    """Direct user follow-up moving management to a dedicated page: "Annoucement
    is managed in that page (CRUD)... For staff they can only sent to
    customers, but it must be approved by the admin before it can become
    visible to the customer." """

    def test_list_my_announcement_requests_scopes_to_the_requester(self):
        from services.notification import service

        with patch(
            "services.notification.repository.list_my_announcement_requests",
            return_value=[{"id": "r1"}, {"id": "r2"}],
        ) as mock_list:
            result = service.list_my_announcement_requests(TENANT_ID, USER_ID)

        assert len(result) == 2
        mock_list.assert_called_once_with(TENANT_ID, USER_ID)

    def test_update_my_announcement_request_succeeds_when_pending_and_owned(self):
        from services.notification import service

        pending_row = {"id": "r1", "requested_by": USER_ID, "status": "pending"}
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=pending_row),
            patch(
                "services.notification.repository.update_announcement_request",
                return_value={"id": "r1", "title": "New title"},
            ) as mock_update,
        ):
            result = service.update_my_announcement_request(TENANT_ID, "r1", USER_ID, "New title", None)

        assert result["title"] == "New title"
        mock_update.assert_called_once_with(TENANT_ID, "r1", USER_ID, "New title", None)

    def test_update_my_announcement_request_404s_for_a_different_owner(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        other_users_row = {"id": "r1", "requested_by": "someone-else", "status": "pending"}
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=other_users_row),
            pytest.raises(ResourceNotFoundError),
        ):
            service.update_my_announcement_request(TENANT_ID, "r1", USER_ID, "New title", None)

    def test_update_my_announcement_request_404s_once_already_reviewed(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        approved_row = {"id": "r1", "requested_by": USER_ID, "status": "approved"}
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=approved_row),
            pytest.raises(ResourceNotFoundError),
        ):
            service.update_my_announcement_request(TENANT_ID, "r1", USER_ID, "New title", None)

    def test_delete_my_announcement_request_withdraws_a_pending_one(self):
        from services.notification import service

        pending_row = {"id": "r1", "requested_by": USER_ID, "status": "pending"}
        with (
            patch("services.notification.repository.get_announcement_request_by_id", return_value=pending_row),
            patch("services.notification.repository.delete_announcement_request", return_value=1) as mock_delete,
        ):
            result = service.delete_my_announcement_request(TENANT_ID, "r1", USER_ID)

        assert result == {"deleted": True}
        mock_delete.assert_called_once_with(TENANT_ID, "r1", USER_ID)

    def test_update_announcement_edits_a_sent_announcement(self):
        from services.notification import service

        with (
            patch("services.notification.repository.update_announcement_group", return_value=4) as mock_update,
            patch("shared.audit.log_audit") as mock_audit,
        ):
            result = service.update_announcement(TENANT_ID, "group1", "Fixed title", "Fixed body", "admin1", "tenant_admin")

        assert result == {"announcement_group_id": "group1", "title": "Fixed title", "body": "Fixed body"}
        mock_update.assert_called_once_with(TENANT_ID, "group1", "Fixed title", "Fixed body")
        assert mock_audit.call_args.kwargs["action"] == "UPDATE"

    def test_update_a_missing_announcement_404s(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        with (
            patch("services.notification.repository.update_announcement_group", return_value=0),
            pytest.raises(ResourceNotFoundError),
        ):
            service.update_announcement(TENANT_ID, "missing", "Title", None, "admin1", "tenant_admin")

    def test_delete_announcement_removes_the_whole_group(self):
        from services.notification import service

        with (
            patch("services.notification.repository.delete_announcement_group", return_value=4) as mock_delete,
            patch("shared.audit.log_audit") as mock_audit,
        ):
            result = service.delete_announcement(TENANT_ID, "group1", "admin1", "tenant_admin")

        assert result == {"deleted": True}
        mock_delete.assert_called_once_with(TENANT_ID, "group1")
        assert mock_audit.call_args.kwargs["action"] == "DELETE"

    def test_delete_a_missing_announcement_404s(self):
        from services.notification import service
        from shared.exceptions import ResourceNotFoundError

        with (
            patch("services.notification.repository.delete_announcement_group", return_value=0),
            pytest.raises(ResourceNotFoundError),
        ):
            service.delete_announcement(TENANT_ID, "missing", "admin1", "tenant_admin")


class TestAnnouncementCrudHandler:
    def _event(self, method: str, path: str, body: str = "{}") -> dict:
        return {
            "requestContext": {
                "requestId": "req-crud-001",
                "http": {"method": method, "path": path},
                "authorizer": {"claims": {"sub": USER_ID, "custom:tenant_id": TENANT_ID}},
                "identity": {"sourceIp": "127.0.0.1"},
            },
            "headers": {},
            "body": body,
            "queryStringParameters": {},
            "pathParameters": {},
        }

    def test_mine_route_requires_nigeria_office_staff(self):
        from services.notification import handler
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with patch("services.notification.handler.get_tenant_context", return_value=ctx):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/announcements/mine"), None)

        assert resp["statusCode"] == 403

    def test_mine_route_calls_service_for_nigeria_office_staff(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "list_my_announcement_requests", return_value=[{"id": "r1"}]) as mock_list,
        ):
            resp = handler.http_handler(self._event("GET", "/v1/notifications/announcements/mine"), None)

        assert resp["statusCode"] == 200
        mock_list.assert_called_once_with(TENANT_ID, USER_ID)

    def test_edit_own_pending_request_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(
                service,
                "update_my_announcement_request",
                return_value={"id": "r1", "title": "New"},
            ) as mock_update,
        ):
            resp = handler.http_handler(
                self._event(
                    "PATCH",
                    "/v1/notifications/announcements/requests/r1",
                    body='{"title": "New"}',
                ),
                None,
            )

        assert resp["statusCode"] == 200
        mock_update.assert_called_once_with(TENANT_ID, "r1", USER_ID, "New", None)

    def test_edit_own_pending_request_route_forbidden_for_tenant_admin(self):
        from services.notification import handler
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with patch("services.notification.handler.get_tenant_context", return_value=ctx):
            resp = handler.http_handler(
                self._event(
                    "PATCH",
                    "/v1/notifications/announcements/requests/r1",
                    body='{"title": "New"}',
                ),
                None,
            )

        assert resp["statusCode"] == 403

    def test_withdraw_own_pending_request_route(self):
        from services.notification import handler, service

        with (
            patch("services.notification.handler.get_tenant_context", return_value=_ctx()),
            patch.object(service, "delete_my_announcement_request", return_value={"deleted": True}) as mock_delete,
        ):
            resp = handler.http_handler(
                self._event("DELETE", "/v1/notifications/announcements/requests/r1"),
                None,
            )

        assert resp["statusCode"] == 200
        mock_delete.assert_called_once_with(TENANT_ID, "r1", USER_ID)

    def test_edit_sent_announcement_route_requires_tenant_admin(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(
                self._event(
                    "PATCH",
                    "/v1/notifications/announcements/group1",
                    body='{"title": "New"}',
                ),
                None,
            )

        assert resp["statusCode"] == 403

    def test_edit_sent_announcement_route_calls_service_for_tenant_admin(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(
                service,
                "update_announcement",
                return_value={"announcement_group_id": "group1", "title": "New", "body": None},
            ) as mock_update,
        ):
            resp = handler.http_handler(
                self._event(
                    "PATCH",
                    "/v1/notifications/announcements/group1",
                    body='{"title": "New"}',
                ),
                None,
            )

        assert resp["statusCode"] == 200
        mock_update.assert_called_once_with(TENANT_ID, "group1", "New", None, USER_ID, "tenant_admin")

    def test_delete_sent_announcement_route_requires_tenant_admin(self):
        from services.notification import handler

        with patch("services.notification.handler.get_tenant_context", return_value=_ctx()):
            resp = handler.http_handler(self._event("DELETE", "/v1/notifications/announcements/group1"), None)

        assert resp["statusCode"] == 403

    def test_delete_sent_announcement_route_calls_service_for_tenant_admin(self):
        from services.notification import handler, service
        from shared.tenant_context import TenantContext, UserRole

        ctx = TenantContext(tenant_id=TENANT_ID, user_id=USER_ID, role=UserRole.TENANT_ADMIN)
        with (
            patch("services.notification.handler.get_tenant_context", return_value=ctx),
            patch.object(service, "delete_announcement", return_value={"deleted": True}) as mock_delete,
        ):
            resp = handler.http_handler(self._event("DELETE", "/v1/notifications/announcements/group1"), None)

        assert resp["statusCode"] == 200
        mock_delete.assert_called_once_with(TENANT_ID, "group1", USER_ID, "tenant_admin")
