"""Pydantic request/response models for the Excel import/export service."""
from enum import StrEnum

from pydantic import BaseModel


class ExportFormat(StrEnum):
    xlsx = "xlsx"
    csv = "csv"
    pdf = "pdf"


class ExportResponse(BaseModel):
    filename: str
    download_url: str
    expires_at: str
    file_size_bytes: int


class ImportRequest(BaseModel):
    container_id: str
    file_key: str  # S3 key of uploaded .xlsx


class ImportResult(BaseModel):
    total_rows: int
    imported: int
    errors: int
    packing_lists_created: int
    error_details: list[dict[str, object]]
