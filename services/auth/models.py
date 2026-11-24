"""Pydantic request models for the auth session-persistence service."""

from pydantic import BaseModel, Field


class EstablishSessionRequest(BaseModel):
    """POST /v1/auth/session body — the Cognito refresh token from a just-completed login.

    The frontend holds this value only for the duration of this one call; it is
    never assigned to a variable that outlives it (see CognitoClient.ts / SessionProvider.tsx).
    """

    # Cookie-safe token characters only — rejects `;`, spaces, or CRLF that would
    # otherwise inject arbitrary Set-Cookie attributes in _establish_session.
    refresh_token: str = Field(min_length=20, max_length=4096, pattern=r"^[A-Za-z0-9._~+/=-]+$")


class LoginRequest(BaseModel):
    """POST /v1/auth/login body — email + password for the Entra ROPC proxy.

    Entra's token endpoint does not send CORS headers for the ROPC password
    grant, so the SPA cannot call it directly (EntraClient.ts). This endpoint
    performs that exchange server-side instead. Entra-only; the Cognito SPA
    logs in client-side and never calls this route.
    """

    username: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class AuthCallbackRequest(BaseModel):
    """POST /v1/auth/callback body — the OAuth2 authorization code + state the SPA
    received back from Entra. The PKCE verifier and expected state live in the
    httpOnly transaction cookie, never in this body (services/auth/handler.py)."""

    code: str = Field(min_length=1, max_length=4096)
    state: str = Field(min_length=1, max_length=512)
