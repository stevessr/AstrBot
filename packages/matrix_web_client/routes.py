"""
Matrix Web Client 路由模块
"""

from quart import jsonify, request

from astrbot.api import logger


def setup_routes(app, client_manager, oauth2_client_id=""):
    """设置所有 Web 路由"""

    # 将 OAuth2 客户端 ID 存储在应用上下文中
    app.config["OAUTH2_CLIENT_ID"] = oauth2_client_id

    @app.route("/")
    async def index():
        """主页 - Matrix 客户端界面"""
        from quart import render_template

        return await render_template("index.html")

    @app.route("/api/astrbot-config", methods=["GET"])
    async def get_astrbot_matrix_configs():
        """获取 AstrBot 配置的 Matrix 账户"""
        from astrbot.core.config.astrbot_config import AstrBotConfig

        try:
            if not AstrBotConfig:
                return jsonify(
                    {"success": False, "error": "AstrBotConfig not available"}
                )

            # 加载 AstrBot 配置
            config = AstrBotConfig()

            # 获取平台配置
            platforms = config.get("platform", [])
            matrix_configs = []

            for platform in platforms:
                if platform.get("type") == "matrix" and platform.get("enable"):
                    matrix_config = {
                        "id": platform.get("id"),
                        "name": platform.get("matrix_bot_name", "Matrix Bot"),
                        "homeserver": platform.get("matrix_homeserver"),
                        "user_id": platform.get("matrix_user_id"),
                        "device_id": platform.get("matrix_device_id"),
                        "device_name": platform.get("matrix_device_name", "AstrBot"),
                        "auth_method": platform.get("matrix_auth_method", "password"),
                        "access_token": platform.get("matrix_access_token", ""),
                        "store_path": platform.get(
                            "matrix_store_path", "./data/matrix_store"
                        ),
                        "auto_join_rooms": platform.get("matrix_auto_join_rooms", True),
                        "sync_timeout": platform.get("matrix_sync_timeout", 30000),
                        "enable_threading": platform.get("matrix_enable_threading", True),
                    }
                    matrix_configs.append(matrix_config)

            return jsonify({"success": True, "matrix_configs": matrix_configs})

        except Exception as e:
            logger.error(f"Failed to get AstrBot Matrix configs: {e}")
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/discover", methods=["POST"])
    async def discover_server():
        """发现服务器配置（包括 OAuth2/OIDC 配置）"""

        import aiohttp

        data = await request.get_json()
        homeserver = data.get("homeserver", "https://matrix.org")

        try:
            async with aiohttp.ClientSession() as session:
                # 获取服务器配置
                async with session.get(
                    f"{homeserver}/.well-known/matrix/client"
                ) as resp:
                    if resp.status == 200:
                        well_known = await resp.json()
                        base_url = well_known.get("m.homeserver", {}).get(
                            "base_url", homeserver
                        )
                    else:
                        base_url = homeserver

                # 获取登录流程
                async with session.get(f"{base_url}/_matrix/client/v3/login") as resp:
                    login_flows = await resp.json() if resp.status == 200 else {}

                # 检查 OAuth2/OIDC 支持
                oidc_config = None
                try:
                    async with session.get(
                        f"{base_url}/.well-known/openid-configuration"
                    ) as resp:
                        if resp.status == 200:
                            oidc_config = await resp.json()
                except Exception:
                    pass

                return jsonify(
                    {
                        "success": True,
                        "homeserver": base_url,
                        "login_flows": login_flows.get("flows", []),
                        "oidc_config": oidc_config,
                    }
                )
        except Exception as e:
            logger.error(f"Failed to discover server: {e}")
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/login/password", methods=["POST"])
    async def login_password():
        """密码登录"""
        from .auth_handlers import handle_password_login

        return await handle_password_login(client_manager)

    @app.route("/api/login/token", methods=["POST"])
    async def login_token():
        """Token 登录"""
        from .auth_handlers import handle_token_login

        return await handle_token_login(client_manager)

    @app.route("/api/login/astrbot-config", methods=["POST"])
    async def login_with_astrbot_config():
        """使用 AstrBot 配置的 Matrix 账户登录"""
        from .auth_handlers import handle_astrbot_config_login

        return await handle_astrbot_config_login(client_manager)

    @app.route("/api/login/oauth2/start", methods=["POST"])
    async def oauth2_start():
        """启动 OAuth2/OIDC 登录流程"""
        from .auth_handlers import handle_oauth2_start

        return await handle_oauth2_start(client_manager)

    @app.route("/api/login/oauth2/callback")
    async def oauth2_callback():
        """OAuth2/OIDC 回调处理"""
        from .auth_handlers import handle_oauth2_callback

        return await handle_oauth2_callback(client_manager)

    @app.route("/api/rooms", methods=["GET"])
    async def get_rooms():
        """获取房间列表"""
        from .room_handlers import handle_get_rooms

        return await handle_get_rooms(client_manager)

    @app.route("/api/room/<room_id>/messages", methods=["GET"])
    async def get_messages(room_id: str):
        """获取房间消息"""
        from .room_handlers import handle_get_messages

        return await handle_get_messages(client_manager, room_id)

    @app.route("/api/room/<room_id>/send", methods=["POST"])
    async def send_message(room_id: str):
        """发送消息"""
        from .room_handlers import handle_send_message

        return await handle_send_message(client_manager, room_id)

    @app.route("/api/upload", methods=["POST"])
    async def upload_file():
        """上传文件到 Matrix 媒体服务器"""
        from .media_handlers import handle_file_upload

        return await handle_file_upload(client_manager)

    @app.route("/api/profile", methods=["GET"])
    async def get_profile():
        """获取用户资料"""
        from .user_handlers import handle_get_profile

        return await handle_get_profile(client_manager)

    @app.route("/api/devices", methods=["GET"])
    async def get_devices():
        """获取设备列表"""
        from .user_handlers import handle_get_devices

        return await handle_get_devices(client_manager)

    @app.route("/api/e2ee/initialize", methods=["POST"])
    async def initialize_e2ee():
        """初始化端到端加密"""
        from .e2ee_handlers import handle_initialize_e2ee

        return await handle_initialize_e2ee(client_manager)

    @app.route("/api/e2ee/status", methods=["GET"])
    async def get_e2ee_status():
        """获取E2EE状态"""
        from .e2ee_handlers import handle_get_e2ee_status

        return await handle_get_e2ee_status(client_manager)

    @app.route("/api/devices/<device_id>/verify", methods=["POST"])
    async def verify_device(device_id: str):
        """验证设备"""
        from .e2ee_handlers import handle_verify_device

        return await handle_verify_device(client_manager, device_id)

    @app.route("/api/devices/verification/<transaction_id>/info", methods=["GET"])
    async def get_verification_info(transaction_id: str):
        """获取验证信息"""
        from .e2ee_handlers import handle_get_verification_info

        return await handle_get_verification_info(client_manager, transaction_id)

    @app.route("/api/devices/verification/<transaction_id>/confirm", methods=["POST"])
    async def confirm_verification(transaction_id: str):
        """确认验证"""
        from .e2ee_handlers import handle_confirm_verification

        return await handle_confirm_verification(client_manager, transaction_id)

    @app.route("/_matrix/media/r0/download/<server_name>/<media_id>", methods=["GET"])
    async def proxy_media_download(server_name: str, media_id: str):
        """代理下载媒体文件，修复跨域问题"""
        from .media_handlers import handle_media_download

        return await handle_media_download(server_name, media_id)

    @app.route("/_matrix/media/r0/thumbnail/<server_name>/<media_id>", methods=["GET"])
    async def proxy_media_thumbnail(server_name: str, media_id: str):
        """代理获取媒体文件缩略图"""
        from .media_handlers import handle_media_thumbnail

        return await handle_media_thumbnail(server_name, media_id)

    return app
