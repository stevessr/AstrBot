# Matrix 适配器流式输出支持

## 更新日期
2025 年 10 月 20 日

## 概述
Matrix 适配器现已支持**流式输出**功能！这意味着当使用支持流式响应的 LLM 提供者时，用户可以看到 AI 回复逐步生成的过程，而不是等待完整回复后才显示。

## 技术实现

### 核心原理
流式输出通过**不断编辑同一条消息**来实现，而不是发送多条独立消息。这遵循了 Matrix 协议的消息编辑规范（`m.replace` relation type）。

### 实现细节

1. **消息编辑 API**
   - 新增 `MatrixHTTPClient.edit_message()` 方法
   - 使用 `m.relates_to` 字段关联原消息
   - 符合 Matrix Spec 的编辑消息格式

2. **流式处理逻辑**
   - 接收 LLM 的异步生成器输出
   - 累积文本内容到 `delta` 变量
   - 定期编辑同一条消息来更新内容
   - 使用节流机制避免过于频繁的编辑请求

3. **节流机制**
   - 默认间隔：**0.8 秒**
   - 防止触发 Matrix 服务器的速率限制
   - 平衡用户体验和服务器负载

4. **混合内容处理**
   - 纯文本：累积并定期编辑
   - 图片/文件：先发送当前文本，然后单独发送媒体
   - 确保内容顺序正确

## 使用方法

### 1. 启用流式输出
确保您的 LLM 提供者配置支持流式响应：

```json
{
  "provider": [
    {
      "id": "openai",
      "api_key": "your-api-key",
      "streaming": true  // 启用流式输出
    }
  ]
}
```

### 2. Matrix 配置
无需特殊配置，流式输出功能会自动工作：

```json
{
  "type": "matrix",
  "enable": true,
  "id": "matrix",
  "matrix_homeserver": "https://matrix.org",
  "matrix_user_id": "@bot:matrix.org",
  "matrix_access_token": "your-token",
  // ... 其他配置
}
```

### 3. 效果演示
当用户发送消息后，AI 回复会逐步显示：

```
初始：你好
更新：你好，我
更新：你好，我是
更新：你好，我是 AstrBot
最终：你好，我是 AstrBot。很高兴为你服务！
```

用户在客户端会看到消息内容逐步增长，提供流畅的体验。

## 技术特性

### ✅ 已支持
- 纯文本流式输出
- **Markdown 格式支持**（粗体、斜体、代码、链接、列表、引用等）
- 消息编辑节流
- 混合内容处理（文本 + 图片/文件）
- 错误容错处理
- 最终内容确保发送
- HTML 格式化（自动转换 Markdown 为 Matrix 支持的 HTML）

### 🔄 工作原理

```python
async def send_streaming(self, generator, use_fallback: bool = False):
    """Matrix 流式发送 - 通过不断编辑同一条消息"""
    delta = ""  # 累积的文本内容
    message_event_id = None  # 消息的 event_id
    
    async for chain in generator:
        # 累积文本
        for component in chain.chain:
            if isinstance(component, Plain):
                delta += component.text
        
        # 定期编辑消息（带节流）
        if should_edit():
            if message_event_id:
                await client.edit_message(room_id, message_event_id, delta)
            else:
                # 第一次发送消息
                response = await client.send_message(room_id, delta)
                message_event_id = response["event_id"]
    
    # 确保最终内容已发送
    if delta != current_content:
        await client.edit_message(room_id, message_event_id, delta)
```

## 测试验证

### 单元测试
运行测试脚本验证功能：

```bash
uv run python test_matrix_streaming.py
```

测试覆盖：
- ✅ 流式消息累积逻辑
- ✅ 节流机制
- ✅ 混合内容处理

### 集成测试
已在实际 Matrix homeserver 上测试：
- ✅ 文本逐步显示正常
- ✅ 编辑消息功能正常
- ✅ 服务器速率限制未触发
- ✅ 用户体验流畅

## 性能优化

### 1. 节流策略
- **间隔**：0.8 秒
- **原因**：Matrix 服务器通常有速率限制（例如 10 req/s）
- **效果**：平衡实时性和服务器负载

### 2. 内容累积
- 不是每个 token 都编辑一次
- 累积多个 token 后统一编辑
- 减少 API 调用次数

### 3. 错误处理
- 编辑失败时记录警告但不中断流程
- 最终确保完整内容已发送
- 避免因个别错误导致消息丢失

## 与其他平台对比

| 平台 | 流式支持 | 实现方式 | 节流间隔 |
|------|---------|---------|---------|
| Matrix | ✅ | 消息编辑 | 0.8s |
| Telegram | ✅ | 消息编辑 | 0.6s |
| QQ Official | ✅ | 流式 API | N/A |
| Webchat | ✅ | WebSocket | N/A |
| 其他 | ⏳ | 待实现 | - |

## 限制和注意事项

### 1. Matrix 服务器限制
- 不同的 homeserver 可能有不同的速率限制
- 部分服务器可能对编辑频率有限制
- 建议根据实际使用调整 `throttle_interval`

### 2. 客户端兼容性
- 大多数现代 Matrix 客户端支持消息编辑
- 旧版客户端可能显示编辑历史
- Fallback 格式确保基本可读性

### 3. E2EE 房间
- 加密房间中的消息编辑需要额外处理
- 当前实现支持加密房间
- 性能可能略有影响

### 4. 内容长度
- Matrix 消息有最大长度限制（通常 65536 字节）
- 超长内容会自动分段发送
- 流式输出通常不会超过限制

## 配置选项

虽然流式输出自动工作，但可以通过以下方式调整：

### 调整节流间隔
编辑 `matrix_event.py`：

```python
throttle_interval = 0.8  # 默认 0.8 秒，可根据需要调整
```

### 禁用流式输出
在提供者配置中关闭：

```json
{
  "provider": [
    {
      "id": "openai",
      "streaming": false  // 禁用流式输出
    }
  ]
}
```

## 故障排除

### 问题 1: 消息更新很慢
**原因**: 节流间隔太长  
**解决**: 减小 `throttle_interval`（例如改为 0.5s）

### 问题 2: 触发速率限制
**原因**: 节流间隔太短  
**解决**: 增大 `throttle_interval`（例如改为 1.0s）

### 问题 3: 消息编辑失败
**原因**: 服务器不支持或权限问题  
**解决**: 检查日志，确认 bot 有编辑消息权限

### 问题 4: 内容显示不完整
**原因**: 最终编辑失败  
**解决**: 检查网络连接和服务器状态

## 开发参考

### Matrix 消息编辑规范
参考 Matrix Spec:
- [Message Edits (m.replace)](https://spec.matrix.org/v1.11/client-server-api/#event-replacements)
- [Room Message Format](https://spec.matrix.org/v1.11/client-server-api/#mroommessage)

### 实现文件
- `astrbot/core/platform/sources/matrix/client/http_client.py` - HTTP 客户端
- `astrbot/core/platform/sources/matrix/matrix_event.py` - 事件处理
- `test_matrix_streaming.py` - 单元测试

## 贡献

欢迎贡献改进！可能的方向：
- 自适应节流策略
- 性能监控和统计
- 更好的错误恢复机制
- 支持更多内容类型

---

**实现时间**: 2025-10-20  
**测试状态**: ✅ 通过  
**维护者**: stevessr  
**版本**: AstrBot v4.x
