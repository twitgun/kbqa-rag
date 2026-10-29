"""兜底模块入口。"""

from kbqa.core.fallback.handler import FallbackHandler
from kbqa.core.fallback.types import FallbackReason, FallbackResult

__all__ = ["FallbackHandler", "FallbackResult", "FallbackReason"]
