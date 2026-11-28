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

import base64
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
from flask_cors import CORS

from shared.db import execute_with_tenant
from shared.http_routing import invoke_handler, resolve_service

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("local_server")

app = Flask(__name__)

# The frontend (Vite, localhost:5173) and this server (localhost:3000) are
# different origins, so browser fetches need CORS — without it, every
# request (including the preflight OPTIONS triggered by the custom
# X-Tenant-ID/X-Role/X-User-ID headers LocalAuthProvider sends) is blocked
# client-side before it ever reaches a route below. Local dev only — never
# runs against production, where API Gateway + Cognito handle this for real.
#
# supports_credentials=True mirrors api-gateway/main.tf's allow_credentials —
# required for the /v1/auth/* httpOnly session cookie (services/auth/handler.py):
# without it, the browser silently drops the Set-Cookie on the response to
# POST /v1/auth/session and never attaches the cookie on later requests, so
# POST /v1/auth/refresh always 401s and every page reload looks like a fresh,
# unauthenticated visitor even though login just succeeded.
_FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# The cookie endpoints (/v1/auth/session, refresh, logout, ...) accept only requests from a trusted
# origin (shared/origin_guard.py). The dev frontend is one, so default to it rather than make
# everyone edit .env.local; an explicit ALLOWED_ORIGINS still wins.
os.environ.setdefault("ALLOWED_ORIGINS", ",".join(_FRONTEND_ORIGINS))

CORS(
    app,
    origins=_FRONTEND_ORIGINS,
    allow_headers=["Content-Type", "X-Tenant-ID", "X-Role", "X-User-ID", "Idempotency-Key", "Authorization", "X-Step-Up-Token"],
    supports_credentials=True,
)

# ---------------------------------------------------------------------------
# Route table + service resolution live in shared/http_routing.py so the dev
# server, the container HTTP app, and production API Gateway share one mapping.
# ---------------------------------------------------------------------------

# Matches the Acme Shipping Ltd dev-seed tenant — seed.py inserts with this
# exact UUID so it survives make stack. DEFAULT_USER_ID is a placeholder;
# _resolve_user_id() replaces it with the real seeded user id at request time.
DEFAULT_TENANT_ID = "10000000-0000-0000-0000-000000000001"
DEFAULT_USER_ID = "local-user-001"
DEFAULT_ROLE = "nigeria_office_staff"

# Real Cognito subs are always UUIDs, and every *_by / created_by column is
# `UUID REFERENCES tenant_user(id)` (see migrations 001-003) — so the fake
# slugs LocalAuthProvider.tsx sends (e.g. "local-china-staff") fail with
# "invalid input syntax for type uuid" on any write. Resolve them here to a
# real tenant_user.id for that tenant+role, looked up once and cached.
_PLATFORM_ADMIN_UUID = "00000000-0000-0000-0000-000000000000"
_user_id_cache: dict[tuple[str, str], str] = {}


def _resolve_user_id(user_id: str, tenant_id: str, role: str) -> str:
    try:
        uuid.UUID(user_id)
        return user_id  # already a real UUID (e.g. a real Cognito sub)
    except ValueError:
        pass

    if role == "platform_admin":
        return _PLATFORM_ADMIN_UUID  # no tenant_user row for platform admins

    cache_key = (tenant_id, role)
    if cache_key in _user_id_cache:
        return _user_id_cache[cache_key]

    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT id FROM tenant_user WHERE tenant_id = %s AND role = %s ORDER BY created_at LIMIT 1",
            (tenant_id, role),
        )
    except Exception:
        logger.exception("Could not resolve local dev user id for %s/%s", tenant_id, role)
        return user_id

    if not rows:
        logger.warning("No seeded tenant_user for tenant=%s role=%s; writes will fail", tenant_id, role)
        return user_id

    resolved = str(rows[0]["id"])
    _user_id_cache[cache_key] = resolved
    return resolved


