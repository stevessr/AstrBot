"""
房间处理模块
"""

from quart import jsonify, request

from astrbot.api import logger


async def handle_get_rooms(client_manager):
    """获取房间列表"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = client_manager.matrix_clients[session_id]
        client = client_data["client"]

        # 获取加入的房间
        sync_response = await client.sync(timeout=0, full_state=True)
        rooms = sync_response.get("rooms", {}).get("join", {})

        room_list = []
        for room_id, room_data in rooms.items():
            room_info = {
                "room_id": room_id,
                "name": _get_room_name(room_data),
                "avatar": None,
                "last_message": _get_last_message(room_data),
                "unread_count": _get_unread_count(room_data),
            }
            room_list.append(room_info)

        return jsonify({"success": True, "rooms": room_list})

    except Exception as e:
        logger.error(f"Failed to get rooms: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_get_messages(client_manager, room_id: str):
    """获取房间消息"""
    session_id = request.args.get("session_id")
    limit = int(request.args.get("limit", 50))

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = client_manager.matrix_clients[session_id]
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


async def handle_send_message(client_manager, room_id: str):
    """发送消息"""
    session_id = request.args.get("session_id")
    data = await request.get_json()
    message = data.get("message")
    msgtype = data.get("msgtype", "m.text")

    if not session_id or session_id not in client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    if not message:
        return jsonify({"success": False, "error": "Missing message"})

    try:
        client_data = client_manager.matrix_clients[session_id]
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


def _get_room_name(room_data):
    """获取房间名称"""
    # 优先使用房间名称
    name_event = room_data.get("state", {}).get("events", [])
    for event in name_event:
        if event.get("type") == "m.room.name":
            return event.get("content", {}).get("name")

    # 其次使用别名
    for event in name_event:
        if event.get("type") == "m.room.canonical_alias":
            return event.get("content", {}).get("alias")

    # 最后使用房间 ID 的简化版本
    room_id = room_data.get("room_id", "")
    if room_id.startswith("!"):
        return room_id[1:].split(":")[0]

    return room_id


def _get_last_message(room_data):
    """获取最后一条消息"""
    timeline = room_data.get("timeline", {}).get("events", [])
    for event in reversed(timeline):
        if event.get("type") == "m.room.message":
            content = event.get("content", {})
            msgtype = content.get("msgtype", "")

            if msgtype == "m.text":
                return content.get("body", "")
            elif msgtype == "m.image":
                return "[图片]"
            elif msgtype == "m.file":
                return f"[文件: {content.get('body', '')}]"
            elif msgtype == "m.video":
                return "[视频]"
            elif msgtype == "m.audio":
                return "[音频]"
            else:
                return f"[{msgtype}]"

    return ""


def _get_unread_count(room_data):
    """获取未读消息数量"""
    # 这里可以实现更复杂的未读计数逻辑
    # 目前返回一个简单的计数
    timeline = room_data.get("timeline", {}).get("events", [])
    unread_count = 0

    # 简单计算：计算时间线中的消息数量
    # 实际实现需要考虑已读标记等
    for event in timeline:
        if event.get("type") == "m.room.message":
            unread_count += 1

    return unread_count
