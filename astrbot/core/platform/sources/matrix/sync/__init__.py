"""
Matrix Sync and Event Processing Module

This module handles the Matrix sync loop and event processing:
- sync_manager: Manages the sync loop and event distribution
- event_processor: Processes room events, to-device events, and handles encryption
"""

from .sync_manager import MatrixSyncManager
from .event_processor import MatrixEventProcessor

__all__ = [
    "MatrixSyncManager",
    "MatrixEventProcessor",
]

