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
    if result.returncode == 0 and args[0] == "upgrade":
        _apply_app_role_credential()
    sys.exit(result.returncode)


def _apply_app_role_credential() -> None:
    """Re-apply ``logistics_app``'s password from ``APP_DB_PASSWORD``.

    Only after a successful ``upgrade`` — a ``downgrade`` or a read-only
    ``current``/``history`` has no business touching a credential.

    This is the container image's migrate entrypoint (``docker-entrypoint.sh``
    ``migrate`` → here), so this is where Azure and local/CI get the credential.
    The AWS migrate Lambda does the same in ``services/migrate/handler.py``.

    See ``shared.db_credentials.ensure_app_role_password`` for why this cannot
    live in migration 060 alone: Alembic runs a migration once per database, and
    060's effect depends on an environment variable, so an environment that
    applied it before its secret existed can never pick the credential up.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from shared.db_credentials import ensure_app_role_password

    print(f"App role credential: {ensure_app_role_password()}")


if __name__ == "__main__":
    main()
