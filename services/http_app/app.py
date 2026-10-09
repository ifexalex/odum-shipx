"""Production WSGI app that fronts the ShipX service handlers on a container
platform (Azure Container Apps), replacing AWS API Gateway + Lambda.

It is the cloud-neutral sibling of ``scripts/local_server.py``: both translate
an incoming HTTP request into the API-Gateway-v2 event the handlers expect,
resolve the handling service via ``shared.http_routing``, invoke it, and map the
Lambda-style response back to HTTP. The difference is auth — the dev server
trusts ``X-Role`` headers, whereas this app verifies a real bearer token
in-process via ``shared.auth_verify`` (the same logic the AWS Lambda authorizer
runs), because there is no API Gateway authorizer in front of it.

Run with a production WSGI server, e.g.::

    gunicorn --bind 0.0.0.0:8080 services.http_app.app:app

Environment:
  OIDC_JWKS_URL / OIDC_AUDIENCE  — token verification (see shared/auth_verify.py).
  CORS_ALLOW_ORIGINS             — comma-separated allowed origins (optional; omit
                                    for same-origin deployments behind the CDN).
  CLOUD_PROVIDER                 — selects the adapter set (azure on Azure).
"""

import json
import logging
import os
import uuid
from typing import Any

from flask import Flask, Response, request

from shared.auth_verify import build_authorizer_claims
from shared.http_routing import invoke_handler, is_public_route, resolve_service
from shared.logging_config import bind_log_context, clear_log_context, setup_logging

setup_logging()
logger = logging.getLogger("shipx_http_app")

app = Flask(__name__)

_CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]


def _bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return ""


def _build_event(claims: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble an API-Gateway-v2 proxy event from the current Flask request.

    ``claims`` is the verified authorizer context for authenticated routes, or
    None for public routes (no authorizer context, mirroring API Gateway's
    ``authorization_type = NONE``).
    """
    body_raw = request.get_data(as_text=True) or None
    authorizer: dict[str, Any] = {"claims": claims} if claims is not None else {}
    return {
        "requestContext": {
            "requestId": str(uuid.uuid4()),
            "http": {
                "method": request.method,
                "path": request.path,
            },
            "authorizer": authorizer,
            "identity": {"sourceIp": request.remote_addr or "127.0.0.1"},
        },
        "body": body_raw,
        "queryStringParameters": dict(request.args) or {},
        # API Gateway v2 lowercases all header names — handlers rely on that
        # (e.g. "x-paystack-signature", "idempotency-key").
        "headers": {k.lower(): v for k, v in request.headers.items()},
        # Payload-format-2.0 "cookies" array — one "name=value" string per cookie.
        "cookies": [f"{name}={value}" for name, value in request.cookies.items()],
    }


def _to_flask_response(lambda_resp: dict[str, Any]) -> Response:
    status_code = lambda_resp.get("statusCode", 200)
    headers = lambda_resp.get("headers", {})
    body = lambda_resp.get("body", "")
    content_type = headers.get("Content-Type", "application/json")
    resp = Response(body, status=status_code, content_type=content_type)
    for key, value in headers.items():
        if key.lower() != "content-type":
            resp.headers[key] = value
    # Payload-format-2.0 "cookies" array → one Set-Cookie header each.
    for cookie in lambda_resp.get("cookies", []):
        resp.headers.add("Set-Cookie", cookie)
    _apply_cors(resp)
    return resp


def _apply_cors(resp: Response) -> None:
    origin = request.headers.get("Origin", "")
    if origin and origin in _CORS_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Vary"] = "Origin"


def _json_response(status: int, payload: dict[str, Any]) -> Response:
    resp = Response(json.dumps(payload), status=status, content_type="application/json")
    _apply_cors(resp)
    return resp


@app.route("/health")
def health() -> Response:
    """Container liveness/readiness probe — unauthenticated, no DB dependency."""
    return _json_response(200, {"status": "ok", "server": "shipx-container"})


@app.route(
    "/v1/<path:path>",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def dispatch(path: str) -> Response:
    full_path = f"/v1/{path}"
    method = request.method

    # CORS preflight — answered here; never reaches a handler.
    if method == "OPTIONS":
        resp = Response(status=204)
        _apply_cors(resp)
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "Access-Control-Request-Headers", "Authorization,Content-Type,Idempotency-Key"
        )
        return resp

    clear_log_context()
    bind_log_context(request_id=str(uuid.uuid4()))

    public = is_public_route(method, full_path)
    claims: dict[str, Any] | None = None
    if not public:
        claims = build_authorizer_claims(_bearer_token())
        if claims is None:
            return _json_response(401, {"error": "Unauthorized"})

    service_name = resolve_service(full_path)
    if service_name is None:
        return _json_response(404, {"error": f"No handler registered for path: {full_path}"})

    logger.info("%s %s -> services.%s.handler", method, full_path, service_name)

    try:
        result = invoke_handler(service_name, _build_event(claims))
        return _to_flask_response(result)
    except Exception:
        logger.exception("Unhandled error in %s handler", service_name)
        return _json_response(500, {"error": "Internal server error"})
