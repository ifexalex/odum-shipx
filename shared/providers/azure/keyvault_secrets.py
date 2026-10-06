"""Azure Key Vault secrets provider — the Azure analogue of `aws/secrets.py`.

Returns the raw secret string so callers that store JSON parse it themselves
(parity with the Secrets Manager adapter). `secret_id` is a Key Vault secret name
(on AWS the same port parameter is a Secrets Manager ARN) — the per-secret env
vars (`DB_SECRET_ARN`, `IMPERSONATION_SECRET_ARN`) hold secret names on Azure.
The vault is `AZURE_KEY_VAULT_URL`; auth is `DefaultAzureCredential`.
"""
import os
from typing import Any


class KeyVaultSecretsProvider:
    """SecretsProvider backed by Azure Key Vault secrets."""

    def __init__(self) -> None:
        self._vault_url = os.environ.get("AZURE_KEY_VAULT_URL", "")
        self._client: Any = None

    def _secret_client(self) -> Any:
        if self._client is None:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            self._client = SecretClient(vault_url=self._vault_url, credential=DefaultAzureCredential())
        return self._client

    def get_secret(self, secret_id: str) -> str:
        return str(self._secret_client().get_secret(secret_id).value)
