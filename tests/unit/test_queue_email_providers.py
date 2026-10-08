"""Unit tests for the queue + email ports and their AWS adapters.

SQS is exercised against moto (real send/receive round-trip); SES is covered with
a stubbed client so the message structure is asserted without SES identity setup.
Factory tests confirm the `CLOUD_PROVIDER` wiring and singleton caching.
"""
from shared.providers.base import EmailProvider, QueueProvider


class TestSqsQueueProvider:
    def test_send_puts_the_body_on_the_queue(self):
        from moto import mock_aws

        with mock_aws():
            import boto3

            sqs = boto3.client("sqs", region_name="eu-west-1")
            url = sqs.create_queue(QueueName="notifications")["QueueUrl"]

            from shared.providers.aws.sqs import SqsQueueProvider

            provider = SqsQueueProvider(region="eu-west-1")
            assert isinstance(provider, QueueProvider)
            provider.send(destination=url, body='{"channel": "sms"}')

            msgs = sqs.receive_message(QueueUrl=url).get("Messages", [])
            assert len(msgs) == 1
            assert msgs[0]["Body"] == '{"channel": "sms"}'


class TestSesEmailProvider:
    def test_send_maps_to_ses_send_email_structure(self, monkeypatch):
        from shared.providers.aws import ses

        captured = {}

        class _FakeSes:
            def send_email(self, **kwargs):
                captured.update(kwargs)
                return {"MessageId": "m-1"}

        provider = ses.SesEmailProvider(region="eu-west-1")
        monkeypatch.setattr(provider, "_ses", lambda: _FakeSes())
        assert isinstance(provider, EmailProvider)

        provider.send(
            sender="from@x.com",
            to_email="to@y.com",
            subject="Hi",
            html_body="<p>hi</p>",
            text_body="hi",
        )

        assert captured["Source"] == "from@x.com"
        assert captured["Destination"] == {"ToAddresses": ["to@y.com"]}
        assert captured["Message"]["Subject"]["Data"] == "Hi"
        assert captured["Message"]["Body"]["Html"]["Data"] == "<p>hi</p>"
        assert captured["Message"]["Body"]["Text"]["Data"] == "hi"


class TestProviderFactories:
    def test_default_cloud_returns_aws_adapters(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.aws.ses import SesEmailProvider
        from shared.providers.aws.sqs import SqsQueueProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_queue_provider", None)
        monkeypatch.setattr(providers, "_email_provider", None)

        assert isinstance(providers.get_queue_provider(), SqsQueueProvider)
        assert isinstance(providers.get_email_provider(), SesEmailProvider)

    def test_providers_are_cached_singletons(self, monkeypatch):
        import shared.providers as providers

        monkeypatch.setattr(providers, "_queue_provider", None)
        monkeypatch.setattr(providers, "_email_provider", None)

        assert providers.get_queue_provider() is providers.get_queue_provider()
        assert providers.get_email_provider() is providers.get_email_provider()
