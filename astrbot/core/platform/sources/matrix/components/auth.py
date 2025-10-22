"""
Matrix 登录认证组件（不依赖 matrix-nio）
支持密码、Token 和 OAuth2 认证
"""

import logging
from typing import Optional

logger = logging.getLogger("astrbot.matrix.auth")


class MatrixAuth:
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.user_id = config.user_id
        self.device_id = config.device_id
        self.password = config.password
        self.access_token = config.access_token
        self.auth_method = config.auth_method
        self.device_name = config.device_name
        self._config_needs_save = False

        # OAuth2 specific attributes
        # All OAuth2 configuration is auto-discovered from server
        self.refresh_token: Optional[str] = getattr(config, "refresh_token", None)
        self.oauth2_handler = None

    def _log(self, level, msg):
        extra = {"plugin_tag": "matrix", "short_levelname": level[:4].upper()}
        if level == "info":
            logger.info(msg, extra=extra)
        elif level == "error":
            logger.error(msg, extra=extra)

    async def login(self):
        """
        Perform login based on configured authentication method
        Supports: password, token, oauth2
        """
        if self.auth_method == "oauth2":
            await self._login_via_oauth2()
        elif self.auth_method == "token":
            await self._login_via_token()
        elif self.auth_method == "password":
            await self._login_via_password()
        else:
            # Auto-detect authentication method
            if self.access_token:
                await self._login_via_token()
            elif self.password:
                await self._login_via_password()
            else:
                raise ValueError(
                    "Either matrix_access_token or matrix_password is required. "
                    "For OAuth2, set matrix_auth_method='oauth2'"
                )

    async def _login_via_password(self):
        self._log("info", "Logging in with password...")
        try:
            response = await self.client.login_password(
                user_id=self.user_id,
                password=self.password,
                device_name=self.device_name,
                device_id=self.device_id,
            )
            self.user_id = response.get("user_id")
            self.device_id = response.get("device_id")
            self.access_token = response.get("access_token")
            self._log("info", f"Successfully logged in as {self.user_id}")
        except Exception as e:
            self._log("error", f"Matrix password login failed: {e}")
            raise RuntimeError(f"Password login failed: {e}")

    async def _login_via_token(self):
        self._log("info", "Logging in with access token...")
        try:
            self.client.restore_login(
                user_id=self.user_id,
                device_id=self.device_id,
                access_token=self.access_token,
            )
            # Validate token by doing a quick sync or whoami
            sync_response = await self.client.sync(timeout=0, full_state=False)
            if "error" in sync_response or "errcode" in sync_response:
                error_msg = sync_response.get("error", "Unknown error")
                raise RuntimeError(f"Token validation failed: {error_msg}")

            whoami = await self.client.whoami()
            self.user_id = whoami.get("user_id", self.user_id)
            self.device_id = whoami.get("device_id", self.device_id)
            self._log("info", f"Successfully logged in as {self.user_id}")
        except Exception as e:
            self._log("error", f"Token validation failed: {e}")
            raise RuntimeError(f"Token validation failed: {e}")

    async def _login_via_oauth2(self):
        """
        Login using OAuth2 authorization code flow
        All OAuth2 configuration is auto-discovered from the homeserver
        """
        self._log("info", "Logging in with OAuth2...")
        self._log("info", "OAuth2 configuration will be auto-discovered from server...")
        try:
            from .oauth2 import MatrixOAuth2

            # Initialize OAuth2 handler - all config auto-discovered
            self.oauth2_handler = MatrixOAuth2(
                client=self.client,
                homeserver=self.config.homeserver,
            )

            # Perform OAuth2 login flow (includes discovery and registration)
            response = await self.oauth2_handler.login()

            # Update credentials
            self.user_id = response.get("user_id")
            self.device_id = response.get("device_id")
            self.access_token = response.get("access_token")
            self.refresh_token = response.get("refresh_token")

            self._log("info", f"✅ Successfully logged in via OAuth2 as {self.user_id}")
            self._config_needs_save = True

        except Exception as e:
            error_msg = str(e)
            self._log("error", f"❌ OAuth2 login failed: {error_msg}")

            # Provide helpful guidance
            if "not supported" in error_msg.lower() or "404" in error_msg:
                self._log(
                    "error",
                    "💡 Suggestion: Change matrix_auth_method to 'password' in your configuration "
                    "and provide matrix_user_id and matrix_password.",
                )

            raise RuntimeError(f"OAuth2 login failed: {e}")

    async def refresh_oauth2_token(self):
        """
        Refresh OAuth2 access token using refresh token
        """
        if not self.oauth2_handler:
            raise RuntimeError("OAuth2 handler not initialized")

        try:
            self._log("info", "Refreshing OAuth2 access token...")
            response = await self.oauth2_handler.refresh_access_token()

            # Update credentials
            self.access_token = response.get("access_token")
            if "refresh_token" in response:
                self.refresh_token = response["refresh_token"]

            self._log("info", "OAuth2 token refreshed successfully")
            self._config_needs_save = True

        except Exception as e:
            self._log("error", f"Failed to refresh OAuth2 token: {e}")
            raise RuntimeError(f"Token refresh failed: {e}")
