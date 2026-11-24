"""AWS KMS envelope-key provider."""

import os
from typing import Any


class KmsKeyProvider:
    """KeyProvider backed by AWS KMS `generate_data_key` / `decrypt`.

    Behaviour is identical to the original `shared/encryption.py` so existing
    ciphertext stays decryptable: AES_256 data key, `CiphertextBlob` as the
    stored `encrypted_key`.
    """

    def __init__(self, key_id: str, region: str | None = None) -> None:
        self._key_id = key_id
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _kms(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("kms", region_name=self._region)
        return self._client

    def generate_data_key(self) -> tuple[bytes, bytes]:
        resp = self._kms().generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
        if len(resp["Plaintext"]) != 32:
            raise RuntimeError(f"KMS AES_256 data key must be exactly 32 bytes, got {len(resp['Plaintext'])}")
        return bytes(resp["Plaintext"]), bytes(resp["CiphertextBlob"])

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        resp = self._kms().decrypt(CiphertextBlob=encrypted_key, KeyId=self._key_id)
        if len(resp["Plaintext"]) != 32:
            raise RuntimeError(f"KMS decrypted data key must be exactly 32 bytes, got {len(resp['Plaintext'])}")
        return bytes(resp["Plaintext"])
