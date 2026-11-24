"""AWS Cognito identity provider (user/group provisioning).

Manages Cognito users and groups as the authoritative identity store on AWS.
Each tenant has groups named `{tenant_id}:{role}`. Behaviour is identical to the
former `services/tenant_management/cognito_client.py` — only the location and
class name changed, so it now sits behind the `IdentityProvider` port.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class CognitoIdentityProvider:
    """IdentityProvider backed by boto3 cognito-idp for user/group provisioning."""

    def __init__(self) -> None:
        import boto3

        self.client: Any = boto3.client("cognito-idp", region_name=os.environ["AWS_REGION"])
        self.user_pool_id = os.environ["COGNITO_USER_POOL_ID"]

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(self, email: str, full_name: str, tenant_id: str, role: str) -> str:
        """Create a Cognito user and return the cognito_sub (UUID).

        Sends a temporary password to the user's email via Cognito. The user
        must change their password on first login.

        Raises:
            DuplicateResourceError: If a user with this email already exists.
            ExternalServiceError: On any other Cognito failure.
        """
        from botocore.exceptions import ClientError

        from shared.exceptions import DuplicateResourceError, ExternalServiceError

        try:
            resp = self.client.admin_create_user(
                UserPoolId=self.user_pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": full_name},
                    {"Name": "custom:tenant_id", "Value": tenant_id},
                    {"Name": "custom:role", "Value": role},
                ],
                DesiredDeliveryMediums=["EMAIL"],
            )
            sub: str = next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub")
            logger.info("Cognito user created: tenant_id=%s role=%s sub=%s", tenant_id, role, sub)
            return sub
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "UsernameExistsException":
                raise DuplicateResourceError("user", email) from exc
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def create_user_with_password(self, email: str, full_name: str, tenant_id: str, role: str, password: str) -> str:
        """Create a Cognito user with a caller-chosen permanent password and return the sub.

        Used by flows where the person sets their own password at creation time
        (customer invite acceptance) rather than receiving a Cognito temp-password
        email — `MessageAction="SUPPRESS"` skips that email, and
        `admin_set_user_password(..., Permanent=True)` sets the password directly
        so no NEW_PASSWORD_REQUIRED challenge is needed on first login.

        Raises:
            DuplicateResourceError: If a user with this email already exists.
            ExternalServiceError: On any other Cognito failure.
        """
        from botocore.exceptions import ClientError

        from shared.exceptions import DuplicateResourceError, ExternalServiceError

        try:
            resp = self.client.admin_create_user(
                UserPoolId=self.user_pool_id,
                Username=email,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "name", "Value": full_name},
                    {"Name": "custom:tenant_id", "Value": tenant_id},
                    {"Name": "custom:role", "Value": role},
                ],
                MessageAction="SUPPRESS",
            )
            sub: str = next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub")
            self.client.admin_set_user_password(
                UserPoolId=self.user_pool_id,
                Username=email,
                Password=password,
                Permanent=True,
            )
            logger.info("Cognito user created with password: tenant_id=%s role=%s sub=%s", tenant_id, role, sub)
            return sub
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "UsernameExistsException":
                raise DuplicateResourceError("user", email) from exc
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def update_user_attributes(self, username: str, full_name: str | None = None, role: str | None = None) -> None:
        """Update mutable Cognito attributes (name, custom:role)."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        attrs = []
        if full_name is not None:
            attrs.append({"Name": "name", "Value": full_name})
        if role is not None:
            attrs.append({"Name": "custom:role", "Value": role})
        if not attrs:
            return
        try:
            self.client.admin_update_user_attributes(
                UserPoolId=self.user_pool_id,
                Username=username,
                UserAttributes=attrs,
            )
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def delete_user(self, username: str) -> None:
        """Permanently delete a Cognito user (GDPR erasure). UserNotFoundException is a no-op."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_delete_user(UserPoolId=self.user_pool_id, Username=username)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UserNotFoundException":
                return
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def disable_user(self, username: str) -> None:
        """Disable (deactivate) a Cognito user account."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_disable_user(UserPoolId=self.user_pool_id, Username=username)
            logger.info("Cognito user disabled")
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def global_sign_out(self, username: str) -> None:
        """Invalidate all active sessions (access + refresh tokens) for a user.

        Called during tenant offboarding to prevent token reuse after offboard.
        UserNotFoundException is silently swallowed — the user may already be
        deleted or may never have logged in.
        """
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_user_global_sign_out(UserPoolId=self.user_pool_id, Username=username)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UserNotFoundException":
                return
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def enable_user(self, username: str) -> None:
        """Re-enable a previously disabled Cognito user account."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_enable_user(UserPoolId=self.user_pool_id, Username=username)
            logger.info("Cognito user enabled")
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def resend_invite(self, username: str) -> None:
        """Resend the temporary-password invite email to an existing Cognito user."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_create_user(
                UserPoolId=self.user_pool_id,
                Username=username,
                MessageAction="RESEND",
                DesiredDeliveryMediums=["EMAIL"],
            )
            logger.info("Cognito invite resent for %s", username)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def reset_password(self, username: str) -> None:
        """Trigger a Cognito-managed password-reset email for the user."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_reset_user_password(UserPoolId=self.user_pool_id, Username=username)
            logger.info("Cognito password reset triggered for %s", username)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def set_password(self, username: str, password: str, force_change: bool = False) -> None:
        """Set a permanent password directly (admin), for ShipX account activation —
        the user chooses their own password via a ShipX link. `force_change` True
        sets a temporary password instead (NEW_PASSWORD_REQUIRED on next login)."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_set_user_password(
                UserPoolId=self.user_pool_id,
                Username=username,
                Password=password,
                Permanent=not force_change,
            )
            logger.info("Cognito password set for %s (permanent=%s)", username, not force_change)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    def create_group_if_not_exists(self, group_name: str) -> None:
        """Create a Cognito group; silently skips if it already exists."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.create_group(GroupName=group_name, UserPoolId=self.user_pool_id)
            logger.info("Cognito group created: %s", group_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "GroupExistsException":
                return
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def add_user_to_group(self, username: str, group_name: str) -> None:
        """Add a Cognito user to a group."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_add_user_to_group(UserPoolId=self.user_pool_id, Username=username, GroupName=group_name)
            logger.info("Cognito user %s added to group %s", username, group_name)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def remove_user_from_group(self, username: str, group_name: str) -> None:
        """Remove a Cognito user from a group."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            self.client.admin_remove_user_from_group(UserPoolId=self.user_pool_id, Username=username, GroupName=group_name)
            logger.info("Cognito user %s removed from group %s", username, group_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UserNotFoundException":
                return
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def list_groups_for_user(self, username: str) -> set[str]:
        """Return the set of Cognito group names the user currently belongs to."""
        from botocore.exceptions import ClientError

        from shared.exceptions import ExternalServiceError

        try:
            groups: set[str] = set()
            paginator = self.client.get_paginator("admin_list_groups_for_user")
            for page in paginator.paginate(Username=username, UserPoolId=self.user_pool_id):
                groups.update(g["GroupName"] for g in page.get("Groups", []))
            return groups
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "UserNotFoundException":
                return set()
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def sync_user_groups(self, username: str, tenant_id: str, roles: set[str]) -> None:
        """Reconcile a user's Cognito group membership to exactly match `roles`.

        Diffs current groups (scoped to this tenant's `{tenant_id}:*` groups only
        — never touches `platform_admin` or another tenant's groups) against the
        desired role set and adds/removes as needed, so a DB role change actually
        propagates to Cognito permissions on next login.
        """
        prefix = f"{tenant_id}:"
        desired_groups = {f"{prefix}{role}" for role in roles}
        current_groups = {g for g in self.list_groups_for_user(username) if g.startswith(prefix)}

        for group_name in desired_groups - current_groups:
            self.create_group_if_not_exists(group_name)
            self.add_user_to_group(username, group_name)
        for group_name in current_groups - desired_groups:
            self.remove_user_from_group(username, group_name)
