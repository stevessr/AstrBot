# Matrix E2EE 自动设置指南

本文档介绍如何使用 Matrix E2EE 自动设置功能，实现密钥交换和设备验证的自动化。

## 🎯 功能概述

E2EE 自动设置模块提供以下功能：

1. **自动获取用户设备列表** - 使用 `/devices` API 获取当前用户的所有设备
2. **自动查询设备密钥** - 使用 `/keys/query` API 获取设备的加密密钥
3. **自动建立 Olm 会话** - 使用 `/keys/claim` API 声明一次性密钥并建立会话
4. **自动验证设备** - 可选的自动验证自己的其他设备

## 📋 使用的 Matrix API

### 1. GET /_matrix/client/v3/account/whoami

获取当前登录用户的信息。

**响应示例：**
```json
{
  "user_id": "@alice:example.org",
  "device_id": "ABCDEFGH"
}
```

### 2. GET /_matrix/client/v3/devices

获取当前用户的所有设备列表。

**响应示例：**
```json
{
  "devices": [
    {
      "device_id": "ABCDEFGH",
      "display_name": "Alice's Phone",
      "last_seen_ip": "192.168.1.100",
      "last_seen_ts": 1234567890000
    },
    {
      "device_id": "IJKLMNOP",
      "display_name": "Alice's Laptop",
      "last_seen_ip": "192.168.1.101",
      "last_seen_ts": 1234567891000
    }
  ]
}
```

### 3. POST /_matrix/client/v3/keys/query

查询用户设备的加密密钥。

**请求示例：**
```json
{
  "device_keys": {
    "@alice:example.org": ["ABCDEFGH", "IJKLMNOP"]
  },
  "timeout": 10000
}
```

**响应示例：**
```json
{
  "device_keys": {
    "@alice:example.org": {
      "ABCDEFGH": {
        "user_id": "@alice:example.org",
        "device_id": "ABCDEFGH",
        "algorithms": ["m.olm.v1.curve25519-aes-sha2", "m.megolm.v1.aes-sha2"],
        "keys": {
          "curve25519:ABCDEFGH": "wjLpTLRqbqBzLs63aYaEv2Boi6cFEbbM/sSRQ2oAKk4",
          "ed25519:ABCDEFGH": "nE6W2fCblxDcOFmeEtCHNl8/l8bXcu7GKyAswA4r3mM"
        },
        "signatures": {
          "@alice:example.org": {
            "ed25519:ABCDEFGH": "m53Wkbh2HXkc3vFApZvCrfXcX3AI51GsDHustMhKwlv3TuOJMj4wistcOTM8q2+e/Ro7rWFUb9ZfnNbwptSUBA"
          }
        }
      }
    }
  }
}
```

### 4. POST /_matrix/client/v3/keys/claim

声明一次性密钥用于建立 Olm 会话。

**请求示例：**
```json
{
  "one_time_keys": {
    "@alice:example.org": {
      "IJKLMNOP": "signed_curve25519"
    }
  }
}
```

**响应示例：**
```json
{
  "one_time_keys": {
    "@alice:example.org": {
      "IJKLMNOP": {
        "signed_curve25519:AAAAHg": {
          "key": "zKbLg+NrIjpnagy+pIY6uPL4ZwEG2v+8F9lmgsnlZzs",
          "signatures": {
            "@alice:example.org": {
              "ed25519:IJKLMNOP": "IQeCEPb9HFk217cU9kw9EOiusC6kMIkoIRnbnfOh5Oc63S1ghgyjShBGpu34blQomoalCyXWyhaaT3MrLZYQAA"
            }
          }
        }
      }
    }
  }
}
```

### 5. PUT /_matrix/client/v3/sendToDevice/{eventType}/{txnId}

发送 to-device 消息（用于设备验证）。

**请求示例：**
```json
{
  "messages": {
    "@alice:example.org": {
      "IJKLMNOP": {
        "transaction_id": "m1234567890",
        "method": "m.sas.v1"
      }
    }
  }
}
```

## 🚀 使用方法

### 基本使用

E2EE 自动设置在 E2EE 管理器初始化时自动执行：

```python
# 初始化 E2EE 管理器（会自动执行设置）
e2ee_manager = MatrixE2EEManager(
    store_path="./data/matrix_store",
    user_id="@alice:example.org",
    device_id="ABCDEFGH",
    homeserver="https://matrix.org",
    client=http_client
)

# 初始化时自动设置 E2EE
await e2ee_manager.initialize(auto_setup=True)
```

### 手动触发自动设置

如果需要手动触发自动设置：

```python
# 手动执行 E2EE 自动设置
success = await e2ee_manager.auto_setup.setup_e2ee()

if success:
    print("E2EE setup completed successfully")
else:
    print("E2EE setup failed")
```

### 配置选项

可以配置自动设置的行为：

