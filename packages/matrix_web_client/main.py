"""
Matrix Web Client Plugin

提供独立的 Web 服务器，支持：
1. OAuth2/OIDC 授权码流程登录
2. SSO 登录支持
3. 完整的 Matrix 客户端界面
4. 调试和配置功能
"""

import asyncio
import json
import secrets
from typing import Optional, Dict, Any
from datetime import datetime
from urllib.parse import urlencode
import aiohttp
from quart import Quart, render_template_string, request, jsonify, websocket

from astrbot.api.star import Star, Context, register
from astrbot.api import logger

# 导入 Matrix 客户端组件
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

try:
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient
    from astrbot.core.platform.sources.matrix.components.oauth2 import MatrixOAuth2
except ImportError:
    logger.warning("Matrix client components not found, some features may be limited")
    MatrixHTTPClient = None
    MatrixOAuth2 = None


@register("matrix_web_client", "AstrBot Team", "Matrix 完整 Web 客户端", "1.0.0")
class MatrixWebClient(Star):
    """Matrix Web Client Plugin"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.app: Optional[Quart] = None
        self.server_task: Optional[asyncio.Task] = None
        self.port = 8766  # 独立端口
        self.host = "0.0.0.0"

        # Matrix 客户端状态
        self.matrix_clients: Dict[str, Any] = {}  # session_id -> client_data
        self.active_sessions: Dict[str, Dict] = {}  # session_id -> session_info

        # 持久化存储路径
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.sessions_file = os.path.join(self.data_dir, "sessions.json")
        os.makedirs(self.data_dir, exist_ok=True)

    async def initialize(self):
        """初始化插件，启动 Web 服务器"""
        logger.info("Initializing Matrix Web Client Plugin...")

        # 加载持久化的会话
        self._load_sessions()

        # 创建 Quart 应用
        self.app = Quart(
            __name__,
            static_folder=os.path.join(os.path.dirname(__file__), "static"),
            template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        )

        # 设置路由
        self._setup_routes()

        # 启动服务器
        self.server_task = asyncio.create_task(self._run_server())

        logger.info(f"Matrix Web Client started on http://{self.host}:{self.port}")

    def _load_sessions(self):
        """从文件加载持久化的会话"""
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, "r") as f:
                    data = json.load(f)
                    saved_sessions = data.get("sessions", {})

                    # 恢复会话
                    for session_id, session_info in saved_sessions.items():
                        try:
                            if MatrixHTTPClient:
                                client = MatrixHTTPClient(
                                    homeserver=session_info["homeserver"]
                                )
                                client.restore_login(
                                    user_id=session_info["user_id"],
                                    device_id=session_info.get("device_id"),
                                    access_token=session_info["access_token"],
                                )

                                self.matrix_clients[session_id] = {
                                    "client": client,
                                    "user_id": session_info["user_id"],
                                    "device_id": session_info.get("device_id"),
                                    "access_token": session_info["access_token"],
                                    "homeserver": session_info["homeserver"],
                                }

                                self.active_sessions[session_id] = {
                                    "user_id": session_info["user_id"],
                                    "homeserver": session_info["homeserver"],
                                    "login_time": session_info.get(
                                        "login_time", datetime.now().isoformat()
                                    ),
                                }

                                logger.info(
                                    f"Restored session for {session_info['user_id']}"
                                )
                        except Exception as e:
                            logger.error(f"Failed to restore session {session_id}: {e}")
                            continue

                logger.info(f"Loaded {len(self.matrix_clients)} sessions from disk")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save_sessions(self):
        """保存会话到文件"""
        try:
            sessions_to_save = {}
            for session_id, client_data in self.matrix_clients.items():
                sessions_to_save[session_id] = {
                    "user_id": client_data["user_id"],
                    "device_id": client_data.get("device_id"),
                    "access_token": client_data["access_token"],
                    "homeserver": client_data["homeserver"],
                    "login_time": self.active_sessions.get(session_id, {}).get(
                        "login_time", datetime.now().isoformat()
                    ),
                }

            with open(self.sessions_file, "w") as f:
                json.dump({"sessions": sessions_to_save}, f, indent=2)

            logger.info(f"Saved {len(sessions_to_save)} sessions to disk")
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    async def terminate(self):
        """终止插件，关闭 Web 服务器"""
        logger.info("Terminating Matrix Web Client Plugin...")

        # 保存会话到磁盘
        self._save_sessions()

        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass

        # 关闭所有 Matrix 客户端连接
        for session_id, client_data in self.matrix_clients.items():
            if "client" in client_data:
                await client_data["client"].close()

        logger.info("Matrix Web Client terminated")

    def _setup_routes(self):
        """设置 Web 路由"""

        @self.app.route("/")
        async def index():
            """主页 - Matrix 客户端界面"""
            return await render_template_string(HTML_TEMPLATE)

        @self.app.route("/api/discover", methods=["POST"])
        async def discover_server():
            """发现服务器配置（包括 OAuth2/OIDC 配置）"""
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
                    async with session.get(
                        f"{base_url}/_matrix/client/v3/login"
                    ) as resp:
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

        @self.app.route("/api/login/password", methods=["POST"])
        async def login_password():
            """密码登录"""
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

                    self.matrix_clients[session_id] = {
                        "client": client,
                        "user_id": response.get("user_id"),
                        "device_id": response.get("device_id"),
                        "access_token": response.get("access_token"),
                        "homeserver": homeserver,
                    }

                    self.active_sessions[session_id] = {
                        "user_id": response.get("user_id"),
                        "homeserver": homeserver,
                        "login_time": datetime.now().isoformat(),
                    }

                    # 保存会话到磁盘
                    self._save_sessions()

                    return jsonify(
                        {
                            "success": True,
                            "session_id": session_id,
                            "user_id": response.get("user_id"),
                            "device_id": response.get("device_id"),
                        }
                    )
                else:
                    return jsonify(
                        {"success": False, "error": "Matrix client not available"}
                    )

            except Exception as e:
                logger.error(f"Login failed: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/login/token", methods=["POST"])
        async def login_token():
            """Token 登录"""
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

                    self.matrix_clients[session_id] = {
                        "client": client,
                        "user_id": whoami.get("user_id"),
                        "device_id": whoami.get("device_id"),
                        "access_token": access_token,
                        "homeserver": homeserver,
                    }

                    self.active_sessions[session_id] = {
                        "user_id": whoami.get("user_id"),
                        "homeserver": homeserver,
                        "login_time": datetime.now().isoformat(),
                    }

                    # 保存会话到磁盘
                    self._save_sessions()

                    return jsonify(
                        {
                            "success": True,
                            "session_id": session_id,
                            "user_id": whoami.get("user_id"),
                            "device_id": whoami.get("device_id"),
                        }
                    )
                else:
                    return jsonify(
                        {"success": False, "error": "Matrix client not available"}
                    )

            except Exception as e:
                logger.error(f"Token login failed: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/login/oauth2/start", methods=["POST"])
        async def oauth2_start():
            """启动 OAuth2/OIDC 登录流程"""
            data = await request.get_json()
            homeserver = data.get("homeserver")

            if not homeserver:
                return jsonify({"success": False, "error": "Missing homeserver"})

            try:
                session_id = secrets.token_urlsafe(32)

                if MatrixOAuth2 and MatrixHTTPClient:
                    client = MatrixHTTPClient(homeserver=homeserver)

                    # 使用请求的 host 构建回调 URL，支持不同部署场景
                    request_host = request.host
                    redirect_uri = f"http://{request_host}/api/login/oauth2/callback"

                    # 创建 OAuth2 handler
                    oauth2_handler = MatrixOAuth2(
                        client=client,
                        homeserver=homeserver,
                        redirect_uri=redirect_uri,
                    )

                    # 发现 OAuth2 配置
                    try:
                        # Note: Using private method temporarily until MatrixOAuth2 provides
                        # a public API for manual authorization URL construction
                        await oauth2_handler._discover_oauth_endpoints()
                    except Exception as e:
                        return jsonify(
                            {
                                "success": False,
                                "error": f"OAuth2 not supported on this server: {str(e)}",
                            }
                        )

                    # 生成授权 URL（手动构建）
                    # Note: Using private methods temporarily. These should be exposed as
                    # public API in MatrixOAuth2 for building authorization URLs manually
                    state = oauth2_handler._generate_state()
                    pkce_verifier = oauth2_handler._generate_pkce_verifier()
                    pkce_challenge = oauth2_handler._generate_pkce_challenge(
                        pkce_verifier
                    )

                    auth_params = {
                        "response_type": "code",
                        # TODO: Make client_id configurable or get from dynamic registration
                        # Fallback client_id may not work with all OAuth2 providers
                        "client_id": oauth2_handler.client_id or "matrix-web-client",
                        "redirect_uri": oauth2_handler.redirect_uri,
                        "scope": " ".join(oauth2_handler.scopes),
                        "state": state,
                        "code_challenge": pkce_challenge,
                        "code_challenge_method": "S256",
                    }
                    auth_url = f"{oauth2_handler.authorization_endpoint}?{urlencode(auth_params)}"

                    # 保存会话状态
                    self.active_sessions[session_id] = {
                        "homeserver": homeserver,
                        "oauth2_handler": oauth2_handler,
                        "oauth2_state": state,
                        "pkce_verifier": pkce_verifier,
                        "start_time": datetime.now().isoformat(),
                    }

                    return jsonify(
                        {
                            "success": True,
                            "session_id": session_id,
                            "authorization_url": auth_url,
                        }
                    )
                else:
                    return jsonify(
                        {"success": False, "error": "OAuth2 support not available"}
                    )

            except Exception as e:
                logger.error(f"OAuth2 start failed: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/login/oauth2/callback")
        async def oauth2_callback():
            """OAuth2/OIDC 回调处理"""
            code = request.args.get("code")
            state = request.args.get("state")
            error = request.args.get("error")

            if error:
                return f"<html><body><h1>认证失败</h1><p>{error}</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

            if not code or not state:
                return "<html><body><h1>认证失败</h1><p>Missing authorization code or state</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

            # 验证 state 参数 (CSRF protection)
            session_id = None
            for sid, session_data in self.active_sessions.items():
                if session_data.get("oauth2_state") == state:
                    session_id = sid
                    break

            if not session_id:
                return "<html><body><h1>认证失败</h1><p>Invalid state parameter (CSRF)</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

            # 获取 OAuth2 handler 和 PKCE verifier
            session_data = self.active_sessions[session_id]
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
                    "client_id": oauth2_handler.client_id or "matrix-web-client",
                    "code_verifier": pkce_verifier,
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        oauth2_handler.token_endpoint, data=token_data
                    ) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.error(f"Token exchange failed: {error_text}")
                            return f"<html><body><h1>认证失败</h1><p>Token exchange failed</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

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
                    self.matrix_clients[session_id] = {
                        "client": client,
                        "user_id": whoami.get("user_id"),
                        "device_id": whoami.get("device_id"),
                        "access_token": access_token,
                        "homeserver": session_data["homeserver"],
                    }

                    # 更新会话状态
                    self.active_sessions[session_id].update(
                        {
                            "user_id": whoami.get("user_id"),
                            "oauth2_state": "completed",
                            "login_time": datetime.now().isoformat(),
                        }
                    )

                    # 保存会话到磁盘
                    self._save_sessions()

                    return """<html><body>
                        <h1>认证成功！</h1>
                        <p>您已成功登录 Matrix。请返回客户端继续...</p>
                        <script>
                            // 通知父窗口登录成功
                            // Using window.location.origin for security instead of '*'
                            if (window.opener) {
                                const targetOrigin = window.location.origin;
                                window.opener.postMessage({type: 'oauth2_success', session_id: '%s'}, targetOrigin);
                            }
                            setTimeout(() => window.close(), 2000);
                        </script>
                    </body></html>""" % (
                        session_id
                    )

            except Exception as e:
                logger.error(f"OAuth2 callback error: {e}")
                return f"<html><body><h1>认证失败</h1><p>{str(e)}</p><script>setTimeout(() => window.close(), 3000);</script></body></html>"

        @self.app.route("/api/rooms", methods=["GET"])
        async def get_rooms():
            """获取房间列表"""
            session_id = request.args.get("session_id")

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 获取加入的房间
                sync_response = await client.sync(timeout=0, full_state=True)
                rooms = sync_response.get("rooms", {}).get("join", {})

                room_list = []
                for room_id, room_data in rooms.items():
                    room_info = {
                        "room_id": room_id,
                        "name": self._get_room_name(room_data),
                        "avatar": None,
                        "last_message": self._get_last_message(room_data),
                        "unread_count": self._get_unread_count(room_data),
                    }
                    room_list.append(room_info)

                return jsonify({"success": True, "rooms": room_list})

            except Exception as e:
                logger.error(f"Failed to get rooms: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/room/<room_id>/messages", methods=["GET"])
        async def get_messages(room_id: str):
            """获取房间消息"""
            session_id = request.args.get("session_id")
            limit = int(request.args.get("limit", 50))

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 获取房间消息
                response = await client.room_messages(
                    room_id=room_id,
                    limit=limit,
                    direction="b",  # backwards
                )

                messages = []
                for event in response.get("chunk", []):
                    if event.get("type") == "m.room.message":
                        messages.append(
                            {
                                "event_id": event.get("event_id"),
                                "sender": event.get("sender"),
                                "timestamp": event.get("origin_server_ts"),
                                "content": event.get("content", {}),
                            }
                        )

                return jsonify(
                    {
                        "success": True,
                        "messages": messages,
                        "start": response.get("start"),
                        "end": response.get("end"),
                    }
                )

            except Exception as e:
                logger.error(f"Failed to get messages: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/room/<room_id>/send", methods=["POST"])
        async def send_message(room_id: str):
            """发送消息"""
            session_id = request.args.get("session_id")
            data = await request.get_json()
            message = data.get("message")
            msgtype = data.get("msgtype", "m.text")

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            if not message:
                return jsonify({"success": False, "error": "Missing message"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 构建消息内容
                content = {"msgtype": msgtype, "body": message}

                # 如果是文件/图片/视频/音频消息，添加额外字段
                if msgtype in ["m.image", "m.file", "m.video", "m.audio"]:
                    url = data.get("url")
                    info = data.get("info", {})
                    if url:
                        content["url"] = url
                        content["info"] = info

                # 发送消息
                response = await client.send_message(
                    room_id=room_id, msg_type="m.room.message", content=content
                )

                return jsonify({"success": True, "event_id": response.get("event_id")})

            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/profile", methods=["GET"])
        async def get_profile():
            """获取用户资料"""
            session_id = request.args.get("session_id")

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]
                user_id = client_data["user_id"]

                # 获取用户资料
                displayname = await client.get_display_name(user_id)
                avatar_url = await client.get_avatar_url(user_id)

                return jsonify(
                    {
                        "success": True,
                        "user_id": user_id,
                        "displayname": displayname,
                        "avatar_url": avatar_url,
                    }
                )

            except Exception as e:
                logger.error(f"Failed to get profile: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/devices", methods=["GET"])
        async def get_devices():
            """获取设备列表"""
            session_id = request.args.get("session_id")

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 获取设备列表
                response = await client.get_devices()

                return jsonify(
                    {"success": True, "devices": response.get("devices", [])}
                )

            except Exception as e:
                logger.error(f"Failed to get devices: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/keys/upload", methods=["POST"])
        async def upload_keys():
            """上传加密密钥"""
            session_id = request.args.get("session_id")
            data = await request.get_json()

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 上传密钥
                response = await client.upload_keys(
                    device_keys=data.get("device_keys"),
                    one_time_keys=data.get("one_time_keys"),
                )

                return jsonify({"success": True, "response": response})

            except Exception as e:
                logger.error(f"Failed to upload keys: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/keys/query", methods=["POST"])
        async def query_keys():
            """查询用户密钥"""
            session_id = request.args.get("session_id")
            data = await request.get_json()

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 查询密钥
                response = await client.query_keys(
                    device_keys=data.get("device_keys", {}), timeout=data.get("timeout")
                )

                return jsonify({"success": True, "response": response})

            except Exception as e:
                logger.error(f"Failed to query keys: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/keys/claim", methods=["POST"])
        async def claim_keys():
            """声明一次性密钥"""
            session_id = request.args.get("session_id")
            data = await request.get_json()

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 声明密钥
                response = await client.claim_keys(
                    one_time_keys=data.get("one_time_keys", {}),
                    timeout=data.get("timeout"),
                )

                return jsonify({"success": True, "response": response})

            except Exception as e:
                logger.error(f"Failed to claim keys: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/upload", methods=["POST"])
        async def upload_file():
            """上传文件"""
            session_id = request.args.get("session_id")

            if not session_id or session_id not in self.matrix_clients:
                return jsonify({"success": False, "error": "Invalid session"})

            try:
                files = await request.files
                if "file" not in files:
                    return jsonify({"success": False, "error": "No file provided"})

                file = files["file"]
                file_data = file.read()  # Not async in Quart

                client_data = self.matrix_clients[session_id]
                client = client_data["client"]

                # 上传文件
                response = await client.upload_file(
                    data=file_data,
                    content_type=file.content_type or "application/octet-stream",
                    filename=file.filename,
                )

                return jsonify(
                    {
                        "success": True,
                        "content_uri": response.get("content_uri"),
                        "filename": file.filename,
                        "content_type": file.content_type,
                        "size": len(file_data),
                    }
                )

            except Exception as e:
                logger.error(f"Failed to upload file: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route("/api/logout", methods=["POST"])
        async def logout():
            """登出"""
            data = await request.get_json()
            session_id = data.get("session_id")

            if not session_id:
                return jsonify({"success": False, "error": "Missing session_id"})

            try:
                if session_id in self.matrix_clients:
                    client_data = self.matrix_clients[session_id]
                    client = client_data["client"]

                    # 登出
                    await client.logout()
                    await client.close()

                    del self.matrix_clients[session_id]

                if session_id in self.active_sessions:
                    del self.active_sessions[session_id]

                # 保存会话到磁盘
                self._save_sessions()

                return jsonify({"success": True})

            except Exception as e:
                logger.error(f"Logout failed: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.websocket("/ws")
        async def websocket_handler():
            """WebSocket 连接用于实时同步"""
            session_id = websocket.args.get("session_id")

            if not session_id or session_id not in self.matrix_clients:
                await websocket.close(1008, "Invalid session")
                return

            client_data = self.matrix_clients[session_id]
            client = client_data["client"]

            try:
                # 保持连接并发送同步事件
                while True:
                    sync_response = await client.sync(timeout=30000)
                    await websocket.send(json.dumps(sync_response))

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.close(1011, str(e))

    def _get_room_name(self, room_data: Dict) -> str:
        """从房间数据中提取房间名称"""
        state_events = room_data.get("state", {}).get("events", [])
        for event in state_events:
            if event.get("type") == "m.room.name":
                return event.get("content", {}).get("name", "Unnamed Room")
        return "Unnamed Room"

    def _get_last_message(self, room_data: Dict) -> Optional[str]:
        """获取最后一条消息"""
        timeline_events = room_data.get("timeline", {}).get("events", [])
        for event in reversed(timeline_events):
            if event.get("type") == "m.room.message":
                return event.get("content", {}).get("body", "")
        return None

    def _get_unread_count(self, room_data: Dict) -> int:
        """获取未读消息数"""
        return room_data.get("unread_notifications", {}).get("notification_count", 0)

    async def _run_server(self):
        """运行 Web 服务器"""
        try:
            await self.app.run_task(host=self.host, port=self.port)
        except asyncio.CancelledError:
            logger.info("Web server cancelled")
        except Exception as e:
            logger.error(f"Web server error: {e}")


# HTML 模板 - 完整的 Matrix 客户端界面
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Matrix Web Client</title>
    <!-- Markdown rendering -->
    <script src="https://cdn.jsdelivr.net/npm/markdown-it@13.0.2/dist/markdown-it.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f5f5;
            height: 100vh;
            overflow: hidden;
        }
        
        .container {
            display: flex;
            height: 100vh;
        }
        
        /* 登录界面 */
        .login-container {
            max-width: 500px;
            margin: 50px auto;
            padding: 30px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .login-container h1 {
            margin-bottom: 30px;
            color: #333;
            text-align: center;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 500;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #4CAF50;
        }
        
        .btn {
            width: 100%;
            padding: 12px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            cursor: pointer;
            margin-bottom: 10px;
        }
        
        .btn:hover {
            background: #45a049;
        }
        
        .btn-secondary {
            background: #2196F3;
        }
        
        .btn-secondary:hover {
            background: #0b7dda;
        }
        
        .btn-oauth {
            background: #FF5722;
        }
        
        .btn-oauth:hover {
            background: #e64a19;
        }
        
        .tabs {
            display: flex;
            margin-bottom: 20px;
            border-bottom: 2px solid #ddd;
        }
        
        .tab {
            flex: 1;
            padding: 12px;
            text-align: center;
            cursor: pointer;
            color: #666;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
        }
        
        .tab.active {
            color: #4CAF50;
            border-bottom-color: #4CAF50;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        /* 客户端界面 */
        .sidebar {
            width: 300px;
            background: #2c3e50;
            color: white;
            display: flex;
            flex-direction: column;
        }
        
        .sidebar-header {
            padding: 20px;
            background: #1a252f;
            border-bottom: 1px solid #34495e;
        }
        
        .sidebar-header h2 {
            font-size: 18px;
            margin-bottom: 10px;
        }
        
        .user-info {
            display: flex;
            align-items: center;
            font-size: 14px;
            color: #95a5a6;
        }
        
        .room-list {
            flex: 1;
            overflow-y: auto;
        }
        
        .room-item {
            padding: 15px 20px;
            border-bottom: 1px solid #34495e;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .room-item:hover {
            background: #34495e;
        }
        
        .room-item.active {
            background: #34495e;
        }
        
        .room-name {
            font-weight: 500;
            margin-bottom: 5px;
        }
        
        .room-last-message {
            font-size: 12px;
            color: #95a5a6;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: white;
        }
        
        .chat-header {
            padding: 20px;
            border-bottom: 1px solid #ddd;
            background: white;
        }
        
        .chat-header h3 {
            font-size: 18px;
            color: #333;
        }
        
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #fafafa;
        }
        
        .message {
            margin-bottom: 15px;
            max-width: 70%;
        }
        
        .message.own {
            margin-left: auto;
        }
        
        .message-sender {
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }
        
        .message-content {
            padding: 10px 15px;
            border-radius: 8px;
            background: white;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            word-wrap: break-word;
        }
        
        .message-content img {
            max-width: 300px;
            max-height: 300px;
            border-radius: 4px;
            margin: 5px 0;
        }
        
        .message-content .file-attachment {
            display: inline-flex;
            align-items: center;
            padding: 8px 12px;
            background: #f0f0f0;
            border-radius: 4px;
            text-decoration: none;
            color: #333;
            margin: 5px 0;
        }
        
        .message-content .sticker {
            max-width: 150px;
            max-height: 150px;
        }
        
        .message.own .message-content {
            background: #4CAF50;
            color: white;
        }
        
        .message.own .message-content a {
            color: #e8f5e9;
        }
        
        .message-time {
            font-size: 11px;
            color: #999;
            margin-top: 5px;
        }
        
        .message-input {
            padding: 20px;
            border-top: 1px solid #ddd;
            background: white;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        
        .message-input input[type="text"] {
            flex: 1;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 20px;
            font-size: 14px;
        }
        
        .message-input input[type="file"] {
            display: none;
        }
        
        .message-input .file-btn {
            padding: 10px 15px;
            background: #2196F3;
            color: white;
            border: none;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
        }
        
        .message-input button {
            padding: 12px 24px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 20px;
            cursor: pointer;
        }
        
        .error {
            color: #f44336;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .success {
            color: #4CAF50;
            margin-top: 10px;
            font-size: 14px;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        
        .hidden {
            display: none !important;
        }
        
        /* 密钥管理模态框 */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }
        
        .modal-content {
            background-color: white;
            margin: 5% auto;
            padding: 20px;
            border-radius: 8px;
            width: 80%;
            max-width: 600px;
            max-height: 80vh;
            overflow-y: auto;
        }
        
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #ddd;
        }
        
        .modal-header h2 {
            margin: 0;
            color: #333;
        }
        
        .close-btn {
            font-size: 28px;
            font-weight: bold;
            color: #aaa;
            cursor: pointer;
            background: none;
            border: none;
        }
        
        .close-btn:hover {
            color: #000;
        }
        
        .key-section {
            margin-bottom: 20px;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 4px;
        }
        
        .key-section h3 {
            margin-top: 0;
            color: #555;
            font-size: 16px;
        }
        
        .key-info {
            font-size: 12px;
            color: #666;
            margin-bottom: 10px;
        }
        
        .key-actions {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        
        .key-actions button {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        
        .btn-primary {
            background: #4CAF50;
            color: white;
        }
        
        .btn-secondary {
            background: #2196F3;
            color: white;
        }
        
        .btn-warning {
            background: #FF9800;
            color: white;
        }
        
        .key-input {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: monospace;
            font-size: 12px;
            margin-top: 10px;
        }
    </style>
</head>
<body>
    <!-- 登录界面 -->
    <div id="loginContainer" class="login-container">
        <h1>Matrix Web Client</h1>
        
        <div class="tabs">
            <div class="tab active" onclick="switchTab('password')">密码登录</div>
            <div class="tab" onclick="switchTab('token')">Token 登录</div>
            <div class="tab" onclick="switchTab('oauth2')">OAuth2/SSO</div>
        </div>
        
        <!-- 密码登录 -->
        <div id="passwordTab" class="tab-content active">
            <div class="form-group">
                <label>Homeserver</label>
                <input type="text" id="homeserver1" value="https://matrix.org" placeholder="https://matrix.org">
            </div>
            <div class="form-group">
                <label>用户名</label>
                <input type="text" id="username" placeholder="@user:matrix.org">
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" id="password" placeholder="密码">
            </div>
            <button class="btn" onclick="loginWithPassword()">登录</button>
        </div>
        
        <!-- Token 登录 -->
        <div id="tokenTab" class="tab-content">
            <div class="form-group">
                <label>Homeserver</label>
                <input type="text" id="homeserver2" value="https://matrix.org" placeholder="https://matrix.org">
            </div>
            <div class="form-group">
                <label>Access Token</label>
                <input type="text" id="accessToken" placeholder="syt_...">
            </div>
            <div class="form-group">
                <label>User ID (可选)</label>
                <input type="text" id="userId" placeholder="@user:matrix.org">
            </div>
            <button class="btn btn-secondary" onclick="loginWithToken()">登录</button>
        </div>
        
        <!-- OAuth2/SSO 登录 -->
        <div id="oauth2Tab" class="tab-content">
            <div class="form-group">
                <label>Homeserver</label>
                <input type="text" id="homeserver3" value="https://matrix.org" placeholder="https://matrix.org">
            </div>
            <button class="btn btn-oauth" onclick="loginWithOAuth2()">使用 OAuth2/SSO 登录</button>
            <p style="margin-top: 15px; color: #666; font-size: 14px;">
                点击后将打开新窗口进行 OAuth2/OIDC 授权。适用于需要 SSO 登录的服务器。
            </p>
        </div>
        
        <div id="loginError" class="error hidden"></div>
        <div id="loginSuccess" class="success hidden"></div>
    </div>
    
    <!-- 客户端界面 -->
    <div id="clientContainer" class="container hidden">
        <div class="sidebar">
            <div class="sidebar-header">
                <h2>Matrix Client</h2>
                <div class="user-info" id="userInfo">
                    加载中...
                </div>
                <button onclick="showKeyManagement()" style="margin-top: 10px; padding: 6px 12px; background: #FF9800; color: white; border: none; border-radius: 4px; cursor: pointer; width: 100%;">
                    🔐 密钥管理
                </button>
            </div>
            <div class="room-list" id="roomList">
                <div class="loading">加载房间列表...</div>
            </div>
        </div>
        
        <div class="main-content">
            <div class="chat-header" id="chatHeader">
                <h3>选择一个房间开始聊天</h3>
            </div>
            <div class="messages" id="messages">
                <div class="loading">选择一个房间查看消息</div>
            </div>
            <div class="message-input hidden" id="messageInput">
                <input type="file" id="fileInput" accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.txt">
                <button class="file-btn" onclick="document.getElementById('fileInput').click()">📎</button>
                <input type="text" id="messageText" placeholder="输入消息 (支持 Markdown)..." onkeypress="handleMessageKeyPress(event)">
                <button onclick="sendMessage()">发送</button>
            </div>
        </div>
    </div>
    
    <!-- 密钥管理模态框 -->
    <div id="keyManagementModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>🔐 密钥管理</h2>
                <button class="close-btn" onclick="closeKeyManagement()">&times;</button>
            </div>
            
            <div class="key-section">
                <h3>📤 上传密钥</h3>
                <p class="key-info">上传设备密钥和一次性密钥到服务器用于端到端加密</p>
                <textarea id="deviceKeys" class="key-input" rows="4" placeholder='{"user_id": "@user:server", "device_id": "DEVICE", ...}'></textarea>
                <textarea id="oneTimeKeys" class="key-input" rows="3" placeholder='{"curve25519:AAAAAQ": "base64+encoded+key", ...}'></textarea>
                <div class="key-actions">
                    <button class="btn-primary" onclick="uploadKeys()">上传密钥</button>
                </div>
                <div id="uploadResult"></div>
            </div>
            
            <div class="key-section">
                <h3>🔍 查询密钥</h3>
                <p class="key-info">查询指定用户的密钥信息</p>
                <input type="text" id="queryUserId" class="key-input" placeholder="@user:server.org">
                <div class="key-actions">
                    <button class="btn-secondary" onclick="queryKeys()">查询密钥</button>
                </div>
                <div id="queryResult"></div>
            </div>
            
            <div class="key-section">
                <h3>🎯 声明一次性密钥</h3>
                <p class="key-info">为指定用户声明一次性密钥</p>
                <textarea id="claimKeysInput" class="key-input" rows="3" placeholder='{"@user:server": {"DEVICE": "signed_curve25519"}}'></textarea>
                <div class="key-actions">
                    <button class="btn-warning" onclick="claimKeys()">声明密钥</button>
                </div>
                <div id="claimResult"></div>
            </div>
            
            <div class="key-section">
                <h3>ℹ️ 说明</h3>
                <p class="key-info">
                    • 设备密钥用于建立加密会话<br>
                    • 一次性密钥用于初始化加密通道<br>
                    • 查询密钥可以获取其他用户的公钥<br>
                    • 声明密钥用于与新设备建立加密<br>
                    • 完整的 E2EE 需要配合加密库使用
                </p>
            </div>
        </div>
    </div>
    
    <script>
        let sessionId = null;
        let currentRoomId = null;
        let ws = null;
        
        // Initialize markdown parser
        const md = window.markdownit({
            html: false,
            linkify: true,
            breaks: true
        });
        
        function switchTab(tabName) {
            // 更新标签
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            
            event.target.classList.add('active');
            document.getElementById(tabName + 'Tab').classList.add('active');
        }
        
        async function loginWithPassword() {
            const homeserver = document.getElementById('homeserver1').value;
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            if (!homeserver || !username || !password) {
                showError('请填写所有字段');
                return;
            }
            
            try {
                const response = await fetch('/api/login/password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({homeserver, username, password})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    sessionId = data.session_id;
                    showSuccess('登录成功！');
                    setTimeout(() => showClient(), 1000);
                } else {
                    showError('登录失败: ' + data.error);
                }
            } catch (e) {
                showError('登录失败: ' + e.message);
            }
        }
        
        async function loginWithToken() {
            const homeserver = document.getElementById('homeserver2').value;
            const accessToken = document.getElementById('accessToken').value;
            const userId = document.getElementById('userId').value;
            
            if (!homeserver || !accessToken) {
                showError('请填写 Homeserver 和 Access Token');
                return;
            }
            
            try {
                const response = await fetch('/api/login/token', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({homeserver, access_token: accessToken, user_id: userId})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    sessionId = data.session_id;
                    showSuccess('登录成功！');
                    setTimeout(() => showClient(), 1000);
                } else {
                    showError('登录失败: ' + data.error);
                }
            } catch (e) {
                showError('登录失败: ' + e.message);
            }
        }
        
        async function loginWithOAuth2() {
            const homeserver = document.getElementById('homeserver3').value;
            
            if (!homeserver) {
                showError('请填写 Homeserver');
                return;
            }
            
            try {
                const response = await fetch('/api/login/oauth2/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({homeserver})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    sessionId = data.session_id;
                    
                    // 监听来自 OAuth2 窗口的消息
                    window.addEventListener('message', (event) => {
                        if (event.data.type === 'oauth2_success' && event.data.session_id === sessionId) {
                            showSuccess('OAuth2 认证成功！');
                            setTimeout(() => showClient(), 1000);
                        }
                    });
                    
                    // 打开 OAuth2 授权窗口
                    const authWindow = window.open(
                        data.authorization_url, 
                        'oauth2',
                        'width=600,height=700'
                    );
                    
                    showSuccess('请在新窗口中完成授权...');
                } else {
                    showError('启动 OAuth2 失败: ' + data.error);
                }
            } catch (e) {
                showError('启动 OAuth2 失败: ' + e.message);
            }
        }
        
        async function showClient() {
            document.getElementById('loginContainer').classList.add('hidden');
            document.getElementById('clientContainer').classList.remove('hidden');
            
            // 加载用户信息
            await loadProfile();
            
            // 加载房间列表
            await loadRooms();
            
            // 建立 WebSocket 连接
            connectWebSocket();
        }
        
        async function loadProfile() {
            try {
                const response = await fetch(`/api/profile?session_id=${sessionId}`);
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('userInfo').textContent = data.displayname || data.user_id;
                }
            } catch (e) {
                console.error('Failed to load profile:', e);
            }
        }
        
        async function loadRooms() {
            try {
                const response = await fetch(`/api/rooms?session_id=${sessionId}`);
                const data = await response.json();
                
                if (data.success) {
                    const roomList = document.getElementById('roomList');
                    roomList.innerHTML = '';
                    
                    data.rooms.forEach(room => {
                        const div = document.createElement('div');
                        div.className = 'room-item';
                        div.onclick = () => selectRoom(room.room_id, room.name);
                        div.innerHTML = `
                            <div class="room-name">${room.name}</div>
                            <div class="room-last-message">${room.last_message || '暂无消息'}</div>
                        `;
                        roomList.appendChild(div);
                    });
                }
            } catch (e) {
                console.error('Failed to load rooms:', e);
            }
        }
        
        async function selectRoom(roomId, roomName) {
            currentRoomId = roomId;
            
            // 更新选中状态
            document.querySelectorAll('.room-item').forEach(item => item.classList.remove('active'));
            event.target.closest('.room-item').classList.add('active');
            
            // 更新标题
            document.getElementById('chatHeader').innerHTML = `<h3>${roomName}</h3>`;
            
            // 显示消息输入框
            document.getElementById('messageInput').classList.remove('hidden');
            
            // 加载消息
            await loadMessages(roomId);
        }
        
        async function loadMessages(roomId) {
            try {
                const response = await fetch(`/api/room/${roomId}/messages?session_id=${sessionId}&limit=50`);
                const data = await response.json();
                
                if (data.success) {
                    const messagesDiv = document.getElementById('messages');
                    messagesDiv.innerHTML = '';
                    
                    data.messages.reverse().forEach(msg => {
                        addMessageToUI(msg);
                    });
                    
                    // 滚动到底部
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                }
            } catch (e) {
                console.error('Failed to load messages:', e);
            }
        }
        
        function addMessageToUI(msg) {
            const messagesDiv = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = 'message';
            
            const time = new Date(msg.timestamp).toLocaleTimeString();
            const content = msg.content || {};
            const msgtype = content.msgtype || 'm.text';
            
            let messageHtml = '';
            
            // 处理不同类型的消息
            if (msgtype === 'm.image') {
                const url = content.url || '';
                const body = content.body || 'Image';
                const mxcUrl = url.replace('mxc://', '');
                const httpUrl = `${window.location.protocol}//${window.location.host}/_matrix/media/r0/download/${mxcUrl}`;
                messageHtml = `<img src="${httpUrl}" alt="${escapeHtml(body)}" title="${escapeHtml(body)}">`;
            } else if (msgtype === 'm.file') {
                const url = content.url || '';
                const body = content.body || 'File';
                const mxcUrl = url.replace('mxc://', '');
                const httpUrl = `${window.location.protocol}//${window.location.host}/_matrix/media/r0/download/${mxcUrl}`;
                messageHtml = `<a href="${httpUrl}" class="file-attachment" download="${escapeHtml(body)}">📎 ${escapeHtml(body)}</a>`;
            } else if (msgtype === 'm.sticker') {
                const url = content.url || '';
                const body = content.body || 'Sticker';
                const mxcUrl = url.replace('mxc://', '');
                const httpUrl = `${window.location.protocol}//${window.location.host}/_matrix/media/r0/download/${mxcUrl}`;
                messageHtml = `<img src="${httpUrl}" alt="${escapeHtml(body)}" class="sticker">`;
            } else if (msgtype === 'm.video') {
                const url = content.url || '';
                const body = content.body || 'Video';
                const mxcUrl = url.replace('mxc://', '');
                const httpUrl = `${window.location.protocol}//${window.location.host}/_matrix/media/r0/download/${mxcUrl}`;
                messageHtml = `<video controls style="max-width: 400px;"><source src="${httpUrl}"></video><br>${escapeHtml(body)}`;
            } else if (msgtype === 'm.audio') {
                const url = content.url || '';
                const body = content.body || 'Audio';
                const mxcUrl = url.replace('mxc://', '');
                const httpUrl = `${window.location.protocol}//${window.location.host}/_matrix/media/r0/download/${mxcUrl}`;
                messageHtml = `<audio controls><source src="${httpUrl}"></audio><br>${escapeHtml(body)}`;
            } else {
                // 文本消息 - 渲染 markdown
                const body = content.body || '';
                const formatted = content.formatted_body;
                const format = content.format;
                
                if (format === 'org.matrix.custom.html' && formatted) {
                    // 已有 HTML 格式
                    messageHtml = formatted;
                } else {
                    // 使用 markdown 渲染
                    messageHtml = md.render(body);
                }
            }
            
            div.innerHTML = `
                <div class="message-sender">${escapeHtml(msg.sender)}</div>
                <div class="message-content">${messageHtml}</div>
                <div class="message-time">${time}</div>
            `;
            
            messagesDiv.appendChild(div);
        }
        
        async function sendMessage() {
            const messageText = document.getElementById('messageText').value;
            const fileInput = document.getElementById('fileInput');
            
            if (!currentRoomId) {
                return;
            }
            
            try {
                // 如果有文件，先上传文件
                if (fileInput.files.length > 0) {
                    const file = fileInput.files[0];
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    // 上传文件
                    const uploadResp = await fetch(`/api/upload?session_id=${sessionId}`, {
                        method: 'POST',
                        body: formData
                    });
                    
                    const uploadData = await uploadResp.json();
                    
                    if (uploadData.success) {
                        // 根据文件类型发送消息
                        const contentType = uploadData.content_type || '';
                        let msgtype = 'm.file';
                        
                        if (contentType.startsWith('image/')) {
                            msgtype = 'm.image';
                        } else if (contentType.startsWith('video/')) {
                            msgtype = 'm.video';
                        } else if (contentType.startsWith('audio/')) {
                            msgtype = 'm.audio';
                        }
                        
                        // 发送文件消息
                        const response = await fetch(`/api/room/${currentRoomId}/send?session_id=${sessionId}`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                message: uploadData.filename,
                                msgtype: msgtype,
                                url: uploadData.content_uri,
                                info: {
                                    size: uploadData.size,
                                    mimetype: uploadData.content_type
                                }
                            })
                        });
                        
                        if (response.ok) {
                            fileInput.value = '';
                        }
                    }
                } else if (messageText) {
                    // 发送文本消息
                    const response = await fetch(`/api/room/${currentRoomId}/send?session_id=${sessionId}`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({message: messageText})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        document.getElementById('messageText').value = '';
                    }
                }
            } catch (e) {
                console.error('Failed to send message:', e);
            }
        }
        
        function handleMessageKeyPress(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }
        
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws?session_id=${sessionId}`);
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                // 处理同步事件
                handleSyncEvent(data);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            ws.onclose = () => {
                console.log('WebSocket closed');
                // 可以实现重连逻辑
            };
        }
        
        function handleSyncEvent(syncData) {
            // 处理新消息
            const rooms = syncData.rooms?.join || {};
            for (const [roomId, roomData] of Object.entries(rooms)) {
                const timeline = roomData.timeline?.events || [];
                timeline.forEach(event => {
                    if (event.type === 'm.room.message' && roomId === currentRoomId) {
                        addMessageToUI({
                            event_id: event.event_id,
                            sender: event.sender,
                            timestamp: event.origin_server_ts,
                            content: event.content
                        });
                        
                        // 滚动到底部
                        const messagesDiv = document.getElementById('messages');
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                    }
                });
            }
        }
        
        function showError(message) {
            const errorDiv = document.getElementById('loginError');
            errorDiv.textContent = message;
            errorDiv.classList.remove('hidden');
            setTimeout(() => errorDiv.classList.add('hidden'), 5000);
        }
        
        function showSuccess(message) {
            const successDiv = document.getElementById('loginSuccess');
            successDiv.textContent = message;
            successDiv.classList.remove('hidden');
            setTimeout(() => successDiv.classList.add('hidden'), 3000);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function showKeyManagement() {
            document.getElementById('keyManagementModal').style.display = 'block';
        }
        
        function closeKeyManagement() {
            document.getElementById('keyManagementModal').style.display = 'none';
        }
        
        async function uploadKeys() {
            const deviceKeysText = document.getElementById('deviceKeys').value;
            const oneTimeKeysText = document.getElementById('oneTimeKeys').value;
            const resultDiv = document.getElementById('uploadResult');
            
            try {
                let deviceKeys = null;
                let oneTimeKeys = null;
                
                if (deviceKeysText) {
                    deviceKeys = JSON.parse(deviceKeysText);
                }
                if (oneTimeKeysText) {
                    oneTimeKeys = JSON.parse(oneTimeKeysText);
                }
                
                const response = await fetch(`/api/keys/upload?session_id=${sessionId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({device_keys: deviceKeys, one_time_keys: oneTimeKeys})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    resultDiv.innerHTML = '<div class="success">✅ 密钥上传成功！<br><pre>' + JSON.stringify(data.response, null, 2) + '</pre></div>';
                } else {
                    resultDiv.innerHTML = '<div class="error">❌ 上传失败: ' + data.error + '</div>';
                }
            } catch (e) {
                resultDiv.innerHTML = '<div class="error">❌ 错误: ' + e.message + '</div>';
            }
        }
        
        async function queryKeys() {
            const userId = document.getElementById('queryUserId').value;
            const resultDiv = document.getElementById('queryResult');
            
            if (!userId) {
                resultDiv.innerHTML = '<div class="error">❌ 请输入用户 ID</div>';
                return;
            }
            
            try {
                const deviceKeys = {};
                deviceKeys[userId] = [];
                
                const response = await fetch(`/api/keys/query?session_id=${sessionId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({device_keys: deviceKeys})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    resultDiv.innerHTML = '<div class="success">✅ 查询成功！<br><pre style="max-height: 200px; overflow-y: auto;">' + JSON.stringify(data.response, null, 2) + '</pre></div>';
                } else {
                    resultDiv.innerHTML = '<div class="error">❌ 查询失败: ' + data.error + '</div>';
                }
            } catch (e) {
                resultDiv.innerHTML = '<div class="error">❌ 错误: ' + e.message + '</div>';
            }
        }
        
        async function claimKeys() {
            const claimKeysText = document.getElementById('claimKeysInput').value;
            const resultDiv = document.getElementById('claimResult');
            
            try {
                const oneTimeKeys = JSON.parse(claimKeysText);
                
                const response = await fetch(`/api/keys/claim?session_id=${sessionId}`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({one_time_keys: oneTimeKeys})
                });
                
                const data = await response.json();
                
                if (data.success) {
                    resultDiv.innerHTML = '<div class="success">✅ 声明成功！<br><pre style="max-height: 200px; overflow-y: auto;">' + JSON.stringify(data.response, null, 2) + '</pre></div>';
                } else {
                    resultDiv.innerHTML = '<div class="error">❌ 声明失败: ' + data.error + '</div>';
                }
            } catch (e) {
                resultDiv.innerHTML = '<div class="error">❌ 错误: ' + e.message + '</div>';
            }
        }
        
        // 监听文件选择
        document.addEventListener('DOMContentLoaded', function() {
            const fileInput = document.getElementById('fileInput');
            if (fileInput) {
                fileInput.addEventListener('change', function() {
                    if (this.files.length > 0) {
                        const fileName = this.files[0].name;
                        document.getElementById('messageText').placeholder = `已选择: ${fileName}`;
                    }
                });
            }
            
            // 点击模态框外部关闭
            const modal = document.getElementById('keyManagementModal');
            window.onclick = function(event) {
                if (event.target == modal) {
                    modal.style.display = 'none';
                }
            }
        });
    </script>
</body>
</html>
"""
