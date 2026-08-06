"""QR Reader MCP Server — main entry point.

Provides two tools for AI agents:
  decode_qrcode_full  — full-image decode with quality diagnostics
  enhance_and_decode  — region-based enhancement pipeline + decode
"""

import base64
import io
import json
import logging
import os
import cv2
import numpy as np
import requests
from PIL import Image
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from qr_reader.core.decoder import decode_qr_from_image, decode_qr_from_region
from qr_reader.core.diagnosis import classify_result
from qr_reader.core.quality import analyze_image_quality
from qr_reader.core.url_utils import is_private_url

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "false").lower() == "true"
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "10485760"))  # 10 MB
MAX_INPUT_PIXELS = int(os.getenv("MAX_INPUT_PIXELS", "1920"))  # auto-resize limit

_ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qr-reader-mcp")

app = Server("qr-reader-mcp-server")


# ---------------------------------------------------------------------------
# Image loading / encoding
# ---------------------------------------------------------------------------

def load_image(
    image_path: str | None = None,
    image_base64: str | None = None,
    image_url: str | None = None,
) -> np.ndarray:
    """Load an image from local path, base64 string, or URL.

    Priority: image_path > image_base64 > image_url.
    Returns a BGR ndarray.
    """
    if image_path:
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in _ALLOWED_IMAGE_EXT:
            raise ValueError(
                f"不支持的文件类型: {ext}，仅允许 {sorted(_ALLOWED_IMAGE_EXT)}"
            )
        if not os.path.isfile(image_path):
            raise ValueError(f"图片文件不存在: {image_path}")
        with open(image_path, "rb") as f:
            img_bytes = f.read()
    elif image_base64:
        img_bytes = base64.b64decode(image_base64)
    elif image_url:
        if is_private_url(image_url):
            raise ValueError("image_url 不允许指向内网/私有地址")
        logger.info("Fetching image from URL: %s", image_url[:120])
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        img_bytes = resp.content
    else:
        raise ValueError("必须提供 image_path、image_base64 或 image_url 之一")

    if len(img_bytes) > MAX_IMAGE_SIZE:
        raise ValueError(
            f"图片大小 {len(img_bytes)} bytes 超过上限 {MAX_IMAGE_SIZE} bytes"
        )

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    # ── auto-resize: keep longest edge ≤ MAX_INPUT_PIXELS ──────────
    h, w = img.shape[:2]
    longer = max(h, w)
    if longer > MAX_INPUT_PIXELS:
        scale = MAX_INPUT_PIXELS / longer
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        logger.info("Auto-resized %dx%d → %dx%d (limit=%dpx)", w, h, new_w, new_h, MAX_INPUT_PIXELS)

    return img


def image_to_base64(img: np.ndarray) -> str:
    """Encode a BGR image to PNG base64."""
    _, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf).decode("utf-8")


# ---------------------------------------------------------------------------
# Image enhancement pipeline
# ---------------------------------------------------------------------------

