# Matrix E2EE 插件

Matrix 端到端加密（E2EE）设备验证和密钥恢复插件。

## 📖 快速开始

**最简单的使用方式：**

1. 发送消息给机器人：`/e2ee_verify`
2. 获取验证码：`/e2ee_sas <verification_id>`
3. 与对方比对验证码
4. 确认验证码：`/e2ee_confirm <verification_id> <sas_code>`
5. 完成验证：`/e2ee_complete <verification_id>`

**详细使用指南：** 请查看 [USER_GUIDE.md](./USER_GUIDE.md)

## ✨ 功能特性

### 设备验证
- ✅ 自动识别发送者设备
- ✅ 自动接受验证请求
- ✅ SAS 验证码比对
- ✅ 设备信任管理

### 密钥恢复
- ✅ 向同账号其他设备请求密钥
- ✅ 6 位验证码确认
- ✅ 自动密钥导入

## 命令

### 设备验证
- `/e2ee_verify <user_id> <device_id>` - 启动设备验证
- `/e2ee_accept <verification_id>` - 接受设备验证
- `/e2ee_sas <verification_id>` - 获取 SAS 验证码
- `/e2ee_confirm <verification_id> <sas_code>` - 确认 SAS 验证码
- `/e2ee_complete <verification_id>` - 完成设备验证

### 密钥恢复
- `/e2ee_recovery_request <device_id>` - 请求密钥恢复
- `/e2ee_recovery_accept <request_id>` - 接受恢复请求
- `/e2ee_recovery_code <request_id>` - 获取恢复验证码
- `/e2ee_recovery_confirm <request_id> <code>` - 确认恢复验证码
- `/e2ee_recovery_share <request_id>` - 分享密钥
- `/e2ee_recovery_receive <request_id>` - 接收密钥
- `/e2ee_recovery_status [request_id]` - 查看恢复状态

### 查询
- `/e2ee_status [verification_id]` - 查看验证状态
- `/e2ee_devices <user_id>` - 查看已验证设备
- `/e2ee_keys` - 查看身份密钥
- `/e2ee_help` - 显示帮助信息

## 📝 使用示例

### 设备验证流程（自动模式）

```
用户：/e2ee_verify
系统：✓ 已启动验证会话：abc123...
     ✓ 已自动接受验证请求

用户：/e2ee_sas abc123
系统：✓ SAS 验证码：20ECC85F-BA08382E-AAA426DA

# 与对方比对验证码

用户：/e2ee_confirm abc123 20ECC85F-BA08382E-AAA426DA
系统：✓ SAS 码已确认

用户：/e2ee_complete abc123
系统：✓ 设备验证已完成
```

### 密钥恢复流程

```
新设备：/e2ee_recovery_request <old_device_id>
旧设备：/e2ee_recovery_accept <request_id>
旧设备：/e2ee_recovery_code <request_id>
# 比对验证码
新设备：/e2ee_recovery_confirm <request_id> <code>
旧设备：/e2ee_recovery_share <request_id>
新设备：/e2ee_recovery_receive <request_id>
```

## 🔧 依赖

- Matrix 适配器（需支持 E2EE 管理器）
- vodozemac 加密库

## 📋 版本

- **当前版本**：v1.0.0
- **支持的 Matrix 规范**：v1.11

## 📚 文档

- [详细使用指南](./USER_GUIDE.md) - 完整的使用说明和示例
- [Matrix E2EE 规范](https://spec.matrix.org/v1.11/client-server-api/#end-to-end-encryption)

