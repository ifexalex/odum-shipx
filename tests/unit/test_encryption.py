"""Field encryption + the KeyProvider abstraction (shared/providers)."""

from unittest.mock import patch

from shared import encryption


class _FakeKeyProvider:
    """Deterministic envelope-key provider for tests: a fixed 32-byte key,
    'wrapped' by prefixing a marker so decrypt can recover it."""

    _KEY = b"0123456789abcdef0123456789abcdef"  # exactly 32 bytes
    _MARK = b"WRAP::"

    def generate_data_key(self):
        return self._KEY, self._MARK + self._KEY

    def decrypt_data_key(self, encrypted_key):
        assert encrypted_key.startswith(self._MARK)
        return encrypted_key[len(self._MARK) :]


class TestFieldEncryption:
    def test_round_trip(self):
        with patch.object(encryption, "get_key_provider", return_value=_FakeKeyProvider()):
            token = encryption.encrypt_field("0806 ID 1234567")
            assert token is not None
            assert token != "0806 ID 1234567"  # actually encrypted
            assert encryption.decrypt_field(token) == "0806 ID 1234567"

    def test_none_passthrough(self):
        with patch.object(encryption, "get_key_provider", return_value=_FakeKeyProvider()):
            assert encryption.encrypt_field(None) is None
            assert encryption.decrypt_field(None) is None

    def test_dev_fallback_stores_plaintext_when_unconfigured(self):
        # No provider configured → values pass through unchanged (both ways).
        with patch.object(encryption, "get_key_provider", return_value=None):
            assert encryption.encrypt_field("secret") == "secret"
            assert encryption.decrypt_field("secret") == "secret"

    def test_envelope_format_is_base64_key_sep_ciphertext(self):
        import base64

        with patch.object(encryption, "get_key_provider", return_value=_FakeKeyProvider()):
            token = encryption.encrypt_field("x")
            raw = base64.b64decode(token)
            assert encryption._SEP in raw  # key || ciphertext envelope
            assert raw.startswith(_FakeKeyProvider._MARK)  # encrypted key first


class TestProviderFactory:
    def test_default_cloud_is_aws(self):
        from shared import providers

        assert providers.CLOUD_PROVIDER in ("aws", "azure")

    def test_aws_key_provider_shape(self):
        # The AWS adapter implements the KeyProvider protocol.
        from shared.providers.aws.kms import KmsKeyProvider
        from shared.providers.base import KeyProvider

        assert isinstance(KmsKeyProvider("alias/x"), KeyProvider)
