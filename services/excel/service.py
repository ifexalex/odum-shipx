"""Orchestration: fetch data → generate file → upload S3 → presigned URL."""

import csv
import hashlib
import io
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

from services.billing import repository as billing_repo
from services.metering.service import check_container_limit
from services.tracking import repository as tracking_repo
from shared import uploads
from shared.audit import log_audit
from shared.cbm_rate import apply_min_cbm, get_min_cbm_per_item
from shared.db import tenant_transaction
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError, ValidationError
from shared.phone import dial_code_for_country, normalize_phone
from shared.providers import get_storage_provider

from . import pdf_theme
from . import repository as repo
from ._tables import Column, build_csv, build_xlsx, csv_safe
from .export_billing import generate_billing_xlsx
from .export_invoice_pdf import generate_invoice_pdf
from .export_lists import (
    BILLING_LIST_COLUMNS,
    CONTAINER_EVENT_COLUMNS,
    CONTAINER_LIST_COLUMNS,
    REPORT_CONTAINER_BILLING_COLUMNS,
)
from .export_loading_receipt_pdf import generate_loading_receipt_pdf_with_meta
from .export_manifest import generate_manifest_xlsx
from .export_manifest_pdf import generate_manifest_pdf
from .export_packing_list import generate_packing_list_xlsx
from .export_packing_list_pdf import generate_packing_list_pdf_with_meta
from .export_receipt_pdf import generate_receipt_pdf
from .export_release_note_pdf import generate_release_note_pdf
from .import_manifest import parse_manifest_xlsx
from .import_packing_list import parse_packing_list_xlsx
from .pdf_image import image_disabled_reason, render_single_page_png

logger = logging.getLogger(__name__)

