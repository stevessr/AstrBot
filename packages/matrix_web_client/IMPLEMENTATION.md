# Matrix Web Client 插件开发文档

## 概述

Matrix Web Client 是一个完整的 Matrix 客户端插件，为 AstrBot 提供独立的 Web 界面，支持多种登录方式和完整的客户端功能。本文档详细说明了实现细节和使用方法。

## 架构设计

### 组件结构

```
data/plugins/matrix_web_client/
├── main.py          # 主插件文件
├── metadata.yaml    # 插件元数据
├── README.md        # 用户文档
├── static/          # 静态资源目录（可选）
└── templates/       # 模板目录（可选）
```

### 核心组件

1. **Web 服务器**: 基于 Quart 的异步 Web 服务器
2. **Matrix 客户端**: 复用 AstrBot 的 MatrixHTTPClient
3. **OAuth2 处理器**: 使用 MatrixOAuth2 实现完整的 OIDC 流程
4. **会话管理**: 内存中的会话存储和管理

## 技术实现

### 1. 独立 Web 服务器

```python
class MatrixWebClient(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.app: Optional[Quart] = None
        self.port = 8766  # 独立端口
        self.host = "0.0.0.0"
```

服务器特性:
- 监听独立端口 8766，不干扰 AstrBot 主服务器
- 支持 WebSocket 连接用于实时消息同步
- 异步处理所有请求

### 2. 三种登录方式

#### 密码登录 (Password Authentication)

```python
@self.app.route("/api/login/password", methods=["POST"])
async def login_password():
    # 1. 接收用户名和密码
    # 2. 使用 MatrixHTTPClient.login_password()
    # 3. 创建会话并返回 session_id
```

优点: 简单直接，适合大多数服务器
缺点: 需要明文传输密码（建议使用 HTTPS）

#### Token 登录 (Access Token Authentication)

```python
@self.app.route("/api/login/token", methods=["POST"])
async def login_token():
    # 1. 接收 access_token
    # 2. 使用 client.restore_login()
    # 3. 验证 token 有效性
```

优点: 最安全的方式，适合已有 token 的用户
缺点: 需要用户提前获取 token

#### OAuth2/OIDC 登录 (SSO Authentication)

```python
@self.app.route("/api/login/oauth2/start", methods=["POST"])
async def oauth2_start():
    # 1. 发现服务器 OAuth2 配置
    # 2. 生成 PKCE 参数
    # 3. 构建授权 URL
    # 4. 等待回调处理
```

实现细节:

**自动服务器发现**:
```python
# 步骤 1: 获取 Matrix 客户端配置
GET /.well-known/matrix/client
返回: { "m.homeserver": { "base_url": "..." } }

# 步骤 2: 获取 OAuth2 配置
GET {homeserver}/.well-known/matrix/client
返回: { "m.authentication": { "issuer": "..." } }

# 步骤 3: 获取 OIDC 配置
GET {issuer}/.well-known/openid-configuration
返回: { "authorization_endpoint": "...", "token_endpoint": "..." }
```

**PKCE 实现**:
```python
# 1. 生成 code_verifier
verifier = secrets.token_urlsafe(64)

# 2. 生成 code_challenge
import hashlib, base64
digest = hashlib.sha256(verifier.encode()).digest()
challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

# 3. 在授权请求中包含 challenge
auth_params = {
    "code_challenge": challenge,
    "code_challenge_method": "S256"
}
```

**授权流程**:
```
1. 用户 -> Plugin: 请求 OAuth2 登录
2. Plugin -> OAuth Provider: 重定向到授权页面
3. 用户 -> OAuth Provider: 完成认证
4. OAuth Provider -> Plugin: 回调并返回 code
5. Plugin -> OAuth Provider: 交换 code 获取 token
6. Plugin -> Matrix Server: 使用 token 访问 Matrix API
```

### 3. 实时消息同步

使用 WebSocket 实现实时同步:

```python
@self.app.websocket("/ws")
async def websocket_handler():
    session_id = request.args.get("session_id")
    client = self.matrix_clients[session_id]["client"]
    
    while True:
        # 使用 Matrix sync API
        sync_response = await client.sync(timeout=30000)
        await websocket.send(json.dumps(sync_response))
```

