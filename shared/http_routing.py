"""HTTP path → service-handler routing, shared by the local dev server
(``scripts/local_server.py``) and the container HTTP app
(``services/http_app/app.py``).

This mirrors the production API Gateway route-to-Lambda mapping
(``infrastructure/aws/modules/api-gateway``) in one place so the dev server, the
Azure Container Apps API, and API Gateway cannot drift apart. The container has
no API Gateway in front of it, so this *is* its router.

Each service module exposes ``lambda_handler(event, context)`` (and a few also
``http_handler``); ``invoke_handler`` resolves and calls the right one with an
API-Gateway-v2-shaped event.
"""

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Route table: (path-prefix, service module name). Order matters — more specific
# prefixes must come first. Mirrors the production API Gateway routes.
ROUTES: list[tuple[str, str]] = [
    ("/v1/health", "tenant_management"),  # public health check
    ("/v1/auth", "auth"),  # httpOnly-cookie session refresh — see services/auth/handler.py
    ("/v1/register", "tenant_management"),  # customer self-registration (public)
    ("/v1/onboarding-requests", "tenant_management"),  # shipping-company onboarding lead (public)
    ("/v1/invites", "tenant_management"),  # customer account-creation invites (public claim + staff issue)
    ("/v1/activate", "tenant_management"),  # staff/admin account activation (public set-password)
    # Webhooks split by provider — payment (Paystack/Flutterwave, HMAC-verified)
    # vs WhatsApp (Meta).
    ("/v1/webhooks/payment", "payment_release"),
    ("/v1/webhooks/whatsapp", "notification"),
    ("/v1/billing", "billing"),
    ("/v1/refunds", "refunds"),
    ("/v1/claims", "claims"),
    ("/v1/uploads", "claims"),  # presigned URL lives in claims handler
    ("/v1/packing-lists", "packing_list"),
    ("/v1/release-notes", "payment_release"),
    ("/v1/payments", "payment_release"),
    ("/v1/warehouses", "payment_release"),
    ("/v1/containers", "tracking"),
    ("/v1/shipments", "tracking"),
    ("/v1/manifests", "manifest"),
    ("/v1/platform", "tenant_management"),
    ("/v1/tenants", "tenant_management"),
    ("/v1/tenant", "tenant_management"),  # tenant-admin routes
    ("/v1/customers", "tenant_management"),  # customer management routes
    ("/v1/notifications", "notification"),
    ("/v1/excel", "excel"),
    ("/v1/search", "search"),  # global search, role-scoped (audit UX-05)
]

# Excel export/import routes share prefixes with other handlers so are checked
# before the general prefix table. Only packing-lists, manifests, billing, and
# containers have excel exports; other /export paths (e.g.
# /v1/customers/{id}/export) belong to their own service handlers.
_EXCEL_EXPORT_PREFIXES = ("/v1/packing-lists/", "/v1/manifests/", "/v1/billing/", "/v1/containers/")
# PDF document generators all live in the excel service, but their paths sit
# under other resources' prefixes (/v1/release-notes/, /v1/payments/), which
# ROUTES would otherwise hand to payment_release. Production API Gateway routes
# these to the excel Lambda explicitly (04c_terraform_api_gateway.md).
_EXCEL_PDF_PREFIXES = ("/v1/packing-lists/", "/v1/release-notes/", "/v1/payments/", "/v1/billing/", "/v1/manifests/")

# Public routes — no JWT required. Mirrors `local.public_routes` in
# infrastructure/aws/modules/api-gateway/main.tf. In production API Gateway marks
# these `authorization_type = NONE`; the container HTTP app has no API Gateway, so
# it consults this set to decide which requests skip the in-process auth check.
# Each entry is "METHOD /path/template" where {param} matches one path segment.
PUBLIC_ROUTES: frozenset[str] = frozenset(
    {
        "GET /v1/health",
        "GET /v1/shipments/{tracking-code}",
        "GET /v1/webhooks/whatsapp",
        "POST /v1/webhooks/whatsapp",
        "POST /v1/register",
        "POST /v1/register/{slug}",
        "POST /v1/onboarding-requests",
        "GET /v1/invites/{token}",
        "POST /v1/invites/{token}/accept",
        "GET /v1/activate/{token}",
        "POST /v1/activate/{token}",
        "POST /v1/auth/login",
        "POST /v1/auth/authorize-url",
        "POST /v1/auth/callback",
        "POST /v1/auth/session",
        "POST /v1/auth/refresh",
        "POST /v1/auth/logout",
        "POST /v1/webhooks/payment",
    }
)

