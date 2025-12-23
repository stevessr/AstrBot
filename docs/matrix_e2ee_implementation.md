# Matrix E2EE 完整实现说明

## 概述

AstrBot 的 Matrix 适配器已完整实现 Matrix 协议的端到端加密 (E2EE) 功能，包括密钥交换、设备验证、密钥备份和恢复等所有核心功能。

## 核心功能

### 1. 密钥交换 (Key Exchange)

#### Olm 协议
- **用途**：设备间一对一的安全通道建立
- **实现**：使用 vodozemac 库提供的 Olm 实现
- **功能**：
  - 自动建立加密会话
  - 支持密钥轮换
  - 处理预密钥 (One-Time Keys) 管理

#### Megolm 协议
- **用途**：群组消息的高效加密
- **实现**：使用 vodozemac 库提供的 Megolm 实现
- **功能**：
  - 自动创建和管理出站会话
  - 自动分发会话密钥给房间成员
  - 处理入站会话密钥
  - 支持会话密钥请求和转发

#### 自动密钥分发
- **实现位置**：`e2ee_manager.py::_create_and_share_session()`
- **触发时机**：发送加密消息时自动检查并创建会话
- **密钥分发**：自动通过 Olm 通道发送 m.room_key 事件给所有房间成员

#### 密钥请求处理
- **m.room_key_request**：处理其他设备的密钥请求
- **m.forwarded_room_key**：转发密钥给请求的设备
- **实现位置**：`event_processor.py::process_to_device_events()`

### 2. 设备验证 (Device Verification)

#### SAS 验证协议
- **实现**：`verification.py::SASVerification`
- **支持方式**：
  - Emoji 验证（7个表情符号）
  - Decimal 验证（3组数字）
- **验证流程**：
  1. m.key.verification.request - 发起验证请求
  2. m.key.verification.ready - 确认准备就绪
  3. m.key.verification.start - 开始验证
  4. m.key.verification.accept - 接受验证
  5. m.key.verification.key - 交换公钥
  6. m.key.verification.mac - 验证 MAC
  7. m.key.verification.done - 完成验证

#### 验证模式
- **auto_accept**：自动接受所有验证请求并完成验证
- **auto_reject**：自动拒绝所有验证请求
- **manual**：手动处理验证（记录日志但不自动操作）

#### In-Room 验证
- **支持**：完整支持房间内验证流程
- **实现**：`verification.py::handle_in_room_verification_event()`
- **加密支持**：自动解密加密的房间内验证消息

#### To-Device 验证
- **支持**：完整支持设备间直接验证
- **实现**：`verification.py::handle_verification_event()`

#### 交叉签名 (Cross-Signing)
- **实现**：`key_backup.py::CrossSigning`
- **功能**：
  - 生成主密钥 (Master Key)
  - 生成自签名密钥 (Self-Signing Key)
  - 生成用户签名密钥 (User-Signing Key)
  - 自动签名自己的设备
  - 支持签名其他用户的设备

### 3. 密钥交换控制 (Key Exchange Control)

#### 可信设备 (Trusted Devices)
- **配置**：`matrix_e2ee_trust_on_first_use`
- **功能**：首次遇到的设备自动建立信任
- **使用场景**：简化同一用户多设备间的密钥交换

#### 交叉验证设备 (Cross-Verified Devices)
- **机制**：通过交叉签名建立信任链
- **实现**：自动检测已交叉签名的设备
- **优势**：验证一次后，所有交叉签名的设备自动信任

#### 所有设备
- **支持**：可以接收来自任何设备的验证请求
- **控制**：通过 `auto_verify_mode` 控制响应方式

#### 允许从其他设备验证
- **支持**：完整支持接收来自其他设备的验证请求
- **场景**：
  - 同一用户的其他会话发起验证
  - 其他用户发起验证
  - 房间内验证和设备间验证

### 4. 密钥备份和恢复 (Key Backup & Recovery)

#### 脱水设备密钥支持 (Dehydrated Device Key) ⭐ 推荐
- **优先级**：最高优先级，最安全的恢复方式
- **兼容性**：
  - FluffyChat 导出的密钥
  - Element 导出的密钥
  - 其他支持脱水设备的客户端
