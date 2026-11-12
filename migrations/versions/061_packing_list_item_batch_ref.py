"""061 — group identically-keyed packing-list items with a batch reference.

Staff receiving 100 cartons of one size had to key 100 line items. They can now
enter the dimensions once and set a quantity, and the server expands that into
the same 100 rows it would have got by hand. `batch_ref` is what ties those rows
back together afterwards.

Why expand into rows instead of storing `quantity = 100`
--------------------------------------------------------
`packing_list_item.quantity` already exists and already means "this row is N
packages" — migration 040 introduced it for the Excel manifest import, and
`services/manifest/repository.py` counts packages with
``SUM(COALESCE(pli.quantity, 1))``.

But **CBM is never multiplied by quantity anywhere in the codebase.** Every
consumer does a plain ``SUM(pli.cbm)``: billing, manifest totals, tracking,
payment_release, packing_list. That works for the import path because the
forwarder's "Meas." column is read straight off the sheet, where the figure is
the line total.

Manual entry is the opposite: CBM is *computed from the dimensions keyed in*, so
it is per package. A manually-keyed row carrying ``quantity = 100`` and a
per-package CBM would be billed as **one** carton. Expanding into 100 rows keeps
every existing query correct without touching one of them — each row carries its
own CBM and its own carton_tag, exactly as if a person had typed it.

It also keeps `quantity` meaning one thing. Expanded rows leave it at its
default, so package counts stay right: 100 rows x COALESCE(NULL, 1) = 100.

What batch_ref is for
---------------------
A safeguard, not decoration. The risk in letting someone type "100" is that they
type it wrongly, or that the packages were not actually identical. Grouping the
rows means that mistake is undone in one action instead of ninety-nine
deletions, and the UI can show "100 identical cartons" rather than a wall of
near-duplicate lines.

Nullable, with no backfill: every row that exists today was keyed or imported
individually and belongs to no batch, which is exactly what NULL says.
"""

import sqlalchemy as sa
from alembic import op

revision = "061"
down_revision = "060"


def upgrade() -> None:
    op.add_column(
        "packing_list_item",
        sa.Column(
            "batch_ref",
            sa.dialects.postgresql.UUID(as_uuid=False),
            nullable=True,
            comment=(
                "Groups rows expanded from one quantity entry. NULL for rows keyed or "
                "imported individually. Shared by every row of one batch so the group can "
                "be shown together and removed in one action."
            ),
        ),
    )
    # Partial: only batched rows are ever looked up this way, and they are the
    # minority, so the index stays small.
    op.create_index(
        "ix_packing_list_item_batch_ref",
        "packing_list_item",
        ["packing_list_id", "batch_ref"],
        postgresql_where=sa.text("batch_ref IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the grouping. The expanded rows remain — they are ordinary items.

    Losing batch_ref costs the ability to show or remove them as a group; it
    does not lose cargo data, because each row already stands on its own with
    its own carton_tag and CBM. That is the point of having expanded them.
    """
    op.drop_index("ix_packing_list_item_batch_ref", table_name="packing_list_item")
    op.drop_column("packing_list_item", "batch_ref")
