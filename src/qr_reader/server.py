"""QR Reader MCP Server — main entry point.

Provides two tools for AI agents:
  decode_qrcode_full  — full-image decode with quality diagnostics
  enhance_and_decode  — region-based enhancement pipeline + decode

In light mode (no opencv-python), all functionality is preserved —
enhance operations fall back to Pillow, quality metrics use pure numpy.
"""

import base64
import importlib.metadata
import io
import json
import logging
import os

import numpy as np
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from qr_reader.core.decoder import decode_qr_from_image, decode_qr_from_region, clamp_bbox, detect_qr_regions
from qr_reader.core.diagnosis import classify_result
from qr_reader.core.quality import analyze_image_quality
from qr_reader.core.url_utils import is_private_url
from qr_reader.core.ops import (
    load_image_bytes,
    image_to_bytes,
    op_upscale,
    op_sharpen,
    op_contrast,
    op_denoise,
    is_cv2_available,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "false").lower() == "true"
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "10485760"))  # 10 MB
MAX_INPUT_PIXELS = int(os.getenv("MAX_INPUT_PIXELS", "2560"))  # auto-resize limit

_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qr-reader-mcp")

try:
    __version__ = importlib.metadata.version("qr-reader-mcp-server")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

app = Server("qr-reader-mcp-server")


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_image(
    image_path: str | None = None,
    image_base64: str | None = None,
    image_url: str | None = None,
) -> np.ndarray:
    """Load an image from local path, base64 string, or URL.

    Priority: image_path > image_base64 > image_url.
    Returns an RGB ndarray (cv2 path returns BGR; light mode returns RGB).
    Calling code should be agnostic to channel order — both work with the
    unified ops layer.
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
        img_bytes = base64.b64decode(image_base64)
    elif image_url:
        if is_private_url(image_url):
            raise ValueError("image_url must not point to internal/private addresses")
        logger.info("Fetching image from URL: %s", image_url[:120])
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        img_bytes = resp.content
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
_ENHANCE_BOUNDS = {
    "upscale":         {"scale":        (1.0, 8.0)},
    "sharpen":         {"strength":     (0.3, 5.0)},
    "adjust_contrast": {"alpha":        (0.5, 3.0)},
    "denoise":         {"h":            (3, 30)},
}
_MAX_OPERATIONS = 5


def _validate_enhance_params(op: str, params: dict) -> dict:
    """Clamp enhancement parameters to safe ranges and return cleaned params.

    Also guards against the sharpen singularity at strength ≈ 0.889
    where the kernel denominator (9*strength − 8) approaches zero.
    """
    bounds = _ENHANCE_BOUNDS.get(op, {})
    cleaned = {}
    for key, (lo, hi) in bounds.items():
        val = params.get(key, (lo + hi) / 2)  # default to mid-point
        cleaned[key] = max(lo, min(hi, val))

    # ── sharpen singularity guard: 9*s − 8 == 0 → s ≈ 0.8889 ───────────
    if op == "sharpen":
        s = cleaned["strength"]
        if abs(9 * s - 8) < 0.08:
            s = 0.96 if s < 0.89 else 0.82
            cleaned["strength"] = s

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
            "Scan the entire image for QR codes and decode them. Returns all detected codes with detailed diagnostics."
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
                        "Public image URL. Use when the image is at a remote location accessible by the server."
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
                    "description": "Base64-encoded image — use when the image is in memory. Large images are auto-resized.",
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
]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [TOOL_SCHEMAS[0]]  # decode_qrcode_full is always available
    if not READ_ONLY_MODE:
        tools.append(TOOL_SCHEMAS[1])  # enhance_and_decode
    logger.info(
        "Listing %d tools (read_only=%s, cv2=%s)",
        len(tools), READ_ONLY_MODE, is_cv2_available(),
    )
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("Tool called: %s", name)

    # ── decode_qrcode_full ────────────────────────────────────────────────
    if name == "decode_qrcode_full":
        try:
            img = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:
            return _error("IMAGE_LOAD_FAILED", str(exc))

        results = decode_qr_from_image(img)
        qr_detected = detect_qr_regions(img)
        info = classify_result(img, qr_detected, len(results) > 0, results)
        response = {
            "success": info["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING"),
            **info,
        }
        quality = info.get("analysis", {}).get("quality", {})
        logger.info(
            "decode_qrcode_full → %s (detected=%d) quality: blur=%.1f contrast=%.2f glare=%.2f",
            info["result_code"],
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
            img = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:
            return _error("IMAGE_LOAD_FAILED", str(exc))

        bbox_raw = arguments.get("bbox")
        operations = arguments.get("operations", [])

        # Normalize: single [x,y,w,h] → [[x,y,w,h]] for uniform processing
        if bbox_raw and all(isinstance(v, int) for v in bbox_raw):
            if len(bbox_raw) != 4:
                return _error("INVALID_BBOX", "bbox must be [x, y, width, height] or [[x,y,w,h], ...]")
            bboxes = [bbox_raw]
        elif bbox_raw and all(isinstance(r, list) for r in bbox_raw):
            bboxes = bbox_raw
        else:
            return _error("INVALID_BBOX", "bbox must be [x, y, width, height] or [[x,y,w,h], ...]")

        all_results: list[dict] = []
        for bi, bbox in enumerate(bboxes):
            # No enhancement → crop and decode directly
            if not operations:
                results = decode_qr_from_region(img, bbox)
                x, y, w, h = clamp_bbox(bbox, img.shape)
                classify_img = img[y:y + h, x:x + w] if w > 0 and h > 0 else img
            else:
                x, y, w, h = clamp_bbox(bbox, img.shape)
                if w <= 0 or h <= 0:
                    return _error("INVALID_BBOX", f"Region {bi}: invalid crop (width/height ≤ 0)")
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
        }
        logger.info(
            "enhance_and_decode → %d regions (ops=%s)",
            len(all_results),
            response["applied_operations"],
        )
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
        from pyzbar import pyzbar  # noqa: F811
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