def apply_operations(img: np.ndarray, operations: list[dict]) -> np.ndarray:
    """Apply a sequence of enhancement operations in order."""
    result = img.copy()
    for step in operations:
        op = step["op"]
        params = step.get("params", {})
        if op == "upscale":
            scale = params.get("scale", 2.0)
            result = cv2.resize(
                result, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
        elif op == "sharpen":
            strength = params.get("strength", 1.5)
            kernel = (
                np.array([[-1, -1, -1], [-1, 9 * strength, -1], [-1, -1, -1]])
                / (9 * strength - 8)
            )
            result = cv2.filter2D(result, -1, kernel)
        elif op == "adjust_contrast":
            alpha = params.get("alpha", 1.5)
            beta = params.get("beta", 0)
            result = cv2.convertScaleAbs(result, alpha=alpha, beta=beta)
        elif op == "denoise":
            h = params.get("h", 10)
            result = cv2.fastNlMeansDenoisingColored(result, None, h, h, 7, 21)
    return result


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    Tool(
        name="decode_qrcode_full",
        description=(
            "对整张图片进行二维码识别和解码。返回所有检测结果及详情信息。"
            "Agent 应根据 result_code 决定下一步："
            "SUCCESS → 使用内容；SUCCESS_WITH_WARNING → 检查警告；"
            "RETRYABLE → 调用 enhance_and_decode；"
            "NO_QR_FOUND / QR_UNRECOVERABLE → 告知用户。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": (
                        "本地图片绝对路径——优先使用（如有）。"
                        "直接传路径字符串，零管道开销，不会超时。"
                    ),
                },
                "image_base64": {
                    "type": "string",
                    "description": (
                        "Base64 编码的图片。图片在内存中、"
                        "或无法获取本地路径时使用。大图会自动缩放。"
                    ),
                },
                "image_url": {
                    "type": "string",
                    "description": (
                        "图片公网 URL。图片在服务器可访问的远程位置时使用。"
                    ),
                },
            },
        },
    ),
    Tool(
        name="enhance_and_decode",
        description=(
            "对图片指定区域执行增强操作后解码。"
            "增强策略由 Agent 根据 decode_qrcode_full 返回的详情自行决定。"
            "支持 upscale(放大)、sharpen(锐化)、"
            "adjust_contrast(调对比度)、denoise(降噪)，可组合使用。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "image_path": {
                    "type": "string",
                    "description": "本地图片绝对路径——优先使用（如有）。",
                },
                "image_base64": {
                    "type": "string",
                    "description": "Base64 编码的图片——图片在内存中时使用。大图会自动缩放。",
                },
                "image_url": {
                    "type": "string",
                    "description": "图片公网 URL——图片在远程位置时使用。",
                },
                "bbox": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "目标区域 [x, y, width, height]",
                },
                "operations": {
                    "type": "array",
                    "description": (
                        "增强操作列表，按顺序执行。"
                        "不传则仅裁剪目标区域后直接解码（无增强）。"
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
                                "description": "操作参数（可选）",
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
    logger.info("Listing %d tools (read_only=%s)", len(tools), READ_ONLY_MODE)
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
        qr_detected = len(results) > 0
        info = classify_result(img, qr_detected, len(results) > 0, results)
        response = {
            "success": info["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING"),
            **info,
        }
        logger.info(
            "decode_qrcode_full → %s (detected=%d)",
            info["result_code"],
            len(results),
        )
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]

    # ── enhance_and_decode ────────────────────────────────────────────────
    if name == "enhance_and_decode":
        if READ_ONLY_MODE:
            return _error("READ_ONLY_MODE", "enhance_and_decode 在只读模式下不可用")

        try:
            img = load_image(
                image_path=arguments.get("image_path"),
                image_base64=arguments.get("image_base64"),
                image_url=arguments.get("image_url"),
            )
        except Exception as exc:
            return _error("IMAGE_LOAD_FAILED", str(exc))

        bbox = arguments.get("bbox")
        operations = arguments.get("operations", [])

        # Validate bbox
        if not bbox or len(bbox) != 4:
            return _error("INVALID_BBOX", "bbox 必须为 [x, y, width, height]")

        # 无增强操作 → 直接裁剪解码（复用 decode_qr_from_region）
        if not operations:
            results = decode_qr_from_region(img, bbox)
            classify_img = img  # 质量分析基于原图
        else:
            # 有增强操作 → 裁剪→增强→解码
            x, y, w, h = bbox
            x, y = max(0, x), max(0, y)
            w = min(w, img.shape[1] - x)
            h = min(h, img.shape[0] - y)

            if w <= 0 or h <= 0:
                return _error("INVALID_BBOX", "裁剪区域无效（宽/高 ≤ 0）")

            roi = img[y:y + h, x:x + w]
            enhanced = apply_operations(roi, operations)
            results = decode_qr_from_image(enhanced)
            classify_img = enhanced  # 质量分析基于增强后的图
        qr_detected = len(results) > 0
        info = classify_result(classify_img, qr_detected, len(results) > 0, results)

        response = {
            "success": info["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING"),
            "applied_operations": [s["op"] for s in operations],
            **info,
        }
        logger.info(
            "enhance_and_decode → %s (ops=%s)",
            info["result_code"],
            response["applied_operations"],
        )
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]

    return _error("UNKNOWN_TOOL", f"未知工具: {name}")


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
    logger.info("Starting QR Reader MCP Server (read_only=%s)", READ_ONLY_MODE)
    _check_prerequisites()
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def cli():
    """Console entry point."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    cli()
