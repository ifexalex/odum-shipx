# Task 19 — Excel Import/Export Service

## Objective

Implement all Excel export (packing list, manifest, billing) and import (packing list) functionality using `openpyxl` for .xlsx generation and parsing. Exports are generated as .xlsx files, stored in S3, and returned via presigned download URLs.

## Depends On

- Task 06 (shared layer), Task 08 (packing list), Task 09 (manifest), Task 11 (billing)

## Files to Create

```
services/excel/
├── __init__.py
├── handler.py          # Lambda entry point for all export/import routes
├── service.py          # Orchestration: fetch data → generate → upload S3
├── export_packing_list.py   # Packing list .xlsx generator
├── export_manifest.py       # Manifest .xlsx generator
├── export_billing.py        # Billing .xlsx generator
├── import_packing_list.py   # Packing list .xlsx parser + validator
├── repository.py            # Queries to fetch export data
└── models.py                # Request/response models for import/export
```

## Routes

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `/v1/packing-lists/{id}/export` | china_office_staff, tenant_admin, nigeria_office_staff | Export single packing list (`?format=xlsx\|csv\|pdf`) |
| GET | `/v1/manifests/{id}/export` | china_office_staff, tenant_admin, nigeria_office_staff | Export manifest (`?format=xlsx\|csv\|pdf`) |
| GET | `/v1/billing/{id}/export` | tenant_admin, nigeria_office_staff | Export billing (`?format=xlsx\|csv\|pdf`) |
| GET | `/v1/containers/{id}/billing/export` | tenant_admin, nigeria_office_staff | Export all billing for a container (`?format=xlsx\|csv\|pdf`) |
| POST | `/v1/packing-lists/import` | china_office_staff | Import packing list from .xlsx |

## Multi-Format Export

All four export endpoints accept an optional `?format=` query parameter:

| Value | Content-Type | Description |
|---|---|---|
| `xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | Default. Full-featured workbook with summary sheet. |
| `csv` | `text/csv` | Flat CSV, UTF-8 BOM encoded for Excel compatibility. |
| `pdf` | `application/pdf` | Landscape A4, blue header row, alternating row shading (reportlab). |

Invalid `?format=` values return 422 with `VALIDATION_ERROR`. Dependencies: `openpyxl` (xlsx), stdlib `csv` (csv), `reportlab>=4.0` (pdf) — all in `requirements-layer.txt`.

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

1. Client calls `POST /v1/uploads/presigned-url` with `purpose = "packing_list_import"`
2. Client uploads .xlsx to S3
3. Client calls `POST /v1/packing-lists/import` with `{ "container_id": "uuid", "file_key": "s3-key" }`
4. Lambda downloads file from S3, processes, returns result

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
- **Layer deps:** `openpyxl` (xlsx), `reportlab>=4.0` (pdf) in `requirements-layer.txt`; stdlib `csv` for csv output

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
