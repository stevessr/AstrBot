"""
Matrix Adapter Components

This package contains modular components for the Matrix platform adapter:

- auth: Authentication handling (password, token, OAuth2)
- config: Configuration management
- sender: Message sending functionality
- receiver: Message receiving and conversion
- event_handler: Event handling utilities
- event_processor: Event processing and filtering
- sync_manager: Sync loop management
- utils: Utility functions
- markdown_utils: Markdown to HTML conversion
- oauth2: OAuth2 authentication flow
- e2ee: End-to-end encryption support

Each component is designed to be independent and focused on a specific responsibility.
"""

from .auth import MatrixAuth
from .config import MatrixConfig
from .sender import MatrixSender
from .receiver import MatrixReceiver
from .event_handler import MatrixEventHandler
from .event_processor import MatrixEventProcessor
from .sync_manager import MatrixSyncManager
from .utils import MatrixUtils

__all__ = [
    "MatrixAuth",
    "MatrixConfig",
    "MatrixSender",
    "MatrixReceiver",
    "MatrixEventHandler",
    "MatrixEventProcessor",
    "MatrixSyncManager",
    "MatrixUtils",
]