_PRESIGNED_EXPIRY = 3600  # 1 hour


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _safe_name(value: str) -> str:
    """Sanitise a string for use in S3 filenames."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value or "unknown"))


_CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "png": "image/png",
}


def _disposition(filename: str, fmt: str) -> str:
    """How the browser should treat the download (FD-44): a PDF opens in the tab, a spreadsheet saves under our name.

    Set on the presigned link because the browser ignores an <a download> name on a cross-origin URL. The name is
    already reduced to safe characters by ``_safe_name``.
    """
    return f'{"inline" if fmt == "pdf" else "attachment"}; filename="{filename}"'


def _upload_and_presign(
    tenant_id: str,
    filename: str,
    buf: BytesIO,
    fmt: str = "xlsx",
    *,
    expires_in: int = _PRESIGNED_EXPIRY,
) -> dict[str, Any]:
    today = date.today().strftime("%Y-%m-%d")
    key = f"{tenant_id}/exports/{today}/{uuid.uuid4().hex}/{filename}"
    file_bytes = buf.getvalue()
    storage = get_storage_provider()
    storage.put_object(key, file_bytes, content_type=_CONTENT_TYPES.get(fmt, _CONTENT_TYPES["xlsx"]))
    download_url = storage.presigned_get_url(key, expires_in=expires_in, response_content_disposition=_disposition(filename, fmt))
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "filename": filename,
        "download_url": download_url,
        "expires_at": expires_at,
        "file_size_bytes": len(file_bytes),
        "format": fmt,
    }


# ---------------------------------------------------------------------------
# CSV generators (thin wrappers — DictWriter from in-memory row dicts)
# ---------------------------------------------------------------------------


def _rows_to_csv(rows: list[dict[str, Any]], columns: list[str]) -> BytesIO:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    # Typed-in text (names, descriptions) must not run as a formula when the file is opened in a spreadsheet.
    writer.writerows({column: csv_safe(row.get(column)) for column in columns} for row in rows)
    return BytesIO(buf.getvalue().encode("utf-8-sig"))  # utf-8-sig for Excel compatibility


# ---------------------------------------------------------------------------
# Packing list export
# ---------------------------------------------------------------------------


_PL_COLUMNS = [
    "carton_tag",
    "tracking_code",
    "description",
    "weight_dispatch_kg",
    "weight_actual_kg",
    "cbm",
    "length_cm",
    "width_cm",
    "height_cm",
    "received_date",
]


def export_packing_list(
    tenant_id: str,
    pl_id: str,
    fmt: str = "xlsx",
    *,
    actor_id: str | None = None,
    actor_role: str = "",
) -> dict[str, Any]:
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    display_name = repo.get_tenant_display_name(tenant_id)
    container_number = str(pl.get("container_number") or "")
    customer_name = str(pl.get("customer_name") or "")

    today_str = date.today().strftime("%Y%m%d")
    stem = f"{_safe_name(display_name)}_packing_list_{_safe_name(container_number)}_{today_str}"

    if fmt == "csv":
        buf = _rows_to_csv(items, _PL_COLUMNS)
    else:
        buf = generate_packing_list_xlsx(display_name, container_number, customer_name, items)

    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    if actor_id or actor_role:
        log_audit(
            tenant_id=tenant_id,
            entity_type="packing_list",
            entity_id=pl_id,
            action="EXPORT",
            actor_id=actor_id,
            actor_role=actor_role or "staff",
            after_state={"format": fmt, "filename": result.get("filename")},
        )
    return result


# ---------------------------------------------------------------------------
# Manifest export
# ---------------------------------------------------------------------------


_MANIFEST_COLUMNS = ["customer_name", "carton_count", "total_weight_kg", "total_cbm", "carton_tags"]


def export_manifest(
    tenant_id: str,
    manifest_id: str,
    fmt: str = "xlsx",
    *,
    actor_id: str | None = None,
    actor_role: str = "",
) -> dict[str, Any]:
    manifest = repo.get_manifest_for_export(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    container_id = str(manifest.get("container_id") or "")
    container_number = str(manifest.get("container_number") or "")
    display_name = repo.get_tenant_display_name(tenant_id)
    all_items = repo.get_items_for_manifest(tenant_id, container_id)

    # Build per-customer summary rows keyed by customer_id (falling back to customer_name)
    customer_data: dict[str, dict[str, Any]] = {}
    for item in all_items:
        cname = str(item.get("customer_name") or "")
        ckey = str(item.get("customer_id") or cname)
        if ckey not in customer_data:
            customer_data[ckey] = {
                "customer_name": cname,
                "carton_count": 0,
                "total_weight_kg": 0.0,
                "total_cbm": 0.0,
                "carton_tags": [],
            }
        d = customer_data[ckey]
        d["carton_count"] += int(item.get("quantity") or 1)
        d["total_weight_kg"] += float(item.get("weight_actual_kg") or 0)
        d["total_cbm"] += float(item.get("cbm") or 0)
        if item.get("carton_tag"):
            d["carton_tags"].append(str(item["carton_tag"]))

    customer_rows = []
    for d in customer_data.values():
        d["carton_tags"] = ", ".join(d["carton_tags"])
        d["total_cbm"] = round(d["total_cbm"], 6)
        customer_rows.append(d)

    today_str = date.today().strftime("%Y%m%d")
    stem = f"{_safe_name(display_name)}_manifest_{_safe_name(container_number)}_{today_str}"

    if fmt == "csv":
        buf = _rows_to_csv(customer_rows, _MANIFEST_COLUMNS)
    else:
        buf = generate_manifest_xlsx(display_name, container_number, customer_rows, all_items)

    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    if actor_id or actor_role:
        log_audit(
            tenant_id=tenant_id,
            entity_type="manifest",
            entity_id=manifest_id,
            action="EXPORT",
            actor_id=actor_id,
            actor_role=actor_role or "staff",
            after_state={"format": fmt, "filename": result.get("filename")},
        )
    return result


# ---------------------------------------------------------------------------
# Billing export (single billing record)
# ---------------------------------------------------------------------------


# Ground-truth gap found live: this used to be
# ["customer_name", "container_number", "total_ngn", "balance_ngn", "status",
# "billed_at", "created_at"] — a customer's downloaded PDF/CSV "invoice"
# showed just the total and balance with zero breakdown of what made up
# either figure. Widened to full parity with generate_billing_xlsx()'s
# _HEADERS (the admin xlsx export already had the complete breakdown; only
# the csv/pdf path — the one the customer's "Download invoice" button
# actually uses — was stripped down). `credits_applied_ngn` (migration 066)
# is the credit the customer held that this invoice absorbed: without it the
# parts above the total do not add up to the total.
_BILLING_COLUMNS = [
    "customer_name",
    "container_number",
    "total_cbm",
    "cbm_rate_usd",
    "exchange_rate_ngn",
    "subtotal_ngn",
    "misc_fees_itemized",
    "storage_fees_ngn",
    "carryover_ngn",
    "credits_applied_ngn",
    "total_ngn",
    "amount_paid_ngn",
    "balance_ngn",
    "status",
    "billed_at",
    "created_at",
]


def _misc_fees_itemized(tenant_id: str, billing_id: str) -> str:
    """Human-readable "description: ₦amount; description: ₦amount" string —
    a flat per-row export can't hold a variable-length fee table, but it can
    still name exactly what each charge is for instead of a bare total.
    """
    charges = repo.get_misc_charges_for_export(tenant_id, billing_id)
    if not charges:
        return ""
    return "; ".join(f"{c['description']}: NGN {float(c['amount_ngn']):,.2f}" for c in charges)


def export_billing(
    tenant_id: str,
    billing_id: str,
    fmt: str = "xlsx",
    customer_user_id: str | None = None,
    *,
    actor_id: str | None = None,
    actor_role: str = "",
) -> dict[str, Any]:
    """Generate a billing export — also the customer's downloadable invoice.

    When customer_user_id is supplied (CUSTOMER role), verifies the billing
    record belongs to that customer; raises ResourceNotFoundError (not 403)
    on mismatch, same pattern as export_packing_list_pdf.
    """
    billing = repo.get_billing_for_export(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

    if customer_user_id:
        customer_id = repo.get_customer_id_for_user(tenant_id, customer_user_id)
        if not customer_id or str(billing.get("customer_id")) != customer_id:
            raise ResourceNotFoundError("billing", billing_id)

    billing = {**billing, "misc_fees_itemized": _misc_fees_itemized(tenant_id, billing_id)}

    display_name = repo.get_tenant_display_name(tenant_id)
    container_number = str(billing.get("container_number") or "")
    today_str = date.today().strftime("%Y%m%d")
    stem = f"{_safe_name(display_name)}_billing_{_safe_name(container_number)}_{today_str}"

    if fmt == "csv":
        buf = _rows_to_csv([billing], _BILLING_COLUMNS)
    else:
        buf = generate_billing_xlsx([billing])

    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    if actor_id or actor_role:
        log_audit(
            tenant_id=tenant_id,
            entity_type="billing",
            entity_id=billing_id,
            action="EXPORT",
            actor_id=actor_id,
            actor_role=actor_role or "staff",
            after_state={"format": fmt, "filename": result.get("filename")},
        )
    return result


# ---------------------------------------------------------------------------
# Billing export (all billing for a container)
# ---------------------------------------------------------------------------


def export_container_billing(
    tenant_id: str,
    container_id: str,
    fmt: str = "xlsx",
    *,
    actor_id: str | None = None,
    actor_role: str = "",
) -> dict[str, Any]:
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    billing_rows = [
        {**row, "misc_fees_itemized": _misc_fees_itemized(tenant_id, str(row["id"]))}
        for row in repo.get_billing_for_container_export(tenant_id, container_id)
    ]
    display_name = repo.get_tenant_display_name(tenant_id)
    container_number = str(container.get("container_number") or "")
    today_str = date.today().strftime("%Y%m%d")
    stem = f"{_safe_name(display_name)}_billing_{_safe_name(container_number)}_{today_str}"

    if fmt == "csv":
        buf = _rows_to_csv(billing_rows, _BILLING_COLUMNS)
    else:
        buf = generate_billing_xlsx(billing_rows)

    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    if actor_id or actor_role:
        log_audit(
            tenant_id=tenant_id,
            entity_type="container",
            entity_id=container_id,
            action="EXPORT",
            actor_id=actor_id,
            actor_role=actor_role or "staff",
            after_state={"scope": "container_billing", "format": fmt, "filename": result.get("filename")},
        )
    return result


# ---------------------------------------------------------------------------
# Tracking events export (one container)
# ---------------------------------------------------------------------------


def _label(code: object) -> str:
    """A status or role code as words: ``in_transit`` → ``In transit``."""
    text = str(code or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def export_container_events(
    tenant_id: str, container_id: str, *, fmt: str, actor_id: str | None, actor_role: str
) -> dict[str, Any]:
    """A container's tracking events, oldest first, as xlsx or csv.

    The rows are the event log on the container's tracking tab. Notes are typed by staff, so the writers neutralise
    formulas (``_tables``).

    Raises:
        ResourceNotFoundError: No such container in the tenant.
    """
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)

    rows = [
        {
            **event,
            "from_status_label": _label(event.get("from_status")),
            "to_status_label": _label(event.get("to_status")),
            "actor_role_label": _label(event.get("actor_role")),
        }
        for event in tracking_repo.get_container_events(tenant_id, container_id)
    ]
    container_number = str(container.get("container_number") or "")
    buf = (
        build_csv(CONTAINER_EVENT_COLUMNS, rows)
        if fmt == "csv"
        else build_xlsx(f"Tracking {container_number}"[:31], CONTAINER_EVENT_COLUMNS, rows)
    )
    stem = f"{_safe_name(repo.get_tenant_display_name(tenant_id))}_tracking_{_safe_name(container_number)}_{date.today():%Y%m%d}"
    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    result["row_count"] = len(rows)

    log_audit(
        tenant_id=tenant_id,
        entity_type="container",
        entity_id=container_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"scope": "tracking_events", "format": fmt, "row_count": len(rows), "filename": result["filename"]},
    )
    return result


# ---------------------------------------------------------------------------
# List exports (the invoice list and the container list)
# ---------------------------------------------------------------------------

# More than this and the export is refused rather than silently cut short: a partial file that looks complete is
# worse than none. Comfortably inside the Lambda's memory and time at the columns exported.
EXPORT_ROW_LIMIT = 10_000


def _list_export(
    tenant_id: str,
    *,
    entity_type: str,
    noun: str,
    sheet_title: str,
    columns: list[Column],
    rows: list[dict[str, Any]],
    truncated: bool,
    fmt: str,
    filters: dict[str, Any],
    actor_id: str | None,
    actor_role: str,
    stem_noun: str | None = None,
    narrow_by: str = "the filters (status, dates or search)",
) -> dict[str, Any]:
    """Build, store and presign a list export, and record who exported it.

    `noun` names the rows in the refusal message; `stem_noun`, when given, names the file instead of `noun`;
    `narrow_by` is what the refusal tells the user to narrow.
    """
    if truncated:
        raise BusinessRuleViolationError(
            f"More than {EXPORT_ROW_LIMIT:,} {noun} match. Narrow {narrow_by} and export again.",
            rule_id="EXPORT_TOO_LARGE",
        )

    buf = build_csv(columns, rows) if fmt == "csv" else build_xlsx(sheet_title, columns, rows)
    stem = f"{_safe_name(repo.get_tenant_display_name(tenant_id))}_{stem_noun or noun}_{date.today().strftime('%Y%m%d')}"
    result = _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)
    result["row_count"] = len(rows)

    log_audit(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=str(uuid.uuid4()),  # a list export has no single entity; this identifies the export itself
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={
            "scope": "list",
            "format": fmt,
            "row_count": len(rows),
            "filename": result["filename"],
            # The search text can be a customer's name or phone number: record that one was used, not what it said.
            "filters": {key: value for key, value in filters.items() if key != "q"},
            "text_search": "q" in filters,
        },
    )
    return result


def export_billing_list(
    tenant_id: str,
    filters: dict[str, Any],
    *,
    fmt: str,
    sort_field: str,
    sort_direction: str,
    actor_id: str | None,
    actor_role: str,
) -> dict[str, Any]:
    """Every invoice that matches the invoice list's filters, as xlsx or csv, in the list's sort order."""
    rows, truncated = repo.list_billing_for_export(tenant_id, filters, EXPORT_ROW_LIMIT, sort_field, sort_direction)
    return _list_export(
        tenant_id,
        entity_type="billing",
        noun="invoices",
        sheet_title="Invoices",
        columns=BILLING_LIST_COLUMNS,
        rows=rows,
        truncated=truncated,
        fmt=fmt,
        filters=filters,
        actor_id=actor_id,
        actor_role=actor_role,
    )


def export_container_list(
    tenant_id: str,
    filters: dict[str, Any],
    *,
    fmt: str,
    sort_field: str,
    sort_direction: str,
    actor_id: str | None,
    actor_role: str,
) -> dict[str, Any]:
    """Every container that matches the container list's filters, as xlsx or csv, in the list's sort order."""
    rows, truncated = repo.list_containers_for_export(tenant_id, filters, EXPORT_ROW_LIMIT, sort_field, sort_direction)
    return _list_export(
        tenant_id,
        entity_type="container",
        noun="containers",
        sheet_title="Containers",
        columns=CONTAINER_LIST_COLUMNS,
        rows=rows,
        truncated=truncated,
        fmt=fmt,
        filters=filters,
        actor_id=actor_id,
        actor_role=actor_role,
    )


def export_report_container_billing(
    tenant_id: str,
    filters: dict[str, Any],
    *,
    fmt: str,
    actor_id: str | None,
    actor_role: str,
) -> dict[str, Any]:
    """The reports page's billing-by-container table for the period, every container (the page shows the top 200).

    Args:
        tenant_id: Owning tenant.
        filters: `created_after` / `created_before`, the report's period; either may be absent.
        fmt: `xlsx` or `csv`.
        actor_id: Who exported, for the audit log.
        actor_role: Their role, for the audit log.

    Returns:
        The presigned download, as every export returns it, with `row_count`.

    Raises:
        BusinessRuleViolationError: More than `EXPORT_ROW_LIMIT` containers were billed in the period.
    """
    rows = billing_repo.get_container_billing(
        tenant_id,
        filters.get("created_after"),
        filters.get("created_before"),
        limit=EXPORT_ROW_LIMIT + 1,
    )
    return _list_export(
        tenant_id,
        entity_type="billing",
        noun="containers",
        sheet_title="Billing by container",
        columns=REPORT_CONTAINER_BILLING_COLUMNS,
        rows=rows[:EXPORT_ROW_LIMIT],
        truncated=len(rows) > EXPORT_ROW_LIMIT,
        fmt=fmt,
        filters=filters,
        actor_id=actor_id,
        actor_role=actor_role,
        stem_noun="billing_by_container",
        narrow_by="the period",
    )


# ---------------------------------------------------------------------------
# Dedicated PDFs (FD-39, FD-40, FD-41): one document per record, on pdf_theme
# ---------------------------------------------------------------------------

#: A document link lasts five minutes: long enough to open, short enough that a forwarded link soon stops working.
_PDF_LINK_SECONDS = 300

#: Bump whenever PDF/PNG layout templates change so fingerprinted Blob caches invalidate automatically.
_DOC_CACHE_VERSION = "v2"
_LOGO_CACHE_TTL_SECONDS = 300.0
_LOGO_CACHE_MAX_ENTRIES = 128
_PAGE_COUNT_CACHE_TTL_SECONDS = 600.0
_PAGE_COUNT_CACHE_MAX_ENTRIES = 512

# Process-local caches: safe across requests because keys include tenant_id + immutable key/fingerprint.
_LOGO_CACHE: dict[tuple[str, str], tuple[float, bytes]] = {}
_PAGE_COUNT_CACHE: dict[str, tuple[float, int]] = {}


def _clear_document_caches() -> None:
    """Clear in-memory logo and page-count caches (intended for tests)."""
    _LOGO_CACHE.clear()
    _PAGE_COUNT_CACHE.clear()


def _get_cached_logo(tenant_id: str, logo_key: str) -> bytes | None:
    now = time.monotonic()
    entry = _LOGO_CACHE.get((tenant_id, logo_key))
    if entry is not None:
        expires_at, data = entry
        if now < expires_at:
            return data
        _LOGO_CACHE.pop((tenant_id, logo_key), None)
    return None


def _store_cached_logo(tenant_id: str, logo_key: str, data: bytes) -> None:
    if len(_LOGO_CACHE) >= _LOGO_CACHE_MAX_ENTRIES:
        _LOGO_CACHE.clear()
    _LOGO_CACHE[(tenant_id, logo_key)] = (time.monotonic() + _LOGO_CACHE_TTL_SECONDS, data)


def _get_cached_page_count(cache_key: str) -> int | None:
    now = time.monotonic()
    entry = _PAGE_COUNT_CACHE.get(cache_key)
    if entry is not None:
        expires_at, count = entry
        if now < expires_at:
            return count
        _PAGE_COUNT_CACHE.pop(cache_key, None)
    return None


def _store_cached_page_count(cache_key: str, page_count: int) -> None:
    if len(_PAGE_COUNT_CACHE) >= _PAGE_COUNT_CACHE_MAX_ENTRIES:
        _PAGE_COUNT_CACHE.clear()
    _PAGE_COUNT_CACHE[cache_key] = (time.monotonic() + _PAGE_COUNT_CACHE_TTL_SECONDS, page_count)


def _document_fingerprint(
    doc_type: str,
    lang: str,
    branding: dict[str, Any],
    pl: dict[str, Any],
    items: list[dict[str, Any]],
) -> str:
    """Deterministic SHA-256 prefix covering every field rendered on a Packing List or Loading Receipt."""
    payload = {
        "v": _DOC_CACHE_VERSION,
        "doc_type": doc_type,
        "lang": lang,
        "branding": branding,
        "pl": pl,
        "items": items,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _cached_blob_key(tenant_id: str, pl_id: str, doc_type: str, lang: str, fingerprint: str, fmt: str) -> str:
    return f"{tenant_id}/exports/cache/{pl_id}/{doc_type}_{lang}_{fingerprint}.{fmt}"


def _cached_export_or_render(
    *,
    tenant_id: str,
    pl_id: str,
    doc_type: str,
    lang: str,
    fingerprint: str,
    filename: str,
    fmt: str,
    expires_in: int,
    render_fn: Callable[[], tuple[BytesIO, int]],
) -> tuple[dict[str, Any], int]:
    """Return a presigned download dict from the content-fingerprinted Blob cache, rendering only on miss."""
    storage = get_storage_provider()
    blob_key = _cached_blob_key(tenant_id, pl_id, doc_type, lang, fingerprint, fmt)
    page_cache_key = f"{doc_type}:{lang}:{fingerprint}"

    cached_size = storage.object_size(blob_key)
    if isinstance(cached_size, int) and cached_size > 0:
        download_url = storage.presigned_get_url(
            blob_key,
            expires_in=expires_in,
            response_content_disposition=_disposition(filename, fmt),
        )
        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cached_pages = _get_cached_page_count(page_cache_key)
        page_count = cached_pages if cached_pages is not None else 1
        return (
            {
                "filename": filename,
                "download_url": download_url,
                "expires_at": expires_at,
                "file_size_bytes": cached_size,
                "format": fmt,
                "expires_in_seconds": expires_in,
            },
            page_count,
        )

    buf, page_count = render_fn()
    _store_cached_page_count(page_cache_key, page_count)
    file_bytes = buf.getvalue()
    storage.put_object(blob_key, file_bytes, content_type=_CONTENT_TYPES.get(fmt, _CONTENT_TYPES["pdf"]))
    download_url = storage.presigned_get_url(
        blob_key,
        expires_in=expires_in,
        response_content_disposition=_disposition(filename, fmt),
    )
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        {
            "filename": filename,
            "download_url": download_url,
            "expires_at": expires_at,
            "file_size_bytes": len(file_bytes),
            "format": fmt,
            "expires_in_seconds": expires_in,
        },
        page_count,
    )


def _brand(tenant_id: str, branding: dict[str, Any] | None = None) -> pdf_theme.Brand:
    """The tenant's branding for a document, with its logo's bytes when one is set (FD-29).

    The logo is read only from this tenant's own logo prefix and cached in memory for 5 minutes
    keyed on ``(tenant_id, logo_key)`` so repeat exports skip Blob downloads. A logo that cannot
    be read leaves the initials tile: a document must never fail for want of its logo.
    """
    resolved_branding = branding if branding is not None else repo.get_tenant_branding(tenant_id)
    logo: bytes | None = None
    key = resolved_branding.get("logo_key")
    if isinstance(key, str) and key.startswith(f"{tenant_id}/branding/logo/"):
        logo = _get_cached_logo(tenant_id, key)
        if logo is None:
            try:
                fetched = get_storage_provider().get_object(key)
                if isinstance(fetched, (bytes, bytearray)) and fetched:
                    logo = bytes(fetched)
                    _store_cached_logo(tenant_id, key, logo)
                else:
                    logo = fetched
            except Exception:  # noqa: BLE001 — any storage failure falls back to the initials tile
                logger.warning("Could not read the tenant logo for a document", exc_info=True)
    return pdf_theme.Brand.from_branding(resolved_branding, logo=logo)


def _publish_pdf(
    tenant_id: str,
    buf: BytesIO,
    stem: str,
    *,
    entity_type: str,
    entity_id: str,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Store a document, return a five-minute link that opens it in the browser, and audit the export."""
    filename = f"{stem}.pdf"
    result = _upload_and_presign(tenant_id, filename, buf, fmt="pdf", expires_in=_PDF_LINK_SECONDS)
    result["expires_in_seconds"] = _PDF_LINK_SECONDS
    log_audit(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "pdf", "filename": result["filename"]},
    )
    return result


