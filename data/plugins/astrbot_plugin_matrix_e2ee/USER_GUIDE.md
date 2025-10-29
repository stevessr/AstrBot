# Matrix E2EE 插件使用指南

## 📖 简介

Matrix E2EE（端到端加密）插件为 AstrBot 提供了完整的 Matrix 加密消息支持，包括：
- 🔐 设备验证（SAS 验证）
- 🔑 密钥恢复
- 🛡️ 设备信任管理

## 🚀 快速开始

### 1. 设备验证（最常用）

当你想要与某个用户建立加密通信时，需要先验证对方的设备。

#### 方法一：自动验证（推荐）

直接发送消息给机器人：

```
/e2ee_verify
```

机器人会自动：
1. 识别你的用户 ID 和设备 ID
2. 发起验证请求
3. 自动接受验证
4. 提示你获取 SAS 验证码

#### 方法二：手动指定设备

如果需要验证特定设备：

```
/e2ee_verify @alice:example.com DEVICEID123
```

### 2. 获取并比对 SAS 验证码

验证启动后，双方都需要获取 SAS 验证码并比对：

```
/e2ee_sas <verification_id>
```

**示例输出：**
```
✓ SAS 验证码：20ECC85F-BA08382E-AAA426DA
请与对方比对此验证码
```

**重要：** 双方必须确认看到的验证码完全一致！

### 3. 确认验证码

确认验证码匹配后：

```
/e2ee_confirm <verification_id> 20ECC85F-BA08382E-AAA426DA
```

### 4. 完成验证

最后一步：

```
/e2ee_complete <verification_id>
```

完成后，该设备将被标记为已验证，可以进行加密通信。

## 📋 完整命令列表

### 设备验证命令

| 命令 | 用法 | 说明 |
|------|------|------|
| `/e2ee_verify` | `/e2ee_verify [user_id] [device_id]` | 启动设备验证（不带参数时自动识别） |
| `/e2ee_accept` | `/e2ee_accept <verification_id>` | 手动接受验证（通常已自动接受） |
| `/e2ee_sas` | `/e2ee_sas <verification_id>` | 获取 SAS 验证码 |
| `/e2ee_confirm` | `/e2ee_confirm <verification_id> <sas_code>` | 确认 SAS 验证码 |
| `/e2ee_complete` | `/e2ee_complete <verification_id>` | 完成设备验证 |

### 密钥恢复命令

当你有新设备需要恢复密钥时使用：

| 命令 | 用法 | 说明 |
|------|------|------|
| `/e2ee_recovery_request` | `/e2ee_recovery_request <device_id>` | 向旧设备请求密钥 |
| `/e2ee_recovery_accept` | `/e2ee_recovery_accept <request_id>` | 接受恢复请求 |
| `/e2ee_recovery_code` | `/e2ee_recovery_code <request_id>` | 获取 6 位验证码 |
| `/e2ee_recovery_confirm` | `/e2ee_recovery_confirm <request_id> <code>` | 确认验证码 |
| `/e2ee_recovery_share` | `/e2ee_recovery_share <request_id>` | 分享密钥 |
| `/e2ee_recovery_receive` | `/e2ee_recovery_receive <request_id>` | 接收密钥 |
| `/e2ee_recovery_status` | `/e2ee_recovery_status [request_id]` | 查看恢复状态 |

### 查询命令

| 命令 | 用法 | 说明 |
|------|------|------|
| `/e2ee_status` | `/e2ee_status [verification_id]` | 查看验证状态 |
| `/e2ee_devices` | `/e2ee_devices <user_id>` | 查看已验证设备 |
| `/e2ee_keys` | `/e2ee_keys` | 查看身份密钥 |
| `/e2ee_help` | `/e2ee_help` | 显示帮助信息 |

## 🔄 完整使用流程

### 场景一：设备验证（Alice 和 Bob）

