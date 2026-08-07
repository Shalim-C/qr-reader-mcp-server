# QR Reader MCP Server — Install Guide

The following steps are written for AI agents. Send this link to your agent and it will handle installation automatically.

> ⚠️ **Before running**: An AI agent should **always show you the commands and wait for your review** before executing them. Never let an agent run installation commands without your explicit approval.

## Prerequisites

Ensure the environment has:
- Python 3.10+
- libzbar (system-level dependency required by pyzbar)

## Step 1 — Install libzbar

```shell
# Ubuntu / Debian
sudo apt install libzbar0

# macOS
brew install zbar

# Windows (choco)
choco install zbar
```

## Step 2 — Clone and install

```shell
git clone --depth 1 https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server

# Base install (~15 MB) — full QR decoding
pip install -e .

# Full (~120 MB) — adds OpenCV decode fallback and better diagnosis
pip install -e ".[full]"
```

## Step 3 — Register with your MCP client

Pick the config that matches your client:

**Reasonix Go (config.toml):**

```toml
[[plugins]]
name    = "qr-reader"
command = "python"
args    = ["-m", "qr_reader.server"]
env     = { LOG_LEVEL = "info" }
```

**Claude Desktop / VS Code / Cursor:**

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

**uvx:**

```shell
uvx qr-reader-mcp-server
```

## Step 4 — Restart and verify

Restart your MCP client, then have the agent verify with:

```shell
python -c "from qr_reader import __version__; print(__version__)"
```

Or ask the agent to call `decode_qrcode_full` on a QR code image directly in conversation.
