"""Unit tests for shared/providers/azure/entra_claims.py — the Entra claims
mapper. Pure dict-in/dict-out; no tokens or network."""

from shared.providers.azure.entra_claims import EntraClaimsMapper


class TestEntraClaimsMapper:
    def setup_method(self):
        self.mapper = EntraClaimsMapper()

    def test_user_id_prefers_oid_then_sub(self):
        assert self.mapper.user_id({"oid": "obj-1", "sub": "pair-1"}) == "obj-1"
        assert self.mapper.user_id({"sub": "pair-1"}) == "pair-1"
        assert self.mapper.user_id({}) == ""

    def test_tenant_id_default_claim(self):
        assert self.mapper.tenant_id({"tenant_id": "t-123"}) == "t-123"
        assert self.mapper.tenant_id({}) == ""

    def test_groups_from_list(self):
        claims = {"groups": ["t1:tenant_admin", "t1:china_office_staff"]}
        assert self.mapper.groups(claims) == ["t1:tenant_admin", "t1:china_office_staff"]

    def test_groups_from_json_array_string(self):
        assert self.mapper.groups({"groups": '["t1:tenant_admin"]'}) == ["t1:tenant_admin"]

    def test_groups_from_csv_string(self):
        assert self.mapper.groups({"groups": "t1:tenant_admin, t1:customer"}) == [
            "t1:tenant_admin",
            "t1:customer",
        ]

    def test_groups_empty(self):
        assert self.mapper.groups({}) == []

    def test_primary_role(self):
        assert self.mapper.primary_role({"role": "tenant_admin"}) == "tenant_admin"
        assert self.mapper.primary_role({}) is None
