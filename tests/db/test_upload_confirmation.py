"""Upload confirmation against a real database (migration 069).

A claim evidence, manifest evidence or container document row is written when the upload URL is issued and listed
only once the upload is confirmed. Only a database shows the SQL is valid against the real schema, that confirming
twice keeps the first time, that a confirmed row is never deleted by the refusal path, and that row-level security
keeps another tenant from confirming a tenant's document.
"""

import uuid

import pytest

from services.claims import repository as claims_repo
from services.manifest import repository as manifest_repo
from services.tracking import repository as tracking_repo

pytestmark = pytest.mark.db


@pytest.fixture
def claim_id(world, admin):
    claim = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO damage_claim (id, tenant_id, customer_id, container_id, description, status, reference) "
            "VALUES (%s, %s, %s, %s, 'Crushed carton', 'filed', 'DC-20261119-001')",
            (claim, world["tenant"], world["customers"][0], world["containers"][0]),
        )
    return claim


@pytest.fixture
def manifest_id(world, admin):
    manifest = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO manifest (id, tenant_id, container_id) VALUES (%s, %s, %s)",
            (manifest, world["tenant"], world["containers"][0]),
        )
    return manifest


class TestClaimEvidence:
    def _create(self, world, claim_id):
        return claims_repo.create_claim_evidence(
            {
                "damage_claim_id": claim_id,
                "file_key": f"{world['tenant']}/claims/{claim_id}/{uuid.uuid4().hex}-a.png",
                "file_name": "a.png",
                "file_type": "image/png",
                "file_size_bytes": None,
                "uploaded_by": world["user"],
            }
        )

    def test_listed_only_once_confirmed(self, world, claim_id):
        row = self._create(world, claim_id)
        assert row["confirmed_at"] is None
        assert claims_repo.list_claim_evidence(claim_id) == []

        confirmed = claims_repo.confirm_claim_evidence(claim_id, str(row["id"]), 2048)

        assert confirmed["confirmed_at"] is not None
        assert [(str(r["id"]), r["file_size_bytes"]) for r in claims_repo.list_claim_evidence(claim_id)] == [
            (str(row["id"]), 2048)
        ]

    def test_confirming_twice_keeps_the_first_time(self, world, claim_id):
        row = self._create(world, claim_id)
        first = claims_repo.confirm_claim_evidence(claim_id, str(row["id"]), 2048)
        second = claims_repo.confirm_claim_evidence(claim_id, str(row["id"]), 2048)
        assert second["confirmed_at"] == first["confirmed_at"]

    def test_the_refusal_path_deletes_only_an_unconfirmed_row(self, world, claim_id):
        refused, kept = self._create(world, claim_id), self._create(world, claim_id)
        claims_repo.confirm_claim_evidence(claim_id, str(kept["id"]), 10)

        assert claims_repo.delete_unconfirmed_claim_evidence(claim_id, str(refused["id"])) is not None
        assert claims_repo.delete_unconfirmed_claim_evidence(claim_id, str(kept["id"])) is None
        assert claims_repo.get_claim_evidence(claim_id, str(refused["id"])) is None
        assert claims_repo.get_claim_evidence(claim_id, str(kept["id"])) is not None

    def test_evidence_of_another_claim_is_not_found(self, world, claim_id):
        row = self._create(world, claim_id)
        other_claim = str(uuid.uuid4())
        assert claims_repo.get_claim_evidence(other_claim, str(row["id"])) is None
        assert claims_repo.confirm_claim_evidence(other_claim, str(row["id"]), 1) is None


class TestManifestEvidence:
    def test_listed_only_once_confirmed(self, world, manifest_id):
        row = manifest_repo.create_manifest_evidence(
            world["tenant"],
            {
                "manifest_id": manifest_id,
                "file_key": f"{world['tenant']}/manifests/{manifest_id}/{uuid.uuid4().hex}-a.png",
                "file_name": "a.png",
                "file_type": "image/png",
                "file_size_bytes": None,
                "label": "Carton 1",
                "uploaded_by": world["user"],
            },
        )
        assert manifest_repo.list_manifest_evidence(world["tenant"], manifest_id) == []
        assert manifest_repo.get_manifest_evidence(world["tenant"], manifest_id, str(row["id"])) is not None

        manifest_repo.confirm_manifest_evidence(world["tenant"], manifest_id, str(row["id"]), 4096)

        listed = manifest_repo.list_manifest_evidence(world["tenant"], manifest_id)
        assert [(r["label"], r["file_size_bytes"]) for r in listed] == [("Carton 1", 4096)]
        assert manifest_repo.delete_unconfirmed_manifest_evidence(world["tenant"], manifest_id, str(row["id"])) is None


class TestContainerDocuments:
    def _create(self, world):
        container = world["containers"][0]
        return tracking_repo.create_container_document(
            world["tenant"],
            {
                "tenant_id": world["tenant"],
                "container_id": container,
                "document_type": "bill_of_lading",
                "s3_key": f"{world['tenant']}/containers/{container}/{uuid.uuid4().hex}-bl.pdf",
                "filename": "bl.pdf",
                "content_type": "application/pdf",
                "uploaded_by": world["user"],
            },
        )

    def test_listed_and_downloadable_only_once_confirmed(self, world):
        tenant, container = world["tenant"], world["containers"][0]
        doc_id = str(self._create(world)["id"])

        assert tracking_repo.list_container_documents(tenant, container) == []
        assert tracking_repo.get_container_document_by_id(tenant, container, doc_id) is None
        assert tracking_repo.get_container_document_by_id(tenant, container, doc_id, include_unconfirmed=True) is not None

        tracking_repo.confirm_container_document(tenant, container, doc_id, 1234)

        assert [str(d["id"]) for d in tracking_repo.list_container_documents(tenant, container)] == [doc_id]
        assert tracking_repo.get_container_document_by_id(tenant, container, doc_id)["file_size_bytes"] == 1234

    def test_another_tenant_cannot_confirm_or_delete_it(self, world):
        container = world["containers"][0]
        doc_id = str(self._create(world)["id"])
        stranger = str(uuid.uuid4())

        assert tracking_repo.confirm_container_document(stranger, container, doc_id, 1) is None
        assert tracking_repo.delete_unconfirmed_container_document(stranger, container, doc_id) is None
        assert (
            tracking_repo.get_container_document_by_id(world["tenant"], container, doc_id, include_unconfirmed=True) is not None
        )
