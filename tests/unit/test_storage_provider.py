"""Unit tests for the object-storage port and its AWS S3 adapter.

The adapter is exercised against moto (an in-memory S3) so the round-trips —
put/get, presigned upload/download, HEAD size, versioned prefix purge — are real
S3 behaviour, not mock assertions. The factory tests confirm the cloud-neutral
wiring (`CLOUD_PROVIDER` selection, per-bucket caching, PUT-normalized ticket).
"""

import pytest
from moto import mock_aws

from shared.providers.base import StorageProvider, UploadTicket

BUCKET = "logistics-assets-test"


@pytest.fixture
def s3_provider():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="eu-west-1").create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        from shared.providers.aws.s3 import S3StorageProvider

        yield S3StorageProvider(BUCKET, region="eu-west-1")


class TestS3StorageProvider:
    def test_satisfies_the_storage_protocol(self, s3_provider):
        assert isinstance(s3_provider, StorageProvider)

    def test_put_then_get_round_trips_bytes(self, s3_provider):
        key = "tenant-1/exports/report.xlsx"
        s3_provider.put_object(key, b"spreadsheet-bytes", content_type="application/octet-stream")
        assert s3_provider.get_object(key) == b"spreadsheet-bytes"

    def test_object_size_matches_body_and_is_none_when_absent(self, s3_provider):
        key = "tenant-1/imports/x.xlsx"
        s3_provider.put_object(key, b"12345", content_type="text/plain")
        assert s3_provider.object_size(key) == 5
        assert s3_provider.object_size("tenant-1/imports/missing.xlsx") is None

    def test_presigned_upload_is_a_put_ticket_with_content_type_header(self, s3_provider):
        ticket = s3_provider.presigned_upload("tenant-1/claims/c1/evidence.png", content_type="image/png", expires_in=3600)
        assert isinstance(ticket, UploadTicket)
        assert ticket.method == "PUT"
        assert ticket.headers == {"Content-Type": "image/png"}
        assert ticket.url.startswith("https://")
        # Wire shape the endpoints spread into their responses.
        assert ticket.as_response() == {
            "upload_url": ticket.url,
            "upload_method": "PUT",
            "upload_headers": {"Content-Type": "image/png"},
        }

    def test_presigned_get_url_signs_the_key(self, s3_provider):
        s3_provider.put_object("tenant-1/doc.pdf", b"pdf", content_type="application/pdf")
        url = s3_provider.presigned_get_url("tenant-1/doc.pdf", expires_in=300)
        assert "tenant-1/doc.pdf" in url
        assert "Signature=" in url or "X-Amz-Signature" in url

    def test_presigned_get_url_passes_through_content_disposition(self, s3_provider):
        url = s3_provider.presigned_get_url(
            "tenant-1/doc.pdf",
            expires_in=300,
            response_content_disposition='attachment; filename="safe.pdf"',
        )
        # S3 URL-encodes the override; "attachment" survives recognizably.
        assert "response-content-disposition" in url.lower()

    def test_delete_prefix_removes_only_matching_keys_and_counts_them(self, s3_provider):
        s3_provider.put_object("tenant-1/a.txt", b"a", content_type="text/plain")
        s3_provider.put_object("tenant-1/nested/b.txt", b"b", content_type="text/plain")
        s3_provider.put_object("tenant-2/c.txt", b"c", content_type="text/plain")

        deleted = s3_provider.delete_prefix("tenant-1/")

        assert deleted == 2
        assert s3_provider.object_size("tenant-1/a.txt") is None
        assert s3_provider.object_size("tenant-1/nested/b.txt") is None
        # Other tenants untouched.
        assert s3_provider.object_size("tenant-2/c.txt") == 1


class TestStorageFactory:
    def test_default_cloud_returns_s3_provider(self, monkeypatch):
        import shared.providers as providers
        from shared.providers.aws.s3 import S3StorageProvider

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_storage_providers", {})
        monkeypatch.setenv("S3_BUCKET_NAME", "my-assets")

        provider = providers.get_storage_provider()
        assert isinstance(provider, S3StorageProvider)

    def test_providers_are_cached_per_bucket(self, monkeypatch):
        import shared.providers as providers

        monkeypatch.setattr(providers, "CLOUD_PROVIDER", "aws")
        monkeypatch.setattr(providers, "_storage_providers", {})

        default_a = providers.get_storage_provider()
        default_b = providers.get_storage_provider()
        other = providers.get_storage_provider("tenant-data-bucket")

        assert default_a is default_b  # same bucket → cached instance
        assert other is not default_a  # distinct bucket → distinct instance
