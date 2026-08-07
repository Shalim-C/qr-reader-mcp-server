# QR Reader MCP Server

**一个 MCP 工具，让 AI 真正读懂二维码。视觉模型能"看到"有码但解不了——这个工具补上了这一步。不只返回内容，还告诉 Agent 码清不清楚、值不值得增强重试。**

`decode_qrcode_full` 只需图片输入即可工作，任何对接了 MCP 的模型都能直接调用。`auto_enhance` 在质量不佳时自动尝试增强恢复，无需手动干预。`enhance_and_decode` 适合需要精确控制的场景。

> 🤖 **通过 AI Agent 安装** — 把这条链接发给你的 AI Agent，它会自动完成安装配置：
>
> https://raw.githubusercontent.com/Shalim-C/qr-reader-mcp-server/main/INSTALL_FOR_AGENT.md

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.0-blueviolet)](https://modelcontextprotocol.io/)

---

## 解决什么问题

AI 模型面临一个尴尬的问题：有视觉能力的模型能认出"图里有一个二维码"，但二维码解码走的是像素→二进制数据→文本的算法路径，模型做不到；纯文本模型更不用说，连"看到图里有码"都做不到。

QR Reader MCP Server 把 zbar 二维码解码能力**嵌入** AI 工作流——只要有图片输入，就能读出码里的内容。视觉模型可主动触发，纯文本模型通过用户引导触发。

### 工作流

```
图片 → decode_qrcode_full → SUCCESS? → 直接用
                ↓
           RETRYABLE? → auto_enhance → 自动恢复
                ↓
           需精确控制? → enhance_and_decode
```

三个工具各司其职——`decode_qrcode_full` 先行诊断，`auto_enhance` 一键自动恢复，`enhance_and_decode` 精确手动控制。

### 三个工具

| 工具 | 说明 |
|---|---|
| `auto_enhance` | 一键自动恢复 — 7 种增强策略有序尝试，首次成功即返回。成功后除 JSON 诊断外还返回增强区域的 PNG 截图（ImageContent），供多模态模型直接查看增强效果 |
| `enhance_and_decode` | 手动精控 — 对指定区域执行自定义增强后再解码 |
| `decode_qrcode_full` | 扫描整张图片，返回所有条形码的内容 + 质量诊断。支持 `symbologies` 参数按码制过滤 |

### 比成功/失败更多的信息

实际场景中二维码质量参差不齐——模糊、反光、太小、对比度不够。MCP 在返回解码结果的同时，也附带了图像质量数据（模糊度、对比度[标准差+ISO15415调制比]、反光比例[空间方差]）和 `result_code`。Agent 拿到这些信息后，可以自然地告诉用户"这个码有点模糊，换个角度拍"或者"反光挡住了，调整一下光源"，也可以直接调用 `auto_enhance` 自动修复。

---

## 快速开始

### 前置依赖

```bash
# Ubuntu / Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows (choco — CI verified)
choco install zbar
```

### 安装运行

```bash
# 推荐：uvx 一行安装（Python 3.10+, 自动处理依赖）
uvx qr-reader-mcp-server

# 或：git clone + pip 安装
pip install .            # 基础版（~15 MB）
pip install ".[full]"   # 全功能版（~120 MB）
```

**两种安装方式 — 按需选择：**

```bash
# ── 基础版（推荐，~15 MB）───────────────────────────────
# pyzbar 解码 + 全部 3 个工具 + 质量诊断
pip install .

# ── 全功能版（需要最强能力）─────────────────────────────
# 基础版全部功能 + OpenCV 解码回退 + finder-pattern 畸变检测
pip install ".[full]"
```

| | 基础版 | 全功能版 `[full]` |
|---|---|---|
| 下载大小 | ~15 MB | ~120 MB |
| decode_qrcode_full | ✅ | ✅ |
| auto_enhance | ✅ | ✅ |
| enhance_and_decode | ✅ | ✅ |
| 质量指标（blur/contrast/glare/noise/modulation） | ✅ | ✅ |
| distortion (finder-pattern 几何畸变) | ❌ | ✅ |
| OpenCV 解码回退 | ❌ | ✅ |

```bash
# 启动（stdio 模式）
python -m qr_reader.server
```

### MCP 客户端配置

**Claude Desktop / VS Code Copilot / Cursor：**

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"],
      "env": {
        "LOG_LEVEL": "info",
        "READ_ONLY_MODE": "false"
      }
    }
  }
}
```

**Docker：**

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "ghcr.io/Shalim-C/qr-reader-mcp-server"
      ]
    }
  }
}
```

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_LEVEL` | `info` | 日志级别：`debug`、`info`、`warning`、`error` |
| `READ_ONLY_MODE` | `false` | 设为 `true` 禁用 `enhance_and_decode`（仅保留 `decode_qrcode_full`） |
| `MAX_IMAGE_SIZE` | `10485760` | 图片大小上限（字节，默认 10 MB） |
| `MAX_INPUT_PIXELS` | `2560` | 图片长边超过此值自动缩放 |
| `QR_BLUR_THRESHOLD` | `50.0` | 模糊度阈值，越低越严格 |
| `QR_CONTRAST_THRESHOLD` | `0.20` | 对比度阈值（std/128），越低越严格 |
| `QR_GLARE_THRESHOLD` | `0.10` | 反光检测阈值（空间方差），越低越敏感 |

---

## 工具说明

### `decode_qrcode_full`

对整张图片进行二维码识别和解码，返回结构化结果和质量指标。

**输入参数：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_path` | string | 三选一 | 本地图片绝对路径（推荐——无管道开销） |
| `image_base64` | string | 三选一 | Base64 编码的图片 |
| `image_url` | string | 三选一 | 图片 URL |

**返回示例：**

