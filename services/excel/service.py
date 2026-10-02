"""Orchestration: fetch data → generate file → upload S3 → presigned URL."""
import csv
import io
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

import boto3

from shared.audit import log_audit
from shared.exceptions import BusinessRuleViolationError, ResourceNotFoundError
from shared.phone import dial_code_for_country, normalize_phone

from . import repository as repo
from .export_billing import generate_billing_xlsx
from .export_manifest import generate_manifest_xlsx
from .export_packing_list import generate_packing_list_xlsx
from .export_packing_list_pdf import generate_packing_list_pdf
from .export_receipt_pdf import generate_receipt_pdf
from .export_release_note_pdf import generate_release_note_pdf
from .import_manifest import parse_manifest_xlsx
from .import_packing_list import parse_packing_list_xlsx

logger = logging.getLogger(__name__)

_s3_client = boto3.client("s3")
_BUCKET = os.environ.get("S3_BUCKET_NAME", "logistics-assets")
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


def _upload_and_presign(tenant_id: str, filename: str, buf: BytesIO, fmt: str = "xlsx") -> dict[str, Any]:
    today = date.today().strftime("%Y-%m-%d")
    key = f"{tenant_id}/exports/{today}/{filename}"
    file_bytes = buf.getvalue()
    _s3_client.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=file_bytes,
        ContentType=_CONTENT_TYPES.get(fmt, _CONTENT_TYPES["xlsx"]),
    )
    download_url = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=_PRESIGNED_EXPIRY,
    )
    expires_at = (datetime.utcnow() + timedelta(seconds=_PRESIGNED_EXPIRY)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    writer.writerows(rows)
    return BytesIO(buf.getvalue().encode("utf-8-sig"))  # utf-8-sig for Excel compatibility


# ---------------------------------------------------------------------------
# PDF generators (reportlab — simple table layout)
# ---------------------------------------------------------------------------


def _rows_to_pdf(title: str, rows: list[dict[str, Any]], columns: list[str]) -> BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=1 * cm, rightMargin=1 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm
    )
    styles = getSampleStyleSheet()

    header_row = [col.replace("_", " ").title() for col in columns]
    data = [header_row]
    for row in rows:
        data.append([str(row.get(col, "") or "") for col in columns])

    col_width = (landscape(A4)[0] - 2 * cm) / max(len(columns), 1)
    table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a56db")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements = [
        Paragraph(title, styles["Title"]),
        Spacer(1, 0.4 * cm),
        table,
    ]
    doc.build(elements)
    buf.seek(0)
    return buf


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


def export_packing_list(tenant_id: str, pl_id: str, fmt: str = "xlsx") -> dict[str, Any]:
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
    elif fmt == "pdf":
        title = f"Packing List — {container_number} — {customer_name}"
        buf = _rows_to_pdf(title, items, _PL_COLUMNS)
    else:
        buf = generate_packing_list_xlsx(display_name, container_number, customer_name, items)

    return _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)


# ---------------------------------------------------------------------------
# Manifest export
# ---------------------------------------------------------------------------


_MANIFEST_COLUMNS = ["customer_name", "carton_count", "total_weight_kg", "total_cbm", "carton_tags"]


def export_manifest(tenant_id: str, manifest_id: str, fmt: str = "xlsx") -> dict[str, Any]:
    manifest = repo.get_manifest_for_export(tenant_id, manifest_id)
    if not manifest:
        raise ResourceNotFoundError("manifest", manifest_id)

    container_id = str(manifest.get("container_id") or "")
    container_number = str(manifest.get("container_number") or "")
    display_name = repo.get_tenant_display_name(tenant_id)
    all_items = repo.get_items_for_manifest(tenant_id, container_id)

    # Build per-customer summary rows
    customer_data: dict[str, dict[str, Any]] = {}
    for item in all_items:
        cname = str(item.get("customer_name") or "")
        if cname not in customer_data:
            customer_data[cname] = {
                "customer_name": cname,
                "carton_count": 0,
                "total_weight_kg": 0.0,
                "total_cbm": 0.0,
                "carton_tags": [],
            }
        d = customer_data[cname]
        d["carton_count"] += 1
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
    elif fmt == "pdf":
        title = f"Manifest — {container_number}"
        buf = _rows_to_pdf(title, customer_rows, _MANIFEST_COLUMNS)
    else:
        buf = generate_manifest_xlsx(display_name, container_number, customer_rows, all_items)

    return _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)


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
# actually uses — was stripped down). `adjustments_ngn` is deliberately
# excluded: it is never populated anywhere in this codebase (CBM dispute
# resolution rewrites subtotal_ngn/total_ngn directly instead), so including
# it would only ever show a misleading, permanently-zero column.
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
    elif fmt == "pdf":
        title = f"Billing — {container_number}"
        buf = _rows_to_pdf(title, [billing], _BILLING_COLUMNS)
    else:
        buf = generate_billing_xlsx([billing])

    return _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)


