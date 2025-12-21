"""
Matrix 客户端管理器
"""

import json
import os
from datetime import datetime
from typing import Any

from astrbot.api import logger


class MatrixClientManager:
    """Matrix 客户端管理器"""

    def __init__(self):
        # Matrix 客户端状态
        self.matrix_clients: dict[str, Any] = {}  # session_id -> client_data
        self.active_sessions: dict[str, dict] = {}  # session_id -> session_info

        # 持久化存储路径
        self.data_dir = os.path.join(os.path.dirname(__file__), "data")
        self.sessions_file = os.path.join(self.data_dir, "sessions.json")
        os.makedirs(self.data_dir, exist_ok=True)

    def load_sessions(self):
        """从文件加载持久化的会话"""
        try:
            # 导入 Matrix 客户端组件
            import sys

            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

            from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient

            if os.path.exists(self.sessions_file):
                with open(self.sessions_file) as f:
                    data = json.load(f)
                    saved_sessions = data.get("sessions", {})

                    # 恢复会话
                    for session_id, session_info in saved_sessions.items():
                        try:
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
                                f"已恢复会话 {session_info['user_id']}"
                            )
                        except Exception as e:
                            logger.error(f"恢复会话 {session_id} 失败: {e}")
                            continue

                logger.info(f"从磁盘加载了 {len(self.matrix_clients)} 个会话")
        except Exception as e:
            logger.error(f"加载会话失败: {e}")

    def save_sessions(self):
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

            logger.info(f"保存了 {len(sessions_to_save)} 个会话到磁盘")
        except Exception as e:
            logger.error(f"保存会话失败: {e}")

    def get_client(self, session_id: str) -> dict[str, Any] | None:
        """获取客户端数据"""
        return self.matrix_clients.get(session_id)

    def add_client(self, session_id: str, client_data: dict[str, Any]):
        """添加客户端数据"""
        self.matrix_clients[session_id] = client_data

    def remove_client(self, session_id: str):
        """移除客户端数据"""
        if session_id in self.matrix_clients:
            del self.matrix_clients[session_id]
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]

    def add_session(self, session_id: str, session_data: dict[str, Any]):
        """添加会话数据"""
        self.active_sessions[session_id] = session_data

    async def close_all_clients(self):
        """关闭所有 Matrix 客户端连接"""
        for session_id, client_data in self.matrix_clients.items():
            if "client" in client_data:
                try:
                    await client_data["client"].close()
                except Exception as e:
                    logger.error(f"关闭客户端 {session_id} 时出错: {e}")
