"""Entra custom authentication extension — OnTokenIssuanceStart claims provider.

Standalone Azure Function that injects ShipX's `tenant_id` + `role` claims into
Entra-issued tokens at sign-in. This is the CIAM-native way to carry those
claims (ADR-004 addendum): Entra External ID does not emit app-manifest
`optionalClaims` for directory extensions, but a custom claims provider runs on
every token issuance and can add them. The pure request/response logic
(`claims.py`) and the inbound-caller check (`security.py`) are SDK-free and
unit-tested; `function_app.py` wires them to the Functions runtime + Graph.
"""
