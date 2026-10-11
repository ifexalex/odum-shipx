"""Unit tests for the Entra OnTokenIssuanceStart claims provider — the pure
request/response logic and the inbound-caller check. No Azure SDK / network
(the Graph lookup is a stub), so these run in the normal unit suite."""

from services.entra_token_claims.claims import build_claims_response, extract_object_id
from services.entra_token_claims.security import is_authorized

OID = "0fd5de8e-bb42-441e-adf4-107cd7f21add"


def _event(oid: str | None = OID) -> dict:
    user = {} if oid is None else {"id": oid}
    return {"data": {"authenticationContext": {"user": user}}}


class TestExtractObjectId:
    def test_reads_user_id(self):
        assert extract_object_id(_event()) == OID

    def test_missing_pieces_return_empty(self):
        assert extract_object_id({}) == ""
        assert extract_object_id({"data": {}}) == ""
        assert extract_object_id(_event(oid=None)) == ""


class TestBuildClaimsResponse:
    def test_maps_lookup_into_response_envelope(self):
        resp = build_claims_response(_event(), lambda oid: {"tenant_id": "PLATFORM", "role": "platform_admin"})
        data = resp["data"]
        assert data["@odata.type"] == "microsoft.graph.onTokenIssuanceStartResponseData"
        action = data["actions"][0]
        assert action["@odata.type"] == "microsoft.graph.tokenIssuanceStart.provideClaimsForToken"
        assert action["claims"] == {"tenant_id": "PLATFORM", "role": "platform_admin"}

    def test_lookup_receives_the_object_id(self):
        seen: list[str] = []
        build_claims_response(_event(), lambda oid: seen.append(oid) or {})
        assert seen == [OID]

    def test_empty_values_are_dropped(self):
        resp = build_claims_response(_event(), lambda oid: {"tenant_id": "PLATFORM", "role": ""})
        assert resp["data"]["actions"][0]["claims"] == {"tenant_id": "PLATFORM"}

    def test_unknown_user_yields_empty_claims_but_valid_envelope(self):
        # Fail-open on the claim: token still issues, backend grants no role.
        resp = build_claims_response(_event(oid=None), lambda oid: {"tenant_id": "x"})
        assert resp["data"]["actions"][0]["claims"] == {}

    def test_lookup_returning_none_is_tolerated(self):
        resp = build_claims_response(_event(), lambda oid: None)  # type: ignore[arg-type,return-value]
        assert resp["data"]["actions"][0]["claims"] == {}


class TestClaimsWsgiApp:
    """The Flask entrypoint (Container App workload) wiring — verify gate +
    response. `_verify_caller`/`is_authorized`/`_reader` are stubbed so no JWKS
    or Graph is touched."""

    def test_health_ok(self):
        from services.entra_token_claims import app as appmod

        resp = appmod.app.test_client().get("/health")
        assert resp.status_code == 200

    def test_unauthorized_without_valid_caller(self, monkeypatch):
        from services.entra_token_claims import app as appmod

        monkeypatch.setattr(appmod, "_verify_caller", lambda _h: None)
        resp = appmod.app.test_client().post("/token-claims", json=_event())
        assert resp.status_code == 401

    def test_returns_claims_when_authorized(self, monkeypatch):
        from services.entra_token_claims import app as appmod

        monkeypatch.setattr(appmod, "_verify_caller", lambda _h: {"aud": "a", "iss": "i"})
        monkeypatch.setattr(appmod, "is_authorized", lambda *_a: True)
        monkeypatch.setattr(appmod, "_reader", lambda _oid: {"tenant_id": "PLATFORM", "role": "platform_admin"})
        resp = appmod.app.test_client().post("/token-claims", json=_event())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["actions"][0]["claims"] == {
            "tenant_id": "PLATFORM",
            "role": "platform_admin",
        }


class TestInboundAuthorization:
    AUD = "api-app-id"
    ISS = "https://tenant.ciamlogin.com/xxx/v2.0"

    def test_accepts_matching_aud_and_iss(self):
        assert is_authorized({"aud": self.AUD, "iss": self.ISS}, self.AUD, self.ISS) is True

    def test_rejects_wrong_audience(self):
        assert is_authorized({"aud": "other", "iss": self.ISS}, self.AUD, self.ISS) is False

    def test_rejects_wrong_issuer(self):
        assert is_authorized({"aud": self.AUD, "iss": "https://evil"}, self.AUD, self.ISS) is False

    def test_fails_closed_on_unconfigured_expected_values(self):
        assert is_authorized({"aud": "", "iss": ""}, "", "") is False
        assert is_authorized({"aud": self.AUD, "iss": self.ISS}, "", self.ISS) is False
