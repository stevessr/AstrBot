"""
Matrix Authentication and Authorization Module

This module handles authentication and authorization for the Matrix platform adapter:
- auth: Password and token authentication
- oauth2: OAuth2 authentication flow with auto-discovery
"""

from .auth import MatrixAuth
from .oauth2 import MatrixOAuth2

__all__ = [
    "MatrixAuth",
    "MatrixOAuth2",
]

