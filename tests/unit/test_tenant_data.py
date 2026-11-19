"""The tenant table inventory (`shared/tenant_data.py`) against the schema the migrations build.

The export reads every table in the inventory and the cleanup deletes from every one, in reverse. A table the
inventory misses is data the tenant never gets back and the cleanup cannot delete (a foreign key blocks it); an order
that breaks a foreign key fails the deletion halfway. Both are checked here from the migration sources, so they hold
without a database.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from shared import tenant_data
from shared.tenant_data import NOT_TENANT_DATA, TENANT_TABLES, TenantTable

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


@dataclass(frozen=True)
class ForeignKey:
    table: str
    column: str
    parent: str
    on_delete: str  # "" when not stated (NO ACTION)


@dataclass
class Schema:
    columns: dict[str, set[str]]
    foreign_keys: list[ForeignKey]


def _upgrade_sql(path: Path) -> list[str]:
    """The SQL strings in a migration's upgrade(). f-strings (generated loops) are skipped."""
    tree = ast.parse(path.read_text())
    upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
    sql: list[str] = []
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            # Keep the constant parts: a CREATE TABLE with an interpolated predicate still names its columns.
            sql.append("".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)))
    return sql


def _split_top_level(body: str) -> list[str]:
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


_REFERENCES = re.compile(
    r"REFERENCES\s+(\w+)\s*(?:\([^)]*\))?(?:\s+ON\s+DELETE\s+(CASCADE|SET\s+NULL|RESTRICT|NO\s+ACTION))?", re.I
)


def _column_fk(table: str, definition: str) -> ForeignKey | None:
    ref = _REFERENCES.search(definition)
    if not ref:
        return None
    named = re.match(r"(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\((\w+)\)", definition, re.I)
    column = named.group(1) if named else definition.split()[0]
    return ForeignKey(table, column.lower(), ref.group(1).lower(), re.sub(r"\s+", " ", (ref.group(2) or "").upper()))


