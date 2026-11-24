"""Fail CI when unit-test line coverage of a money service falls below its floor (audit OPS-03).

Coverage was reported (Codecov, when a token is set) but never enforced, so a change could delete the tests of the
code that moves money and still pass. The floors live in ``pyproject.toml`` under ``[tool.shipx.coverage-floors]``:
one line-coverage percentage per directory, set at the level the directory had when the floor was introduced. Raise
a floor when coverage has risen (this script says when); never lower one to make a change pass.

Run after ``pytest --cov=services --cov=shared --cov-report=xml``::

    uv run python scripts/check_coverage.py coverage.xml
"""

import argparse
import sys
import tomllib
import xml.etree.ElementTree as ET  # noqa: S405 - reads our own coverage report, not untrusted input
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Coverage this far above a floor is worth raising the floor for.
RAISE_HINT_POINTS = 1.0


@dataclass(frozen=True)
class Result:
    directory: str
    covered: int
    total: int
    floor: float

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.percent >= self.floor


def load_floors(pyproject: Path = ROOT / "pyproject.toml") -> dict[str, float]:
    """The floors from ``[tool.shipx.coverage-floors]``: directory → minimum line coverage, in percent."""
    with pyproject.open("rb") as f:
        floors = tomllib.load(f)["tool"]["shipx"]["coverage-floors"]
    return {str(directory).rstrip("/"): float(floor) for directory, floor in floors.items()}


def _file_paths(report: ET.Element) -> list[tuple[str, ET.Element]]:
    """Every measured file as a repository-relative path, with its ``<class>`` element.

    coverage.py names files relative to the ``<source>`` they were found under (``billing/service.py`` for
    ``--cov=services``), so the source root is put back in front to get ``services/billing/service.py``.
    """
    sources = [Path(s.text or "") for s in report.iter("source")]
    files = []
    for cls in report.iter("class"):
        name = cls.get("filename", "")
        for source in sources:
            candidate = source / name
            if candidate.exists():
                try:
                    files.append((candidate.resolve().relative_to(ROOT).as_posix(), cls))
                except ValueError:
                    files.append((candidate.as_posix(), cls))
                break
        else:
            files.append((name, cls))
    return files


def measure(report_path: Path, floors: dict[str, float]) -> list[Result]:
    """Line coverage of each floored directory, from a Cobertura XML report."""
    report = ET.parse(report_path).getroot()  # noqa: S314 - our own report
    files = _file_paths(report)
    results = []
    for directory, floor in floors.items():
        covered = total = 0
        for path, cls in files:
            if path.startswith(f"{directory}/"):
                for line in cls.iter("line"):
                    total += 1
                    covered += int(line.get("hits", "0")) > 0
        results.append(Result(directory, covered, total, floor))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="Cobertura XML from pytest --cov-report=xml")
    args = parser.parse_args(argv)

    results = measure(args.report, load_floors())
    failed = False
    for r in results:
        if r.total == 0:
            # A directory with no measured lines means the report or the floor is wrong (renamed, not measured):
            # passing silently would switch the floor off.
            print(f"FAIL  {r.directory}: no lines measured. Is it under --cov, and does the directory still exist?")
            failed = True
        elif not r.passed:
            print(f"FAIL  {r.directory}: {r.percent:.1f}% < floor {r.floor:.1f}% ({r.covered}/{r.total} lines)")
            failed = True
        else:
            hint = (
                f"  -> raise the floor to {int(r.percent * 10) / 10:.1f} in pyproject.toml"
                if r.percent - r.floor >= RAISE_HINT_POINTS
                else ""
            )
            print(f"ok    {r.directory}: {r.percent:.1f}% >= floor {r.floor:.1f}% ({r.covered}/{r.total} lines){hint}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
