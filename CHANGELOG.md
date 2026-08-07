# Changelog

All notable changes to QR Reader MCP Server will be documented in this file.

## [0.2.0] - 2026-08-08

### Added
- **Barcode symbology filter** — `decode_qrcode_full` / `enhance_and_decode` accept an optional `symbologies` whitelist (e.g. `["EAN13"]` for receipts, `["QRCODE"]` for URLs). Empty/omitted = all types.
- **Enhanced-image return** — `auto_enhance` now returns the enhanced region as an `ImageContent` (PNG) alongside JSON diagnostics, so multimodal agents can visually verify the enhancement result.
- **Quality-anchor env vars documented** — the six normalization anchors (`QR_CONTRAST_PERFECT`, `QR_MODULATION_PERFECT`, `QR_GLARE_MAX`, `QR_NOISE_MAX`, `QR_ANGLE_MAX`, `QR_LEG_RATIO_MIN`) are now real, documented configuration.
- **E2E edge cases** — malformed-image and blank-image test coverage.

### Fixed
- **Blank / no-QR images no longer misclassified as RETRYABLE** — when OpenCV explicitly detects no QR-like regions (`qr_detected=False`), the result is `NO_QR_FOUND` regardless of image quality; quality issues are still surfaced in `suggestion` so an agent can choose to call `auto_enhance` manually. (Reverted an over-correction that sent agents on pointless enhancement attempts for images with no code.)
- **OpenCV decode path** — BGR/RGB handling and fallback decode fixes.
- **Dead configuration removed** — `QR_CONTRAST_THRESHOLD` / `QR_GLARE_THRESHOLD` were read but never used by the production path; removed from code and documentation.
- **Docs drift** — README / setup docs / `.env.example` now list only variables that actually take effect.

### Changed
- `MAX_INPUT_PIXELS` default raised `2560` → `4096` (larger images allowed before auto-resize).
- Type-checking hardened: mypy errors 20 → 0.

### CI
- **PyPI publishing via OIDC trusted publishing** (no long-lived tokens).
- **Docker smoke test** — builds the image and performs a real MCP `initialize` handshake.
- **Version-consistency check** — `pyproject.toml` and `src/qr_reader/__init__.py` must agree.
- **Light-mode (cv2-free) CI runs the full test suite**; cv2-dependent tests skip gracefully via `importorskip`.

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

[0.2.0]: https://github.com/Shalim-C/qr-reader-mcp-server/releases/tag/v0.2.0
[0.1.0]: https://github.com/Shalim-C/qr-reader-mcp-server/releases/tag/v0.1.0
