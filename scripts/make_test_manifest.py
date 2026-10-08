"""Generate a single-row manifest workbook for live notification testing.

The sheet mirrors the layout of a real forwarder export (metadata block above a
two-row header) but contains exactly one consignee — the tester's own contact —
so an import can be run end to end without any real customer being reachable.

Usage:
    python3 scripts/make_test_manifest.py [--out PATH] [--container REF]
"""
import argparse
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font

# The tester's own contact. Never a customer's — see the notification allowlist
# in `15_api_notifications.md` §"Recipient safety".
TEST_CONSIGNEE = "Ifesinachi Ugwuoke"
TEST_PHONE = "08169760253"


def build(path: str, container_ref: str) -> None:
    """Write a one-consignee manifest workbook to `path`."""
    wb = Workbook()
    ws = wb.active
    ws.title = "PACKING LIST"

    today = date.today()
    for row, (label, value) in enumerate(
        [
            ("PARTIAL NO.:", container_ref),
            ("LOADING DATE:", today - timedelta(days=21)),
            ("DEPARTURE DATE:", today - timedelta(days=20)),
            ("ARRIVEL DATE:", today + timedelta(days=3)),
            ("PORT:", "LAGOS"),
        ],
        start=1,
    ):
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
        ws.cell(row=row, column=2, value=value)

    header_row = 7
    headers = [
        "DLVY NO.", "NAME", "CONTACT", "ITEM",
        "QTY CTNS/PKG", "MEAS.", "KG", "BALE NO.", "BALE TYPE",
    ]
    for col, name in enumerate(headers, start=1):
        ws.cell(row=header_row, column=col, value=name).font = Font(bold=True)
    # Second header line, as real exports carry — the parser must skip it.
    for col, unit in enumerate(
        ["", "", "", "", "CTNS/PKGS", "(CBM)", "KG", "", ""], start=1
    ):
        ws.cell(row=header_row + 1, column=col, value=unit)

    rows = [
        (f"{container_ref}-001", TEST_CONSIGNEE, TEST_PHONE,
         "Ladies handbags", "12CTNS", 1.85, 148.0, "", "CARTON"),
        (f"{container_ref}-002", TEST_CONSIGNEE, TEST_PHONE,
         "Cotton fabric rolls", "2BALES", 3.20, 415.5, "B-07", "MASTER BALE"),
    ]
    for offset, values in enumerate(rows):
        for col, value in enumerate(values, start=1):
            ws.cell(row=header_row + 2 + offset, column=col, value=value)

    total_row = header_row + 2 + len(rows)
    ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=6, value=round(sum(r[5] for r in rows), 2))
    ws.cell(row=total_row, column=7, value=round(sum(r[6] for r in rows), 2))

    for col, width in zip("ABCDEFGHI", (14, 22, 16, 26, 14, 10, 10, 12, 14), strict=True):
        ws.column_dimensions[col].width = width

    wb.save(path)
    print(f"Wrote {path}")
    print(f"  container   {container_ref}")
    print(f"  consignee   {TEST_CONSIGNEE} ({TEST_PHONE}) — 1 customer, {len(rows)} items")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="test_manifest.xlsx")
    parser.add_argument("--container", default="TEST001")
    args = parser.parse_args()
    build(args.out, args.container)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
