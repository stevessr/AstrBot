# Matrix 适配器快速开始指南

## 简介

本指南将帮助您快速为 AstrBot 配置 Matrix 协议适配器。Matrix 是一个开放的去中心化通信协议，本适配器支持端到端加密（E2EE）。

## 5分钟快速开始

### 1. 准备 Matrix 账号

如果您还没有 Matrix 账号：

1. 访问 https://app.element.io
2. 点击 "创建账号"
3. 选择 matrix.org 服务器（或选择其他服务器）
4. 填写用户名和密码
5. 完成注册

记下您的 Matrix ID，格式为：`@username:matrix.org`

### 2. 安装依赖

在 AstrBot 目录中运行：

```bash
pip install "matrix-nio[e2e]>=0.25.0"
```

这会安装：
- matrix-nio: Matrix 客户端库
- vodozemac: E2EE 加密支持

### 3. 配置 AstrBot

#### 方式 A: 使用管理面板（推荐）

1. 打开 AstrBot 管理面板
2. 进入 **平台管理**
3. 点击 **添加平台**
4. 选择 **Matrix**
5. 填写以下信息：
   - **Homeserver**: `https://matrix.org`
   - **User ID**: `@你的用户名:matrix.org`
   - **Password**: 你的密码
   - **Device Name**: `AstrBot`
6. 点击保存

#### 方式 B: 手动编辑配置文件

编辑 `data/cmd_config.json`，在 `"platform"` 数组中添加：

```json
{
  "id": "matrix",
  "type": "matrix",
  "enable": true,
  "matrix_homeserver": "https://matrix.org",
  "matrix_user_id": "@你的用户名:matrix.org",
  "matrix_password": "你的密码",
  "matrix_device_name": "AstrBot",
  "matrix_device_id": "",
  "matrix_access_token": ""
}
```

**重要提示**：
- 将 `@你的用户名:matrix.org` 替换为你的实际 Matrix ID
- 将 `你的密码` 替换为你的实际密码

### 4. 启动 AstrBot

```bash
python main.py
```

或者如果你使用守护进程：

```bash
astrbot restart
```

### 5. 查看日志确认启动成功

你应该能看到类似这样的日志：

```
[INFO] 载入 matrix(matrix) 平台适配器 ...
[INFO] Matrix login successful: @username:matrix.org
[INFO] Device ID: ABCDEFGHIJK
[INFO] Matrix E2EE support enabled
[INFO] Matrix Platform Adapter is running.
```

### 6. 测试机器人

1. 在 Element 客户端中创建一个新房间
2. 邀请你的机器人加入：
   - 点击房间信息
   - 点击 "邀请"
   - 输入机器人的 Matrix ID（就是你配置的 `matrix_user_id`）
3. 机器人会自动接受邀请
4. 发送一条消息测试，例如：`/help`

## 配置加密房间（可选但推荐）

### 创建加密房间

1. 在 Element 中创建新房间
2. 在房间设置中启用 "端到端加密"
3. 邀请机器人
4. 机器人会自动处理加密消息

### 验证设备（推荐）

为了获得最佳安全性：

1. 在 Element 中，点击左下角的用户名
2. 选择 "所有设置"
3. 进入 "会话" 或 "安全与隐私"
4. 找到名为 "AstrBot" 的设备
5. 点击 "验证"
6. 选择 "Emoji 验证" 并按提示操作

## 常见配置选项

### 配置项说明

| 配置项 | 说明 | 是否必填 | 默认值 |
|--------|------|----------|--------|
| `matrix_homeserver` | Matrix 服务器地址 | ✅ | `https://matrix.org` |
| `matrix_user_id` | 你的 Matrix ID | ✅ | - |
| `matrix_password` | 你的密码 | ❌* | - |
| `matrix_device_name` | 设备名称 | ❌ | `AstrBot` |
| `matrix_device_id` | 设备 ID（重用） | ❌ | 自动生成 |
| `matrix_access_token` | 访问令牌 | ❌* | - |

\* `matrix_password` 或 `matrix_access_token` 二选一必填

### 使用访问令牌（更安全）

首次登录后，从日志中复制访问令牌：

```
[INFO] Access Token: syt_abc123...
```

