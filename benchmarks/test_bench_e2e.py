"""L3 end-to-end benchmarks — MCP tool handlers.

Tests decode_qrcode_full and enhance_and_decode via call_tool,
covering the full pipeline: load → decode → classify → respond.

All async call_tool calls are wrapped with asyncio.run() so
pytest-benchmark can measure them synchronously.
"""

import asyncio
import base64
import io
import json

from PIL import Image


def _run_async(coro):
    """Run an async function and return its result synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# decode_qrcode_full
# ---------------------------------------------------------------------------

async def _decode_path(path):
    from qr_reader.server import call_tool
    result = await call_tool("decode_qrcode_full", {"image_path": path})
    payload = json.loads(result[0].text)
    assert "result_code" in payload
    return payload


async def _decode_base64(b64):
    from qr_reader.server import call_tool
    return await call_tool("decode_qrcode_full", {"image_base64": b64})


async def _enhance(path, bbox, ops):
    from qr_reader.server import call_tool
    return await call_tool("enhance_and_decode", {
        "image_path": path,
        "bbox": bbox,
        "operations": ops,
    })


def test_e2e_decode_clean_qr_path(benchmark, qr_clean, tmp_path):
    """End-to-end: local path → decode_qrcode_full on a clean QR."""
    path = tmp_path / "qr.png"
    Image.fromarray(qr_clean).save(path, format="PNG")
    benchmark(lambda: asyncio.run(_decode_path(str(path))))


def test_e2e_decode_clean_qr_base64(benchmark, qr_clean):
    """End-to-end: base64 input → decode_qrcode_full."""
    buf = io.BytesIO()
    Image.fromarray(qr_clean).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    benchmark(lambda: asyncio.run(_decode_base64(b64)))


def test_e2e_decode_no_qr(benchmark, no_qr_photo, tmp_path):
    """End-to-end: image with no QR code."""
    path = tmp_path / "no_qr.png"
    Image.fromarray(no_qr_photo).save(path, format="PNG")
    benchmark(lambda: asyncio.run(_decode_path(str(path))))


def test_e2e_decode_blurry_qr(benchmark, qr_blurry, tmp_path):
    """End-to-end: blurry QR — tests diagnosis path."""
    path = tmp_path / "blur.png"
    Image.fromarray(qr_blurry).save(path, format="PNG")
    benchmark(lambda: asyncio.run(_decode_path(str(path))))


def test_e2e_enhance_crop_only(benchmark, qr_clean, tmp_path):
    """End-to-end: enhance_and_decode with no enhancement (crop + decode)."""
    path = tmp_path / "qr.png"
    Image.fromarray(qr_clean).save(path, format="PNG")
    h, w = qr_clean.shape[:2]
    bbox = [w // 4, h // 4, w // 2, h // 2]
    benchmark(lambda: asyncio.run(_enhance(str(path), bbox, [])))


def test_e2e_enhance_upscale_sharpen(benchmark, qr_clean, tmp_path):
    """End-to-end: enhance_and_decode with upscale + sharpen."""
    path = tmp_path / "qr.png"
    Image.fromarray(qr_clean).save(path, format="PNG")
    h, w = qr_clean.shape[:2]
    bbox = [w // 4, h // 4, w // 2, h // 2]
    ops = [
        {"op": "upscale", "params": {"scale": 2.0}},
        {"op": "sharpen", "params": {"strength": 1.5}},
    ]
    benchmark(lambda: asyncio.run(_enhance(str(path), bbox, ops)))


def test_e2e_enhance_full_chain(benchmark, qr_clean, tmp_path):
    """End-to-end: enhance_and_decode — full 4-op chain."""
    path = tmp_path / "qr.png"
    Image.fromarray(qr_clean).save(path, format="PNG")
    h, w = qr_clean.shape[:2]
    bbox = [w // 4, h // 4, w // 2, h // 2]
    ops = [
        {"op": "upscale", "params": {"scale": 2.0}},
        {"op": "sharpen", "params": {"strength": 1.5}},
        {"op": "adjust_contrast", "params": {"alpha": 1.2}},
        {"op": "denoise", "params": {"h": 5}},
    ]
    benchmark(lambda: asyncio.run(_enhance(str(path), bbox, ops)))
