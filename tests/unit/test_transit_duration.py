"""Unit tests for ENG-1: tenant default transit duration setting & omitting ETA on container create."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from services.tenant_management import tenant_config
from services.tenant_management.models import UpdateTenantConfigRequest
from services.tracking import service as tracking_service

TENANT_ID = "00000000-0000-0000-0000-000000000001"
ACTOR_ID = "00000000-0000-0000-0000-000000000002"


class TestDefaultTransitDaysSetting:
    def test_get_tenant_config_defaults_to_45_when_unconfigured(self) -> None:
        with patch("services.tenant_management.tenant_config.repo.get_all_configs", return_value=[]):
            cfg = tenant_config.get_tenant_config(TENANT_ID)
        assert cfg["default_transit_days"] == 45

    def test_get_default_transit_days_returns_override_when_configured(self) -> None:
        rows = [{"config_key": "default_transit_days", "config_value": 30}]
        with patch("services.tenant_management.tenant_config.repo.get_all_configs", return_value=rows):
            assert tenant_config.get_default_transit_days(TENANT_ID) == 30

    def test_get_default_transit_days_falls_back_to_45_on_invalid_stored_value(self) -> None:
        rows = [{"config_key": "default_transit_days", "config_value": "not-a-number"}]
        with patch("services.tenant_management.tenant_config.repo.get_all_configs", return_value=rows):
            assert tenant_config.get_default_transit_days(TENANT_ID) == 45

    @pytest.mark.parametrize("bad_value", [0, -5, 366])
    def test_model_rejects_out_of_range_transit_days(self, bad_value: int) -> None:
        with pytest.raises(ValidationError):
            UpdateTenantConfigRequest(default_transit_days=bad_value)

    def test_update_tenant_config_persists_and_audits_default_transit_days(self) -> None:
        req = UpdateTenantConfigRequest(default_transit_days=35)
        with (
            patch("services.tenant_management.tenant_config.repo.upsert_config") as upsert,
            patch("services.tenant_management.tenant_config.log_audit") as audit,
            patch(
                "services.tenant_management.tenant_config.repo.get_all_configs",
                return_value=[{"config_key": "default_transit_days", "config_value": {"days": 35}}],
            ),
        ):
            updated = tenant_config.update_tenant_config(TENANT_ID, req, actor_id=ACTOR_ID)

        upsert.assert_called_once_with(TENANT_ID, "default_transit_days", {"days": 35}, updated_by=ACTOR_ID)
        audit.assert_called_once()
        assert updated["default_transit_days"] == 35


class TestCreateContainerOmitsEta:
    def test_create_container_ignores_estimated_arrival_date(self) -> None:
        captured: dict[str, object] = {}

        def fake_create(tenant_id: str, data: dict[str, object]) -> dict[str, object]:
            captured.update(data)
            return {"id": "c-1", **data}

        with (
            patch("services.tracking.service.check_container_limit"),
            patch("services.tracking.service.repo.create_container", side_effect=fake_create),
            patch("services.tracking.service.log_audit"),
        ):
            row = tracking_service.create_container(
                TENANT_ID,
                {
                    "container_number": "MSCU1234567",
                    "origin": "China",
                    "destination": "Nigeria",
                    "estimated_arrival_date": "2026-12-31",
                },
                actor_id=ACTOR_ID,
            )

        assert captured["estimated_arrival_date"] is None
        assert row["estimated_arrival_date"] is None
