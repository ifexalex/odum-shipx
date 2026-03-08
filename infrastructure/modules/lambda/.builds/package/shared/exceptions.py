"""Custom exceptions for the logistics system.

Every exception maps to an RFC 7807 error response with a unique error_code.
See 00_CROSS_CUTTING_STANDARDS.md §1.5 for the full error catalog.
"""


class LogisticsBaseError(Exception):
    """Base exception for all logistics system errors."""

    def __init__(self, message: str, error_code: str, status_code: int = 500):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(self.message)


class AuthenticationRequiredError(LogisticsBaseError):
    def __init__(self) -> None:
        super().__init__(
            message="Authentication required",
            error_code="AUTHENTICATION_REQUIRED",
            status_code=401,
        )


class TenantSuspendedError(LogisticsBaseError):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            message=f"Tenant {tenant_id} is suspended",
            error_code="TENANT_SUSPENDED",
            status_code=403,
        )


class ResourceNotFoundError(LogisticsBaseError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            error_code="RESOURCE_NOT_FOUND",
            status_code=404,
        )


class DuplicateResourceError(LogisticsBaseError):
    def __init__(self, resource_type: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource_type} with identifier '{identifier}' already exists",
            error_code="DUPLICATE_RESOURCE",
            status_code=409,
        )


class IllegalTransitionError(LogisticsBaseError):
    def __init__(self, entity: str, current_state: str, requested_state: str, allowed: list[str]) -> None:
        super().__init__(
            message=f"Cannot transition {entity} from '{current_state}' to '{requested_state}'. Allowed: {allowed}",
            error_code="ILLEGAL_TRANSITION",
            status_code=409,
        )
        self.current_state = current_state
        self.requested_state = requested_state
        self.allowed_transitions = allowed


class BusinessRuleViolationError(LogisticsBaseError):
    def __init__(self, message: str, rule_id: str | None = None) -> None:
        super().__init__(message=message, error_code="BUSINESS_RULE_VIOLATION", status_code=422)
        self.rule_id = rule_id


class SelfApprovalForbiddenError(LogisticsBaseError):
    def __init__(self) -> None:
        super().__init__(
            message="You cannot approve your own submission",
            error_code="SELF_APPROVAL_FORBIDDEN",
            status_code=422,
        )


class PaymentRequiredError(LogisticsBaseError):
    def __init__(self, billing_id: str, outstanding_ngn: float) -> None:
        super().__init__(
            message=f"Payment required. Outstanding: \u20a6{outstanding_ngn:,.2f}",
            error_code="PAYMENT_REQUIRED",
            status_code=422,
        )
        self.billing_id = billing_id
        self.outstanding_ngn = outstanding_ngn


class UsageLimitExceededError(LogisticsBaseError):
    def __init__(self, limit_type: str, current: int, maximum: int) -> None:
        super().__init__(
            message=f"Usage limit exceeded for {limit_type}: {current}/{maximum}",
            error_code="USAGE_LIMIT_EXCEEDED",
            status_code=429,
        )
        self.limit_type = limit_type
        self.current = current
        self.maximum = maximum


class InsufficientPermissionsError(LogisticsBaseError):
    def __init__(self, action: str, required_role: str = "") -> None:
        if required_role:
            message = f"Insufficient permissions for {action}. Required role: {required_role}"
        else:
            message = action  # caller passed a full message as the first arg
        super().__init__(
            message=message,
            error_code="INSUFFICIENT_PERMISSIONS",
            status_code=403,
        )


class ApprovalThresholdExceededError(LogisticsBaseError):
    def __init__(self, message_or_amount, threshold: float = 0, required_role: str = "") -> None:
        if isinstance(message_or_amount, str) and not threshold:
            message = message_or_amount
        else:
            message = f"Amount ${message_or_amount} exceeds threshold ${threshold}. Requires {required_role}."
        super().__init__(
            message=message,
            error_code="APPROVAL_THRESHOLD_EXCEEDED",
            status_code=403,
        )


class ExternalServiceError(LogisticsBaseError):
    def __init__(self, service_name: str, detail: str = "") -> None:
        super().__init__(
            message=f"External service '{service_name}' unavailable. {detail}".strip(),
            error_code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
        )


class IdempotencyConflictError(LogisticsBaseError):
    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            message=f"Request with idempotency key '{idempotency_key}' is already being processed",
            error_code="IDEMPOTENCY_CONFLICT",
            status_code=409,
        )


class ValidationError(LogisticsBaseError):
    def __init__(self, message: str, field_errors: dict | None = None) -> None:
        super().__init__(message=message, error_code="VALIDATION_ERROR", status_code=422)
        self.field_errors = field_errors or {}
