# Matrix Sync Error 修复

## 问题描述

Matrix 适配器在同步时出现错误：

```
Error validating response: 'next_batch' is a required property
Sync error: SyncError: unknown error
```

## 问题原因

1. **错误的 API 调用**: 代码中错误地调用了 `load_store()` 方法，这不是 matrix-nio 的公开 API
2. **同步状态问题**: 当使用访问令牌登录时，客户端的同步状态可能不正确
3. **缺少错误处理**: 没有正确处理 `SyncError` 响应

## 解决方案

### 1. 移除错误的 API 调用

**之前**:
```python
# Load crypto store if available
if self.client.store:
    await self.client.load_store()  # ❌ 错误！
```

**之后**:
```python
# Login first
await self._login()
# matrix-nio 会自动从 store_path 加载存储
```

### 2. 简化启动流程

移除了不必要的初始同步和密钥查询，让 matrix-nio 自动处理：

```python
@override
async def run(self):
    """Start the Matrix client"""
    try:
        # Login first
        await self._login()
        
        # Log E2EE status
        if self.client.store:
            logger.info(f"Matrix E2EE support enabled (store: {self.store_path})")
        else:
            logger.warning("Matrix E2EE support not available")
        
        # Start syncing
        self.running = True
        logger.info("Matrix Platform Adapter is running.")
        
        # Sync loop
        while self.running:
            response = await self.client.sync(timeout=30000)
            if isinstance(response, SyncResponse):
                await self._sync_callback(response)
            elif isinstance(response, SyncError):
                await self._handle_sync_error(response)  # 处理错误
                await asyncio.sleep(5)
```

### 3. 添加 SyncError 处理

新增 `_handle_sync_error()` 方法来处理同步错误：

```python
async def _handle_sync_error(self, error: SyncError):
    """Handle sync errors, attempting recovery when possible"""
    message = getattr(error, "message", str(error))
    status_code = getattr(error, "status_code", None)
    logger.error(f"Matrix sync error: {message}")
    
    # 检测需要重置同步状态的情况
    needs_reset = False
    if message and "next_batch" in message:
        needs_reset = True
    if status_code in {400, 401}:
        needs_reset = True
    
    if needs_reset:
        await self._reset_sync_state()
    
    # 401 错误时重新认证
    if status_code == 401:
        logger.warning("Matrix sync unauthorized. Reauthenticating...")
        await self._login()
```

### 4. 添加同步状态重置

新增 `_reset_sync_state()` 方法来重置同步状态：

```python
async def _reset_sync_state(self):
    """Reset sync-related state to recover from errors"""
    logger.warning("Resetting Matrix sync state due to sync error")
    if hasattr(self.client, "next_batch"):
        self.client.next_batch = None
    if hasattr(self.client, "sync_token"):
        self.client.sync_token = None
    if self.client.store:
        try:
            self.client.store.next_batch = None
        except AttributeError:
            pass
```

## 技术细节

### matrix-nio 的正确使用方式

1. **创建客户端**时提供 `store_path`:
   ```python
   self.client = AsyncClient(
       self.homeserver,
       self.user_id,
       store_path=str(store_path),  # 自动加载/保存
       config=None,
   )
   ```

2. **登录**: 使用密码或访问令牌
   ```python
   # 密码登录
   response = await self.client.login(password=password, device_name=device_name)
   
   # 或访问令牌
   self.client.access_token = token
   self.client.user_id = user_id
   ```

3. **同步**: 直接调用 sync()，matrix-nio 自动处理存储
   ```python
   response = await self.client.sync(timeout=30000)
   ```

### SyncError 的常见原因

| 错误类型 | 原因 | 解决方案 |
|---------|------|---------|
| `next_batch` validation error | 客户端状态不一致 | 重置 `next_batch` 为 None |
| 400 Bad Request | 无效的同步令牌 | 重置同步状态 |
| 401 Unauthorized | 访问令牌过期 | 重新登录 |
| 500 Server Error | 服务器问题 | 等待后重试 |

## 改进效果

### 之前
```
[ERROR] Initial sync error: SyncError: unknown error
[ERROR] Sync error: SyncError: unknown error
[ERROR] Sync error: SyncError: unknown error
```

### 之后
```
[INFO] Matrix login successful: @bot:matrix.org
[INFO] Device ID: ABCDEFGHIJK
[INFO] Uploaded {'signed_curve25519': 50} encryption keys
[INFO] Matrix E2EE support enabled (store: /data/matrix_store/matrix)
[INFO] Matrix Platform Adapter is running.
[INFO] Received invitation to room !xyz:matrix.org
[INFO] Joined room !xyz:matrix.org
```

如果仍有错误，会详细记录：
```
[ERROR] Matrix sync error: Invalid next_batch token
[ERROR] Matrix sync status code: 400
[WARNING] Resetting Matrix sync state due to sync error
```

## 相关修改

### 新增导入
```python
from nio import (
    ...
    SyncError,  # 新增
    ...
)
```

### 新增方法
- `_reset_sync_state()`: 重置同步状态
- `_handle_sync_error()`: 处理同步错误

### 修改方法
- `run()`: 简化启动流程，添加错误处理

## 测试建议

1. **正常登录测试**:
   - 使用密码登录
   - 使用访问令牌登录
   - 验证能够正常同步

2. **错误恢复测试**:
   - 使用过期的访问令牌（应自动重新登录）
   - 删除 `matrix_store` 目录后重启（应重新初始化）
   - 模拟网络中断后恢复（应自动重连）

3. **E2EE 测试**:
   - 加入加密房间
   - 发送和接收加密消息
   - 验证密钥上传成功

## 后续改进

可能的进一步优化：

- [ ] 添加重试计数器，避免无限重试
- [ ] 实现指数退避策略
- [ ] 添加健康检查机制
- [ ] 记录更详细的错误统计

---

**修复日期**: 2025-10-18  
**版本**: v1.0.2
