"""Every table that holds a tenant's data, in one list.

Two jobs walk a tenant's data table by table: the offboarding export (``services/scheduled/offboarding_export.py``)
reads all of it, and the 90-day cleanup (``services/scheduled/data_cleanup.py``) deletes all of it. Before this module
each kept its own list, and the cleanup's had fallen behind the schema by about twenty tables, so a tenant with a
payment claim, a warehouse or a staff notification could not be deleted at all.

``TENANT_TABLES`` is in parent-first order: a table comes after every table it references, unless that reference
cascades or is set null on delete. Exporting walks it forwards; deleting walks it backwards. A unit test reads the
migrations and fails if a table is missing from this list (or from ``NOT_TENANT_DATA``) or if the order breaks a
foreign key (``tests/unit/test_tenant_data.py``).
"""

import re
from dataclasses import dataclass, field

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class TenantTable:
    """One table of tenant data and how to find a tenant's rows in it.

    Attributes:
        name: The table.
        via: For a table with no ``tenant_id`` column, ``(foreign_key_column, parent_table)``: its rows belong to the
            tenant that owns the parent row. ``None`` for a table with its own ``tenant_id``.
        omit: Columns left out of the export: secrets and hashes of secrets, which are of no use to the tenant and
            must not leave the database.
        decrypt: Columns stored encrypted with ``shared.encryption``; the export holds their plaintext.
    """

    name: str
    via: tuple[str, str] | None = None
    omit: frozenset[str] = field(default_factory=frozenset)
    decrypt: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Table and column names are interpolated into SQL; they come from this file, never from input.
        names = [self.name, *self.omit, *self.decrypt, *(self.via or ())]
        bad = [n for n in names if not _IDENTIFIER.match(n)]
        if bad:
            raise ValueError(f"not an SQL identifier: {bad}")

    def select_sql(self) -> str:
        """``SELECT`` for this tenant's rows, with one ``%s`` for the tenant id."""
        if self.via is None:
            return f"SELECT * FROM {self.name} WHERE tenant_id = %s"  # noqa: S608 - fixed identifiers, see __post_init__
        column, parent = self.via
        return (
            f"SELECT child.* FROM {self.name} child "  # noqa: S608 - fixed identifiers, see __post_init__
            f"JOIN {parent} parent ON parent.id = child.{column} WHERE parent.tenant_id = %s"
        )

    def delete_sql(self) -> str:
        """``DELETE`` of this tenant's rows, with one ``%(tenant_id)s`` parameter, ``RETURNING 1``."""
        if self.via is None:
            return f"DELETE FROM {self.name} WHERE tenant_id = %(tenant_id)s RETURNING 1"  # noqa: S608 - fixed identifiers
        column, parent = self.via
        return (
            f"DELETE FROM {self.name} WHERE {column} IN "  # noqa: S608 - fixed identifiers, see __post_init__
            f"(SELECT id FROM {parent} WHERE tenant_id = %(tenant_id)s) RETURNING 1"
        )


#: Parent-first. Comments name the references that fix a table's place.
TENANT_TABLES: tuple[TenantTable, ...] = (
    TenantTable("tenant_user"),  # referenced by nearly every table (created_by, actor_id, ...)
    TenantTable("tenant_user_role"),
    TenantTable("tenant_user_activation", omit=frozenset({"token_hash"})),
    TenantTable("tenant_config"),  # secrets inside config_value are removed by the export, see redact_config
    TenantTable("tenant_counter"),
    TenantTable("charge_type"),
    TenantTable("warehouse"),
    TenantTable("notification_template"),
    TenantTable("rate_history"),
    TenantTable("container"),
    TenantTable("container_capacity"),
    TenantTable("container_event"),  # → container
    TenantTable("container_document"),  # → container
    TenantTable("customer"),  # → tenant_user
    TenantTable("customer_invite", omit=frozenset({"token_hash"})),  # → customer
    TenantTable("manifest"),  # → container
    TenantTable("manifest_evidence", via=("manifest_id", "manifest")),
    TenantTable("packing_list"),  # → container, customer, manifest
    TenantTable("packing_list_item", via=("packing_list_id", "packing_list")),
    TenantTable("shipment_tracking"),  # → packing_list_item
    TenantTable("tracking_event", via=("shipment_tracking_id", "shipment_tracking")),
    TenantTable("billing"),  # → customer, container, packing_list
    TenantTable("misc_charge", via=("billing_id", "billing")),
    TenantTable("payment_record"),  # → billing
    TenantTable("payment_claim"),  # → billing, payment_record
    TenantTable("storage_fee_log"),  # → billing, container, misc_charge
    TenantTable("cbm_dispute"),  # → billing, packing_list
    TenantTable("release_note", omit=frozenset({"pickup_code_hash"})),  # → billing, container, release_note
    TenantTable("pickup_record", decrypt=frozenset({"id_number"})),  # → release_note
    TenantTable("carryover_ledger"),  # → billing, release_note
    TenantTable("damage_claim"),  # → container, packing_list
    TenantTable("claim_evidence", via=("damage_claim_id", "damage_claim")),
    TenantTable("refund_request", decrypt=frozenset({"account_number", "account_name"})),  # → billing, damage_claim
    TenantTable("claim_resolution"),  # → damage_claim, refund_request
    TenantTable("billing_credit_application"),  # → billing, refund_request
    TenantTable("missing_item"),  # → manifest, packing_list
    TenantTable("seized_item"),  # → container, packing_list_item
    TenantTable("staff_notification"),
    TenantTable("staff_notification_read"),  # → staff_notification
    TenantTable("announcement_request"),
    TenantTable("notification_log"),  # → notification_log (retries)
    TenantTable("usage_record"),
    TenantTable("audit_log"),
)

#: Tables in the schema that are not a tenant's data, and why. Each still has to be handled when a tenant is deleted
#: if it references the tenant: see ``services/scheduled/data_cleanup.py``.
NOT_TENANT_DATA: dict[str, str] = {
    "tenant": "the tenant row itself: exported separately as tenant.jsonl, deleted last",
    "platform_audit_log": "the platform's record of admin actions; anonymised, not deleted, when the tenant goes",
    "impersonation_session": "the platform's record of support sessions; deleted with the tenant (target is NOT NULL)",
    "platform_settings": "platform-wide settings, no tenant",
    "tenant_onboarding_request": "the platform's sales lead; its tenant_id is set null when the tenant is deleted",
    "tenant_offboarding_export": "the record of this export itself; cascades with the tenant",
}

#: Keys inside ``tenant_config.config_value`` that hold credentials, by config key.
_CONFIG_SECRETS: dict[str, tuple[str, ...]] = {
    "webhook_config": ("secret",),
    "paystack_config": ("secret_key_encrypted",),
}


def redact_config(config_key: str, config_value: object) -> object:
    """``config_value`` without the credentials it holds (the webhook signing secret, the Paystack key)."""
    secrets = _CONFIG_SECRETS.get(config_key)
    if not secrets or not isinstance(config_value, dict):
        return config_value
    return {k: v for k, v in config_value.items() if k not in secrets}


def table(name: str) -> TenantTable:
    """The inventory entry for ``name``."""
    for entry in TENANT_TABLES:
        if entry.name == name:
            return entry
    raise KeyError(name)
