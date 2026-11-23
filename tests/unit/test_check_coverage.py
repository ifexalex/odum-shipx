"""The coverage floor check CI runs after the unit tests (scripts/check_coverage.py, audit OPS-03)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_coverage", ROOT / "scripts" / "check_coverage.py")
assert _spec and _spec.loader
check_coverage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_coverage)


def _report(tmp_path: Path, files: dict[tuple[str, str], tuple[int, int]]) -> Path:
    """A Cobertura report. ``files`` maps (source root, file under it) to (covered lines, total lines)."""
    sources = sorted({root for root, _ in files})
    classes = []
    for (_root, name), (covered, total) in files.items():
        lines = "".join(f'<line number="{i}" hits="{1 if i <= covered else 0}"/>' for i in range(1, total + 1))
        classes.append(f'<class name="{name}" filename="{name}"><lines>{lines}</lines></class>')
    xml = (
        "<coverage><sources>"
        + "".join(f"<source>{ROOT / s}</source>" for s in sources)
        + "</sources><packages><package><classes>"
        + "".join(classes)
        + "</classes></package></packages></coverage>"
    )
    path = tmp_path / "coverage.xml"
    path.write_text(xml)
    return path


FLOORS = {"services/billing": 50.0, "services/refunds": 40.0}


def _run(tmp_path, files, monkeypatch, capsys, floors=FLOORS):
    monkeypatch.setattr(check_coverage, "load_floors", lambda: floors)
    code = check_coverage.main([str(_report(tmp_path, files))])
    return code, capsys.readouterr().out


def test_coverage_at_or_above_every_floor_passes(tmp_path, monkeypatch, capsys):
    code, out = _run(
        tmp_path,
        {("services", "billing/service.py"): (50, 100), ("services", "refunds/service.py"): (9, 10)},
        monkeypatch,
        capsys,
    )
    assert code == 0 and "ok    services/billing: 50.0%" in out


def test_coverage_below_a_floor_fails_ci(tmp_path, monkeypatch, capsys):
    code, out = _run(
        tmp_path,
        {("services", "billing/service.py"): (49, 100), ("services", "refunds/service.py"): (9, 10)},
        monkeypatch,
        capsys,
    )
    assert code == 1 and "FAIL  services/billing: 49.0% < floor 50.0%" in out


def test_a_floored_directory_with_nothing_measured_fails_rather_than_passing_silently(tmp_path, monkeypatch, capsys):
    code, out = _run(tmp_path, {("services", "billing/service.py"): (90, 100)}, monkeypatch, capsys)
    assert code == 1 and "FAIL  services/refunds: no lines measured" in out


def test_a_shared_file_with_a_similar_name_does_not_count_toward_the_service(tmp_path, monkeypatch, capsys):
    # shared/billing_money.py is reported as "billing_money.py" under the shared source; it is not services/billing.
    code, out = _run(
        tmp_path,
        {("services", "billing/service.py"): (10, 100), ("shared", "billing_money.py"): (100, 100)},
        monkeypatch,
        capsys,
        floors={"services/billing": 50.0},
    )
    assert code == 1 and "10.0%" in out


def test_it_says_when_a_floor_can_be_raised(tmp_path, monkeypatch, capsys):
    code, out = _run(
        tmp_path,
        {("services", "billing/service.py"): (62, 100), ("services", "refunds/service.py"): (81, 200)},
        monkeypatch,
        capsys,
    )
    assert code == 0
    assert "raise the floor to 62.0" in out
    assert "services/refunds: 40.5%" in out and "raise the floor to 40" not in out  # half a point: not worth it


def test_the_money_services_have_floors_in_pyproject():
    floors = check_coverage.load_floors()
    assert set(floors) >= {"services/billing", "services/payment_release", "services/refunds"}
    assert all(0 < floor <= 100 for floor in floors.values())


@pytest.mark.parametrize("workflow", [".github/workflows/ci.yml"])
def test_ci_runs_the_check_on_the_unit_test_report(workflow):
    text = (ROOT / workflow).read_text()
    unit = text.index("--cov-report=xml")
    check = text.index("scripts/check_coverage.py coverage.xml")
    assert unit < check
