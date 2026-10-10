"""Lumen package alias pointing to course_tutor."""

from course_tutor import LumenCore, check_capabilities, LumenError, __version__
from course_tutor.cli import main

__all__ = ["LumenCore", "check_capabilities", "LumenError", "__version__", "main"]
