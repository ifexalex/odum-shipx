"""Azure Key Vault envelope-key provider — the Azure analogue of `aws/kms.py`.

Key Vault has no KMS-style `generate_data_key`, so the envelope is built the
standard Azure way: generate a random 32-byte AES-256 data key locally, then
**wrap** it with a Key Vault key (RSA-OAEP-256) to produce the stored
`encrypted_key`; `decrypt_data_key` **unwraps** it. The Fernet layer in
`shared/encryption.py` is identical to the AWS path — only the wrapping differs,
so the envelope format (`base64(encrypted_key || "||" || ciphertext)`) is
unchanged. (Values encrypted under one cloud's key can only be decrypted under
that same key — cross-cloud re-encryption is an ADR-004 migration concern.)
"""
import os
from typing import Any

_WRAP_ALGO = "RSA-OAEP-256"


class KeyVaultKeyProvider:
    """KeyProvider backed by Azure Key Vault key wrap/unwrap."""

    def __init__(self, key_id: str) -> None:
        # key_id is the full Key Vault key identifier
        # (https://<vault>.vault.azure.net/keys/<name>[/<version>]).
        self._key_id = key_id
        self._crypto: Any = None

    def _crypto_client(self) -> Any:
        if self._crypto is None:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.keys.crypto import CryptographyClient

            self._crypto = CryptographyClient(self._key_id, credential=DefaultAzureCredential())
        return self._crypto

    def generate_data_key(self) -> tuple[bytes, bytes]:
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm

        plaintext = os.urandom(32)  # AES-256 data key
        result = self._crypto_client().wrap_key(KeyWrapAlgorithm(_WRAP_ALGO), plaintext)
        return plaintext, bytes(result.encrypted_key)

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm

        result = self._crypto_client().unwrap_key(KeyWrapAlgorithm(_WRAP_ALGO), encrypted_key)
        plaintext = bytes(result.key)
        if len(plaintext) != 32:
            raise RuntimeError(f"Key Vault unwrapped data key must be exactly 32 bytes, got {len(plaintext)}")
        return plaintext
