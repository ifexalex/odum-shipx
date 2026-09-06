"""Regression tests for shared/validation.py::parse_validated().

Found live via e2e testing: recording a release-note pickup for the
customer themselves (not a delegate) crashed with a raw 500. The actual
cause — RecordPickupRequest's cross-field check ("collected_by_name is
required when is_delegate is false") — never reached the client as a real
error: nine identical, independently-copied `_parse_validated()` functions
across services/*/handler.py all did `e["loc"][-1]` to build field_errors,
which crashes with IndexError on exactly this class of error (a
`@model_validator`, not a per-field one, reports an empty `loc` tuple).
Consolidated into this one function, fixed once.
"""
import pytest
from pydantic import BaseModel, model_validator

from shared.exceptions import ValidationError
from shared.validation import parse_validated


class _FieldLevelModel(BaseModel):
    name: str


class _ModelLevelModel(BaseModel):
    is_delegate: bool = False
    delegate_name: str | None = None

    @model_validator(mode="after")
    def _check_delegate_name(self) -> "_ModelLevelModel":
        if self.is_delegate and not self.delegate_name:
            raise ValueError("delegate_name is required when is_delegate is true")
        return self


class TestParseValidated:
    def test_valid_body_returns_a_populated_model(self) -> None:
        result = parse_validated(_FieldLevelModel, {"name": "Ngozi"})
        assert result.name == "Ngozi"

    def test_field_level_error_is_keyed_by_field_name(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            parse_validated(_FieldLevelModel, {})
        assert "name" in exc_info.value.field_errors

    def test_model_level_error_does_not_crash_with_indexerror(self) -> None:
        """The exact bug: a cross-field validator's error has an empty `loc`
        tuple, so `e["loc"][-1]` raised IndexError instead of a clean 422."""
        with pytest.raises(ValidationError) as exc_info:
            parse_validated(_ModelLevelModel, {"is_delegate": True})
        assert "__root__" in exc_info.value.field_errors
        assert "delegate_name" in exc_info.value.field_errors["__root__"]
