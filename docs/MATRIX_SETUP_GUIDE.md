# Matrix 协议适配器设置指南

本指南将帮助您为 AstrBot 配置 Matrix 协议适配器，该适配器支持端到端加密（E2EE）。

## 概述

Matrix 适配器使用 `matrix-nio` Python 库，并通过 `vodozemac` 提供端到端加密支持。这是 Matrix 官方推荐的现代化 E2EE 实现，替代了已弃用的 `libolm`。

## 功能特性

- ✅ 完整的 Matrix 协议支持
- ✅ 端到端加密（E2EE）支持（使用 vodozemac）
- ✅ 支持文本、图片、语音消息
- ✅ 支持私聊和群组聊天
- ✅ 自动管理设备密钥和加密会话
- ✅ 透明处理加密和未加密房间

## 前置要求

### 1. Matrix 账号

您需要一个 Matrix 账号。您可以：
- 在 https://matrix.org 上注册账号
- 使用任何其他 Matrix 家庭服务器
- 自建 Matrix 服务器（Synapse、Dendrite 等）

### 2. Python 依赖

Matrix 适配器需要以下依赖：
```bash
pip install "matrix-nio[e2e]>=0.25.0"
```

这将自动安装：
- `matrix-nio`: Python Matrix 客户端库
- `vodozemac-python`: vodozemac 的 Python 绑定（E2EE）
- `python-olm`: 额外的 E2EE 支持（作为后备）

## 安装步骤

### 步骤 1: 安装依赖

在 AstrBot 项目目录中运行：

```bash
pip install "matrix-nio[e2e]>=0.25.0"
```

或者，如果已经安装了 AstrBot，依赖会自动安装。

### 步骤 2: 配置 Matrix 适配器

在 AstrBot 的配置文件中添加 Matrix 平台配置：

#### 方法 A: 使用管理面板

1. 打开 AstrBot 管理面板
2. 导航到 **平台管理**
3. 点击 **添加平台**
4. 选择 **Matrix**
5. 填写以下信息：

#### 方法 B: 手动编辑配置文件

编辑 `data/cmd_config.json`，在 `platform` 数组中添加：

```json
{
  "id": "matrix",
  "type": "matrix",
  "enable": true,
  "matrix_homeserver": "https://matrix.org",
  "matrix_user_id": "@your_username:matrix.org",
  "matrix_password": "your_password",
  "matrix_device_name": "AstrBot",
  "matrix_device_id": "",
  "matrix_access_token": ""
}
```

### 配置项说明

| 配置项 | 必填 | 说明 | 示例 |
|--------|------|------|------|
| `id` | ✅ | 适配器唯一标识符 | `"matrix"` |
| `type` | ✅ | 平台类型，必须为 `"matrix"` | `"matrix"` |
| `enable` | ✅ | 是否启用适配器 | `true` / `false` |
| `matrix_homeserver` | ✅ | Matrix 家庭服务器 URL | `"https://matrix.org"` |
| `matrix_user_id` | ✅ | Matrix 用户 ID | `"@username:matrix.org"` |
| `matrix_password` | ❌* | Matrix 账号密码 | `"your_password"` |
| `matrix_device_name` | ❌ | 设备名称 | `"AstrBot"` |
| `matrix_device_id` | ❌ | 已有的设备 ID（可选） | `""` |
| `matrix_access_token` | ❌* | 访问令牌（可选） | `""` |

\* `matrix_password` 或 `matrix_access_token` 二选一必填

### 步骤 3: 启动 AstrBot

保存配置后，重启 AstrBot：

```bash
python main.py
```

或者如果使用守护进程：

```bash
astrbot restart
```

查看日志确认 Matrix 适配器成功启动：

```
[INFO] 载入 matrix(matrix) 平台适配器 ...
[INFO] Matrix login successful: @username:matrix.org
[INFO] Device ID: XXXXXXXXXXXX
[INFO] Matrix E2EE support enabled
[INFO] Matrix Platform Adapter is running.
```

## 验证配置（可选）

您可以使用提供的测试脚本来验证配置：

```bash
cd astrbot/core/platform/sources/matrix
python test_matrix.py
```

按照提示输入您的 Matrix 凭据，脚本将测试：
- 连接到家庭服务器
- 登录认证
- E2EE 功能
- 同步房间列表

## 使用说明

### 邀请机器人加入房间

1. 在您的 Matrix 客户端（如 Element）中创建或打开一个房间
2. 点击房间设置 → 邀请用户
3. 输入机器人的 Matrix ID（例如 `@your_bot:matrix.org`）
4. 机器人会自动接受邀请并加入房间

### 与机器人交互

- **私聊**: 直接给机器人发送消息
- **群聊**: 在群组中发送消息（根据 AstrBot 的唤醒词配置）

### 支持的消息类型

#### 接收
- ✅ 文本消息
- ✅ 图片（自动下载）
- ✅ 语音/音频（自动下载）
- ⚠️ 视频（显示为文本通知）
- ⚠️ 文件（显示为文本通知）

