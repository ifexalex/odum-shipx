"""The tenant's logo (FD-29): upload, use, remove, and the link that shows it.

The logo is a file in the tenant's storage prefix, ``{tenant_id}/branding/logo/{random hex}-{name}``, and
``branding_config.logo_key`` names it. The key is the server's to set: ``update_tenant_config`` drops any
``logo_key`` or ``logo_url`` a client sends and keeps the stored one, so a branding save from the settings form never
loses the logo and a client can never point it at another tenant's file. Readers get ``logo_url``, a short-lived
presigned link, in place of the key.

Upload follows the shared three steps (``shared.uploads``): presign under the tenant prefix, the browser PUTs the file,
then ``set_logo`` confirms it landed within the size limit and stores the key. Raster images only (PNG, JPEG, WebP), at
most 1 MB; SVG is refused because it can carry script.
"""

import json
import logging
from typing import Any

from shared import uploads
from shared.audit import log_audit
from shared.exceptions import ValidationError
from shared.providers import get_storage_provider

from . import repository as repo

logger = logging.getLogger(__name__)

#: Path segments under the tenant prefix where logos are stored.
_LOGO_SEGMENTS = ("branding", "logo")
#: How long the link to show the logo lasts. The settings page and the sidebar re-read the config well within it.
LOGO_LINK_SECONDS = 3600
#: Fields of ``branding_config`` only the server writes.
_SERVER_OWNED = ("logo_key", "logo_url")


def _logo_prefix(tenant_id: str) -> str:
    return "/".join((tenant_id, *_LOGO_SEGMENTS)) + "/"


def _stored_branding(tenant_id: str) -> dict[str, Any]:
    rows = repo.get_all_configs(tenant_id)
    branding = next((row["config_value"] for row in rows if row["config_key"] == "branding_config"), None)
    return dict(branding) if isinstance(branding, dict) else {}


def _save_branding(tenant_id: str, branding: dict[str, Any], actor_id: str) -> None:
    """Write branding to the config row and the tenant column, as ``update_tenant_config`` does."""
    repo.upsert_config(tenant_id, "branding_config", branding, updated_by=actor_id)
    repo.update_tenant(tenant_id, {"branding_config": json.dumps(branding)})


def _delete_quietly(key: str) -> None:
    """Delete a replaced or removed logo file; a failure leaves an orphan, never a broken logo."""
    try:
        get_storage_provider().delete_object(key)
    except Exception:  # noqa: BLE001 — any provider failure is logged and left; the logo itself is already updated
        logger.warning("Could not delete a replaced tenant logo file", exc_info=True)


def keep_server_owned(tenant_id: str, branding: dict[str, Any]) -> dict[str, Any]:
    """The branding a client sent, with the logo fields replaced by the stored ones.

    Args:
        tenant_id: The tenant saving its branding.
        branding: The client's branding dict, as sent to ``PUT /v1/tenant/config``.
    """
    kept = {key: value for key, value in branding.items() if key not in _SERVER_OWNED}
    stored_key = _stored_branding(tenant_id).get("logo_key")
    if stored_key:
        kept["logo_key"] = stored_key
    return kept


def with_logo_url(tenant_id: str, branding: dict[str, Any] | None) -> dict[str, Any] | None:
    """Branding as readers get it: ``logo_url`` (a presigned link) in place of ``logo_key``.

    A key outside this tenant's logo prefix is never signed, whatever put it there.
    """
    if not isinstance(branding, dict):
        return branding
    shown = {key: value for key, value in branding.items() if key not in _SERVER_OWNED}
    key = branding.get("logo_key")
    if isinstance(key, str) and key.startswith(_logo_prefix(tenant_id)):
        shown["logo_url"] = get_storage_provider().presigned_get_url(key, expires_in=LOGO_LINK_SECONDS)
    return shown


def create_logo_upload(tenant_id: str, filename: str, content_type: str, size_bytes: object) -> dict[str, Any]:
    """Presign the logo upload under the tenant's prefix.

    Raises:
        BusinessRuleViolationError: ``INVALID_CONTENT_TYPE`` (not PNG, JPEG or WebP) or ``FILE_TOO_LARGE`` (over 1 MB).
        ValidationError: No usable ``size_bytes``.
    """
    upload = uploads.presign_upload(uploads.TENANT_LOGO, tenant_id, _LOGO_SEGMENTS, filename, content_type, size_bytes)
    return {"file_key": upload.key, **upload.as_response()}


def set_logo(tenant_id: str, file_key: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """Use an uploaded file as the tenant's logo, replacing (and deleting) any previous one.

    Returns:
        The branding as readers get it, with the new ``logo_url``.

    Raises:
        ValidationError: The key is not one of this tenant's logo uploads.
        BusinessRuleViolationError: ``UPLOAD_NOT_FOUND`` or ``FILE_TOO_LARGE`` (the oversize file is deleted).
    """
    prefix = _logo_prefix(tenant_id)
    rest = file_key[len(prefix) :] if file_key.startswith(prefix) else ""
    if not rest or "/" in rest or "\\" in rest or ".." in rest:
        raise ValidationError(
            "file_key is not a logo upload for this tenant.",
            field_errors={"file_key": "Upload the logo again."},
        )
    uploads.confirm_stored_upload(uploads.TENANT_LOGO, file_key)

    branding = _stored_branding(tenant_id)
    previous = branding.get("logo_key")
    branding["logo_key"] = file_key
    _save_branding(tenant_id, branding, actor_id)
    if isinstance(previous, str) and previous != file_key and previous.startswith(prefix):
        _delete_quietly(previous)

    log_audit(
        tenant_id=tenant_id,
        entity_type="tenant_config",
        entity_id=tenant_id,
        action="UPDATE",
        actor_id=actor_id,
        actor_role="tenant_admin",
        after_state={"action": "logo_set"},
        ip_address=ip_address,
    )
    return with_logo_url(tenant_id, branding) or {}


def remove_logo(tenant_id: str, actor_id: str, ip_address: str | None = None) -> dict[str, Any]:
    """Stop using a logo: documents and the sidebar fall back to the initials tile. The file is deleted."""
    branding = _stored_branding(tenant_id)
    previous = branding.pop("logo_key", None)
    if previous is not None:
        _save_branding(tenant_id, branding, actor_id)
        if isinstance(previous, str) and previous.startswith(_logo_prefix(tenant_id)):
            _delete_quietly(previous)
        log_audit(
            tenant_id=tenant_id,
            entity_type="tenant_config",
            entity_id=tenant_id,
            action="UPDATE",
            actor_id=actor_id,
            actor_role="tenant_admin",
            after_state={"action": "logo_removed"},
            ip_address=ip_address,
        )
    return with_logo_url(tenant_id, branding) or {}