def _assert_customer_owns(tenant_id: str, customer_user_id: str | None, owner_id: object, entity: str, entity_id: str) -> None:
    """A customer reads only their own documents; anything else is "not found", never "forbidden"."""
    if customer_user_id:
        customer_id = repo.get_customer_id_for_user(tenant_id, customer_user_id)
        if not customer_id or str(owner_id) != customer_id:
            raise ResourceNotFoundError(entity, entity_id)


def _stem(brand: pdf_theme.Brand, kind: str, reference: object) -> str:
    return f"{_safe_name(brand.name)}_{kind}_{_safe_name(str(reference or ''))}"


def _publish_image(
    tenant_id: str,
    buf: BytesIO,
    stem: str,
    *,
    entity_type: str,
    entity_id: str,
    actor_id: str,
    actor_role: str,
    expires_in: int = _PDF_LINK_SECONDS,
) -> dict[str, Any]:
    """Store a single-page PNG document, return a presigned attachment link, and audit the export."""
    filename = f"{stem}.png"
    result = _upload_and_presign(tenant_id, filename, buf, fmt="png", expires_in=expires_in)
    result["expires_in_seconds"] = expires_in
    log_audit(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "png", "filename": result["filename"]},
    )
    return result


def _normalize_pl_lang(lang: str | None) -> Any:
    return "zh" if (lang or "").strip().lower() == "zh" else "en"


