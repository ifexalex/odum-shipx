"""Provider factories — resolve the active cloud adapter from CLOUD_PROVIDER.

    CLOUD_PROVIDER = aws (default) | azure

Factories return None when a capability is not configured, preserving the
existing dev-fallback behaviour (e.g. no encryption key → values stored in
plaintext with a warning).
"""
import os

from shared.providers.base import (
    ClaimsMapper,
    EmailProvider,
    EventProvider,
    IdentityProvider,
    KeyProvider,
    QueueProvider,
    SecretsProvider,
    StorageProvider,
)

CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws").lower()

_key_provider: KeyProvider | None = None
_key_resolved = False

# Storage providers are cached per bucket/container — the default bucket plus any
# explicitly-named one (e.g. the GDPR tenant-data bucket).
_storage_providers: dict[str, StorageProvider] = {}

_secrets_provider: SecretsProvider | None = None
_event_provider: EventProvider | None = None
_queue_provider: QueueProvider | None = None
_email_provider: EmailProvider | None = None
_identity_provider: IdentityProvider | None = None
_claims_mapper: ClaimsMapper | None = None


def get_key_provider() -> KeyProvider | None:
    """Return the configured envelope-key provider, or None when field
    encryption is not configured."""
    global _key_provider, _key_resolved
    if _key_resolved:
        return _key_provider
    _key_resolved = True

    if CLOUD_PROVIDER == "aws":
        key_id = os.environ.get("ENCRYPTION_KMS_KEY_ID", "")
        if key_id:
            from shared.providers.aws.kms import KmsKeyProvider

            _key_provider = KmsKeyProvider(key_id)
    elif CLOUD_PROVIDER == "azure":
        # Azure adapter lands with the Azure stack (Key Vault wrap/unwrap).
        key_id = os.environ.get("ENCRYPTION_KEY_VAULT_KEY_ID", "")
        if key_id:
            from shared.providers.azure.keyvault import (
                KeyVaultKeyProvider,
            )

            _key_provider = KeyVaultKeyProvider(key_id)
    return _key_provider


def get_storage_provider(bucket: str | None = None) -> StorageProvider:
    """Return the object-storage provider for `bucket`.

    `bucket=None` resolves the default assets bucket (`S3_BUCKET_NAME` on AWS).
    An explicit bucket name (e.g. the GDPR `TENANT_DATA_BUCKET`) returns a
    provider bound to it. Instances are cached per bucket.
    """
    key = bucket or _default_bucket()
    cached = _storage_providers.get(key)
    if cached is not None:
        return cached

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.blob import (
            BlobStorageProvider,
        )

        provider: StorageProvider = BlobStorageProvider(key)
    else:
        from shared.providers.aws.s3 import S3StorageProvider

        provider = S3StorageProvider(key)

    _storage_providers[key] = provider
    return provider


def _default_bucket() -> str:
    """The default object-storage container name for the active cloud."""
    if CLOUD_PROVIDER == "azure":
        return os.environ.get("BLOB_CONTAINER_NAME", "logistics-assets")
    return os.environ.get("S3_BUCKET_NAME", "logistics-assets")


def get_secrets_provider() -> SecretsProvider:
    """Return the secrets provider for the active cloud (cached singleton)."""
    global _secrets_provider
    if _secrets_provider is not None:
        return _secrets_provider

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.keyvault_secrets import (
            KeyVaultSecretsProvider,
        )

        _secrets_provider = KeyVaultSecretsProvider()
    else:
        from shared.providers.aws.secrets import SecretsManagerProvider

        _secrets_provider = SecretsManagerProvider()
    return _secrets_provider


def get_event_provider() -> EventProvider:
    """Return the domain-event provider for the active cloud (cached singleton)."""
    global _event_provider
    if _event_provider is not None:
        return _event_provider

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.eventgrid import (
            EventGridProvider,
        )

        _event_provider = EventGridProvider()
    else:
        from shared.providers.aws.eventbridge import EventBridgeProvider

        _event_provider = EventBridgeProvider()
    return _event_provider


def get_queue_provider() -> QueueProvider:
    """Return the message-queue provider for the active cloud (cached singleton)."""
    global _queue_provider
    if _queue_provider is not None:
        return _queue_provider

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.servicebus import (
            ServiceBusQueueProvider,
        )

        _queue_provider = ServiceBusQueueProvider()
    else:
        from shared.providers.aws.sqs import SqsQueueProvider

        _queue_provider = SqsQueueProvider()
    return _queue_provider


def get_email_provider() -> EmailProvider:
    """Return the transactional-email provider for the active cloud (cached singleton)."""
    global _email_provider
    if _email_provider is not None:
        return _email_provider

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.acs_email import (
            AcsEmailProvider,
        )

        _email_provider = AcsEmailProvider()
    else:
        from shared.providers.aws.ses import SesEmailProvider

        _email_provider = SesEmailProvider()
    return _email_provider


def get_identity_provider() -> IdentityProvider:
    """Return the user/role provisioning provider for the active cloud (cached singleton)."""
    global _identity_provider
    if _identity_provider is not None:
        return _identity_provider

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.entra import EntraIdentityProvider

        _identity_provider = EntraIdentityProvider()
    else:
        from shared.providers.aws.cognito import CognitoIdentityProvider

        _identity_provider = CognitoIdentityProvider()
    return _identity_provider


def get_claims_mapper() -> ClaimsMapper:
    """Return the JWT claims mapper for the active cloud (cached singleton)."""
    global _claims_mapper
    if _claims_mapper is not None:
        return _claims_mapper

    if CLOUD_PROVIDER == "azure":
        from shared.providers.azure.entra_claims import EntraClaimsMapper

        _claims_mapper = EntraClaimsMapper()
    else:
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        _claims_mapper = CognitoClaimsMapper()
    return _claims_mapper
