"""Field-level encryption for sensitive PII columns.

Generates a per-value 32-byte data key via the configured cloud KeyProvider
(AWS KMS today; Azure Key Vault behind the same interface), then encrypts with
Fernet (AES-128-CBC + HMAC-SHA256). The encrypted data key is stored alongside
the ciphertext so decryption can always recover the plaintext.

Encrypted values are base64-encoded strings safe to store in TEXT columns. The
envelope format is `base64(encrypted_data_key || fernet_ciphertext)` — unchanged
from the original KMS-only implementation, so existing ciphertext stays readable.

Usage:
    from shared.encryption import encrypt_field, decrypt_field
    stored    = encrypt_field(plaintext_id_number)   # on write
    plaintext = decrypt_field(stored)                # on read

Configuration (via shared/providers):
    CLOUD_PROVIDER=aws   → ENCRYPTION_KMS_KEY_ID        (KMS key ARN/alias)
    CLOUD_PROVIDER=azure → ENCRYPTION_KEY_VAULT_KEY_ID  (Key Vault key id)
    If unset (e.g. local dev), values are stored unencrypted with a warning.
"""

import base64
import logging

from shared.providers import get_key_provider

logger = logging.getLogger(__name__)

# Separator between the encrypted data key and the Fernet ciphertext.
# b"||" is safe — base64url does not contain "|".
_SEP = b"||"


def encrypt_field(plaintext: str | None) -> str | None:
    """Encrypt a plaintext string with a provider data key + Fernet.

    Returns a base64-encoded token for a TEXT column. When no key provider is
    configured, returns the plaintext unchanged (dev fallback — logs a warning).
    """
    if plaintext is None:
        return None
    provider = get_key_provider()
    if provider is None:
        logger.warning("Field encryption not configured — storing sensitive field unencrypted")
        return plaintext
    try:
        from cryptography.fernet import Fernet

        plain_key, enc_key = provider.generate_data_key()
        f = Fernet(base64.urlsafe_b64encode(plain_key))
        ciphertext = f.encrypt(plaintext.encode("utf-8"))
        combined = enc_key + _SEP + ciphertext
        return base64.b64encode(combined).decode("ascii")
    except Exception as exc:
        logger.error("Field encryption failed: %s", exc)
        raise


def decrypt_field(token: str | None) -> str | None:
    """Decrypt a token produced by encrypt_field.

    When no key provider is configured, returns the token unchanged (mirrors the
    dev fallback in encrypt_field).
    """
    if token is None:
        return None
    provider = get_key_provider()
    if provider is None:
        return token
    try:
        from cryptography.fernet import Fernet

        raw = base64.b64decode(token.encode("ascii"))
        # The LAST separator: the wrapped key is binary (KMS / Key Vault output) and can contain b"||" itself, about
        # once in 300 keys; the Fernet ciphertext is base64url and never contains "|". Splitting at the first one made
        # those values undecryptable; splitting at the last reads them, including any written before this fix.
        sep_idx = raw.rindex(_SEP)
        enc_key = raw[:sep_idx]
        ciphertext = raw[sep_idx + len(_SEP) :]
        plain_key = provider.decrypt_data_key(enc_key)
        f = Fernet(base64.urlsafe_b64encode(plain_key))
        plaintext: bytes = f.decrypt(ciphertext)
        return plaintext.decode("utf-8")
    except Exception as exc:
        logger.error("Field decryption failed: %s", exc)
        raise
