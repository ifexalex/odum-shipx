"""Field-level encryption for sensitive PII columns.

Uses AWS KMS to generate a per-value data key, then encrypts with Fernet
(AES-128-CBC + HMAC-SHA256). The encrypted data key is stored alongside the
ciphertext so decryption can always recover the plaintext without storing
the key separately.

Encrypted values are base64-encoded strings safe to store in TEXT columns.

Usage:
    from shared.encryption import encrypt_field, decrypt_field

    # On write:
    stored = encrypt_field(plaintext_id_number)

    # On read:
    plaintext = decrypt_field(stored)

Environment:
    ENCRYPTION_KMS_KEY_ID — ARN or alias of the KMS key used for data key generation.
    If unset (e.g. in local dev), values are stored unencrypted with a warning.
"""

import base64
import logging
import os

logger = logging.getLogger(__name__)

_KMS_KEY_ID = os.environ.get("ENCRYPTION_KMS_KEY_ID", "")

# Separator between the encrypted KMS data key and the Fernet ciphertext.
# Using b"||" — safe since base64url does not contain |.
_SEP = b"||"

_kms_client = None


def _get_kms():
    global _kms_client
    if _kms_client is None:
        import boto3
        _kms_client = boto3.client("kms", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    return _kms_client


def encrypt_field(plaintext: str | None) -> str | None:
    """Encrypt a plaintext string using KMS + Fernet.

    Returns a base64-encoded token that can be stored in a TEXT column.
    If ENCRYPTION_KMS_KEY_ID is not configured, returns plaintext unchanged
    (development fallback — logs a warning).
    """
    if plaintext is None:
        return None
    if not _KMS_KEY_ID:
        logger.warning(
            "ENCRYPTION_KMS_KEY_ID not set — storing sensitive field unencrypted"
        )
        return plaintext
    try:
        from cryptography.fernet import Fernet

        kms = _get_kms()
        resp = kms.generate_data_key(KeyId=_KMS_KEY_ID, KeySpec="AES_256")
        # AES_256 yields exactly 32 bytes; raise explicitly to catch any KMS API change early.
        if len(resp["Plaintext"]) != 32:
            raise RuntimeError(f"KMS AES_256 data key must be exactly 32 bytes, got {len(resp['Plaintext'])}")
        fernet_key = base64.urlsafe_b64encode(resp["Plaintext"])
        f = Fernet(fernet_key)
        ciphertext = f.encrypt(plaintext.encode("utf-8"))
        # Combine encrypted KMS data key + ciphertext
        combined = resp["CiphertextBlob"] + _SEP + ciphertext
        return base64.b64encode(combined).decode("ascii")
    except Exception as exc:
        logger.error("Field encryption failed: %s", exc)
        raise


def decrypt_field(token: str | None) -> str | None:
    """Decrypt a token produced by encrypt_field.

    If ENCRYPTION_KMS_KEY_ID is not configured, returns token unchanged
    (mirrors the development fallback in encrypt_field).
    """
    if token is None:
        return None
    if not _KMS_KEY_ID:
        return token
    try:
        from cryptography.fernet import Fernet

        raw = base64.b64decode(token.encode("ascii"))
        sep_idx = raw.index(_SEP)
        enc_key = raw[:sep_idx]
        ciphertext = raw[sep_idx + len(_SEP):]
        kms = _get_kms()
        resp = kms.decrypt(CiphertextBlob=enc_key)
        if len(resp["Plaintext"]) != 32:
            raise RuntimeError(f"KMS decrypted data key must be exactly 32 bytes, got {len(resp['Plaintext'])}")
        fernet_key = base64.urlsafe_b64encode(resp["Plaintext"])
        f = Fernet(fernet_key)
        return f.decrypt(ciphertext).decode("utf-8")
    except Exception as exc:
        logger.error("Field decryption failed: %s", exc)
        raise
