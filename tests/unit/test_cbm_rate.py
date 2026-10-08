"""Unit tests for shared.cbm_rate — tenant-configured currency + per-package-
type (carton/bag/bale) CBM freight rate, replacing the old single flat USD
number model.

"flat" is deliberately not a separate code path in compute_cbm_charge —
it's just the case where all three rates happen to be equal — so these
tests exercise one code path throughout, not two.
"""
from decimal import Decimal
from unittest.mock import patch

from shared.cbm_rate import compute_cbm_charge, get_cbm_rate_config, normalize_package_unit

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestNormalizePackageUnit:
    def test_exact_bag_and_bale_get_their_own_bucket(self):
        assert normalize_package_unit("bag") == "bag"
        assert normalize_package_unit("bale") == "bale"

    def test_is_case_insensitive(self):
        assert normalize_package_unit("BAG") == "bag"
        assert normalize_package_unit("Bale") == "bale"

    def test_everything_else_falls_back_to_carton(self):
        for unit in ["carton", "pallet", "item", "mixed", "unspecified", "package", "", None, "banana"]:
            assert normalize_package_unit(unit) == "carton"


class TestGetCbmRateConfig:
    def test_new_shape_passes_through(self):
        rows = [
            {
                "config_value": {
                    "currency": "ngn",
                    "rate_mode": "per_package_type",
                    "carton_rate": 45000,
                    "bag_rate": 45000,
                    "bale_rate": 60000,
                    "effective_from": "t1",
                }
            }
        ]
        with patch("shared.cbm_rate.execute_with_tenant", return_value=rows):
            config = get_cbm_rate_config(TENANT_ID)
        assert config == {
            "currency": "ngn",
            "rate_mode": "per_package_type",
            "carton_rate": Decimal("45000"),
            "bag_rate": Decimal("45000"),
            "bale_rate": Decimal("60000"),
            "effective_from": "t1",
        }

    def test_new_shape_defaults_missing_bag_and_bale_to_carton(self):
        rows = [{"config_value": {"currency": "usd", "rate_mode": "flat", "carton_rate": 45}}]
        with patch("shared.cbm_rate.execute_with_tenant", return_value=rows):
            config = get_cbm_rate_config(TENANT_ID)
        assert config["bag_rate"] == Decimal("45")
        assert config["bale_rate"] == Decimal("45")

    def test_pre_existing_flat_rate_shape_is_normalized(self):
        """The shape every tenant provisioned before 2026-09-20 has."""
        rows = [{"config_value": {"rate_usd": 45.00, "effective_from": "t0"}}]
        with patch("shared.cbm_rate.execute_with_tenant", return_value=rows):
            config = get_cbm_rate_config(TENANT_ID)
        assert config == {
            "currency": "usd",
            "rate_mode": "flat",
            "carton_rate": Decimal("45.00"),
            "bag_rate": Decimal("45.00"),
            "bale_rate": Decimal("45.00"),
            "effective_from": "t0",
        }

    def test_missing_config_defaults_to_all_zero_rates(self):
        with patch("shared.cbm_rate.execute_with_tenant", return_value=[]):
            config = get_cbm_rate_config(TENANT_ID)
        assert config["carton_rate"] == Decimal("0")
        assert config["bag_rate"] == Decimal("0")
        assert config["bale_rate"] == Decimal("0")
        assert config["currency"] == "usd"
        assert config["rate_mode"] == "flat"


class TestComputeCbmCharge:
    def _flat_config(self, rate: str = "45", currency: str = "usd") -> dict:
        return {"currency": currency, "carton_rate": Decimal(rate), "bag_rate": Decimal(rate), "bale_rate": Decimal(rate)}

    def test_flat_rate_single_bucket(self):
        charge = compute_cbm_charge({"carton": Decimal("10")}, self._flat_config("45"))
        assert charge["amount"] == Decimal("450.00")
        assert charge["currency"] == "usd"
        assert charge["breakdown"]["carton"] == {"cbm": Decimal("10"), "rate": Decimal("45"), "subtotal": Decimal("450.00")}
        assert charge["breakdown"]["bag"]["subtotal"] == Decimal("0.00")
        assert charge["breakdown"]["bale"]["subtotal"] == Decimal("0.00")

    def test_genuine_per_package_type_mix(self):
        config = {"currency": "usd", "carton_rate": Decimal("45"), "bag_rate": Decimal("45"), "bale_rate": Decimal("60")}
        charge = compute_cbm_charge({"carton": Decimal("10"), "bag": Decimal("5"), "bale": Decimal("2")}, config)
        # 10*45 + 5*45 + 2*60 = 450 + 225 + 120 = 795
        assert charge["amount"] == Decimal("795.00")
        assert charge["breakdown"]["carton"]["subtotal"] == Decimal("450.00")
        assert charge["breakdown"]["bag"]["subtotal"] == Decimal("225.00")
        assert charge["breakdown"]["bale"]["subtotal"] == Decimal("120.00")

    def test_unrecognized_package_unit_folds_into_carton_bucket(self):
        config = {"currency": "usd", "carton_rate": Decimal("45"), "bag_rate": Decimal("45"), "bale_rate": Decimal("60")}
        charge = compute_cbm_charge({"pallet": Decimal("3"), "mixed": Decimal("2"), None: Decimal("1")}, config)
        assert charge["breakdown"]["carton"]["cbm"] == Decimal("6")
        assert charge["breakdown"]["carton"]["subtotal"] == Decimal("270.00")
        assert charge["breakdown"]["bag"]["cbm"] == Decimal("0")
        assert charge["breakdown"]["bale"]["cbm"] == Decimal("0")

    def test_ngn_currency_passes_through_unchanged(self):
        charge = compute_cbm_charge({"carton": Decimal("10")}, self._flat_config("45000", currency="ngn"))
        assert charge["currency"] == "ngn"
        assert charge["amount"] == Decimal("450000.00")

    def test_zero_cbm_yields_zero_charge(self):
        charge = compute_cbm_charge({}, self._flat_config("45"))
        assert charge["amount"] == Decimal("0.00")

    def test_each_bucket_rounds_independently_before_summing(self):
        # 3.335 * 45 = 150.075 -> rounds to 150.08 (ROUND_HALF_UP) per bucket,
        # not summed-then-rounded — confirms the breakdown always sums
        # exactly to the displayed total.
        config = {"currency": "usd", "carton_rate": Decimal("45"), "bag_rate": Decimal("45"), "bale_rate": Decimal("45")}
        charge = compute_cbm_charge({"carton": Decimal("3.335")}, config)
        assert charge["breakdown"]["carton"]["subtotal"] == Decimal("150.08")
        assert charge["amount"] == Decimal("150.08")
