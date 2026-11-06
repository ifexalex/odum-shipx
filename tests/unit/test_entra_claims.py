"""Unit tests for shared/providers/azure/entra_claims.py — the Entra claims
mapper. Pure dict-in/dict-out; no tokens or network."""

import importlib

import shared.providers.azure.entra_claims as entra_claims_module
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

    def test_tenant_id_not_derived_for_non_platform_without_claim(self):
        # A tenant-scoped user's tenant id is not derivable — must be explicit.
        assert self.mapper.tenant_id({"role": "tenant_admin", "groups": ["some-guid"]}) == ""

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

    # ── Entra object-id groups: the real-token shape ──────────────────────────

    def test_bare_object_id_groups_are_dropped_when_unmapped(self):
        """Cloud-only Entra groups arrive as GUIDs; with no mapping/role claim
        there is nothing to interpret, so none are granted (not misread as roles)."""
        claims = {"groups": ["11111111-2222-3333-4444-555555555555"]}
        assert self.mapper.groups(claims) == []

    def test_platform_admin_synthesized_from_role_claim(self):
        """The policy-free path: role=platform_admin yields the prefixless group."""
        claims = {"tenant_id": "PLATFORM", "role": "platform_admin"}
        assert self.mapper.groups(claims) == ["platform_admin"]

    def test_tenant_role_synthesized_from_role_and_tenant_claims(self):
        claims = {"tenant_id": "t-9", "role": "tenant_admin"}
        assert self.mapper.groups(claims) == ["t-9:tenant_admin"]

    def test_non_platform_role_without_tenant_is_not_synthesized(self):
        assert self.mapper.groups({"role": "tenant_admin"}) == []

    def test_synthesized_role_merges_with_passthrough_without_duplicates(self):
        claims = {
            "tenant_id": "t-9",
            "role": "tenant_admin",
            "groups": ["t-9:tenant_admin", "t-9:nigeria_office_staff"],
        }
        assert self.mapper.groups(claims) == ["t-9:tenant_admin", "t-9:nigeria_office_staff"]


