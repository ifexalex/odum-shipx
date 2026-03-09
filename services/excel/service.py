"""Orchestration: fetch data → generate file → upload S3 → presigned URL."""
import csv
import io
import logging
import os
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

import boto3

from shared.exceptions import ResourceNotFoundError

from . import repository as repo
from .export_billing import generate_billing_xlsx
from .export_manifest import generate_manifest_xlsx
from .export_packing_list import generate_packing_list_xlsx
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


_BILLING_COLUMNS = [
    "customer_name",
    "container_number",
    "total_ngn",
    "balance_ngn",
    "status",
    "billed_at",
    "created_at",
]


def export_billing(tenant_id: str, billing_id: str, fmt: str = "xlsx") -> dict[str, Any]:
    billing = repo.get_billing_for_export(tenant_id, billing_id)
    if not billing:
        raise ResourceNotFoundError("billing", billing_id)

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

    billing_rows = repo.get_billing_for_container_export(tenant_id, container_id)
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
# Packing list import
# ---------------------------------------------------------------------------


def import_packing_list(
    tenant_id: str,
    container_id: str,
    file_key: str,
    actor_id: str,
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

    return {
        "total_rows": total_rows,
        "imported": imported_count,
        "errors": len(errors),
        "packing_lists_created": packing_lists_created,
        "error_details": errors,
    }