def _resolve_user_id_by_sub(sub: str, tenant_id: str) -> str | None:
    """Return `sub` itself if it's already a real tenant_user.id in this tenant.

    True for every self-registered or invite-accepted customer — their
    tenant_user.id is set equal to the Cognito sub at creation
    (repository.create_tenant_user) — but never true for seed-time staff/
    customer rows, whose fixed seed UUID never matches moto's randomly
    generated sub. Checked first so this common case skips the email/role
    guesswork entirely.
    """
    if not sub:
        return None
    cache_key = ("sub", tenant_id, sub)
    if cache_key in _user_id_cache:
        return _user_id_cache[cache_key]
    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT id FROM tenant_user WHERE tenant_id = %s AND id = %s LIMIT 1",
            (tenant_id, sub),
        )
    except Exception:
        logger.exception("Could not resolve user id by sub %s/%s", tenant_id, sub)
        return None
    if not rows:
        return None
    resolved = str(rows[0]["id"])
    _user_id_cache[cache_key] = resolved
    return resolved


def _resolve_user_id_by_email(email: str, tenant_id: str) -> str | None:
    """Look up tenant_user.id by email — used for Cognito JWT logins where the
    Moto-generated sub UUID doesn't match our seeded tenant_user rows."""
    if not email:
        return None
    cache_key = ("email", tenant_id, email)
    if cache_key in _user_id_cache:
        return _user_id_cache[cache_key]
    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT id FROM tenant_user WHERE tenant_id = %s AND email = %s LIMIT 1",
            (tenant_id, email),
        )
    except Exception:
        logger.exception("Could not resolve user id by email %s/%s", tenant_id, email)
        return None
    if not rows:
        return None
    resolved = str(rows[0]["id"])
    _user_id_cache[cache_key] = resolved
    return resolved


def _role_from_groups(groups_str: str, tenant_id: str) -> str | None:
    """Extract the role from a comma-joined cognito:groups string."""
    prefix = f"{tenant_id}:"
    for group in groups_str.split(","):
        group = group.strip()
        if group.startswith(prefix):
            return group[len(prefix) :]
    return None


def _resolve_user_id_by_role(tenant_id: str, role: str | None) -> str | None:
    """Look up tenant_user.id by (tenant_id, role) — fallback when email is absent."""
    if not role:
        return None
    cache_key = (tenant_id, role)
    if cache_key in _user_id_cache:
        return _user_id_cache[cache_key]
    try:
        rows = execute_with_tenant(
            tenant_id,
            "SELECT id FROM tenant_user WHERE tenant_id = %s AND role = %s ORDER BY created_at LIMIT 1",
            (tenant_id, role),
        )
    except Exception:
        logger.exception("Could not resolve user id by role %s/%s", tenant_id, role)
        return None
    if not rows:
        return None
    resolved = str(rows[0]["id"])
    _user_id_cache[cache_key] = resolved
    return resolved


# ---------------------------------------------------------------------------
# Build API Gateway v2 event from Flask request
# ---------------------------------------------------------------------------


def _decode_jwt_claims(token: str) -> dict | None:
    """Decode a JWT's payload without verifying its signature.

    Local dev only — production's API Gateway JWT authorizer verifies the
    signature against Cognito's JWKS before this code ever runs; this server
    has no equivalent and skips verification entirely, same bypass posture
    as the X-Tenant-ID/X-Role/X-User-ID header path below.
    """
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, UnicodeDecodeError):
        return None


