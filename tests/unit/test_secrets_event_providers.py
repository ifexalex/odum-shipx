"""Unit tests for the secrets + event-publishing ports and their AWS adapters.

Secrets Manager and EventBridge adapters are exercised against moto so the
round-trips are real SDK behaviour; the EventBridge failure path (which moto does
not naturally produce) is covered with a stubbed client. Factory tests confirm
the `CLOUD_PROVIDER` wiring and singleton caching.
"""
import json

import pytest
from moto import mock_aws

from shared.exceptions import ExternalServiceError
from shared.providers.base import EventProvider, SecretsProvider


class TestSecretsManagerProvider:
    @mock_aws
    def test_returns_the_raw_secret_string(self):
        import boto3

        sm = boto3.client("secretsmanager", region_name="eu-west-1")
        arn = sm.create_secret(Name="db-creds", SecretString=json.dumps({"password": "s3cr3t"}))["ARN"]

        from shared.providers.aws.secrets import SecretsManagerProvider

        provider = SecretsManagerProvider(region="eu-west-1")
        assert isinstance(provider, SecretsProvider)
        assert json.loads(provider.get_secret(arn))["password"] == "s3cr3t"


class TestEventBridgeProvider:
    @mock_aws
    def test_publish_succeeds_against_a_real_bus(self):
        import boto3

        boto3.client("events", region_name="eu-west-1").create_event_bus(Name="logistics-events")

        from shared.providers.aws.eventbridge import EventBridgeProvider

        provider = EventBridgeProvider(region="eu-west-1")
        assert isinstance(provider, EventProvider)
        # Should not raise.
        provider.publish(
            source="logistics.test",
            detail_type="ThingHappened",
            detail={"tenant_id": "t1", "payload": {"x": 1}},
            bus_name="logistics-events",
        )

    def test_publish_raises_external_service_error_on_failed_entry(self, monkeypatch):
        from shared.providers.aws import eventbridge

        class _FakeClient:
            def put_events(self, Entries):  # noqa: N803 — boto3 kwarg name
                return {
                    "FailedEntryCount": 1,
                    "Entries": [{"ErrorCode": "ThrottlingException", "ErrorMessage": "slow down"}],
                }

        provider = eventbridge.EventBridgeProvider(region="eu-west-1")
        monkeypatch.setattr(provider, "_events", lambda: _FakeClient())

        with pytest.raises(ExternalServiceError) as exc:
            provider.publish(source="logistics.test", detail_type="X", detail={}, bus_name="logistics-events")
        assert "ThrottlingException" in str(exc.value)


class TestProviderFactories:
    def test_default_cloud_returns_aws_adapters(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.aws.eventbridge import EventBridgeProvider
        from shared.providers.aws.secrets import SecretsManagerProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_secrets_provider", None)
        monkeypatch.setattr(providers, "_event_provider", None)

        assert isinstance(providers.get_secrets_provider(), SecretsManagerProvider)
        assert isinstance(providers.get_event_provider(), EventBridgeProvider)

    def test_providers_are_cached_singletons(self, monkeypatch):
        import shared.providers as providers

        monkeypatch.setattr(providers, "_secrets_provider", None)
        monkeypatch.setattr(providers, "_event_provider", None)

        assert providers.get_secrets_provider() is providers.get_secrets_provider()
        assert providers.get_event_provider() is providers.get_event_provider()
