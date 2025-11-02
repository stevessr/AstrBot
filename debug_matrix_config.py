#!/usr/bin/env python3
"""
Matrix 配置诊断工具

检查 Matrix 配置是否正确，并测试连接
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from nio import AsyncClient


async def test_matrix_connection(
    homeserver: str, user_id: str, access_token: str, device_id: str
):
    """测试 Matrix 连接"""

    print("\n" + "=" * 60)
    print("Matrix 连接测试")
    print("=" * 60)

    print("\n配置信息:")
    print(f"  Homeserver: {homeserver}")
    print(f"  User ID: {user_id}")
    print(f"  Device ID: {device_id}")
    print(
        f"  Access Token: {access_token[:20]}..."
        if access_token
        else "  Access Token: (空)"
    )

    # 创建客户端
    client = AsyncClient(
        homeserver=homeserver,
        user=user_id,
        device_id=device_id,
    )

    try:
        # 测试 1: restore_login
        print("\n测试 1: restore_login")
        try:
            client.restore_login(
                user_id=user_id,
                device_id=device_id,
                access_token=access_token,
            )
            print("  ✓ restore_login 成功")
        except Exception as e:
            print(f"  ✗ restore_login 失败: {e}")
            return False

        # 测试 2: whoami
        print("\n测试 2: whoami")
        try:
            whoami = await client.whoami()
            print(f"  响应类型: {type(whoami).__name__}")
            print(f"  响应内容: {whoami}")

            if hasattr(whoami, "user_id"):
                print(f"  ✓ User ID: {whoami.user_id}")
            if hasattr(whoami, "device_id"):
                print(f"  ✓ Device ID: {whoami.device_id}")

            from nio.responses import WhoamiError

            if isinstance(whoami, WhoamiError):
                print("  ✗ whoami 失败")
                if hasattr(whoami, "message"):
                    print(f"     错误信息: {whoami.message}")
                if hasattr(whoami, "status_code"):
                    print(f"     状态码: {whoami.status_code}")
        except Exception as e:
            print(f"  ✗ whoami 异常: {e}")

        # 测试 3: sync
        print("\n测试 3: sync (timeout=0)")
        try:
            sync_response = await client.sync(timeout=0, full_state=False)
            print(f"  响应类型: {type(sync_response).__name__}")

            from nio.responses import SyncResponse, SyncError

            if isinstance(sync_response, SyncResponse):
                print("  ✓ Sync 成功")
                if hasattr(sync_response, "next_batch"):
                    print(f"    Next batch: {sync_response.next_batch[:20]}...")
                if hasattr(sync_response, "rooms"):
                    print(f"    房间数: {len(sync_response.rooms.join)}")
            elif isinstance(sync_response, SyncError):
                print("  ✗ Sync 失败")
                print(f"    错误对象: {sync_response}")
                print(f"    错误类型: {type(sync_response)}")
                print(f"    可用属性: {dir(sync_response)}")

                if hasattr(sync_response, "message"):
                    print(f"    message: {sync_response.message}")
                if hasattr(sync_response, "status_code"):
                    print(f"    status_code: {sync_response.status_code}")
                if hasattr(sync_response, "transport_response"):
                    print(f"    transport_response: {sync_response.transport_response}")

                # 尝试获取更多信息
                try:
                    print(f"    repr: {repr(sync_response)}")
                    print(f"    str: {str(sync_response)}")
                except Exception as e:
                    print(f"    无法获取字符串表示: {e}")

                return False
            else:
                print(f"  ? 未知响应类型: {type(sync_response)}")
                return False

        except Exception as e:
            print(f"  ✗ Sync 异常: {e}")
            import traceback

            print(traceback.format_exc())
            return False

        print("\n" + "=" * 60)
        print("✓ 所有测试通过！Matrix 配置正确。")
        print("=" * 60)
        return True

    finally:
        await client.close()


async def main():
    """主函数"""

    # 从配置文件读取
    try:
        from astrbot.core.config.astrbot_config import AstrBotConfig

        config = AstrBotConfig()
        platforms = config.get("platform", [])

        matrix_config = None
        for platform in platforms:
            if platform.get("type") == "matrix" and platform.get("enable"):
                matrix_config = platform
                break

        if not matrix_config:
            print("错误: 未找到启用的 Matrix 平台配置")
            return 1

        homeserver = matrix_config.get("matrix_homeserver")
        user_id = matrix_config.get("matrix_user_id")
        access_token = matrix_config.get("matrix_access_token")
        device_id = matrix_config.get("matrix_device_id")

        if not all([homeserver, user_id, access_token, device_id]):
            print("错误: Matrix 配置不完整")
            print(f"  homeserver: {bool(homeserver)}")
            print(f"  user_id: {bool(user_id)}")
            print(f"  access_token: {bool(access_token)}")
            print(f"  device_id: {bool(device_id)}")
            return 1

        success = await test_matrix_connection(
            homeserver, user_id, access_token, device_id
        )
        return 0 if success else 1

    except Exception as e:
        print(f"错误: {e}")
        import traceback

        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
