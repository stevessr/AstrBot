# Matrix 适配器重构说明

## 问题分析

原始代码存在的问题：

1. **响应对象处理不当**：代码使用 `getattr()` 尝试从响应对象中提取字段，但没有正确检查响应类型
2. **错误处理不完善**：WhoamiError 等错误响应没有被正确识别和处理
3. **缺少类型检查**：直接假设响应对象的结构，导致在响应格式不符合预期时崩溃
4. **未使用框架数据结构**：没有充分利用 AstrBot 框架提供的数据结构和机制

## 主要改进

### 1. 修复 Token 登录流程

**原代码问题**：
```python
whoami = await self.client.whoami()
if isinstance(whoami, WhoamiError):
    # 错误处理
    got_user = getattr(whoami, "user_id", None)  # WhoamiError 没有 user_id
```

**改进后**：
```python
# 使用 restore_login 正确恢复会话
self.client.restore_login(
    user_id=self.user_id,
    device_id=self.device_id,
    access_token=self.access_token,
)

# 使用 sync 验证 token，而不是依赖 whoami
sync_response = await self.client.sync(timeout=0, full_state=False)
if not isinstance(sync_response, SyncResponse):
    raise RuntimeError(f"Token validation failed: {sync_response}")
```

**关键改变**：
- 使用 `restore_login()` 而不是手动设置 token
- 使用 `sync()` 作为主要验证方式
- `whoami()` 仅作为可选的补充验证
- 正确处理所有响应类型

### 2. 改进密码登录流程

**改进点**：
- 添加详细的错误信息提取
- 提供用户友好的配置检查提示
- 正确保存 access_token 供后续使用
- 处理 device_id 和 user_id 的更新

### 3. 强化配置验证

**新增验证**：
```python
# 验证必需字段
if not self.user_id:
    raise ValueError("matrix_user_id is required. Format: @username:homeserver.com")

# 验证认证方式
valid_auth_methods = ["password", "token", "oauth2"]
if self.auth_method not in valid_auth_methods:
    raise ValueError(f"Invalid matrix_auth_method: {self.auth_method}")

# 验证认证凭据
if self.auth_method == "password" and not self.password:
    raise ValueError("matrix_password is required when matrix_auth_method='password'")
```

### 4. 优化启动流程

**改进**：
- 添加自动检测认证方式（优先使用 token）
- 改进 E2EE 初始化错误处理（失败时继续运行）
- 添加详细的启动日志信息
- 统一异常处理和错误消息

### 5. 完善消息处理

**改进 `convert_message()` 方法**：
```python
async def convert_message(self, room: MatrixRoom, event) -> Optional[AstrBotMessage]:
    """转换 Matrix 消息为 AstrBotMessage
    
    使用框架提供的 AstrBotMessage 数据结构，确保与其他组件的兼容性
    """
    try:
        # 创建消息对象 - 使用框架定义的字段
        message = AstrBotMessage()
        
        # 基本信息
        message.session_id = room.room_id
        message.message_id = event.event_id
        message.raw_message = event
        message.timestamp = event.server_timestamp
        
        # 正确判断消息类型（群聊/私聊）
        member_count = len(room.users)
        if member_count > 2 or room.is_group:
            message.type = MessageType.GROUP_MESSAGE
            message.group_id = room.room_id
        else:
            message.type = MessageType.FRIEND_MESSAGE
        
        # 使用 MessageMember 结构
        sender_display_name = room.user_name(event.sender)
        message.sender = MessageMember(
            user_id=event.sender,
            nickname=sender_display_name or event.sender.split(":")[0].lstrip("@")
        )
        
        # 使用框架的消息组件（Plain, Image, File）
        # ...
        
        return message
        
    except Exception as e:
        logger.error(f"Error converting Matrix message: {e}")
        return None
```

**关键点**：
- 严格遵循 AstrBot 框架的数据结构
- 正确使用 `MessageType`、`MessageMember`、`Plain`、`Image` 等组件
- 添加完整的错误处理和日志
- 返回 `Optional[AstrBotMessage]` 以处理转换失败情况

### 6. 改进消息发送

