# Matrix Adapter Changelog

## v1.0.1 - 2025-10-18 (E2EE Fixes)

### ✨ E2EE 增强

- **自动加密密钥上传**: 登录后自动上传加密密钥到服务器
- **加密媒体支持**: 正确处理加密图片和音频消息的解密
  - 支持 `RoomEncryptedImage` 事件
  - 支持 `RoomEncryptedAudio` 事件
  - 使用 `nio.crypto.decrypt_attachment()` 解密媒体
- **自动加密上传**: 在加密房间中自动加密媒体文件
  - 使用 `client.upload(..., encrypt=True)`
  - 正确构建加密文件的 content
- **自动加入房间**: 自动接受房间邀请
- **忽略未验证设备**: 发送消息时使用 `ignore_unverified_devices=True` 避免阻塞

### 🐛 Bug 修复

- 修复加密图片/音频无法下载的问题
- 修复加密房间中发送媒体失败的问题
- 修复 MXC URL 解析错误
- 添加对 `RoomEncryptedVideo` 和 `RoomEncryptedFile` 的支持

### 📝 文档更新

- 添加 `E2EE_NOTES.md` - E2EE 实现细节文档
- 更新 `README.md` - E2EE 工作原理说明
- 更新代码注释

### 🔧 技术改进

- 导入缺失的加密事件类型
- 改进错误处理和日志记录
- 支持多实例独立密钥存储 (`data/matrix_store/{id}/`)

---

## v1.0.0 - 2025-10-18 (Initial Release)

### ✨ 核心功能

- **Matrix 协议支持**: 完整的 Matrix 客户端实现
- **E2EE 支持**: 使用 vodozemac 的端到端加密
- **消息类型**:
  - 文本消息 (Text)
  - 图片消息 (Image)
  - 语音消息 (Audio)
  - 视频通知 (Video - 显示通知)
  - 文件通知 (File - 显示通知)
- **房间支持**: 私聊和群组
- **自动登录**: 密码或访问令牌登录
- **密钥管理**: 自动管理设备密钥

### 📦 依赖

- matrix-nio[e2e]>=0.25.0
- vodozemac (通过 matrix-nio[e2e] 自动安装)

### 🎯 已知限制

- 视频和文件消息仅显示通知，不下载内容
- 暂不支持消息回复 (Reply)
- 暂不支持 @提及 (At)
- 暂不支持流式消息发送

### 📚 文档

- README.md - 使用说明
- example_config.json - 配置示例
- test_matrix.py - 测试脚本
- ../../docs/MATRIX_SETUP_GUIDE.md - 详细设置指南
- ../../docs/MATRIX_QUICK_START_CN.md - 快速开始指南
