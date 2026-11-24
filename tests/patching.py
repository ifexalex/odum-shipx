"""Patching a collaborator of the tenant-management service across the modules it was split into (audit BE-13).

``services/tenant_management/service.py`` used to be one module, so ``patch.object(service, "log_audit")`` replaced
the one ``log_audit`` every function there called. The code now lives in sub-domain modules (``tenants``, ``users``,
``customers``, ...), each with its own binding. ``patch_tenant_management`` patches the name in every one of them
that has it, with one shared mock, which is what the old single patch did.

Prefer a plain ``patch("services.tenant_management.<module>.<name>")`` when only one module is involved.
"""

import importlib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import DEFAULT, MagicMock, patch

#: The modules ``service`` was split into, plus ``service`` itself (it re-exports the public functions).
TENANT_MANAGEMENT_MODULES = (
    "service",
    "tenants",
    "offboarding_export",
    "activation",
    "users",
    "customers",
    "tenant_config",
    "rates",
    "platform",
)


@contextmanager
def patch_tenant_management(name: str, new: Any = DEFAULT, **kwargs: Any) -> Iterator[Any]:
    """Patch ``name`` in every tenant-management module that has it, all with the same object.

    Args:
        name: The attribute to replace, e.g. ``"log_audit"`` or ``"get_identity_provider"``.
        new: The replacement; a ``MagicMock(**kwargs)`` when omitted, as with ``patch``.
        **kwargs: Passed to the ``MagicMock`` (``return_value``, ``side_effect``, ...).

    Yields:
        The replacement, for assertions.

    Raises:
        AttributeError: No tenant-management module has ``name``.
    """
    replacement = MagicMock(**kwargs) if new is DEFAULT else new
    modules = [importlib.import_module(f"services.tenant_management.{m}") for m in TENANT_MANAGEMENT_MODULES]
    holders = [module for module in modules if hasattr(module, name)]
    if not holders:
        raise AttributeError(f"no tenant_management module has {name!r}")
    with ExitStack() as stack:
        for module in holders:
            stack.enter_context(patch.object(module, name, replacement))
        yield replacement
