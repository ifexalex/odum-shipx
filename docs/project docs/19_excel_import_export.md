# Task 19 — Excel Import/Export Service

## Objective

Implement all Excel export (packing list, manifest, billing) and import (packing list) functionality using `openpyxl` for .xlsx generation and parsing. Exports are generated as .xlsx files, stored in S3, and returned via presigned download URLs.

## Depends On

- Task 06 (shared layer), Task 08 (packing list), Task 09 (manifest), Task 11 (billing)

## Files

```
services/excel/
├── __init__.py
├── handler.py               # Lambda entry point for all export/import routes
├── service.py               # Orchestration: fetch data → generate → upload S3
├── export_packing_list.py        # Packing list .xlsx generator
├── export_packing_list_pdf.py    # Branded A4 packing list PDF (reportlab)
├── export_release_note_pdf.py    # Branded A4 release note PDF with QR code (reportlab)
├── export_receipt_pdf.py    # Branded A4 cash receipt PDF with QR code (reportlab)
├── export_manifest.py       # Manifest .xlsx generator
├── export_billing.py        # Billing .xlsx generator
├── import_packing_list.py   # Packing list .xlsx parser + validator (exact header)
├── import_manifest.py       # Manifest .xlsx parser — flexible header-alias matching (Task 040)
├── _import_helpers.py       # Shared parse helpers (positive decimal, date, CBM) used by both importers
├── repository.py            # Queries to fetch export data (incl. release_note_for_pdf)
└── models.py                # Request/response models for import/export
```

## Routes

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `/v1/packing-lists/{id}/export` | china_office_staff, tenant_admin, nigeria_office_staff | Export single packing list (`?format=xlsx\|csv\|pdf`) |
| GET | `/v1/packing-lists/{id}/pdf` | china_office_staff, tenant_admin, nigeria_office_staff, customer (own only) | Branded A4 PDF; 5-min presigned URL; EXPORT audit |
| GET | `/v1/release-notes/{id}/pdf` | nigeria_office_staff, tenant_admin, warehouse_attendant, customer (own only) | Branded A4 PDF with QR code; 5-min presigned URL; EXPORT audit |
| GET | `/v1/payments/{id}/receipt/pdf` | nigeria_office_staff, tenant_admin, customer (own only) | Branded A4 cash-receipt PDF with QR code; 5-min presigned URL; EXPORT audit |
| GET | `/v1/manifests/{id}/export` | china_office_staff, tenant_admin, nigeria_office_staff | Export manifest (`?format=xlsx\|csv\|pdf`) |
| GET | `/v1/billing/{id}/export` | tenant_admin, nigeria_office_staff, customer (own only) | Export billing (`?format=xlsx\|csv\|pdf`) — the `pdf` format doubles as the customer's downloadable invoice |
| GET | `/v1/containers/{id}/billing/export` | tenant_admin, nigeria_office_staff | Export all billing for a container (`?format=xlsx\|csv\|pdf`) |
| POST | `/v1/packing-lists/import/presigned-url` | china_office_staff | Get a cloud-neutral **PUT** presigned URL for an import .xlsx (`content_type` must be the xlsx MIME type); returns `{ upload_url, upload_method, upload_headers, file_key }`. Reused unchanged by the manifest import flow below — there is no second presigned-url endpoint. |
| POST | `/v1/packing-lists/import` | china_office_staff | Import packing list from .xlsx (exact header, pre-existing container + customers required) |
| POST | `/v1/manifests/import` | china_office_staff | Import a China-side freight-forwarder manifest .xlsx (flexible header matching; auto-creates container/customers/packing lists) — see "Manifest Import" below |

### PDF Export Details

**Packing list PDF** (`export_packing_list_pdf.py`):
- Header: tenant `company_display_name` in brand colour
- Meta: Customer, Container, Status, Generated date
- "✓ APPROVED" stamp when `status IN ('approved', 'recorded')`
- Line-item table: Carton Tag | Description | Dispatch kg | Actual kg | CBM | Tracking Code
- Totals row; S3 key `{tenant_id}/exports/{date}/{stem}.pdf`

**Release note PDF** (`export_release_note_pdf.py`):
- Header strip (brand colour): company name left | QR code right (encodes `RELEASE:{reference_number}`)
- Meta: Customer, Phone, Container, Payment Reference, Carton Count, Status, Valid From, plus — only when present on the note — Warehouse (name/address/city/state), Document No. (`physical_document_number`), Invoice No(s). (`packing_list_invoice_numbers`), Cartons Balance, and either "ON CREDIT — granted by {name}" or Amount Paid/Balance Outstanding, plus Receipt No. Field list built by the pure, independently-tested `build_meta_pairs()` helper.
- Signature block: 4 named lines — Customer's Rep, Customer Service Officer, Accounting Officer, Warehouse Attendant (parity with `PrintReleaseNote.tsx`'s HTML signature block; previously 3 generic "Authorized Signature / Date / Name" columns naming no one)
- Footer validity statement + the "goods must be confirmed before leaving" disclaimer (from the reference paper "Goods Release Note" form)
- QR via `reportlab.graphics.barcode.qr.QrCodeWidget` (no extra deps)

