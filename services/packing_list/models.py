"""Pydantic models for the Packing List service."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PackingListStatus(StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# Nested input models
# ---------------------------------------------------------------------------


class PackingListItemInput(BaseModel):
    description: str = Field(min_length=1)
    weight_dispatch_kg: Decimal | None = Field(default=None, ge=Decimal("0"))
    weight_actual_kg: Decimal | None = Field(default=None, ge=Decimal("0"))
    length_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    width_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    height_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    received_date: date | None = None
    cbm: Decimal | None = None  # auto-computed below
    declared_value_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    # Package type: carton | bag | pallet | bale | sack (free-text-tolerant for
    # manifest imports; the wizard constrains the choices). Drives bale sizing
    # and CBM-rate bucketing.
    package_unit: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def compute_cbm(self) -> "PackingListItemInput":
        if self.length_cm is not None and self.width_cm is not None and self.height_cm is not None:
            self.cbm = (self.length_cm * self.width_cm * self.height_cm) / Decimal("1000000")
        return self


class UpdatePackingListItemInput(BaseModel):
    id: str | None = None  # None = new item; present = update existing
    description: str | None = Field(default=None, min_length=1)
    weight_dispatch_kg: Decimal | None = Field(default=None, ge=Decimal("0"))
    weight_actual_kg: Decimal | None = Field(default=None, ge=Decimal("0"))
    length_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    width_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    height_cm: Decimal | None = Field(default=None, gt=Decimal("0"))
    received_date: date | None = None
    declared_value_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    package_unit: str | None = Field(default=None, max_length=30)


class ItemRejection(BaseModel):
    item_id: str
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class _ShipmentDatesMixin(BaseModel):
    """Shared validation for a packing list's two shipment dates.

    The domain order is fixed: a supplier **delivers** goods to the China
    warehouse, and only then can they be **loaded** into a container. So:

      - `delivery_date` (goods received at the China warehouse) cannot be in the
        future — it records something that has already happened.
      - `loading_date` must be on or after `delivery_date`. Same day is fine;
        goods received in the morning are often loaded that afternoon.

    `loading_date` has no upper bound on purpose: packing lists are written
    against containers still in `loading` status, so a planned load date is
    legitimate. Both fields stay optional (they always were) — the rules only
    apply to the values actually supplied.
    """

    loading_date: date | None = None
    delivery_date: date | None = None

    @model_validator(mode="after")
    def _validate_shipment_dates(self) -> "_ShipmentDatesMixin":
        if self.delivery_date is not None and self.delivery_date > _latest_acceptable_today():
            raise ValueError("delivery_date cannot be in the future - it is the date the goods were " "received at the warehouse")
        if self.loading_date is not None and self.delivery_date is not None and self.loading_date < self.delivery_date:
            raise ValueError("loading_date cannot be before delivery_date - goods must be received " "before they can be loaded")
        return self


def _latest_acceptable_today() -> date:
    """The latest date that still counts as "not in the future".

    One day past the server's UTC date, NOT the UTC date itself. The China
    office is UTC+8, so for several hours each evening their local calendar date
    is already tomorrow in UTC; comparing against UTC "today" would reject the
    date they can see on the wall as a future date. A one-day allowance covers
    every real timezone (max UTC+14) and still rejects the mistakes this rule
    exists for — a date next week or next year.
    """
    return datetime.now(UTC).date() + timedelta(days=1)


class CreatePackingListRequest(_ShipmentDatesMixin):
    container_id: str
    customer_id: str
    # Destination warehouse the cargo is bound for. Omitted → the tenant's
    # default warehouse is applied server-side.
    arrival_warehouse_id: str | None = None
    items: list[PackingListItemInput] = Field(default_factory=list)


class UpdatePackingListRequest(_ShipmentDatesMixin):
    arrival_warehouse_id: str | None = None
    items: list[UpdatePackingListItemInput] = Field(min_length=1)


class ApprovePackingListRequest(BaseModel):
    comments: str | None = None


class RejectPackingListRequest(BaseModel):
    comments: str = Field(min_length=1)
    item_rejections: list[ItemRejection] | None = None


class BulkApproveRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    comments: str | None = None


class BulkSubmitRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class BulkRejectRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    comments: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PackingListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    description: str
    weight_dispatch_kg: Decimal | None = None
    weight_actual_kg: Decimal | None = None
    carton_tag: str | None = None
    tracking_code: str | None = None
    cbm: Decimal | None = None
    length_cm: Decimal | None = None
    width_cm: Decimal | None = None
    height_cm: Decimal | None = None
    received_date: date | None = None


class PackingListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    container_id: str
    customer_id: str
    customer_name: str | None = None
    status: PackingListStatus
    items: list[PackingListItemResponse] = Field(default_factory=list)
    total_cbm: Decimal | None = None
    total_weight_kg: Decimal | None = None
    carton_count: int = 0
    created_at: datetime
