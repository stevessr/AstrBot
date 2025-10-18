"""
Matrix Protocol Adapter for AstrBot

This adapter provides Matrix protocol support with End-to-End Encryption (E2EE)
using vodozemac via matrix-nio.
"""

from .matrix_adapter import MatrixPlatformAdapter
from .matrix_event import MatrixPlatformEvent

__all__ = ["MatrixPlatformAdapter", "MatrixPlatformEvent"]
