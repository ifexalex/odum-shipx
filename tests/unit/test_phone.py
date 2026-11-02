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


class TestFrontendDialCodesAgree:
    """The frontend's own country list must not drift from `_DIAL_CODES`.

    `shared/phone.py` normalises a LOCAL-format number by prepending the dial
    code derived from the tenant's destination country, while the browser's
    `PhoneField` submits E.164 assembled from `frontend/src/data/countries.ts`.
    If the two tables disagreed on a country, a number entered for one market
    could be stored under another's prefix — and nothing else would catch it,
    because each side is internally consistent.

    Asserted from the backend because the frontend's tsconfig carries no Node
    types, so a vitest test cannot read this file without loosening that config
    for a single test.
    """

    @staticmethod
    def _frontend_countries() -> dict[str, str]:
        """Parse {lowercased name: dial} out of the frontend dataset."""
        import pathlib
        import re

        path = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/data/countries.ts"
        assert path.is_file(), f"frontend country dataset missing at {path}"
        text = path.read_text(encoding="utf-8")
        # Entries look like: { code: 'NG', name: 'Nigeria', dial: '234' }
        pattern = re.compile(r"\{\s*code:\s*'([A-Z]{2})',\s*name:\s*(?:'([^']*)'|\"([^\"]*)\"),\s*dial:\s*'(\d+)'\s*\}")
        found = {}
        for _code, single, double, dial in pattern.findall(text):
            found[(single or double).strip().lower()] = dial
        assert found, "parsed no countries from countries.ts — did its shape change?"
        return found

    def test_every_backend_dial_code_matches_the_frontend(self) -> None:
        from shared.phone import _DIAL_CODES

        frontend = self._frontend_countries()
        for name, dial in _DIAL_CODES.items():
            assert name in frontend, f"shared/phone.py knows '{name}' but countries.ts does not"
            assert frontend[name] == dial, f"dial code mismatch for '{name}': backend={dial} frontend={frontend[name]}"

    def test_the_frontend_default_is_nigeria(self) -> None:
        import pathlib
        import re

        from shared.phone import DEFAULT_DIAL_CODE

        frontend = self._frontend_countries()
        assert frontend["nigeria"] == DEFAULT_DIAL_CODE

        path = pathlib.Path(__file__).resolve().parents[2] / "frontend/src/data/countries.ts"
        text = path.read_text(encoding="utf-8")
        default_code = re.search(r"DEFAULT_COUNTRY_CODE = '([A-Z]{2})'", text)
        assert default_code is not None, "DEFAULT_COUNTRY_CODE not found in countries.ts"
        assert default_code.group(1) == "NG", "the phone field must default to Nigeria"
