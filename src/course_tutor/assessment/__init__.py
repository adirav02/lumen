"""Assessment package initialization."""

from .brief import get_course_brief
from .diagnostic import DiagnosticService

__all__ = ["DiagnosticService", "get_course_brief"]
