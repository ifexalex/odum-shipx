"""AWS S3 object-storage provider."""
import os
from typing import Any

from shared.providers.base import UploadTicket


class S3StorageProvider:
    """StorageProvider backed by AWS S3.

    Bound to a single bucket. Presigned uploads use `put_object` (not the old
    POST-policy form) so the browser contract is a plain PUT — identical in shape
    to Azure Blob SAS, which lets `useFileUpload` run unchanged on either cloud.
    """

    def __init__(self, bucket: str, region: str | None = None) -> None:
        self._bucket = bucket
        self._region = region or os.environ.get("AWS_REGION", "eu-west-1")
        self._client: Any = None

    def _s3(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int,
        response_content_disposition: str | None = None,
    ) -> str:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if response_content_disposition is not None:
            params["ResponseContentDisposition"] = response_content_disposition
        url: str = self._s3().generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return url

    def presigned_upload(self, key: str, *, content_type: str, expires_in: int) -> UploadTicket:
        url: str = self._s3().generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        # The browser must send Content-Type matching the signed value, or S3
        # rejects the PUT with SignatureDoesNotMatch.
        return UploadTicket(url=url, method="PUT", headers={"Content-Type": content_type})

    def put_object(self, key: str, body: bytes, *, content_type: str) -> None:
        self._s3().put_object(Bucket=self._bucket, Key=key, Body=body, ContentType=content_type)

    def get_object(self, key: str) -> bytes:
        resp = self._s3().get_object(Bucket=self._bucket, Key=key)
        return bytes(resp["Body"].read())

    def object_size(self, key: str) -> int | None:
        try:
            resp = self._s3().head_object(Bucket=self._bucket, Key=key)
        except self._s3().exceptions.ClientError:
            return None
        return int(resp["ContentLength"])

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects, versions, and delete-markers under `prefix`.

        Versioned buckets retain history after a plain delete, so GDPR erasure
        must purge non-current versions and delete-markers too (not just current
        objects) to remove the data immediately rather than waiting on lifecycle
        rules.
        """
        s3 = self._s3()
        total = 0

        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                s3.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
                total += len(objects)

        version_paginator = s3.get_paginator("list_object_versions")
        for page in version_paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            to_delete = [
                {"Key": v["Key"], "VersionId": v["VersionId"]} for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            if to_delete:
                s3.delete_objects(Bucket=self._bucket, Delete={"Objects": to_delete})
                total += len(to_delete)

        return total
