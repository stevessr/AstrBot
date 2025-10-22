"""
Matrix E2EE (End-to-End Encryption) 模块

提供完整的端到端加密支持，包括：
- 密钥管理和存储
- 设备验证
- 消息加密/解密
- 密钥恢复
- 自动设置和密钥交换
"""

from .e2ee_manager import MatrixE2EEManager
from .e2ee_store import MatrixE2EEStore
from .e2ee_crypto import MatrixE2EECrypto
from .e2ee_verification import MatrixE2EEVerification
from .e2ee_commands import MatrixE2EECommands
from .e2ee_recovery import MatrixE2EERecovery
from .e2ee_auto_setup import MatrixE2EEAutoSetup
from .e2ee_diagnostics import MatrixE2EEDiagnostics

__all__ = [
    "MatrixE2EEManager",
    "MatrixE2EEStore",
    "MatrixE2EECrypto",
    "MatrixE2EEVerification",
    "MatrixE2EECommands",
    "MatrixE2EERecovery",
    "MatrixE2EEAutoSetup",
    "MatrixE2EEDiagnostics",
]