# ---------------------------------------------------------------------------
# Billing export (all billing for a container)
# ---------------------------------------------------------------------------


def export_container_billing(tenant_id: str, container_id: str, fmt: str = "xlsx") -> dict[str, Any]:
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
    elif fmt == "pdf":
        title = f"Container Billing — {container_number}"
        buf = _rows_to_pdf(title, billing_rows, _BILLING_COLUMNS)
    else:
        buf = generate_billing_xlsx(billing_rows)

    return _upload_and_presign(tenant_id, f"{stem}.{fmt}", buf, fmt=fmt)


# ---------------------------------------------------------------------------
# Packing list PDF (dedicated layout — EXPORT audit)
# ---------------------------------------------------------------------------


def export_packing_list_pdf(
    tenant_id: str,
    pl_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """Generate a branded A4 packing list PDF and return a 5-min presigned GET URL.

    When customer_user_id is supplied (CUSTOMER role), verifies that the packing
    list belongs to that customer; raises ResourceNotFoundError (not 403) on mismatch.
    """
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    pl = repo.get_packing_list_for_export(tenant_id, pl_id)
    if not pl:
        raise ResourceNotFoundError("packing_list", pl_id)

    if customer_user_id:
        customer_id = repo.get_customer_id_for_user(tenant_id, customer_user_id)
        if not customer_id or str(pl.get("customer_id")) != customer_id:
            raise ResourceNotFoundError("packing_list", pl_id)

    items = repo.get_items_for_packing_list(tenant_id, pl_id)
    branding = repo.get_tenant_branding(tenant_id)

    buf = generate_packing_list_pdf(branding, dict(pl), items)

    today_str = date.today().strftime("%Y%m%d")
    company_part = _safe_name(branding.get("company_name", "export"))
    container_part = _safe_name(str(pl.get("container_number") or ""))
    stem = f"{company_part}_packing_list_{container_part}_pdf_{today_str}"
    result = _upload_and_presign(tenant_id, f"{stem}.pdf", buf, fmt="pdf")
    result["expires_in_seconds"] = 300
    # Override the presigned URL expiry to 5 minutes (task requirement)
    key = f"{tenant_id}/exports/{date.today().strftime('%Y-%m-%d')}/{stem}.pdf"
    result["download_url"] = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=300,
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
    return result


# ---------------------------------------------------------------------------
# Release note PDF (dedicated layout — EXPORT audit)
# ---------------------------------------------------------------------------


def export_release_note_pdf(
    tenant_id: str,
    note_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """Generate a branded A4 release note PDF and return a 5-min presigned GET URL.

    When customer_user_id is supplied (CUSTOMER role), verifies ownership; raises
    ResourceNotFoundError (not 403) on mismatch.
    """
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    note = repo.get_release_note_for_pdf(tenant_id, note_id)
    if not note:
        raise ResourceNotFoundError("release_note", note_id)

    if customer_user_id:
        customer_id = repo.get_customer_id_for_user(tenant_id, customer_user_id)
        if not customer_id or str(note.get("customer_id")) != customer_id:
            raise ResourceNotFoundError("release_note", note_id)

    branding = repo.get_tenant_branding(tenant_id)
    buf = generate_release_note_pdf(branding, dict(note))

    today_str = date.today().strftime("%Y%m%d")
    ref = _safe_name(str(note.get("reference_number") or note_id))
    stem = f"{_safe_name(branding.get('company_name', 'export'))}_release_note_{ref}_{today_str}"
    result = _upload_and_presign(tenant_id, f"{stem}.pdf", buf, fmt="pdf")
    result["expires_in_seconds"] = 300
    key = f"{tenant_id}/exports/{date.today().strftime('%Y-%m-%d')}/{stem}.pdf"
    result["download_url"] = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=300,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="release_note",
        entity_id=note_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "pdf", "filename": result["filename"]},
    )
    return result


