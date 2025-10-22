"""
Matrix Message Sending Module

This module handles sending messages and events to Matrix rooms:
- Message sending with support for text, images, files, and replies
- Markdown to HTML conversion for formatted messages
- E2EE encrypted message sending support
"""

from .sender import MatrixSender

__all__ = [
    "MatrixSender",
]

