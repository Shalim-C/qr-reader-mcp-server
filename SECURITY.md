# 安全策略

## 报告漏洞

如果你在 QR Reader MCP Server 中发现了安全漏洞，请**不要**公开提 Issue。请直接联系维护者。

我们会在 48 小时内响应并提供修复时间线。

## 安全考量

### 数据处理

- **图片仅在内存中处理。** 服务不会将图片写入磁盘。
- **解码内容不记日志。** 日志仅记录结果码和分析详情，不记录解码后的二维码数据。
- **无持久化存储。** 无数据库、无缓存、无文件持久化。

### 网络访问

- `image_url` 仅通过 HTTPS 获取。服务不会发起任意网络请求——只请求你提供的 URL。
- 设置 `MAX_IMAGE_SIZE` 可防止大文件下载导致内存耗尽。

### 攻击面

| 风险 | 缓解措施 |
|---|---|
| 畸形图片导致崩溃 | OpenCV/Pillow 处理大多数情况；异常被捕获并返回结构化错误 |
| image_url SSRF | URL 仅加载到内存，不访问文件系统 |
| Base64 炸弹（超大载荷） | `MAX_IMAGE_SIZE` 限制解码后图片大小 |
| pyzbar 库崩溃 | 由服务错误处理器捕获，返回结构化错误 |
| 内存耗尽 | `MAX_IMAGE_SIZE`（默认 10 MB）+ 单图处理 |

### 认证

**Stdio 模式（默认）：** 无网络暴露——MCP 服务以 MCP 客户端的子进程方式运行。认证由 MCP 客户端自身的安全模型处理。

**未来的 HTTP/SSE 模式（规划中）：** 将要求 API Key 或 OAuth。

### 只读模式

设置 `READ_ONLY_MODE=true` 后，服务仅保留 `decode_qrcode_full` 工具。此模式下：
- 不修改任何图片
- `enhance_and_decode` 不可用
- AI 只能读取，不能变换

### 依赖安全

主要依赖及其角色：

| 依赖 | 用途 | 安全说明 |
|---|---|---|
| `mcp` | MCP 协议 | 官方 Python SDK |
| `opencv-python` | 图像处理 | 广泛审查，无网络 |
| `pyzbar` | 二维码解码 | 封装系统 `libzbar` |
| `Pillow` | 图片加载 | 标准库 |
| `numpy` | 数组运算 | 标准库 |
| `requests` | URL 获取 | 仅用于 `image_url` |

### 建议做法

1. 如果只需要扫描，设置 `READ_ONLY_MODE=true`
2. 将 `MAX_IMAGE_SIZE` 设为你预期的最大图片尺寸
3. 如果部署为远程服务，请在防火墙后运行
4. 保持依赖更新：`pip install --upgrade -r requirements.txt`
5. 通过 `LOG_LEVEL=debug` 监控异常模式
