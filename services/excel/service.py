"""Orchestration: fetch data → generate file → upload S3 → presigned URL."""

import csv
import io
import logging
import re
import uuid
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
from .export_manifest import generate_manifest_xlsx
from .export_manifest_pdf import generate_manifest_pdf
from .export_packing_list import generate_packing_list_xlsx
from .export_packing_list_pdf import generate_packing_list_pdf
from .export_receipt_pdf import generate_receipt_pdf
from .export_release_note_pdf import generate_release_note_pdf
from .import_manifest import parse_manifest_xlsx
from .import_packing_list import parse_packing_list_xlsx

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


def _brand(tenant_id: str) -> pdf_theme.Brand:
    """The tenant's branding for a document, with its logo's bytes when one is set (FD-29).

    The logo is read only from this tenant's own logo prefix. A logo that cannot be read leaves the initials tile:
    a document must never fail for want of its logo.
    """
    branding = repo.get_tenant_branding(tenant_id)
    logo: bytes | None = None
    key = branding.get("logo_key")
    if isinstance(key, str) and key.startswith(f"{tenant_id}/branding/logo/"):
        try:
            logo = get_storage_provider().get_object(key)
        except Exception:  # noqa: BLE001 — any storage failure falls back to the initials tile
            logger.warning("Could not read the tenant logo for a document", exc_info=True)
    return pdf_theme.Brand.from_branding(branding, logo=logo)


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


def export_packing_list_pdf(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """The packing list as its one PDF, behind a five-minute link (a customer: their own only)."""
    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)
    _assert_customer_owns(tenant_id, customer_user_id, pl.get("customer_id"), "packing_list", pl_id)
    brand = _brand(tenant_id)
    buf = generate_packing_list_pdf(brand, dict(pl), repo.get_items_for_packing_list(tenant_id, pl_id))
    return _publish_pdf(
        tenant_id,
        buf,
        _stem(brand, "packing_list", pl.get("reference") or pl.get("container_number")),
        entity_type="packing_list",
        entity_id=pl_id,
        actor_id=actor_id,
        actor_role=actor_role,
    )


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
