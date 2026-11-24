"""The pickup code module (audit UX-09): format, the keyed hash, and matching."""

from unittest.mock import patch

import pytest

from shared import pickup_code

PEPPER = "unit-test-pepper-0123456789"
NOTE = "11111111-1111-1111-1111-111111111111"
OTHER_NOTE = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setenv("PICKUP_CODE_PEPPER", PEPPER)


class TestConfiguration:
    def test_configured_when_a_pepper_is_set(self):
        assert pickup_code.is_configured()

    @pytest.mark.parametrize("value", ["", "short"])
    def test_not_configured_without_a_usable_pepper(self, monkeypatch, value):
        monkeypatch.setenv("PICKUP_CODE_PEPPER", value)
        assert not pickup_code.is_configured()

    def test_not_configured_when_the_variable_is_absent(self, monkeypatch):
        monkeypatch.delenv("PICKUP_CODE_PEPPER")
        assert not pickup_code.is_configured()

    def test_hashing_without_a_pepper_is_an_error_not_a_weak_hash(self, monkeypatch):
        monkeypatch.delenv("PICKUP_CODE_PEPPER")
        with pytest.raises(RuntimeError):
            pickup_code.hash_code(NOTE, "123456")


class TestNewCode:
    def test_it_is_six_digits_zero_padded(self):
        codes = {pickup_code.new_code() for _ in range(2000)}
        assert all(len(c) == 6 and c.isdigit() for c in codes)
        assert any(c.startswith("0") for c in codes), "leading zeros must be kept, or a tenth of codes would be five digits"

    def test_codes_vary(self):
        assert len({pickup_code.new_code() for _ in range(200)}) > 150

    def test_it_uses_a_cryptographic_source(self):
        with patch("shared.pickup_code.secrets.randbelow", return_value=48213) as rand:
            assert pickup_code.new_code() == "048213"
        rand.assert_called_once_with(10**6)


class TestHash:
    def test_the_hash_does_not_contain_the_code(self):
        assert "123456" not in pickup_code.hash_code(NOTE, "123456")

    def test_it_is_a_sha256_hex_digest(self):
        assert len(pickup_code.hash_code(NOTE, "123456")) == 64

    def test_the_same_digits_hash_differently_on_different_notes(self):
        assert pickup_code.hash_code(NOTE, "123456") != pickup_code.hash_code(OTHER_NOTE, "123456")

    def test_the_hash_depends_on_the_secret(self, monkeypatch):
        first = pickup_code.hash_code(NOTE, "123456")
        monkeypatch.setenv("PICKUP_CODE_PEPPER", "a-completely-different-pepper")
        assert pickup_code.hash_code(NOTE, "123456") != first

    def test_it_is_stable(self):
        assert pickup_code.hash_code(NOTE, "123456") == pickup_code.hash_code(NOTE, "123456")


class TestMatches:
    def test_the_right_code_matches(self):
        stored = pickup_code.hash_code(NOTE, "048213")
        assert pickup_code.matches(NOTE, "048213", stored)

    @pytest.mark.parametrize("typed", ["048 213", "048-213", " 048213 ", "048 - 213"])
    def test_spaces_and_dashes_are_ignored(self, typed):
        assert pickup_code.matches(NOTE, typed, pickup_code.hash_code(NOTE, "048213"))

    @pytest.mark.parametrize("typed", ["048214", "048213 7", "04821", "", None, "abcdef", "０４８２１３", "048213\n; DROP"])
    def test_anything_else_does_not(self, typed):
        assert not pickup_code.matches(NOTE, typed, pickup_code.hash_code(NOTE, "048213"))

    def test_a_code_for_another_note_does_not_match(self):
        assert not pickup_code.matches(OTHER_NOTE, "048213", pickup_code.hash_code(NOTE, "048213"))

    def test_the_comparison_is_constant_time(self):
        with patch("shared.pickup_code.hmac.compare_digest", return_value=True) as compare:
            assert pickup_code.matches(NOTE, "048213", "whatever")
        compare.assert_called_once()

    def test_a_malformed_entry_is_refused_before_any_hashing(self):
        with patch("shared.pickup_code.hash_code") as hash_it:
            assert not pickup_code.matches(NOTE, "12", "x")
        assert not hash_it.called


class TestNormalise:
    def test_it_strips_separators_only(self):
        assert pickup_code.normalise("04 82-13") == "048213"
        assert pickup_code.normalise(None) == ""
