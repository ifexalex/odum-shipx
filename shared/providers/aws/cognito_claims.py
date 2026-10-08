"""AWS Cognito claims mapper.

Reads ShipX's logical identity fields out of a verified Cognito JWT's claims.
The claim names (`sub`, `custom:tenant_id`, `cognito:groups`, `custom:role`) are
the only Cognito-specific part; the role interpretation stays in `shared/auth.py`.
"""
from typing import Any


class CognitoClaimsMapper:
    """ClaimsMapper for Cognito-issued JWTs."""

    def user_id(self, claims: dict[str, Any]) -> str:
        return str(claims.get("sub", ""))

    def tenant_id(self, claims: dict[str, Any]) -> str:
        return str(claims.get("custom:tenant_id", ""))

    def groups(self, claims: dict[str, Any]) -> list[str]:
        """Parse the raw `cognito:groups` claim into a list of group-name strings.

        Handles both a comma-separated string and a JSON-array string. API Gateway
        HTTP API v2 passes `cognito:groups` as `[group1,group2]` — unquoted values,
        not valid JSON — so `json.loads` raising falls back to stripping brackets.
        Groups are already in ShipX's canonical `{tenant_id}:{role}` form.
        """
        groups_raw: str = claims.get("cognito:groups", "") or ""
        if groups_raw.startswith("["):
            import json

            try:
                parsed: list[str] = json.loads(groups_raw)
                return parsed
            except ValueError:
                inner = groups_raw.strip("[]")
                return [g.strip() for g in inner.split(",") if g.strip()]
        return [g.strip() for g in groups_raw.split(",") if g.strip()]

    def primary_role(self, claims: dict[str, Any]) -> str | None:
        role = claims.get("custom:role")
        return str(role) if role is not None else None
