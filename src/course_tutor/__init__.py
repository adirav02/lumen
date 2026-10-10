"""Lumen - A portable course-learning assistant and evidence-based tutor."""

from .api import LumenCore
from .capabilities import check_capabilities
from .errors import LumenError

__version__ = "0.1.0"
__all__ = ["LumenCore", "check_capabilities", "LumenError", "__version__"]
