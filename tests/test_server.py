"""Integration tests for the MCP server entry point.

Tests the image loading, enhancement pipeline, tool listing, and error
handling — mocking external dependencies (requests, pyzbar, cv2 where needed).
"""

import base64
import io
import json
import os
import tempfile

import cv2
import numpy as np
import pytest
from PIL import Image

from qr_reader.server import (
    _error,
    TOOL_SCHEMAS,
    apply_operations,
    img_to_base64,
    load_image,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_png_path():
    """Create a tiny valid PNG on disk and return its path."""
    img = Image.new("RGB", (10, 10), color="white")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f, format="PNG")
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def sample_png_base64():
    """Return a base64-encoded 10×10 white PNG."""
    img = Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


@pytest.fixture
def sample_qr_image():
    """Generate a synthetic image with a simple QR-like pattern.

    Not a valid QR, but enough to test the decoding pipeline works."""
    import qrcode
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data("https://example.com/test")
    qr.make(fit=True)
    pil = qr.make_image(fill_color="black", back_color="white")
    return cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------------------
# load_image
# ---------------------------------------------------------------------------

class TestLoadImage:
    def test_load_from_local_path(self, sample_png_path):
        img = load_image(image_path=sample_png_path)
        assert isinstance(img, np.ndarray)
        assert img.shape == (10, 10, 3)

    def test_load_from_base64(self, sample_png_base64):
        img = load_image(image_base64=sample_png_base64)
        assert img.shape == (10, 10, 3)

    def test_load_from_url(self, mocker):
        mock_get = mocker.patch("qr_reader.server.requests.get")
        img = Image.new("RGB", (5, 5), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        mock_resp = mocker.MagicMock()
        mock_resp.iter_content = lambda chunk_size: [data]
        mock_resp.raise_for_status = lambda: None
        mock_get.return_value = mock_resp
        result = load_image(image_url="https://example.com/qr.png")
        assert result.shape == (5, 5, 3)

    def test_rejects_private_url(self, mocker):
        mocker.patch("qr_reader.server.is_private_url", return_value=True)
        with pytest.raises(ValueError, match="internal"):
            load_image(image_url="http://localhost/img.png")

    def test_rejects_unsupported_extension(self, tmp_path):
        bad = tmp_path / "image.txt"
        bad.write_bytes(b"not an image")
        with pytest.raises(ValueError, match="Unsupported file type"):
            load_image(image_path=str(bad))

    def test_rejects_nonexistent_file(self):
        with pytest.raises(ValueError, match="Image file not found"):
            load_image(image_path="/nonexistent/qr.png")

    def test_rejects_no_input(self):
        with pytest.raises(ValueError, match="Must provide one of"):
            load_image()

    def test_rejects_oversized_image(self, sample_png_base64, monkeypatch):
        monkeypatch.setattr("qr_reader.server.MAX_IMAGE_SIZE", 10)
        with pytest.raises(ValueError, match="exceeds limit"):
            load_image(image_base64=sample_png_base64)

    def test_auto_resize_large_image(self, monkeypatch):
        """Image exceeding MAX_INPUT_PIXELS on longest edge gets downscaled."""
        monkeypatch.setattr("qr_reader.server.MAX_INPUT_PIXELS", 20)
        img = np.zeros((50, 30, 3), dtype=np.uint8)
        # wrap via base64
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result = load_image(image_base64=b64)
        h, w = result.shape[:2]
        assert max(h, w) <= 20


# ---------------------------------------------------------------------------
# apply_operations
# ---------------------------------------------------------------------------

class TestApplyOperations:
    def test_upscale(self):
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        result = apply_operations(img, [{"op": "upscale", "params": {"scale": 2.0}}])
        assert result.shape == (40, 40, 3)

    def test_sharpen(self):
        img = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        result = apply_operations(img, [{"op": "sharpen", "params": {"strength": 1.5}}])
        assert result.shape == img.shape

    def test_adjust_contrast(self):
        img = np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8)
        result = apply_operations(img, [{"op": "adjust_contrast", "params": {"alpha": 1.5}}])
        assert result.shape == img.shape

    def test_denoise(self):
        img = np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8)
        result = apply_operations(img, [{"op": "denoise", "params": {"h": 10}}])
        assert result.shape == img.shape

    def test_chain_multiple_operations(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        ops = [
            {"op": "upscale", "params": {"scale": 2.0}},
            {"op": "sharpen", "params": {"strength": 1.5}},
            {"op": "adjust_contrast", "params": {"alpha": 1.2}},
        ]
        result = apply_operations(img, ops)
        assert result.shape == (20, 20, 3)

    def test_params_clamped_to_bounds(self):
        """Extreme params are clamped to safe ranges — no crash."""
        img = np.zeros((30, 30, 3), dtype=np.uint8)
        # scale=20 exceeds max (8.0) — should be clamped
        result = apply_operations(img, [{"op": "upscale", "params": {"scale": 20.0}}])
        assert result.shape[0] <= 30 * 8  # clamped to 8 at most

    def test_sharpen_singularity_guard(self):
        """Strength ≈ 0.889 triggers the singularity nudge — no crash."""
        img = np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8)
        result = apply_operations(img, [{"op": "sharpen", "params": {"strength": 0.889}}])
        assert result.shape == img.shape

    def test_max_operations_capped(self):
        """More than _MAX_OPERATIONS steps are truncated.

        scale=1.1 applied 5 times → ~1.61× enlargement.
        """
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        ops = [{"op": "upscale", "params": {"scale": 1.1}}] * 10
        result = apply_operations(img, ops)
        # Only 5 ops applied → max scale = 1.1^5 ≈ 1.61
        h, w = result.shape[:2]
        assert 10 <= h <= 17  # 1.61×10 ≈ 16.1 → int rounding
        assert 10 <= w <= 17