_handlers: dict[str, Any] = {}


def _segments_match(template: str, actual: str) -> bool:
    """True if a "/"-split path template matches an actual path, where a
    ``{param}`` template segment matches exactly one non-empty actual segment."""
    t_parts = template.strip("/").split("/")
    a_parts = actual.strip("/").split("/")
    if len(t_parts) != len(a_parts):
        return False
    return all((t.startswith("{") and t.endswith("}") and a) or t == a for t, a in zip(t_parts, a_parts, strict=True))


def is_public_route(method: str, path: str) -> bool:
    """True if ``METHOD path`` is a public (no-JWT) route.

    ``path`` is matched without its query string against PUBLIC_ROUTES templates.
    """
    path_no_qs = path.split("?")[0]
    method = method.upper()
    for entry in PUBLIC_ROUTES:
        route_method, _, template = entry.partition(" ")
        if route_method == method and _segments_match(template, path_no_qs):
            return True
    return False


def resolve_service(path: str) -> str | None:
    """Return the service module name that handles ``path``, or None if unrouted.

    ``path`` is the request path (``/v1/...``); any query string is ignored.
    """
    path_no_qs = path.split("?")[0]

    if (
        (path_no_qs.endswith("/export") and any(path_no_qs.startswith(p) for p in _EXCEL_EXPORT_PREFIXES))
        or (path_no_qs.endswith("/pdf") and any(path_no_qs.startswith(p) for p in _EXCEL_PDF_PREFIXES))
        or (
            path_no_qs.startswith("/v1/packing-lists/")
            and (path_no_qs.endswith("/image") or path_no_qs.endswith("/documents") or path_no_qs.endswith("/share-whatsapp"))
        )
        or path_no_qs.endswith("/import")
        or path_no_qs.endswith("/import/presigned-url")
    ):
        return "excel"
    if path_no_qs.startswith("/v1/containers/") and path_no_qs.endswith("/packing-lists"):
        # GET /v1/containers/{id}/packing-lists — sub-resource alias handled by
        # packing_list/handler.py's _container_packing_lists(), not tracking.
        return "packing_list"
    if path_no_qs.startswith("/v1/platform/tenants/") and path_no_qs.endswith("/usage"):
        # Per-tenant usage lives in the metering handler (API GW routes it there
        # in production); everything else under /v1/platform is tenant_management.
        return "metering"

    for prefix, name in ROUTES:
        if path_no_qs == prefix or path_no_qs.startswith(prefix + "/"):
            return name
    return None


def _get_handler_module(name: str) -> Any:
    """Lazily import and cache a service handler module (avoids importing all on boot)."""
    if name not in _handlers:
        _handlers[name] = importlib.import_module(f"services.{name}.handler")
    return _handlers[name]


def invoke_handler(service_name: str, event: dict[str, Any]) -> dict[str, Any]:
    """Resolve the service's entry function and invoke it with ``event``.

    Prefers ``lambda_handler``, falling back to ``http_handler`` (some modules,
    e.g. notification, expose both an SQS consumer and an HTTP entry point).
    """
    handler_mod = _get_handler_module(service_name)
    fn = getattr(handler_mod, "lambda_handler", None) or getattr(handler_mod, "http_handler", None)
    if fn is None:
        raise AttributeError(f"No lambda_handler or http_handler in services.{service_name}.handler")
    result: dict[str, Any] = fn(event, {})
    return result
