"""Pydantic models for the Tracking service."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TrackingStage(str, Enum):
    received_china = "received_china"
    packed = "packed"
    in_transit = "in_transit"
    arrived_nigeria = "arrived_nigeria"
    customs_clearance = "customs_clearance"
    cleared = "cleared"
    ready_for_pickup = "ready_for_pickup"
    picked_up = "picked_up"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class UpdateShipmentStatusRequest(BaseModel):
    stage: TrackingStage
    notes: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class StageEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: TrackingStage
    occurred_at: datetime
    notes: str | None = None


class EstimatedStage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: TrackingStage
    estimated: date


class TrackingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tracking_code: str
    current_stage: TrackingStage
    company_name: str | None = None
    stage_history: list[StageEvent] = Field(default_factory=list)
    estimated_stages: list[EstimatedStage] | None = None
