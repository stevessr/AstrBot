"""
用户处理模块
"""

from quart import jsonify, request

from astrbot.api import logger


async def handle_get_profile(client_manager):
    """获取用户资料"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = client_manager.matrix_clients[session_id]
        client = client_data["client"]
        user_id = client_data["user_id"]
        homeserver = client_data.get("homeserver")

        # 获取用户资料
        displayname = await client.get_display_name(user_id)
        avatar_url = await client.get_avatar_url(user_id)

        return jsonify(
            {
                "success": True,
                "user_id": user_id,
                "displayname": displayname,
                "avatar_url": avatar_url,
                "homeserver": homeserver,
            }
        )

    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_get_devices(client_manager):
    """获取设备列表"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = client_manager.matrix_clients[session_id]
        client = client_data["client"]

        # 获取设备列表
        response = await client.get_devices()

        return jsonify({"success": True, "devices": response.get("devices", [])})

    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return jsonify({"success": False, "error": str(e)})
