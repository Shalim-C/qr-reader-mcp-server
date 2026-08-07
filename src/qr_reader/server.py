"""QR Reader MCP Server — main entry point.

Provides three tools for AI agents:
  decode_qrcode_full  — full-image decode with quality diagnostics
  enhance_and_decode  — region-based enhancement pipeline + decode
  auto_enhance       — automatic multi-strategy enhancement

In light mode (no opencv-python), core functionality is preserved —
enhance operations fall back to Pillow, quality metrics use pure numpy.
"""

import base64
import json
import logging
import os
from collections.abc import Sequence

import numpy as np
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

from qr_reader.core.decoder import (
    clamp_bbox,
    decode_qr_from_image,
    decode_qr_from_region,
    detect_qr_regions,
    validate_bbox,
)
from qr_reader.core.diagnosis import classify_result
from qr_reader.core.distortion import analyze_distortion
from qr_reader.core.ops import (
    image_modulation,
    image_to_bytes,
    is_cv2_available,
    load_image_bytes,
    op_contrast,
    op_denoise,
    op_sharpen,
    op_upscale,
)
from qr_reader.core.url_utils import is_private_url

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "false").lower() == "true"
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "10485760"))  # 10 MB
MAX_INPUT_PIXELS = int(os.getenv("MAX_INPUT_PIXELS", "4096"))  # auto-resize limit

_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qr-reader-mcp")

try:
    from qr_reader import __version__
except ImportError:
    __version__ = "0.0.0"

app = Server("qr-reader-mcp-server")


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_image(
    image_path: str | None = None,
    image_base64: str | None = None,
    image_url: str | None = None,
) -> tuple[np.ndarray, dict]:
    """Load an image from local path, base64 string, or URL.

    Priority: image_path > image_base64 > image_url.
    Returns an RGB ndarray (normalized across backends).
    """
    if image_path:
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in _ALLOWED_IMAGE_EXT:
            raise ValueError(
                f"Unsupported file type: {ext}, only {sorted(_ALLOWED_IMAGE_EXT)} are allowed"
            )
        if not os.path.isfile(image_path):
            raise ValueError(f"Image file not found: {image_path}")
        with open(image_path, "rb") as f:
            img_bytes = f.read()
    elif image_base64:
        # B-14: pre-check estimated size before decoding
        est_size = (len(image_base64) * 3) // 4
        if est_size > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Estimated image size {est_size} bytes exceeds limit "
                f"of {MAX_IMAGE_SIZE} bytes — image may be too large"
            )
        img_bytes = base64.b64decode(image_base64)
    elif image_url:
        if is_private_url(image_url):
            raise ValueError("image_url must not point to internal/private addresses")
        logger.info("Fetching image from URL: %s", image_url[:120])
        resp = requests.get(image_url, timeout=10, allow_redirects=False, stream=True)
        resp.raise_for_status()
        # Stream to enforce MAX_IMAGE_SIZE during download, not after
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > MAX_IMAGE_SIZE:
                resp.close()
                raise ValueError(
                    f"Image size exceeds limit of {MAX_IMAGE_SIZE} bytes "
                    f"(received {total}+ bytes)"
                )
            chunks.append(chunk)
        img_bytes = b"".join(chunks)
    else:
        raise ValueError("Must provide one of image_path, image_base64, or image_url")

    if len(img_bytes) > MAX_IMAGE_SIZE:
        raise ValueError(
            f"Image size {len(img_bytes)} bytes exceeds limit of {MAX_IMAGE_SIZE} bytes"
        )

    return load_image_bytes(img_bytes, max_long_edge=MAX_INPUT_PIXELS)


def img_to_base64(arr: np.ndarray) -> str:
    """Encode an image array (RGB or BGR) to PNG base64."""
    buf = image_to_bytes(arr, fmt="png")
    return base64.b64encode(buf).decode("utf-8")


# ---------------------------------------------------------------------------
# Image enhancement pipeline
# ---------------------------------------------------------------------------

# ── parameter bounds (prevents OOM / NaN / hangs) ───────────────────────
_ENHANCE_BOUNDS: dict[str, dict[str, tuple[float, float, float]]] = {
    "upscale":         {"scale":        (1.0, 8.0, 2.0)},
    "sharpen":         {"strength":     (0.3, 5.0, 1.5)},
    "adjust_contrast": {"alpha":        (0.5, 3.0, 1.5)},
    "denoise":         {"h":            (3, 30, 10)},
}
_MAX_OPERATIONS = 5

