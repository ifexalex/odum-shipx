"""AWS SQS queue provider."""
import os
from typing import Any


class SqsQueueProvider:
    """QueueProvider backed by AWS SQS `send_message`.

    `destination` is the SQS queue URL (callers read it from the per-channel
    `SQS_*_QUEUE_URL` env vars).
    """

    def __init__(self, region: str | None = None) -> None:
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _sqs(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=self._region)
        return self._client

    def send(self, *, destination: str, body: str) -> None:
        self._sqs().send_message(QueueUrl=destination, MessageBody=body)
