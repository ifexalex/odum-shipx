#!/usr/bin/env python3
"""Local HTTP server that wraps Lambda handlers for Postman / browser testing.

Each Lambda function is invoked directly (no AWS runtime) using the same
API Gateway v2 payload format the production handlers expect.

Usage:
    # Load env vars and start server
    source .env.local
    PYTHONPATH=. python3 scripts/local_server.py

    # Or with a one-liner
    env $(cat .env.local | grep -v '^#' | xargs) PYTHONPATH=. python3 scripts/local_server.py

Server listens on http://localhost:3000

Auth headers (all optional — defaults used when missing):
    X-Tenant-ID   : tenant UUID          (default: test-tenant-id)
    X-User-ID     : user sub/UUID        (default: local-user)
    X-Role        : one of the role names below (default: nigeria_office_staff)

Valid roles:
    platform_admin, tenant_admin, china_office_staff,
    nigeria_office_staff, warehouse_attendant, customer

Examples (Postman / curl):
    curl -X GET http://localhost:3000/v1/billing/disputes \\
         -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \\
         -H "X-Role: nigeria_office_staff"

    curl -X POST http://localhost:3000/v1/packing-lists \\
         -H "Content-Type: application/json" \\
         -H "X-Role: china_office_staff" \\
         -d '{"container_id":"c-001","customer_id":"cust-001"}'
"""

import json
import logging
import os
import sys
import uuid

# Ensure project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, Response, request

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("local_server")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Lazy-import handler modules (avoids importing everything on startup)
# ---------------------------------------------------------------------------

_handlers: dict = {}


def _get_handler(name: str):
    if name not in _handlers:
        import importlib
        mod = importlib.import_module(f"services.{name}.handler")
        _handlers[name] = mod
    return _handlers[name]


# ---------------------------------------------------------------------------
# Route table  (path-prefix → service module name)
# Order matters — more specific prefixes must come first.
# ---------------------------------------------------------------------------

_ROUTES = [
    ("/v1/billing",       "billing"),
    ("/v1/refunds",       "refunds"),
    ("/v1/claims",        "claims"),
    ("/v1/uploads",       "claims"),       # presigned URL lives in claims handler
    ("/v1/packing-lists", "packing_list"),
    ("/v1/release-notes", "payment_release"),
    ("/v1/payments",      "payment_release"),
    ("/v1/containers",    "tracking"),
    ("/v1/shipments",     "tracking"),
    ("/v1/manifests",     "manifest"),
    ("/v1/platform",      "tenant_management"),
    ("/v1/tenants",       "tenant_management"),
    ("/v1/tenant",        "tenant_management"),   # tenant-admin routes
    ("/v1/customers",     "tenant_management"),   # customer management routes
    ("/v1/notifications", "notification"),
    ("/v1/excel",         "excel"),
]

DEFAULT_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
DEFAULT_USER_ID   = "local-user-001"
DEFAULT_ROLE      = "nigeria_office_staff"


# ---------------------------------------------------------------------------
# Build API Gateway v2 event from Flask request
# ---------------------------------------------------------------------------

def _build_event() -> dict:
    tenant_id = request.headers.get("X-Tenant-ID", DEFAULT_TENANT_ID)
    user_id   = request.headers.get("X-User-ID",   DEFAULT_USER_ID)
    role      = request.headers.get("X-Role",       DEFAULT_ROLE)

    # Platform admins have no tenant scope — their Cognito group is just
    # "platform_admin" (no tenant prefix) and their tenant_id claim is "PLATFORM".
    # This bypasses the tenant suspension check in get_tenant_context().
    if role == "platform_admin":
        claims_tenant_id = "PLATFORM"
        cognito_groups   = "platform_admin"
    else:
        claims_tenant_id = tenant_id
        cognito_groups   = f"{tenant_id}:{role}"

    body_raw = request.get_data(as_text=True) or None

    return {
        "requestContext": {
            "requestId": str(uuid.uuid4()),
            "http": {
                "method": request.method,
                "path":   request.path,
            },
            "authorizer": {
                "claims": {
                    "sub":              user_id,
                    "custom:tenant_id": claims_tenant_id,
                    "cognito:groups":   cognito_groups,
                }
            },
            "identity": {"sourceIp": request.remote_addr or "127.0.0.1"},
        },
        "body": body_raw,
        "queryStringParameters": dict(request.args) or {},
        "headers": dict(request.headers),
    }


