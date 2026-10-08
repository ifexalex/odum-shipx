"""Unit tests for the Azure Key Vault adapters (KeyProvider + SecretsProvider).

No official Key Vault emulator exists, so these use stubbed Key Vault clients —
same rigor as the SES/Service-Bus stubs. The crypto test still exercises the real
`shared/encryption.py` Fernet envelope (only the Key-Vault wrap/unwrap is stubbed),
so the envelope round-trip is genuinely validated end-to-end.
"""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("azure.keyvault.keys")

from shared.providers.base import KeyProvider, SecretsProvider  # noqa: E402


class _FakeCrypto:
    """Reversible stub of Key Vault's CryptographyClient wrap/unwrap."""

    _MARK = b"WRAP::"

    def wrap_key(self, algorithm, key):  # noqa: ANN001
        return SimpleNamespace(encrypted_key=self._MARK + key)

    def unwrap_key(self, algorithm, encrypted_key):  # noqa: ANN001
        assert encrypted_key.startswith(self._MARK)
        return SimpleNamespace(key=encrypted_key[len(self._MARK) :])


def _key_provider(monkeypatch):
    from shared.providers.azure.keyvault import KeyVaultKeyProvider

    provider = KeyVaultKeyProvider("https://vault.vault.azure.net/keys/data-key")
    monkeypatch.setattr(provider, "_crypto_client", lambda: _FakeCrypto())
    return provider


class TestKeyVaultKeyProvider:
    def test_satisfies_the_key_protocol(self, monkeypatch):
        assert isinstance(_key_provider(monkeypatch), KeyProvider)

    def test_generate_returns_32_byte_key_and_wrapped_blob(self, monkeypatch):
        provider = _key_provider(monkeypatch)
        plaintext, wrapped = provider.generate_data_key()
        assert len(plaintext) == 32
        assert wrapped == b"WRAP::" + plaintext

    def test_generate_then_decrypt_round_trips(self, monkeypatch):
        provider = _key_provider(monkeypatch)
        plaintext, wrapped = provider.generate_data_key()
        assert provider.decrypt_data_key(wrapped) == plaintext

    def test_decrypt_rejects_non_32_byte_key(self, monkeypatch):
        provider = _key_provider(monkeypatch)
        with pytest.raises(RuntimeError):
            provider.decrypt_data_key(b"WRAP::short")

    def test_integrates_with_the_real_fernet_envelope(self, monkeypatch):
        """encrypt_field/decrypt_field round-trip with the Azure KeyProvider —
        only the Key Vault wrap is stubbed; the Fernet envelope is real."""
        from shared import encryption

        provider = _key_provider(monkeypatch)
        monkeypatch.setattr(encryption, "get_key_provider", lambda: provider)

        token = encryption.encrypt_field("id-number-12345")
        assert token != "id-number-12345"
        assert encryption.decrypt_field(token) == "id-number-12345"


class TestKeyVaultSecretsProvider:
    def test_satisfies_the_secrets_protocol_and_returns_value(self, monkeypatch):
        from shared.providers.azure.keyvault_secrets import KeyVaultSecretsProvider

        provider = KeyVaultSecretsProvider()
        fake = SimpleNamespace(get_secret=lambda name: SimpleNamespace(value='{"password": "p"}'))
        monkeypatch.setattr(provider, "_secret_client", lambda: fake)

        assert isinstance(provider, SecretsProvider)
        assert provider.get_secret("db-creds") == '{"password": "p"}'


class TestFactorySelectsAzureKeyVault:
    def test_key_provider_factory(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.azure.keyvault import KeyVaultKeyProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_key_provider", None)
        monkeypatch.setattr(providers, "_key_resolved", False)
        monkeypatch.setenv("ENCRYPTION_KEY_VAULT_KEY_ID", "https://vault.vault.azure.net/keys/data-key")

        assert isinstance(providers.get_key_provider(), KeyVaultKeyProvider)

    def test_secrets_provider_factory(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.azure.keyvault_secrets import KeyVaultSecretsProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_secrets_provider", None)

        provider = providers.get_secrets_provider()
        assert isinstance(provider, KeyVaultSecretsProvider)
        assert provider is providers.get_secrets_provider()  # cached singleton


# ---------------------------------------------------------------------------
# Real Key Vault integration — runs only when pointed at an actual vault
# (needs `az login` for DefaultAzureCredential). Verifies the KeyProvider +
# SecretsProvider against the resources the keyvault Terraform module creates:
#   export AZURE_KEY_VAULT_URL=$(terraform -chdir=infrastructure/azure output -raw key_vault_url)
#   export ENCRYPTION_KEY_VAULT_KEY_ID=$(terraform -chdir=infrastructure/azure output -raw encryption_key_vault_key_id)
# ---------------------------------------------------------------------------
_REAL_VAULT = os.environ.get("AZURE_KEY_VAULT_URL", "")
_REAL_KEY_ID = os.environ.get("ENCRYPTION_KEY_VAULT_KEY_ID", "")


@pytest.mark.skipif(
    not (_REAL_VAULT and _REAL_KEY_ID),
    reason="AZURE_KEY_VAULT_URL / ENCRYPTION_KEY_VAULT_KEY_ID not set (no real vault)",
)
class TestAgainstRealKeyVault:
    def test_secret_round_trips(self):
        from shared.providers.azure.keyvault_secrets import KeyVaultSecretsProvider

        name = os.environ.get("AZURE_KEYVAULT_SMOKE_SECRET", "shipx-smoke-secret")
        assert KeyVaultSecretsProvider().get_secret(name) == "ok"

    def test_envelope_key_wrap_unwrap_round_trips(self):
        from shared.providers.azure.keyvault import KeyVaultKeyProvider

        provider = KeyVaultKeyProvider(_REAL_KEY_ID)
        plaintext, wrapped = provider.generate_data_key()
        assert len(plaintext) == 32
        assert provider.decrypt_data_key(wrapped) == plaintext

    def test_integrates_with_the_real_fernet_envelope(self, monkeypatch):
        from shared import encryption
        from shared.providers.azure.keyvault import KeyVaultKeyProvider

        monkeypatch.setattr(encryption, "get_key_provider", lambda: KeyVaultKeyProvider(_REAL_KEY_ID))
        token = encryption.encrypt_field("id-number-12345")
        assert token != "id-number-12345"
        assert encryption.decrypt_field(token) == "id-number-12345"
