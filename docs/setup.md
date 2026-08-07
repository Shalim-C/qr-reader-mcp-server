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
pip install -e .
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
| `READ_ONLY_MODE` | `false` | 设为 `true` 禁用 `enhance_and_decode` |
| `MAX_IMAGE_SIZE` | `10485760` | 图片大小上限（字节） |

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