客户端处理:
```javascript
ws.onmessage = (event) => {
    const syncData = JSON.parse(event.data);
    // 处理新消息
    handleSyncEvent(syncData);
};
```

### 4. 会话管理

```python
self.matrix_clients[session_id] = {
    "client": client,
    "user_id": user_id,
    "device_id": device_id,
    "access_token": access_token,
    "homeserver": homeserver
}

self.active_sessions[session_id] = {
    "user_id": user_id,
    "homeserver": homeserver,
    "login_time": datetime.now().isoformat()
}
```

安全考虑:
- session_id 使用 `secrets.token_urlsafe(32)` 生成
- access_token 仅存储在服务器内存中
- 会话在插件重启后失效

## API 接口文档

### 认证相关

#### POST /api/discover
发现服务器配置

请求:
```json
{
    "homeserver": "https://matrix.org"
}
```

响应:
```json
{
    "success": true,
    "homeserver": "https://matrix-client.matrix.org",
    "login_flows": [...],
    "oidc_config": {...}
}
```

#### POST /api/login/password
密码登录

请求:
```json
{
    "homeserver": "https://matrix.org",
    "username": "@user:matrix.org",
    "password": "password123"
}
```

响应:
```json
{
    "success": true,
    "session_id": "abc123...",
    "user_id": "@user:matrix.org",
    "device_id": "DEVICEID"
}
```

#### POST /api/login/token
Token 登录

请求:
```json
{
    "homeserver": "https://matrix.org",
    "access_token": "syt_...",
    "user_id": "@user:matrix.org",
    "device_id": "DEVICEID"
}
```

#### POST /api/login/oauth2/start
启动 OAuth2 流程

请求:
```json
{
    "homeserver": "https://matrix.org"
}
```

响应:
```json
{
    "success": true,
    "session_id": "abc123...",
    "authorization_url": "https://..."
}
```

### 客户端功能

#### GET /api/rooms?session_id={session_id}
获取房间列表

响应:
```json
{
    "success": true,
    "rooms": [
        {
            "room_id": "!room:matrix.org",
            "name": "Room Name",
            "avatar": null,
            "last_message": "Hello world",
            "unread_count": 5
        }
    ]
}
```

#### GET /api/room/{room_id}/messages?session_id={session_id}&limit=50
获取房间消息

响应:
```json
{
    "success": true,
    "messages": [
        {
            "event_id": "$event:matrix.org",
            "sender": "@user:matrix.org",
            "timestamp": 1234567890,
            "content": {
                "msgtype": "m.text",
                "body": "Hello"
            }
        }
    ],
    "start": "t1-...",
    "end": "t2-..."
}
```

#### POST /api/room/{room_id}/send?session_id={session_id}
发送消息

请求:
```json
{
    "message": "Hello world",
    "msgtype": "m.text"
}
```

响应:
```json
{
    "success": true,
    "event_id": "$event:matrix.org"
}
```

#### GET /api/profile?session_id={session_id}
获取用户资料

响应:
```json
{
    "success": true,
    "user_id": "@user:matrix.org",
    "displayname": "User Name",
    "avatar_url": "mxc://..."
}
```

#### GET /api/devices?session_id={session_id}
获取设备列表

响应:
```json
{
    "success": true,
    "devices": [
        {
            "device_id": "DEVICEID",
            "display_name": "Web Client",
            "last_seen_ip": "1.2.3.4",
            "last_seen_ts": 1234567890
        }
    ]
}
```

#### POST /api/logout
登出

请求:
```json
{
    "session_id": "abc123..."
}
```

### WebSocket

#### WS /ws?session_id={session_id}
实时同步连接

接收消息格式:
```json
{
    "next_batch": "s123_456_789",
    "rooms": {
        "join": {
            "!room:matrix.org": {
                "timeline": {
                    "events": [...]
                }
            }
        }
    }
}
```

## 前端实现

### UI 设计

界面分为三个主要部分:

1. **登录界面**: 标签式切换三种登录方式
2. **侧边栏**: 房间列表和用户信息
3. **主界面**: 消息显示和输入

