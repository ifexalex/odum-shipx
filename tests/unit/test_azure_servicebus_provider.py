"""Unit tests for the Azure Service Bus QueueProvider adapter.

Service Bus's official local emulator needs a SQL Edge sidecar and is finicky on
arm64, so (for a send-only adapter) these use a stubbed Service Bus client — the
same rigor as the SES stub in `test_queue_email_providers.py`. A real
`ServiceBusMessage` is constructed, so the body/queue wiring is genuinely checked.
"""
import pytest

pytest.importorskip("azure.servicebus")

from shared.providers.base import QueueProvider  # noqa: E402

_CONN = "Endpoint=sb://local/;SharedAccessKeyName=k;SharedAccessKey=secret;UseDevelopmentEmulator=true"


class _FakeSender:
    def __init__(self, captured):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_messages(self, message):
        self._captured["message"] = message


class _FakeServiceBusClient:
    def __init__(self, captured):
        self._captured = captured

    def get_queue_sender(self, queue_name):
        self._captured["queue"] = queue_name
        return _FakeSender(self._captured)


class TestServiceBusQueueProvider:
    def test_satisfies_the_queue_protocol(self, monkeypatch):
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", _CONN)
        from shared.providers.azure.servicebus import ServiceBusQueueProvider

        assert isinstance(ServiceBusQueueProvider(), QueueProvider)

    def test_send_targets_the_queue_and_sends_the_body(self, monkeypatch):
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", _CONN)
        from shared.providers.azure.servicebus import ServiceBusQueueProvider

        captured: dict = {}
        provider = ServiceBusQueueProvider()
        monkeypatch.setattr(provider, "_service_bus", lambda: _FakeServiceBusClient(captured))

        provider.send(destination="sms-notifications", body='{"channel": "sms"}')

        assert captured["queue"] == "sms-notifications"
        # A real ServiceBusMessage was constructed; its str() is the body.
        assert str(captured["message"]) == '{"channel": "sms"}'


class TestQueueFactorySelectsAzure:
    def test_azure_cloud_returns_service_bus_provider(self, monkeypatch):
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", _CONN)

        import shared.providers as providers
        from shared.providers.azure.servicebus import ServiceBusQueueProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_queue_provider", None)

        provider = providers.get_queue_provider()
        assert isinstance(provider, ServiceBusQueueProvider)
        assert provider is providers.get_queue_provider()  # cached singleton
