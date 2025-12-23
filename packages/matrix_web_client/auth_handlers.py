"""
认证处理模块
"""

import secrets
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from quart import jsonify, request

from astrbot.api import logger


async def handle_password_login(client_manager):
    """处理密码登录"""
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient

    data = await request.get_json()
    homeserver = data.get("homeserver")
    username = data.get("username")
    password = data.get("password")
    device_name = data.get("device_name", "Matrix Web Client")

    if not all([homeserver, username, password]):
        return jsonify({"success": False, "error": "Missing required fields"})

    try:
        session_id = secrets.token_urlsafe(32)

        if MatrixHTTPClient:
            client = MatrixHTTPClient(homeserver=homeserver)
            response = await client.login_password(
                user_id=username, password=password, device_name=device_name
            )

            client_manager.add_client(
                session_id,
                {
                    "client": client,
                    "user_id": response.get("user_id"),
                    "device_id": response.get("device_id"),
                    "access_token": response.get("access_token"),
                    "homeserver": homeserver,
                    "e2ee_manager": None,  # Will be initialized on demand
                },
            )

            client_manager.add_session(
                session_id,
                {
                    "user_id": response.get("user_id"),
                    "homeserver": homeserver,
                    "login_time": datetime.now().isoformat(),
                },
            )

            # 保存会话到磁盘
            client_manager.save_sessions()

            return jsonify(
                {
                    "success": True,
                    "session_id": session_id,
                    "user_id": response.get("user_id"),
                    "device_id": response.get("device_id"),
                }
            )
        else:
            return jsonify({"success": False, "error": "Matrix client not available"})

    except Exception as e:
        logger.error(f"Login failed: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_token_login(client_manager):
    """处理 Token 登录"""
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient

    data = await request.get_json()
    homeserver = data.get("homeserver")
    access_token = data.get("access_token")
    user_id = data.get("user_id")
    device_id = data.get("device_id")

    if not all([homeserver, access_token]):
        return jsonify({"success": False, "error": "Missing required fields"})

    try:
        session_id = secrets.token_urlsafe(32)

        if MatrixHTTPClient:
            client = MatrixHTTPClient(homeserver=homeserver)
            client.restore_login(
                user_id=user_id, device_id=device_id, access_token=access_token
            )

            # 验证 token
            whoami = await client.whoami()

            client_manager.add_client(
                session_id,
                {
                    "client": client,
                    "user_id": whoami.get("user_id"),
                    "device_id": whoami.get("device_id"),
                    "access_token": access_token,
                    "homeserver": homeserver,
                    "e2ee_manager": None,  # Will be initialized on demand
                },
            )

            client_manager.add_session(
                session_id,
                {
                    "user_id": whoami.get("user_id"),
                    "homeserver": homeserver,
                    "login_time": datetime.now().isoformat(),
                },
            )

            # 保存会话到磁盘
            client_manager.save_sessions()

            return jsonify(
                {
                    "success": True,
                    "session_id": session_id,
                    "user_id": whoami.get("user_id"),
                    "device_id": whoami.get("device_id"),
                }
            )
        else:
            return jsonify({"success": False, "error": "Matrix client not available"})

    except Exception as e:
        logger.error(f"Token login failed: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_astrbot_config_login(client_manager):
    """使用 AstrBot 配置的 Matrix 账户登录"""
    from astrbot.core.config.astrbot_config import AstrBotConfig
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient
    from astrbot.core.platform.sources.matrix.e2ee import E2EEManager

    data = await request.get_json()
    config_id = data.get("config_id")

    if not config_id:
        return jsonify({"success": False, "error": "Missing config_id"})

    try:
        if not AstrBotConfig:
            return jsonify({"success": False, "error": "AstrBotConfig not available"})

        # 加载 AstrBot 配置
        config = AstrBotConfig()

        # 查找指定的 Matrix 配置
        platforms = config.get("platform", [])
        matrix_config = None

        for platform in platforms:
            if platform.get("type") == "matrix" and platform.get("id") == config_id:
                matrix_config = platform
                break

        if not matrix_config:
            return jsonify(
                {
                    "success": False,
                    "error": f"Matrix config with id '{config_id}' not found",
                }
            )

        if not matrix_config.get("enable"):
            return jsonify({"success": False, "error": "Matrix config is disabled"})

        # 创建会话
        session_id = secrets.token_urlsafe(32)

        if MatrixHTTPClient:
            client = MatrixHTTPClient(homeserver=matrix_config.get("matrix_homeserver"))

            # 根据认证方法登录
            auth_method = matrix_config.get("matrix_auth_method", "password")

            if auth_method == "password":
                # 密码登录
                response = await client.login_password(
                    user_id=matrix_config.get("matrix_user_id"),
                    password=matrix_config.get("matrix_password"),
                    device_name=matrix_config.get(
                        "matrix_device_name", "AstrBot Web Client"
                    ),
                )

                user_id = response.get("user_id")
                device_id = response.get("device_id")
                access_token = response.get("access_token")

            elif auth_method == "token" and matrix_config.get("matrix_access_token"):
                # Token 登录
                client.restore_login(
                    user_id=matrix_config.get("matrix_user_id"),
                    device_id=matrix_config.get("matrix_device_id"),
                    access_token=matrix_config.get("matrix_access_token"),
                )

                # 验证 token
                whoami = await client.whoami()
                user_id = whoami.get("user_id")
                device_id = whoami.get("device_id")
                access_token = matrix_config.get("matrix_access_token")

            else:
                return jsonify(
                    {
                        "success": False,
                        "error": f"Unsupported auth method: {auth_method}",
                    }
                )

            # 保存客户端和会话信息
            client_manager.add_client(
                session_id,
                {
                    "client": client,
                    "user_id": user_id,
                    "device_id": device_id,
                    "access_token": access_token,
                    "homeserver": matrix_config.get("matrix_homeserver"),
                    "config_id": config_id,
                    "config_name": matrix_config.get("matrix_bot_name", "Matrix Bot"),
                    "e2ee_manager": None,  # Will be initialized on demand
                },
            )

            client_manager.add_session(
                session_id,
                {
                    "user_id": user_id,
                    "homeserver": matrix_config.get("matrix_homeserver"),
                    "config_id": config_id,
                    "config_name": matrix_config.get("matrix_bot_name", "Matrix Bot"),
                    "login_time": datetime.now().isoformat(),
                    "login_method": "astrbot_config",
                },
            )

            # 如果启用了 E2EE，初始化 E2EE 管理器
            if matrix_config.get("matrix_enable_e2ee") and E2EEManager:
                try:
                    e2ee_manager = E2EEManager(
                        client=client,
                        user_id=user_id,
                        device_id=device_id,
                        store_path=matrix_config.get("matrix_e2ee_store_path", "./data/matrix_e2ee"),
                        homeserver=matrix_config.get("matrix_homeserver"),
                    )

                    # 初始化 E2EE
                    await e2ee_manager.initialize()

                    # 保存 E2EE 管理器
                    client_manager.matrix_clients[session_id]["e2ee_manager"] = (
                        e2ee_manager
                    )

                    logger.info(f"E2EE initialized for AstrBot config {config_id}")
                except Exception as e:
                    logger.warning(
                        f"Failed to initialize E2EE for AstrBot config {config_id}: {e}"
                    )

            # 保存会话到磁盘
            client_manager.save_sessions()

            return jsonify(
                {
                    "success": True,
                    "session_id": session_id,
                    "user_id": user_id,
                    "device_id": device_id,
                    "config_id": config_id,
                    "config_name": matrix_config.get("matrix_bot_name", "Matrix Bot"),
                    "e2ee_enabled": client_manager.matrix_clients[session_id].get(
                        "e2ee_manager"
                    )
                    is not None,
                }
            )
        else:
            return jsonify({"success": False, "error": "Matrix client not available"})

    except Exception as e:
        logger.error(f"AstrBot config login failed: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_oauth2_start(client_manager):
    """开始 OAuth2/OIDC 登录流程"""
    from datetime import datetime

    from quart import current_app, jsonify, request

    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient
    from astrbot.core.platform.sources.matrix.author.oauth2 import MatrixOAuth2

    data = await request.get_json()
    homeserver = data.get("homeserver")

    if not homeserver:
        return jsonify({"success": False, "error": "Missing homeserver"})

    # 获取配置的 OAuth2 客户端 ID
    configured_client_id = current_app.config.get("OAUTH2_CLIENT_ID", "")

    try:
        session_id = secrets.token_urlsafe(32)

        if MatrixOAuth2 and MatrixHTTPClient:
            client = MatrixHTTPClient(homeserver=homeserver)

            # 使用请求的 host 构建回调 URL，支持不同部署场景
            request_host = request.host
            redirect_uri = f"http://{request_host}/api/login/oauth2/callback"

            # 发现 OAuth2 配置
            try:
                # 创建临时的 OAuth2 handler 只用于发现端点
                temp_oauth2_handler = MatrixOAuth2(
                    client=client,
                    homeserver=homeserver,
                    redirect_uri=redirect_uri,
                )

                # Note: Using private method temporarily until MatrixOAuth2 provides
                # a public API for manual authorization URL construction
                await temp_oauth2_handler._discover_oauth_endpoints()

                # 确定最终使用的客户端 ID
                final_client_id = None

                # 优先使用配置的 client_id
                if configured_client_id:
                    final_client_id = configured_client_id
                    logger.info(f"Using configured client_id: {final_client_id}")
                else:
                    # 尝试动态注册
                    try:
                        logger.info(
                            "No client_id configured, attempting dynamic client registration..."
                        )
                        registration = await temp_oauth2_handler._register_client(
                            redirect_uri
                        )
                        final_client_id = registration["client_id"]
                        logger.info(f"✅ Registered as client: {final_client_id}")
                    except Exception as e:
                        logger.error(f"Dynamic registration failed: {e}")
                        # 使用默认值作为最后的备选
                        final_client_id = "im.fluffychat"
                        logger.info(f"Using default client_id: {final_client_id}")

                # 创建正式的 OAuth2 handler，使用确定的 client_id
                oauth2_handler = MatrixOAuth2(
                    client=client,
                    homeserver=homeserver,
                    client_id=final_client_id,
                    redirect_uri=redirect_uri,
                )

                # 复用发现的端点信息
                oauth2_handler.issuer = temp_oauth2_handler.issuer
                oauth2_handler.authorization_endpoint = (
                    temp_oauth2_handler.authorization_endpoint
                )
                oauth2_handler.token_endpoint = temp_oauth2_handler.token_endpoint
                oauth2_handler.registration_endpoint = (
                    temp_oauth2_handler.registration_endpoint
                )
                oauth2_handler.account_management_uri = (
                    temp_oauth2_handler.account_management_uri
                )

            except Exception as e:
                error_msg = str(e)
                if (
                    "No authentication configuration found in well-known" in error_msg
                    or "No m.authentication found in well-known" in error_msg
                ):
                    return jsonify(
                        {
                            "success": False,
                            "error": "This homeserver does not support OAuth2 authentication. Please use password or token authentication instead.",
                        }
                    )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": f"OAuth2 discovery failed: {error_msg}",
                        }
                    )

            # 生成授权 URL（手动构建）
            # Note: Using private methods temporarily. These should be exposed as
            # public API in MatrixOAuth2 for building authorization URLs manually
            state = oauth2_handler._generate_state()
            pkce_verifier = oauth2_handler._generate_pkce_verifier()
            pkce_challenge = oauth2_handler._generate_pkce_challenge(pkce_verifier)

            auth_params = {
                "response_type": "code",
                "client_id": final_client_id,
                "redirect_uri": oauth2_handler.redirect_uri,
                "scope": " ".join(oauth2_handler.scopes),
                "state": state,
                "code_challenge": pkce_challenge,
                "code_challenge_method": "S256",
            }
            auth_url = (
                f"{oauth2_handler.authorization_endpoint}?{urlencode(auth_params)}"
            )

            # 保存会话状态
            client_manager.add_session(
                session_id,
                {
                    "homeserver": homeserver,
                    "oauth2_handler": oauth2_handler,
                    "oauth2_state": state,
                    "pkce_verifier": pkce_verifier,
                    "start_time": datetime.now().isoformat(),
                },
            )

            return jsonify(
                {
                    "success": True,
                    "session_id": session_id,
                    "authorization_url": auth_url,
                }
            )
        else:
            return jsonify({"success": False, "error": "OAuth2 support not available"})

    except Exception as e:
        logger.error(f"OAuth2 start failed: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_oauth2_callback(client_manager):
    """OAuth2/OIDC 回调处理"""
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient

    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")

    if error:
        return f"<html><body><h1>认证失败</h1><p>{error}</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

    if not code or not state:
        return "<html><body><h1>认证失败</h1><p>Missing authorization code or state</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

    # 验证 state 参数 (CSRF protection)
    session_id = None
    for sid, session_data in client_manager.active_sessions.items():
        if session_data.get("oauth2_state") == state:
            session_id = sid
            break

    if not session_id:
        return "<html><body><h1>认证失败</h1><p>Invalid state parameter (CSRF)</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

    # 获取 OAuth2 handler 和 PKCE verifier
    session_data = client_manager.active_sessions[session_id]
    oauth2_handler = session_data.get("oauth2_handler")
    pkce_verifier = session_data.get("pkce_verifier")

    if not oauth2_handler or not pkce_verifier:
        return "<html><body><h1>认证失败</h1><p>Session expired</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

    try:
        # 交换授权码获取 token
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": oauth2_handler.redirect_uri,
            "client_id": oauth2_handler.client_id or "im.fluffychat",
            "code_verifier": pkce_verifier,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                oauth2_handler.token_endpoint, data=token_data
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Token exchange failed: {error_text}")
                    return "<html><body><h1>认证失败</h1><p>Token exchange failed</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

                token_response = await resp.json()

        access_token = token_response.get("access_token")
        if not access_token:
            return "<html><body><h1>认证失败</h1><p>No access token received</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

        # 使用 access token 创建客户端
        if MatrixHTTPClient:
            client = MatrixHTTPClient(homeserver=session_data["homeserver"])
            client.restore_login(
                user_id=None,  # Will be fetched from whoami
                device_id=None,
                access_token=access_token,
            )

            # 获取用户信息
            whoami = await client.whoami()

            # 保存客户端和会话信息
            client_manager.add_client(
                session_id,
                {
                    "client": client,
                    "user_id": whoami.get("user_id"),
                    "device_id": whoami.get("device_id"),
                    "access_token": access_token,
                    "homeserver": session_data["homeserver"],
                    "e2ee_manager": None,  # Will be initialized on demand
                },
            )

            # 更新会话状态
            client_manager.active_sessions[session_id].update(
                {
                    "user_id": whoami.get("user_id"),
                    "oauth2_state": "completed",
                    "login_time": datetime.now().isoformat(),
                }
            )

            # 保存会话到磁盘
            client_manager.save_sessions()

            return f"""<html><body>
                <h1>认证成功！</h1>
                <p>您已成功登录 Matrix。请返回客户端继续...</p>
                <script>
                    // 通知父窗口登录成功
                    if (window.opener) {{
                        const targetOrigin = window.location.origin;
                        window.opener.postMessage({{type: 'oauth2_success', session_id: '{session_id}'}}, targetOrigin);
                    }}
                    setTimeout(() => window.close(), 2000);
                </script>
            </body></html>"""

    except Exception as e:
        logger.error(f"OAuth2 callback error: {e}")
        return f"<html><body><h1>认证失败</h1><p>{str(e)}</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"
