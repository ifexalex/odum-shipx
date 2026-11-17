"""The pickup code a collector gives the warehouse (audit UX-09).

A release note carries a short numeric code that is sent to the customer. Whoever collects the goods must give it to the
warehouse attendant, which proves they were sent it by the customer (or are the customer). A delegate gets it by the
customer passing it on.

* **Only a keyed hash is stored.** A six digit number has a million possibilities, so an unkeyed hash could be reversed
  by anyone who read the table. The hash is an HMAC-SHA256 under a secret (`PICKUP_CODE_PEPPER`) that is not in the
  database, bound to the release note's id so the same digits on two notes hash differently.
* **It cannot be guessed at the counter.** `MAX_FAILED_ATTEMPTS` wrong tries lock the note until staff reissue a code;
  the count is kept by the caller (`release_note.pickup_code_failed_attempts`).
* **Switched on by configuration.** With no pepper, `is_configured()` is false: release notes are issued without a code,
  and a note without one needs none to collect. That keeps an environment that has not provisioned the secret working,
  rather than failing every release note. The pepper is required in production.

The plaintext code must never be logged, audited, stored or put in an error message.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets

logger = logging.getLogger(__name__)

CODE_LENGTH = 6
MAX_FAILED_ATTEMPTS = 5

_PEPPER_ENV = "PICKUP_CODE_PEPPER"
_MIN_PEPPER_LENGTH = 16


def _pepper() -> bytes | None:
    value = os.environ.get(_PEPPER_ENV, "")
    return value.encode("utf-8") if len(value) >= _MIN_PEPPER_LENGTH else None


def is_configured() -> bool:
    """True once a usable pepper is set. Until then no codes are issued and none are required."""
    return _pepper() is not None


def new_code() -> str:
    """A fresh random code, zero-padded: `048213`."""
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def normalise(entered: str | None) -> str:
    """What the attendant typed with spaces and dashes removed: `048 213` and `048-213` are `048213`."""
    return re.sub(r"[\s-]", "", entered or "")


def hash_code(release_note_id: str, code: str) -> str:
    """The value stored for `code` on this release note.

    Raises:
        RuntimeError: if no pepper is configured (callers check `is_configured()` first).
    """
    pepper = _pepper()
    if pepper is None:
        raise RuntimeError("PICKUP_CODE_PEPPER is not configured")
    return hmac.new(pepper, f"{release_note_id}:{code}".encode(), hashlib.sha256).hexdigest()


def matches(release_note_id: str, entered: str | None, stored_hash: str) -> bool:
    """Does `entered` match the stored hash? Constant time, and False for anything that is not a well-formed code."""
    code = normalise(entered)
    if not re.fullmatch(rf"[0-9]{{{CODE_LENGTH}}}", code):
        return False
    return hmac.compare_digest(hash_code(release_note_id, code), stored_hash)
