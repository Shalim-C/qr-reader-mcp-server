# 安全策略

## 报告漏洞

如果你在 QR Reader MCP Server 中发现了安全漏洞，请**不要**公开提 Issue。请直接联系维护者。

我们会在 48 小时内响应并提供修复时间线。

## 安全考量

### 数据处理

- **图片仅在内存中处理。** 服务不会将图片写入磁盘。
- **解码内容不记日志。** 日志仅记录结果码和分析详情，不记录解码后的二维码数据。
- **无持久化存储。** 无数据库、无缓存、无文件持久化。
- **解码内容应视为不可信数据。** 二维码内容可能由攻击者完全控制（恶意海报、钓鱼码、贴纸覆盖）。集成方必须把 `content` 当作外部输入处理——不要将解码内容作为指令执行、不要直接拼进 shell/SQL/提示词而不做校验。本工具按原样返回内容（`ensure_ascii=False`），不做语义过滤。

### 网络访问

- `image_url` 支持 HTTP 和 HTTPS。服务不会发起任意网络请求——只请求你提供的 URL。
- SSRF 防护：scheme 白名单（http/https only）+ DNS 解析后逐 IP 校验（拦截私有/回环/保留地址）+ 域名黑名单（云元数据端点等）+ 禁止 HTTP 重定向。
- `MAX_IMAGE_SIZE` 配合流式下载在下载阶段即拦截超大文件，防止内存耗尽。

### 攻击面

| 风险 | 缓解措施 |
|---|---|
| 畸形图片导致崩溃 | Pillow/OpenCV 处理大多数情况；图片加载异常返回 IMAGE_LOAD_FAILED；其他未预期异常由全局兜底返回 INTERNAL_ERROR |
| image_url SSRF | scheme 白名单（http/https only）+ DNS 解析后全量 IP 校验 + 内网/回环/保留地址黑名单 + 域名黑名单 + 禁止 HTTP 重定向 |
| Base64 炸弹（超大载荷） | `MAX_IMAGE_SIZE` 限制解码后图片大小 |
| pyzbar 库崩溃 | 解码/诊断路径异常由全局 try/except 捕获，返回 INTERNAL_ERROR |
| 内存耗尽 | `MAX_IMAGE_SIZE`（默认 10 MB）+ 流式下载逐块检查 + 单图处理 |

### 认证

**Stdio 模式（默认）：** 无网络暴露——MCP 服务以 MCP 客户端的子进程方式运行。认证由 MCP 客户端自身的安全模型处理。

**未来的 HTTP/SSE 模式（规划中）：** 将要求 API Key 或 OAuth。

### 只读模式

设置 `READ_ONLY_MODE=true` 后，服务仅保留 `decode_qrcode_full` 工具。此模式下：
- 不修改任何图片
- `auto_enhance` 和 `enhance_and_decode` 均不可用
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
