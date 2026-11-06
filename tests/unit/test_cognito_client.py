"""Unit tests for shared.providers.aws.cognito (CognitoIdentityProvider) — group management.

Uses a real (moto-mocked) Cognito user pool rather than a MagicMock so these
tests exercise the actual boto3 call shapes (admin_add_user_to_group /
admin_remove_user_from_group / admin_list_groups_for_user), not just that
"some method got called." sync_user_groups is the direct fix for the bug
where changing a staff member's role never actually updated their Cognito
group membership — these are the regression tests for that fix.
"""

import os

import boto3
import pytest
from moto import mock_aws

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def cognito_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def client(cognito_env):
    with mock_aws():
        from shared.providers.aws.cognito import CognitoIdentityProvider

        idp = boto3.client("cognito-idp", region_name="us-east-1")
        pool = idp.create_user_pool(PoolName="test-pool")
        pool_id = pool["UserPool"]["Id"]
        os.environ["COGNITO_USER_POOL_ID"] = pool_id

        idp.admin_create_user(
            UserPoolId=pool_id,
            Username="staff@acme.com",
            UserAttributes=[{"Name": "email", "Value": "staff@acme.com"}],
            MessageAction="SUPPRESS",
        )

        yield CognitoIdentityProvider()


class TestRemoveUserFromGroup:
    def test_removes_membership(self, client):
        client.create_group_if_not_exists(f"{TENANT_ID}:tenant_admin")
        client.add_user_to_group("staff@acme.com", f"{TENANT_ID}:tenant_admin")
        assert client.list_groups_for_user("staff@acme.com") == {f"{TENANT_ID}:tenant_admin"}

        client.remove_user_from_group("staff@acme.com", f"{TENANT_ID}:tenant_admin")

        assert client.list_groups_for_user("staff@acme.com") == set()

    def test_missing_user_does_not_raise(self, client):
        client.create_group_if_not_exists(f"{TENANT_ID}:tenant_admin")
        # UserNotFoundException is swallowed — mirrors global_sign_out's posture.
        client.remove_user_from_group("nobody@acme.com", f"{TENANT_ID}:tenant_admin")


class TestListGroupsForUser:
    def test_empty_when_no_groups(self, client):
        assert client.list_groups_for_user("staff@acme.com") == set()

    def test_returns_all_assigned_groups(self, client):
        client.create_group_if_not_exists(f"{TENANT_ID}:nigeria_office_staff")
        client.create_group_if_not_exists(f"{TENANT_ID}:warehouse_attendant")
        client.add_user_to_group("staff@acme.com", f"{TENANT_ID}:nigeria_office_staff")
        client.add_user_to_group("staff@acme.com", f"{TENANT_ID}:warehouse_attendant")

        assert client.list_groups_for_user("staff@acme.com") == {
            f"{TENANT_ID}:nigeria_office_staff",
            f"{TENANT_ID}:warehouse_attendant",
        }


class TestSyncUserGroups:
    """The direct regression tests for the group-sync bug: changing roles
    must add newly-assigned groups AND remove unassigned ones."""

    def test_add_only_from_no_groups(self, client):
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"tenant_admin"})

        assert client.list_groups_for_user("staff@acme.com") == {f"{TENANT_ID}:tenant_admin"}

    def test_add_only_extends_existing_membership(self, client):
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff"})

        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff", "warehouse_attendant"})

        assert client.list_groups_for_user("staff@acme.com") == {
            f"{TENANT_ID}:nigeria_office_staff",
            f"{TENANT_ID}:warehouse_attendant",
        }

    def test_remove_only_drops_unassigned_role(self, client):
        """This is the exact bug scenario: a role is taken away and the
        corresponding Cognito group must actually be removed."""
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff", "warehouse_attendant"})

        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff"})

        assert client.list_groups_for_user("staff@acme.com") == {f"{TENANT_ID}:nigeria_office_staff"}

    def test_add_and_remove_diff_in_one_call(self, client):
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff"})

        client.sync_user_groups("staff@acme.com", TENANT_ID, {"warehouse_attendant"})

        assert client.list_groups_for_user("staff@acme.com") == {f"{TENANT_ID}:warehouse_attendant"}

    def test_no_op_when_groups_already_match(self, client):
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"tenant_admin"})

        # Second call with the same desired set must not error or change anything.
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"tenant_admin"})

        assert client.list_groups_for_user("staff@acme.com") == {f"{TENANT_ID}:tenant_admin"}

    def test_never_touches_other_tenants_groups(self, client):
        """sync_user_groups must only diff this tenant's `{tenant_id}:*`
        groups — never platform_admin or another tenant's groups."""
        client.create_group_if_not_exists("platform_admin")
        client.add_user_to_group("staff@acme.com", "platform_admin")
        client.sync_user_groups("staff@acme.com", OTHER_TENANT_ID, {"tenant_admin"})

        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff"})

        assert client.list_groups_for_user("staff@acme.com") == {
            "platform_admin",
            f"{OTHER_TENANT_ID}:tenant_admin",
            f"{TENANT_ID}:nigeria_office_staff",
        }

    def test_empty_roles_removes_all_of_this_tenants_groups(self, client):
        client.sync_user_groups("staff@acme.com", TENANT_ID, {"nigeria_office_staff", "warehouse_attendant"})

        client.sync_user_groups("staff@acme.com", TENANT_ID, set())

        assert client.list_groups_for_user("staff@acme.com") == set()


class TestCreateUserWithPassword:
    """Customer-invite acceptance path: no temp-password email, permanent
    password set directly so the customer can log in immediately."""

    def test_creates_user_with_permanent_password(self, client):
        sub = client.create_user_with_password(
            email="customer@acme.com",
            full_name="Ngozi Okonkwo",
            tenant_id=TENANT_ID,
            role="customer",
            password="Sup3rSecret!",
        )

        assert sub

        idp = client.client
        user = idp.admin_get_user(UserPoolId=client.user_pool_id, Username="customer@acme.com")
        assert user["UserStatus"] == "CONFIRMED"
        attrs = {a["Name"]: a["Value"] for a in user["UserAttributes"]}
        assert attrs["custom:role"] == "customer"
        assert attrs["custom:tenant_id"] == TENANT_ID

    def test_duplicate_email_raises(self, client):
        from shared.exceptions import DuplicateResourceError

        client.create_user_with_password(
            email="dup@acme.com",
            full_name="First",
            tenant_id=TENANT_ID,
            role="customer",
            password="Sup3rSecret!",
        )
        with pytest.raises(DuplicateResourceError):
            client.create_user_with_password(
                email="dup@acme.com",
                full_name="Second",
                tenant_id=TENANT_ID,
                role="customer",
                password="Sup3rSecret!",
            )


class TestIdentityProviderPort:
    def test_adapter_satisfies_the_port(self, client):
        from shared.providers.base import IdentityProvider

        assert isinstance(client, IdentityProvider)

    def test_factory_default_cloud_returns_cognito(self, cognito_env, monkeypatch):
        with mock_aws():
            boto3.client("cognito-idp", region_name="us-east-1").create_user_pool(PoolName="p")
            os.environ["COGNITO_USER_POOL_ID"] = "us-east-1_test"

            import shared.providers as providers
            from shared.providers.aws.cognito import CognitoIdentityProvider

            monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
            monkeypatch.setattr(providers, "_identity_provider", None)

            provider = providers.get_identity_provider()
            assert isinstance(provider, CognitoIdentityProvider)
            assert provider is providers.get_identity_provider()  # cached singleton
