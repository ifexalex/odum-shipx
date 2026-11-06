"""Unit tests for the Azure Event Grid + ACS email adapters.

Neither service has a local emulator, so these use stubbed SDK clients — same
rigor as the SES/Service-Bus stubs. They verify the port→SDK mapping (event
subject/type/data, ACS message shape), the error-normalization contract, and
factory selection.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("azure.eventgrid")
pytest.importorskip("azure.communication.email")

from shared.exceptions import ExternalServiceError  # noqa: E402
from shared.providers.base import EmailProvider, EventProvider  # noqa: E402


class TestEventGridProvider:
    def test_satisfies_the_event_protocol(self):
        from shared.providers.azure.eventgrid import EventGridProvider

        assert isinstance(EventGridProvider(), EventProvider)

    def test_publish_maps_source_type_and_data(self, monkeypatch):
        from shared.providers.azure.eventgrid import EventGridProvider

        captured: dict = {}
        provider = EventGridProvider()
        monkeypatch.setattr(provider, "_publisher", lambda: SimpleNamespace(send=lambda event: captured.update(event=event)))

        provider.publish(
            source="logistics.tracking",
            detail_type="ContainerArrived",
            detail={"tenant_id": "t1", "payload": {"x": 1}},
            bus_name="logistics-events",
        )

        event = captured["event"]
        assert event.subject == "logistics.tracking"
        assert event.event_type == "ContainerArrived"
        assert event.data == {"tenant_id": "t1", "payload": {"x": 1}}

    def test_publish_normalizes_sdk_error_to_external_service_error(self, monkeypatch):
        from shared.providers.azure.eventgrid import EventGridProvider

        def _boom(event):
            raise RuntimeError("topic unreachable")

        provider = EventGridProvider()
        monkeypatch.setattr(provider, "_publisher", lambda: SimpleNamespace(send=_boom))

        with pytest.raises(ExternalServiceError) as exc:
            provider.publish(source="s", detail_type="T", detail={}, bus_name="b")
        assert "EventGrid" in str(exc.value)


class TestAcsEmailProvider:
    def test_satisfies_the_email_protocol(self):
        from shared.providers.azure.acs_email import AcsEmailProvider

        assert isinstance(AcsEmailProvider(), EmailProvider)

    def test_send_builds_the_acs_message_shape(self, monkeypatch):
        from shared.providers.azure.acs_email import AcsEmailProvider

        captured: dict = {}
        provider = AcsEmailProvider()
        monkeypatch.setattr(
            provider, "_email_client", lambda: SimpleNamespace(begin_send=lambda message: captured.update(message=message))
        )

        provider.send(
            sender="no-reply@shipx.test",
            to_email="customer@example.com",
            subject="Your shipment",
            html_body="<p>hi</p>",
            text_body="hi",
        )

        msg = captured["message"]
        assert msg["senderAddress"] == "no-reply@shipx.test"
        assert msg["recipients"]["to"] == [{"address": "customer@example.com"}]
        assert msg["content"] == {"subject": "Your shipment", "html": "<p>hi</p>", "plainText": "hi"}


class TestFactoriesSelectAzure:
    def test_event_provider_factory(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.azure.eventgrid import EventGridProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_event_provider", None)
        assert isinstance(providers.get_event_provider(), EventGridProvider)

    def test_email_provider_factory(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.azure.acs_email import AcsEmailProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "azure")
        monkeypatch.setattr(providers, "_email_provider", None)
        assert isinstance(providers.get_email_provider(), AcsEmailProvider)
