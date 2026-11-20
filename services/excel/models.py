"""Pydantic request/response models for the Excel import/export service."""

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExportFormat(StrEnum):
    xlsx = "xlsx"
    csv = "csv"
    pdf = "pdf"


class ExportResponse(BaseModel):
    filename: str
    download_url: str
    expires_at: str
    file_size_bytes: int


class ImportPresignedUrlRequest(BaseModel):
    content_type: str
    #: The file's size in bytes; at most 5 MB (shared.uploads.MAX_UPLOAD_BYTES), checked by the upload policy.
    size_bytes: int | None = None


class ImportPresignedUrlResponse(BaseModel):
    upload_url: str
    fields: dict[str, str]
    file_key: str


class ImportRequest(BaseModel):
    container_id: str
    file_key: str  # S3 key of uploaded .xlsx


class ImportResult(BaseModel):
    total_rows: int
    imported: int
    errors: int
    packing_lists_created: int
    error_details: list[dict[str, object]]


class ManifestImportRequest(BaseModel):
    file_key: str  # S3 key of uploaded .xlsx


class ManifestImportResult(BaseModel):
    total_rows: int
    imported: int
    errors: int
    containers_created: int
    customers_created: int
    packing_lists_created: int
    items_created: int
    items_skipped_duplicate: int
    error_details: list[dict[str, object]]


_STATUS_TOKEN = re.compile(r"[a-z_]{1,32}")
_MAX_STATUSES = 12


def _iso_date_string(value: Any) -> str | None:
    """A calendar date, `YYYY-MM-DD`, kept as the string the list endpoints would also receive."""
    if value is None or value == "":
        return None
    try:
        date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("must be a date as YYYY-MM-DD") from exc
    return str(value)


class ListExportQuery(BaseModel):
    """The query string of a list export: the list screen's own filters and sort, plus the file format.

    Names and meanings match the list endpoints (`GET /v1/billing`, `GET /v1/containers`) so the screen can forward
    what it is showing unchanged. PDF is not offered: a list can run to thousands of rows.
    """

    model_config = ConfigDict(extra="ignore")

    format: Literal["xlsx", "csv"] = "xlsx"
    status: list[str] | None = None
    q: str | None = Field(default=None, max_length=100)
    created_after: str | None = None
    created_before: str | None = None
    sort: str = Field(default="created_at", pattern=r"^[a-z_]{1,40}$")
    direction: Literal["asc", "desc"] = "desc"

    @field_validator("status", mode="before")
    @classmethod
    def _split_statuses(cls, value: Any) -> Any:
        """`?status=unpaid,paid` (what the lists send) becomes a list; each must look like a status."""
        if value is None or value == "":
            return None
        tokens = [token for token in value.split(",") if token] if isinstance(value, str) else value
        if len(tokens) > _MAX_STATUSES or not all(isinstance(t, str) and _STATUS_TOKEN.fullmatch(t) for t in tokens):
            raise ValueError("status must be a comma-separated list of status names")
        return tokens

    @field_validator("created_after", "created_before", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> Any:
        return _iso_date_string(value)

    @field_validator("direction", mode="before")
    @classmethod
    def _lower(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value

    def filters(self) -> dict[str, Any]:
        """The filter dict the list queries take: only what was actually set."""
        raw = {
            "status": self.status,
            "q": self.q,
            "created_after": self.created_after,
            "created_before": self.created_before,
        }
        return {key: value for key, value in raw.items() if value}


class ReportExportQuery(BaseModel):
    """The query string of the reports page's export: its period and the file format."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["xlsx", "csv"] = "xlsx"
    created_after: str | None = None
    created_before: str | None = None

    @field_validator("created_after", "created_before", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> Any:
        return _iso_date_string(value)

    def filters(self) -> dict[str, Any]:
        """The period, with only the bounds that were set."""
        raw = {"created_after": self.created_after, "created_before": self.created_before}
        return {key: value for key, value in raw.items() if value}


class ContainerListExportQuery(ListExportQuery):
    """The container list adds an ETA window."""

    eta_after: str | None = None
    eta_before: str | None = None

    @field_validator("eta_after", "eta_before", mode="before")
    @classmethod
    def _eta_dates(cls, value: Any) -> Any:
        return _iso_date_string(value)

    def filters(self) -> dict[str, Any]:
        filters = super().filters()
        for key in ("eta_after", "eta_before"):
            if getattr(self, key):
                filters[key] = getattr(self, key)
        return filters
