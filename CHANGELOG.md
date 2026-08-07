# Changelog

All notable changes to QR Reader MCP Server will be documented in this file.

## [0.1.0] - 2026-08-07

### Added
- **Three tools:** `decode_qrcode_full` (full-image decode with diagnostics), `auto_enhance` (automatic multi-strategy recovery), and `enhance_and_decode` (region-based enhancement pipeline).
- **Five-tier result code system** — SUCCESS / SUCCESS_WITH_WARNING / RETRYABLE / NO_QR_FOUND / QR_UNRECOVERABLE — enabling AI agents to self-correct on failure.
- **Image quality diagnostics** — blur score, contrast, glare ratio, noise level included in every response.
- **Weighted multi-metric fusion** — RMS aggregation of six metrics (blur, contrast, glare, noise, modulation, distortion) with auto-inferred `primary_issue`.
- **Distortion detection** (`core/distortion.py`) — analyzes QR finder-pattern geometry (right-angle deviation, leg ratio, diagonal ratio) to detect perspective/physical distortion. Requires `[full]` extras (cv2); light mode returns `None`.
- **Enhancement pipeline** — upscale, sharpen, contrast adjustment, denoising, composable in any order.
- **Dual-mode install** — light (~15 MB, Pillow-based) and full (~120 MB, OpenCV) via `pip install ".[full]"`.
- **`image_path` input** — pass local file paths instead of base64, avoiding stdio pipe timeouts on large images.
- **Auto-resize** — images exceeding `MAX_INPUT_PIXELS` (default 2560px) are downscaled transparently.
- **Security** — `READ_ONLY_MODE` support; four-layer SSRF defense; structured error codes; `SECURITY.md`.
- **Docker support** with `Dockerfile` and `docker-compose.yml`.
- **CI** — test matrix (3 OS × 3 Python), light-mode tests, Docker build, mypy type checking, benchmark regression.
- **ruff lint** — E/F/I/S/BLE/RUF rules with zero warnings.
- **Comprehensive tests** — unit, integration, E2E (real QR generation + degradation), SSRF validation.

### Changed
- **Color space unified** — `load_image_bytes` always returns RGB (cv2 path converts BGR→RGB).
- Pillow `contrast` fallback uses the same linear transform as cv2 (`np.clip(alpha*arr+beta)`) for consistent cross-backend behavior.
- `pyzbar` is now a base dependency (was optional extra).

[0.1.0]: https://github.com/Shalim-C/qr-reader-mcp-server/releases/tag/v0.1.0
