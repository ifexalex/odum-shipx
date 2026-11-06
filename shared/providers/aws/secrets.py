"""AWS Secrets Manager provider."""

import os
from typing import Any


class SecretsManagerProvider:
    """SecretsProvider backed by AWS Secrets Manager.

    Returns the raw `SecretString`; callers that store JSON (DB credentials, the
    impersonation signing key) parse it themselves.
    """

    def __init__(self, region: str | None = None) -> None:
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _sm(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    def get_secret(self, secret_id: str) -> str:
        resp = self._sm().get_secret_value(SecretId=secret_id)
        return str(resp["SecretString"])
