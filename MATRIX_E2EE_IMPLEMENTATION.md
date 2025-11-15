# Matrix E2EE 实现说明

> 注意：端到端加密 (E2EE) 功能已从项目中移除。此实现文档作为历史参考保留。

## 概述

已通过 `vodozemac` 库为 AstrBot 的 Matrix 适配器实现了端到端加密 (E2EE) 支持。

## 实现的功能

### 1. 核心加密组件 (`components/crypto.py`)

- **Olm 账户管理**
  - 自动创建和持久化 Olm 账户
  - 设备密钥生成和上传
  - 一次性密钥管理

- **Megolm 群组加密**
  - Outbound Group Session：用于加密发送的消息
  - Inbound Group Session：用于解密接收的消息
  - 会话密钥分享机制

- **消息加解密**
  - `encrypt_message()`: 加密待发送的消息
  - `_handle_encrypted_event()`: 解密接收的加密消息
  - `_decrypt_to_device_message()`: 解密设备间消息（密钥交换）

### 2. 发送器更新 (`components/sender.py`)

- 自动检测房间是否加密
- 对加密房间自动加密消息
- 加密失败时回退到明文发送
- 支持引用回复的加密消息

### 3. 适配器集成 (`matrix_adapter.py`)

- 根据配置启用/禁用 E2EE
- 正确初始化 nio 客户端的加密支持
- 将 E2EE handler 传递给发送器

## 配置参数

在 Matrix 平台配置中设置：

```yaml
# Historical example: E2EE support has been removed from AstrBot.
# Set `matrix_enable_e2ee: false` or omit this key in current configs.
matrix_enable_e2ee: false              # E2EE removed (historical example)
matrix_store_path: "./data/matrix_store"  # 加密 storage path (historical)
```

## 工作流程

### 初始化流程

1. 加载或创建 Olm 账户
2. 上传设备密钥到服务器
3. 上传一次性密钥
4. 注册加密事件回调

### 发送加密消息

1. 检测房间是否加密
2. 获取或创建 Outbound Group Session
3. 分享会话密钥给房间成员（首次）
4. 使用 Megolm 加密消息内容
5. 发送 `m.room.encrypted` 事件

### 接收加密消息

1. 接收 `m.room.encrypted` 事件
2. 查找对应的 Inbound Group Session
3. 使用 Megolm 解密消息
4. 处理解密后的消息

## 当前限制和待完成功能

### 已实现 ✅
- Olm 账户管理
- 设备密钥上传
- 一次性密钥管理
- Megolm 加密消息发送
- 基本的消息解密框架

### 待完成 ⚠️
- [ ] 完善会话密钥分享逻辑
  - 获取房间成员设备列表
  - 创建 Olm 会话
  - 通过 to-device 消息发送密钥
- [ ] 设备验证流程
  - 交叉签名
  - 设备信任管理
- [ ] 密钥备份和恢复
- [ ] 会话持久化
  - 保存 Olm 会话
  - 保存 Megolm 会话
- [ ] 完整的解密消息处理
  - 将解密后的事件转换为标准消息
  - 集成到现有消息处理流程

## 使用示例

### 启用 E2EE

在 `data/config/platform_config.yaml` 中：

```yaml
platforms:
  - type: matrix
    id: my_matrix_bot
    matrix_homeserver: "https://matrix.org"
    matrix_user_id: "@mybot:matrix.org"
    matrix_password: "your_password"
  matrix_enable_e2ee: false  # E2EE removed (historical example)
    matrix_store_path: "./data/matrix_store"
    matrix_auto_join_rooms: true
```

### 测试 E2EE

1. 启动 AstrBot
2. 邀请机器人加入加密房间
3. 发送消息到加密房间
4. 机器人会自动使用 E2EE 回复

## 依赖项

- `vodozemac >= 0.9.0` - Rust 实现的 Olm/Megolm 库
- `matrix-nio >= 0.25.0` - Matrix 客户端库

## 调试

启用调试日志以查看加密详情：

```python
import logging
logging.getLogger("astrbot.matrix.crypto").setLevel(logging.DEBUG)
```

## 安全注意事项

1. **存储路径安全**: `matrix_store_path` 包含敏感的加密材料，应限制访问权限
2. **备份**: 定期备份加密存储，丢失会导致无法解密历史消息
3. **设备验证**: 生产环境应实现完整的设备验证流程
4. **密钥轮换**: 建议定期轮换 Megolm 会话密钥

## 参考资料

- [Matrix E2EE 规范](https://spec.matrix.org/v1.11/client-server-api/#end-to-end-encryption)
- [vodozemac 文档](https://docs.rs/vodozemac/)
- [matrix-nio E2EE 示例](https://github.com/poljar/matrix-nio/tree/master/examples)

## 贡献

欢迎提交 PR 完善 E2EE 实现，特别是：
- 会话密钥分享逻辑
- 设备验证流程
- 密钥备份功能