# ---------------------------------------------------------------------------
# Convert Lambda response dict → Flask Response
# ---------------------------------------------------------------------------

def _to_flask_response(lambda_resp: dict) -> Response:
    status_code = lambda_resp.get("statusCode", 200)
    headers     = lambda_resp.get("headers", {})
    body        = lambda_resp.get("body", "")

    content_type = headers.get("Content-Type", "application/json")
    return Response(body, status=status_code, content_type=content_type)


# ---------------------------------------------------------------------------
# Generic catch-all route
# ---------------------------------------------------------------------------

@app.route("/v1/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(path: str):
    full_path = f"/v1/{path}"
    event = _build_event()

    # Find the matching service.
    # Excel export/import routes share prefixes with other handlers so must be
    # checked before the general prefix table.  Only packing-lists, manifests,
    # billing, and containers have excel exports; other /export paths (e.g.
    # /v1/customers/{id}/export) belong to their own service handlers.
    _excel_prefixes = ("/v1/packing-lists/", "/v1/manifests/", "/v1/billing/", "/v1/containers/")
    _path_no_qs = full_path.split("?")[0]
    service_name = None
    if (
        (_path_no_qs.endswith("/export") and any(_path_no_qs.startswith(p) for p in _excel_prefixes))
        or _path_no_qs.endswith("/import")
    ):
        service_name = "excel"
    else:
        for prefix, name in _ROUTES:
            if full_path == prefix or full_path.startswith(prefix + "/") or full_path.startswith(prefix + "?"):
                service_name = name
                break

    if service_name is None:
        return Response(
            json.dumps({"error": f"No handler registered for path: {full_path}"}),
            status=404,
            content_type="application/json",
        )

    logger.info("%s %s → services.%s.handler", request.method, full_path, service_name)

    try:
        handler_mod = _get_handler(service_name)
        result = handler_mod.lambda_handler(event, {})
        return _to_flask_response(result)
    except Exception as exc:
        logger.exception("Unhandled error in %s handler", service_name)
        return Response(
            json.dumps({"error": "Internal server error", "detail": str(exc)}),
            status=500,
            content_type="application/json",
        )


@app.route("/health")
def health():
    return {"status": "ok", "server": "shipx-local"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Safety guard: this server bypasses JWT validation entirely.
    # It must NEVER run outside a local development environment.
    _env = os.environ.get("ENVIRONMENT", "local")
    if _env not in ("local", "test"):
        raise RuntimeError(
            f"local_server.py must only run with ENVIRONMENT=local or test, got '{_env}'. "
            "This server bypasses JWT auth and is unsafe in any shared environment."
        )

    port = int(os.environ.get("LOCAL_PORT", "3000"))
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           ShipX Local API Server  →  http://localhost:{port}   ║
╠══════════════════════════════════════════════════════════════╣
║  Auth headers (all optional):                                ║
║    X-Tenant-ID  : {DEFAULT_TENANT_ID}  ║
║    X-User-ID    : {DEFAULT_USER_ID:<42} ║
║    X-Role       : nigeria_office_staff (default)             ║
║                                                              ║
║  Valid roles: platform_admin, tenant_admin,                  ║
║    china_office_staff, nigeria_office_staff,                 ║
║    warehouse_attendant, customer                             ║
╚══════════════════════════════════════════════════════════════╝
""")
    # Bind to loopback only — do not expose the bypass server on the network.
    app.run(host="127.0.0.1", port=port, debug=False)
