"""Drain the local SQS notification queues through the real Lambda consumers.

In AWS an event-source mapping delivers SQS messages to the notification
Lambdas. Nothing plays that role against Moto, so locally enqueued
notifications sit in the queue and no provider is ever called — making it look
as though sending silently failed. This script is that missing link.

Messages are dispatched to the same `sms_handler` / `whatsapp_handler` /
`email_handler` used in production, so provider behaviour, the allowlist guard,
and template rendering are all exercised for real.

Usage:
    python3 scripts/drain_notifications.py            # drain once and exit
    python3 scripts/drain_notifications.py --watch    # poll until interrupted
    python3 scripts/drain_notifications.py --peek     # show messages, consume none
"""
import argparse
import json
import logging
import os
import sys
import time
from typing import Any

import boto3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.notification import handler as notification_handler  # noqa: E402

# LOG_LEVEL=DEBUG in .env.local makes botocore emit every signing step, which
# buries the one line that matters — whether the provider accepted the message.
for _noisy in ("botocore", "boto3", "urllib3", "s3transfer"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

CHANNELS: dict[str, tuple[str, Any]] = {
    "sms": ("SQS_SMS_QUEUE_URL", notification_handler.sms_handler),
    "whatsapp": ("SQS_WHATSAPP_QUEUE_URL", notification_handler.whatsapp_handler),
    "email": ("SQS_EMAIL_QUEUE_URL", notification_handler.email_handler),
}


def _sqs() -> Any:
    return boto3.client(
        "sqs",
        endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:5100"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )


def _summarise(body: dict[str, Any]) -> str:
    """One-line description of a queued notification, with the phone masked."""
    to = str(body.get("phone") or body.get("email") or "?")
    masked = f"{to[:6]}***{to[-3:]}" if len(to) > 9 else "***"
    return f"{body.get('event_type', '?')} → {masked}"


def drain(channel: str, peek: bool) -> int:
    """Process one batch from `channel`'s queue. Returns the message count."""
    env_name, lambda_fn = CHANNELS[channel]
    queue_url = os.environ.get(env_name, "")
    if not queue_url:
        return 0

    sqs = _sqs()
    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1)
    messages = resp.get("Messages", [])
    if not messages:
        return 0

    for message in messages:
        try:
            body = json.loads(message["Body"])
        except json.JSONDecodeError:
            print(f"  [{channel}] unparseable message body — left on queue")
            continue

        if peek:
            print(f"  [{channel}] {_summarise(body)}  (peek — not consumed)")
            continue

        print(f"  [{channel}] {_summarise(body)}")
        try:
            lambda_fn({"Records": [{"body": message["Body"], "messageId": message["MessageId"]}]}, None)
        except Exception as exc:  # noqa: BLE001 — a bad message must not stop the drain
            print(f"      ✗ handler raised {type(exc).__name__}: {exc}")
            continue
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])

    return len(messages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="poll until interrupted")
    parser.add_argument("--peek", action="store_true", help="show messages without consuming")
    parser.add_argument("--channel", choices=sorted(CHANNELS), help="drain one channel only")
    args = parser.parse_args()

    channels = [args.channel] if args.channel else list(CHANNELS)
    if not args.watch:
        total = sum(drain(c, args.peek) for c in channels)
        print(f"{total} message(s)." if total else "Queues empty.")
        return 0

    print("Watching notification queues — Ctrl-C to stop.")
    try:
        while True:
            if not sum(drain(c, args.peek) for c in channels):
                time.sleep(2)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
