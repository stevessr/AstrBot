"""
Matrix protocol adapter for AstrBot.
"""

from .adapter import MatrixPlatformAdapter
from .event import MatrixPlatformEvent

__all__ = [
    "MatrixPlatformAdapter",
    "MatrixPlatformEvent",
]
