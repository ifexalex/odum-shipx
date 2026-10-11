"""Entra custom authentication extension — OnTokenIssuanceStart claims provider.

Injects ShipX's `tenant_id` + `role` claims into Entra-issued tokens at sign-in.
This is the CIAM-native way to carry those claims (ADR-004 addendum): Entra
External ID does not emit app-manifest `optionalClaims` for directory
extensions, but a custom claims provider runs on every token issuance and can
add them. Hosted as a **Container App** workload on the shared backend image
(`docker-entrypoint.sh claims`) — App Service quota is 0 on the target
subscription, so Azure Functions is not an option (ADR-005 one-image model).
The pure request/response logic (`claims.py`) and the inbound-caller check
(`security.py`) are SDK-free and unit-tested; `app.py` is the Flask WSGI
entrypoint that wires them to Graph.
"""
