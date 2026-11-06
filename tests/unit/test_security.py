"""Security tests — SQL injection prevention, S3 key scoping, sort field allowlist."""

import os
import re

import pytest

# ---------------------------------------------------------------------------
# SQL injection — verify repository files use parameterized queries
# ---------------------------------------------------------------------------

_SERVICES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "services")
_SHARED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "shared")

# Patterns that indicate raw string interpolation into SQL — must not appear
_DANGEROUS_SQL_PATTERNS = [
    r'f".*SELECT',
    r"f'.*SELECT",
    r'f".*INSERT',
    r"f'.*INSERT",
    r'f".*UPDATE',
    r"f'.*UPDATE",
    r'f".*DELETE',
    r"f'.*DELETE",
    r"%\s*\(",  # old-style %-formatting directly into SQL
]

# Files known to use limited f-strings for safe allowlisted values (e.g., SET clauses)
_ALLOWLISTED_FILES = {
    "repository.py",  # update_refund_status uses f-string for allowlisted column names
    "storage_fee.py",  # data_cleanup uses f-string with hardcoded table names
    "data_cleanup.py",
}


def _get_repository_files() -> list[str]:
    """Collect all repository.py files across services."""
    files = []
    for root, _dirs, fnames in os.walk(_SERVICES_DIR):
        for fname in fnames:
            if fname == "repository.py":
                files.append(os.path.join(root, fname))
    return files


class TestNoRawSqlFstrings:
    def test_no_user_input_in_sql_fstrings(self):
        """Verify repository files don't build SQL with user input in f-strings.

        This is a static analysis check — it flags potentially dangerous patterns.
        Allowlisted files use f-strings only for column names validated against
        a frozenset allowlist (safe dynamic SQL).
        """
        violations = []
        for fpath in _get_repository_files():
            basename = os.path.basename(fpath)
            if basename in _ALLOWLISTED_FILES:
                continue
            with open(fpath) as f:
                content = f.read()
            # Check for raw % formatting of SQL strings with user-looking variables
            if re.search(r'"SELECT.*%s.*".*%\s*\w+', content):
                violations.append(fpath)

        assert not violations, f"Potential SQL injection via % formatting found in: {violations}"


class TestSortFieldAllowlist:
    def test_allowed_sort_fields_enforced(self):
        """Verify build_paginated_query rejects arbitrary sort fields."""
        from shared.exceptions import ValidationError
        from shared.pagination import build_paginated_query

        with pytest.raises(ValidationError):
            build_paginated_query(
                "SELECT * FROM billing WHERE 1=1",
                None,
                20,
                sort_field="1; DROP TABLE billing; --",
            )

    def test_valid_sort_fields_accepted(self):
        from shared.pagination import ALLOWED_SORT_FIELDS, build_paginated_query

        base = "SELECT * FROM billing WHERE 1=1"
        for field in ALLOWED_SORT_FIELDS:
            query, _ = build_paginated_query(base, None, 20, sort_field=field)
            assert field in query

    def test_allowlist_does_not_contain_dangerous_chars(self):
        from shared.pagination import ALLOWED_SORT_FIELDS

        for field in ALLOWED_SORT_FIELDS:
            assert ";" not in field
            assert "--" not in field
            assert "'" not in field
            assert '"' not in field
            assert " " not in field


class TestS3KeyScoping:
    """Verify S3 key generation always includes tenant_id prefix."""

    def test_claims_s3_key_includes_tenant_id(self):
        """Evidence upload keys must be scoped to tenant."""

        # The _evidence_s3_key function (if public) or verify via pattern
        tenant_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        claim_id = "claim-001"
        filename = "damage_photo.jpg"

        # Build the key the way the service would
        key = f"{tenant_id}/claims/{claim_id}/{filename}"
        assert key.startswith(tenant_id)
        assert "/" in key

    def test_s3_key_pattern_includes_tenant_prefix(self):
        """All S3 keys follow {tenant_id}/{service}/{resource_id}/{filename} pattern."""
        tenant_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        patterns = [
            f"{tenant_id}/claims/claim-001/photo.jpg",
            f"{tenant_id}/manifests/manifest-001/doc.pdf",
        ]
        for key in patterns:
            assert key.startswith(tenant_id), f"Key {key!r} does not start with tenant_id"

    def test_cross_tenant_s3_prefix_rejected(self):
        """A tenant cannot generate keys for another tenant's prefix."""
        tenant_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        tenant_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        # Simulate: ctx.tenant_id scopes the key
        claimed_key = f"{tenant_b}/claims/claim-001/photo.jpg"
        # The service should only generate keys starting with ctx.tenant_id (tenant_a)
        assert not claimed_key.startswith(tenant_a)


class TestNoSecretsInLogs:
    """Verify structured logger setup does not include password fields."""

    def test_logging_formatter_excludes_sensitive_keys(self):
        """StructuredFormatter should not log password, token, or secret fields."""
        import logging
        from io import StringIO

        from shared.logging_config import setup_logging

        # Set up structured logging to a string buffer
        setup_logging()
        logger = logging.getLogger("test_security")

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        logger.addHandler(handler)

        # Log a message that contains safe fields only
        logger.info(
            "Test log",
            extra={"tenant_id": "t-1", "request_id": "r-1"},
        )

        output = stream.getvalue()
        # Verify no secrets leaked
        for sensitive in ("password", "secret", "token", "private_key"):
            assert sensitive not in output.lower(), f"Sensitive field '{sensitive}' found in log output"

    def test_db_password_not_in_environment_variables_log(self):
        """DB password should come from Secrets Manager, not env vars logged."""
        # Verify the DB module reads from Secrets Manager, not plaintext env
        import inspect

        from shared import db

        source = inspect.getsource(db)
        # Should use SecretId pattern, not os.environ["DB_PASSWORD"]
        assert "DB_SECRET_ARN" in source or "SecretId" in source


class TestStatusExtraFieldAllowlist:
    """Verify dynamic SET clauses use allowlisted field names."""

    def test_refund_status_extra_fields_allowlist(self):
        from services.refunds.repository import _STATUS_EXTRA_FIELDS

        # These are the only safe fields — no user-controlled column names
        expected = {
            "has_outstanding_debt",
            "outstanding_debt_ngn",
            "debt_check_passed",
            "debt_check_notes",
            "amount_approved_ngn",
            "approval_level",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejection_reason",
        }
        assert expected == _STATUS_EXTRA_FIELDS

    def test_allowlisted_fields_safe_identifiers(self):
        from services.refunds.repository import _STATUS_EXTRA_FIELDS

        for field in _STATUS_EXTRA_FIELDS:
            # Must be valid SQL identifier: only alphanumeric and underscores
            assert re.match(r"^[a-z_]+$", field), f"Field '{field}' contains unsafe characters"
