# INSTALL_FOR_AGENT.md — Copy This to Your Agent

> 👤 **You (the human):** copy this entire document into your AI agent's chat.
> 🤖 **Your agent:** follow the steps below to install the QR Reader MCP Server.

---

## Your Task

Install `qr-reader-mcp-server` — an MCP tool that gives you the ability to decode QR codes from images.

Two tools:
- **decode_qrcode_full** — scan a full image, return all QR codes + quality diagnostics
- **enhance_and_decode** — crop a region, apply enhancements (upscale/sharpen/contrast/denoise), then decode

---

## Step 1 — Install the MCP

First, check whether `libzbar` is available on the system:

```
# Linux
dpkg -l | grep libzbar || sudo apt install -y libzbar0

# macOS
brew list zbar || brew install zbar

# Windows
# libzbar.dll should be in PATH; if not, install via vcpkg:
vcpkg install zbar
```

Then:

```
cd /d/GitHub
git clone --depth 1 https://githubproxy.cc/https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server

# Choose one:
# Light (~15 MB):      pip install -e ".[light]"
# Full (~120 MB):      pip install -e ".[full]"
pip install -e ".[full]"
```

**Recommendation:** use `[full]` — the extra ~100MB gives you an OpenCV fallback decoder and finder-pattern detection, making `RETRYABLE → enhance_and_decode` more reliable.

---

## Step 2 — Register in Your MCP Client

Add the following to your MCP client config. If using **Reasonix Go**, add to `[[plugins]]` in `config.toml`:

```toml
[[plugins]]
name    = "qr-reader"
command = "python"
args    = ["-m", "qr_reader.server"]
env     = { LOG_LEVEL = "info", READ_ONLY_MODE = "false" }
```

If your client uses `.mcp.json` / Claude-style config:

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

**After registering, restart your MCP client** to pick up the new server.

---

## Step 3 — Verify

Once restarted, call `decode_qrcode_full` on a test QR image to confirm it works. The MCP server starts and prints its version and cv2 availability in the logs — check for something like:

```
Starting QR Reader MCP Server v0.1.0 (read_only=False, cv2=True)
```

---

## Optional Configuration

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |
| `READ_ONLY_MODE` | `false` | Set `true` to disable `enhance_and_decode` |
| `MAX_IMAGE_SIZE` | `10485760` | Max image bytes (default 10 MB) |
| `MAX_INPUT_PIXELS` | `2560` | Auto-resize long edge if exceeded |
| `QR_BLUR_THRESHOLD` | `50.0` | Lower = stricter "too blur" check |
| `QR_CONTRAST_THRESHOLD` | `0.15` | Lower = stricter "too dark" check |
| `QR_GLARE_THRESHOLD` | `0.3` | Lower = stricter glare detection |

---

You're all set. Your agent can now scan QR codes from any image you give it.
