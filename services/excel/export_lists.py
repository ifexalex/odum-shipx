"""Column specs for the tenant-wide list exports: the invoice list and the container list.

These are what the "Export" button on each list screen downloads: the rows that match the screen's filters, in its
sort order. `balance_ngn` is the database's own generated column (total less paid), so the sheet never subtracts.
"""

from ._tables import Column

BILLING_LIST_COLUMNS: list[Column] = [
    Column("invoice_number", "Invoice Number"),
    Column("customer_name", "Customer"),
    Column("container_number", "Container"),
    Column("billed_at", "Billed At (UTC)", "datetime"),
    Column("status", "Status"),
    Column("total_cbm", "Total CBM", "number"),
    Column("cbm_rate_usd", "CBM Rate (USD)", "money"),
    Column("exchange_rate_ngn", "Dollar Rate (NGN)", "money"),
    Column("subtotal_usd", "Subtotal (USD)", "money"),
    Column("subtotal_ngn", "Subtotal (NGN)", "money"),
    Column("misc_charges_ngn", "Misc Fees (NGN)", "money"),
    Column("carryover_ngn", "Carryover (NGN)", "money"),
    Column("storage_fees_ngn", "Storage Fees (NGN)", "money"),
    Column("credits_applied_ngn", "Credits Applied (NGN)", "money"),
    Column("total_ngn", "Total Due (NGN)", "money"),
    Column("amount_paid_ngn", "Total Paid (NGN)", "money"),
    Column("balance_ngn", "Outstanding (NGN)", "money"),
]

CONTAINER_LIST_COLUMNS: list[Column] = [
    Column("container_number", "Container"),
    Column("status", "Status"),
    Column("vessel_name", "Vessel"),
    Column("voyage_number", "Voyage"),
    Column("shipping_line", "Shipping Line"),
    Column("origin", "Origin"),
    Column("destination", "Destination"),
    Column("ship_date", "Ship Date", "date"),
    Column("estimated_arrival_date", "ETA", "date"),
    Column("actual_arrival_date", "Arrived", "date"),
    Column("packing_list_count", "Packing Lists", "integer"),
    Column("approved_packing_list_count", "Approved Packing Lists", "integer"),
    Column("total_cbm_packed", "CBM Packed", "number"),
    Column("capacity_cbm", "Capacity (CBM)", "number"),
    Column("seal_number", "Seal Number"),
    Column("created_at", "Created At (UTC)", "datetime"),
]

#: A container's tracking events, oldest first: what the "Export" button on the container's tracking tab downloads.
CONTAINER_EVENT_COLUMNS: list[Column] = [
    Column("created_at", "Time (UTC)", "datetime"),
    Column("from_status_label", "From"),
    Column("to_status_label", "To"),
    Column("actor_name", "Updated By"),
    Column("actor_role_label", "Role"),
    Column("notes", "Notes"),
]
