#!/usr/bin/env python3
"""Fill ``tenant_metrics_daily`` for past days (platform audit Phase 1c).

The hourly usage job keeps yesterday and today current; this fills the days before the table existed, from history:
customers, containers, notifications and audit entries by their timestamps, and metered API calls, containers and
storage from ``usage_record``. Re-running is safe: each tenant-day is an upsert.

Usage (inside the network that reaches the database, with the usual ``DATABASE_*`` settings)::

    python3 scripts/backfill_tenant_metrics.py --days 90
"""

import argparse
import sys

from services.scheduled import tenant_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill daily tenant metrics")
    parser.add_argument("--days", type=int, default=90, help="How many complete days back to fill (1–730)")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 730:
        parser.error("--days must be between 1 and 730")
    result = tenant_metrics.backfill(args.days)
    print(f"Wrote {result['metric_rows']} tenant-day rows; {result['metric_errors']} failed (see the log).")
    return 0 if result["metric_errors"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
