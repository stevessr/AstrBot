# Matrix Web Client Plugin

完整的 Matrix Web 客户端插件，支持多种登录方式和完整的客户端功能。

## 功能特性

### 登录方式
- **密码登录**: 使用用户名和密码登录
- **Token 登录**: 使用 Access Token 登录
- **OAuth2/OIDC/SSO 登录**: 支持需要 SSO 的服务器

### 客户端功能
- 房间列表和管理
- 实时消息发送和接收
- 用户资料查看
- 设备管理
- WebSocket 实时同步

## 使用方法

1. 插件会自动启动独立的 Web 服务器在端口 **8766**
2. 访问 `http://localhost:8766` 打开 Matrix 客户端界面
3. 选择登录方式并输入相应信息
4. 登录成功后即可使用完整的客户端功能

## OAuth2/OIDC 支持

本插件完整实现了 OAuth2 授权码流程，支持：
- 自动服务器发现 (`.well-known/matrix/client`)
- OIDC 配置自动获取 (`.well-known/openid-configuration`)
- 授权码交换
- PKCE (Proof Key for Code Exchange)
- State 参数验证 (CSRF 防护)

适用于需要 SSO 单点登录的 Matrix 服务器。

## 配置

插件使用默认配置，启动即可使用。默认配置：
- 主机: `0.0.0.0` (监听所有网卡)
- 端口: `8766`

如需修改，可在插件代码中调整 `self.port` 和 `self.host` 参数。

## 技术实现

- **Web 框架**: Quart (异步 Flask)
- **Matrix 客户端**: 基于 AstrBot 的 MatrixHTTPClient
- **OAuth2**: 基于 MatrixOAuth2（部分使用内部方法，待公共 API 完善）
- **实时通信**: WebSocket
- **前端**: 原生 HTML/CSS/JavaScript

## 调试功能

客户端提供完整的调试功能：
- 查看所有房间和消息
- 发送测试消息
- 查看用户设备列表
- 实时同步事件查看

## 安全说明

- 会话使用随机生成的 session_id 进行管理
- Access Token 仅存储在服务器内存中
- OAuth2 流程包含 CSRF 防护（state 参数验证）
- PKCE 增强授权码流安全性
- postMessage 使用明确的 origin 而非 '*'
- **建议在生产环境中使用 HTTPS**

## 已知限制

- OAuth2 实现目前使用了 MatrixOAuth2 的部分私有方法（`_generate_state` 等），这些应该在未来版本中替换为公共 API
- client_id 使用硬编码的默认值 'matrix-web-client'，应该支持配置或动态注册

## 依赖

本插件依赖 AstrBot 的 Matrix 适配器组件：
- `astrbot.core.platform.sources.matrix.client.MatrixHTTPClient`
- `astrbot.core.platform.sources.matrix.components.oauth2.MatrixOAuth2`

确保 AstrBot 主程序已正确安装这些组件。