```json
{
  "success": true,
  "result_code": "SUCCESS",
  "results": [
    {
      "content": "https://example.com",
      "bbox": [50, 60, 200, 200],
      "type": "QRCODE",
      "raw_bytes": "..."
    }
  ],
  "analysis": {
    "total_detected": 1,
    "modulation": 0.92,
    "quality": {
      "blur_score": 128.5,
      "contrast": 0.72,
      "glare_ratio": 0.05,
      "noise_level": 12.3
    }
  },
  "suggestion": null,
  "image_size": [600, 800],
  "resize_factor": 1.0
}
```

### `auto_enhance`

质量不佳时的一键自动恢复。7 种增强策略有序尝试（upscale / sharpen / contrast / denoise / 组合策略），首次解码成功即返回，无需手动指定 bbox 或 operation。

**输入参数：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_path` | string | 三选一 | 本地图片绝对路径 |
| `image_base64` | string | 三选一 | Base64 编码的图片 |
| `image_url` | string | 三选一 | 图片 URL |
| `bbox` | [int,int,int,int] | 否 | 可选目标区域，不传则处理全图 |

**返回示例（成功）：**

```json
{
  "success": true,
  "applied_strategy": "upscale_2x",
  "strategies_tried": 1,
  "result_code": "SUCCESS",
  "results": [{"content": "https://example.com", "type": "QRCODE"}],
  "image_size": [96, 96],
  "resize_factor": 1.0
}
```

**返回示例（全部失败）：**

```json
{
  "success": false,
  "applied_strategy": null,
  "strategies_tried": 7,
  "result_code": "NO_QR_FOUND",
  "suggestion": "All 7 enhancement strategies failed to decode a QR code..."
}
```

### `enhance_and_decode`

裁剪指定区域，执行增强操作后再解码。

**输入参数：**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image_path` | string | 三选一 | 本地图片绝对路径（推荐——无管道开销） |
| `image_base64` | string | 三选一 | Base64 编码的图片 |
| `image_url` | string | 三选一 | 图片 URL |
| `bbox` | [int,int,int,int] 或 [[int,int,int,int], ...] | 是 | 目标区域。单区域传 `[x, y, width, height]`，多区域传 `[[x1,y1,w1,h1], ...]` |
| `operations` | object[] | 否 | 增强操作列表（见下方），不传则仅裁剪解码 |

**增强操作：**

| 操作 | 说明 | 关键参数 |
|---|---|---|
| `upscale` | 放大区域 | `scale`（默认 2.0） |
| `sharpen` | 锐化边缘 | `strength`（默认 1.5） |
| `adjust_contrast` | 调整对比度 | `alpha`（默认 1.5），`beta`（默认 0） |
| `denoise` | 降噪 | `h`（默认 10） |

---

## 结果码说明

`result_code` 告诉 AI 助手下一步该做什么：

| 结果码 | 含义 | AI 应该做什么 |
|---|---|---|
| `SUCCESS` | 解码成功 | 直接使用内容 |
| `SUCCESS_WITH_WARNING` | 解码成功但内容可能有异常 | 检查警告，验证内容 |
| `RETRYABLE` | 质量问题，可修复 | 调用 `auto_enhance`（推荐）或 `enhance_and_decode` |
| `NO_QR_FOUND` | 未检测到二维码 | 告知用户图中没有二维码 |
| `QR_UNRECOVERABLE` | 二维码已损坏无法恢复 | 告知用户二维码损坏 |

---

## 示例对话

接入后试试对 AI 助手说：

- "帮我读一下这张截图里的二维码"
- "这个二维码太模糊了，试试增强后再读"
- "扫描这张照片里的所有二维码，列出内容"
- "这个收据上的码很难扫——能修复一下吗？"

---

## 只读模式

设置 `READ_ONLY_MODE=true` 后，仅保留 `decode_qrcode_full`。`auto_enhance` 和 `enhance_and_decode` 均不可用——AI 只能扫描，不能修改图片。

适用于审计/日志场景，确保行为确定、无副作用。

---

## 安全说明

- 通过 `image_path` 读取调用方指定的本地图片（仅扩展名白名单过滤）
- `image_url` 通过四层 SSRF 防御（DNS 解析后 IP 校验 + hostname 黑名单 + 禁用重定向 + scheme 白名单）保护内网安全
- stdio 模式下无需 API Key 或认证
- 设置 `MAX_IMAGE_SIZE` 可限制内存占用
- 日志不记录图片内容和解码数据

---

## 项目结构

```
qr-reader-mcp-server/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
├── docs/
│   ├── setup.md
│   ├── tools.md
│   ├── troubleshooting.md
│   └── prompts.md
├── src/
│   └── qr_reader/
│       ├── __init__.py
│       ├── server.py          # MCP 入口 + 三工具注册
│       └── core/
│           ├── __init__.py
│           ├── decoder.py     # 二维码解码（pyzbar + OpenCV fallback）
│           ├── ops.py         # 统一图像操作层（cv2 / Pillow 双后端）
|           ├── quality.py     # 图像质量分析 + ISO 15415 modulation
│           ├── diagnosis.py   # 五级结果码分类
│           ├── distortion.py  # finder-pattern 几何畸变检测
│           └── url_utils.py   # 四层 SSRF 防护
├── tests/
│   ├── test_decoder.py
│   ├── test_diagnosis.py
│   ├── test_e2e.py
│   ├── test_quality.py
│   ├── test_server.py
│   └── test_ssrf.py
├── benchmarks/                 # pytest-benchmark 性能回归
├── INSTALL_FOR_AGENT.md        # AI Agent 自动安装指南
├── CHANGELOG.md
└── SECURITY.md
```

---

## 开源协议

MIT — 详见 [LICENSE](LICENSE)。
