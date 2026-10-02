"""Pydantic request models for the auth session-persistence service."""

from pydantic import BaseModel, Field


class EstablishSessionRequest(BaseModel):
    """POST /v1/auth/session body — the Cognito refresh token from a just-completed login.

    The frontend holds this value only for the duration of this one call; it is
    never assigned to a variable that outlives it (see CognitoClient.ts / SessionProvider.tsx).
    """

    refresh_token: str = Field(min_length=20)