def export_receipt_pdf(
    tenant_id: str,
    payment_id: str,
    actor_id: str,
    actor_role: str,
    customer_user_id: str | None = None,
) -> dict[str, Any]:
    """Generate a branded A4 cash receipt PDF and return a 5-min presigned GET URL.

    Mirrors export_release_note_pdf: same presign/audit shape, and the same
    404-not-403 ownership rule — when customer_user_id is supplied (CUSTOMER
    role), a payment belonging to another customer raises ResourceNotFoundError
    so the endpoint never doubles as an existence oracle.
    """
    from shared.audit import log_audit
    from shared.exceptions import ResourceNotFoundError

    payment = repo.get_payment_for_receipt_pdf(tenant_id, payment_id)
    if not payment:
        raise ResourceNotFoundError("payment_record", payment_id)

    if customer_user_id:
        customer_id = repo.get_customer_id_for_user(tenant_id, customer_user_id)
        if not customer_id or str(payment.get("billing_customer_id")) != customer_id:
            raise ResourceNotFoundError("payment_record", payment_id)

    branding = repo.get_tenant_branding(tenant_id)
    buf = generate_receipt_pdf(branding, dict(payment))

    today_str = date.today().strftime("%Y%m%d")
    ref = _safe_name(str(payment.get("receipt_number") or payment_id))
    stem = f"{_safe_name(branding.get('company_name', 'export'))}_receipt_{ref}_{today_str}"
    result = _upload_and_presign(tenant_id, f"{stem}.pdf", buf, fmt="pdf")
    result["expires_in_seconds"] = 300
    key = f"{tenant_id}/exports/{date.today().strftime('%Y-%m-%d')}/{stem}.pdf"
    result["download_url"] = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": key},
        ExpiresIn=300,
    )

    log_audit(
        tenant_id=tenant_id,
        entity_type="payment_record",
        entity_id=payment_id,
        action="EXPORT",
        actor_id=actor_id,
        actor_role=actor_role,
        after_state={"format": "pdf", "filename": result["filename"]},
    )
    return result


# ---------------------------------------------------------------------------
# Packing list import — presigned upload
# ---------------------------------------------------------------------------

_IMPORT_URL_EXPIRY = 900  # 15 minutes
_IMPORT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_IMPORT_ALLOWED_CONTENT_TYPES = frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})