def _build_event() -> dict:
    auth_header = request.headers.get("Authorization", "")
    claims: dict | None = None
    if auth_header.startswith("Bearer "):
        claims = _decode_jwt_claims(auth_header.removeprefix("Bearer "))

    if claims is not None and "impersonated_by" in claims and "session_id" in claims:
        # ShipX impersonation token (services/tenant_management/impersonation.py).
        # Mirror the production REQUEST authorizer (services/authorizer/handler.py):
        # its claims are tenant_id/role (not custom:tenant_id/cognito:groups), so
        # synthesise the Cognito-shaped claims get_tenant_context() expects and
        # pass the impersonation markers through for read-only enforcement.
        # Signature is NOT verified — same bypass posture as the paths below.
        imp_tenant_id = claims.get("tenant_id", DEFAULT_TENANT_ID)
        imp_role = claims.get("role", "tenant_admin")
        claims_out = {
            "sub": claims.get("sub", DEFAULT_USER_ID),
            "custom:tenant_id": imp_tenant_id,
            "cognito:groups": f"{imp_tenant_id}:{imp_role}",
            "impersonated_by": claims.get("impersonated_by", ""),
            "session_id": claims.get("session_id", ""),
            "read_only": "true",
        }
    elif claims is not None:
        # Real Cognito-via-Moto login (frontend/src/auth/CognitoClient.ts).
        # A raw ID token's cognito:groups is a real JSON list — API Gateway's
        # HTTP API v2 JWT authorizer flattens it to a comma-joined string
        # before shared/auth.py ever sees it (see _parse_roles()'s docstring).
        # Mirror that flattening here rather than passing the list through.
        raw_groups = claims.get("cognito:groups", "")
        groups_str = ",".join(raw_groups) if isinstance(raw_groups, list) else raw_groups
        tenant_id = claims.get("custom:tenant_id", DEFAULT_TENANT_ID)
        # Moto generates a random UUID for the Cognito sub which won't match any
        # *seeded* tenant_user.id row — resolve the real DB row so FK constraints
        # on container.created_by / audit_log.actor_id don't reject writes.
        # Self-registered/invite-accepted accounts are the exception: their
        # tenant_user.id is set equal to their real Cognito sub at creation
        # time (see repository.create_tenant_user), so the sub already *is*
        # the right row and must be tried first — moto's ID token carries no
        # "email" claim at all (found live verifying 7.52's invite-claim
        # flow: every login fell through to the role-based fallback, which
        # arbitrarily picks the *first*-created tenant_user for that role,
        # silently showing one customer's portal data under another's
        # session). Only fall back to email/role lookup for seeded users
        # whose sub was never written to tenant_user.id.
        email = claims.get("email", "")
        role_from_groups = _role_from_groups(groups_str, tenant_id)
        sub = claims.get("sub", DEFAULT_USER_ID)
        resolved_sub = (
            _resolve_user_id_by_sub(sub, tenant_id)
            or _resolve_user_id_by_email(email, tenant_id)
            or _resolve_user_id_by_role(tenant_id, role_from_groups)
            or sub
        )
        # Moto's random sub matches no platform directory row (migration 076); every local platform admin is the
        # seeded owner, the same id the header path below uses.
        if "platform_admin" in groups_str.split(","):
            resolved_sub = _PLATFORM_ADMIN_UUID
        claims_out = {
            "sub": resolved_sub,
            "custom:tenant_id": tenant_id,
            "cognito:groups": groups_str,
        }
    else:
        # LocalAuthProvider dev shim — synthesize equivalent claims from the
        # X-Tenant-ID/X-Role/X-Roles/X-User-ID headers it sends instead of a JWT.
        # X-Role is always the primary/active role (mirrors custom:role); X-Roles
        # is an optional comma-separated list of every role the dev identity
        # holds (multi-role staff support) — defaults to just [X-Role] when absent.
        tenant_id = request.headers.get("X-Tenant-ID", DEFAULT_TENANT_ID)
        user_id = request.headers.get("X-User-ID", DEFAULT_USER_ID)
        role = request.headers.get("X-Role", DEFAULT_ROLE)
        roles_header = request.headers.get("X-Roles", "")
        roles = [r.strip() for r in roles_header.split(",") if r.strip()] or [role]

        # Platform admins have no tenant scope — their Cognito group is just
        # "platform_admin" (no tenant prefix) and their tenant_id claim is "PLATFORM".
        # This bypasses the tenant suspension check in get_tenant_context().
        if role == "platform_admin":
            claims_tenant_id = "PLATFORM"
            cognito_groups = "platform_admin"
        else:
            claims_tenant_id = tenant_id
            cognito_groups = ",".join(f"{tenant_id}:{r}" for r in roles)

        user_id = _resolve_user_id(user_id, tenant_id, role)
        claims_out = {
            "sub": user_id,
            "custom:tenant_id": claims_tenant_id,
            "custom:role": role,
            "cognito:groups": cognito_groups,
        }

    body_raw = request.get_data(as_text=True) or None

    return {
        "requestContext": {
            "requestId": str(uuid.uuid4()),
            "http": {
                "method": request.method,
                "path": request.path,
            },
            "authorizer": {"claims": claims_out},
            "identity": {"sourceIp": request.remote_addr or "127.0.0.1"},
        },
        "body": body_raw,
        "queryStringParameters": dict(request.args) or {},
        # API Gateway v2 lowercases all header names — handlers rely on that
        # (e.g. "x-paystack-signature", "idempotency-key"); mirror it here.
        "headers": {k.lower(): v for k, v in request.headers.items()},
        # Payload-format-2.0 shape (services/auth/handler.py reads this, not
        # a Cookie header) — one "name=value" string per cookie.
        "cookies": [f"{name}={value}" for name, value in request.cookies.items()],
    }


