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
        field_errors = {
            (str(e["loc"][-1]) if e["loc"] else "__root__"): e["msg"] for e in exc.errors()
        }
        raise ValidationError("Request validation failed", field_errors=field_errors) from exc
