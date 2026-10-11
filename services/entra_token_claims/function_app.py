"""Azure Functions entrypoint — Entra OnTokenIssuanceStart claims provider.

Anonymous HTTP route (the caller is authenticated by the Azure AD bearer token
Entra sends, verified here against the tenant JWKS — not by a Function key).
Wires the pure request/response logic (`claims.py`), the inbound-caller check
(`security.py`), and the Graph-backed directory lookup (`directory.py`).

Expected app settings:
    CALLER_JWKS_URL     tenant JWKS (verifies the inbound Entra token's signature)
    CALLER_AUDIENCE     expected `aud` of the inbound token (the extension's API app id)
    CALLER_ISSUER       expected `iss` of the inbound token
    ENTRA_TENANT_ID_ATTR / ENTRA_ROLE_ATTR  directory extension attribute names to read
    OUT_TENANT_CLAIM / OUT_ROLE_CLAIM        emitted claim names (default tenant_id / role)
    GRAPH_BASE_URL      optional Graph base (default v1.0 public cloud)
"""

import json
import logging
import os
from typing import Any

import azure.functions as func
from directory import DirectoryClaimsReader
from security import is_authorized

from claims import build_claims_response

logger = logging.getLogger(__name__)

_JWKS_URL = os.environ.get("CALLER_JWKS_URL", "")
_EXPECTED_AUD = os.environ.get("CALLER_AUDIENCE", "")
_EXPECTED_ISS = os.environ.get("CALLER_ISSUER", "")
_OUT_TENANT = os.environ.get("OUT_TENANT_CLAIM", "tenant_id")
_OUT_ROLE = os.environ.get("OUT_ROLE_CLAIM", "role")

_reader = DirectoryClaimsReader(
    tenant_attr=os.environ.get("ENTRA_TENANT_ID_ATTR", ""),
    role_attr=os.environ.get("ENTRA_ROLE_ATTR", ""),
    out_tenant_claim=_OUT_TENANT,
    out_role_claim=_OUT_ROLE,
)

app = func.FunctionApp()


def _verify_caller(auth_header: str) -> dict[str, Any] | None:
    """Verify the inbound Entra bearer token (RS256 against the tenant JWKS).

    Returns the decoded claims on success, else None. Signature, expiry, and
    audience are enforced by the JWT library; the issuer is checked by the
    caller via `is_authorized`.
    """
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


# azure.functions ships no type stubs, so its route decorators read as untyped;
# strict mypy's untyped-decorator check is disabled for this module in pyproject.
@app.function_name(name="tokenClaims")
@app.route(route="token-claims", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def token_claims(req: func.HttpRequest) -> func.HttpResponse:
    """Handle the token-issuance-start webhook and return ShipX claims."""
    claims = _verify_caller(req.headers.get("Authorization", ""))
    if claims is None or not is_authorized(claims, _EXPECTED_AUD, _EXPECTED_ISS):
        return func.HttpResponse(status_code=401)
    try:
        event = req.get_json()
    except ValueError:
        return func.HttpResponse(status_code=400)
    body = build_claims_response(event, _reader)
    return func.HttpResponse(json.dumps(body), mimetype="application/json")