**优化 `send_by_session()` 方法**：
```python
async def send_by_session(self, session: MessageSesion, message_chain: MessageChain):
    """通过会话发送消息
    
    使用框架提供的 MessageSesion 和 MessageChain 数据结构
    确保与其他平台适配器行为一致
    """
    try:
        room_id = session.session_id
        
        if not room_id:
            logger.error("Session does not have a valid room_id")
            return
        
        # 使用 MatrixPlatformEvent 的发送方法保证格式一致性
        await MatrixPlatformEvent.send_with_client(
            self.client, message_chain, room_id
        )
        
        # 调用父类方法触发框架后处理
        await super().send_by_session(session, message_chain)
        
    except Exception as e:
        logger.error(f"Failed to send message via session: {e}")
```

### 7. 完善事件处理

**改进回调函数**：
- `message_callback()`：添加详细日志和错误追踪
- `invite_callback()`：正确处理 JoinResponse/JoinError
- `handle_msg()`：确保正确使用框架的事件系统

### 8. 优雅关闭

**改进 `terminate()` 方法**：
```python
async def terminate(self):
    """关闭 Matrix 客户端
    
    清理资源并优雅地关闭连接
    """
    try:
        logger.info("Shutting down Matrix adapter...")
        
        # 关闭 E2EE handler
        if self.e2ee_handler:
            await self.e2ee_handler.close()
        
        # 关闭客户端连接
        if self.client:
            await self.client.close()
        
        logger.info("Matrix 适配器已被优雅地关闭")
        
    except Exception as e:
        logger.error(f"Matrix 适配器关闭时出错：{e}")
```

## 与框架的集成

### 数据流向

```
Matrix Server
    ↓ (nio events)
message_callback()
    ↓ (convert)
AstrBotMessage (框架数据结构)
    ↓ (create event)
MatrixPlatformEvent (继承 AstrMessageEvent)
    ↓ (commit)
事件队列 (框架核心)
    ↓ (dispatch)
插件和处理器
```

### 关键接口

1. **Platform 基类**：
   - `run()`: 启动适配器
   - `send_by_session()`: 发送消息
   - `terminate()`: 关闭适配器
   - `meta()`: 平台元数据

2. **AstrBotMessage**：
   - 框架定义的消息数据结构
   - 包含 sender, session_id, message, type 等字段

3. **MessageChain**：
   - 消息链，包含多个消息组件
   - 组件类型：Plain, Image, File, Voice 等

4. **AstrMessageEvent**：
   - 消息事件基类
   - 通过 `commit_event()` 提交到队列

## 测试建议

### 配置测试

1. **Token 认证**：
```yaml
platform:
  - type: matrix
    matrix_auth_method: token
    matrix_homeserver: https://matrix.org
    matrix_user_id: "@bot:matrix.org"
    matrix_access_token: "your_token_here"
    matrix_device_id: "ASTRBOT_DEVICE"
```

2. **密码认证**：
```yaml
platform:
  - type: matrix
    matrix_auth_method: password
    matrix_homeserver: https://matrix.org
    matrix_user_id: "@bot:matrix.org"
    matrix_password: "your_password"
```

### 功能测试

1. 发送文本消息
2. 发送图片
3. 接收文本消息
4. 接收图片
5. 群聊和私聊消息区分
6. 房间邀请自动加入
7. 优雅关闭

## 注意事项

1. **E2EE 支持**：当前实现使用 vodozemac 而不是 matrix-nio 内置的 E2EE（已弃用）
2. **设备 ID**：自动生成并保存，用于端到端加密
3. **Access Token**：密码登录后自动保存，下次可使用 token 认证
4. **错误恢复**：所有网络操作都有超时和重试机制
5. **日志级别**：使用 DEBUG 级别记录详细信息，便于排查问题

## 修复的原始问题

原始错误日志：
```
Error validating response: 'user_id' is a required property
WhoamiError: unknown error
user_id: None
device_id: None
```

**根本原因**：
- `whoami()` 返回 `WhoamiError` 时，代码尝试从错误对象中提取 `user_id`
- `WhoamiError` 对象没有 `user_id` 字段，导致验证失败

**解决方案**：
- 改用 `restore_login()` + `sync()` 组合验证 token
- 正确区分成功响应（SyncResponse）和错误响应
- 添加详细的类型检查和错误处理

## 代码质量

- ✅ 通过 ruff format 格式化
- ✅ 通过 ruff check 检查
- ✅ 符合 AstrBot 编码规范
- ✅ 添加详细的文档字符串
- ✅ 完善的错误处理和日志
