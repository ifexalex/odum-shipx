"""AWS SES email provider."""
import os
from typing import Any


class SesEmailProvider:
    """EmailProvider backed by Amazon SES `send_email`."""

    def __init__(self, region: str | None = None) -> None:
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _ses(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("ses", region_name=self._region)
        return self._client

    def send(self, *, sender: str, to_email: str, subject: str, html_body: str, text_body: str) -> None:
        self._ses().send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                },
            },
        )
