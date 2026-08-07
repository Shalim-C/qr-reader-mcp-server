# 安装指南

## 系统要求

- **Python** 3.10 或更高版本
- **ZBar** 系统库（pyzbar 依赖）

### 安装 ZBar

```bash
# Ubuntu / Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows（通过 choco）
choco install zbar
```

## 安装方式

### 方式一：pip（推荐）

```bash
git clone https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server
pip install -e ".[full]"   # 推荐：包含 OpenCV + 全部增强
# 或
# pip install -e ".[light]"  # 轻量版：仅 pyzbar，auto_enhance 仍可用
```

### 方式二：从 PyPI 安装（后续）

```bash
pip install qr-reader-mcp-server
```

## MCP 客户端配置

### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"]
    }
  }
}
```

### VS Code / Copilot Chat

在项目根目录添加 `.vscode/mcp.json`：

```json
{
  "servers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"]
    }
  }
}
```

### Cursor

同 VS Code——在项目根目录添加 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"]
    }
  }
}
```

### Docker

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

## 环境变量

通过 MCP 客户端的 `env` 配置段设置以下变量（服务不读取 `.env` 文件）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_LEVEL` | `info` | `debug`、`info`、`warning`、`error` |
| `READ_ONLY_MODE` | `false` | 设为 `true` 禁用 `auto_enhance` 和 `enhance_and_decode` |
| `MAX_IMAGE_SIZE` | `10485760` | 图片大小上限（字节，默认 10 MB） |
| `MAX_INPUT_PIXELS` | `4096` | 图片长边超过此值自动缩放 |
| `QR_BLUR_THRESHOLD` | `50.0` | Laplacian 方差归一化阈值（模糊贡献 = 阈值 ÷ 实际方差） |
| `QR_CONTRAST_PERFECT` | `0.50` | 对比度归一化锚点（实际对比度越接近此值越健康） |
| `QR_MODULATION_PERFECT` | `0.70` | ISO 15415 调制比归一化锚点 |
| `QR_GLARE_MAX` | `0.30` | 反光归一化上界（超过视为严重反光） |
| `QR_NOISE_MAX` | `50.0` | 噪声归一化上界 |
| `QR_ANGLE_MAX` | `30.0` | 畸变角度归一化上界（度） |
| `QR_LEG_RATIO_MIN` | `0.60` | 畸变腿比归一化下界 |

## 验证安装

接入 MCP 客户端后，试试：

> "帮我读一下这张图片里的二维码"（上传一张含二维码的图片）

或者手动测试：

```bash
python -c "
from qr_reader.core.quality import analyze_image_quality
import numpy as np
print(analyze_image_quality(np.zeros((100, 100, 3), dtype='uint8')))
"
```