def _schema() -> Schema:
    columns: dict[str, set[str]] = {}
    fks: list[ForeignKey] = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.py")):
        for sql in _upgrade_sql(path):
            for statement in sql.split(";"):
                text = statement.strip()
                create = re.match(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*)\)\s*$", text, re.S | re.I)
                if create:
                    table = create.group(1).lower()
                    columns[table] = set()
                    for definition in _split_top_level(create.group(2)):
                        first = definition.split()[0].lower()
                        if first not in {"primary", "unique", "check", "constraint", "foreign", "exclude"}:
                            columns[table].add(first)
                        fk = _column_fk(table, definition)
                        if fk:
                            fks.append(fk)
                    continue
                alter = re.match(r"ALTER TABLE (?:IF EXISTS )?(?:ONLY )?(\w+)\s+(.*)$", text, re.S | re.I)
                if alter:
                    table = alter.group(1).lower()
                    for action in _split_top_level(alter.group(2)):
                        add_col = re.match(r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+(.*)$", action, re.S | re.I)
                        if add_col:
                            columns.setdefault(table, set()).add(add_col.group(1).lower())
                            fk = _column_fk(table, f"{add_col.group(1)} {add_col.group(2)}")
                            if fk:
                                fks.append(fk)
                            continue
                        add_fk = re.match(r"ADD (CONSTRAINT \w+ )?FOREIGN KEY.*$", action, re.S | re.I)
                        if add_fk:
                            fk = _column_fk(table, action[4:])
                            if fk:
                                fks.append(fk)
                        rename = re.match(r"RENAME TO (\w+)", action, re.I)
                        if rename:
                            columns[rename.group(1).lower()] = columns.pop(table, set())
                    continue
                drop = re.match(r"DROP TABLE (?:IF EXISTS )?(\w+)", text, re.I)
                if drop:
                    columns.pop(drop.group(1).lower(), None)
    return Schema(columns, [fk for fk in fks if fk.table in columns and fk.parent in columns])


SCHEMA = _schema()
ORDER = {entry.name: i for i, entry in enumerate(TENANT_TABLES)}


class TestTheParserReadsTheSchema:
    """Guards the guard: if parsing quietly found nothing, every check below would pass."""

    def test_it_finds_the_core_tables_and_their_keys(self):
        assert {"tenant", "billing", "packing_list_item", "release_note"} <= set(SCHEMA.columns)
        assert "tenant_id" in SCHEMA.columns["billing"] and "tenant_id" not in SCHEMA.columns["packing_list_item"]
        assert ForeignKey("packing_list_item", "packing_list_id", "packing_list", "CASCADE") in SCHEMA.foreign_keys
        assert len(SCHEMA.foreign_keys) > 100

    def test_it_sees_columns_added_after_a_table_was_created(self):
        assert "pickup_code_hash" in SCHEMA.columns["release_note"]  # migration 065
        assert "credit_applied_ngn" in SCHEMA.columns["refund_request"]  # migration 066
        assert any(fk.table == "refund_request" and fk.parent == "damage_claim" for fk in SCHEMA.foreign_keys)  # 009


class TestEveryTableIsAccountedFor:
    def test_every_table_is_tenant_data_or_has_a_reason_not_to_be(self):
        listed = set(ORDER) | set(NOT_TENANT_DATA)
        assert set(SCHEMA.columns) - listed == set(), "add the new table to shared/tenant_data.py"
        assert listed - set(SCHEMA.columns) == set(), "the inventory names a table the migrations do not create"

    def test_no_table_is_listed_twice(self):
        assert len(ORDER) == len(TENANT_TABLES)
        assert not set(ORDER) & set(NOT_TENANT_DATA)

    @pytest.mark.parametrize("entry", [e for e in TENANT_TABLES if e.via is None], ids=lambda e: e.name)
    def test_a_table_read_by_tenant_id_has_that_column(self, entry):
        assert "tenant_id" in SCHEMA.columns[entry.name]

    @pytest.mark.parametrize("entry", [e for e in TENANT_TABLES if e.via is not None], ids=lambda e: e.name)
    def test_a_table_read_through_its_parent_has_that_key_and_the_parent_has_tenant_id(self, entry):
        column, parent = entry.via
        assert "tenant_id" not in SCHEMA.columns[entry.name]
        assert any(fk.table == entry.name and fk.column == column and fk.parent == parent for fk in SCHEMA.foreign_keys)
        assert "tenant_id" in SCHEMA.columns[parent] and ORDER[parent] < ORDER[entry.name]

    def test_every_table_that_references_a_tenant_is_handled(self):
        # The cleanup deletes the tenant row last; anything still pointing at it without a cascade would block that.
        blockers = {
            fk.table for fk in SCHEMA.foreign_keys if fk.parent == "tenant" and fk.on_delete not in {"CASCADE", "SET NULL"}
        }
        assert blockers <= set(ORDER) | {"impersonation_session", "platform_audit_log"}

    @pytest.mark.parametrize("entry", [e for e in TENANT_TABLES if e.omit or e.decrypt], ids=lambda e: e.name)
    def test_columns_named_for_omission_or_decryption_exist(self, entry):
        assert entry.omit | entry.decrypt <= SCHEMA.columns[entry.name]


class TestTheOrderKeepsForeignKeys:
    def test_parents_come_before_children_so_deleting_in_reverse_never_breaks_a_key(self):
        broken = [
            f"{fk.table}.{fk.column} → {fk.parent}"
            for fk in SCHEMA.foreign_keys
            if fk.table in ORDER
            and fk.parent in ORDER
            and fk.table != fk.parent
            and fk.on_delete not in {"CASCADE", "SET NULL"}
            and ORDER[fk.parent] > ORDER[fk.table]
        ]
        assert broken == []


class TestSql:
    def test_a_direct_table_is_read_and_deleted_by_tenant_id(self):
        entry = tenant_data.table("billing")
        assert entry.select_sql() == "SELECT * FROM billing WHERE tenant_id = %s"
        assert entry.delete_sql() == "DELETE FROM billing WHERE tenant_id = %(tenant_id)s RETURNING 1"

    def test_a_child_table_is_reached_through_its_parent(self):
        entry = tenant_data.table("packing_list_item")
        assert entry.select_sql() == (
            "SELECT child.* FROM packing_list_item child JOIN packing_list parent ON parent.id = child.packing_list_id "
            "WHERE parent.tenant_id = %s"
        )
        assert entry.delete_sql() == (
            "DELETE FROM packing_list_item WHERE packing_list_id IN "
            "(SELECT id FROM packing_list WHERE tenant_id = %(tenant_id)s) RETURNING 1"
        )

    @pytest.mark.parametrize("name", ["billing; DROP TABLE tenant", "Billing", "1table", "a-b"])
    def test_only_plain_identifiers_are_accepted(self, name):
        with pytest.raises(ValueError):
            TenantTable(name)

    def test_secrets_in_tenant_config_are_removed(self):
        assert tenant_data.redact_config("webhook_config", {"url": "https://x", "secret": "s"}) == {"url": "https://x"}
        assert tenant_data.redact_config("paystack_config", {"last4": "1234", "secret_key_encrypted": "e"}) == {"last4": "1234"}
        assert tenant_data.redact_config("branding", {"primary_color": "#000"}) == {"primary_color": "#000"}
        assert tenant_data.redact_config("webhook_config", "not a dict") == "not a dict"
