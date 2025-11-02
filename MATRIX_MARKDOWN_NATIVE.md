# Matrix Markdown 原生支持说明

## 重要更正

**Matrix 协议本身就支持 Markdown 格式！**

### 正确理解

根据 Matrix Client-Server API 规范（v1.11），Matrix 客户端（如 Element）**原生支持在 `body` 字段中渲染 Markdown 语法**。

服务器端不需要做任何 Markdown 到 HTML 的转换工作。只需要直接发送包含 Markdown 语法的纯文本即可，客户端会自动渲染。

### 支持的 Markdown 语法

Matrix 客户端通常支持：

- **粗体**: `**text**` 或 `__text__`
- *斜体*: `*text*` 或 `_text_`
- `代码`: `` `code` ``
- 代码块：
  ````markdown
  ```language
  code block
  ```
  ````
- 链接：`[text](url)`
- 标题：`# Header`
- 列表：`- item` 或 `* item`
- 引用：`> quote`
- 删除线：`~~text~~`

### 实现方式

#### 简单消息发送

```python
content = {
    "msgtype": "m.text",
    "body": "这是 **粗体** 和 *斜体* 的文本"  # 客户端会自动渲染
}
```

#### 可选的 HTML 格式化（高级）

如果需要更复杂的格式化或确保跨客户端兼容性，可以同时提供 HTML 版本：

```python
content = {
    "msgtype": "m.text",
    "body": "这是 **粗体** 和 *斜体* 的文本",  # Markdown fallback
    "format": "org.matrix.custom.html",
    "formatted_body": "这是 <strong>粗体</strong> 和 <em>斜体</em> 的文本"  # HTML 版本
}
```

但这是**可选的**，不是必需的！大多数现代 Matrix 客户端都能正确渲染 Markdown。

### 错误的实现

~~之前我们错误地实现了自定义的 Markdown 到 HTML 转换器（`markdown.py`）。~~

这是不必要的，因为：
1. Matrix 客户端已经内置 Markdown 渲染支持
2. 手动转换会增加复杂度和维护成本
3. 可能与不同客户端的渲染方式不一致

### 当前正确实现

现在 `matrix_event.py` 使用正确的方式：

```python
# 直接发送 Markdown 文本，客户端会处理渲染
content = {
    "msgtype": "m.text",
    "body": text  # 包含 Markdown 语法的纯文本
}
```

### 参考资料

- [Matrix Client-Server API - m.room.message](https://spec.matrix.org/v1.11/client-server-api/#mroommessage)
- [Matrix Instant Messaging Module](https://spec.matrix.org/v1.11/client-server-api/#instant-messaging)

### 总结

✅ Matrix 原生支持 Markdown  
✅ 只需发送包含 Markdown 的 `body` 字段  
✅ 客户端自动渲染，无需服务器端转换  
❌ 不要自己实现 Markdown 到 HTML 的转换器  
