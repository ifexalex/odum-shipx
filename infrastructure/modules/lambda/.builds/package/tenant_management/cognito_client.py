"""Cognito user provisioning wrapper for the Tenant Management service.

Manages Cognito users and groups as the authoritative identity store for the
logistics platform. Each tenant has groups named `{tenant_id}:{role}`.

Module-level singleton is reused across warm Lambda invocations.
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from shared.exceptions import DuplicateResourceError, ExternalServiceError

logger = logging.getLogger(__name__)


class CognitoClient:
    """Thin wrapper around boto3 cognito-idp for user/group provisioning."""

    def __init__(self) -> None:
        self.client = boto3.client(
            "cognito-idp",
            region_name=os.environ["AWS_REGION"],
        )
        self.user_pool_id = os.environ["COGNITO_USER_POOL_ID"]

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    def create_user(
        self,
        email: str,
        full_name: str,
        tenant_id: str,
        role: str,
    ) -> str:
        """Create a Cognito user and return the cognito_sub (UUID).

        Sends a temporary password to the user's email via Cognito.
        The user must change their password on first login.

        Raises:
            DuplicateResourceError: If a user with this email already exists.
            ExternalServiceError: On any other Cognito failure.
        """
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
            sub = next(
                a["Value"]
                for a in resp["User"]["Attributes"]
                if a["Name"] == "sub"
            )
            logger.info(
                "Cognito user created: email=%s tenant_id=%s role=%s sub=%s",
                email, tenant_id, role, sub,
            )
            return sub
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "UsernameExistsException":
                raise DuplicateResourceError("user", email) from exc
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def disable_user(self, username: str) -> None:
        """Disable (deactivate) a Cognito user account."""
        try:
            self.client.admin_disable_user(
                UserPoolId=self.user_pool_id,
                Username=username,
            )
            logger.info("Cognito user disabled: %s", username)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def enable_user(self, username: str) -> None:
        """Re-enable a previously disabled Cognito user account."""
        try:
            self.client.admin_enable_user(
                UserPoolId=self.user_pool_id,
                Username=username,
            )
            logger.info("Cognito user enabled: %s", username)
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    def create_group_if_not_exists(self, group_name: str) -> None:
        """Create a Cognito group; silently skips if it already exists."""
        try:
            self.client.create_group(
                GroupName=group_name,
                UserPoolId=self.user_pool_id,
            )
            logger.info("Cognito group created: %s", group_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "GroupExistsException":
                return
            raise ExternalServiceError("Cognito", str(exc)) from exc

    def add_user_to_group(self, username: str, group_name: str) -> None:
        """Add a Cognito user to a group."""
        try:
            self.client.admin_add_user_to_group(
                UserPoolId=self.user_pool_id,
                Username=username,
                GroupName=group_name,
            )
            logger.info(
                "Cognito user %s added to group %s", username, group_name
            )
        except ClientError as exc:
            raise ExternalServiceError("Cognito", str(exc)) from exc


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_cognito: CognitoClient | None = None


def get_cognito_client() -> CognitoClient:
    """Return the module-level CognitoClient, creating it on first call."""
    global _cognito
    if _cognito is None:
        _cognito = CognitoClient()
    return _cognito
