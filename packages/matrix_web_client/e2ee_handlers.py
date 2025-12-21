"""
Matrix Web Client E2EE 处理模块
"""

from quart import jsonify, request

from astrbot.api import logger


async def handle_initialize_e2ee(matrix_client_manager):
    """初始化端到端加密"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in matrix_client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        from astrbot.core.platform.sources.matrix.e2ee_manager import MatrixE2EEManager

        client_data = matrix_client_manager.matrix_clients[session_id]
        client = client_data["client"]

        # 检查是否已经初始化
        if client_data.get("e2ee_manager"):
            return jsonify({"success": True, "message": "E2EE already initialized"})

        # 创建E2EE管理器
        if MatrixE2EEManager:
            e2ee_manager = MatrixE2EEManager(
                client=client,
                user_id=client_data["user_id"],
                device_id=client_data["device_id"],
            )

            # 初始化E2EE
            await e2ee_manager.initialize()

            # 保存E2EE管理器
            client_data["e2ee_manager"] = e2ee_manager

            return jsonify(
                {
                    "success": True,
                    "message": "E2EE initialized successfully",
                    "device_keys": e2ee_manager.encryption_manager.identity_keys,
                }
            )
        else:
            return jsonify({"success": False, "error": "E2EE not available"})

    except Exception as e:
        logger.error(f"Failed to initialize E2EE: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_get_e2ee_status(matrix_client_manager):
    """获取E2EE状态"""
    session_id = request.args.get("session_id")
    room_id = request.args.get("room_id")

    if not session_id or session_id not in matrix_client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = matrix_client_manager.matrix_clients[session_id]
        e2ee_manager = client_data.get("e2ee_manager")

        if not e2ee_manager:
            return jsonify(
                {
                    "success": True,
                    "e2ee_enabled": False,
                    "message": "E2EE not initialized",
                }
            )

        # 获取加密状态
        if room_id:
            # 获取房间成员
            response = await client_data["client"].get_room_members(room_id)
            members = []
            for event in response.get("chunk", []):
                if (
                    event.get("type") == "m.room.member"
                    and event.get("content", {}).get("membership") == "join"
                ):
                    members.append(event.get("state_key"))

            status = await e2ee_manager.get_encryption_status(room_id, members)
            return jsonify(
                {
                    "success": True,
                    "e2ee_enabled": True,
                    "room_id": room_id,
                    "encryption_status": status,
                }
            )
        else:
            # 返回基本 E2EE 状态
            return jsonify(
                {
                    "success": True,
                    "e2ee_enabled": True,
                    "device_keys": e2ee_manager.encryption_manager.identity_keys,
                }
            )

    except Exception as e:
        logger.error(f"Failed to get E2EE status: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_verify_device(matrix_client_manager, device_id):
    """验证设备"""
    session_id = request.args.get("session_id")

    # 安全地获取 JSON 数据
    try:
        if request.content_type and "application/json" in request.content_type:
            # silent=True prevents BadRequest on empty body or invalid JSON
            data = await request.get_json(silent=True)
            if data is None:
                data = {}
        else:
            # 如果不是 JSON content-type，尝试解析表单数据
            data = await request.form
            # 转换为字典格式
            data = dict(data)
    except Exception as e:
        logger.warning(f"Failed to parse request data: {e}")
        data = {}

    user_id = data.get("user_id")

    if not session_id or session_id not in matrix_client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = matrix_client_manager.matrix_clients[session_id]
        client = client_data["client"]
        e2ee_manager = client_data.get("e2ee_manager")
        current_user_id = client_data["user_id"]

        if not e2ee_manager:
            return jsonify({"success": False, "error": "E2EE not initialized"})

        # 如果没有提供 user_id，假设是验证当前用户的设备
        if not user_id:
            user_id = current_user_id

        # 检查设备是否存在
        try:
            # 尝试获取用户的设备密钥
            device_keys_response = await client.query_keys(
                device_keys={user_id: [device_id]}
            )

            device_keys = device_keys_response.get("device_keys", {})
            if user_id not in device_keys or device_id not in device_keys[user_id]:
                # 如果是验证自己的设备，尝试从设备列表中获取
                if user_id == current_user_id:
                    try:
                        devices_response = await client.get_devices()
                        devices = devices_response.get("devices", [])
                        device_found = any(
                            d.get("device_id") == device_id for d in devices
                        )

                        if not device_found:
                            return jsonify(
                                {
                                    "success": False,
                                    "error": f"Device {device_id} not found for user {user_id}",
                                }
                            )
                    except Exception as e:
                        logger.error(f"Failed to get device list: {e}")
                        return jsonify(
                            {
                                "success": False,
                                "error": f"Failed to get device list: {str(e)}",
                            }
                        )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": f"Device {device_id} not found for user {user_id}",
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to query device keys: {e}")
            # 如果是验证自己的设备，尝试从设备列表中获取
            if user_id == current_user_id:
                try:
                    devices_response = await client.get_devices()
                    devices = devices_response.get("devices", [])
                    device_found = any(d.get("device_id") == device_id for d in devices)

                    if not device_found:
                        return jsonify(
                            {
                                "success": False,
                                "error": f"Device {device_id} not found for user {user_id}",
                            }
                        )
                except Exception as e2:
                    logger.error(f"Failed to get device list: {e2}")
                    return jsonify(
                        {
                            "success": False,
                            "error": "Failed to query device keys and get device list",
                        }
                    )
            else:
                return jsonify(
                    {
                        "success": False,
                        "error": f"Failed to query device keys: {str(e)}",
                    }
                )

        # 无论是自己的设备还是其他用户的设备，都优先尝试启动 SAS 验证流程
        try:
            # 开始 SAS 验证
            transaction_id = await e2ee_manager.start_sas_verification(
                user_id, device_id
            )

            if transaction_id:
                logger.info(
                    f"SAS verification started for device {device_id}, transaction: {transaction_id}"
                )
                return jsonify(
                    {
                        "success": True,
                        "message": f"SAS verification started for device {device_id}",
                        "transaction_id": transaction_id,
                        "requires_interaction": True,
                    }
                )
            else:
                # 如果 SAS 验证启动失败，对于自己的设备，尝试回退到简单验证（直接信任）
                logger.warning("Failed to start SAS verification")

                if user_id == current_user_id:
                    logger.warning("Falling back to simple verification for own device")
                    # ... existing simple verification logic ...
                    # (Need to inline it or call it)
                    success = await e2ee_manager.verify_device(user_id, device_id)
                    if success:
                        return jsonify(
                            {
                                "success": True,
                                "message": f"Device {device_id} verified (simple verification)",
                            }
                        )

                return jsonify(
                    {
                        "success": False,
                        "error": "Failed to start SAS verification",
                    }
                )

        except Exception as e:
            logger.error(f"SAS verification error: {e}")
            return jsonify(
                {
                    "success": False,
                    "error": f"SAS verification failed: {str(e)}",
                }
            )

    except Exception as e:
        logger.error(f"Failed to verify device: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_get_verification_info(matrix_client_manager, transaction_id):
    """获取验证信息"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in matrix_client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = matrix_client_manager.matrix_clients[session_id]
        e2ee_manager = client_data.get("e2ee_manager")

        if not e2ee_manager:
            return jsonify({"success": False, "error": "E2EE not initialized"})

        info = await e2ee_manager.get_verification_info(transaction_id)
        if info:
            return jsonify({"success": True, "info": info})
        else:
            return jsonify(
                {
                    "success": False,
                    "error": "Verification not found or info not available",
                }
            )

    except Exception as e:
        logger.error(f"Failed to get verification info: {e}")
        return jsonify({"success": False, "error": str(e)})


async def handle_confirm_verification(matrix_client_manager, transaction_id):
    """确认验证"""
    session_id = request.args.get("session_id")

    if not session_id or session_id not in matrix_client_manager.matrix_clients:
        return jsonify({"success": False, "error": "Invalid session"})

    try:
        client_data = matrix_client_manager.matrix_clients[session_id]
        e2ee_manager = client_data.get("e2ee_manager")

        if not e2ee_manager:
            return jsonify({"success": False, "error": "E2EE not initialized"})

        success = await e2ee_manager.confirm_sas_verification(transaction_id)
        if success:
            return jsonify({"success": True, "message": "Verification confirmed"})
        else:
            return jsonify(
                {"success": False, "error": "Failed to confirm verification"}
            )

    except Exception as e:
        logger.error(f"Failed to confirm verification: {e}")
        return jsonify({"success": False, "error": str(e)})