**Alice 的操作：**
```
1. /e2ee_verify
   → 输出：✓ 已启动验证会话：abc123...
           ✓ 已自动接受验证请求

2. /e2ee_sas abc123
   → 输出：✓ SAS 验证码：20ECC85F-BA08382E-AAA426DA

3. 与 Bob 比对验证码（通过其他安全渠道，如面对面、电话等）

4. /e2ee_confirm abc123 20ECC85F-BA08382E-AAA426DA
   → 输出：✓ SAS 码已确认

5. /e2ee_complete abc123
   → 输出：✓ 设备验证已完成
```

**Bob 的操作：**
```
1. /e2ee_sas abc123
   → 输出：✓ SAS 验证码：20ECC85F-BA08382E-AAA426DA

2. 与 Alice 比对验证码

3. /e2ee_confirm abc123 20ECC85F-BA08382E-AAA426DA
   → 输出：✓ SAS 码已确认
```

### 场景二：密钥恢复（新设备恢复旧设备的密钥）

**新设备的操作：**
```
1. /e2ee_recovery_request OLDDEVICE123
   → 输出：✓ 已发送密钥恢复请求：req456...

2. 等待旧设备接受并生成验证码

3. /e2ee_recovery_confirm req456 123456
   → 输出：✓ 恢复验证码已确认

4. /e2ee_recovery_receive req456
   → 输出：✓ 密钥已接收并导入
```

**旧设备的操作：**
```
1. /e2ee_recovery_accept req456
   → 输出：✓ 已接受恢复请求

2. /e2ee_recovery_code req456
   → 输出：✓ 恢复验证码：123456

3. 通过安全渠道告知新设备验证码

4. /e2ee_recovery_share req456
   → 输出：✓ 密钥已分享
```

## 🔍 查询和管理

### 查看验证状态

查看所有验证会话：
```
/e2ee_status
```

查看特定验证会话：
```
/e2ee_status abc123
```

### 查看已验证设备

```
/e2ee_devices @alice:example.com
```

**示例输出：**
```
用户 @alice:example.com 的已验证设备：
- DEVICEID123
- DEVICEID456
```

### 查看身份密钥

```
/e2ee_keys
```

**示例输出：**
```
身份密钥：
Curve25519：AbCdEf1234567890...
Ed25519：1234567890AbCdEf...
```

## ⚠️ 重要提示

### 安全建议

1. **验证码比对**：务必通过安全渠道（面对面、电话等）比对 SAS 验证码
2. **验证码保密**：不要在不安全的渠道（如未加密的聊天）中发送验证码
3. **定期验证**：定期检查已验证设备列表，移除不再使用的设备

### 自动接受功能

- 插件已启用**自动接受验证请求**功能
- 使用 `/e2ee_verify` 时会自动接受验证
- 这简化了验证流程，但仍需手动比对 SAS 验证码

### 故障排除

**问题：提示 "E2EE 未启用"**
- 检查 Matrix 适配器是否正确配置
- 确认 E2EE 管理器已初始化

**问题：无法获取设备 ID**
- 使用手动指定设备的方式：`/e2ee_verify @user:server.com DEVICEID`
- 检查 Matrix 客户端是否正确发送设备信息

**问题：验证码不匹配**
- 确认双方使用的是同一个 verification_id
- 重新启动验证流程

## 📚 技术细节

### SAS 验证码格式

- 12 字节验证码
- 格式化为 3 组 8 位十六进制字符串
- 示例：`20ECC85F-BA08382E-AAA426DA`

### 密钥恢复验证码

- 6 位数字（000000-999999）
- 基于时间戳和请求 ID 生成
- 5 分钟超时

### 验证状态

- `started` - 已启动
- `accepted` - 已接受
- `sas_generated` - SAS 已生成
- `sas_confirmed` - SAS 已确认
- `verified` - 已验证
- `cancelled` - 已取消

## 🆘 获取帮助

在 Matrix 中发送：
```
/e2ee_help
```

查看所有可用命令和简要说明。

## 📝 版本信息

- 插件版本：v1.0.0
- 支持的 Matrix 规范：v1.11
- 加密库：vodozemac

## 🔗 相关资源

- [Matrix E2EE 规范](https://spec.matrix.org/v1.11/client-server-api/#end-to-end-encryption)
- [AstrBot 文档](https://docs.astrbot.app)
- [vodozemac 文档](https://docs.rs/vodozemac/)

