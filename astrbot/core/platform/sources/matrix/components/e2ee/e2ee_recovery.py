"""
Matrix E2EE 密钥恢复模块

支持从其他设备恢复密钥
"""

import hashlib
import time
from typing import Dict, Optional, List
from astrbot import logger


class MatrixE2EERecovery:
    """Matrix E2EE 密钥恢复管理器"""

    def __init__(self, user_id: str, device_id: str):
        """
        初始化密钥恢复管理器

        Args:
            user_id: 用户 ID
            device_id: 设备 ID
        """
        self.user_id = user_id
        self.device_id = device_id

        # 恢复请求：{request_id: {target_device_id, state, timestamp, ...}}
        self.recovery_requests: Dict[str, Dict] = {}

        # 恢复会话：{session_id: {requester_device_id, state, keys, ...}}
        self.recovery_sessions: Dict[str, Dict] = {}

    def request_key_recovery(self, target_device_id: str) -> str:
        """
        向其他设备请求密钥恢复

        Args:
            target_device_id: 目标设备 ID

        Returns:
            恢复请求 ID
        """
        request_id = hashlib.md5(
            f"{self.device_id}:{target_device_id}:{time.time()}".encode()
        ).hexdigest()

        self.recovery_requests[request_id] = {
            "target_device_id": target_device_id,
            "state": "pending",
            "timestamp": time.time(),
            "requester_device_id": self.device_id,
        }

        logger.info(
            f"Requested key recovery from device {target_device_id}, "
            f"request_id: {request_id}"
        )

        return request_id

    def accept_recovery_request(self, request_id: str) -> bool:
        """
        接受密钥恢复请求

        Args:
            request_id: 恢复请求 ID

        Returns:
            是否成功
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return False

        request = self.recovery_requests[request_id]
        if request["state"] != "pending":
            logger.error(
                f"Recovery request {request_id} is not in pending state: "
                f"{request['state']}"
            )
            return False

        request["state"] = "accepted"
        request["accepted_at"] = time.time()

        logger.info(f"Accepted recovery request {request_id}")
        return True

    def generate_recovery_code(self, request_id: str) -> Optional[str]:
        """
        生成恢复验证码

        Args:
            request_id: 恢复请求 ID

        Returns:
            恢复验证码（6 位数字）
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return None

        request = self.recovery_requests[request_id]
        if request["state"] != "accepted":
            logger.error(
                f"Recovery request {request_id} is not in accepted state: "
                f"{request['state']}"
            )
            return None

        # 生成 6 位数字验证码
        combined = f"{self.device_id}:{request['target_device_id']}:{request_id}"
        hash_bytes = hashlib.sha256(combined.encode()).digest()
        code = str(int.from_bytes(hash_bytes[:4], byteorder="big") % 1000000).zfill(6)

        request["recovery_code"] = code
        request["state"] = "code_generated"

        logger.info(f"Generated recovery code for request {request_id}")
        return code

    def confirm_recovery_code(self, request_id: str, code: str) -> bool:
        """
        确认恢复验证码

        Args:
            request_id: 恢复请求 ID
            code: 恢复验证码

        Returns:
            是否成功
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return False

        request = self.recovery_requests[request_id]
        if request["state"] != "code_generated":
            logger.error(
                f"Recovery request {request_id} is not in code_generated state: "
                f"{request['state']}"
            )
            return False

        if request.get("recovery_code") != code:
            logger.error(f"Recovery code mismatch for request {request_id}")
            return False

        request["state"] = "code_confirmed"
        request["confirmed_at"] = time.time()

        logger.info(f"Confirmed recovery code for request {request_id}")
        return True

    def share_keys(self, request_id: str, keys: Dict) -> bool:
        """
        分享密钥给请求设备

        Args:
            request_id: 恢复请求 ID
            keys: 要分享的密钥

        Returns:
            是否成功
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return False

        request = self.recovery_requests[request_id]
        if request["state"] != "code_confirmed":
            logger.error(
                f"Recovery request {request_id} is not in code_confirmed state: "
                f"{request['state']}"
            )
            return False

        request["shared_keys"] = keys
        request["state"] = "keys_shared"
        request["shared_at"] = time.time()

        logger.info(f"Shared keys for recovery request {request_id}")
        return True

    def receive_keys(self, request_id: str) -> Optional[Dict]:
        """
        接收恢复的密钥

        Args:
            request_id: 恢复请求 ID

        Returns:
            恢复的密钥
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return None

        request = self.recovery_requests[request_id]
        if request["state"] != "keys_shared":
            logger.error(
                f"Recovery request {request_id} is not in keys_shared state: "
                f"{request['state']}"
            )
            return None

        keys = request.get("shared_keys")
        if not keys:
            logger.error(f"No keys found for recovery request {request_id}")
            return None

        request["state"] = "completed"
        request["completed_at"] = time.time()

        logger.info(f"Received keys for recovery request {request_id}")
        return keys

    def cancel_recovery_request(self, request_id: str, reason: str = "") -> bool:
        """
        取消密钥恢复请求

        Args:
            request_id: 恢复请求 ID
            reason: 取消原因

        Returns:
            是否成功
        """
        if request_id not in self.recovery_requests:
            logger.error(f"Recovery request {request_id} not found")
            return False

        request = self.recovery_requests[request_id]
        request["state"] = "cancelled"
        request["cancelled_at"] = time.time()
        request["cancel_reason"] = reason

        logger.info(f"Cancelled recovery request {request_id}: {reason}")
        return True

    def get_recovery_request_status(self, request_id: str) -> Optional[Dict]:
        """
        获取恢复请求状态

        Args:
            request_id: 恢复请求 ID

        Returns:
            恢复请求状态
        """
        return self.recovery_requests.get(request_id)

    def list_recovery_requests(self) -> List[Dict]:
        """
        列出所有恢复请求

        Returns:
            恢复请求列表
        """
        return [
            {"request_id": request_id, **request}
            for request_id, request in self.recovery_requests.items()
        ]

    def list_pending_recovery_requests(self) -> List[Dict]:
        """
        列出待处理的恢复请求

        Returns:
            待处理的恢复请求列表
        """
        return [
            {"request_id": request_id, **request}
            for request_id, request in self.recovery_requests.items()
            if request["state"] == "pending"
        ]
