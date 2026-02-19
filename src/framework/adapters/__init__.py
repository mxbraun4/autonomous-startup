"""Layer I - Domain adapters."""

from src.framework.adapters.base import BaseDomainAdapter
from src.framework.adapters.startup_vc import StartupVCAdapter
from src.framework.adapters.web_product import WebProductAdapter

__all__ = [
    "BaseDomainAdapter",
    "StartupVCAdapter",
    "WebProductAdapter",
]
