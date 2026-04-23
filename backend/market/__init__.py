"""backend.market package.

This package hosts market intelligence modules.
Exports are intentionally minimal and stable to avoid import-time failures.
"""

from .client import JobAPIClient, MarketSource, ClientConfig
from .cache_loader import MarketCacheLoader

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "JobAPIClient",
    "MarketSource",
    "ClientConfig",
    "MarketCacheLoader",
]
