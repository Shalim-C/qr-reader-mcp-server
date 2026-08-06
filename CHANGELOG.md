# Changelog

All notable changes to QR Reader MCP Server will be documented in this file.

## [0.1.0] — 2026-08-06

### Initial release

- **Two tools:** `decode_qrcode_full` (full-image decode with diagnostics) and `enhance_and_decode` (region-based enhancement pipeline).
- **Five-tier result code system** — SUCCESS / SUCCESS_WITH_WARNING / RETRYABLE / NO_QR_FOUND / QR_UNRECOVERABLE — enabling AI agents to self-correct on failure.
- **Image quality diagnostics** — blur score, contrast, glare ratio, noise level included in every response.
- **Enhancement pipeline** — upscale, sharpen, contrast adjustment, denoising, composable in any order.
- **`image_path` input** — pass local file paths instead of base64, avoiding stdio pipe timeouts on large images.
- **Auto-resize** — images exceeding `MAX_INPUT_PIXELS` (default 1920px) are downscaled transparently.
- **Multi-client configs** — Claude Desktop, VS Code/Cursor, Continue.dev, Reasonix, Codex/Zed.
- **VS Code one-click install badge**.
- **MCP Inspector integration** for local debugging.
- **Docker support** with `Dockerfile` and `docker-compose.yml`.
- **CI** — tests on Python 3.10 / 3.11 / 3.12 + Docker build.
- **Security** — `READ_ONLY_MODE` support, structured error codes, SECURITY.md.

[0.1.0]: https://github.com/Shalim-C/qr-reader-mcp-server/releases/tag/v0.1.0