# ---------------------------------------------------------------------------
# image_to_base64
# ---------------------------------------------------------------------------

class TestImgToBase64:
    def test_roundtrip(self):
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        b64 = img_to_base64(img)
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0
        # Re-load to verify valid PNG
        reloaded = Image.open(io.BytesIO(decoded))
        assert reloaded.size == (10, 10)


# ---------------------------------------------------------------------------
# _error helper
# ---------------------------------------------------------------------------

class TestError:
    def test_structured_error(self):
        result = _error("TEST_CODE", "Something went wrong")
        assert len(result) == 1
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "TEST_CODE"
        assert "Something went wrong" in payload["error"]["message"]


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_decode_qrcode_full_schema(self):
        schema = TOOL_SCHEMAS[0]
        assert schema.name == "decode_qrcode_full"
        props = schema.inputSchema["properties"]
        assert "image_path" in props
        assert "image_base64" in props
        assert "image_url" in props

    def test_enhance_and_decode_schema(self):
        schema = TOOL_SCHEMAS[1]
        assert schema.name == "enhance_and_decode"
        assert "bbox" in schema.inputSchema["required"]


# ---------------------------------------------------------------------------
# Server tool handlers (mocked)
# ---------------------------------------------------------------------------

class TestCallToolDecodeQrcodeFull:
    """Tests for decode_qrcode_full via call_tool with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_success_path(self, mocker, sample_qr_image):
        """End-to-end: decode_qrcode_full on a real QR returns SUCCESS."""
        from qr_reader.server import call_tool

        mocker.patch("qr_reader.server.load_image", return_value=sample_qr_image)
        result = await call_tool("decode_qrcode_full", {"image_path": "/fake/qr.png"})
        payload = json.loads(result[0].text)

        # Verify result_code is present and valid
        assert "result_code" in payload

        # When pyzbar is available, a clean QR should decode to SUCCESS
        try:
            from pyzbar import pyzbar as _  # noqa
            assert payload["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING")
            assert payload["results"][0]["content"] == "https://example.com/test"
        except ImportError:
            # Without pyzbar, any result_code is acceptable
            assert payload["result_code"] in (
                "SUCCESS", "SUCCESS_WITH_WARNING", "RETRYABLE",
                "NO_QR_FOUND", "QR_UNRECOVERABLE",
            )

    @pytest.mark.asyncio
    async def test_image_load_failure(self, mocker):
        from qr_reader.server import call_tool

        mocker.patch("qr_reader.server.load_image", side_effect=ValueError("bad"))
        result = await call_tool("decode_qrcode_full", {"image_path": "/bad.png"})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "IMAGE_LOAD_FAILED"


class TestCallToolEnhanceAndDecode:
    @pytest.mark.asyncio
    async def test_read_only_mode_blocked(self, mocker, monkeypatch):
        from qr_reader.server import call_tool

        monkeypatch.setattr("qr_reader.server.READ_ONLY_MODE", True)
        mocker.patch("qr_reader.server.load_image")
        result = await call_tool("enhance_and_decode", {"bbox": [0, 0, 10, 10]})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "READ_ONLY_MODE"

    @pytest.mark.asyncio
    async def test_invalid_bbox(self, mocker):
        from qr_reader.server import call_tool

        mocker.patch("qr_reader.server.load_image", return_value=np.zeros((50, 50, 3), dtype=np.uint8))
        result = await call_tool("enhance_and_decode", {"bbox": [0, 0]})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "INVALID_BBOX"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, mocker):
        from qr_reader.server import call_tool

        result = await call_tool("nonexistent_tool", {})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "UNKNOWN_TOOL"