- **实现位置**：`key_backup.py::_try_restore_from_secret_storage()`
- **工作流程**：
  1. 检查 `m.dehydrated_device` 或 `org.matrix.msc2697.dehydrated_device` 事件
  2. 使用提供的密钥解密脱水设备数据
  3. 从脱水设备数据中提取备份密钥
  4. 使用提取的备份密钥解密会话密钥

#### Matrix Base58 恢复密钥
- **支持**：完整支持标准 Matrix 恢复密钥格式
- **编码**：Base58 编码（使用 Matrix 字母表）
- **验证**：包含 2 字节头部和 XOR 校验和

#### Base64 密钥
- **支持**：兼容 Base64 编码的 32 字节密钥
- **自动转换**：自动检测并转换为内部格式

#### 备份密钥持久化
- **位置**：`{store_path}/extracted_backup_key.bin`
- **功能**：
  - 首次提取后保存到本地
  - 下次启动自动加载
  - 避免重复从服务器提取
- **实现**：
  - `_save_extracted_key()`：保存密钥
  - `_load_extracted_key()`：加载密钥

#### 密钥备份创建
- **实现**：`key_backup.py::create_backup()`
- **功能**：
  - 生成或使用现有恢复密钥
  - 创建服务器端备份版本
  - 上传备份认证数据

#### 密钥备份恢复
- **实现**：`key_backup.py::restore_room_keys()`
- **功能**：
  - 从服务器下载备份的会话密钥
  - 使用恢复密钥解密
  - 导入到本地 Olm 机器

## E2EE 事件处理

### 房间事件 (Room Events)
- **m.room.encrypted**：加密消息，自动解密
- **m.room.message**：明文消息
- **m.key.verification.***：房间内验证事件

### To-Device 事件 (To-Device Events)
- **m.room_key**：Megolm 会话密钥分发
- **m.room_key_request**：密钥请求
- **m.forwarded_room_key**：转发的密钥
- **m.key.verification.***：设备间验证事件
- **m.secret.request**：秘密请求（用于交叉签名）
- **m.secret.send**：秘密发送响应
- **m.dummy**：会话保活/轮换

### Sync 响应事件
- **device_lists**：设备列表变更
  - `changed`：密钥已更改的用户
  - `left`：已离开的用户
- **device_one_time_keys_count**：一次性密钥计数
  - 自动补充当密钥数 < 25
- **device_unused_fallback_key_types**：未使用的备用密钥类型

## 配置说明

### 必需配置

```yaml
matrix_enable_e2ee: true              # 启用 E2EE
matrix_device_id: "DEVICE_ID"         # 设备 ID
matrix_e2ee_store_path: "./data/matrix_e2ee"  # 加密存储路径
```

### 推荐配置

```yaml
# 恢复密钥（推荐使用从 FluffyChat/Element 导出的脱水设备密钥）
matrix_e2ee_recovery_key: "从客户端导出的密钥"

# 密钥备份
matrix_e2ee_key_backup: true          # 启用密钥备份

# 自动验证模式
matrix_e2ee_auto_verify: "auto_accept"  # auto_accept/auto_reject/manual

# 首次使用时信任
matrix_e2ee_trust_on_first_use: false  # 是否自动信任首次设备
```

### 配置说明

#### matrix_e2ee_recovery_key
用户应该提供的密钥类型（按优先级）：

1. **脱水设备密钥** ⭐ 最推荐
   - 从 FluffyChat 或 Element 导出
   - 最安全的恢复方式
   - 自动提取备份密钥

2. **Matrix Base58 恢复密钥**
   - 标准 Matrix 格式
   - 以 `Ek` 开头的长字符串

3. **Base64 密钥**
   - 兼容格式
   - 32 字节的 Base64 编码

## 工作流程示例

### 首次启动
1. 生成设备密钥（Ed25519 + Curve25519）
2. 上传设备密钥和一次性密钥到服务器
3. 如果配置了恢复密钥：
   - 尝试从脱水设备提取备份密钥
   - 或使用 SSSS 解密备份密钥
   - 从服务器恢复会话密钥