然后更新配置：

```json
{
  "matrix_access_token": "syt_abc123...",
  "matrix_password": ""
}
```

## 功能说明

### 支持的消息类型

✅ 文本消息
✅ 图片（自动下载和上传）
✅ 语音/音频（自动下载和上传）
⚠️ 视频（显示通知，暂不下载）
⚠️ 文件（显示通知，暂不下载）

### 支持的场景

- ✅ 私聊（1对1）
- ✅ 群组聊天
- ✅ 加密房间（E2EE）
- ✅ 普通房间

## 故障排除

### 问题：无法安装 matrix-nio

**解决方案**：

```bash
# 确保 pip 是最新版本
pip install --upgrade pip

# 重新安装
pip install "matrix-nio[e2e]>=0.25.0"
```

### 问题：登录失败

**可能原因**：
- 用户名或密码错误
- Homeserver 地址错误
- 网络问题

**解决方案**：
1. 在 Element 中确认能正常登录
2. 检查配置文件中的 Matrix ID 格式是否正确
3. 尝试 ping homeserver: `ping matrix.org`

### 问题：E2EE 不工作

**解决方案**：

1. 确认已安装 `[e2e]` 额外依赖：
   ```bash
   pip show matrix-nio | grep "e2e"
   ```

2. 查看日志，应该看到：
   ```
   [INFO] Matrix E2EE support enabled
   ```

3. 在 Element 中验证机器人设备

4. 如果仍有问题，清空密钥存储：
   ```bash
   rm -rf data/matrix_store/*
   ```
   然后重启 AstrBot

### 问题：机器人不响应

**检查清单**：
- ✅ 机器人是否成功加入房间？
- ✅ 是否配置了正确的唤醒词？（查看 AstrBot 主配置）
- ✅ 日志中是否有错误？
- ✅ 网络连接是否正常？

## 进阶配置

### 使用自建 Matrix 服务器

如果你有自己的 Matrix 服务器（例如 Synapse）：

```json
{
  "matrix_homeserver": "https://your-matrix-server.com"
}
```

### 多机器人配置

你可以同时运行多个 Matrix 机器人：

```json
{
  "platform": [
    {
      "id": "matrix_bot1",
      "type": "matrix",
      "enable": true,
      "matrix_user_id": "@bot1:matrix.org",
      "matrix_password": "password1",
      ...
    },
    {
      "id": "matrix_bot2",
      "type": "matrix",
      "enable": true,
      "matrix_user_id": "@bot2:matrix.org",
      "matrix_password": "password2",
      ...
    }
  ]
}
```

## 测试脚本

我们提供了一个测试脚本来验证配置：

```bash
cd astrbot/core/platform/sources/matrix
python test_matrix.py
```

按照提示输入你的 Matrix 凭据，脚本会测试：
- 连接到 Homeserver
- 登录
- E2EE 功能
- 同步房间

## 获取帮助

### 文档

- [完整设置指南](./MATRIX_SETUP_GUIDE.md)
- [技术文档](../astrbot/core/platform/sources/matrix/README.md)
- [集成报告](../MATRIX_INTEGRATION.md)

### 外部资源

- [Matrix 官网](https://matrix.org)
- [Element 客户端](https://app.element.io)
- [matrix-nio 文档](https://matrix-nio.readthedocs.io/)

### 社区支持

如果遇到问题：
1. 查看 AstrBot 文档
2. 在 GitHub 上提交 Issue
3. 加入 AstrBot 社区讨论

## 安全建议

1. ✅ 使用访问令牌代替密码（更安全）
2. ✅ 定期验证设备
3. ✅ 在加密房间中使用机器人
4. ✅ 保护好 `data/matrix_store/` 目录
5. ✅ 不要在配置文件中使用明文密码（使用访问令牌）

## 下一步

现在你的 Matrix 机器人已经运行了！你可以：

1. 🤖 安装 AstrBot 插件增强功能
2. 🔐 在 Element 中验证设备提高安全性
3. 👥 创建更多房间并邀请机器人
4. 📝 自定义机器人的行为和响应
5. 🚀 探索 AstrBot 的更多功能

祝使用愉快！🎉
