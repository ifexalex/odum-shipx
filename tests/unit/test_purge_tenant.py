"""Unit tests for scripts/purge_tenant.py's delete ordering.

The ordering is the whole safety story: 26 FKs reference `tenant(id)` with
ON DELETE RESTRICT, so deleting a parent before its children is refused by
Postgres. These assert children always precede their parents.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "purge_tenant", Path(__file__).resolve().parents[2] / "scripts" / "purge_tenant.py"
)
assert _SPEC and _SPEC.loader
purge_tenant = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(purge_tenant)


def _assert_children_first(order: list[str], edges: dict[str, set[str]]) -> None:
    pos = {t: i for i, t in enumerate(order)}
    for child, parents in edges.items():
        for parent in parents:
            assert pos[child] < pos[parent], f"{child} must be deleted before {parent}"


class TestDeletionOrder:
    def test_simple_chain_deletes_children_first(self):
        tables = ["tenant_user", "packing_list", "container"]
        # packing_list -> container, packing_list -> tenant_user
        edges = {"packing_list": {"container", "tenant_user"}}
        order = purge_tenant.deletion_order(tables, edges)
        assert set(order) == set(tables)
        _assert_children_first(order, edges)

    def test_deep_dependency_graph(self):
        tables = ["a", "b", "c", "d"]
        edges = {"d": {"c"}, "c": {"b"}, "b": {"a"}}
        order = purge_tenant.deletion_order(tables, edges)
        assert order == ["d", "c", "b", "a"]

    def test_independent_tables_all_present(self):
        tables = ["x", "y", "z"]
        order = purge_tenant.deletion_order(tables, {})
        assert sorted(order) == ["x", "y", "z"]

    def test_cycle_does_not_hang_and_keeps_every_table(self):
        # A genuine FK cycle can't be ordered — it must still terminate and emit
        # everything, letting the single transaction surface any real violation.
        tables = ["p", "q"]
        edges = {"p": {"q"}, "q": {"p"}}
        order = purge_tenant.deletion_order(tables, edges)
        assert sorted(order) == ["p", "q"]

    def test_self_reference_is_not_a_cycle(self):
        # fk_edges drops self-refs; a table referencing itself must still order.
        order = purge_tenant.deletion_order(["solo"], {})
        assert order == ["solo"]


class TestSpecialTables:
    def test_onboarding_lead_is_not_purged_as_tenant_data(self):
        """A lead outlives the tenant it provisioned — purging reopens it instead."""
        assert "tenant_onboarding_request" in purge_tenant.SPECIAL_TABLES


class TestSafetyDefaults:
    def test_requires_a_target(self, monkeypatch):
        """No --email/--tenant-id must abort before touching the database."""
        monkeypatch.setattr("sys.argv", ["purge_tenant.py"])
        with pytest.raises(SystemExit):
            purge_tenant.main()
