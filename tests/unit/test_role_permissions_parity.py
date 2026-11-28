"""TC-05 CI parity test: shared/role_permissions.py must stay in lockstep with handler role tuples.

Fails if any handler's role constant diverges from the canonical capability map
served by GET /v1/tenant/permissions.
"""

from __future__ import annotations

import importlib

from shared.role_permissions import CAPABILITIES, TENANT_ROLE_ORDER, get_role_permissions_payload


def test_role_permissions_match_handler_role_tuples() -> None:
    bound = [cap for cap in CAPABILITIES if cap.handler_binding is not None]
    assert len(bound) >= 12, "Expected at least 12 handler-bound capabilities"

    mismatches: list[str] = []
    for cap in bound:
        assert cap.handler_binding is not None
        module_path, attr_name = cap.handler_binding
        mod = importlib.import_module(module_path)
        actual_roles = frozenset(getattr(mod, attr_name))
        if actual_roles != cap.roles:
            mismatches.append(
                f"{cap.key} ({module_path}.{attr_name}): "
                f"map={sorted(r.value for r in cap.roles)} != handler={sorted(r.value for r in actual_roles)}"
            )

    assert not mismatches, "Handler role tuples disagree with shared/role_permissions.py:\n" + "\n".join(mismatches)


def test_permissions_payload_covers_every_tenant_role() -> None:
    payload = get_role_permissions_payload()
    assert set(payload["roles"].keys()) == {r.value for r in TENANT_ROLE_ORDER}
    for role_key, entries in payload["roles"].items():
        assert len(entries) == len(CAPABILITIES), f"Role {role_key} missing capability entries"
        for entry in entries:
            assert set(entry.keys()) == {"key", "domain", "label", "allowed"}
            assert isinstance(entry["allowed"], bool)
