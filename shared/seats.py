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

    A seat is an active user whose primary role is not ``customer``. The result is a fixed SQL fragment with no user
    input in it; ``alias`` is the table name or alias the caller's query uses for ``tenant_user``.

    Args:
        alias: The ``tenant_user`` table name or alias in the calling query.

    Returns:
        A condition such as ``tu.status = 'active' AND tu.role <> 'customer'``.

    Raises:
        ValueError: If ``alias`` is not a plain SQL identifier.
    """
    if _ALIAS_RE.fullmatch(alias) is None:
        raise ValueError(f"Not a SQL identifier: {alias!r}")
    return f"{alias}.status = 'active' AND {alias}.role <> 'customer'"
