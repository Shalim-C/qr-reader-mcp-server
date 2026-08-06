# QR Reader MCP Server

**只要有图片（本地路径 / base64 / URL），就能读出里面的二维码内容。**

`decode_qrcode_full` 只需图片输入即可工作，任何对接了 MCP 的模型都能直接调用。`enhance_and_decode` 需要模型自行分析图片质量并指定增强区域与策略，因此最适合具备视觉能力的模型使用。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.0-blueviolet)](https://modelcontextprotocol.io/)

---

## 解决什么问题

AI 模型面临一个尴尬的问题：有视觉能力的模型能认出"图里有一个二维码"，但二维码解码走的是像素→二进制数据→文本的算法路径，模型做不到；纯文本模型更不用说，连"看到图里有码"都做不到。

QR Reader MCP Server 把 zbar 二维码解码能力**嵌入** AI 工作流——只要有图片输入，就能读出码里的内容。视觉模型可主动触发，纯文本模型通过用户引导触发。

### 两个工具

| 工具 | 说明 |
|---|---|
| `decode_qrcode_full` | 扫描整张图片，返回所有二维码的内容 |
| `enhance_and_decode` | 对模糊/反光/太小的区域做增强后再解码 |

### 比成功/失败更多的信息

实际场景中二维码质量参差不齐——模糊、反光、太小、对比度不够。MCP 在返回解码结果的同时，也附带了图像质量数据（模糊度、对比度、反光比例）和 `result_code`。Agent 拿到这些信息后，可以自然地告诉用户"这个码有点模糊，换个角度拍"或者"反光挡住了，调整一下光源"，而不需要用户自己猜测问题出在哪。

---

## 快速开始

### 前置依赖

```bash
# Ubuntu / Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows (vcpkg)
vcpkg install zbar
```

### 安装运行

```bash
# 克隆
git clone https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server
```

**两种安装方式 — 按需选择：**

```bash
# ── 轻量版（推荐给只想扫码拿结果的人）─────────────────────
# 依赖 ≈15 MB：Pillow + numpy + pyzbar + mcp + requests
# 功能：decode_qrcode_full + enhance_and_decode 全部保留
#       增强管道 degrades to Pillow（denoise 效果稍弱）
pip install -e ".[light]"

# ── 全功能版（需要最强解码能力的）─────────────────────────
# 依赖 ≈120 MB：额外包含 opencv-python
# 功能：轻量版全部功能 + OpenCV 解码回退 + finder-pattern 检测
pip install -e ".[full]"
```

| | 轻量版 `[light]` | 全功能版 `[full]` |
|---|---|---|
| 下载大小 | ~15 MB | ~120 MB |
| decode_qrcode_full | ✅ | ✅ |
| enhance_and_decode | ✅ | ✅（denoise 稍弱） |
| 质量指标（blur/contrast/glare） | ✅ | ✅ |
| OpenCV 解码回退 | ❌ | ✅ |
| finder-pattern 检测 | ❌ | ✅ |

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
        "ghcr.io/<your-org>/qr-reader-mcp-server"
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
    "quality": {
      "blur_score": 128.5,
      "contrast": 0.72,
      "glare_ratio": 0.05,
      "noise_level": 12.3
    }
  },
  "suggestion": null
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
| `bbox` | [int,int,int,int] | 是 | 目标区域 `[x, y, width, height]` |
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
| `RETRYABLE` | 质量问题，可修复 | 调用 `enhance_and_decode` 重试 |
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

设置 `READ_ONLY_MODE=true` 后，仅保留 `decode_qrcode_full` 工具。此模式下 `enhance_and_decode` 不可用——AI 只能扫描，不能修改图片。

适用于审计/日志场景，确保行为确定、无副作用。

---

## 安全说明

- 本服务只处理你提供的图片，不访问你的文件系统
- `image_url` 仅用于获取你指定的图片，不做其他网络请求
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
│       ├── server.py          # MCP 入口
│       └── core/
│           ├── __init__.py
│           ├── decoder.py     # 二维码解码（基于 pyzbar）
│           ├── quality.py     # 图像质量分析
│           ├── diagnosis.py   # 结果分类与详情提取
│           └── url_utils.py   # SSRF 防护
└── tests/
    ├── __init__.py
    ├── test_decoder.py
    ├── test_diagnosis.py
    ├── test_quality.py
    ├── test_server.py
    └── test_ssrf.py
```

---

## 开源协议

MIT — 详见 [LICENSE](LICENSE)。
