"""
Matrix 配置与初始化组件
"""

import uuid
from astrbot.api import logger


class MatrixConfig:
    def __init__(self, config: dict):
        """Initialize Matrix configuration.

        Supported authentication methods: 'password', 'token', and 'oauth2'.
        """
        self.config = config or {}
        self.homeserver = self.config.get("matrix_homeserver", "https://matrix.org")
        self.user_id = self.config.get("matrix_user_id")
        self.password = self.config.get("matrix_password")
        self.access_token = self.config.get("matrix_access_token")
        # Supported methods: password, token, oauth2
        self.auth_method = self.config.get("matrix_auth_method", "password")
        self.device_name = self.config.get("matrix_device_name", "AstrBot")
        self.device_id = self.config.get("matrix_device_id")
        if not self.device_id:
            self.device_id = f"ASTRBOT_{uuid.uuid4().hex[:12].upper()}"
            self.config["matrix_device_id"] = self.device_id
            logger.info(
                f"Auto-generated Matrix device_id: {self.device_id}",
                extra={"plugin_tag": "matrix", "short_levelname": "INFO"},
            )

        # OAuth2 configuration - all parameters auto-discovered from server
        # Only refresh_token is stored locally (auto-saved after login)
        self.refresh_token = self.config.get("matrix_refresh_token")

        # E2EE configuration
        self.enable_e2ee = self.config.get("matrix_enable_e2ee", True)

        # Ensure these attributes exist for other components
        self.store_path = self.config.get("matrix_store_path", "./data/matrix_store")
        self.auto_join_rooms = self.config.get("matrix_auto_join_rooms", True)
        self.sync_timeout = self.config.get("matrix_sync_timeout", 30000)

        self._validate()

    def _validate(self):
        if not self.user_id and self.auth_method != "oauth2":
            raise ValueError(
                "matrix_user_id is required in configuration. Format: @username:homeserver.com"
            )
        if not self.homeserver:
            raise ValueError(
                "matrix_homeserver is required in configuration. Example: https://matrix.org"
            )

        valid_auth_methods = ["password", "token", "oauth2"]
        if self.auth_method not in valid_auth_methods:
            raise ValueError(
                f"Invalid matrix_auth_method: {self.auth_method}. Must be one of: {', '.join(valid_auth_methods)}"
            )

        if self.auth_method == "password" and not self.password:
            raise ValueError(
                "matrix_password is required when matrix_auth_method='password'"
            )

        if self.auth_method == "token" and not self.access_token:
            raise ValueError(
                "matrix_access_token is required when matrix_auth_method='token'"
            )

        # OAuth2: client_id is now optional (can be auto-registered if server supports it)
        # No strict validation needed for OAuth2 mode
