"""Offboarding export — runs hourly (audit BE-10).

The PRD (FR-TN-004) promises a leaving tenant a full export of its data. Offboarding queues one
(``shared.tenant_export``); this job writes it:

  1. Claim the oldest export that needs doing (pending, failed with attempts left, or stuck running).
  2. Skip it (``cancelled``) if the tenant is no longer offboarded.
  3. Read every table in ``shared.tenant_data.TENANT_TABLES`` for the tenant, through its own RLS scope, leaving out
     secrets and decrypting the fields stored encrypted.
  4. Write one zip to ``{tenant_id}/exports/offboarding/{export_id}.zip``: ``manifest.json``, ``README.txt``,
     ``tenant.jsonl`` and ``tables/{table}.jsonl`` (one JSON object per row).
  5. Mark it completed and record it in the platform audit log.

The archive stays in the tenant's storage prefix until the 90-day cleanup deletes the tenant, which it refuses to do
until an export has completed. Platform admins download it through a five-minute link (``services/tenant_management``).
The format is JSON Lines, not CSV: lossless types, and nothing a spreadsheet would run as a formula.
"""

import hashlib
import io
import json
import logging
import time
import traceback
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from shared import tenant_export
from shared.db import execute_with_tenant
from shared.encryption import decrypt_field
from shared.logging_config import bind_log_context, clear_log_context, setup_logging
from shared.observability import init_tracing
from shared.platform_audit import insert_platform_audit
from shared.providers import get_storage_provider
from shared.tenant_context import PLATFORM_TENANT_ID
from shared.tenant_data import TENANT_TABLES, TenantTable, redact_config

setup_logging()
init_tracing()

logger = logging.getLogger(__name__)

FORMAT = "shipx-tenant-export"
FORMAT_VERSION = 1

#: Stop claiming new exports after this long, leaving room to finish the current one under the Lambda timeout (900 s)
#: and the Azure job timeout (600 s, ``job_timeout_seconds``). A worker killed mid-export leaves it ``running``; it is
#: claimed again after ``tenant_export.STALE_AFTER_MINUTES``.
_TIME_BUDGET_SECONDS = 300

_README = """ShipX tenant data export
=======================

This archive holds the records ShipX kept for {company_name} (tenant {tenant_id}) when the account was closed.

manifest.json      what is in the archive: each table, its row count and file, and what was left out
tenant.jsonl       the account itself
tables/*.jsonl     one file per table, one JSON object per line, one line per row

Dates and times are ISO 8601 in UTC. Money is a decimal string, exactly as stored.
Left out: passwords, payment-gateway and webhook secrets, and the hashes of invitation, activation and pickup codes.
Uploaded files (photos, documents) are not in this archive; their storage keys are in the rows that refer to them.
"""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """Write every export that is due, until none is left or the time budget is spent."""
    clear_log_context()
    bind_log_context(request_id=getattr(context, "aws_request_id", None))
    deadline = time.monotonic() + _TIME_BUDGET_SECONDS
    counts = {"completed": 0, "failed": 0, "cancelled": 0}
    while time.monotonic() < deadline:
        export = tenant_export.claim_next()
        if export is None:
            break
        counts[run_export(export)] += 1
    logger.info("Offboarding export job done: %s", counts)
    return counts


