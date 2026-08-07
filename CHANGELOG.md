# Changelog

All notable changes to QR Reader MCP Server will be documented in this file.

## [Unreleased]

### Added
- **Distortion detection** (`core/distortion.py`) — analyzes QR finder-pattern geometry (right-angle deviation, leg ratio, diagonal ratio) to detect perspective/physical distortion. Integrated into `decode_qrcode_full`; light mode returns `None` (no cv2 required).
- **URL download tests** (E-06) — 3 tests covering redirect handling, streaming size limit, and request timeout.
- **ruff lint** (D-01) — full lint pass with E/F/I/S/BLE/RUF rules; 35 issues resolved (zero warnings). Added to dev deps + `pyproject.toml` config.
- **macOS CI** (D-04) — `macos-latest` added to test matrix with `brew install zbar`.

### Changed
- **Diagnosis engine refactored** — tree-based `if/elif` replaced with RMS-weighted multi-metric fusion. Six metrics (blur, contrast, glare, noise, modulation, distortion) normalized to [0,1] and aggregated; `primary_issue` auto-inferred from top-contributing metric.
- **Color space unified** — `load_image_bytes` always returns RGB (cv2 path now converts BGR→RGB). Removed unreliable BGR heuristic from `image_to_bytes`.
- **contrast** Pillow fallback now uses the same linear transform as cv2 (`np.clip(alpha*arr+beta)`) instead of `ImageEnhance.Contrast` (mean-interpolation), ensuring consistent behavior across install modes.

### Documentation
- `SECURITY.md` ...
- `INSTALL_FOR_AGENT.md` ...
- `docs/tools.md` ...
- `docs/setup.md` ...
- `docs/troubleshooting.md` ...
- `CHANGELOG.md` ...
- `README.md` ...

### Changed (Phase 1)
- `pyzbar` moved from optional `[light]`/`[full]` extras to base dependencies ...
- Enhance parameter defaults changed ...

## [0.1.0] — unreleased

### Initial release

- **Three tools:** `decode_qrcode_full` (full-image decode with diagnostics) and `enhance_and_decode` (region-based enhancement pipeline).
- **Five-tier result code system** — SUCCESS / SUCCESS_WITH_WARNING / RETRYABLE / NO_QR_FOUND / QR_UNRECOVERABLE — enabling AI agents to self-correct on failure.
- **Image quality diagnostics** — blur score, contrast, glare ratio, noise level included in every response.
- **Enhancement pipeline** — upscale, sharpen, contrast adjustment, denoising, composable in any order.
- **`image_path` input** — pass local file paths instead of base64, avoiding stdio pipe timeouts on large images.
- **Auto-resize** — images exceeding `MAX_INPUT_PIXELS` (default 2560px) are downscaled transparently.
- **Multi-client configs** — Claude Desktop, VS Code/Cursor, Continue.dev, Reasonix, Codex/Zed.
- **VS Code one-click install badge**.
- **MCP Inspector integration** for local debugging.
- **Docker support** with `Dockerfile` and `docker-compose.yml`.
- **CI** — tests on Python 3.10 / 3.11 / 3.12 + Docker build.
- **Security** — `READ_ONLY_MODE` support, structured error codes, SECURITY.md.

[0.1.0]: https://github.com/Shalim-C/qr-reader-mcp-server/releases/tag/v0.1.0
