"""
Matrix Web Client Plugin

提供独立的 Web 服务器，支持：
1. OAuth2/OIDC 授权码流程登录
2. SSO 登录支持
3. 完整的 Matrix 客户端界面
4. 调试和配置功能
"""

import asyncio
import os

from quart import Quart

from astrbot.api import logger
from astrbot.api.star import Context, Star, register

# 导入客户端管理器
from .client_manager import MatrixClientManager
from .routes import setup_routes


@register("matrix_web_client", "AstrBot Team", "Matrix 完整 Web 客户端", "1.0.0")
class MatrixWebClient(Star):
    """Matrix Web Client Plugin"""

    def __init__(self, context: Context, config=None):
        super().__init__(context, config)
        self.app: Quart | None = None
        self.server_task: asyncio.Task | None = None
        self.client_manager = MatrixClientManager()

        # 从配置中获取端口、主机和 OAuth2 客户端 ID
        plugin_config = (
            self.context.get_config()
            .get("plugin_config", {})
            .get("matrix_web_client", {})
        )
        self.port = plugin_config.get("port", 8766)  # 独立端口
        self.host = plugin_config.get("host", "0.0.0.0")
        self.oauth2_client_id = plugin_config.get(
            "oauth2_client_id", ""
        )  # OAuth2 客户端 ID

    async def initialize(self):
        """初始化插件，启动 Web 服务器"""
        logger.info("Initializing Matrix Web Client Plugin...")

        # 加载持久化的会话
        self.client_manager.load_sessions()

        # 创建 Quart 应用
        self.app = Quart(
            __name__,
            static_folder=os.path.join(os.path.dirname(__file__), "static"),
            template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        )

        # 设置路由
        setup_routes(self.app, self.client_manager, self.oauth2_client_id)

        # 启动服务器
        self.server_task = asyncio.create_task(self._run_server())

        logger.info(f"Matrix Web Client started on http://{self.host}:{self.port}")

    async def terminate(self):
        """终止插件，关闭 Web 服务器"""
        logger.info("Terminating Matrix Web Client Plugin...")

        # 保存会话到磁盘
        self.client_manager.save_sessions()

        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass

        # 关闭所有 Matrix 客户端连接
        await self.client_manager.close_all_clients()

        logger.info("Matrix Web Client terminated")

    async def _run_server(self):
        """运行 Web 服务器"""
        try:
            await self.app.run_task(
                host=self.host,
                port=self.port,
                debug=False,
            )
        except Exception as e:
            logger.error(f"Web server error: {e}")
