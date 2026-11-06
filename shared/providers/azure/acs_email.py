"""Azure Communication Services email provider — the Azure analogue of `aws/ses.py`.

Implements the `EmailProvider` port via ACS Email. `begin_send` submits the
message (a long-running op); submission validates and raises on hard failures
(bad sender/recipient/auth), which is what the caller's log/retry path needs —
so, like SES, this does not block on final delivery.

Auth: `AZURE_COMMUNICATION_CONNECTION_STRING`.
"""

import os
from typing import Any


class AcsEmailProvider:
    """EmailProvider backed by Azure Communication Services Email."""

    def __init__(self) -> None:
        self._conn = os.environ.get("AZURE_COMMUNICATION_CONNECTION_STRING", "")
        self._client: Any = None

    def _email_client(self) -> Any:
        if self._client is None:
            from azure.communication.email import EmailClient

            self._client = EmailClient.from_connection_string(self._conn)
        return self._client

    def send(self, *, sender: str, to_email: str, subject: str, html_body: str, text_body: str) -> None:
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to_email}]},
            "content": {"subject": subject, "html": html_body, "plainText": text_body},
        }
        self._email_client().begin_send(message)
