"""One list of platform audit action names, shared by the backend and the console (audit PA-05).

Before 2026-11-28 the console's audit filter offered ``IMPERSONATION_STARTED``, ``IMPERSONATION_ENDED`` and
``PLAN_UPDATED``, which the backend never writes, so those filters always came back empty.
"""

import pathlib
import re

from shared.platform_audit import PlatformAuditAction

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_LIST = ROOT / "frontend" / "src" / "api" / "platformAuditActions.ts"
_CALL_RE = re.compile(r"insert_platform_audit\(\s*action=([^\n]+)", re.MULTILINE)
_LITERAL_RE = re.compile(r'"([A-Z_]+)"')


def _written_actions() -> set[str]:
    written: set[str] = set()
    for path in [*(ROOT / "services").rglob("*.py"), *(ROOT / "shared").rglob("*.py")]:
        for match in _CALL_RE.finditer(path.read_text()):
            written.update(_LITERAL_RE.findall(match.group(1)))
    return written


def test_every_action_the_code_writes_is_listed():
    written = _written_actions()
    assert written, "no insert_platform_audit(action=...) calls were found; the scan is broken"
    assert written <= {a.value for a in PlatformAuditAction}


def test_every_listed_action_is_written_somewhere():
    assert {a.value for a in PlatformAuditAction} <= _written_actions()


def test_the_console_offers_exactly_the_listed_actions():
    offered = set(re.findall(r"'([A-Z_]+)'", FRONTEND_LIST.read_text()))
    assert offered == {a.value for a in PlatformAuditAction}