def _normalize_lr_lang(lang: str | None) -> Any:
    return "en" if (lang or "").strip().lower() == "en" else "zh"


def _assert_packing_list_approved(pl: dict[str, Any]) -> None:
    if pl.get("status") != "approved":
        raise BusinessRuleViolationError(
            "Packing list must be approved before generating or sharing documents.",
            rule_id="PACKING_LIST_NOT_APPROVED",
        )


def _assert_loading_receipt_ready(pl: dict[str, Any]) -> None:
    if pl.get("status") != "approved" or not pl.get("loading_receipt_number"):
        raise BusinessRuleViolationError(
            "Loading receipt is generated once the packing list has been approved.",
            rule_id="LOADING_RECEIPT_NOT_READY",
        )


def export_packing_list_pdf(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
    *,
    lang: str = "en",
) -> dict[str, Any]:
    """The packing list as its one PDF, behind a five-minute link (a customer: their own only)."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)
    _assert_packing_list_approved(pl)
    branding = repo.get_tenant_branding(tenant_id)
    brand = _brand(tenant_id, branding=branding)
    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    norm_lang = _normalize_pl_lang(lang)
    pl_dict = dict(pl)
    fp = _document_fingerprint("packing_list", norm_lang, branding, pl_dict, items)
    filename = f"{_stem(brand, f'packing_list_{norm_lang}', pl.get('reference') or pl.get('container_number'))}.pdf"

    def _render() -> tuple[BytesIO, int]:
        rendered = generate_packing_list_pdf_with_meta(brand, pl_dict, items, lang=norm_lang)
        return rendered.buf, rendered.page_count

    result, page_count = _cached_export_or_render(
        tenant_id=tenant_id,
        pl_id=pl_id,
        doc_type="packing_list",
        lang=norm_lang,
        fingerprint=fp,
        filename=filename,
        fmt="pdf",
        expires_in=_PDF_LINK_SECONDS,
        render_fn=_render,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "pdf", "filename": result["filename"]},
    )
    result["page_count"] = page_count
    result["lang"] = norm_lang
    return result


def export_packing_list_image(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
    *,
    lang: str = "en",
) -> dict[str, Any]:
    """Single-page PNG export of a packing list (422 MULTIPAGE_IMAGE_DISABLED when > 1 page)."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)
    _assert_packing_list_approved(pl)
    branding = repo.get_tenant_branding(tenant_id)
    brand = _brand(tenant_id, branding=branding)
    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    norm_lang = _normalize_pl_lang(lang)
    pl_dict = dict(pl)
    fp = _document_fingerprint("packing_list", norm_lang, branding, pl_dict, items)
    filename = f"{_stem(brand, f'packing_list_{norm_lang}', pl.get('reference') or pl.get('container_number'))}.png"

    def _render() -> tuple[BytesIO, int]:
        rendered = generate_packing_list_pdf_with_meta(brand, pl_dict, items, lang=norm_lang)
        png_buf = render_single_page_png(rendered.buf.getvalue(), rendered.page_count)
        return png_buf, rendered.page_count

    result, page_count = _cached_export_or_render(
        tenant_id=tenant_id,
        pl_id=pl_id,
        doc_type="packing_list",
        lang=norm_lang,
        fingerprint=fp,
        filename=filename,
        fmt="png",
        expires_in=_PDF_LINK_SECONDS,
        render_fn=_render,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "png", "filename": result["filename"]},
    )
    result["page_count"] = page_count
    result["lang"] = norm_lang
    return result


