"""
Matrix 登录认证组件（不依赖 matrix-nio）
"""

import logging

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

    def _log(self, level, msg):
        extra = {"plugin_tag": "matrix", "short_levelname": level[:4].upper()}
        if level == "info":
            logger.info(msg, extra=extra)
        elif level == "error":
            logger.error(msg, extra=extra)

    async def login(self):
        if self.auth_method == "token":
            await self._login_via_token()
        elif self.auth_method == "password":
            await self._login_via_password()
        else:
            if self.access_token:
                await self._login_via_token()
            elif self.password:
                await self._login_via_password()
            else:
                raise ValueError(
                    "Either matrix_access_token or matrix_password is required"
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