# ---------------------------------------------------------------------------
# Convert Lambda response dict → Flask Response
# ---------------------------------------------------------------------------

# Local-dev-only: point presigned storage URLs at the Vite dev server's
# /__storage proxy instead of Moto directly.
#
# Why this is necessary, not a convenience: every upload in this app is a
# browser PUT straight to object storage against a presigned URL. It carries a
# Content-Type header, so the browser sends a CORS preflight first — and Moto
# validates the presigned signature on that OPTIONS request, rejecting it with
# SignatureDoesNotMatch because the signature was computed for the PUT. Real S3
# answers preflight unauthenticated, so this is purely a Moto limitation, but
# it means NO browser upload can succeed against Moto directly. It is why
# manifest import succeeded under curl (which ignores CORS) while failing in
# the app and in e2e.
#
# Routing the PUT through the dev server makes it same-origin, so no preflight
# is sent. The signature still validates: SigV2's string-to-sign covers the
# object path, which the proxy preserves, not the host.
#
# This rewrite is confined to this dev shim — handlers, shared/storage and the
# deployed stack are untouched, and production relies on the real bucket's CORS
# rule (infrastructure/aws/modules/s3/main.tf). Set LOCAL_UPLOAD_PROXY_BASE
# empty to disable it and get raw Moto URLs back (useful from curl/Postman,
# which need no proxy).
_STORAGE_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "").rstrip("/")
_UPLOAD_PROXY_BASE = os.environ.get("LOCAL_UPLOAD_PROXY_BASE", "http://localhost:5173/__storage").rstrip("/")


def _proxy_storage_urls(body: str) -> str:
    """Rewrite Moto storage URLs in a response body to the dev-server proxy."""
    if not body or not _STORAGE_ENDPOINT or not _UPLOAD_PROXY_BASE:
        return body
    if _STORAGE_ENDPOINT not in body:
        return body
    return body.replace(_STORAGE_ENDPOINT, _UPLOAD_PROXY_BASE)


