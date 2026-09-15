"""Domain exceptions. Each carries a machine-readable code and an HTTP status;
the global handler turns them into the standard error envelope. Messages are
written for humans and never contain internal details."""

from __future__ import annotations


class DocAIError(Exception):
    status_code = 500
    error_code = "INTERNAL_ERROR"
    message = "An unexpected error occurred."
    retryable = False

    def __init__(
        self,
        message: str | None = None,
        *,
        errors: dict | list | None = None,
        error_code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        diagnostics: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.errors = errors or {}
        # Internal, content-free diagnostics. Never included in the API error envelope.
        self.diagnostics = diagnostics or {}
        self.headers = headers or {}
        if error_code:
            self.error_code = error_code
        if status_code:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable


class ValidationFailed(DocAIError):
    status_code = 422
    error_code = "VALIDATION_ERROR"
    message = "Validation failed."


class NotFound(DocAIError):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "The requested resource was not found."


class Conflict(DocAIError):
    status_code = 409
    error_code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class PermissionDenied(DocAIError):
    status_code = 403
    error_code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class UnsupportedFile(ValidationFailed):
    error_code = "UNSUPPORTED_FILE"
    message = "Upload a PDF, JPEG, PNG, TIFF, DOCX, XLSX, XLS, or TXT file."


class CorruptFile(ValidationFailed):
    error_code = "CORRUPT_FILE"
    message = "We couldn't read this file. It may be corrupt or truncated."


class ProtectedFile(ValidationFailed):
    error_code = "PROTECTED_FILE"
    message = "This file is password-protected. Remove the password and re-upload."


class EmptyFile(ValidationFailed):
    error_code = "EMPTY_FILE"
    message = "This file has no readable content."


class DuplicateFile(Conflict):
    error_code = "DUPLICATE_FILE"
    message = "An identical file already exists in this dataset."


class UnsafeWorkbook(ValidationFailed):
    error_code = "UNSAFE_WORKBOOK"
    message = "This workbook contains content we don't process (macros, external links, or embedded objects)."


class UnsafeRegex(ValidationFailed):
    error_code = "UNSAFE_REGEX"
    message = "A rule pattern was rejected as unsafe."


class IntegrationError(DocAIError):
    status_code = 503
    error_code = "INTEGRATION_ERROR"
    message = "An external service is unavailable. Please try again."
    retryable = True


class ThrottledUpstream(IntegrationError):
    status_code = 429
    error_code = "UPSTREAM_THROTTLED"
    message = "The model service is busy. Please retry shortly."


class InvalidModelOutput(DocAIError):
    """The model returned something the Pydantic schema rejected. Never coerced;
    the item is routed to retry/review."""

    status_code = 502
    error_code = "INVALID_MODEL_OUTPUT"
    message = "The model returned an invalid result; the item has been routed for review."
    retryable = True


class ContextLimitExceeded(DocAIError):
    status_code = 422
    error_code = "CONTEXT_LIMIT"
    message = "The document is too large for the selected processing strategy."


class WorkflowConfigError(ValidationFailed):
    error_code = "WORKFLOW_CONFIG_ERROR"
    message = "The workflow configuration is invalid."


class RunStateError(Conflict):
    error_code = "RUN_STATE_ERROR"
    message = "This operation is not allowed in the run's current state."


class SpanMappingFailed(DocAIError):
    status_code = 422
    error_code = "SPAN_MAPPING_FAILED"
    message = "The selected text could not be mapped to a source location."


class NormalizationUnavailable(ValidationFailed):
    error_code = "NORMALIZATION_UNAVAILABLE"
    message = "Scan enhancement is unavailable. Use original input or contact an administrator."


class NormalizationFailed(DocAIError):
    status_code = 422
    error_code = "NORMALIZATION_FAILED"
    message = "Scan enhancement failed and the original input could not be read safely."


class NormalizationLimitExceeded(NormalizationFailed):
    error_code = "NORMALIZATION_LIMIT_EXCEEDED"
    message = "Scan enhancement exceeded its configured processing limits."