```python
# 启用自动验证自己的设备
e2ee_manager.auto_setup.auto_verify_own_devices = True

# 启用自动接受所有验证请求（谨慎使用！）
e2ee_manager.auto_setup.auto_accept_verifications = False
```

## 📊 工作流程

### 完整的自动设置流程

```
1. 获取设备列表
   ↓
2. 查询设备密钥
   ↓
3. 对每个设备：
   ├─ 检查是否已有 Olm 会话
   ├─ 如果没有，声明一次性密钥
   ├─ 创建 Olm 会话
   └─ 保存会话到存储
   ↓
4. 自动验证设备（可选）
   ↓
5. 完成
```

### 日志输出示例

```
[INFO] [matrix] 🔐 Starting automatic E2EE setup...
[INFO] [matrix] Found 3 device(s) for user @alice:example.org
[INFO] [matrix]   📱 Device: ABCDEFGH (current)
[INFO] [matrix]      Name: Alice's Phone
[INFO] [matrix]      Last seen: 2025-10-22 00:30:00
[INFO] [matrix]   📱 Device: IJKLMNOP
[INFO] [matrix]      Name: Alice's Laptop
[INFO] [matrix]      Last seen: 2025-10-21 18:45:00
[INFO] [matrix]   📱 Device: QRSTUVWX
[INFO] [matrix]      Name: Alice's Desktop
[INFO] [matrix]      Last seen: 2025-10-20 12:00:00
[INFO] [matrix] 🔍 Querying keys for 3 device(s)...
[INFO] [matrix] ✅ Retrieved keys for 3 device(s)
[INFO] [matrix] 🔑 Claiming one-time key for device IJKLMNOP...
[INFO] [matrix] 🔗 Creating Olm session with device IJKLMNOP...
[INFO] [matrix] ✅ Olm session created for device IJKLMNOP
[INFO] [matrix] 🔑 Claiming one-time key for device QRSTUVWX...
[INFO] [matrix] 🔗 Creating Olm session with device QRSTUVWX...
[INFO] [matrix] ✅ Olm session created for device QRSTUVWX
[INFO] [matrix] ✅ Created 2 Olm session(s)
[INFO] [matrix] 🔐 Auto-verifying own devices...
[INFO] [matrix] ✅ Auto-verified device IJKLMNOP
[INFO] [matrix] ✅ Auto-verified device QRSTUVWX
[INFO] [matrix] ✅ E2EE automatic setup completed successfully
```

## 🔧 高级功能

### 获取设备列表

```python
devices = await e2ee_manager.auto_setup.get_user_devices()

for device in devices:
    print(f"Device: {device['device_id']}")
    print(f"Name: {device.get('display_name', 'Unknown')}")
```

### 查询设备密钥

```python
device_keys = await e2ee_manager.auto_setup.query_device_keys(devices)

for device_id, keys in device_keys.items():
    print(f"Device {device_id}:")
    print(f"  Algorithms: {keys.get('algorithms')}")
    print(f"  Keys: {keys.get('keys')}")
```

### 建立 Olm 会话

```python
sessions_created = await e2ee_manager.auto_setup.establish_olm_sessions(device_keys)
print(f"Created {sessions_created} Olm sessions")
```

### 处理验证请求

```python
# 当收到验证请求时
should_accept = await e2ee_manager.auto_setup.handle_verification_request(
    sender_user_id="@alice:example.org",
    sender_device_id="IJKLMNOP",
    transaction_id="m1234567890"
)

if should_accept:
    # 接受验证
    pass
```

## ⚠️ 安全注意事项

1. **自动验证设备** - 默认启用自动验证自己的设备，这在大多数情况下是安全的
2. **自动接受验证** - 默认禁用自动接受所有验证请求，因为这可能带来安全风险
3. **密钥存储** - 所有密钥和会话都安全存储在本地数据库中
4. **一次性密钥** - 每次建立会话都使用新的一次性密钥，确保前向保密性

## 🐛 故障排除

### 无法获取设备列表

**问题：** `get_devices()` 返回空列表

**解决方案：**
- 确保已正确登录
- 检查访问令牌是否有效
- 确认服务器支持设备管理 API

### 无法查询设备密钥

**问题：** `query_keys()` 返回空字典

**解决方案：**
- 确保设备已上传密钥到服务器
- 检查 E2EE 是否已正确初始化
- 确认服务器支持 E2EE

### 无法建立 Olm 会话

**问题：** `establish_olm_sessions()` 返回 0

**解决方案：**
- 确保目标设备有可用的一次性密钥
- 检查 vodozemac 库是否正确安装
- 查看日志了解具体错误信息

## 📚 相关文档

- [Matrix E2EE 概述](./README.md)
- [设备验证指南](./e2ee_verification.py)
- [密钥恢复指南](./e2ee_recovery.py)
- [Matrix Client-Server API](https://spec.matrix.org/v1.8/client-server-api/)