def export_loading_receipt_pdf(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
    *,
    lang: str = "zh",
) -> dict[str, Any]:
    """Bilingual Loading Receipt PDF (defaults to Chinese ``zh``; requires approved packing list)."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)
    _assert_loading_receipt_ready(pl)
    branding = repo.get_tenant_branding(tenant_id)
    brand = _brand(tenant_id, branding=branding)
    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    norm_lang = _normalize_lr_lang(lang)
    pl_dict = dict(pl)
    fp = _document_fingerprint("loading_receipt", norm_lang, branding, pl_dict, items)
    filename = f"{_stem(brand, f'loading_receipt_{norm_lang}', pl.get('loading_receipt_number') or pl.get('reference'))}.pdf"

    def _render() -> tuple[BytesIO, int]:
        rendered = generate_loading_receipt_pdf_with_meta(brand, pl_dict, items, lang=norm_lang)
        return rendered.buf, rendered.page_count

    result, page_count = _cached_export_or_render(
        tenant_id=tenant_id,
        pl_id=pl_id,
        doc_type="loading_receipt",
        lang=norm_lang,
        fingerprint=fp,
        filename=filename,
        fmt="pdf",
        expires_in=_PDF_LINK_SECONDS,
        render_fn=_render,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "pdf", "filename": result["filename"]},
    )
    result["page_count"] = page_count
    result["lang"] = norm_lang
    return result


def export_loading_receipt_image(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
    *,
    lang: str = "zh",
) -> dict[str, Any]:
    """Single-page PNG export of a Loading Receipt (422 MULTIPAGE_IMAGE_DISABLED when > 1 page)."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)
    _assert_loading_receipt_ready(pl)
    branding = repo.get_tenant_branding(tenant_id)
    brand = _brand(tenant_id, branding=branding)
    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    norm_lang = _normalize_lr_lang(lang)
    pl_dict = dict(pl)
    fp = _document_fingerprint("loading_receipt", norm_lang, branding, pl_dict, items)
    filename = f"{_stem(brand, f'loading_receipt_{norm_lang}', pl.get('loading_receipt_number') or pl.get('reference'))}.png"

    def _render() -> tuple[BytesIO, int]:
        rendered = generate_loading_receipt_pdf_with_meta(brand, pl_dict, items, lang=norm_lang)
        png_buf = render_single_page_png(rendered.buf.getvalue(), rendered.page_count)
        return png_buf, rendered.page_count

    result, page_count = _cached_export_or_render(
        tenant_id=tenant_id,
        pl_id=pl_id,
        doc_type="loading_receipt",
        lang=norm_lang,
        fingerprint=fp,
        filename=filename,
        fmt="png",
        expires_in=_PDF_LINK_SECONDS,
        render_fn=_render,
    )
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "png", "filename": result["filename"]},
    )
    result["page_count"] = page_count
    result["lang"] = norm_lang
    return result


