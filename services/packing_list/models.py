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


class DeliveryDateMode(StrEnum):
    same_day = "same_day"
    multiple_days = "multiple_days"


# ---------------------------------------------------------------------------
# Nested input models
# ---------------------------------------------------------------------------


class PackingListItemInput(BaseModel):
    description: str = Field(min_length=1)
    weight_dispatch_kg: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    weight_actual_kg: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    length_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    width_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    height_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    received_date: date | None = None
    loading_date: date | None = None
    cbm: Decimal | None = None  # auto-computed below
    declared_value_usd: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    # Package type: carton | bag | pallet | bale | sack (matches VARCHAR(20) column).
    package_unit: str | None = Field(default=None, max_length=20)

    # ── Bulk entry ──────────────────────────────────────────────────────────
    # How many identical packages this line stands for. The server expands it
    # into that many rows (see _build_item_rows), each with its own carton_tag
    # and its own CBM — it is NOT stored as `quantity = N` on one row.
    #
    # That distinction is load-bearing. `packing_list_item.quantity` exists and
    # means "N packages" for the Excel manifest import, but **CBM is never
    # multiplied by quantity anywhere**: billing, manifest totals, tracking and
    # payment_release all do a plain SUM(pli.cbm). The import gets away with it
    # because its CBM is read off the forwarder's "Meas." column as a line
    # total. Here CBM is computed from the dimensions keyed in, so it is per
    # package — one row carrying quantity=100 would bill as a single carton.
    # Bounded by container CBM capacity on the service rather than an arbitrary count cap.
    quantity: int = Field(default=1, ge=1)

    # The safeguard, enforced here rather than only in the UI: a client calling
    # the API directly must assert it too. Quantity is a shortcut for packages
    # that are genuinely identical, and the failure mode is an oversight — 100
    # cartons recorded at one carton's weight and dimensions — not a typo that
    # looks wrong on screen.
    identical_confirmed: bool = False

    # Set when editing a packing list that already contains an expanded batch,
    # so the grouping survives the round trip. Generated server-side for a new
    # batch; never trusted as a way to merge unrelated rows, since it only ever
    # groups rows within one packing list.
    batch_ref: str | None = None

    @model_validator(mode="after")
    def compute_cbm(self) -> "PackingListItemInput":
        if self.length_cm is not None and self.width_cm is not None and self.height_cm is not None:
            self.cbm = (self.length_cm * self.width_cm * self.height_cm) / Decimal("1000000")
        return self

    @model_validator(mode="after")
    def require_identical_confirmation(self) -> "PackingListItemInput":
        """Refuse a bulk quantity that nobody has affirmed is actually bulk.

        Deliberately a hard error rather than a silent clamp to 1: quietly
        dropping 99 cartons would be far worse than refusing the request.
        """
        if self.quantity > 1 and not self.identical_confirmed:
            raise ValueError(
                f"quantity {self.quantity} requires identical_confirmed=true — confirm that all "
                f"{self.quantity} packages share these exact dimensions and weight"
            )
        return self


class UpdatePackingListItemInput(BaseModel):
    id: str | None = None  # None = new item; present = update existing
    description: str = Field(min_length=1)
    weight_dispatch_kg: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    weight_actual_kg: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    length_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    width_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    height_cm: Decimal | None = Field(default=None, gt=Decimal("0"), allow_inf_nan=False)
    received_date: date | None = None
    loading_date: date | None = None
    cbm: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    declared_value_usd: Decimal | None = Field(default=None, ge=Decimal("0"), allow_inf_nan=False)
    package_unit: str | None = Field(default=None, max_length=20)
    # Bounded by container CBM capacity on the service rather than an arbitrary count cap.
    quantity: int = Field(default=1, ge=1)
    identical_confirmed: bool = False
    batch_ref: str | None = None

    @model_validator(mode="after")
    def require_identical_confirmation(self) -> "UpdatePackingListItemInput":
        if self.quantity > 1 and not self.identical_confirmed:
            raise ValueError(
                f"quantity {self.quantity} requires identical_confirmed=true — confirm that all "
                f"{self.quantity} packages share these exact dimensions and weight"
            )
        return self


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
    delivery_date_mode: DeliveryDateMode = DeliveryDateMode.same_day
    supplier_name: str | None = Field(default=None, max_length=200)
    supplier_phone: str | None = Field(default=None, max_length=40)
    remarks: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _validate_shipment_dates(self) -> "_ShipmentDatesMixin":
        latest_today = _latest_acceptable_today()
        if self.delivery_date is not None and self.delivery_date > latest_today:
            raise ValueError("delivery_date cannot be in the future - it is the date the goods were received at the warehouse")
        if self.loading_date is not None and self.delivery_date is not None and self.loading_date < self.delivery_date:
            raise ValueError("loading_date cannot be before delivery_date - goods must be received before they can be loaded")

        items = getattr(self, "items", None) or []
        for idx, item in enumerate(items, start=1):
            item_received: date | None = getattr(item, "received_date", None)
            item_loading: date | None = getattr(item, "loading_date", None)
            if item_received is not None and item_received > latest_today:
                raise ValueError(
                    f"Item #{idx} delivery date cannot be in the future - it is the date the goods were received at the warehouse"
                )
            effective_received = (
                self.delivery_date
                if self.delivery_date_mode == DeliveryDateMode.same_day and self.delivery_date is not None
                else (item_received or self.delivery_date)
            )
            effective_loading = item_loading or self.loading_date
            if effective_received is not None and effective_loading is not None and effective_loading < effective_received:
                raise ValueError(
                    f"Item #{idx} loading date cannot be before its delivery date - "
                    "goods must be received before they can be loaded"
                )
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
    loading_date: date | None = None


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