**Ground-truth gap fixed (2026-09-13):** `get_release_note_for_pdf`'s query already joined `customer_phone`, `warehouse_name/address/city/state`, `billing_total_ngn/amount_paid_ngn/balance_ngn`, `payment_status`, and `receipt_number`, plus `rn.*` already carried `is_on_credit`/`credit_granted_by_name`/`physical_document_number`/`packing_list_invoice_numbers`/`packages_balance` — but `generate_release_note_pdf` only ever read 7 of the ~20 available fields, silently dropping the rest from the printed document. Same class of bug as the `_fmt_release_note`/`create_split_release_note` gaps fixed the same day in `services/payment_release`. Fixed by reading every joined field, matching the print HTML view's field completeness.

**QR rendering bug fixed (2026-09-13):** `_qr_image()` in both `export_release_note_pdf.py` and `export_receipt_pdf.py` set `.transform` on the `QrCodeWidget` itself — reportlab's `AttrMap` validation rejects that (`AttributeError: Illegal attribute 'transform' in class QrCodeWidget`), so **every call to `generate_release_note_pdf` and `generate_receipt_pdf` has always raised, meaning both PDF exports have never worked in production**. Fixed by setting `.transform` on the enclosing `Drawing` instead (the correct reportlab pattern for scaling a widget within a Drawing). No unit test previously exercised the reportlab call path (mocks stopped at `repo.get_release_note_for_pdf`/`repo.get_payment_for_receipt_pdf`), so this was invisible to the suite; `tests/unit/test_export_release_note_pdf.py` and `tests/unit/test_export_receipt_pdf.py` now render a real PDF end-to-end and assert on the `%PDF` magic bytes.

**Customer ownership**: when role is CUSTOMER, the endpoint fetches the customer_id from `customer.user_id` and returns 404 (never 403) if the record doesn't belong to them.

## Multi-Format Export

All four export endpoints accept an optional `?format=` query parameter:

| Value | Content-Type | Description |
|---|---|---|
| `xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | Default. Full-featured workbook with summary sheet. |
| `csv` | `text/csv` | Flat CSV, UTF-8 BOM encoded for Excel compatibility. |
| `pdf` | `application/pdf` | Landscape A4, blue header row, alternating row shading (reportlab). |

Invalid `?format=` values return 422 with `VALIDATION_ERROR`. Dependencies: `openpyxl` (xlsx), stdlib `csv` (csv), `reportlab>=4.0` (pdf) — bundled in the shared Lambda layer (pyproject `layer` deps).

## Packing List Excel Export (Backend Spec §7.1)

**Filename:** `{tenant_name}_packing_list_{container_number}_{date}.{format}`

**Sheet 1: "Packing List"**

| Column | Header | Data Type | Source |
|---|---|---|---|
| A | Carton Tag | String | packing_list_item.carton_tag |
| B | Tracking Code | String | packing_list_item.tracking_code |
| C | Description | String | packing_list_item.description |
| D | Weight (Dispatch) kg | Decimal | packing_list_item.weight_dispatch_kg |
| E | Weight (Actual) kg | Decimal | packing_list_item.weight_actual_kg |
| F | Length (cm) | Decimal | packing_list_item.length_cm |
| G | Width (cm) | Decimal | packing_list_item.width_cm |
| H | Height (cm) | Decimal | packing_list_item.height_cm |
| I | CBM | Decimal (6dp) | packing_list_item.cbm |
| J | Received Date | Date (YYYY-MM-DD) | packing_list_item.received_date |

**Formatting:**
- Row 1: Bold headers with auto-filter enabled
- Last row: Totals for Weight (D, E), CBM (I), and Carton Count
- Column widths auto-sized

**Sheet 2: "Summary"**

| Row | Content | Source |
|---|---|---|
| 1 | Company Name | tenant.branding_config.company_display_name |
| 2 | Container Number | container.container_number |
| 3 | Customer Name | customer.name |
| 4 | Total Cartons | COUNT(items) |
| 5 | Total Weight (kg) | SUM(weight_actual_kg) |
| 6 | Total CBM | SUM(cbm) |
| 7 | Generated Date | NOW() |

### Implementation

```python
# services/excel/export_packing_list.py
import openpyxl
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter
from io import BytesIO