### 关键功能实现

#### 登录流程

```javascript
async function loginWithPassword() {
    const response = await fetch('/api/login/password', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({homeserver, username, password})
    });
    
    const data = await response.json();
    if (data.success) {
        sessionId = data.session_id;
        showClient();
    }
}
```

#### OAuth2 流程

```javascript
async function loginWithOAuth2() {
    // 1. 启动 OAuth2 流程
    const response = await fetch('/api/login/oauth2/start', {
        method: 'POST',
        body: JSON.stringify({homeserver})
    });
    
    const data = await response.json();
    
    // 2. 在新窗口打开授权页面
    window.open(data.authorization_url, 'oauth2', 'width=600,height=700');
    
    // 3. 等待回调（通过轮询或 WebSocket）
    // 实际实现中需要完善此部分
}
```

#### 实时消息更新

```javascript
function connectWebSocket() {
    ws = new WebSocket(`ws://localhost:8766/ws?session_id=${sessionId}`);
    
    ws.onmessage = (event) => {
        const syncData = JSON.parse(event.data);
        handleSyncEvent(syncData);
    };
}

function handleSyncEvent(syncData) {
    const rooms = syncData.rooms?.join || {};
    for (const [roomId, roomData] of Object.entries(rooms)) {
        const timeline = roomData.timeline?.events || [];
        timeline.forEach(event => {
            if (event.type === 'm.room.message') {
                addMessageToUI(event);
            }
        });
    }
}
```

## 部署和使用

### 安装

1. 将插件目录复制到 `data/plugins/matrix_web_client/`
2. 重启 AstrBot 或重新加载插件

### 配置

插件使用默认配置，无需额外设置:
- 端口: 8766
- 主机: 0.0.0.0 (所有网卡)

如需修改，编辑 `main.py`:
```python
self.port = 8766  # 改为其他端口
self.host = "127.0.0.1"  # 仅本地访问
```

### 访问

启动后访问: http://localhost:8766

### 使用场景

1. **调试 Matrix 连接**: 测试登录和消息收发
2. **SSO 配置**: 为需要 SSO 的服务器配置登录
3. **开发测试**: 在开发过程中快速测试 Matrix 功能
4. **用户界面**: 为不熟悉命令行的用户提供图形界面

## 安全建议

1. **生产环境**: 建议配置 HTTPS（使用反向代理如 Nginx）
2. **访问控制**: 考虑添加基本认证或 IP 白名单
3. **Token 管理**: 定期轮换 access token
4. **会话超时**: 实现会话超时机制
5. **输入验证**: 添加更严格的输入验证

## 扩展功能

可以添加的功能:

1. **E2EE 支持**: 集成端到端加密
2. **文件上传**: 支持图片和文件发送
3. **语音/视频**: WebRTC 通话支持
4. **通知**: 浏览器推送通知
5. **主题定制**: 自定义 UI 主题
6. **多语言**: 国际化支持
7. **持久化会话**: 使用数据库存储会话
8. **用户管理**: 多用户支持

## 故障排除

### 常见问题

1. **端口冲突**: 修改 `self.port` 为其他值
2. **OAuth2 失败**: 检查服务器是否支持 OAuth2
3. **WebSocket 连接失败**: 检查防火墙设置
4. **登录失败**: 验证 homeserver URL 是否正确

### 日志查看

插件使用 AstrBot 的日志系统:
```python
logger.info("消息内容")
logger.error("错误信息")
```

查看日志:
- AstrBot Dashboard -> 日志页面
- 或直接查看 AstrBot 控制台输出

## 性能优化

1. **连接池**: 复用 HTTP 连接
2. **消息缓存**: 缓存最近的消息
3. **懒加载**: 按需加载房间列表
4. **压缩**: 启用 gzip 压缩
5. **CDN**: 静态资源使用 CDN

## 贡献指南

欢迎提交 Issue 和 Pull Request！

改进方向:
- UI/UX 优化
- 功能增强
- 性能优化
- 文档完善
- 测试用例

## 许可证

与 AstrBot 主项目保持一致

## 联系方式

如有问题，请在 GitHub 仓库提交 Issue。
