"""What counts as a staff seat against a plan's ``users`` limit.

One definition for every place that counts seats: the quota check on staff creation, the tenant's own plan page, the
platform tenant list, the platform Usage tab and the platform dashboard. Before 2026-11-28 (audit PA-03) the three
platform views counted every active ``tenant_user``, customer portal accounts included, while the quota check left them
out, so the platform showed false "Over quota" badges and different numbers from the tenant's own page.
"""

import re

_ALIAS_RE = re.compile(r"[a-z_][a-z0-9_]*")


def staff_seat_condition(alias: str = "tenant_user") -> str:
    """Return the SQL condition that a ``tenant_user`` row occupies a staff seat.

    A seat is an active user holding any staff role: a primary role other than ``customer``, or a staff role among
    their assigned roles (``tenant_user_role``), so a multi-role user whose primary role is ``customer`` still counts
    (permissioning Phase 2, #195). An ``EXISTS`` rather than a join, so a user with several roles counts once and
    callers need no ``DISTINCT``. The result is a fixed SQL fragment with no user input in it; ``alias`` is the table
    name or alias the caller's query uses for ``tenant_user``.

    Args:
        alias: The ``tenant_user`` table name or alias in the calling query.

    Returns:
        A condition such as ``tu.status = 'active' AND (tu.role <> 'customer' OR EXISTS (…))``.

    Raises:
        ValueError: If ``alias`` is not a plain SQL identifier.
    """
    if _ALIAS_RE.fullmatch(alias) is None:
        raise ValueError(f"Not a SQL identifier: {alias!r}")
    return (
        f"{alias}.status = 'active' AND ({alias}.role <> 'customer' OR EXISTS ("
        f"SELECT 1 FROM tenant_user_role seat_role WHERE seat_role.tenant_user_id = {alias}.id "
        f"AND seat_role.tenant_id = {alias}.tenant_id AND seat_role.role <> 'customer'))"
    )
