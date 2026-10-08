"""Unit tests for shared.invites — token mint/hash and validity checks.

Covers the token invariants the plan calls out explicitly: plaintext is
never stored, `is_invite_valid` rejects expired/consumed/unknown invites,
and mint/hash are stable primitives independent of the DB layer.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from shared.invites import hash_token, is_invite_valid, mint_token


class TestMintAndHashToken:
    def test_mint_returns_url_safe_random_token(self):
        token = mint_token()
        assert isinstance(token, str)
        assert len(token) > 20

    def test_mint_is_not_deterministic(self):
        assert mint_token() != mint_token()

    def test_hash_is_sha256_hex_digest(self):
        token = "some-token-value"
        assert hash_token(token) == hashlib.sha256(token.encode()).hexdigest()

    def test_hash_never_reveals_plaintext(self):
        token = mint_token()
        digest = hash_token(token)
        assert token not in digest
        assert len(digest) == 64  # sha256 hex digest length


class TestIsInviteValid:
    def _invite(self, **kw):
        base = {
            "consumed_at": None,
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
        base.update(kw)
        return base

    def test_none_invite_is_invalid(self):
        assert is_invite_valid(None) is False

    def test_fresh_unconsumed_invite_is_valid(self):
        assert is_invite_valid(self._invite()) is True

    def test_consumed_invite_is_invalid(self):
        invite = self._invite(consumed_at=datetime.now(UTC))
        assert is_invite_valid(invite) is False

    def test_expired_invite_is_invalid(self):
        invite = self._invite(expires_at=datetime.now(UTC) - timedelta(hours=1))
        assert is_invite_valid(invite) is False

    def test_string_expires_at_is_parsed(self):
        expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        invite = self._invite(expires_at=expires)
        assert is_invite_valid(invite) is True

    def test_naive_expires_at_is_treated_as_utc(self):
        # Postgres can hand back a naive datetime depending on driver config;
        # is_invite_valid must not crash comparing naive vs aware.
        invite = self._invite(expires_at=datetime.now() + timedelta(hours=1))
        assert is_invite_valid(invite) is True