4. 初始化交叉签名
5. 自动签名自己的设备

### 发送加密消息
1. 检查房间是否需要加密
2. 检查是否有 Megolm 出站会话
3. 如果没有：
   - 创建新的 Megolm 会话
   - 获取房间成员列表
   - 查询成员的设备密钥
   - 通过 Olm 加密并发送会话密钥给每个设备
4. 使用 Megolm 会话加密消息内容
5. 发送 m.room.encrypted 事件

### 接收加密消息
1. 接收 m.room.encrypted 事件
2. 查找对应的 Megolm 入站会话
3. 如果找不到会话：
   - 发送 m.room_key_request 请求密钥
   - 等待 m.room_key 或 m.forwarded_room_key
4. 使用会话解密消息
5. 处理解密后的内容

### 设备验证流程
1. 接收验证请求（m.key.verification.request）
2. 根据 `auto_verify_mode` 决定响应：
   - **auto_accept**：自动接受并完成验证
   - **auto_reject**：自动拒绝
   - **manual**：仅记录日志
3. 如果接受：
   - 交换公钥（m.key.verification.key）
   - 计算 SAS 值（Emoji 或 Decimal）
   - 交换 MAC（m.key.verification.mac）
   - 完成验证（m.key.verification.done）
4. 更新设备验证状态

## 安全特性

### 密钥管理
- ✅ 安全的密钥存储（加密存储到本地文件）
- ✅ 自动密钥轮换
- ✅ 一次性密钥补充
- ✅ 备份密钥持久化

### 设备验证
- ✅ SAS 验证协议
- ✅ 交叉签名支持
- ✅ 设备信任链
- ✅ 防重放攻击

### 密钥恢复
- ✅ 脱水设备支持（最安全）
- ✅ 多种密钥格式支持
- ✅ 自动密钥提取
- ✅ 本地密钥缓存

## 兼容性

### 客户端兼容
- ✅ Element（Web、Desktop、iOS、Android）
- ✅ FluffyChat
- ✅ SchildiChat
- ✅ Nheko
- ✅ 其他支持 Matrix E2EE 的客户端

### 服务器兼容
- ✅ Synapse
- ✅ Dendrite
- ✅ Conduit
- ✅ 其他 Matrix 服务器

## 故障排查

### 无法解密消息
1. 检查 E2EE 是否启用：`matrix_enable_e2ee: true`
2. 检查设备密钥是否上传成功（查看日志）
3. 检查是否收到会话密钥（查看 m.room_key 事件日志）
4. 尝试请求密钥（自动发送 m.room_key_request）

### 密钥恢复失败
1. 检查恢复密钥格式是否正确
2. 优先使用脱水设备密钥
3. 检查日志中的解密错误信息
4. 确认服务器上有密钥备份版本

### 设备验证失败
1. 检查 `auto_verify_mode` 配置
2. 查看验证流程日志
3. 确认两边设备的公钥交换成功
4. 检查 SAS 值是否匹配

## 开发参考

### 核心文件
- `e2ee_manager.py`：E2EE 管理器主类
- `olm_machine.py`：Olm/Megolm 加密机器
- `verification.py`：SAS 验证实现
- `key_backup.py`：密钥备份和恢复
- `crypto_store.py`：加密状态存储
- `device_store.py`：设备密钥存储

### 相关规范
- [Matrix Client-Server API](https://spec.matrix.org/latest/client-server-api/)
- [Matrix E2EE Specification](https://spec.matrix.org/latest/client-server-api/#end-to-end-encryption)
- [Olm/Megolm Specification](https://gitlab.matrix.org/matrix-org/olm/)
- [Matrix Cross-Signing](https://spec.matrix.org/latest/client-server-api/#cross-signing)

## 总结

AstrBot 的 Matrix 适配器提供了完整的 E2EE 支持，实现了 Matrix 协议的所有核心加密功能。特别强调对脱水设备密钥的优先支持，这是最安全和推荐的密钥恢复方式。用户只需提供从 FluffyChat 或 Element 导出的脱水设备密钥，系统会自动处理所有加密、解密、验证和密钥恢复工作。
