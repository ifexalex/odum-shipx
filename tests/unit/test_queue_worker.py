"""Unit tests for services/queue_worker/worker.py — the Service Bus consumer
that replaces AWS's SQS → Lambda event sources. No Azure SDK, no network: the
message→event wrapping and config are tested directly."""

import json
from unittest.mock import MagicMock

import pytest

from services.queue_worker import worker


class TestProcessMessage:
    def test_wraps_body_in_sqs_shaped_event(self):
        handler = MagicMock()
        body = json.dumps({"tenant_id": "t1", "event_type": "test"})

        worker.process_message(handler, body, "msg-1")

        handler.assert_called_once()
        event = handler.call_args.args[0]
        assert event["Records"][0]["body"] == body
        assert event["Records"][0]["messageId"] == "msg-1"
        assert event["Records"][0]["eventSource"] == "aws:sqs"

    def test_handler_exception_propagates(self):
        handler = MagicMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            worker.process_message(handler, "{}", "msg-1")


class TestConfig:
    def test_all_queue_keys_map_to_a_handler_and_env(self):
        assert set(worker._QUEUE_CONFIG) == {"sms", "whatsapp", "email", "metering"}
        for handler_ref, env_var in worker._QUEUE_CONFIG.values():
            assert ":" in handler_ref  # module:function
            assert env_var.startswith("SQS_") and env_var.endswith("_QUEUE_URL")


class TestRunWorkerGuards:
    def test_unknown_queue_key_raises(self):
        with pytest.raises(ValueError, match="Unknown queue key"):
            worker.run_worker("not-a-queue")

    def test_missing_queue_name_env_raises(self, monkeypatch):
        monkeypatch.delenv("SQS_SMS_QUEUE_URL", raising=False)
        monkeypatch.setenv("AZURE_SERVICE_BUS_CONNECTION_STRING", "conn")
        with pytest.raises(RuntimeError, match="SQS_SMS_QUEUE_URL"):
            worker.run_worker("sms")

    def test_missing_connection_string_raises(self, monkeypatch):
        monkeypatch.setenv("SQS_SMS_QUEUE_URL", "sms-queue")
        monkeypatch.delenv("AZURE_SERVICE_BUS_CONNECTION_STRING", raising=False)
        with pytest.raises(RuntimeError, match="AZURE_SERVICE_BUS_CONNECTION_STRING"):
            worker.run_worker("sms")


class TestMainArgparse:
    def test_rejects_unknown_queue(self):
        with pytest.raises(SystemExit):
            worker.main(["--queue", "bogus"])