def get_packing_list_documents(
    tenant_id: str,
    pl_id: str,
    customer_user_id: str | None = None,
    *,
    lang_lr: str = "zh",
    lang_pl: str = "en",
) -> dict[str, Any]:
    """Return dual-format & multi-page eligibility metadata for a packing list's documents."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)

    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    branding = repo.get_tenant_branding(tenant_id)
    norm_lr = _normalize_lr_lang(lang_lr)
    norm_pl = _normalize_pl_lang(lang_pl)
    pl_dict = dict(pl)
    brand: pdf_theme.Brand | None = None

    is_approved = pl.get("status") == "approved"
    is_finalized = is_approved and bool(pl.get("ship_date") or pl.get("container_ship_date"))
    pl_pages = 0
    pl_reason: str | None = None
    if is_approved:
        pl_fp = _document_fingerprint("packing_list", norm_pl, branding, pl_dict, items)
        pl_cache_key = f"packing_list:{norm_pl}:{pl_fp}"
        cached_pl_pages = _get_cached_page_count(pl_cache_key)
        if cached_pl_pages is not None:
            pl_pages = cached_pl_pages
        else:
            brand = brand or _brand(tenant_id, branding=branding)
            pl_rendered = generate_packing_list_pdf_with_meta(brand, pl_dict, items, lang=norm_pl)
            pl_pages = pl_rendered.page_count
            _store_cached_page_count(pl_cache_key, pl_pages)
        pl_reason = image_disabled_reason(pl_pages)

    lr_available = is_approved and bool(pl.get("loading_receipt_number"))
    lr_pages = 0
    lr_reason: str | None = None
    if lr_available:
        lr_fp = _document_fingerprint("loading_receipt", norm_lr, branding, pl_dict, items)
        lr_cache_key = f"loading_receipt:{norm_lr}:{lr_fp}"
        cached_lr_pages = _get_cached_page_count(lr_cache_key)
        if cached_lr_pages is not None:
            lr_pages = cached_lr_pages
        else:
            brand = brand or _brand(tenant_id, branding=branding)
            lr_rendered = generate_loading_receipt_pdf_with_meta(brand, pl_dict, items, lang=norm_lr)
            lr_pages = lr_rendered.page_count
            _store_cached_page_count(lr_cache_key, lr_pages)
        lr_reason = image_disabled_reason(lr_pages)

    return {
        "packing_list_id": str(pl["id"]),
        "customer_phone": pl.get("customer_phone"),
        "customer_whatsapp": pl.get("customer_whatsapp") or pl.get("customer_phone"),
        "loading_receipt": {
            "available": lr_available,
            "reference": pl.get("loading_receipt_number"),
            "loaded_at": pl.get("loaded_at"),
            "lang": norm_lr,
            "page_count": lr_pages,
            "image_eligible": lr_available and lr_pages == 1,
            "image_disabled_reason": lr_reason,
        },
        "packing_list": {
            "available": is_approved,
            "finalized": is_finalized,
            "reference": pl.get("reference"),
            "ship_date": pl.get("ship_date") or pl.get("container_ship_date"),
            "estimated_arrival_date": pl.get("estimated_arrival_date") or pl.get("container_eta"),
            "lang": norm_pl,
            "page_count": pl_pages,
            "image_eligible": is_approved and pl_pages == 1,
            "image_disabled_reason": pl_reason,
        },
    }


def share_packing_list_document_whatsapp(
    tenant_id: str,
    pl_id: str,
    document_type: str,
    *,
    lang: str | None = None,
    actor_id: str,
    actor_role: str,
) -> dict[str, Any]:
    """Share a Loading Receipt or Packing List via WhatsApp (PNG for 1-page, PDF for multi-page)."""
    from services.notification import service as notif_service

    if document_type not in ("loading_receipt", "packing_list"):
        raise ValidationError("document_type must be 'loading_receipt' or 'packing_list'")

    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    if document_type == "loading_receipt":
        _assert_loading_receipt_ready(pl)
    else:
        _assert_packing_list_approved(pl)

    recipient_phone = str(pl.get("customer_whatsapp") or pl.get("customer_phone") or "").strip()
    if not recipient_phone:
        raise BusinessRuleViolationError(
            "Customer has no WhatsApp or phone number on file.",
            rule_id="MISSING_CUSTOMER_PHONE",
        )

    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    branding = repo.get_tenant_branding(tenant_id)
    brand = _brand(tenant_id, branding=branding)
    pl_dict = dict(pl)

    if document_type == "loading_receipt":
        norm_lang = _normalize_lr_lang(lang)
        ref = str(pl.get("loading_receipt_number") or pl.get("reference") or pl_id)
        stem = _stem(brand, f"loading_receipt_{norm_lang}", ref)
        pdf_gen = generate_loading_receipt_pdf_with_meta
    else:
        norm_lang = _normalize_pl_lang(lang)
        ref = str(pl.get("reference") or pl.get("container_number") or pl_id)
        stem = _stem(brand, f"packing_list_{norm_lang}", ref)
        pdf_gen = generate_packing_list_pdf_with_meta

    fp = _document_fingerprint(document_type, norm_lang, branding, pl_dict, items)
    page_cache_key = f"{document_type}:{norm_lang}:{fp}"
    cached_pages = _get_cached_page_count(page_cache_key)
    rendered_pdf: pdf_theme.RenderedPdf | None = None
    if cached_pages is None:
        rendered_pdf = pdf_gen(brand, pl_dict, items, lang=norm_lang)
        page_count = rendered_pdf.page_count
        _store_cached_page_count(page_cache_key, page_count)
    else:
        page_count = cached_pages

    notice: str | None = None
    if page_count == 1:
        format_sent = "image"

        def _render_png() -> tuple[BytesIO, int]:
            pdf_out = rendered_pdf or pdf_gen(brand, pl_dict, items, lang=norm_lang)
            return render_single_page_png(pdf_out.buf.getvalue(), pdf_out.page_count), pdf_out.page_count

        upload, _ = _cached_export_or_render(
            tenant_id=tenant_id,
            pl_id=pl_id,
            doc_type=document_type,
            lang=norm_lang,
            fingerprint=fp,
            filename=f"{stem}.png",
            fmt="png",
            expires_in=_PRESIGNED_EXPIRY,
            render_fn=_render_png,
        )
        media_header: dict[str, Any] = {"type": "image", "link": upload["download_url"]}
        event_type = f"{document_type}_image"
    else:
        format_sent = "pdf"

        def _render_pdf() -> tuple[BytesIO, int]:
            pdf_out = rendered_pdf or pdf_gen(brand, pl_dict, items, lang=norm_lang)
            return pdf_out.buf, pdf_out.page_count

        upload, _ = _cached_export_or_render(
            tenant_id=tenant_id,
            pl_id=pl_id,
            doc_type=document_type,
            lang=norm_lang,
            fingerprint=fp,
            filename=f"{stem}.pdf",
            fmt="pdf",
            expires_in=_PRESIGNED_EXPIRY,
            render_fn=_render_pdf,
        )
        media_header = {"type": "document", "link": upload["download_url"], "filename": upload["filename"]}
        event_type = f"{document_type}_pdf"
        notice = (
            f"Image export is disabled for multi-page documents ({page_count} pages) to preserve readability. "
            "The PDF version was attached instead."
        )

    template_map = notif_service.WA_TEMPLATE_MAP_ZH if norm_lang == "zh" else notif_service.WA_TEMPLATE_MAP
    template_name = template_map.get(event_type, event_type)
    components = notif_service.build_wa_components(
        branding,
        {"reference": ref, "container_number": str(pl.get("container_number") or "")},
        event_type=event_type,
        media_header=media_header,
    )
    message_id = notif_service.send_whatsapp(
        phone=recipient_phone,
        template_name=template_name,
        components=components,
        tenant_id=tenant_id,
        language_code=notif_service.wa_language_code(norm_lang),
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=pl_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={
            "channel": "whatsapp",
            "document_type": document_type,
            "format_sent": format_sent,
            "page_count": page_count,
            "lang": norm_lang,
        },
    )

    return {
        "document_type": document_type,
        "format_sent": format_sent,
        "page_count": page_count,
        "lang": norm_lang,
        "recipient_phone": recipient_phone,
        "filename": upload["filename"],
        "message_id": message_id or None,
        "notice": notice,
    }


def export_release_note_pdf(
    tenant_id: str,
    note_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """The release note as its one PDF, behind a five-minute link (a customer: their own only)."""
    note = repo.get_release_note_for_pdf(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)
    _assert_customer_owns(tenant_id, customer_user_id, note.get("customer_id"), "release_note", note_id)
    brand = _brand(tenant_id)
    buf = generate_release_note_pdf(brand, dict(note))
    return _publish_pdf(
        tenant_id,
        buf,
        _stem(brand, "release_note", note.get("reference_number") or note_id),
        entity_type="release_note",
        entity_id=note_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )


def export_receipt_pdf(
    tenant_id: str,
    payment_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """A payment's receipt as a PDF, behind a five-minute link (a customer: their own only, else "not found")."""
    payment = repo.get_payment_for_receipt_pdf(tenant_id, payment_id)
    if not payment:
        raise ResourceNotFoundError("payment_record", payment_id)
    _assert_customer_owns(tenant_id, customer_user_id, payment.get("billing_customer_id"), "payment_record", payment_id)
    brand = _brand(tenant_id)
    buf = generate_receipt_pdf(brand, dict(payment))
    return _publish_pdf(
        tenant_id,
        buf,
        _stem(brand, "receipt", payment.get("receipt_number") or payment_id),
        entity_type="payment_record",
        entity_id=payment_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )


