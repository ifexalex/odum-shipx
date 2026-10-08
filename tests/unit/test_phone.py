"""Unit tests for shared.phone — the normaliser every customer write path uses.

Regression coverage for the bug this consolidation fixes: `08012345678`
(local format) and `+2348012345678` (international) previously matched as
two different customers because tenant_management stored phones verbatim
and the old excel-only normaliser never canonicalised local vs.
international format.
"""

from shared.phone import dial_code_for_country, mask_phone, normalize_phone


class TestNormalizePhone:
    def test_local_and_international_forms_converge(self):
        assert normalize_phone("08012345678", dial_code="234") == normalize_phone("+2348012345678", dial_code="234")
        assert normalize_phone("08012345678", dial_code="234") == "+2348012345678"

    def test_international_with_spaces_and_punctuation(self):
        assert normalize_phone("+234 801 234 5678", dial_code="234") == "+2348012345678"

    def test_digits_only_international_gets_leading_plus(self):
        assert normalize_phone("2348012345678", dial_code="234") == "+2348012345678"

    def test_blank_input_returns_none(self):
        assert normalize_phone(None) is None
        assert normalize_phone("") is None
        assert normalize_phone("   ") is None

    def test_unparseable_input_returns_none(self):
        assert normalize_phone("not a phone") is None

    def test_default_dial_code_is_nigeria(self):
        assert normalize_phone("08012345678") == "+2348012345678"


class TestDialCodeForCountry:
    def test_known_country(self):
        assert dial_code_for_country("Nigeria") == "234"
        assert dial_code_for_country("nigeria") == "234"
        assert dial_code_for_country("  Ghana  ") == "233"

    def test_unknown_or_missing_falls_back_to_default(self):
        assert dial_code_for_country(None) == "234"
        assert dial_code_for_country("") == "234"
        assert dial_code_for_country("Atlantis") == "234"


class TestMaskPhone:
    def test_masks_middle_digits(self):
        assert mask_phone("+2348012345678") == "+23480****678"

    def test_none_stays_none(self):
        assert mask_phone(None) is None

    def test_short_number_fully_masked(self):
        assert mask_phone("1234") == "****"
