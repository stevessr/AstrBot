"""
Matrix 配置与初始化组件
"""

import uuid
from astrbot.api import logger


class MatrixConfig:
    def __init__(self, config: dict):
        """Initialize Matrix configuration.

        OAuth2/SSO login has been removed. Supported methods are 'password' and 'token'.
        """
        self.config = config or {}
        self.homeserver = self.config.get("matrix_homeserver", "https://matrix.org")
        self.user_id = self.config.get("matrix_user_id")
        self.password = self.config.get("matrix_password")
        self.access_token = self.config.get("matrix_access_token")
        # Only supported methods now: password, token
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

        # Note: E2EE support has been removed from AstrBot; configuration key removed.

        # Ensure these attributes exist for other components
        self.store_path = self.config.get("matrix_store_path", "./data/matrix_store")
        self.auto_join_rooms = self.config.get("matrix_auto_join_rooms", True)
        self.sync_timeout = self.config.get("matrix_sync_timeout", 30000)

        self._validate()

    def _validate(self):
        if not self.user_id:
            raise ValueError(
                "matrix_user_id is required in configuration. Format: @username:homeserver.com"
            )
        if not self.homeserver:
            raise ValueError(
                "matrix_homeserver is required in configuration. Example: https://matrix.org"
            )

        valid_auth_methods = ["password", "token"]
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

        # If a user used an older config without specifying auth_method,
        # ensure at least one credential is present.
        if not self.password and not self.access_token:
            raise ValueError(
                "Either matrix_password or matrix_access_token is required. Please configure at least one authentication credential."
            )