# ── auto_enhance strategies (ordered: simpler first, combos last) ──────
_AUTO_ENHANCE_STRATEGIES = [
    ("upscale_2x",     [{"op": "upscale",         "params": {"scale": 2.0}}]),
    ("upscale_4x",     [{"op": "upscale",         "params": {"scale": 4.0}}]),
    ("sharpen",        [{"op": "sharpen",         "params": {"strength": 2.0}}]),
    ("contrast",       [{"op": "adjust_contrast", "params": {"alpha": 1.5}}]),
    ("denoise",        [{"op": "denoise",         "params": {"h": 10}}]),
    ("upscale_sharpen",[
        {"op": "upscale", "params": {"scale": 2.0}},
        {"op": "sharpen", "params": {"strength": 1.5}},
    ]),
    ("upscale_contrast",[
        {"op": "upscale",         "params": {"scale": 2.0}},
        {"op": "adjust_contrast", "params": {"alpha": 1.5}},
    ]),
]

def _validate_enhance_params(op: str, params: dict) -> dict:
    """Clamp enhancement parameters to safe ranges and return cleaned params.

    """
    bounds = _ENHANCE_BOUNDS.get(op, {})
    cleaned = {}
    for key, (lo, hi, default) in bounds.items():
        val = params.get(key, default)
        cleaned[key] = max(lo, min(hi, val))

    return cleaned


def apply_operations(arr: np.ndarray, operations: list[dict]) -> np.ndarray:
    """Apply a sequence of enhancement operations in order.

    Parameters are clamped to safe ranges before use.
    At most _MAX_OPERATIONS steps are applied.
    """
    result = arr.copy()
    for step in operations[:_MAX_OPERATIONS]:
        op = step["op"]
        raw_params = step.get("params", {})
        params = _validate_enhance_params(op, raw_params)

        if op == "upscale":
            result = op_upscale(result, params["scale"])
        elif op == "sharpen":
            result = op_sharpen(result, params["strength"])
        elif op == "adjust_contrast":
            result = op_contrast(result, params["alpha"], params.get("beta", 0))
        elif op == "denoise":
            result = op_denoise(result, params["h"])
    return result


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    Tool(
        name="decode_qrcode_full",
        description=(
            "Scan the entire image for QR codes and decode them. "
            "Returns all detected codes with detailed diagnostics. "
            "Agent should decide next step based on result_code:"
            "SUCCESS → use content; SUCCESS_WITH_WARNING → check warnings;"
            "RETRYABLE → call enhance_and_decode;"
            "NO_QR_FOUND / QR_UNRECOVERABLE → inform user."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": (
                        "Local image absolute path — preferred when available."
                        "Pass the path string directly — zero pipe overhead, no timeout."
                    ),
                },
                "image_base64": {
                    "type": "string",
                    "description": (
                        "Base64-encoded image. Use when the image is in memory or "
                        "when a local path is unavailable. Large images are auto-resized."
                    ),
                },
                "image_url": {
                    "type": "string",
                    "description": (
                        "Public image URL. "
                        "Use when the image is at a remote location accessible by the server."
                    ),
                },
                "symbologies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional whitelist of barcode types to decode. "
                        "Supported: QRCODE, EAN13, EAN8, CODE128, CODE39, "
                        "CODABAR, I25, UPC-A, UPC-E, PDF417, DataMatrix, Aztec. "
                        "Default (empty or omitted) = all types. "
                        "Use e.g. ['EAN13'] for receipts, ['QRCODE'] for URLs."
                    ),
                },
            },
        },
    ),
    Tool(
        name="enhance_and_decode",
        description=(
            "Apply enhancement operations to a region of the image, then decode."
            "Enhancement strategy is decided by the Agent based on decode_qrcode_full diagnostics."
            "Supports upscale, sharpen, "
            "adjust_contrast, denoise — composable in any order."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Local image absolute path — preferred when available.",
                },
                "image_base64": {
                    "type": "string",
                    "description": (
                        "Base64-encoded image — use when the image is in memory. "
                        "Large images are auto-resized."
                    ),
                },
                "image_url": {
                    "type": "string",
                    "description": "Public image URL — use when the image is at a remote location.",
                },
                "bbox": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Target region [x, y, width, height]",
                },
                "operations": {
                    "type": "array",
                    "description": (
                        "List of enhancement operations, applied in order."
                        "If omitted, crops the region and decodes directly (no enhancement)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": [
                                    "upscale",
                                    "sharpen",
                                    "adjust_contrast",
                                    "denoise",
                                ],
                            },
                            "params": {
                                "type": "object",
                                "description": "Operation parameters (optional)",
                            },
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["bbox"],
        },
    ),
    Tool(
        name="auto_enhance",
        description=(
            "Automatically try enhancement strategies to decode a QR code in one call."
            "Tries up to 7 strategies (upscale, sharpen, contrast, denoise, combos) "
            "in sequence — returns as soon as one succeeds."
            "Ideal for RETRYABLE results from decode_qrcode_full:"
            "no manual bbox estimation or operation selection needed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "Local image absolute path — preferred when available.",
                },
                "image_base64": {
                    "type": "string",
                    "description": "Base64-encoded image.",
                },
                "image_url": {
                    "type": "string",
                    "description": "Public image URL.",
                },
                "bbox": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "Optional target region [x, y, width, height]."
                        "If omitted, processes the entire image."
                    ),
                },
            },
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [TOOL_SCHEMAS[0]]  # decode_qrcode_full is always available
    if not READ_ONLY_MODE:
        tools.append(TOOL_SCHEMAS[1])  # enhance_and_decode
        tools.append(TOOL_SCHEMAS[2])  # auto_enhance
    logger.info(
        "Listing %d tools (read_only=%s, cv2=%s)",
        len(tools), READ_ONLY_MODE, is_cv2_available(),
    )
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[TextContent | ImageContent]:
    logger.info("Tool called: %s", name)

    try:
        return await _handle_tool(name, arguments)
    except Exception as exc:
        logger.exception("Unhandled exception in tool %s", name)
        return _error("INTERNAL_ERROR", f"Unexpected error: {exc}")


