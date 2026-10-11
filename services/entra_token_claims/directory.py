"""Microsoft Graph directory-attribute reader for the claims extension.

Reads a user's ShipX `tenant_id` / `role` from their directory **extension
attributes** by object id, authenticated with the Function's managed identity
(`DefaultAzureCredential`). Isolated from the pure logic (`claims.py`) so unit
tests never need the Azure SDK; `app.py` injects an instance as the
`lookup` callable.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_GRAPH_BASE = os.environ.get("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class DirectoryClaimsReader:
    """Callable `lookup(oid) -> {output_claim_name: value}` backed by Graph.

    Maps the directory extension attributes (`tenant_attr` / `role_attr`) onto
    the output claim names the backend reads (`ENTRA_TENANT_ID_CLAIM` /
    `ENTRA_ROLE_CLAIM`, default `tenant_id` / `role`). Any Graph failure returns
    an empty mapping so a transient miss never blocks sign-in (fail-open on the
    claim only — the backend then grants no elevated role).
    """

    def __init__(
        self,
        tenant_attr: str,
        role_attr: str,
        out_tenant_claim: str = "tenant_id",
        out_role_claim: str = "role",
    ) -> None:
        self._tenant_attr = tenant_attr
        self._role_attr = role_attr
        self._out_tenant = out_tenant_claim
        self._out_role = out_role_claim
        self._credential: Any = None

    def _token(self) -> str:
        if self._credential is None:
            from azure.identity import DefaultAzureCredential

            self._credential = DefaultAzureCredential()
        return str(self._credential.get_token(_GRAPH_SCOPE).token)

    def __call__(self, oid: str) -> dict[str, str]:
        select = ",".join(attr for attr in (self._tenant_attr, self._role_attr) if attr)
        if not select:
            return {}
        url = f"{_GRAPH_BASE}/users/{urllib.parse.quote(oid)}?$select={select}"
        req = urllib.request.Request(url, method="GET")  # noqa: S310 - Graph host only
        req.add_header("Authorization", f"Bearer {self._token()}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                data: dict[str, Any] = json.loads(resp.read() or b"{}")
        except (urllib.error.URLError, ValueError) as exc:
            logger.warning("Graph attribute read failed for oid=%s: %s", oid, exc)
            return {}
        out: dict[str, str] = {}
        if self._tenant_attr and data.get(self._tenant_attr):
            out[self._out_tenant] = str(data[self._tenant_attr])
        if self._role_attr and data.get(self._role_attr):
            out[self._out_role] = str(data[self._role_attr])
        return out