def _to_flask_response(lambda_resp: dict) -> Response:
    status_code = lambda_resp.get("statusCode", 200)
    headers = lambda_resp.get("headers", {})
    body = _proxy_storage_urls(lambda_resp.get("body", ""))

    content_type = headers.get("Content-Type", "application/json")
    resp = Response(body, status=status_code, content_type=content_type)

    # API Gateway forwards every response header the handler sets (Retry-After on a 429, Location on a 201,
    # X-Request-Id); this used to forward only Content-Type, so dev hid them from anything that reads them.
    for key, value in headers.items():
        if key.lower() != "content-type":
            resp.headers[key] = value

    # Payload-format-2.0's dedicated "cookies" array (services/auth/handler.py) —
    # mirror API Gateway's behavior of turning each entry into its own
    # Set-Cookie header, since Werkzeug won't do that from a plain headers dict.
    for cookie in lambda_resp.get("cookies", []):
        resp.headers.add("Set-Cookie", cookie)

    return resp


# ---------------------------------------------------------------------------
# Generic catch-all route
# ---------------------------------------------------------------------------


@app.route("/v1/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(path: str):
    full_path = f"/v1/{path}"
    event = _build_event()

    # Resolve the handling service via the shared route table (shared/http_routing.py),
    # the same mapping the container HTTP app and production API Gateway use.
    service_name = resolve_service(full_path)

    if service_name is None:
        return Response(
            json.dumps({"error": f"No handler registered for path: {full_path}"}),
            status=404,
            content_type="application/json",
        )

    logger.info("%s %s → services.%s.handler", request.method, full_path, service_name)

    try:
        result = invoke_handler(service_name, event)
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

    # Auto-drain the local notification queues, in a separate OS process.
    #
    # Ground-truth gap found live, reported by the user: they rejected a
    # payment claim and saw no notification at all, either as staff or
    # (separately, in a follow-up report) as the customer. The notification
    # code was working correctly — it enqueued to SQS — but in AWS an
    # event-source mapping feeds SQS straight into the notification Lambdas,
    # and nothing plays that role against Moto locally, so a queued message
    # just sits there until someone manually runs
    # scripts/drain_notifications.py. Nobody testing the product would know
    # to do that, so it looked exactly like a silent bug.
    #
    # This MUST be a separate process, not a background thread: threaded=False
    # below is load-bearing (see its own comment) because shared/db.py's
    # module-level connection singleton isn't thread-safe, and a poller
    # thread sharing this process's connection would reintroduce the exact
    # concurrent-access corruption that threaded=False was added to prevent.
    # A subprocess gets its own interpreter and its own connection singleton,
    # so it can poll continuously with zero risk to this process's DB state.
    if os.environ.get("DISABLE_NOTIFICATION_DRAIN") != "true":
        import subprocess

        drain_script = os.path.join(PROJECT_ROOT, "scripts", "drain_notifications.py")
        _drain_proc = subprocess.Popen([sys.executable, drain_script, "--watch"], cwd=PROJECT_ROOT)

        import atexit

        atexit.register(_drain_proc.terminate)

    port = int(os.environ.get("LOCAL_PORT", "3000"))
    print(
        f"""
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
"""
    )
    # Bind to loopback only — do not expose the bypass server on the network.
    #
    # threaded=False is load-bearing, not a default: Flask's own run()
    # docstring says "Threaded mode is enabled by default," and shared/db.py's
    # module-level `_connection` singleton (the warm-Lambda-container reuse
    # pattern) is not thread-safe — nothing locks it. With threading on, two
    # browser XHRs firing in parallel (any page that fetches several
    # endpoints at once) can genuinely interleave cur.execute() calls from
    # separate Python threads on the *same* psycopg2 connection, corrupting
    # its transaction state in ways a single connection was never built to
    # survive. Found live: an e2e smoke sweep intermittently crashed
    # unrelated pages with "Internal server error" /
    # psycopg2.errors.InFailedSqlTransaction, scattered across endpoints with
    # no per-endpoint pattern — the signature of a shared resource being
    # corrupted by concurrent access, not a single buggy query. Real AWS
    # Lambda never has this hazard: one container processes one invocation
    # at a time, so threaded=False here is also the more faithful match to
    # production's actual execution model, not just a workaround.
    app.run(host="127.0.0.1", port=port, debug=False, threaded=False)
