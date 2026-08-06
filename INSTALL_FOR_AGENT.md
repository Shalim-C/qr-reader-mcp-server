# QR Reader MCP Server — 安装指南

以下步骤面向 AI Agent，复制全文给你的 Agent 即可自动完成安装。

## 环境要求

开始安装之前，请确保环境中已安装：
- Python 3.10+
- libzbar（系统级依赖，pyzbar 需要）

## 第 1 步 — 安装 libzbar

```shell
# Ubuntu / Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows (choco)
choco install zbar
```

## 第 2 步 — 克隆仓库并安装

```shell
cd /d/GitHub
git clone --depth 1 https://githubproxy.cc/https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server

# 轻量版（~15 MB），功能完整
pip install -e ".[light]"

# 全功能版（~120 MB），额外 OpenCV 解码回退
pip install -e ".[full]"
```

## 第 3 步 — 注册到 MCP 客户端

根据你的客户端选择对应的配置：

**Reasonix Go（config.toml）：**

```toml
[[plugins]]
name    = "qr-reader"
command = "python"
args    = ["-m", "qr_reader.server"]
env     = { LOG_LEVEL = "info" }
```

**Claude Desktop / VS Code / Cursor：**

```json
{
  "mcpServers": {
    "qr-reader": {
      "command": "python",
      "args": ["-m", "qr_reader.server"],
      "env": {
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

**uvx（如果已发布到 PyPI）：**

```shell
uvx qr-reader-mcp-server
```

## 第 4 步 — 重启并验证

重启你的 MCP 客户端，然后让 Agent 用以下命令验证：

```shell
python -c "from qr_reader.server import __version__; print(__version__)"
```

或直接在对话中让 Agent 调用 `decode_qrcode_full` 读取一张二维码图片。
