"""Pydantic request/response models for the Excel import/export service."""
from pydantic import BaseModel


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
    error_details: list[dict]
