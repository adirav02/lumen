"""Structured error hierarchy for Lumen / Course Tutor.

All errors provide machine-readable error codes and structured details.
"""

from typing import Any, Dict, Optional


class LumenError(Exception):
    """Base exception for all Lumen operations."""

    def __init__(
        self,
        message: str,
        error_code: str = "LUMEN_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(LumenError):
    """Raised when input parameters fail schema or semantic validation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="VALIDATION_ERROR", details=details)


class CourseNotFoundError(LumenError):
    """Raised when a specified course does not exist."""

    def __init__(self, course_id: str, details: Optional[Dict[str, Any]] = None):
        d = {"course_id": course_id}
        if details:
            d.update(details)
        super().__init__(f"Course '{course_id}' not found.", error_code="COURSE_NOT_FOUND", details=d)


class SourceNotFoundError(LumenError):
    """Raised when a source or source version does not exist."""

    def __init__(self, source_id: str, details: Optional[Dict[str, Any]] = None):
        d = {"source_id": source_id}
        if details:
            d.update(details)
        super().__init__(f"Source '{source_id}' not found.", error_code="SOURCE_NOT_FOUND", details=d)


class SourceCorruptedError(LumenError):
    """Raised when stored file bytes do not match expected hash."""

    def __init__(self, file_path: str, expected_hash: str, actual_hash: str):
        super().__init__(
            f"File integrity violation for '{file_path}'. Expected SHA-256 {expected_hash}, got {actual_hash}.",
            error_code="SOURCE_CORRUPTED",
            details={
                "file_path": file_path,
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            },
        )


class IdempotencyConflictError(LumenError):
    """Raised when request_id is reused with different request payload."""

    def __init__(self, request_id: str, existing_hash: str, new_hash: str):
        super().__init__(
            f"Idempotency conflict for request '{request_id}': identical request ID reused with different content hash.",
            error_code="IDEMPOTENCY_CONFLICT",
            details={
                "request_id": request_id,
                "existing_hash": existing_hash,
                "new_hash": new_hash,
            },
        )


class StaleRevisionError(LumenError):
    """Raised when an update specifies an outdated entity revision."""

    def __init__(self, entity_type: str, entity_id: str, expected_revision: int, current_revision: int):
        super().__init__(
            f"Stale revision conflict on {entity_type} '{entity_id}'. Expected revision {expected_revision}, current is {current_revision}.",
            error_code="STALE_REVISION",
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            },
        )


class CrossCourseViolationError(LumenError):
    """Raised when an operation attempts to link or access entities across different courses."""

    def __init__(self, entity_type: str, entity_id: str, expected_course: str, actual_course: str):
        super().__init__(
            f"Cross-course boundary violation: {entity_type} '{entity_id}' belongs to course '{actual_course}', but operation is scoped to '{expected_course}'.",
            error_code="CROSS_COURSE_VIOLATION",
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_course": expected_course,
                "actual_course": actual_course,
            },
        )


class UnvalidatedQuestionError(LumenError):
    """Raised when an unvalidated question or rubric is submitted for formal assessment."""

    def __init__(self, exercise_version_id: str, validation_state: str, details: Optional[Dict[str, Any]] = None):
        d = {
            "exercise_version_id": exercise_version_id,
            "validation_state": validation_state,
        }
        if details:
            d.update(details)
        super().__init__(
            f"Exercise version '{exercise_version_id}' is not validated (state: '{validation_state}'). Cannot evaluate assessment with unvalidated material.",
            error_code="UNVALIDATED_QUESTION",
            details=d,
        )


class WorkspaceError(LumenError):
    """Raised when workspace path is invalid, missing, or unwritable."""

    def __init__(self, workspace_path: str, reason: str):
        super().__init__(
            f"Workspace error at '{workspace_path}': {reason}",
            error_code="WORKSPACE_ERROR",
            details={"workspace_path": workspace_path, "reason": reason},
        )


class RestoreIntegrityError(LumenError):
    """Raised when a workspace backup or restore fails integrity checks."""

    def __init__(self, reason: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            f"Restore integrity failed: {reason}",
            error_code="RESTORE_INTEGRITY_ERROR",
            details=details or {},
        )


class WorkspaceDetachedError(LumenError):
    """Raised when an active database handle or workspace has been replaced or detached by an external operation."""

    def __init__(self, workspace_path: str, reason: str = "Database file inode has changed or handle is detached"):
        super().__init__(
            f"Workspace at '{workspace_path}' has been detached: {reason}",
            error_code="WORKSPACE_DETACHED",
            details={"workspace_path": workspace_path, "reason": reason},
        )


class LegacyDuplicateAttemptLinkError(LumenError):
    """Raised when a legacy schema-v4 workspace contains duplicate attempt links in assessment items."""

    def __init__(
        self,
        duplicate_attempt_ids: list,
        affected_items: list,
        details: Optional[Dict[str, Any]] = None,
    ):
        d = {
            "duplicate_attempt_ids": duplicate_attempt_ids,
            "affected_items": affected_items,
        }
        if details:
            d.update(details)
        super().__init__(
            f"Found {len(duplicate_attempt_ids)} legacy duplicate attempt link(s) across {len(affected_items)} assessment items. "
            "Manual resolution required or run repair_legacy_duplicate_links before migration.",
            error_code="LEGACY_DUPLICATE_ATTEMPT_LINK",
            details=d,
        )


class ConflictError(LumenError):
    """Raised when an operation conflicts with the current state of an entity or resolution."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONFLICT_ERROR", details=details or {})

