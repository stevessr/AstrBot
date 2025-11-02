"""
Matrix Message Receiving Module

This module handles receiving and processing messages from Matrix rooms:
- Message receiving and conversion to AstrBot format
- Support for text, images, files, and reply messages
- E2EE encrypted message decryption support
- Bot mention detection
"""

from .receiver import MatrixReceiver

__all__ = [
    "MatrixReceiver",
]

