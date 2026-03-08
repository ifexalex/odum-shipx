"""Base Pydantic models shared across all services.

Provides the foundational building blocks that every service model inherits from.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TenantScopedBase(BaseModel):
    """Base for all domain models that belong to a tenant."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: str


class TimestampMixin(BaseModel):
    """Mixin for models with audit timestamps."""

    created_at: datetime
    updated_at: datetime | None = None


class PaginationMeta(BaseModel):
    """Pagination metadata included in list responses."""

    cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None
