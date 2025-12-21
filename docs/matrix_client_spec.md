# Matrix 客户端规范 (Client-Server API)

> 基于 Matrix Specification v1.17 (https://spec.matrix.org/latest/)
> 
> 本文档提取了客户端实现所需的所有关键规范和技术细节

---

## 目录

1. [概述](#1-概述)
2. [架构](#2-架构)
3. [API 标准](#3-api-标准)
4. [服务器发现](#4-服务器发现)
5. [客户端认证](#5-客户端认证)
6. [账户管理](#6-账户管理)
7. [能力协商](#7-能力协商)
8. [过滤器](#8-过滤器)
9. [事件](#9-事件)
10. [同步](#10-同步)
11. [房间](#11-房间)
12. [消息发送](#12-消息发送)
13. [用户资料](#13-用户资料)
14. [模块](#14-模块)
15. [端到端加密 (E2EE)](#15-端到端加密-e2ee)
16. [媒体库](#16-媒体库)
17. [设备管理](#17-设备管理)
18. [推送通知](#18-推送通知)
19. [VoIP 通话](#19-voip-通话)

---

## 1. 概述

Matrix 是一组开放的 API，用于开放联邦的即时通讯 (IM)、VoIP 和物联网通信。其设计目标是创建一个全新的开放实时通信生态系统。

### 核心原则

- **务实的 Web 友好 API**: JSON over REST
- **保持简单**: 最小化第三方依赖的简单架构
- **完全开放**: 开放联邦 + 公开文档的标准
- **赋能终端用户**: 用户选择服务器和客户端，控制隐私
- **完全去中心化**: 无单点控制

### 规范组成

| 规范 | 说明 |
|------|------|
| **Client-Server API** | 客户端与服务器通信 |
| **Server-Server API** | 服务器间联邦通信 |
| **Application Service API** | 应用服务扩展 |
| **Identity Service API** | 身份服务 |
| **Push Gateway API** | 推送网关 |
| **Room Versions** | 房间版本规范 |
| **Olm & Megolm** | 加密算法规范 |

---

## 2. 架构

### 2.1 用户 (Users)

用户 ID 格式: `@localpart:domain`

- `localpart`: 区分大小写，仅包含 `[a-z0-9._=-/]`
- `domain`: 服务器域名
- 最大长度: 255 字符 (包括 `@` 和 `:`)

### 2.2 设备 (Devices)

- 每个用户可以拥有多个设备
- 每个设备有唯一的 `device_id`
- 设备用于端到端加密的密钥管理
- 访问令牌与设备关联

### 2.3 事件 (Events)

Matrix 中的所有数据都表示为事件:

```json
{
  "type": "m.room.message",
  "content": {
    "msgtype": "m.text",
    "body": "Hello, World!"
  },
  "sender": "@alice:example.com",
  "room_id": "!room:example.com",
  "event_id": "$event123:example.com",
  "origin_server_ts": 1234567890123
}
```

### 2.4 房间 (Rooms)

- **房间 ID**: `!localpart:domain`
- **房间别名**: `#alias:domain`
- 房间是一个事件有向无环图 (DAG)
- 状态事件定义房间元数据

---

## 3. API 标准

### 3.1 请求格式

- **基础路径**: `/_matrix/client/v3/`
- **Content-Type**: `application/json`
- **认证**: `Authorization: Bearer <access_token>`

### 3.2 标准错误响应

```json
{
  "errcode": "M_FORBIDDEN",
  "error": "You are not allowed to do this"
}
```

**常见错误码**:

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| `M_FORBIDDEN` | 403 | 无权限 |
| `M_UNKNOWN_TOKEN` | 401 | 令牌无效/过期 |
| `M_NOT_FOUND` | 404 | 资源不存在 |
| `M_LIMIT_EXCEEDED` | 429 | 速率限制 |
| `M_USER_IN_USE` | 400 | 用户名已占用 |
| `M_INVALID_USERNAME` | 400 | 用户名无效 |
| `M_BAD_JSON` | 400 | JSON 格式错误 |
| `M_NOT_JSON` | 400 | 非 JSON 内容 |
| `M_UNKNOWN` | 500 | 未知错误 |
| `M_UNRECOGNIZED` | 400 | 未识别的请求 |

### 3.3 事务标识符

- 用于幂等性保证
- 客户端生成唯一 `txnId`
- 服务器缓存结果，重复请求返回相同响应

---

## 4. 服务器发现

### 4.1 Well-Known URI

```
GET /.well-known/matrix/client
```

**响应**:
```json
{
  "m.homeserver": {
    "base_url": "https://matrix.example.com"
  },
  "m.identity_server": {
    "base_url": "https://identity.example.com"
  }
}
```

### 4.2 API 版本

```
GET /_matrix/client/versions
```

**响应**:
```json
{
  "versions": ["v1.1", "v1.2", "v1.3"],
  "unstable_features": {
    "org.example.feature": true
  }
}
```

---

## 5. 客户端认证

### 5.1 双认证 API (v1.15+)

1. **Legacy API**: 传统 Matrix 认证
2. **OAuth 2.0 API**: 行业标准认证

两者互不兼容，登录后必须使用同一 API。

### 5.2 用户交互认证 (UIA)

用于敏感操作的多阶段认证:

```json
{
  "flows": [
    { "stages": ["m.login.password"] },
    { "stages": ["m.login.email.identity"] }
  ],
  "params": {},
  "session": "session_id"
}
```

**认证类型**:
- `m.login.password` - 密码认证
- `m.login.recaptcha` - reCAPTCHA
- `m.login.oauth2` - OAuth 2.0
- `m.login.token` - 令牌认证
- `m.login.sso` - 单点登录
- `m.login.email.identity` - 邮箱验证
- `m.login.msisdn` - 手机验证
- `m.login.registration_token` - 注册令牌

### 5.3 登录

```
POST /_matrix/client/v3/login
```

**请求体**:
```json
{
  "type": "m.login.password",
  "identifier": {
    "type": "m.id.user",
    "user": "@alice:example.com"
  },
  "password": "secret",
  "device_id": "DEVICE_ID",
  "initial_device_display_name": "My Device"
}
```

**响应**:
```json
{
  "user_id": "@alice:example.com",
  "access_token": "abc123",
  "device_id": "DEVICE_ID",
  "expires_in_ms": 3600000,
  "refresh_token": "def456"
}
```

### 5.4 刷新令牌

```
POST /_matrix/client/v3/refresh
```

**请求体**:
```json
{
  "refresh_token": "def456"
}
```

### 5.5 登出

```
POST /_matrix/client/v3/logout      # 当前设备
POST /_matrix/client/v3/logout/all  # 所有设备
```

### 5.6 注册

```
POST /_matrix/client/v3/register
```

**请求体**:
```json
{
  "username": "alice",
  "password": "secret",
  "device_id": "DEVICE_ID",
  "initial_device_display_name": "My Device",
  "inhibit_login": false
}
```

---

## 6. 账户管理

### 6.1 账户信息

```
GET /_matrix/client/v3/account/whoami
```

**响应**:
```json
{
  "user_id": "@alice:example.com",
  "device_id": "DEVICE_ID",
  "is_guest": false
}
```

### 6.2 修改密码

```
POST /_matrix/client/v3/account/password
```

### 6.3 停用账户

```
POST /_matrix/client/v3/account/deactivate
```

### 6.4 第三方标识符 (3PID)

管理邮箱、手机等关联:

```
GET  /_matrix/client/v3/account/3pid
POST /_matrix/client/v3/account/3pid/add
POST /_matrix/client/v3/account/3pid/bind
POST /_matrix/client/v3/account/3pid/delete
```

---

## 7. 能力协商

```
GET /_matrix/client/v3/capabilities
```

**响应**:
```json
{
  "capabilities": {
    "m.change_password": { "enabled": true },
    "m.room_versions": {
      "default": "10",
      "available": { "9": "stable", "10": "stable" }
    },
    "m.set_displayname": { "enabled": true },
    "m.set_avatar_url": { "enabled": true },
    "m.3pid_changes": { "enabled": true }
  }
}
```

---

## 8. 过滤器

### 8.1 创建过滤器

```
POST /_matrix/client/v3/user/{userId}/filter
```

**请求体**:
```json
{
  "room": {
    "state": {
      "types": ["m.room.*"],
      "not_types": ["m.room.member"]
    },
    "timeline": {
      "limit": 10,
      "types": ["m.room.message"]
    },
    "ephemeral": {
      "types": ["m.receipt", "m.typing"]
    }
  },
  "presence": {
    "types": ["m.presence"]
  },
  "event_format": "client"
}
```

### 8.2 过滤器选项

| 字段 | 说明 |
|------|------|
| `limit` | 返回事件数量限制 |
| `types` | 包含的事件类型 |
| `not_types` | 排除的事件类型 |
| `senders` | 包含的发送者 |
| `not_senders` | 排除的发送者 |
| `rooms` | 包含的房间 |
| `not_rooms` | 排除的房间 |

### 8.3 延迟加载成员

在过滤器中设置:
```json
{
  "room": {
    "state": {
      "lazy_load_members": true
    }
  }
}
```

---

## 9. 事件

### 9.1 事件格式

**完整事件 (ClientEvent)**:
```json
{
  "type": "m.room.message",
  "event_id": "$event:example.com",
  "sender": "@alice:example.com",
  "room_id": "!room:example.com",
  "origin_server_ts": 1234567890123,
  "content": { ... },
  "unsigned": {
    "age": 1234,
    "transaction_id": "txn123"
  }
}
```

**状态事件额外字段**:
```json
{
  "state_key": "",
  "prev_content": { ... }
}
```

### 9.2 房间事件类型

| 事件类型 | 状态键 | 说明 |
|----------|--------|------|
| `m.room.create` | `""` | 房间创建 |
| `m.room.name` | `""` | 房间名称 |
| `m.room.topic` | `""` | 房间主题 |
| `m.room.avatar` | `""` | 房间头像 |
| `m.room.member` | `user_id` | 成员状态 |
| `m.room.join_rules` | `""` | 加入规则 |
| `m.room.power_levels` | `""` | 权限等级 |
| `m.room.history_visibility` | `""` | 历史可见性 |
| `m.room.guest_access` | `""` | 访客权限 |
| `m.room.canonical_alias` | `""` | 规范别名 |
| `m.room.encryption` | `""` | 加密设置 |
| `m.room.message` | N/A | 消息事件 |
| `m.room.redaction` | N/A | 撤回事件 |

### 9.3 消息类型 (msgtype)

| msgtype | 说明 |
|---------|------|
| `m.text` | 文本消息 |
| `m.emote` | 表情动作 |
| `m.notice` | 通知消息 |
| `m.image` | 图片 |
| `m.file` | 文件 |
| `m.audio` | 音频 |
| `m.video` | 视频 |
| `m.location` | 位置 |

### 9.4 事件关系

通过 `m.relates_to` 建立事件关系:

```json
{
  "m.relates_to": {
    "rel_type": "m.thread",
    "event_id": "$parent_event_id"
  }
}
```

**关系类型**:
- `m.thread` - 话题/线程
- `m.replace` - 编辑/替换
- `m.reference` - 引用
- `m.annotation` - 注释/反应

**回复 (Rich Reply)**:
```json
{
  "m.relates_to": {
    "m.in_reply_to": {
      "event_id": "$original_event_id"
    }
  }
}
```

### 9.5 大小限制

| 项目 | 限制 |
|------|------|
| 事件 JSON | 65536 字节 |
| 用户 ID | 255 字符 |
| 房间 ID | 255 字符 |
| 事件类型 | 255 字符 |
| 状态键 | 255 字符 |

---

## 10. 同步

### 10.1 同步 API

```
GET /_matrix/client/v3/sync
```

**参数**:
| 参数 | 说明 |
|------|------|
| `since` | 上次同步的 `next_batch` |
| `timeout` | 长轮询超时 (毫秒) |
| `filter` | 过滤器 ID 或 JSON |
| `full_state` | 是否返回完整状态 |
| `set_presence` | 设置在线状态 |

### 10.2 同步响应结构

```json
{
  "next_batch": "s123_456_789",
  "rooms": {
    "join": {
      "!room:example.com": {
        "state": {
          "events": [...]
        },
        "timeline": {
          "events": [...],
          "limited": false,
          "prev_batch": "t123_456"
        },
        "ephemeral": {
          "events": [...]
        },
        "account_data": {
          "events": [...]
        },
        "unread_notifications": {
          "notification_count": 5,
          "highlight_count": 2
        },
        "summary": {
          "m.heroes": ["@alice:example.com"],
          "m.joined_member_count": 10,
          "m.invited_member_count": 2
        }
      }
    },
    "invite": { ... },
    "leave": { ... },
    "knock": { ... }
  },
  "presence": {
    "events": [...]
  },
  "account_data": {
    "events": [...]
  },
  "to_device": {
    "events": [...]
  },
  "device_lists": {
    "changed": ["@bob:example.com"],
    "left": []
  },
  "device_one_time_keys_count": {
    "signed_curve25519": 50
  },
  "device_unused_fallback_key_types": ["signed_curve25519"]
}
```

### 10.3 同步流程

1. **初始同步**: 不带 `since` 参数
2. **增量同步**: 使用上次的 `next_batch` 作为 `since`
3. **长轮询**: 设置 `timeout` 等待新事件
4. **有限时间线**: `limited: true` 表示有遗漏事件

### 10.4 填补时间线空隙

```
GET /_matrix/client/v3/rooms/{roomId}/messages
```

**参数**:
| 参数 | 说明 |
|------|------|
| `from` | 起始位置 (prev_batch) |
| `to` | 结束位置 |
| `dir` | 方向 (b=向后, f=向前) |
| `limit` | 返回数量 |
| `filter` | 过滤器 |

---

## 11. 房间

### 11.1 创建房间

```
POST /_matrix/client/v3/createRoom
```

**请求体**:
```json
{
  "name": "My Room",
  "topic": "A room for testing",
  "room_alias_name": "myroom",
  "preset": "private_chat",
  "visibility": "private",
  "invite": ["@bob:example.com"],
  "is_direct": false,
  "creation_content": {
    "m.federate": true
  },
  "initial_state": [
    {
      "type": "m.room.encryption",
      "content": {
        "algorithm": "m.megolm.v1.aes-sha2"
      }
    }
  ],
  "power_level_content_override": { ... }
}
```

**预设值**:
| preset | 说明 |
|--------|------|
| `private_chat` | 私聊，仅邀请可加入 |
| `public_chat` | 公开，任何人可加入 |
| `trusted_private_chat` | 可信私聊，所有人有完整权限 |

### 11.2 房间别名

```
GET    /_matrix/client/v3/directory/room/{roomAlias}
PUT    /_matrix/client/v3/directory/room/{roomAlias}
DELETE /_matrix/client/v3/directory/room/{roomAlias}
GET    /_matrix/client/v3/rooms/{roomId}/aliases
```

### 11.3 房间成员操作

```
POST /_matrix/client/v3/join/{roomIdOrAlias}      # 加入
POST /_matrix/client/v3/rooms/{roomId}/leave      # 离开
POST /_matrix/client/v3/rooms/{roomId}/forget     # 忘记
POST /_matrix/client/v3/rooms/{roomId}/invite     # 邀请
POST /_matrix/client/v3/rooms/{roomId}/kick       # 踢出
POST /_matrix/client/v3/rooms/{roomId}/ban        # 封禁
POST /_matrix/client/v3/rooms/{roomId}/unban      # 解封
POST /_matrix/client/v3/knock/{roomIdOrAlias}     # 敲门
```

### 11.4 成员状态

`m.room.member` 事件的 `membership` 字段:

| 状态 | 说明 |
|------|------|
| `join` | 已加入 |
| `invite` | 被邀请 |
| `leave` | 已离开 |
| `ban` | 被封禁 |
| `knock` | 正在敲门 |

### 11.5 权限等级

```json
{
  "users_default": 0,
  "events_default": 0,
  "state_default": 50,
  "ban": 50,
  "kick": 50,
  "redact": 50,
  "invite": 0,
  "users": {
    "@admin:example.com": 100
  },
  "events": {
    "m.room.name": 50,
    "m.room.power_levels": 100
  },
  "notifications": {
    "room": 50
  }
}
```

### 11.6 加入规则

```json
{
  "join_rule": "invite"  // public, invite, knock, restricted
}
```

### 11.7 历史可见性

```json
{
  "history_visibility": "shared"  // invited, joined, shared, world_readable
}
```

---

## 12. 消息发送

### 12.1 发送消息事件

```
PUT /_matrix/client/v3/rooms/{roomId}/send/{eventType}/{txnId}
```

**文本消息**:
```json
{
  "msgtype": "m.text",
  "body": "Hello, World!"
}
```

**格式化消息**:
```json
{
  "msgtype": "m.text",
  "body": "Hello, **World**!",
  "format": "org.matrix.custom.html",
  "formatted_body": "Hello, <b>World</b>!"
}
```

### 12.2 发送状态事件

```
PUT /_matrix/client/v3/rooms/{roomId}/state/{eventType}/{stateKey}
```

### 12.3 撤回事件

```
PUT /_matrix/client/v3/rooms/{roomId}/redact/{eventId}/{txnId}
```

**请求体**:
```json
{
  "reason": "Spam"
}
```

### 12.4 获取单个事件

```
GET /_matrix/client/v3/rooms/{roomId}/event/{eventId}
```

### 12.5 获取房间状态

```
GET /_matrix/client/v3/rooms/{roomId}/state
GET /_matrix/client/v3/rooms/{roomId}/state/{eventType}/{stateKey}
```

---

## 13. 用户资料

### 13.1 获取/设置资料

```
GET /_matrix/client/v3/profile/{userId}
GET /_matrix/client/v3/profile/{userId}/{keyName}
PUT /_matrix/client/v3/profile/{userId}/{keyName}
```

**标准字段**:
- `displayname` - 显示名称
- `avatar_url` - 头像 URL (mxc://)

### 13.2 搜索用户

```
POST /_matrix/client/v3/user_directory/search
```

**请求体**:
```json
{
  "search_term": "alice",
  "limit": 10
}
```

---

## 14. 模块

Matrix 客户端必须实现所有模块。主要模块包括:

### 14.1 即时消息 (Instant Messaging)

- 文本、图片、文件等消息类型
- 消息格式化 (HTML)
- 富文本回复

### 14.2 输入指示 (Typing Notifications)

```
PUT /_matrix/client/v3/rooms/{roomId}/typing/{userId}
```

```json
{
  "typing": true,
  "timeout": 30000
}
```

### 14.3 已读回执 (Receipts)

```
POST /_matrix/client/v3/rooms/{roomId}/receipt/{receiptType}/{eventId}
```

**回执类型**:
- `m.read` - 已读回执 (公开)
- `m.read.private` - 私有已读回执
- `m.fully_read` - 完全已读标记

### 14.4 在线状态 (Presence)

```
GET /_matrix/client/v3/presence/{userId}/status
PUT /_matrix/client/v3/presence/{userId}/status
```

**状态值**:
- `online` - 在线
- `unavailable` - 离开
- `offline` - 离线

### 14.5 房间标签 (Room Tags)

```
GET    /_matrix/client/v3/user/{userId}/rooms/{roomId}/tags
PUT    /_matrix/client/v3/user/{userId}/rooms/{roomId}/tags/{tag}
DELETE /_matrix/client/v3/user/{userId}/rooms/{roomId}/tags/{tag}
```

**预定义标签**:
- `m.favourite` - 收藏
- `m.lowpriority` - 低优先级

### 14.6 账户数据 (Account Data)

```
GET /_matrix/client/v3/user/{userId}/account_data/{type}
PUT /_matrix/client/v3/user/{userId}/account_data/{type}
GET /_matrix/client/v3/user/{userId}/rooms/{roomId}/account_data/{type}
PUT /_matrix/client/v3/user/{userId}/rooms/{roomId}/account_data/{type}
```

### 14.7 直接消息 (Direct Messaging)

账户数据类型 `m.direct`:
```json
{
  "@alice:example.com": ["!room1:example.com"],
  "@bob:example.com": ["!room2:example.com"]
}
```

### 14.8 忽略用户 (Ignoring Users)

账户数据类型 `m.ignored_user_list`:
```json
{
  "ignored_users": {
    "@spammer:example.com": {}
  }
}
```

### 14.9 贴纸 (Stickers)

事件类型 `m.sticker`:
```json
{
  "body": "Smiley face",
  "info": {
    "mimetype": "image/png",
    "w": 512,
    "h": 512
  },
  "url": "mxc://example.com/sticker123"
}
```

---

## 15. 端到端加密 (E2EE)

### 15.1 概述

Matrix 使用 Olm 和 Megolm 协议实现端到端加密:

- **Olm**: 用于建立一对一安全通道
- **Megolm**: 用于高效的群组消息加密

### 15.2 密钥算法

| 算法 | 用途 |
|------|------|
| `ed25519` | 签名 (设备密钥、交叉签名) |
| `curve25519` | 密钥交换 |
| `signed_curve25519` | 签名的一次性密钥 |

### 15.3 设备密钥

```
POST /_matrix/client/v3/keys/upload
```

**请求体**:
```json
{
  "device_keys": {
    "user_id": "@alice:example.com",
    "device_id": "DEVICE_ID",
    "algorithms": [
      "m.olm.v1.curve25519-aes-sha2-256",
      "m.megolm.v1.aes-sha2"
    ],
    "keys": {
      "curve25519:DEVICE_ID": "...",
      "ed25519:DEVICE_ID": "..."
    },
    "signatures": {
      "@alice:example.com": {
        "ed25519:DEVICE_ID": "..."
      }
    }
  },
  "one_time_keys": {
    "signed_curve25519:AAAAAQ": { ... }
  },
  "fallback_keys": {
    "signed_curve25519:AAAAAB": { ... }
  }
}
```

### 15.4 查询密钥

```
POST /_matrix/client/v3/keys/query
```

**请求体**:
```json
{
  "device_keys": {
    "@bob:example.com": []
  }
}
```

### 15.5 声明一次性密钥

```
POST /_matrix/client/v3/keys/claim
```

**请求体**:
```json
{
  "one_time_keys": {
    "@bob:example.com": {
      "DEVICE_ID": "signed_curve25519"
    }
  }
}
```

### 15.6 密钥变更追踪

```
GET /_matrix/client/v3/keys/changes?from=s123&to=s456
```

### 15.7 房间加密

`m.room.encryption` 状态事件:
```json
{
  "algorithm": "m.megolm.v1.aes-sha2"
}
```

### 15.8 加密消息

`m.room.encrypted` 事件:
```json
{
  "algorithm": "m.megolm.v1.aes-sha2",
  "sender_key": "...",
  "session_id": "...",
  "ciphertext": "..."
}
```

### 15.9 交叉签名

上传交叉签名密钥:
```
POST /_matrix/client/v3/keys/device_signing/upload
```

上传签名:
```
POST /_matrix/client/v3/keys/signatures/upload
```

**交叉签名密钥类型**:
- `master` - 主密钥
- `self_signing` - 自签名密钥 (签名自己的设备)
- `user_signing` - 用户签名密钥 (签名其他用户)

### 15.10 设备验证

**验证事件类型**:
- `m.key.verification.request` - 验证请求
- `m.key.verification.ready` - 准备就绪
- `m.key.verification.start` - 开始验证
- `m.key.verification.accept` - 接受验证
- `m.key.verification.key` - 交换密钥
- `m.key.verification.mac` - MAC 验证
- `m.key.verification.done` - 验证完成
- `m.key.verification.cancel` - 取消验证

**SAS 验证方法** (`m.sas.v1`):
1. 交换承诺值 (commitment)
2. 交换公钥
3. 计算 SAS 值
4. 用户对比 emoji 或数字
5. 交换 MAC 确认

### 15.11 秘密存储与共享

**秘密请求**:
```json
{
  "action": "request",
  "requesting_device_id": "DEVICE_ID",
  "request_id": "request123",
  "name": "m.cross_signing.master"
}
```

**秘密发送**:
```json
{
  "request_id": "request123",
  "secret": "base64_encoded_secret"
}
```

### 15.12 密钥备份

```
GET  /_matrix/client/v3/room_keys/version
POST /_matrix/client/v3/room_keys/version
PUT  /_matrix/client/v3/room_keys/keys
GET  /_matrix/client/v3/room_keys/keys
```

---

## 16. 媒体库

### 16.1 MXC URI

格式: `mxc://<server-name>/<media-id>`

### 16.2 上传媒体

```
POST /_matrix/media/v3/upload
```

**请求头**:
- `Content-Type`: 媒体 MIME 类型
- `Content-Length`: 文件大小

**响应**:
```json
{
  "content_uri": "mxc://example.com/abc123"
}
```

### 16.3 异步上传

1. 创建占位符:
```
POST /_matrix/media/v1/create
```

2. 上传内容:
```
PUT /_matrix/media/v3/upload/{serverName}/{mediaId}
```

### 16.4 下载媒体 (认证)

```
GET /_matrix/client/v1/media/download/{serverName}/{mediaId}
GET /_matrix/client/v1/media/download/{serverName}/{mediaId}/{fileName}
```

### 16.5 缩略图

```
GET /_matrix/client/v1/media/thumbnail/{serverName}/{mediaId}
```

**参数**:
- `width` - 宽度
- `height` - 高度
- `method` - `crop` 或 `scale`

### 16.6 媒体配置

```
GET /_matrix/client/v1/media/config
```

**响应**:
```json
{
  "m.upload.size": 52428800
}
```

---

## 17. 设备管理

### 17.1 列出设备

```
GET /_matrix/client/v3/devices
```

### 17.2 获取设备信息

```
GET /_matrix/client/v3/devices/{deviceId}
```

### 17.3 更新设备

```
PUT /_matrix/client/v3/devices/{deviceId}
```

### 17.4 删除设备

```
DELETE /_matrix/client/v3/devices/{deviceId}
POST /_matrix/client/v3/delete_devices  # 批量删除
```

---

## 18. 推送通知

### 18.1 推送器

```
GET  /_matrix/client/v3/pushers
POST /_matrix/client/v3/pushers/set
```

**推送器配置**:
```json
{
  "pushkey": "unique_push_key",
  "kind": "http",
  "app_id": "com.example.app",
  "app_display_name": "My App",
  "device_display_name": "My Device",
  "lang": "en",
  "data": {
    "url": "https://push.example.com/_matrix/push/v1/notify"
  }
}
```

### 18.2 推送规则

```
GET    /_matrix/client/v3/pushrules/
GET    /_matrix/client/v3/pushrules/global/{kind}/{ruleId}
PUT    /_matrix/client/v3/pushrules/global/{kind}/{ruleId}
DELETE /_matrix/client/v3/pushrules/global/{kind}/{ruleId}
```

**规则类型**:
- `override` - 最高优先级
- `underride` - 最低优先级
- `sender` - 基于发送者
- `room` - 基于房间
- `content` - 基于内容

**默认规则**:
- `.m.rule.master` - 主开关
- `.m.rule.suppress_notices` - 抑制通知消息
- `.m.rule.invite_for_me` - 收到邀请
- `.m.rule.member_event` - 成员事件
- `.m.rule.contains_display_name` - 包含显示名
- `.m.rule.contains_user_name` - 包含用户名
- `.m.rule.roomnotif` - @房间通知
- `.m.rule.tombstone` - 房间升级
- `.m.rule.encrypted_room_one_to_one` - 加密私聊
- `.m.rule.encrypted` - 加密消息
- `.m.rule.message` - 普通消息

### 18.3 通知列表

```
GET /_matrix/client/v3/notifications
```

---

## 19. VoIP 通话

### 19.1 通话事件类型

| 事件类型 | 说明 |
|----------|------|
| `m.call.invite` | 呼叫邀请 |
| `m.call.candidates` | ICE 候选 |
| `m.call.answer` | 接听 |
| `m.call.hangup` | 挂断 |
| `m.call.reject` | 拒绝 |
| `m.call.negotiate` | SDP 协商 |
| `m.call.select_answer` | 选择应答 |

### 19.2 呼叫邀请

```json
{
  "type": "m.call.invite",
  "content": {
    "call_id": "call123",
    "party_id": "party456",
    "version": "1",
    "lifetime": 60000,
    "offer": {
      "type": "offer",
      "sdp": "..."
    }
  }
}
```

### 19.3 TURN 服务器

```
GET /_matrix/client/v3/voip/turnServer
```

**响应**:
```json
{
  "username": "user123",
  "password": "pass456",
  "uris": [
    "turn:turn.example.com:3478?transport=udp"
  ],
  "ttl": 86400
}
```

---

## 20. To-Device 消息

### 20.1 发送设备消息

```
PUT /_matrix/client/v3/sendToDevice/{eventType}/{txnId}
```

**请求体**:
```json
{
  "messages": {
    "@bob:example.com": {
      "DEVICE_ID": {
        "key": "value"
      }
    }
  }
}
```

**常见用途**:
- E2EE 密钥交换
- 设备验证
- 秘密共享

---

## 21. 搜索

```
POST /_matrix/client/v3/search
```

**请求体**:
```json
{
  "search_categories": {
    "room_events": {
      "search_term": "hello",
      "keys": ["content.body"],
      "filter": {
        "rooms": ["!room:example.com"]
      },
      "order_by": "recent",
      "event_context": {
        "before_limit": 2,
        "after_limit": 2
      }
    }
  }
}
```

---

## 22. 第三方网络

用于桥接其他通信网络:

```
GET /_matrix/client/v3/thirdparty/protocols
GET /_matrix/client/v3/thirdparty/protocol/{protocol}
GET /_matrix/client/v3/thirdparty/location
GET /_matrix/client/v3/thirdparty/user
```

---

## 23. 客户端功能配置

### 23.1 功能配置文件

| Profile | 必须支持的功能 |
|---------|----------------|
| Web | 所有模块 |
| Desktop | 所有模块 |
| Mobile | 基本消息、同步、推送 |
| CLI | 基本消息、同步 |
| Embedded | 仅基本功能 |

### 23.2 必须实现

所有符合规范的客户端实现必须支持:

1. ✅ 服务器发现
2. ✅ 登录/登出
3. ✅ 同步
4. ✅ 发送/接收消息
5. ✅ 房间操作
6. ✅ 用户资料
7. ✅ 事件关系

### 23.3 推荐实现

- ⭐ 端到端加密
- ⭐ 推送通知
- ⭐ VoIP 通话
- ⭐ 设备验证
- ⭐ 交叉签名

---

## 附录

### A. 全部 API 端点

<details>
<summary>点击展开完整 API 列表</summary>

**认证**
- `GET /.well-known/matrix/client`
- `GET /_matrix/client/versions`
- `GET /_matrix/client/v3/login`
- `POST /_matrix/client/v3/login`
- `POST /_matrix/client/v3/refresh`
- `POST /_matrix/client/v3/logout`
- `POST /_matrix/client/v3/logout/all`
- `POST /_matrix/client/v3/register`
- `GET /_matrix/client/v3/register/available`
- `GET /_matrix/client/v3/account/whoami`

**账户**
- `POST /_matrix/client/v3/account/password`
- `POST /_matrix/client/v3/account/deactivate`
- `GET /_matrix/client/v3/account/3pid`
- `POST /_matrix/client/v3/account/3pid/add`
- `POST /_matrix/client/v3/account/3pid/bind`
- `POST /_matrix/client/v3/account/3pid/delete`

**同步**
- `GET /_matrix/client/v3/sync`
- `POST /_matrix/client/v3/user/{userId}/filter`
- `GET /_matrix/client/v3/user/{userId}/filter/{filterId}`

**房间**
- `POST /_matrix/client/v3/createRoom`
- `GET /_matrix/client/v3/joined_rooms`
- `GET /_matrix/client/v3/rooms/{roomId}/members`
- `GET /_matrix/client/v3/rooms/{roomId}/joined_members`
- `GET /_matrix/client/v3/rooms/{roomId}/state`
- `GET /_matrix/client/v3/rooms/{roomId}/messages`
- `POST /_matrix/client/v3/rooms/{roomId}/invite`
- `POST /_matrix/client/v3/rooms/{roomId}/join`
- `POST /_matrix/client/v3/rooms/{roomId}/leave`
- `POST /_matrix/client/v3/rooms/{roomId}/kick`
- `POST /_matrix/client/v3/rooms/{roomId}/ban`
- `POST /_matrix/client/v3/rooms/{roomId}/unban`

**消息**
- `PUT /_matrix/client/v3/rooms/{roomId}/send/{eventType}/{txnId}`
- `PUT /_matrix/client/v3/rooms/{roomId}/state/{eventType}/{stateKey}`
- `PUT /_matrix/client/v3/rooms/{roomId}/redact/{eventId}/{txnId}`
- `GET /_matrix/client/v3/rooms/{roomId}/event/{eventId}`

**用户**
- `GET /_matrix/client/v3/profile/{userId}`
- `PUT /_matrix/client/v3/profile/{userId}/{keyName}`
- `POST /_matrix/client/v3/user_directory/search`

**媒体**
- `POST /_matrix/media/v3/upload`
- `GET /_matrix/client/v1/media/download/{serverName}/{mediaId}`
- `GET /_matrix/client/v1/media/thumbnail/{serverName}/{mediaId}`

**加密**
- `POST /_matrix/client/v3/keys/upload`
- `POST /_matrix/client/v3/keys/query`
- `POST /_matrix/client/v3/keys/claim`
- `GET /_matrix/client/v3/keys/changes`
- `POST /_matrix/client/v3/keys/device_signing/upload`
- `POST /_matrix/client/v3/keys/signatures/upload`

**设备**
- `GET /_matrix/client/v3/devices`
- `GET /_matrix/client/v3/devices/{deviceId}`
- `PUT /_matrix/client/v3/devices/{deviceId}`
- `DELETE /_matrix/client/v3/devices/{deviceId}`

**推送**
- `GET /_matrix/client/v3/pushers`
- `POST /_matrix/client/v3/pushers/set`
- `GET /_matrix/client/v3/pushrules/`
- `PUT /_matrix/client/v3/pushrules/global/{kind}/{ruleId}`

**VoIP**
- `GET /_matrix/client/v3/voip/turnServer`

**其他**
- `PUT /_matrix/client/v3/sendToDevice/{eventType}/{txnId}`
- `POST /_matrix/client/v3/search`

</details>

### B. 参考资料

- [Matrix Specification](https://spec.matrix.org/latest/)
- [Matrix API Viewer](https://matrix.org/docs/api/)
- [Olm/Megolm Specification](https://spec.matrix.org/latest/olm-megolm/)
- [Room Versions](https://spec.matrix.org/latest/rooms/)

---

*文档版本: 基于 Matrix Spec v1.17 生成*
*生成时间: 2025-12-21*
