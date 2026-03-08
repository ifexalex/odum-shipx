#!/usr/bin/env python3
"""Run Alembic migrations against the configured database.

Usage:
    python scripts/migrate.py                   # upgrade to head (default)
    python scripts/migrate.py upgrade head      # same as above
    python scripts/migrate.py downgrade -1      # roll back one revision
    python scripts/migrate.py downgrade base    # roll back all revisions
    python scripts/migrate.py current           # show current revision
    python scripts/migrate.py history           # show migration history
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = PROJECT_ROOT / "migrations" / "alembic.ini"


def main() -> None:
    args = sys.argv[1:] or ["upgrade", "head"]
    result = subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI)] + args,
        cwd=PROJECT_ROOT,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