def run_export(export: dict[str, Any]) -> str:
    """Write one claimed export. Returns ``completed``, ``failed`` or ``cancelled``; never raises."""
    tenant_id, export_id = str(export["tenant_id"]), str(export["id"])
    bind_log_context(tenant_id=tenant_id)
    try:
        tenant = _get_tenant(tenant_id)
        if tenant is None or tenant["status"] != "offboarded":
            tenant_export.mark_cancelled(export_id)
            logger.info("Offboarding export %s cancelled: the tenant is no longer offboarded", export_id)
            return "cancelled"

        generated_at = datetime.now(UTC)
        archive, row_counts = build_archive(tenant, export_id, generated_at)
        key = tenant_export.object_key(tenant_id, export_id)
        get_storage_provider().put_object(key, archive, content_type="application/zip")
        sha256 = hashlib.sha256(archive).hexdigest()
        done = tenant_export.mark_completed(
            export_id, key=key, size_bytes=len(archive), sha256=sha256, row_counts=row_counts, completed_at=generated_at
        )
        if done is None:
            raise RuntimeError("export was no longer running when it finished")
    except Exception as exc:
        # Type and place only, no message and no traceback text: this job reads every customer's personal data, and a
        # database or decryption error message can quote a row.
        logger.error("Offboarding export %s failed for tenant %s: %s at %s", export_id, tenant_id, *_where(exc))
        try:
            tenant_export.mark_failed(export_id, type(exc).__name__)
        except Exception:
            logger.exception("Could not record the failure of offboarding export %s", export_id)
        return "failed"

    try:
        insert_platform_audit(
            action="TENANT_DATA_EXPORTED",
            actor_id=None,
            target_tenant_id=tenant_id,
            details={"export_id": export_id, "size_bytes": len(archive), "sha256": sha256, "rows": sum(row_counts.values())},
        )
    except Exception:
        logger.warning("Platform audit insert failed for offboarding export %s", export_id, exc_info=True)
    logger.info("Offboarding export %s written: %d bytes, %d rows", export_id, len(archive), sum(row_counts.values()))
    return "completed"


def build_archive(tenant: dict[str, Any], export_id: str, generated_at: datetime) -> tuple[bytes, dict[str, int]]:
    """The zip for one tenant, and the number of rows written per table.

    Args:
        tenant: The tenant row.
        export_id: The export being written (named in the manifest).
        generated_at: When the export was made.

    Returns:
        ``(zip bytes, {table: row count})``.

    Raises:
        Exception: Any read or decryption failure. Nothing partial is returned: a field that cannot be decrypted
            fails the export rather than handing over ciphertext.
    """
    tenant_id = str(tenant["id"])
    row_counts: dict[str, int] = {}
    tables: dict[str, dict[str, Any]] = {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tenant.jsonl", _jsonl([tenant]))
        for entry in TENANT_TABLES:
            rows = [_export_row(entry, row) for row in execute_with_tenant(tenant_id, entry.select_sql(), (tenant_id,))]
            path = f"tables/{entry.name}.jsonl"
            archive.writestr(path, _jsonl(rows))
            row_counts[entry.name] = len(rows)
            tables[entry.name] = {
                "file": path,
                "rows": len(rows),
                "omitted_columns": sorted(entry.omit),
                "decrypted_columns": sorted(entry.decrypt),
            }
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "export_id": export_id,
            "generated_at": generated_at.isoformat(),
            "tenant": {
                "id": tenant_id,
                "company_name": tenant.get("company_name"),
                "offboarded_at": _json_value(tenant.get("offboarded_at")),
            },
            "tables": tables,
            "redactions": {"tenant_config": "webhook_config.secret and paystack_config.secret_key_encrypted removed"},
            "not_included": "uploaded files; their storage keys are in the rows that refer to them",
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr("README.txt", _README.format(company_name=tenant.get("company_name") or "", tenant_id=tenant_id))
    return buffer.getvalue(), row_counts


def _export_row(entry: TenantTable, row: dict[str, Any]) -> dict[str, Any]:
    out = {column: value for column, value in row.items() if column not in entry.omit}
    for column in entry.decrypt:
        if out.get(column) is not None:
            out[column] = decrypt_field(out[column])
    if entry.name == "tenant_config":
        out["config_value"] = redact_config(str(out.get("config_key")), out.get("config_value"))
    return out


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, bytes | memoryview):
        return bytes(value).hex()
    raise TypeError(f"cannot export a {type(value).__name__}")


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, default=_json_value, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def _where(exc: BaseException) -> tuple[str, str]:
    """The exception's type and the file:line it was raised at, without its message."""
    frames = traceback.extract_tb(exc.__traceback__)
    place = f"{frames[-1].filename.rsplit('/', 1)[-1]}:{frames[-1].lineno}" if frames else "unknown"
    return type(exc).__name__, place


def _get_tenant(tenant_id: str) -> dict[str, Any] | None:
    rows = execute_with_tenant(PLATFORM_TENANT_ID, "SELECT * FROM tenant WHERE id = %s", (tenant_id,))
    return rows[0] if rows else None
