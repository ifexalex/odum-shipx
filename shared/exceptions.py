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


class TenantOffboardedError(LogisticsBaseError):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(
            message=f"Tenant {tenant_id} account is closed",
            error_code="TENANT_OFFBOARDED",
            status_code=410,
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
        self.entity = entity
        self.current_state = current_state
        self.requested_state = requested_state
        self.allowed_transitions = allowed

    def __reduce__(self) -> tuple[type["IllegalTransitionError"], tuple[str, str, str, list[str]]]:
        return (type(self), (self.entity, self.current_state, self.requested_state, self.allowed_transitions))


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
    def __init__(self, limit_type: str, current: int | float, maximum: int | float) -> None:
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


class UntrustedOriginError(LogisticsBaseError):
    """A cookie-authenticated request that did not come from one of our own frontends."""

    def __init__(self) -> None:
        super().__init__(
            message="Request origin is not allowed",
            error_code="ORIGIN_NOT_ALLOWED",
            status_code=403,
        )


class RateLimitExceededError(LogisticsBaseError):
    """A client or tenant has sent more requests than its limit allows (shared/rate_limit.py)."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(
            message="Too many requests. Please wait a moment and try again.",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
        )
        # Seconds until the window that refused this request ends, sent as the Retry-After header.
        self.retry_after = max(int(retry_after), 1)


class UnsupportedMediaTypeError(LogisticsBaseError):
    def __init__(self, expected: str = "application/json") -> None:
        super().__init__(
            message=f"Content-Type must be {expected}",
            error_code="UNSUPPORTED_MEDIA_TYPE",
            status_code=415,
        )


class ApprovalThresholdExceededError(LogisticsBaseError):
    def __init__(
        self,
        message: str,
        staff_limit_usd: float = 0,
        staff_limit_ngn: float = 0,
        dollar_rate: float = 0,
        amount_ngn: float = 0,
    ) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_THRESHOLD_EXCEEDED",
            status_code=403,
        )
        self.threshold_details = {
            "staff_limit_usd": staff_limit_usd,
            "staff_limit_ngn": staff_limit_ngn,
            "dollar_rate": dollar_rate,
            "amount_ngn": amount_ngn,
        }


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
    def __init__(self, message: str, field_errors: dict[str, str] | None = None) -> None:
        super().__init__(message=message, error_code="VALIDATION_ERROR", status_code=422)
        self.field_errors = field_errors or {}


class ServiceUnavailableError(LogisticsBaseError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(
            message=f"Service temporarily unavailable. {detail}".strip(),
            error_code="SERVICE_UNAVAILABLE",
            status_code=503,
        )


class MaintenanceModeError(ServiceUnavailableError):
    """503 while a platform admin has ShipX in maintenance mode.

    Its own code, ``MAINTENANCE_MODE``, lets the apps show a maintenance screen instead of telling every user to check
    their connection, which is what a bare 503 shows (audit PA-01).
    """

    def __init__(self) -> None:
        LogisticsBaseError.__init__(
            self,
            message="ShipX is undergoing scheduled maintenance. Please try again shortly.",
            error_code="MAINTENANCE_MODE",
            status_code=503,
        )


class PlatformAdminNotEnrolledError(LogisticsBaseError):
    """403 for a platform-group identity with no active ``platform_user`` row (platform audit Phase 1).

    Membership of the identity provider's ``platform_admin`` group is no longer enough on its own: an owner must invite
    the person into the directory, which also gives them a role.
    """

    def __init__(self) -> None:
        super().__init__(
            message="You are not in the platform admin directory. Ask a platform owner to invite you.",
            error_code="PLATFORM_ADMIN_NOT_ENROLLED",
            status_code=403,
        )


class StepUpRequiredError(LogisticsBaseError):
    """403 for a dangerous platform action sent without a fresh re-authentication (platform audit C-29).

    The console answers it by asking the admin to re-authenticate, then retries with the step-up token it receives.
    """

    def __init__(self) -> None:
        super().__init__(
            message="Re-authenticate to confirm this action.",
            error_code="STEP_UP_REQUIRED",
            status_code=403,
        )
