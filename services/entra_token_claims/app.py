"""WSGI claims provider — Entra OnTokenIssuanceStart custom authentication
extension, hosted as a **Container App** workload on the shared backend image
(not an Azure Function: App Service quota is 0 on the target subscription, and
Container Apps is the proven compute — ADR-004 addendum / ADR-005 one-image
model). Reuses the pure logic in `claims.py` / `security.py` and the DB-backed
reader in `db_lookup.py`.

Run via the container entrypoint (`docker-entrypoint.sh claims`), i.e.::

    gunicorn --bind 0.0.0.0:8080 services.entra_token_claims.app:app

Environment:
  CALLER_JWKS_URL / CALLER_AUDIENCE / CALLER_ISSUER  — verify Entra's inbound token
  OUT_TENANT_CLAIM / OUT_ROLE_CLAIM                  — emitted claim names (default tenant_id/role)
  DATABASE_* / DATABASE_SSLMODE                      — ShipX DB connection (see shared/db.py)
The claims are read from the ShipX DB (tenant_user) by the Entra oid — no Graph
permission is needed.
"""

import json
import logging
import os
from typing import Any

from flask import Flask, Response, request

from services.entra_token_claims.claims import build_claims_response, extract_object_id
from services.entra_token_claims.db_lookup import DatabaseClaimsReader
from services.entra_token_claims.security import is_authorized
from shared.logging_config import setup_logging

setup_logging()
logger = logging.getLogger("shipx_entra_claims")

_JWKS_URL = os.environ.get("CALLER_JWKS_URL", "")
_EXPECTED_AUD = os.environ.get("CALLER_AUDIENCE", "")
_EXPECTED_ISS = os.environ.get("CALLER_ISSUER", "")

_reader = DatabaseClaimsReader(
    out_tenant_claim=os.environ.get("OUT_TENANT_CLAIM", "tenant_id"),
    out_role_claim=os.environ.get("OUT_ROLE_CLAIM", "role"),
)

app = Flask(__name__)


def _verify_caller(auth_header: str) -> dict[str, Any] | None:
    """Verify Entra's inbound bearer (RS256 against the tenant JWKS). Returns the
    decoded claims or None; signature/expiry/audience enforced here, issuer by
    the caller via `is_authorized`."""
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[len("bearer ") :].strip()
    try:
        import jwt
        from jwt import PyJWKClient

        signing_key = PyJWKClient(_JWKS_URL).get_signing_key_from_jwt(token)
        decoded: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_EXPECTED_AUD or None,
            options={"verify_aud": bool(_EXPECTED_AUD)},
        )
        return decoded
    except Exception as exc:
        logger.warning("Inbound caller token verification failed: %s", exc)
        return None


@app.get("/health")
def health() -> Response:
    """Liveness probe for Container Apps ingress."""
    return Response("ok", status=200, mimetype="text/plain")


@app.post("/token-claims")
def token_claims() -> Response:
    """OnTokenIssuanceStart webhook — return ShipX's tenant_id/role claims."""
    caller = _verify_caller(request.headers.get("Authorization", ""))
    if caller is None:
        # _verify_caller already logged the signature/audience/JWKS failure reason.
        return Response(status=401)
    if not is_authorized(caller, _EXPECTED_AUD, _EXPECTED_ISS):
        # Log the mismatch so a misconfigured caller audience/issuer is diagnosable
        # without a redeploy. aud/iss are token identifiers, not secrets — but the
        # token itself is never logged.
        logger.warning(
            "Caller not authorized: aud=%r (expected %r) iss=%r (expected %r)",
            caller.get("aud"),
            _EXPECTED_AUD,
            caller.get("iss"),
            _EXPECTED_ISS,
        )
        return Response(status=401)
    event = request.get_json(silent=True)
    if event is None:
        return Response(status=400)
    body = build_claims_response(event, _reader)

    # Log the outcome per request. Without this the only signal is the response
    # SIZE in the access log (181 bytes = no claims, 256 = claims), which cannot
    # be attributed to a user — so "the token has no tenant_id" was undebuggable.
    # `oid` is a directory object id (the same UUID shape as user_id, which the
    # logging standard permits); no email/name is logged.
    oid = extract_object_id(event)
    claims = (body.get("data", {}).get("actions") or [{}])[0].get("claims") or {}
    if claims:
        logger.info("Claims issued for oid=%s: %s", oid, {k: v for k, v in claims.items()})
    else:
        logger.warning(
            "NO claims for oid=%s — no active tenant_user row matches this subject. "
            "A tenant-scoped sign-in will fail with 'JWT is missing required claims'; "
            "a platform_admin is unaffected (resolves from the group claim). Check "
            "tenant_user.cognito_sub = this oid AND status = 'active'.",
            oid,
        )
    return Response(json.dumps(body), status=200, mimetype="application/json")
