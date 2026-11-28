"""Platform admin audit, Phase 1a: who the platform caller is, what their role allows, re-authentication, and
two-person approval (C-28, C-29, C-30; decisions D2 and D4).

See the "ShipX Platform Admin Console: Audit and Redesign Plan" doc and ``07_api_tenant_management.md``.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Imported before tests/conftest.py's autouse fixture replaces the hook in shared.auth for handler suites.
from shared.auth import _resolve_platform_caller as real_resolve_platform_caller
from shared.exceptions import (
    DuplicateResourceError,
    InsufficientPermissionsError,
    PlatformAdminNotEnrolledError,
    SelfApprovalForbiddenError,
    ServiceUnavailableError,
    StepUpRequiredError,
    ValidationError,
)
from shared.platform_roles import APPROVER_ROLES, PlatformPermission, PlatformRole, permissions_for
from shared.tenant_context import TenantContext, UserRole

TENANT_ID = "11111111-1111-1111-1111-111111111111"
REQUESTER = "aaaaaaaa-0000-0000-0000-000000000001"
APPROVER = "aaaaaaaa-0000-0000-0000-000000000002"


def _ctx(role: str = "owner", platform_user_id: str = REQUESTER, user_id: str = "sub-requester") -> TenantContext:
    return TenantContext(
        tenant_id="PLATFORM",
        user_id=user_id,
        role=UserRole.PLATFORM_ADMIN,
        platform_user_id=platform_user_id,
        platform_role=role,
    )


def _event(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    return {
        "requestContext": {
            "requestId": "req-p1",
            "http": {"method": method, "path": path},
            "authorizer": {"claims": {"sub": "sub-requester", "custom:tenant_id": "PLATFORM"}},
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "headers": headers or {},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": {},
        "pathParameters": {},
    }


def _call(event: dict, ctx: TenantContext) -> dict:
    from services.tenant_management import handler

    with patch("services.tenant_management.handler.get_tenant_context", return_value=ctx):
        return handler.lambda_handler(event, None)


# ---------------------------------------------------------------------------
# Roles (D2)
# ---------------------------------------------------------------------------


class TestRoleMatrix:
    def test_owner_can_do_everything(self):
        assert permissions_for("owner") == frozenset(PlatformPermission)

    def test_admin_cannot_manage_admins(self):
        assert PlatformPermission.ADMINS not in permissions_for("admin")
        assert PlatformPermission.APPROVE in permissions_for("admin")

    def test_support_reads_and_supports_only(self):
        assert permissions_for("support") == {PlatformPermission.READ, PlatformPermission.SUPPORT}

    def test_finance_only_reads(self):
        assert permissions_for("finance") == {PlatformPermission.READ}

    def test_an_unknown_or_missing_role_grants_nothing(self):
        assert permissions_for("superuser") == frozenset()
        assert permissions_for(None) == frozenset()

    def test_only_owners_and_admins_can_approve(self):
        assert {PlatformRole.OWNER, PlatformRole.ADMIN} == APPROVER_ROLES

    def test_a_platform_context_without_a_directory_role_has_no_permissions(self):
        ctx = TenantContext(tenant_id="PLATFORM", user_id="x", role=UserRole.PLATFORM_ADMIN)
        assert not ctx.has_platform_permission(PlatformPermission.READ)

    def test_a_tenant_user_never_has_platform_permissions(self):
        ctx = TenantContext(tenant_id=TENANT_ID, user_id="x", role=UserRole.TENANT_ADMIN, platform_role="owner")
        assert not ctx.has_platform_permission(PlatformPermission.READ)


class TestRoutePermissions:
    @pytest.mark.parametrize(
        ("method", "path", "permission"),
        [
            ("GET", "/v1/platform/tenants", PlatformPermission.READ),
            ("PATCH", f"/v1/platform/tenants/{TENANT_ID}/suspend", PlatformPermission.TENANT_LIFECYCLE),
            ("DELETE", f"/v1/platform/tenants/{TENANT_ID}", PlatformPermission.TENANT_LIFECYCLE),
            ("POST", f"/v1/platform/tenants/{TENANT_ID}/impersonate", PlatformPermission.SUPPORT),
            ("POST", f"/v1/platform/tenants/{TENANT_ID}/quota-override", PlatformPermission.PLANS),
            ("PUT", "/v1/platform/plans/starter", PlatformPermission.PLANS),
            ("PUT", "/v1/platform/settings", PlatformPermission.SETTINGS),
            ("PUT", "/v1/platform/settings/sms-gateway", PlatformPermission.SETTINGS),
            ("DELETE", "/v1/platform/impersonation/s-1", PlatformPermission.SUPPORT),
            ("PATCH", "/v1/platform/onboarding-requests/r-1", PlatformPermission.SUPPORT),
            ("POST", "/v1/platform/admins", PlatformPermission.ADMINS),
            ("POST", "/v1/platform/approvals/a-1/approve", PlatformPermission.APPROVE),
            ("POST", "/v1/platform/approvals/a-1/cancel", PlatformPermission.READ),
            ("POST", "/v1/platform/auth/step-up", PlatformPermission.READ),
            ("POST", "/v1/platform/something-new", PlatformPermission.ADMINS),
        ],
    )
    def test_each_route_names_one_permission(self, method, path, permission):
        from services.tenant_management.handler import _required_platform_permission

        assert _required_platform_permission(method, path.strip("/").split("/")) == permission

    def test_finance_cannot_suspend_a_tenant(self):
        with patch("services.tenant_management.handler.service.suspend_tenant") as suspend:
            resp = _call(_event("PATCH", f"/v1/platform/tenants/{TENANT_ID}/suspend", {"reason": "x"}), _ctx("finance"))
        assert resp["statusCode"] == 403
        suspend.assert_not_called()

    def test_finance_can_read_the_tenant_list(self):
        with patch("services.tenant_management.handler.service.list_tenants", return_value=([], None, False, 0)):
            resp = _call(_event("GET", "/v1/platform/tenants"), _ctx("finance"))
        assert resp["statusCode"] == 200

    def test_support_cannot_create_a_tenant_through_the_short_alias(self):
        with patch("services.tenant_management.handler.service.create_tenant") as create:
            resp = _call(_event("POST", "/v1/tenants", {"company_name": "Acme"}), _ctx("support"))
        assert resp["statusCode"] == 403
        create.assert_not_called()


class TestWritesOutsideTheConsole:
    def test_support_cannot_write_to_a_tenant_route(self):
        from shared.auth import _assert_platform_write_outside_console

        with pytest.raises(InsufficientPermissionsError):
            _assert_platform_write_outside_console("support", "POST", "/v1/packing-lists")

    def test_support_can_read_a_tenant_route(self):
        from shared.auth import _assert_platform_write_outside_console

        _assert_platform_write_outside_console("support", "GET", "/v1/packing-lists")

    def test_an_admin_can_write_to_a_tenant_route(self):
        from shared.auth import _assert_platform_write_outside_console

        _assert_platform_write_outside_console("admin", "POST", "/v1/packing-lists")

    def test_console_routes_are_left_to_their_own_permission_check(self):
        from shared.auth import _assert_platform_write_outside_console

        _assert_platform_write_outside_console("finance", "POST", "/v1/platform/approvals/a/cancel")


# ---------------------------------------------------------------------------
# The directory: every platform request resolves its caller
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, owner_exists: bool):
        self.owner_exists = owner_exists
        self.statements: list[str] = []
        self._last = None

    def execute(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))
        if "SELECT 1 FROM platform_user" in sql:
            self._last = {"?column?": 1} if self.owner_exists else None
        elif "INSERT INTO platform_user" in sql:
            self._last = {"id": "pu-new"}
        else:
            self._last = None

    def fetchone(self):
        return self._last


class TestDirectoryLookup:
    def _resolve(self, *, by_subject=None, bound=None, owner_exists=True, email="a@shipx.test"):
        from shared import platform_directory as directory

        cursor = _FakeCursor(owner_exists)
        writes: list[str] = []

        def fake_write(_tenant, sql, params=None):
            writes.append(" ".join(sql.split()))
            if "lower(email)" in sql:
                return bound
            if "status = 'active'" in sql and "WHERE id" in sql:
                return {"id": by_subject[0]["id"], "role": by_subject[0]["role"]} if by_subject else None
            return {"id": "x"}

        class _Txn:
            def __enter__(self):
                return cursor

            def __exit__(self, *exc):
                return False

        cache = MagicMock()
        cache.get.return_value = None
        with (
            patch.object(directory, "_caller_cache", cache),
            patch("shared.db.execute_with_tenant", return_value=by_subject or []),
            patch("shared.db.execute_write_with_tenant", side_effect=fake_write),
            patch("shared.db.tenant_transaction", return_value=_Txn()),
            patch("shared.platform_audit.insert_platform_audit") as audit,
        ):
            result = directory.resolve_platform_caller("sub-1", email, "Ada")
        return result, writes, cursor, audit, cache

    def test_an_active_row_resolves_to_its_role(self):
        (uid, role), _, _, audit, cache = self._resolve(by_subject=[{"id": "pu-1", "role": "support", "status": "active"}])
        assert (uid, role) == ("pu-1", "support")
        audit.assert_not_called()
        cache.set.assert_called_with("sub-1", "pu-1:support")

    def test_an_invited_row_becomes_active_on_first_request(self):
        (uid, role), writes, _, audit, _ = self._resolve(by_subject=[{"id": "pu-2", "role": "admin", "status": "invited"}])
        assert (uid, role) == ("pu-2", "admin")
        assert any("SET status = 'active'" in w for w in writes)
        assert audit.call_args.kwargs["action"] == "PLATFORM_ADMIN_ENROLLED"

    def test_a_disabled_row_is_refused(self):
        from shared.platform_directory import PlatformAdminDisabledError

        with pytest.raises(PlatformAdminDisabledError):
            self._resolve(by_subject=[{"id": "pu-3", "role": "owner", "status": "disabled"}])

    def test_a_seeded_invite_is_bound_by_email(self):
        (uid, role), _, _, _, _ = self._resolve(bound={"id": "pu-4", "role": "finance"})
        assert (uid, role) == ("pu-4", "finance")

    def test_the_first_admin_becomes_owner_while_there_is_none(self):
        (uid, role), _, cursor, audit, _ = self._resolve(owner_exists=False)
        assert (uid, role) == ("pu-new", "owner")
        assert any("pg_advisory_xact_lock" in s for s in cursor.statements)
        assert audit.call_args.kwargs["details"]["bootstrap"] is True

    def test_a_stranger_is_refused_once_an_owner_exists(self):
        with pytest.raises(PlatformAdminNotEnrolledError):
            self._resolve(owner_exists=True)

    def test_a_directory_outage_denies_the_request(self):
        from shared import platform_directory as directory

        cache = MagicMock()
        cache.get.return_value = None
        with (
            patch.object(directory, "_caller_cache", cache),
            patch("shared.db.execute_with_tenant", side_effect=OSError("db down")),
            pytest.raises(ServiceUnavailableError),
        ):
            directory.resolve_platform_caller("sub-1", None, None)

    def test_a_cached_caller_skips_the_database(self):
        from shared import platform_directory as directory

        cache = MagicMock()
        cache.get.return_value = "pu-9:admin"
        with patch.object(directory, "_caller_cache", cache), patch("shared.db.execute_with_tenant") as read:
            assert directory.resolve_platform_caller("sub-1", None, None) == ("pu-9", "admin")
        read.assert_not_called()


class TestGetTenantContextResolvesPlatformCallers:
    def test_the_directory_role_lands_on_the_context(self, monkeypatch):
        from shared.auth import get_tenant_context

        monkeypatch.setattr("shared.auth._resolve_platform_caller", lambda s, e, n: ("pu-7", "finance"))
        ctx = get_tenant_context(
            {
                "requestContext": {
                    "http": {"method": "GET", "path": "/v1/platform/tenants"},
                    "authorizer": {
                        "claims": {"sub": "sub-7", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
                    },
                }
            }
        )
        assert (ctx.platform_user_id, ctx.platform_role) == ("pu-7", "finance")
        assert ctx.has_platform_permission(PlatformPermission.READ)
        assert not ctx.has_platform_permission(PlatformPermission.SETTINGS)

    def test_the_real_hook_calls_the_directory(self):
        with patch("shared.platform_directory.resolve_platform_caller", return_value=("pu-1", "owner")) as resolve:
            assert real_resolve_platform_caller("sub", "e@x.test", "N") == ("pu-1", "owner")
        resolve.assert_called_once_with("sub", "e@x.test", "N")


# ---------------------------------------------------------------------------
# Step-up re-authentication (C-29)
# ---------------------------------------------------------------------------


@pytest.fixture
def signing_secret(monkeypatch):
    monkeypatch.setenv("IMPERSONATION_SECRET", "test-secret-for-step-up-tokens-32b")
    monkeypatch.delenv("IMPERSONATION_SECRET_ARN", raising=False)


class TestStepUpTokens:
    def test_a_minted_token_passes_for_its_own_subject(self, signing_secret):
        from services.tenant_management import step_up

        token = step_up.mint_step_up_token("sub-requester")["step_up_token"]
        step_up.require_step_up(_event("DELETE", "/x", headers={"X-Step-Up-Token": token}), _ctx())

    def test_a_missing_token_is_refused(self, signing_secret):
        from services.tenant_management import step_up

        with pytest.raises(StepUpRequiredError):
            step_up.require_step_up(_event("DELETE", "/x"), _ctx())

    def test_another_admins_token_is_refused(self, signing_secret):
        from services.tenant_management import step_up

        token = step_up.mint_step_up_token("someone-else")["step_up_token"]
        with pytest.raises(StepUpRequiredError):
            step_up.require_step_up(_event("DELETE", "/x", headers={"x-step-up-token": token}), _ctx())

    def test_an_expired_token_is_refused(self, signing_secret):
        from services.tenant_management import step_up

        with patch("services.tenant_management.step_up.time.time", return_value=time.time() - 600):
            token = step_up.mint_step_up_token("sub-requester")["step_up_token"]
        with pytest.raises(StepUpRequiredError):
            step_up.require_step_up(_event("DELETE", "/x", headers={"x-step-up-token": token}), _ctx())

    def test_an_impersonation_token_is_not_a_step_up_token(self, signing_secret):
        import jwt

        from services.tenant_management import step_up

        forged = jwt.encode(
            {"sub": "sub-requester", "exp": int(time.time()) + 60, "typ": "impersonation"},
            "test-secret-for-step-up-tokens-32b",
            algorithm="HS256",
        )
        with pytest.raises(StepUpRequiredError):
            step_up.require_step_up(_event("DELETE", "/x", headers={"x-step-up-token": forged}), _ctx())


class TestStepUpVerification:
    @pytest.fixture(autouse=True)
    def _no_audit(self):
        with patch("services.tenant_management.step_up.insert_platform_audit"):
            yield

    def test_the_local_password_works_only_in_local_and_test(self, signing_secret, monkeypatch):
        from services.tenant_management import step_up

        monkeypatch.setenv("ENVIRONMENT", "local")
        monkeypatch.setenv("STEP_UP_LOCAL_PASSWORD", "let-me-in")
        assert step_up.step_up(_ctx(), "a@x.test", password="let-me-in", mfa_code=None, id_token=None)["step_up_token"]
        with pytest.raises(step_up.StepUpFailedError):
            step_up.step_up(_ctx(), "a@x.test", password="wrong", mfa_code=None, id_token=None)

        monkeypatch.setenv("ENVIRONMENT", "prod")
        assert step_up._local_password() is None

    def _cognito(self, monkeypatch, client):
        from services.tenant_management import step_up

        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("COGNITO_CLIENT_ID", "client-1")
        monkeypatch.setattr(step_up, "_cognito_client", lambda: client)
        monkeypatch.setattr("shared.providers.AUTH_PROVIDER", "aws")
        return step_up

    def test_cognito_asks_for_the_code_then_accepts_it(self, signing_secret, monkeypatch):
        import jwt

        id_token = jwt.encode({"sub": "sub-requester"}, "k", algorithm="HS256")
        client = MagicMock()
        client.initiate_auth.return_value = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "s"}
        client.respond_to_auth_challenge.return_value = {"AuthenticationResult": {"IdToken": id_token, "RefreshToken": "rt"}}
        step_up = self._cognito(monkeypatch, client)

        with pytest.raises(step_up.StepUpCodeRequiredError):
            step_up.step_up(_ctx(), "a@x.test", password="pw", mfa_code=None, id_token=None)
        result = step_up.step_up(_ctx(), "a@x.test", password="pw", mfa_code="123456", id_token=None)
        assert result["step_up_token"]
        assert client.initiate_auth.call_args.kwargs["AuthParameters"]["USERNAME"] == "a@x.test"
        client.revoke_token.assert_called_with(Token="rt", ClientId="client-1")

    def test_cognito_refuses_a_sign_in_that_names_someone_else(self, signing_secret, monkeypatch):
        import jwt

        client = MagicMock()
        client.initiate_auth.return_value = {
            "AuthenticationResult": {"IdToken": jwt.encode({"sub": "other"}, "k", algorithm="HS256"), "RefreshToken": "rt"}
        }
        step_up = self._cognito(monkeypatch, client)
        with pytest.raises(step_up.StepUpFailedError):
            step_up.step_up(_ctx(), "a@x.test", password="pw", mfa_code=None, id_token=None)
        client.revoke_token.assert_called_once()

    def test_a_wrong_password_counts_toward_the_lockout(self, signing_secret, monkeypatch):
        from botocore.exceptions import ClientError

        client = MagicMock()
        client.initiate_auth.side_effect = ClientError({"Error": {"Code": "NotAuthorizedException"}}, "InitiateAuth")
        step_up = self._cognito(monkeypatch, client)
        with (
            patch("services.tenant_management.step_up.rate_limit.record_failure") as failure,
            pytest.raises(step_up.StepUpFailedError),
        ):
            step_up.step_up(_ctx(), "a@x.test", password="bad", mfa_code=None, id_token=None)
        failure.assert_called_once()

    def test_entra_needs_a_fresh_sign_in_for_the_same_person(self, signing_secret, monkeypatch):
        from services.tenant_management import step_up

        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setattr("shared.providers.AUTH_PROVIDER", "azure")
        fresh = {"oid": "sub-requester", "auth_time": int(time.time()) - 30}
        with patch("shared.auth_verify.verify_oidc_jwt", return_value=fresh):
            assert step_up.step_up(_ctx(), "a@x.test", password=None, mfa_code=None, id_token="t")["step_up_token"]
        stale = {"oid": "sub-requester", "auth_time": int(time.time()) - 3600}
        with patch("shared.auth_verify.verify_oidc_jwt", return_value=stale), pytest.raises(step_up.StepUpFailedError):
            step_up.step_up(_ctx(), "a@x.test", password=None, mfa_code=None, id_token="t")


class TestDangerousRoutesNeedStepUp:
    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("DELETE", f"/v1/platform/tenants/{TENANT_ID}", {"reason": "Contract ended"}),
            ("PATCH", f"/v1/platform/tenants/{TENANT_ID}/suspend", {"reason": "Unpaid"}),
            ("POST", "/v1/platform/admins", {"email": "new@shipx.test", "name": "New", "role": "support"}),
            ("PATCH", f"/v1/platform/admins/{APPROVER}", {"role": "admin"}),
            ("POST", f"/v1/platform/approvals/{APPROVER}/approve", {}),
            ("POST", f"/v1/platform/approvals/{APPROVER}/reject", {}),
            ("PUT", "/v1/platform/settings", {"maintenance_mode": True}),
        ],
    )
    def test_refused_with_step_up_required(self, method, path, body, signing_secret):
        with (
            patch("services.tenant_management.handler.service.get_tenant", return_value={"id": TENANT_ID, "status": "active"}),
            patch("services.tenant_management.handler.service.get_platform_settings", return_value={}),
        ):
            resp = _call(_event(method, path, body), _ctx())
        assert resp["statusCode"] == 403
        assert json.loads(resp["body"])["error_code"] == "STEP_UP_REQUIRED"


# ---------------------------------------------------------------------------
# Two-person approval (C-30, D4)
# ---------------------------------------------------------------------------


class _FakeApprovals:
    """An in-memory platform_repository for the approvals flow."""

    def __init__(self, approvers: list[dict[str, Any]], owners: list[dict[str, Any]] | None = None):
        self.rows: dict[str, dict[str, Any]] = {}
        self.approvers = approvers
        self.owners = owners or []
        self.users = {
            REQUESTER: {"id": REQUESTER, "subject": "sub-requester", "name": "Req"},
            APPROVER: {"id": APPROVER, "subject": "sub-approver", "name": "App"},
        }

    def find_open_approval(self, action, label):
        return next(
            (
                r
                for r in self.rows.values()
                if r["action"] == action and r["target_label"] == label and r["status"] in ("pending", "scheduled")
            ),
            None,
        )

    def list_active_users_with_roles(self, roles):
        return self.owners if roles == ["owner"] else self.approvers

    def insert_approval(self, values):
        row_id = f"ap-{len(self.rows) + 1}"
        row = {
            **values,
            "id": row_id,
            "payload": json.loads(values["payload"]),
            "requested_by_name": "Req",
            "target_tenant_name": None,
        }
        self.rows[row_id] = row
        return dict(row)

    def get_approval(self, approval_id, with_secret=False):
        row = self.rows.get(approval_id)
        return dict(row) if row else None

    def transition_approval(self, approval_id, from_statuses, to_status, **fields):
        row = self.rows.get(approval_id)
        if row is None or row["status"] not in from_statuses:
            return None
        row["status"] = to_status
        for key in ("decided_by", "decision_note", "error"):
            if fields.get(key) is not None:
                row[key] = fields[key]
        return dict(row)

    def get_platform_user(self, user_id):
        return self.users.get(user_id)

    def list_due_scheduled_approvals(self):
        return [dict(r) for r in self.rows.values() if r["status"] == "scheduled"]

    def list_expired_pending_approvals(self):
        return [dict(r) for r in self.rows.values() if r["status"] == "pending" and r["expires_at"] <= datetime.now(UTC)]


@pytest.fixture
def fake_approvals():
    def build(approvers=None, owners=None):
        fake = _FakeApprovals(
            approvers if approvers is not None else [{"id": APPROVER, "email": "app@shipx.test", "role": "admin"}],
            owners,
        )
        stack = [
            patch("services.tenant_management.approvals.prepo", fake),
            patch("services.tenant_management.approvals.insert_platform_audit"),
            patch("services.tenant_management.approvals.send_platform_email"),
            patch("services.tenant_management.approvals.encrypt_field", side_effect=lambda v: f"enc:{v}"),
            patch("services.tenant_management.approvals.decrypt_field", side_effect=lambda v: v.removeprefix("enc:")),
        ]
        mocks = [p.start() for p in stack]
        fake.audit, fake.email = mocks[1], mocks[2]
        return fake

    yield build
    patch.stopall()


def _offboard_action():
    from services.tenant_management import approvals

    return approvals.ProtectedAction(
        action=approvals.ApprovalAction.OFFBOARD_TENANT,
        target_label=TENANT_ID,
        target_tenant_id=TENANT_ID,
        summary="Offboard Acme",
        confirm_text="acme",
        payload={"tenant_id": TENANT_ID, "reason": "Contract ended"},
        reason="Contract ended",
    )


class TestRequesting:
    def test_with_another_admin_it_waits_for_them(self, fake_approvals):
        from services.tenant_management import approvals

        fake = fake_approvals()
        outcome = approvals.request_protected_action(_ctx(), _offboard_action(), confirm=None)
        assert outcome["outcome"] == "pending_approval"
        assert outcome["approval"]["status"] == "pending"
        fake.email.assert_called_once()
        assert fake.email.call_args.args[0] == "app@shipx.test"

    def test_the_requester_is_not_counted_as_an_approver(self, fake_approvals):
        from services.tenant_management import approvals

        fake_approvals(approvers=[{"id": REQUESTER, "email": "me@shipx.test", "role": "owner"}])
        with pytest.raises(ValidationError):
            approvals.request_protected_action(_ctx(), _offboard_action(), confirm=None)

    def test_a_second_request_for_the_same_target_is_refused(self, fake_approvals):
        from services.tenant_management import approvals

        fake_approvals()
        approvals.request_protected_action(_ctx(), _offboard_action(), confirm=None)
        with pytest.raises(DuplicateResourceError):
            approvals.request_protected_action(_ctx(), _offboard_action(), confirm=None)

    def test_a_sole_admin_must_type_the_target(self, fake_approvals):
        from services.tenant_management import approvals

        fake_approvals(approvers=[])
        with pytest.raises(ValidationError) as err:
            approvals.request_protected_action(_ctx(), _offboard_action(), confirm="wrong")
        assert "confirm" in err.value.field_errors

    def test_a_sole_admins_offboarding_waits_24_hours_and_tells_the_owners(self, fake_approvals):
        from services.tenant_management import approvals

        fake = fake_approvals(approvers=[], owners=[{"id": REQUESTER, "email": "owner@shipx.test", "role": "owner"}])
        with patch("services.tenant_management.tenants.offboard_tenant") as offboard:
            outcome = approvals.request_protected_action(_ctx(), _offboard_action(), confirm=" ACME ")
        assert outcome["outcome"] == "scheduled"
        row = fake.rows[outcome["approval"]["id"]]
        assert row["execute_after"] - datetime.now(UTC) > timedelta(hours=23)
        offboard.assert_not_called()
        fake.email.assert_called_once()

    def test_a_sole_admins_maintenance_switch_runs_at_once(self, fake_approvals):
        from services.tenant_management import approvals

        fake_approvals(approvers=[])
        protected = approvals.ProtectedAction(
            action=approvals.ApprovalAction.MAINTENANCE_ON,
            target_label="maintenance_mode",
            summary="Turn maintenance on",
            confirm_text="maintenance",
        )
        with patch("services.tenant_management.platform.update_platform_settings", return_value={"ok": 1}) as update:
            outcome = approvals.request_protected_action(_ctx(), protected, confirm="maintenance")
        assert outcome["outcome"] == "executed"
        assert outcome["approval"]["status"] == "executed"
        update.assert_called_once_with({"maintenance_mode": True}, actor_id="sub-requester", ip_address=None)

    def test_an_action_without_an_executor_cannot_be_requested(self, fake_approvals):
        from services.tenant_management import approvals
        from shared.exceptions import BusinessRuleViolationError

        fake_approvals()
        protected = approvals.ProtectedAction(
            action=approvals.ApprovalAction.PLAN_PRICE_CHANGE, target_label="starter", summary="x", confirm_text="x"
        )
        with pytest.raises(BusinessRuleViolationError):
            approvals.request_protected_action(_ctx(), protected, confirm=None)


class TestDeciding:
    def _pending(self, fake_approvals):
        from services.tenant_management import approvals

        fake = fake_approvals()
        outcome = approvals.request_protected_action(_ctx(), _offboard_action(), confirm=None)
        return fake, outcome["approval"]["id"]

    def test_nobody_approves_their_own_request(self, fake_approvals):
        from services.tenant_management import approvals

        _, approval_id = self._pending(fake_approvals)
        with pytest.raises(SelfApprovalForbiddenError):
            approvals.approve(_ctx(), approval_id, None)

    def test_a_second_admin_approves_and_it_runs_as_the_requester(self, fake_approvals):
        from services.tenant_management import approvals

        fake, approval_id = self._pending(fake_approvals)
        approver = _ctx("admin", platform_user_id=APPROVER, user_id="sub-approver")
        with patch("services.tenant_management.tenants.offboard_tenant", return_value={"id": TENANT_ID}) as offboard:
            outcome = approvals.approve(approver, approval_id, "ok")
        offboard.assert_called_once_with(TENANT_ID, actor_id="sub-requester", reason="Contract ended", ip_address=None)
        assert outcome["approval"]["status"] == "executed"
        assert fake.rows[approval_id]["decided_by"] == APPROVER

    def test_it_cannot_be_approved_twice(self, fake_approvals):
        from services.tenant_management import approvals
        from shared.exceptions import BusinessRuleViolationError

        _, approval_id = self._pending(fake_approvals)
        approver = _ctx("admin", platform_user_id=APPROVER, user_id="sub-approver")
        with patch("services.tenant_management.tenants.offboard_tenant", return_value={}):
            approvals.approve(approver, approval_id, None)
            with pytest.raises(BusinessRuleViolationError):
                approvals.approve(approver, approval_id, None)

    def test_a_payload_changed_after_the_request_is_not_run(self, fake_approvals):
        from services.tenant_management import approvals
        from shared.exceptions import BusinessRuleViolationError

        fake, approval_id = self._pending(fake_approvals)
        fake.rows[approval_id]["payload"]["tenant_id"] = "22222222-2222-2222-2222-222222222222"
        approver = _ctx("admin", platform_user_id=APPROVER, user_id="sub-approver")
        with (
            patch("services.tenant_management.tenants.offboard_tenant") as offboard,
            pytest.raises(BusinessRuleViolationError),
        ):
            approvals.approve(approver, approval_id, None)
        offboard.assert_not_called()
        assert fake.rows[approval_id]["status"] == "failed"

    def test_a_failed_action_is_recorded_as_failed(self, fake_approvals):
        from services.tenant_management import approvals

        fake, approval_id = self._pending(fake_approvals)
        approver = _ctx("admin", platform_user_id=APPROVER, user_id="sub-approver")
        with (
            patch("services.tenant_management.tenants.offboard_tenant", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            approvals.approve(approver, approval_id, None)
        assert fake.rows[approval_id]["status"] == "failed"

    def test_an_expired_request_cannot_be_approved(self, fake_approvals):
        from services.tenant_management import approvals
        from shared.exceptions import BusinessRuleViolationError

        fake, approval_id = self._pending(fake_approvals)
        fake.rows[approval_id]["expires_at"] = datetime.now(UTC) - timedelta(minutes=1)
        with pytest.raises(BusinessRuleViolationError):
            approvals.approve(_ctx("admin", platform_user_id=APPROVER), approval_id, None)
        assert fake.rows[approval_id]["status"] == "expired"

    def test_a_second_admin_can_reject(self, fake_approvals):
        from services.tenant_management import approvals

        fake, approval_id = self._pending(fake_approvals)
        approvals.reject(_ctx("admin", platform_user_id=APPROVER), approval_id, "no")
        assert fake.rows[approval_id]["status"] == "rejected"

    def test_only_the_requester_or_an_owner_can_cancel(self, fake_approvals):
        from services.tenant_management import approvals

        fake, approval_id = self._pending(fake_approvals)
        with pytest.raises(InsufficientPermissionsError):
            approvals.cancel(_ctx("admin", platform_user_id=APPROVER), approval_id, None)
        approvals.cancel(_ctx(), approval_id, None)
        assert fake.rows[approval_id]["status"] == "cancelled"


class TestScheduledRun:
    def test_due_offboardings_run_and_stale_requests_expire(self, fake_approvals):
        from services.tenant_management import approvals

        fake = fake_approvals(approvers=[])
        approvals.request_protected_action(_ctx(), _offboard_action(), confirm="acme")
        fake.approvers = [{"id": APPROVER, "email": "a@x.test", "role": "admin"}]
        stale = approvals.ProtectedAction(
            action=approvals.ApprovalAction.MAINTENANCE_ON, target_label="maintenance_mode", summary="m", confirm_text="m"
        )
        stale_id = approvals.request_protected_action(_ctx(), stale, confirm=None)["approval"]["id"]
        fake.rows[stale_id]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)

        with patch("services.tenant_management.tenants.offboard_tenant", return_value={}) as offboard:
            result = approvals.run_due()
        assert result == {"executed": 1, "failed": 0, "expired": 1}
        assert offboard.call_args.kwargs["actor_id"] == "sub-requester"

    def test_the_job_is_registered_with_the_runner(self):
        from services.scheduled.run import JOBS

        assert "platform_approvals" in JOBS


# ---------------------------------------------------------------------------
# Which settings changes are protected
# ---------------------------------------------------------------------------


class TestProtectedSettingsRoutes:
    def _put(self, path, body, settings):
        with (
            patch("services.tenant_management.handler.step_up.require_step_up"),
            patch("services.tenant_management.handler.service.get_platform_settings", return_value=settings),
            patch("services.tenant_management.platform.repo.get_platform_settings", return_value=settings),
            patch(
                "services.tenant_management.handler.approvals.request_protected_action",
                return_value={"outcome": "pending_approval", "approval": {"id": "a"}},
            ) as protected,
            patch("services.tenant_management.handler.service.update_gateway_settings", return_value={}) as gateway,
            patch("services.tenant_management.handler.service.update_platform_settings", return_value={}) as general,
        ):
            resp = _call(_event("PUT", path, body), _ctx())
        return resp, protected, gateway, general

    def test_a_new_gateway_key_needs_approval_and_is_kept_out_of_the_shown_payload(self):
        stored = {"sms_gateway": {"api_key": "old", "sender_id": "ShipX"}}
        resp, protected, gateway, _ = self._put("/v1/platform/settings/sms-gateway", {"api_key": "new", "sender_id": "X"}, stored)
        assert resp["statusCode"] == 202
        action = protected.call_args.args[1]
        assert action.secret == {"api_key": "new"}
        assert "new" not in json.dumps(action.payload)
        gateway.assert_not_called()

    def test_a_gateway_change_that_keeps_the_key_is_applied_directly(self):
        stored = {"sms_gateway": {"api_key": "old", "sender_id": "ShipX"}}
        resp, protected, gateway, _ = self._put(
            "/v1/platform/settings/sms-gateway", {"api_key": "****", "sender_id": "X"}, stored
        )
        assert resp["statusCode"] == 200
        protected.assert_not_called()
        gateway.assert_called_once()

    def test_turning_maintenance_on_needs_approval(self):
        resp, protected, _, general = self._put("/v1/platform/settings", {"maintenance_mode": True}, {})
        assert resp["statusCode"] == 202
        assert protected.call_args.args[1].action == "maintenance_on"
        general.assert_not_called()

    def test_maintenance_must_be_turned_on_by_itself(self):
        resp, protected, _, _ = self._put("/v1/platform/settings", {"maintenance_mode": True, "platform_name": "X"}, {})
        assert resp["statusCode"] == 422
        protected.assert_not_called()

    def test_turning_maintenance_off_is_direct(self):
        resp, protected, _, general = self._put("/v1/platform/settings", {"maintenance_mode": False}, {"maintenance_mode": True})
        assert resp["statusCode"] == 200
        protected.assert_not_called()
        general.assert_called_once()


# ---------------------------------------------------------------------------
# The admin directory (C-28)
# ---------------------------------------------------------------------------


class TestDirectoryService:
    def _target(self, **overrides):
        return {
            "id": APPROVER,
            "email": "t@shipx.test",
            "name": "T",
            "role": "owner",
            "status": "active",
            "subject": "sub-t",
            "last_seen_at": datetime.now(UTC),
            **overrides,
        }

    def test_invite_creates_the_sign_in_in_the_platform_group(self):
        from services.tenant_management import platform_admins
        from services.tenant_management.models import InvitePlatformAdminRequest

        idp = MagicMock()
        idp.create_user.return_value = "sub-new"
        with (
            patch.object(platform_admins.prepo, "get_platform_user_by_email", return_value=None),
            patch.object(
                platform_admins.prepo, "insert_platform_user", return_value={"id": "pu-n", "subject": "sub-new"}
            ) as insert,
            patch.object(platform_admins, "get_identity_provider", return_value=idp),
            patch.object(platform_admins, "insert_platform_audit"),
        ):
            out = platform_admins.invite_admin(
                _ctx(), InvitePlatformAdminRequest(email=" New@ShipX.test ", name="New", role="support")
            )
        assert idp.create_user.call_args.kwargs["tenant_id"] == "PLATFORM"
        idp.add_user_to_group.assert_called_once_with("new@shipx.test", "platform_admin")
        assert insert.call_args.args == ("sub-new", "new@shipx.test", "New", "support", REQUESTER)
        assert "subject" not in out

    def test_an_email_already_in_the_directory_is_refused(self):
        from services.tenant_management import platform_admins
        from services.tenant_management.models import InvitePlatformAdminRequest

        with (
            patch.object(platform_admins.prepo, "get_platform_user_by_email", return_value={"id": "x"}),
            pytest.raises(DuplicateResourceError),
        ):
            platform_admins.invite_admin(_ctx(), InvitePlatformAdminRequest(email="a@b.co", name="A", role="admin"))

    def test_nobody_changes_their_own_access(self):
        from services.tenant_management import platform_admins
        from services.tenant_management.models import UpdatePlatformAdminRequest
        from shared.exceptions import BusinessRuleViolationError

        with (
            patch.object(platform_admins.prepo, "get_platform_user", return_value=self._target(id=REQUESTER)),
            pytest.raises(BusinessRuleViolationError),
        ):
            platform_admins.update_admin(_ctx(), REQUESTER, UpdatePlatformAdminRequest(role="finance"))

    def test_the_last_owner_cannot_be_demoted_or_disabled(self):
        from services.tenant_management import platform_admins
        from services.tenant_management.models import UpdatePlatformAdminRequest
        from shared.exceptions import BusinessRuleViolationError

        for change in (UpdatePlatformAdminRequest(role="admin"), UpdatePlatformAdminRequest(disabled=True)):
            with (
                patch.object(platform_admins.prepo, "get_platform_user", return_value=self._target()),
                patch.object(platform_admins.prepo, "count_active_owners", return_value=1),
                pytest.raises(BusinessRuleViolationError),
            ):
                platform_admins.update_admin(_ctx(), APPROVER, change)

    def test_disabling_cuts_the_sign_in_and_forgets_the_cached_role(self):
        from services.tenant_management import platform_admins
        from services.tenant_management.models import UpdatePlatformAdminRequest

        idp = MagicMock()
        target = self._target(role="support")
        with (
            patch.object(platform_admins.prepo, "get_platform_user", return_value=target),
            patch.object(platform_admins.prepo, "update_platform_user", return_value={**target, "status": "disabled"}) as update,
            patch.object(platform_admins, "get_identity_provider", return_value=idp),
            patch.object(platform_admins, "evict_platform_caller") as evict,
            patch.object(platform_admins, "insert_platform_audit") as audit,
        ):
            platform_admins.update_admin(_ctx(), APPROVER, UpdatePlatformAdminRequest(disabled=True))
        idp.disable_user.assert_called_once_with("t@shipx.test")
        idp.global_sign_out.assert_called_once_with("t@shipx.test")
        update.assert_called_once_with(APPROVER, status="disabled")
        evict.assert_called_once_with("sub-t")
        assert audit.call_args.kwargs["after_state"] == {"status": "disabled"}


# ---------------------------------------------------------------------------
# Audit rows carry what changed (C-31 groundwork)
# ---------------------------------------------------------------------------


class TestAuditRows:
    def test_before_after_and_request_id_are_stored(self):
        from shared import platform_audit
        from shared.logging_config import bind_log_context, clear_log_context

        bind_log_context(request_id="req-77")
        try:
            with patch.object(platform_audit, "execute_write_with_tenant") as write:
                platform_audit.insert_platform_audit(
                    action="TENANT_SUSPENDED",
                    actor_id="a",
                    target_tenant_id=TENANT_ID,
                    before_state={"status": "active"},
                    after_state={"status": "suspended"},
                )
        finally:
            clear_log_context()
        params = write.call_args.args[2]
        assert json.loads(params["before_state"]) == {"status": "active"}
        assert json.loads(params["after_state"]) == {"status": "suspended"}
        assert params["request_id"] == "req-77"

    def test_the_audit_list_names_the_actor(self):
        from services.tenant_management import repository as repo

        with patch.object(repo, "execute_with_tenant", return_value=[]) as execute:
            repo.list_platform_audit_log(limit=10)
        sql = " ".join(execute.call_args.args[1].split())
        assert "pu.name AS actor_name" in sql
        assert "LEFT JOIN platform_user pu ON pu.subject = pal.actor_id::text" in sql