async def _handle_tool(name: str, arguments: dict) -> Sequence[TextContent | ImageContent]:
    # ── decode_qrcode_full ────────────────────────────────────────────────
    if name == "decode_qrcode_full":
        try:
            img, resize_info = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:  # noqa: BLE001
            return _error("IMAGE_LOAD_FAILED", str(exc))

        results = decode_qr_from_image(img, symbologies=arguments.get("symbologies"))
        qr_detected = detect_qr_regions(img)

        # Distortion + modulation (cv2-only metrics, synchronous with bbox)
        distortion_info: dict | None = None
        modulation_val: float | None = None
        if is_cv2_available() and results and len(results[0].get("bbox", [])) == 4:
            bbox = results[0]["bbox"]
            modulation_val = image_modulation(img, bbox)
            if modulation_val is not None:
                modulation_val = round(modulation_val, 4)
            distortion_info = analyze_distortion(img, bbox)

        info = classify_result(
            img, qr_detected, len(results) > 0, results,
            distortion_info=distortion_info,
            modulation=modulation_val,
        )

        response = {
            "success": info["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING"),
            **info,
            **resize_info,
        }
        quality = info.get("analysis", {}).get("quality", {})
        qscore = info.get("analysis", {}).get("quality_score", -1)
        logger.info(
            "decode_qrcode_full → %s (score=%.2f detected=%d) blur=%.1f contr=%.2f glare=%.2f",
            info["result_code"],
            qscore,
            len(results),
            quality.get("blur_score", -1),
            quality.get("contrast", -1),
            quality.get("glare_ratio", -1),
        )
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]

    # ── enhance_and_decode ────────────────────────────────────────────────
    if name == "enhance_and_decode":
        if READ_ONLY_MODE:
            return _error("READ_ONLY_MODE", "enhance_and_decode is unavailable in read-only mode")

        try:
            img, resize_info = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:  # noqa: BLE001
            return _error("IMAGE_LOAD_FAILED", str(exc))

        bbox_raw = arguments.get("bbox")
        operations = arguments.get("operations", [])

        # Normalize: single [x,y,w,h] → [[x,y,w,h]] for uniform processing
        if bbox_raw and all(isinstance(v, int) for v in bbox_raw):
            bboxes = [bbox_raw]
        elif bbox_raw and all(isinstance(r, list) for r in bbox_raw):
            bboxes = bbox_raw
        else:
            return _error("INVALID_BBOX", "bbox must be [x, y, width, height] or [[x,y,w,h], ...]")

        all_results: list[dict] = []
        for bi, bbox in enumerate(bboxes):
            # Validate bbox shape — raises ValueError with good message
            try:
                validate_bbox(bbox, bi)
            except ValueError as exc:
                return _error("INVALID_BBOX", str(exc))
            x, y, w, h = clamp_bbox(bbox, img.shape)

            # No enhancement → crop and decode directly
            if not operations:
                results = decode_qr_from_region(img, bbox)
                classify_img = img[y:y + h, x:x + w]
            else:
                roi = img[y:y + h, x:x + w]
                enhanced = apply_operations(roi, operations)
                results = decode_qr_from_image(enhanced)
                classify_img = enhanced

            qr_detected = detect_qr_regions(classify_img)
            info = classify_result(classify_img, qr_detected, len(results) > 0, results)
            info["region_index"] = bi
            info["region_bbox"] = bbox
            all_results.append(info)

        response = {
            "success": any(r["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING") for r in all_results),
            "applied_operations": [s["op"] for s in operations],
            "regions_processed": len(all_results),
            "results": all_results,
            **resize_info,
        }
        logger.info(
            "enhance_and_decode → %d regions (ops=%s)",
            len(all_results),
            response["applied_operations"],
        )
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]

    # ── auto_enhance ─────────────────────────────────────────────────────
    if name == "auto_enhance":
        if READ_ONLY_MODE:
            return _error("READ_ONLY_MODE", "auto_enhance is unavailable in read-only mode")

        try:
            img, resize_info = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:  # noqa: BLE001
            return _error("IMAGE_LOAD_FAILED", str(exc))

        bbox_raw = arguments.get("bbox")
        region_img: np.ndarray = img
        bbox_used: list | None = None

        if bbox_raw:
            try:
                validate_bbox(bbox_raw)
            except ValueError as exc:
                return _error("INVALID_BBOX", str(exc))
            x, y, w, h = clamp_bbox(bbox_raw, img.shape)
            region_img = img[y:y + h, x:x + w]
            bbox_used = [x, y, w, h]

        # -- Attempt 0: decode as-is ---------------------------------------
        results = decode_qr_from_image(region_img)
        if results:
            qr_detected = detect_qr_regions(region_img)
            info = classify_result(region_img, qr_detected, True, results)
            response = {
                "success": True,
                "applied_strategy": None,
                "strategies_tried": 0,
                **info,
                **resize_info,
            }
            logger.info("auto_enhance → success without enhancement")
            return [
                TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2)),
                ImageContent(type="image", data=img_to_base64(region_img), mimeType="image/png"),
            ]

        # -- Try each enhancement strategy sequentially --------------------
        strategies_tried = 0
        last_info: dict = {}

        for strategy_name, operations in _AUTO_ENHANCE_STRATEGIES:
            strategies_tried += 1
            enhanced = apply_operations(region_img, operations)
            results = decode_qr_from_image(enhanced)
            if results:
                qr_detected = detect_qr_regions(enhanced)
                info = classify_result(enhanced, qr_detected, True, results)
                response = {
                    "success": True,
                    "applied_strategy": strategy_name,
                    "strategies_tried": strategies_tried,
                    **info,
                    **resize_info,
                }
                if bbox_used:
                    response["bbox_used"] = bbox_used
                logger.info("auto_enhance → success with %s (attempt %d)", strategy_name, strategies_tried)
                return [
                    TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2)),
                    ImageContent(type="image", data=img_to_base64(enhanced), mimeType="image/png"),
                ]

            # Keep the best diagnostic for the final report
            qr_detected = detect_qr_regions(enhanced)
            info = classify_result(enhanced, qr_detected, len(results) > 0, results)
            if not last_info or info["result_code"] not in ("RETRYABLE", "NO_QR_FOUND"):
                last_info = info

        # -- All strategies failed -----------------------------------------
        response = {
            "success": False,
            "applied_strategy": None,
            "strategies_tried": strategies_tried,
            **last_info,
            **resize_info,
            "suggestion": (
                "All 7 enhancement strategies failed to decode a QR code."
                "The image may contain no QR code, or the QR code is too damaged."
            ),
        }
        if bbox_used:
            response["bbox_used"] = bbox_used
        logger.info("auto_enhance → all %d strategies failed", strategies_tried)
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]

    return _error("UNKNOWN_TOOL", f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Structured errors
# ---------------------------------------------------------------------------

def _error(code: str, message: str) -> list[TextContent]:
    """Return a structured error response the AI can reason about."""
    payload = json.dumps(
        {"error": {"code": code, "message": message}},
        ensure_ascii=False,
        indent=2,
    )
    logger.warning("Error response: %s — %s", code, message)
    return [TextContent(type="text", text=payload)]


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def _check_prerequisites() -> None:
    """Warn if critical dependencies are missing."""
    try:
        from pyzbar import pyzbar  # noqa: F401 — availability check
    except ImportError:
        logger.warning(
            "pyzbar not found — install system zbar library: "
            "apt install libzbar0 (Linux) / brew install zbar (macOS) / "
            "vcpkg install zbar (Windows)"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    logger.info(
        "Starting QR Reader MCP Server v%s (read_only=%s, cv2=%s)",
        __version__, READ_ONLY_MODE, is_cv2_available(),
    )
    _check_prerequisites()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def cli():
    """Console entry point."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    cli()