def generate_import_presigned_url(tenant_id: str, content_type: str) -> dict[str, Any]:
    """Generate an S3 presigned POST URL for uploading a packing-list import .xlsx.

    Scoped to {tenant_id}/imports/{uuid}.xlsx so the resulting file_key always
    satisfies import_packing_list()'s tenant-prefix guard. No DB row is
    created — the uploaded file is transient, consumed once by
    POST /v1/packing-lists/import and never listed or referenced again, so
    there's nothing to persist (unlike claim evidence or container documents).
    """
    if content_type not in _IMPORT_ALLOWED_CONTENT_TYPES:
        raise BusinessRuleViolationError(
            f"content_type '{content_type}' not allowed. " f"Allowed: {', '.join(sorted(_IMPORT_ALLOWED_CONTENT_TYPES))}",
            rule_id="INVALID_CONTENT_TYPE",
        )

    file_key = f"{tenant_id}/imports/{uuid.uuid4()}.xlsx"

    presigned = _s3_client.generate_presigned_post(
        Bucket=_BUCKET,
        Key=file_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, _IMPORT_MAX_FILE_SIZE],
        ],
        ExpiresIn=_IMPORT_URL_EXPIRY,
    )

    return {
        "upload_url": presigned["url"],
        "fields": presigned["fields"],
        "file_key": file_key,
    }


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
    # 1. Guard: file_key must be under this tenant's S3 prefix to prevent cross-tenant reads.
    expected_prefix = f"{tenant_id}/"
    if not file_key.startswith(expected_prefix) or ".." in file_key:
        from shared.exceptions import ValidationError

        raise ValidationError(f"file_key must be under the tenant prefix '{expected_prefix}'")

    # 2. Download file from S3
    s3_obj = _s3_client.get_object(Bucket=_BUCKET, Key=file_key)
    file_buffer = BytesIO(s3_obj["Body"].read())

    # 2. Pre-fetch customers (name → id mapping)
    customers = repo.get_tenant_customers(tenant_id)
    customers_by_name = {c["name"].lower(): str(c["id"]) for c in customers}

    # 3. Parse and validate
    items_by_group, errors, total_rows = parse_packing_list_xlsx(file_buffer, customers_by_name)

    # 4. Get tenant short and container for tag generation
    tenant_short = repo.get_tenant_short(tenant_id)
    container = repo.get_container_by_id(tenant_id, container_id)
    if not container:
        raise ResourceNotFoundError("container", container_id)
    container_number = str(container.get("container_number") or "")

    # 5. Create packing lists grouped by (customer_id, received_date)
    packing_lists_created = 0
    imported_count = 0
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
                        tracking_seq_cache[date_prefix] = trk_seq
                    else:
                        trk_seq = tracking_seq_cache[date_prefix]
                        tracking_seq_cache[date_prefix] += 1
                    tracking_code = f"{date_prefix}-{trk_seq:03d}"
                tracking_cache[cache_key] = tracking_code

            carton_tag = f"{tenant_short}-{container_number}-{seq:03d}"
            seq += 1

            item_rows.append(
                {
                    "packing_list_id": pl_id,
                    "description": item["description"],
                    "weight_dispatch_kg": item["weight_dispatch_kg"],
                    "weight_actual_kg": item["weight_actual_kg"],
                    "carton_tag": carton_tag,
                    "tracking_code": tracking_code,
                    "cbm": item["cbm"],
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
    """Parse a manifest .xlsx and auto-create/match container, customers, and packing lists.

    See `services/excel/import_manifest.py` for the parser and
    `19_excel_import_export.md` §"Manifest Import" for the full behaviour
    reference (header-alias table, dedupe key, auto-creation semantics).
    """
    expected_prefix = f"{tenant_id}/"
    if not file_key.startswith(expected_prefix) or ".." in file_key:
        from shared.exceptions import ValidationError

        raise ValidationError(f"file_key must be under the tenant prefix '{expected_prefix}'")

    s3_obj = _s3_client.get_object(Bucket=_BUCKET, Key=file_key)
    file_buffer = BytesIO(s3_obj["Body"].read())

    container_metadata, rows, errors, total_rows = parse_manifest_xlsx(file_buffer)

    container_number = str(container_metadata.get("container_number") or "").strip()
    if not container_number:
        from shared.exceptions import ValidationError

        raise ValidationError("Could not find PARTIAL NO / container number in the manifest header")

    # 1. Find-or-create the container. Fields set only on creation — an
    # existing container's fields are never overwritten by a re-import.
    containers_created = 0
    container = repo.find_container_by_number(tenant_id, container_number)
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

    tenant_short = repo.get_tenant_short(tenant_id)
    seq = repo.get_next_carton_sequence(tenant_id, container_id)
    tracking_seq_cache: dict[str, int] = {}
    tracking_cache: dict[str, str] = {}
    today = date.today()
    date_prefix = f"{tenant_short}-TRK-{today.strftime('%Y%m%d')}"

    dial_code = dial_code_for_country(repo.get_tenant_destination_country(tenant_id))

    customers_created = 0
    packing_lists_created = 0
    items_created = 0
    items_skipped_duplicate = 0
    customer_cache: dict[str, str] = {}  # normalized phone or lowercase name -> customer_id
    packing_list_cache: dict[str, str] = {}  # customer_id -> packing_list_id
    newly_created_customer_ids: list[str] = []  # invites are issued only for these, never matches

    for row in rows:
        # 2. Find-or-create customer, matched by normalized phone, falling
        # back to exact name match when phone is missing.
        phone = normalize_phone(row.get("customer_phone"), dial_code)
        name = row["customer_name"]
        cache_key = phone or name.lower()

        if cache_key in customer_cache:
            customer_id = customer_cache[cache_key]
        else:
            existing_customer = repo.find_customer_by_phone(tenant_id, phone) if phone else None
            if existing_customer is None:
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

        # 3. Find-or-create the packing list for (customer, container).
        if customer_id in packing_list_cache:
            pl_id = packing_list_cache[customer_id]
        else:
            existing_pl = repo.find_packing_list(tenant_id, container_id, customer_id)
            if existing_pl is not None:
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

        # 4. Dedupe by (delivery_note_number, bale_no) within the packing list —
        #    one delivery note can legitimately cover several distinct bales.
        delivery_note_number = row.get("delivery_note_number")
        if delivery_note_number:
            existing_item = repo.find_existing_item_by_delivery_note(tenant_id, pl_id, delivery_note_number, row.get("bale_no"))
            if existing_item is not None:
                items_skipped_duplicate += 1
                continue

        # 5. Generate carton_tag/tracking_code, same pattern as the existing importer.
        if customer_id in tracking_cache:
            tracking_code = tracking_cache[customer_id]
        else:
            existing_tracking = repo.get_existing_tracking_code(tenant_id, customer_id, today)
            if existing_tracking:
                tracking_code = existing_tracking
            else:
                if date_prefix not in tracking_seq_cache:
                    tracking_seq_cache[date_prefix] = repo.get_next_tracking_sequence(tenant_id, date_prefix)
                else:
                    tracking_seq_cache[date_prefix] += 1
                tracking_code = f"{date_prefix}-{tracking_seq_cache[date_prefix]:03d}"
            tracking_cache[customer_id] = tracking_code

        carton_tag = f"{tenant_short}-{container_number}-{seq:03d}"
        seq += 1

        repo.insert_manifest_items(
            tenant_id,
            [
                {
                    "packing_list_id": pl_id,
                    "description": row["description"],
                    "weight_actual_kg": row.get("weight_actual_kg"),
                    "carton_tag": carton_tag,
                    "tracking_code": tracking_code,
                    "cbm": row.get("cbm") or 0.0,
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