def generate_packing_list_xlsx(
    tenant_branding: dict,
    container_number: str,
    customer_name: str,
    items: list[dict],
) -> BytesIO:
    """Generate packing list .xlsx and return as BytesIO buffer."""
    wb = openpyxl.Workbook()
    
    # Sheet 1: Packing List
    ws = wb.active
    ws.title = "Packing List"
    
    headers = [
        "Carton Tag", "Tracking Code", "Description",
        "Weight (Dispatch) kg", "Weight (Actual) kg",
        "Length (cm)", "Width (cm)", "Height (cm)",
        "CBM", "Received Date"
    ]
    
    # Bold headers
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
    
    # Data rows
    for row_idx, item in enumerate(items, 2):
        ws.cell(row=row_idx, column=1, value=item["carton_tag"])
        ws.cell(row=row_idx, column=2, value=item["tracking_code"])
        ws.cell(row=row_idx, column=3, value=item["description"])
        ws.cell(row=row_idx, column=4, value=float(item["weight_dispatch_kg"] or 0))
        ws.cell(row=row_idx, column=5, value=float(item["weight_actual_kg"] or 0))
        ws.cell(row=row_idx, column=6, value=float(item["length_cm"] or 0))
        ws.cell(row=row_idx, column=7, value=float(item["width_cm"] or 0))
        ws.cell(row=row_idx, column=8, value=float(item["height_cm"] or 0))
        ws.cell(row=row_idx, column=9, value=float(item["cbm"]))
        ws.cell(row=row_idx, column=10, value=str(item["received_date"]))
    
    # Totals row
    total_row = len(items) + 2
    ws.cell(row=total_row, column=3, value="TOTALS").font = Font(bold=True)
    ws.cell(row=total_row, column=4, value=sum(float(i["weight_dispatch_kg"] or 0) for i in items))
    ws.cell(row=total_row, column=5, value=sum(float(i["weight_actual_kg"] or 0) for i in items))
    ws.cell(row=total_row, column=9, value=sum(float(i["cbm"]) for i in items))
    
    # Auto-filter
    ws.auto_filter.ref = f"A1:J{len(items) + 1}"
    
    # Sheet 2: Summary
    ws_summary = wb.create_sheet("Summary")
    summary_data = [
        ("Company Name", tenant_branding.get("company_display_name", "")),
        ("Container Number", container_number),
        ("Customer Name", customer_name),
        ("Total Cartons", len(items)),
        ("Total Weight (kg)", sum(float(i["weight_actual_kg"] or 0) for i in items)),
        ("Total CBM", sum(float(i["cbm"]) for i in items)),
        ("Generated Date", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")),
    ]
    for row_idx, (label, value) in enumerate(summary_data, 1):
        ws_summary.cell(row=row_idx, column=1, value=label).font = Font(bold=True)
        ws_summary.cell(row=row_idx, column=2, value=value)
    
    # Write to buffer
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
```

## Manifest Excel Export (Backend Spec §7.2)

**Filename:** `{tenant_name}_manifest_{container_number}_{date}.xlsx`

**Sheet 1: "Manifest Summary"**

| Column | Header | Data Type |
|---|---|---|
| A | # | Integer (row number) |
| B | Customer Name | String |
| C | Carton Count | Integer |
| D | Total Weight (kg) | Decimal |
| E | Total CBM | Decimal |
| F | Carton Tags | String (comma-separated) |

**Sheet 2: "All Items"** — flat list of all packing_list_items across all customers for this container, with columns matching the packing list export Sheet 1.

## Billing Excel Export (Backend Spec §7.4)

**Filename:** `{tenant_name}_billing_{container_number}_{date}.xlsx`

| Column | Header | Source |
|---|---|---|
| A | Customer Name | customer.name |
| B | Total CBM | billing.total_cbm |
| C | CBM Rate (USD) | billing.cbm_rate_usd |
| D | Dollar Rate (NGN) | billing.dollar_rate |
| E | Subtotal (USD) | billing.subtotal_usd |
| F | Subtotal (NGN) | billing.subtotal_ngn |
| G | Misc Fees (NGN) | billing.misc_fees_ngn |
| H | Carryover (NGN) | billing.carryover_ngn |
| I | Adjustments (NGN) | billing.adjustments_ngn |
| J | Storage Fees (NGN) | billing.storage_fees_ngn |
| K | Total Due (NGN) | billing.total_due_ngn |
| L | Total Paid (NGN) | billing.total_paid_ngn |
| M | Outstanding (NGN) | billing.outstanding_ngn |
| N | Payment Status | billing.payment_status |

When exporting for an entire container (`GET /containers/{id}/billing/export`), include one row per customer.

**Ground-truth fix (2026-07-19) — customer-facing invoice download.** `GET /v1/billing/{id}/export` was staff-only; the customer portal's post-payment "View invoice" flow (`PaymentSuccess.tsx` → `MyBillingDetail.tsx`) had nowhere to actually download an invoice from — no button existed on the billing-detail page at all. Fixed:
- `export_billing()` now accepts an optional `customer_user_id`; when set (CUSTOMER role), it resolves the caller's own `customer.id` via `get_customer_id_for_user()` and 404s (not 403 — same pattern as `export_packing_list_pdf`) on any mismatch, so a customer can never enumerate or download another customer's invoice.
- `_BILLING_EXPORT_ROLES` (staff-only) stayed as-is for the **container-level** export (`GET /containers/{id}/billing/export`) — that returns every customer sharing the container and must never be customer-facing. A separate `_BILLING_SINGLE_EXPORT_ROLES` adds `customer` only to the single-record route.
- Frontend: `MyBillingDetail.tsx` gained a "Download invoice" button (`?format=pdf`, opens in a new tab per `apiDownloadFile`'s existing PDF handling) in the Invoice breakdown section header. `billingApi.export()`'s type signature was widened from `Exclude<ExportFormat, 'pdf'>` to `ExportFormat` — pdf was already implemented service-side (`_rows_to_pdf`) but never exposed to any frontend caller.

Verified live: real PDF generated and downloaded via the presigned S3 URL (valid single-page PDF, confirmed with `file`); a second customer in the same tenant hitting the same billing ID gets `404 RESOURCE_NOT_FOUND`, not the invoice. Tests: `TestExportBilling` in `tests/unit/test_excel.py` (5 cases — staff export, own-record customer export, cross-customer 404, orphaned-customer-row 404, unknown-billing 404).

**Ground-truth gap found live (2026-09-06) — the downloadable invoice had no breakdown at all.** `_BILLING_COLUMNS` (used by the `csv` and `pdf` export formats — `pdf` being exactly what `MyBillingDetail.tsx`'s "Download invoice" button calls) was a bare 7 columns: `customer_name`, `container_number`, `total_ngn`, `balance_ngn`, `status`, `billed_at`, `created_at`. A customer's official invoice literally said "you owe ₦X, balance ₦Y" with zero itemization — no CBM, no rate, no fees, no total paid. (The `xlsx` format, via `generate_billing_xlsx()`'s separate `_HEADERS`, already had the full breakdown — only the csv/pdf path was stripped down, and pdf is the one customers actually get.) Fixed: widened `_BILLING_COLUMNS` to full parity — `total_cbm`, `cbm_rate_usd`, `exchange_rate_ngn`, `subtotal_ngn`, a new `misc_fees_itemized` computed column, `storage_fees_ngn`, `carryover_ngn`, `total_ngn`, `amount_paid_ngn`, `balance_ngn`, `status`, `billed_at`, `created_at`. `adjustments_ngn` was deliberately left out — it is never populated anywhere in this codebase (CBM dispute resolution rewrites `subtotal_ngn`/`total_ngn` directly instead of recording a delta), so including it would only ever show a misleading, permanently-zero column.

`misc_fees_itemized` (new `services/excel/repository.py::get_misc_charges_for_export()` + `service.py::_misc_fees_itemized()`) renders as `"Customs clearance fee: NGN 5,000.00; Documentation fee: NGN 2,000.00"` — a flat per-row export can't hold a variable-length fee table, but it can still name exactly what each charge is for instead of a bare total, matching the "misc fees" clarity fix across the customer-facing UI (see `frontend/07_domain_modules.md`).

Verified live: downloaded the real PDF via the presigned URL and extracted its text with `pdftotext` — confirmed it now shows `Total Cbm`, `Cbm Rate Usd`, `Exchange Rate Ngn`, `Subtotal Ngn`, the itemized fee string, `Total Ngn`, `Balance Ngn`. Tests: `TestExportBilling::test_invoice_names_each_fee_instead_of_a_bare_total` in `tests/unit/test_excel.py`.

## Packing List Excel Import (Backend Spec §7.3)

**Route:** `POST /v1/packing-lists/import`

### Expected Input Format

`.xlsx` file with a single sheet:

| Column | Header (Row 1) | Required | Validation |
|---|---|---|---|
| A | Customer Name | Yes | Must match existing customer in tenant |
| B | Description | Yes | Non-empty string |
| C | Weight Dispatch (kg) | No | Positive number or empty |
| D | Weight Actual (kg) | No | Positive number or empty |
| E | Length (cm) | No | Positive number or empty |
| F | Width (cm) | No | Positive number or empty |
| G | Height (cm) | No | Positive number or empty |
| H | Received Date | No | Valid date; defaults to today if empty |

### Import Processing Logic

```python
def process_import(tenant_id: str, container_id: str, file_buffer: BytesIO) -> ImportResult:
    """Parse and import packing list from .xlsx."""
    wb = openpyxl.load_workbook(file_buffer, data_only=True)
    ws = wb.active
    
    # 1. Validate header row (case-insensitive)
    expected_headers = ["customer name", "description", "weight dispatch (kg)", 
                        "weight actual (kg)", "length (cm)", "width (cm)", 
                        "height (cm)", "received date"]
    actual_headers = [str(ws.cell(row=1, column=c).value or "").strip().lower() 
                      for c in range(1, 9)]
    if actual_headers != expected_headers:
        raise ValidationError("Header row does not match expected format")
    
    # 2. Pre-fetch all customers for this tenant (for name lookup)
    customers = {c["name"].lower(): c["id"] for c in get_tenant_customers(tenant_id)}
    
    # 3. Process each data row
    errors = []
    items_by_customer_date = defaultdict(list)
    
    for row_idx in range(2, ws.max_row + 1):
        customer_name = str(ws.cell(row=row_idx, column=1).value or "").strip()
        
        # a. Look up customer
        customer_id = customers.get(customer_name.lower())
        if not customer_id:
            errors.append({"row": row_idx, "field": "Customer Name", 
                          "value": customer_name, "error": "Customer not found"})
            continue
        
        # b-c. Validate numeric fields
        # ... (validate positive numbers, parse dates)
        
        # d. Calculate CBM
        # e. Auto-generate carton_tag and tracking_code
        
        # Group by customer + received_date
        key = (customer_id, received_date)
        items_by_customer_date[key].append(item)
    
    # 4. Create packing lists in 'draft' status (one per customer+date group)
    packing_lists_created = 0
    for (customer_id, date), items in items_by_customer_date.items():
        create_packing_list(tenant_id, container_id, customer_id, items)
        packing_lists_created += 1
    
    return ImportResult(
        total_rows=ws.max_row - 1,
        imported=sum(len(items) for items in items_by_customer_date.values()),
        errors=len(errors),
        packing_lists_created=packing_lists_created,
        error_details=errors,
    )
```

### Import Request Flow

1. Client calls `POST /v1/packing-lists/import/presigned-url` with `{ "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }`
2. Lambda validates the content type and returns a cloud-neutral PUT ticket: `{ "upload_url": "...", "upload_method": "PUT", "upload_headers": { "Content-Type": "..." }, "file_key": "{tenant_id}/imports/{uuid}.xlsx" }` (was an S3 POST-policy `{ upload_url, fields }` before 2026-10-05 — see the cloud-portability note in `09_api_manifest.md`)
3. Client **PUTs** the raw file to `upload_url` with the returned `upload_headers` (no multipart form)
4. Client calls `POST /v1/packing-lists/import` with `{ "container_id": "uuid", "file_key": "s3-key" }`
5. Lambda downloads the file from S3, processes it, returns the result

This route was added specifically for this flow — there is no generic `/v1/uploads/presigned-url` with a `purpose` parameter. `POST /v1/uploads/presigned-url` (`services/claims/handler.py`) is a separate, claims-evidence-specific endpoint and isn't usable here (wrong role, wrong S3 prefix, wrong side effect). The import upload is transient and unrecorded: no DB row is created for it, since the file is consumed once by step 4 and never referenced again.

### Import Response

```json
{
  "data": {
    "total_rows": 150,
    "imported": 142,
    "errors": 8,
    "packing_lists_created": 25,
    "error_details": [
      { "row": 15, "field": "Customer Name", "value": "Unknown Corp", "error": "Customer not found" },
      { "row": 47, "field": "Weight Dispatch (kg)", "value": "abc", "error": "Invalid number" }
    ]
  }
}
```

## Manifest Import (Task 040)

**Route:** `POST /v1/manifests/import` (`china_office_staff` — same role as the existing importer, since
manifests originate at the China-loading side). New, parallel sibling to `POST /v1/packing-lists/import`
— that route is unchanged and stays exact-header / pre-existing-records only, for staff filling in ShipX's
own template. This route exists to ingest exports from a China-side freight-forwarder platform as-is,
without requiring the container, customers, or packing lists to already exist in ShipX.

### Why a second importer

Real freight-forwarder manifest exports (e.g. a "PARTIAL NO: STL377" container manifest) don't match the
existing importer's assumptions:

- Container-level fields (PARTIAL NO, LOADING DATE, PORT, ARRIVAL DATE, DEPARTURE DATE) are label:value
  pairs in rows *above* the tabular data, not spreadsheet columns.
- The same source file uses two different column layouts across its own pages/blocks (bale-type goods vs.
  carton/bag goods) — an exact 8-column header check would reject one or both.
- Manifest rows are a bulk quantity under one delivery note ("17CTNS", "3BAGS"), not one row per physical
  carton.
- The container and customers usually don't exist in ShipX yet — the whole point is to bootstrap them.

### Request flow

Identical upload step to the existing importer — reuses `POST /v1/packing-lists/import/presigned-url`
unchanged (same `{tenant_id}/imports/{uuid}.xlsx` S3 prefix). Then:

```
POST /v1/manifests/import
{ "file_key": "s3-key" }
```

No `container_id` in the request — the container is resolved from the manifest's own header metadata
(see below), not passed by the client.

### Header-metadata scan

The parser (`services/excel/import_manifest.py::_scan_header_metadata`) scans the first ~10 rows for
known label:value pairs (case-insensitive), either `"LABEL: value"` in one cell or a label cell followed
by its value in the next cell on the same row:

| Label variants | Container field |
|---|---|
| `PARTIAL NO`, `PARTIAL NO.` | `container_number` (find-or-create key) |
| `LOADING DATE` | `ship_date` |
| `PORT` | `destination` |
| `ARRIVAL DATE` | `estimated_arrival_date` |
| `DEPARTURE DATE` | `departure_date` (new column, migration 040) |

The sheet is also scanned for a free-text caveat note containing the word "hold" (e.g. "goods on hold —
China phone number used") — stored as `hold_reason` and applied to any row detected as on-hold.

Not implemented: the manifest's unlabeled secondary numeric reference (e.g. a bare "4287252" line below
the header) is documented in the schema as mapping to the existing `container.parcel_number`, but there is
no reliable label to scan for it, so it is left null by the parser. Can be added if the tenant clarifies
its exact position/format.

### Flexible column-header resolution

Unlike the existing importer's exact 8-column check, this parser matches an alias table
(`_COLUMN_ALIASES` in `import_manifest.py`) against whatever header row it finds, and re-checks *every*
subsequent row against the same alias table — so a second header row further down the sheet (a layout
switch, as the real source file does) is detected and swapped in automatically instead of being
mis-parsed as data:

| Header aliases (case-insensitive) | Canonical field |
|---|---|
| `dlvy no.`, `dlvy no`, `delivery note no.`, `delivery note no` | `delivery_note_number` |
| `name` | `customer_name` |
| `contact` | `customer_phone` |
| `item`, `description` | `description` |
| `qty`, `ctns/pkg`, `qty ctns/pkg` | `quantity_raw` |
| `meas.`, `meas`, `cbm` | `cbm` |
| `kg`, `weight(kg)` | `weight_actual_kg` |
| `bale no.`, `bale no` | `bale_no` |
| `bale type` | `package_unit` |
| `port` | `delivery_zone` |
| `og no.`, `og no` | `original_receipt_number` |

Alias lookups are whitespace-normalised (lowercased, internal runs collapsed), because real
headers are hand-typed and inconsistently spaced — the genuine STL409 export writes
`DLVY  NO.` with a double space.

Unrecognized columns are ignored; recognized-but-absent columns are left null. A row is only accepted as
the header row if it contains at least one "strong signal" alias (`delivery_note_number`, `customer_name`,
`description`, or `quantity_raw`).

### Quantity / unit parsing

Bulk quantity cells like `"17CTNS"` or `"3BAGS"` are split via `^(\d+)\s*([A-Za-z]+)$` plus a
unit-normalization map:

| Raw unit | Normalized `package_unit` |
|---|---|
| `CTN`, `CTNS`, `CARTON`, `CARTONS` | `carton` |
| `BAG`, `BAGS` | `bag` |
| `BALE`, `BALES` | `bale` |
| `PKG`, `PKGS` | `package` |

Bale-layout rows with no `QTY`/`CTNS-PKG` column default to `quantity=1`, with `package_unit` taken
directly from the `BALE TYPE` column (also normalized against the same map).

Real quantity cells are not always a single clean pair, so the parser scans every `<count><unit>`
run in the cell rather than requiring the whole cell to match:

| Source cell | `quantity` | `package_unit` | `quantity_raw` |
|---|---|---|---|
| `17CTNS` | 17 | `carton` | `17CTNS` |
| `1PALLET(61items)` | 1 | `pallet` | `1PALLET(61items)` |
| `3bags2ctns1pallet` | 6 | `mixed` | `3bags2ctns1pallet` |
| `5` | 5 | *(null — unit comes from another column)* | `5` |

Parenthetical annotations describe what is *inside* a package (`(61items)`) and never the package
count, so they are stripped before matching. `quantity_raw` always keeps the verbatim cell so a
mixed parcel that normalises to `6 / mixed` does not lose what was actually written.

`BALE TYPE` values name a bale *type*, not a distinct unit: `BIG BALE` / `LONG BALE` normalise to
`package_unit = 'bale'` (so "count all bales" queries are correct) while the verbatim value is kept
in `bale_type` (so the big/long distinction, which the trade prices differently, survives).

### Multi-sheet workbooks

Every worksheet is parsed and the rows concatenated. Real exports split the two column layouts into
**separate sheets** for the same container (`Master-BALES` + `Master-CTN GOOD` under one `PARTIAL NO`)
rather than stacking them in one sheet. Each sheet repeats the container header block; metadata is
merged with the first non-empty value winning, and each parsed row is tagged with its `sheet_name`.
A sheet with no recognisable header row (a cover/notes tab) is skipped rather than failing the
import — but if *no* sheet parses, the error is raised so an unreadable file still fails loudly.

### Structural rows

Rows inside the tabular block that carry no customer are skipped silently, not reported as errors:
the second line of a two-row header (`CTNS/PKG` under `QTY`, `(CBM)` under `MEAS.`) and the sheet's
own footer rows (`TOTAL:`, `CLOSE CONTAINER ITEM:`). Counting them as failures told staff records
had been rejected when nothing was wrong.

### Container metadata dates

Header dates are read as the **native Excel date value**, not stringified. Excel stores these as real
date cells; `str()` renders them `2026-07-04 00:00:00`, which matched no accepted format and silently
imported every container date as NULL. String forms (`2026-07-04`, `21-May-2026`, `dd/mm/yyyy`) are
still accepted for exports that emit text.

### On-hold detection

`openpyxl` cell font color is checked per row (`_is_red_font`) — any mapped cell with red font
(`FFFF0000`/`00FF0000` ARGB) sets `on_hold=TRUE`; `hold_reason` is populated from the sheet's own caveat
note if one was found during the header-metadata scan.

### Auto-creation semantics

`services/excel/service.py::process_manifest_import`:

1. **Container**: find-or-create by `container_number` (= PARTIAL NO). Fields (`ship_date`,
   `departure_date`, `estimated_arrival_date`, `destination`, `parcel_number`) are set **only at
   creation** — re-importing against an existing container never overwrites hand-edited fields.
2. **Customer**: find-or-create per row, matched by normalized phone number first (digits only, `+`
   preserved if present), falling back to exact (case-insensitive) name match when phone is missing/blank.
   Name suffixes seen in source data (e.g. `"(GQL)"`, `"(JF)"`) are imported as-is, embedded in the name —
   not modeled as a separate field.
3. **Packing list**: find-or-create for `(customer, container)` — same one-per-customer-per-container
   semantics the schema already enforces. Lands in `status = 'draft'`, same as the existing importer.
4. **Item dedupe**: keyed on `(delivery_note_number, bale_no)` *within* a packing list. A row matching
   both is skipped and counted in `items_skipped_duplicate` rather than re-inserted — this is what makes
   re-uploading the same file idempotent. The bale number is part of the key, not decoration: one
   delivery note routinely covers several physical bales, each its own row with its own bale number and
   weight (in the real STL409 export, `HM(UNIQUEWEARS)` has bales 5, 4 and 3 all under delivery note
   `0079283`). Keying on the delivery note alone treated those as re-imports of a single parcel and
   dropped all but the first — losing real cargo on the very first import. Carton/bag rows carry no bale
   number, so there the delivery note alone is the key (matched with `IS NOT DISTINCT FROM`).
5. `carton_tag`/`tracking_code` are auto-generated using the exact same sequence pattern as the existing
   importer (`{tenant_short}-{container_number}-{seq}` / `{tenant_short}-TRK-{yyyymmdd}-{seq}`) — the
   source data has no natural per-carton tag to reuse.

### Response

```json
{
  "data": {
    "total_rows": 4,
    "imported": 4,
    "errors": 0,
    "containers_created": 1,
    "customers_created": 4,
    "packing_lists_created": 4,
    "items_created": 4,
    "items_skipped_duplicate": 0,
    "error_details": []
  }
}
```

Re-uploading the identical file returns `items_created: 0`, `items_skipped_duplicate` equal to the
original `items_created`, and zero `containers_created`/`customers_created`/`packing_lists_created`.

**Auto-issued account invites (migration 042, 2026-08-28):** manifest import creates customer rows with
only `name` + `phone` — no way to log in. After the row loop, `process_manifest_import` calls
`tenant_management.service.issue_customer_invite` for every customer id in `newly_created_customer_ids`
(populated only when `repo.create_customer` ran — never for a phone/name match against an existing
customer, who may already have a login). Best-effort, same posture as `record_usage`: a notification-side
failure is caught and logged, never fails the import response. See
`07_api_tenant_management.md` §"Customer Account-Creation Invites" for the invite lifecycle. Phone
normalisation (`shared/phone.py::normalize_phone`, replacing the old excel-only `_normalize_phone`) also
moved earlier in this same change — `dial_code_for_country(repo.get_tenant_destination_country(tenant_id))`
is resolved once per import and applied to every row's phone before the find-or-create lookup, so
`08012345678` and `+2348012345678` in the same manifest converge on one customer.

### New schema fields powering this (migration 040 — see `05a_database_schema_core.md`)

`container.departure_date`; `packing_list_item.delivery_note_number`, `.quantity`, `.package_unit`,
`.bale_no`, `.original_receipt_number`, `.delivery_zone`, `.on_hold`, `.hold_reason`. All
nullable/defaulted — no impact on the existing importer, manual packing-list flows, or any pre-existing
row.

**Naming note (2026-08-23):** the "OG NO." manifest column and its field were originally named
`supplier_reference` on the mistaken assumption it referred to the goods' supplier. The source
packing-list document spells this out as "ORIGINAL RECEIPT NUMBER" — a per-parcel receipt reference,
unrelated to any supplier. Renamed to `original_receipt_number` before this migration was committed, to
keep field names aligned with the actual freight/logistics terminology used in the source documents
(consistency was an explicit ask, not just a preference) and to avoid representing the wrong concept
under a misleading name. `package_unit` and `delivery_zone` were deliberately **not** renamed to the
source's literal `bale_type`/`port`: `package_unit` also holds non-bale values (`carton`, `bag`) parsed
from the other column layout's `QTY` cell, so `bale_type` would be inaccurate for most rows; `delivery_zone`
avoids colliding with `container.destination`, which the source also calls "port," at a coarser
granularity (LAGOS vs. LAGOS-ISLAND/LAGOS-TRADE FAIR).

## S3 Storage for Exports

Generated .xlsx files are stored at:
```
{tenant_id}/exports/{date}/{filename}.xlsx
```

The handler returns a presigned download URL (valid for 1 hour).

### Export Response

```json
{
  "data": {
    "filename": "AcmeShipping_packing_list_MSKU123_CustomerA_20260301.xlsx",
    "download_url": "https://logistics-assets.s3.eu-west-1.amazonaws.com/...",
    "expires_at": "2026-03-01T11:30:00Z",
    "file_size_bytes": 15234
  }
}
```

## Models (`services/excel/models.py`)

```python
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
```

## Lambda Configuration

- **Memory:** 512MB (openpyxl can be memory-intensive for large files)
- **Timeout:** 60s (import may process hundreds of rows)
- **VPC:** Yes (needs DB access for customer lookup + packing list creation)
- **Layer deps:** `openpyxl` (xlsx), `reportlab>=4.0` (pdf) in the shared Lambda layer; stdlib `csv` for csv output

## Acceptance Criteria

- [x] Packing list export generates correct 2-sheet .xlsx matching spec §7.1
- [x] Manifest export generates correct 2-sheet .xlsx matching spec §7.2
- [x] Billing export generates correct .xlsx matching spec §7.4 (14 columns)
- [x] Container-level billing export includes one row per customer
- [x] Headers are bold with auto-filter enabled
- [x] Summary/totals rows calculated correctly
- [x] Tenant branding (company name) included in summary sheet
- [x] Files uploaded to tenant-scoped S3 prefix
- [x] Presigned download URL returned (valid 1 hour)
- [x] Packing list import validates headers (case-insensitive)
- [x] Import looks up customers by name within tenant scope
- [x] Import rejects rows with unknown customers and invalid numbers
- [x] Import groups items by customer + date into separate packing lists
- [x] Import creates packing lists in 'draft' status
- [x] Import returns detailed error report with row numbers
- [x] openpyxl added to Lambda layer dependencies
- [x] Manifest import (Task 040): header-metadata scan, flexible column-alias matching across two
      observed layouts, quantity/unit parsing, delivery-note dedupe, auto-creation of container/customer/
      packing list without overwriting existing container fields on re-import — verified live end-to-end
      against the real local stack (see "Manifest Import" section above)
- [x] Manifest import auto-issues a customer account-creation invite for every newly created customer
      (never matched ones), best-effort — see "Manifest Import" section above and
      `07_api_tenant_management.md` §"Customer Account-Creation Invites"
- [x] Phone normalisation moved to `shared/phone.py` and applied before the customer find-or-create
      lookup, so local (`08012345678`) and international (`+2348012345678`) forms of the same number in
      one manifest converge on a single customer

## Implementation notes / ground-truth gaps found

**`packing_list.reference` was never set by `services/excel/repository.py::create_packing_list` (used by
both the existing packing-list importer and the new manifest importer).** Migration 031 added
`packing_list.reference` as `NOT NULL` with a per-tenant daily-counter format (`PL-YYYYMMDD-NNN`), but only
`services/packing_list/repository.py::create_packing_list` (the manual create-packing-list flow) was ever
updated to generate and supply it. `services/excel/repository.py::create_packing_list` still inserted
without a `reference` value, so **any real (non-mocked) run of `POST /v1/packing-lists/import` would have
hit a `NotNullViolation` and failed** — masked because the unit test suite mocks the repository layer.
Found live while verifying the new manifest importer end-to-end (Task 040's first live test run crashed on
this exact constraint). Fixed by adding `services/excel/repository.py::get_next_pl_reference` (mirrors the
`services/packing_list` implementation) and wiring it into both `import_packing_list()`'s and
`process_manifest_import()`'s `create_packing_list` calls. Confirmed fixed via a live run of the *existing*
importer post-fix (`ShipX_API.postman_collection.json` unaffected — no wire-format change, `reference` was
already a documented response field via `packing_list.*`).

**Ground-truth gap found while auditing log coverage (2026-09-07):** `import_packing_list` and `process_manifest_import` — both bulk-create containers/customers/packing lists/cartons in a single call — had no `log_audit()` call at all, so goods entering the system through either import path left zero trail in the tenant's audit log. Both now write **one summary entry per import** (not one per row — a single import can create dozens of records), `entity_type="packing_list"`/`"manifest"`, recording counts (containers/customers/packing lists/items created, errors, source file key). Full account in `07_api_tenant_management.md`'s "Tenant Activity Log" section.