def export_invoice_pdf(
    tenant_id: str,
    billing_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """The invoice as its one PDF (FD-39), behind a five-minute link (a customer: their own only)."""
    billing = repo.get_billing_for_export(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)
    _assert_customer_owns(tenant_id, customer_user_id, billing.get("customer_id"), "billing", billing_id)
    brand = _brand(tenant_id)
    buf = generate_invoice_pdf(
        brand,
        dict(billing),
        repo.get_misc_charges_for_export(tenant_id, billing_id),
        bank=repo.get_bank_transfer_config(tenant_id),
        online=repo.paystack_enabled(tenant_id),
    )
    return _publish_pdf(
        tenant_id,
        buf,
        _stem(brand, "invoice", billing.get("invoice_number") or billing_id),
        entity_type="billing",
        entity_id=billing_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )


def export_manifest_pdf(tenant_id: str, manifest_id: str, actor_id: str, actor_role: str) -> dict[str, Any]:
    """The manifest as its one PDF (FD-39), behind a five-minute link."""
    manifest = repo.get_manifest_for_export(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)
    brand = _brand(tenant_id)
    items = repo.get_items_for_manifest(tenant_id, str(manifest.get("container_id") or ""))
    buf = generate_manifest_pdf(brand, dict(manifest), items)
    return _publish_pdf(
        tenant_id,
        buf,
        _stem(brand, "manifest", manifest.get("container_number") or manifest_id),
        entity_type="manifest",
        entity_id=manifest_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )


# ---------------------------------------------------------------------------
# Packing list import — presigned upload
# ---------------------------------------------------------------------------


def generate_import_presigned_url(tenant_id: str, content_type: str, size_bytes: object = None) -> dict[str, Any]:
    """Generate an S3 presigned POST URL for uploading a packing-list import .xlsx.

    Scoped to {tenant_id}/imports/{uuid}.xlsx so the resulting file_key always
    satisfies import_packing_list()'s tenant-prefix guard. No DB row is
    created — the uploaded file is transient, consumed once by
    POST /v1/packing-lists/import and never listed or referenced again, so
    there's nothing to persist (unlike claim evidence or container documents).
    """
    upload = uploads.presign_upload(
        uploads.SPREADSHEET_IMPORT, tenant_id, ("imports",), f"{uuid.uuid4()}.xlsx", content_type, size_bytes
    )
    return {**upload.as_response(), "file_key": upload.key}


# ---------------------------------------------------------------------------
# Packing list import
# ---------------------------------------------------------------------------


def import_packing_list(
    tenant_id: str,
    container_id: str,
    file_key: str,
    actor_id: str,
    ctx: Any,
) -> dict[str, Any]:
    # 1. Guard: file_key must be under this tenant's imports S3 prefix to prevent cross-tenant/cross-category reads.
    expected_prefix = f"{tenant_id}/imports/"
    if not file_key.startswith(expected_prefix) or ".." in file_key:
        raise ValidationError(f"file_key must be under the tenant imports prefix '{expected_prefix}'")

    # 2. Download file from object storage
    uploads.check_stored_size(uploads.SPREADSHEET_IMPORT, file_key)
    file_buffer = BytesIO(get_storage_provider().get_object(file_key))

    # 3. Validate container is present and in 'loading' status BEFORE writing
    tenant_short = repo.get_tenant_short(tenant_id)
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    container_status = container.get("status")
    if container_status is not None and container_status != "loading":
        raise BusinessRuleViolationError(
            f"Container must be in 'loading' status to import packing lists (current: {container_status})",
            rule_id="CONTAINER_NOT_LOADING",
        )
    container_number = str(container.get("container_number") or "")

    # 4. Pre-fetch customers (name → id mapping) and minimum CBM floor
    customers = repo.get_tenant_customers(tenant_id)
    customers_by_name = {c["name"].lower(): str(c["id"]) for c in customers}
    min_cbm = get_min_cbm_per_item(tenant_id)

    # 5. Parse and validate
    items_by_group, errors, total_rows = parse_packing_list_xlsx(file_buffer, customers_by_name)

    # 6. Create packing lists grouped by (customer_id, received_date) atomically
    packing_lists_created = 0
    imported_count = 0
    with tenant_transaction(tenant_id):
        seq = repo.get_next_carton_sequence(tenant_id, container_id)
        tracking_seq_cache: dict[str, int] = {}
        tracking_cache: dict[tuple[str, Any], str] = {}

        for (customer_id, _received_date), items in items_by_group.items():
            pl = repo.create_packing_list(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "container_id": container_id,
                    "customer_id": customer_id,
                    "created_by": actor_id,
                    "reference": repo.get_next_pl_reference(tenant_id),
                },
            )
            if pl is None:
                raise RuntimeError("create_packing_list returned None unexpectedly")
            pl_id = str(pl["id"])

            item_rows = []
            for item in items:
                item_date = item["received_date"]
                date_str = item_date.strftime("%Y%m%d")
                date_prefix = f"{tenant_short}-TRK-{date_str}"
                cache_key = (customer_id, item_date)

                if cache_key in tracking_cache:
                    tracking_code = tracking_cache[cache_key]
                else:
                    existing = repo.get_existing_tracking_code(tenant_id, customer_id, item_date)
                    if existing:
                        tracking_code = existing
                    else:
                        if date_prefix not in tracking_seq_cache:
                            trk_seq = repo.get_next_tracking_sequence(tenant_id, date_prefix)
                            tracking_seq_cache[date_prefix] = trk_seq + 1
                        else:
                            trk_seq = tracking_seq_cache[date_prefix]
                            tracking_seq_cache[date_prefix] = trk_seq + 1
                        tracking_code = f"{date_prefix}-{trk_seq:03d}"
                    tracking_cache[cache_key] = tracking_code

                carton_tag = f"{tenant_short}-{container_number}-{seq:03d}"
                seq += 1

                floored_cbm = float(apply_min_cbm(Decimal(str(item["cbm"] or 0)), min_cbm))

                item_rows.append(
                    {
                        "packing_list_id": pl_id,
                        "description": item["description"],
                        "weight_dispatch_kg": item["weight_dispatch_kg"],
                        "weight_actual_kg": item["weight_actual_kg"],
                        "carton_tag": carton_tag,
                        "tracking_code": tracking_code,
                        "cbm": floored_cbm,
                        "length_cm": item["length_cm"],
                        "width_cm": item["width_cm"],
                        "height_cm": item["height_cm"],
                        "received_date": item_date,
                    }
                )

            repo.insert_packing_list_items(tenant_id, item_rows)
            imported_count += len(item_rows)
            packing_lists_created += 1

    # One summary entry, not one per row — a bulk import can create dozens
    # of packing lists in a single call, and a tenant admin auditing "who
    # brought this cargo into the system" needs the shape of the import
    # (how many lists/items, which container, which file), not a wall of
    # near-duplicate rows. Ground-truth gap found while auditing log
    # coverage: this bulk-creation path (goods entering the system) had no
    # audit_log entry at all.
    log_audit(
        tenant_id=tenant_id,
        entity_type="packing_list",
        entity_id=container_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={
            "container_id": container_id,
            "packing_lists_created": packing_lists_created,
            "items_imported": imported_count,
            "errors": len(errors),
            "source_file_key": file_key,
        },
    )

    return {
        "total_rows": total_rows,
        "imported": imported_count,
        "errors": len(errors),
        "packing_lists_created": packing_lists_created,
        "error_details": errors,
    }


# ---------------------------------------------------------------------------
# Manifest import — flexible, auto-creating
# ---------------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",  # "21-May-2026", as printed on the source manifest
)