class TestEntraGroupIdMap:
    """Object-id → canonical-name translation via env config."""

    def _mapper_with_env(self, monkeypatch, **env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        # The map is captured in __init__, so construct after setting env.
        return EntraClaimsMapper()

    def test_platform_admin_group_id_shorthand(self, monkeypatch):
        gid = "aaaabbbb-cccc-dddd-eeee-ffff00001111"
        mapper = self._mapper_with_env(monkeypatch, ENTRA_PLATFORM_ADMIN_GROUP_ID=gid)
        assert mapper.groups({"groups": [gid]}) == ["platform_admin"]

    def test_tenant_id_derived_from_platform_admin_group_id(self, monkeypatch):
        # The real CIAM case: token carries only the platform_admin group GUID
        # (no tenant/role extension claims). tenant_id is derived as PLATFORM.
        gid = "226e2e44-ef7e-4dc6-bf2b-6f39879e8628"
        mapper = self._mapper_with_env(monkeypatch, ENTRA_PLATFORM_ADMIN_GROUP_ID=gid)
        claims = {"oid": "u", "groups": [gid]}
        assert mapper.tenant_id(claims) == "PLATFORM"
        assert mapper.groups(claims) == ["platform_admin"]

    def test_group_id_map_json(self, monkeypatch):
        gid = "22223333-4444-5555-6666-777788889999"
        mapper = self._mapper_with_env(monkeypatch, ENTRA_GROUP_ID_MAP=f'{{"{gid}": "t-9:tenant_admin"}}')
        assert mapper.groups({"groups": [gid]}) == ["t-9:tenant_admin"]

    def test_malformed_group_id_map_is_ignored(self, monkeypatch):
        mapper = self._mapper_with_env(monkeypatch, ENTRA_GROUP_ID_MAP="not-json")
        # Falls back cleanly: unmapped GUID dropped, no crash.
        assert mapper.groups({"groups": ["00000000-0000-0000-0000-000000000000"]}) == []

    def test_overridable_claim_names(self, monkeypatch):
        """ENTRA_*_CLAIM point the mapper at directory-extension claim names."""
        monkeypatch.setenv("ENTRA_TENANT_ID_CLAIM", "extension_abc_tenant_id")
        monkeypatch.setenv("ENTRA_ROLE_CLAIM", "extension_abc_role")
        reloaded = importlib.reload(entra_claims_module)
        try:
            mapper = reloaded.EntraClaimsMapper()
            claims = {"extension_abc_tenant_id": "PLATFORM", "extension_abc_role": "platform_admin"}
            assert mapper.tenant_id(claims) == "PLATFORM"
            assert mapper.groups(claims) == ["platform_admin"]
        finally:
            monkeypatch.undo()
            importlib.reload(entra_claims_module)


class TestDualCloudRoleResolution:
    """Regression guard for the Cognito↔Entra gap: the SAME cloud-agnostic
    `shared.auth` logic must resolve roles from a Cognito-shaped token AND a
    native Entra-shaped token, with no code change — only the active mapper
    differs. This is the "deploy to either cloud without touching code" contract."""

    def _roles(self, monkeypatch, mapper, claims):
        import shared.auth as auth

        monkeypatch.setattr(auth, "get_claims_mapper", lambda: mapper)
        return {r.value for r in auth._parse_roles(claims, mapper.tenant_id(claims))}

    def test_cognito_platform_admin(self, monkeypatch):
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        claims = {"sub": "u", "custom:tenant_id": "PLATFORM", "cognito:groups": "platform_admin"}
        assert self._roles(monkeypatch, CognitoClaimsMapper(), claims) == {"platform_admin"}

    def test_entra_platform_admin_from_native_token(self, monkeypatch):
        # Real Entra shape: groups are object ids (unmapped here), role via claim.
        claims = {
            "oid": "u",
            "tenant_id": "PLATFORM",
            "role": "platform_admin",
            "groups": ["11111111-2222-3333-4444-555555555555"],
        }
        assert self._roles(monkeypatch, EntraClaimsMapper(), claims) == {"platform_admin"}

    def test_entra_platform_admin_from_mapped_group_id(self, monkeypatch):
        monkeypatch.setenv("ENTRA_PLATFORM_ADMIN_GROUP_ID", "GUID-PA")
        claims = {"oid": "u", "tenant_id": "PLATFORM", "groups": ["GUID-PA"]}
        assert self._roles(monkeypatch, EntraClaimsMapper(), claims) == {"platform_admin"}

    def test_entra_platform_admin_ciam_token_no_extension_claims(self, monkeypatch):
        # The exact real-world CIAM id_token: only the platform_admin group GUID,
        # no tenant/role extension claims (CIAM ignores manifest optional claims).
        gid = "226e2e44-ef7e-4dc6-bf2b-6f39879e8628"
        monkeypatch.setenv("ENTRA_PLATFORM_ADMIN_GROUP_ID", gid)
        mapper = EntraClaimsMapper()
        claims = {"oid": "0fd5de8e", "groups": [gid]}
        # get_tenant_context derives tenant_id, then parses roles from it:
        assert mapper.tenant_id(claims) == "PLATFORM"
        assert self._roles(monkeypatch, mapper, claims) == {"platform_admin"}

    def test_both_clouds_resolve_tenant_admin_identically(self, monkeypatch):
        from shared.providers.aws.cognito_claims import CognitoClaimsMapper

        cog = {"sub": "u", "custom:tenant_id": "t-9", "cognito:groups": "t-9:tenant_admin"}
        ent = {"oid": "u", "tenant_id": "t-9", "role": "tenant_admin", "groups": ["some-guid"]}
        assert self._roles(monkeypatch, CognitoClaimsMapper(), cog) == {"tenant_admin"}
        assert self._roles(monkeypatch, EntraClaimsMapper(), ent) == {"tenant_admin"}
