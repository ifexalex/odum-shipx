"""Shared request-body validation for Lambda handlers.

Every service handler parsed its request body into a Pydantic model with an
identical, independently-copied `_parse_validated()` — nine byte-for-byte
duplicates across services/*/handler.py. Consolidated here after finding a
real bug in all nine copies at once: a pydantic model-level validator (a
`@model_validator` cross-field check, as opposed to a per-field one) reports
its error with an *empty* `loc` tuple, since it isn't about one field. Every
copy did `e["loc"][-1]`, which crashes with `IndexError: tuple index out of
range` on exactly that case — turning a validation failure that should be a
clean 422 into a raw 500. Found live via e2e testing
(RecordPickupRequest's "collected_by_name is required when is_delegate is
false").
"""

import re
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from shared.exceptions import ValidationError


def parse_validated(model_class: type[BaseModel], body: dict[str, Any]) -> Any:
    """Parse `body` into `model_class`, raising the app's ValidationError on failure.

    Args:
        model_class: The Pydantic model to validate against.
        body: The raw request body dict.

    Returns:
        A populated instance of `model_class`.

    Raises:
        shared.exceptions.ValidationError: with one `field_errors` entry per
            pydantic error. A field-level error is keyed by its field name;
            a model-level error (empty `loc`, e.g. a `@model_validator`
            cross-field check) is keyed `"__root__"` rather than crashing.
    """
    try:
        return model_class(**body)
    except PydanticValidationError as exc:
        field_errors = {(str(e["loc"][-1]) if e["loc"] else "__root__"): e["msg"] for e in exc.errors()}
        raise ValidationError("Request validation failed", field_errors=field_errors) from exc


# Unicode word characters (so 装箱单.xlsx survives), dot, space, hyphen and
# parentheses. Everything else — path separators, quotes, semicolons, control
# characters and bidi-override characters (U+202E can render "fdp.exe" as
# "exe.pdf") — is replaced.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.() -]")


def safe_filename(name: Any, *, default: str | None = None, max_length: int = 100) -> str:
    """Reduce a client-supplied upload name to a safe S3 key segment and header value.

    Upload names are embedded verbatim in S3 keys
    (`{tenant_id}/claims/{claim_id}/{filename}`) and later in
    `Content-Disposition: inline; filename="{name}"` on presigned download URLs,
    so a `"` breaks out of the quoted string, `/` fabricates key structure, and a
    bidi-override character spoofs the extension staff see. Directory components
    are dropped, unsafe characters become `_`, leading/trailing dots and spaces
    are stripped (no hidden `.` / `..` names) and the length is capped with the
    extension preserved.

    Args:
        name: The client-supplied file name.
        default: Returned when nothing usable remains (e.g. for legacy rows read
            back at download time). When omitted, an unusable name raises.
        max_length: Maximum length of the result.

    Raises:
        shared.exceptions.ValidationError: if `name` isn't a string or reduces to
            nothing and no `default` was given.
    """
    cleaned = ""
    if isinstance(name, str):
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip(" .")
    if not cleaned or set(cleaned) <= {"_"}:
        if default is not None:
            return default
        raise ValidationError("filename is required", field_errors={"filename": "A usable file name is required"})
    if len(cleaned) > max_length:
        stem, dot, extension = cleaned.rpartition(".")
        extension = extension[:10] if dot else ""
        cleaned = (stem[: max_length - len(extension) - 1] + "." + extension) if dot and stem else cleaned[:max_length]
    return cleaned
