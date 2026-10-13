"""Pydantic request models for the auth session-persistence service."""

from pydantic import BaseModel, Field


class EstablishSessionRequest(BaseModel):
    """POST /v1/auth/session body — the Cognito refresh token from a just-completed login.

    The frontend holds this value only for the duration of this one call; it is
    never assigned to a variable that outlives it (see CognitoClient.ts / SessionProvider.tsx).
    """

    refresh_token: str = Field(min_length=20)


class LoginRequest(BaseModel):
    """POST /v1/auth/login body — email + password for the Entra ROPC proxy.

    Entra's token endpoint does not send CORS headers for the ROPC password
    grant, so the SPA cannot call it directly (EntraClient.ts). This endpoint
    performs that exchange server-side instead. Entra-only; the Cognito SPA
    logs in client-side and never calls this route.
    """

    username: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