def _parse_metadata_date(raw: Any) -> date | None:
    """Best-effort parse of a header-metadata date string; None if unparseable/blank.

    Unlike `_import_helpers.parse_date` (which defaults blanks to today() for
    the per-row "received date" field of the existing importer), container
    metadata is optional — a blank or unparseable value should stay None
    rather than being defaulted, since these are container-level fields the
    importer only sets at creation time.
    """
    if not raw:
        return None
    # Excel date cells arrive as native datetimes — use them directly rather
    # than round-tripping through a string format that may not match.
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def process_manifest_import(
    tenant_id: str,
    file_key: str,
    actor_id: str,
    ctx: Any,
) -> dict[str, Any]:
    """Parse a manifest .xlsx and auto-create/match container, customers, and packing lists."""
    expected_prefix = f"{tenant_id}/imports/"
    if not file_key.startswith(expected_prefix) or ".." in file_key:
        raise ValidationError(f"file_key must be under the tenant imports prefix '{expected_prefix}'")

    uploads.check_stored_size(uploads.SPREADSHEET_IMPORT, file_key)
    file_buffer = BytesIO(get_storage_provider().get_object(file_key))

    try:
        container_metadata, rows, errors, total_rows = parse_manifest_xlsx(file_buffer)
    except ValueError as exc:
        raise ValidationError(str(exc), field_errors={"file": str(exc)}) from exc

    container_number = str(container_metadata.get("container_number") or "").strip()
    if not container_number:
        raise ValidationError("Could not find PARTIAL NO / container number in the manifest header")

    # Resolve PLATFORM-scoped tenant attributes BEFORE opening tenant_transaction.
    tenant_short = repo.get_tenant_short(tenant_id)
    dial_code = dial_code_for_country(repo.get_tenant_destination_country(tenant_id))
    min_cbm = get_min_cbm_per_item(tenant_id)

    # 1. Find-or-create the container.
    containers_created = 0
    container = repo.find_container_by_number(tenant_id, container_number)
    if container is None:
        check_container_limit(tenant_id)
    else:
        container_status = container.get("status")
        if container_status is not None and container_status != "loading":
            raise BusinessRuleViolationError(
                f"Container '{container_number}' is in '{container_status}' status and cannot accept manifest imports",
                rule_id="CONTAINER_NOT_LOADING",
            )

    customers_created = 0
    packing_lists_created = 0
    items_created = 0
    items_skipped_duplicate = 0
    newly_created_customer_ids: list[str] = []

    with tenant_transaction(tenant_id):
        if container is None:
            container = repo.create_container(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "container_number": container_number,
                    "parcel_number": container_metadata.get("parcel_number"),
                    "destination": container_metadata.get("destination") or "Nigeria",
                    "ship_date": _parse_metadata_date(container_metadata.get("ship_date")),
                    "departure_date": _parse_metadata_date(container_metadata.get("departure_date")),
                    "estimated_arrival_date": _parse_metadata_date(container_metadata.get("estimated_arrival_date")),
                    "created_by": actor_id,
                },
            )
            if container is None:
                raise RuntimeError("create_container returned None unexpectedly")
            containers_created = 1
        container_id = str(container["id"])

        seq = repo.get_next_carton_sequence(tenant_id, container_id)
        tracking_seq_cache: dict[str, int] = {}
        tracking_cache: dict[str, str] = {}
        today = date.today()
        date_prefix = f"{tenant_short}-TRK-{today.strftime('%Y%m%d')}"

        customer_cache: dict[str, str] = {}
        packing_list_cache: dict[str, str] = {}
        # Cache pre-import delivery-note checks per (pl_id, delivery_note_number, bale_no)
        # so multi-line delivery notes within the same file are all imported on first import
        # while true re-imports of a previously imported delivery note are still skipped.
        preexisting_delivery_note_cache: dict[tuple[str, str, str | None], bool] = {}

        for row in rows:
            # 2. Find-or-create customer: match by normalized phone when present;
            # only fall back to exact name match when the row has no phone (so two
            # distinct customers sharing a name with different phones never merge).
            phone = normalize_phone(row.get("customer_phone"), dial_code)
            name = row["customer_name"]
            cache_key = f"phone:{phone}" if phone else f"name:{name.lower()}"

            if cache_key in customer_cache:
                customer_id = customer_cache[cache_key]
            else:
                existing_customer = repo.find_customer_by_phone(tenant_id, phone) if phone else None
                if existing_customer is None and not phone:
                    existing_customer = repo.find_customer_by_name(tenant_id, name)
                if existing_customer is not None:
                    customer_id = str(existing_customer["id"])
                else:
                    new_customer = repo.create_customer(tenant_id, name, phone)
                    if new_customer is None:
                        raise RuntimeError("create_customer returned None unexpectedly")
                    customer_id = str(new_customer["id"])
                    customers_created += 1
                    newly_created_customer_ids.append(customer_id)
                customer_cache[cache_key] = customer_id

            # 3. Find-or-create an editable packing list for (customer, container).
            # Never append items into an already-approved or rejected packing list.
            if customer_id in packing_list_cache:
                pl_id = packing_list_cache[customer_id]
            else:
                existing_pl = repo.find_packing_list(tenant_id, container_id, customer_id)
                if existing_pl is not None and existing_pl.get("status") not in ("approved", "rejected"):
                    pl_id = str(existing_pl["id"])
                else:
                    new_pl = repo.create_packing_list(
                        tenant_id,
                        {
                            "tenant_id": tenant_id,
                            "container_id": container_id,
                            "customer_id": customer_id,
                            "created_by": actor_id,
                            "reference": repo.get_next_pl_reference(tenant_id),
                        },
                    )
                    if new_pl is None:
                        raise RuntimeError("create_packing_list returned None unexpectedly")
                    pl_id = str(new_pl["id"])
                    packing_lists_created += 1
                packing_list_cache[customer_id] = pl_id

            # 4. Dedupe by (delivery_note_number, bale_no) against pre-existing items in the packing list.
            delivery_note_number = row.get("delivery_note_number")
            if delivery_note_number:
                dedupe_key = (pl_id, delivery_note_number, row.get("bale_no"))
                if dedupe_key not in preexisting_delivery_note_cache:
                    existing_item = repo.find_existing_item_by_delivery_note(
                        tenant_id, pl_id, delivery_note_number, row.get("bale_no")
                    )
                    preexisting_delivery_note_cache[dedupe_key] = existing_item is not None
                if preexisting_delivery_note_cache[dedupe_key]:
                    items_skipped_duplicate += 1
                    continue

            # 5. Generate carton_tag/tracking_code.
            if customer_id in tracking_cache:
                tracking_code = tracking_cache[customer_id]
            else:
                existing_tracking = repo.get_existing_tracking_code(tenant_id, customer_id, today)
                if existing_tracking:
                    tracking_code = existing_tracking
                else:
                    if date_prefix not in tracking_seq_cache:
                        trk_seq = repo.get_next_tracking_sequence(tenant_id, date_prefix)
                        tracking_seq_cache[date_prefix] = trk_seq + 1
                    else:
                        trk_seq = tracking_seq_cache[date_prefix]
                        tracking_seq_cache[date_prefix] = trk_seq + 1
                    tracking_code = f"{date_prefix}-{trk_seq:03d}"
                tracking_cache[customer_id] = tracking_code

            carton_tag = f"{tenant_short}-{container_number}-{seq:03d}"
            seq += 1

            raw_cbm = Decimal(str(row.get("cbm") or 0))
            floored_cbm = float(apply_min_cbm(raw_cbm, min_cbm)) if raw_cbm > Decimal("0") else float(raw_cbm)

            repo.insert_manifest_items(
                tenant_id,
                [
                    {
                        "packing_list_id": pl_id,
                        "description": row["description"],
                        "weight_actual_kg": row.get("weight_actual_kg"),
                        "carton_tag": carton_tag,
                        "tracking_code": tracking_code,
                        "cbm": floored_cbm,
                        "received_date": today,
                        "delivery_note_number": delivery_note_number,
                        "quantity": row.get("quantity") or 1,
                        "quantity_raw": row.get("quantity_raw"),
                        "package_unit": row.get("package_unit"),
                        "bale_type": row.get("bale_type"),
                        "bale_no": row.get("bale_no"),
                        "original_receipt_number": row.get("original_receipt_number"),
                        "delivery_zone": row.get("delivery_zone"),
                        "on_hold": bool(row.get("on_hold")),
                        "hold_reason": container_metadata.get("hold_reason") if row.get("on_hold") else None,
                    }
                ],
            )
            items_created += 1

    # 6. Auto-issue an account-creation invite for every customer this import
    # *created* (never matched customers — they may already have a login).
    # Best-effort, same pattern as record_usage below: a notification-side
    # outage must never fail the import itself.
    from services.tenant_management.service import issue_customer_invite

    for new_customer_id in newly_created_customer_ids:
        try:
            issue_customer_invite(tenant_id, new_customer_id, actor_id=actor_id)
        except Exception as exc:
            logger.warning("Failed to issue customer invite for customer_id=%s: %s", new_customer_id, exc)

    # One summary entry, not one per row — a manifest import can auto-create
    # a container, dozens of customers, and dozens of packing lists in a
    # single call. Ground-truth gap found while auditing log coverage: this
    # bulk-creation path (goods entering the system, plus new customer
    # accounts) had no audit_log entry at all.
    log_audit(
        tenant_id=tenant_id,
        entity_type="manifest",
        entity_id=container_id,
        action="CREATE",
        actor_id=actor_id,
        actor_role=str(ctx.role),
        after_state={
            "container_id": container_id,
            "containers_created": containers_created,
            "customers_created": customers_created,
            "packing_lists_created": packing_lists_created,
            "items_created": items_created,
            "items_skipped_duplicate": items_skipped_duplicate,
            "errors": len(errors),
            "source_file_key": file_key,
        },
    )

    return {
        "total_rows": total_rows,
        "imported": items_created,
        "errors": len(errors),
        "containers_created": containers_created,
        "customers_created": customers_created,
        "packing_lists_created": packing_lists_created,
        "items_created": items_created,
        "items_skipped_duplicate": items_skipped_duplicate,
        "error_details": errors,
    }