#### 发送
- ✅ 纯文本消息
- ✅ 图片（上传到服务器）
- ✅ 语音/音频（上传到服务器）
- ✅ 文件（上传到服务器）

## 端到端加密（E2EE）

### 工作原理

Matrix 适配器使用 `matrix-nio` 内置的 E2EE 支持：
- 使用 **vodozemac** (Rust 实现的 Olm/Megolm)
- 设备密钥自动存储在 `data/matrix_store/` 目录
- 加密和解密过程完全透明
- 支持加密和未加密房间

### 设备验证（推荐）

为了获得最佳安全性，建议验证机器人的设备：

1. 在 Element 或其他 Matrix 客户端中登录您的账号
2. 打开设置 → 安全与隐私 → 设备列表
3. 找到名为 "AstrBot" 的设备
4. 点击设备并选择验证方式：
   - **Emoji 验证**: 比对 emoji 序列
   - **设备密钥验证**: 比对设备密钥

### E2EE 故障排除

如果 E2EE 不工作：

1. **检查依赖安装**:
   ```bash
   pip show matrix-nio | grep "e2e"
   # 应该显示安装了 e2e 相关依赖
   ```

2. **检查日志**:
   查找 `Matrix E2EE support enabled` 日志
   
3. **清理密钥存储**:
   如果遇到密钥问题：
   ```bash
   rm -rf data/matrix_store/*
   ```
   然后重启 AstrBot（会生成新的设备密钥）

4. **验证设备**:
   在 Element 中验证机器人的设备

## 高级配置

### 使用访问令牌（推荐用于生产环境）

为了避免在配置文件中存储密码，您可以使用访问令牌：

1. 首次使用密码登录时，查看日志获取令牌：
   ```
   [INFO] Access Token: abcdef1234567890...
   ```

2. 将令牌保存到配置：
   ```json
   {
     "matrix_access_token": "your_access_token_here",
     "matrix_password": ""
   }
   ```

3. 重启 AstrBot，它将使用令牌而非密码

### 自定义存储路径

默认情况下，设备密钥存储在 `data/matrix_store/`。如果需要自定义，可以修改 `matrix_adapter.py` 中的 `store_path`。

### 使用自建服务器

如果您有自己的 Matrix 服务器：

```json
{
  "matrix_homeserver": "https://your-matrix-server.com"
}
```

## 常见问题

### Q: 如何获取 Matrix 账号？

A: 在 https://app.element.io 注册，或使用任何 Matrix 客户端。

### Q: 机器人不响应消息？

A: 检查：
- 机器人是否成功加入房间
- 是否配置了正确的唤醒词（在 AstrBot 主配置中）
- 日志中是否有错误信息

### Q: E2EE 房间中消息无法解密？

A: 确保：
- 安装了 `matrix-nio[e2e]`
- 在 Element 中验证了机器人的设备
- 检查日志是否显示 "Matrix E2EE support enabled"

### Q: 如何更换设备/重新登录？

A: 
1. 删除 `data/matrix_store/` 目录
2. 清空配置中的 `matrix_device_id`
3. 重启 AstrBot，会生成新的设备

### Q: 支持多个 Matrix 账号吗？

A: 是的，在配置中添加多个 Matrix 平台配置，使用不同的 `id`：

```json
[
  {
    "id": "matrix_bot1",
    "type": "matrix",
    "enable": true,
    "matrix_user_id": "@bot1:matrix.org",
    ...
  },
  {
    "id": "matrix_bot2",
    "type": "matrix",
    "enable": true,
    "matrix_user_id": "@bot2:matrix.org",
    ...
  }
]
```

## 技术细节

### 依赖关系

```
matrix-nio[e2e]
├── matrix-nio (核心客户端库)
├── vodozemac-python (E2EE - Rust 实现)
├── python-olm (E2EE 后备)
├── aiohttp (HTTP 客户端)
└── 其他依赖...
```

### E2EE 实现

- **Olm**: 1对1 加密会话
- **Megolm**: 群组加密会话
- **vodozemac**: Rust 实现，替代 libolm
- **密钥管理**: 自动处理设备密钥、会话密钥

### 性能

- vodozemac 比 libolm 快 5-6 倍
- 内存安全（Rust 实现）
- 异步 I/O（asyncio）

## 参考资源

- [Matrix 官网](https://matrix.org)
- [matrix-nio 文档](https://matrix-nio.readthedocs.io/)
- [vodozemac GitHub](https://github.com/matrix-org/vodozemac)
- [Matrix E2EE 指南](https://matrix.org/docs/matrix-concepts/end-to-end-encryption/)
- [Element Web 客户端](https://app.element.io)

## 贡献

如果您发现问题或有改进建议，请：
1. 在 GitHub 上提交 Issue
2. 提交 Pull Request
3. 在社区论坛讨论

## 许可证

此 Matrix 适配器遵循 AstrBot 的许可证。
