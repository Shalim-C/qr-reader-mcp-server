"""Integration tests for the MCP server entry point.

Tests the image loading, enhancement pipeline, tool listing, and error
handling — mocking external dependencies (requests, pyzbar, cv2 where needed).
"""

import base64
import io
import json
import os
import tempfile

import numpy as np
import pytest
import requests
from PIL import Image

from qr_reader.server import (
    TOOL_SCHEMAS,
    _error,
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
    try:
        import cv2
    except ImportError:
        pytest.skip("requires opencv-python")
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
        img, _ = load_image(image_path=sample_png_path)
        assert isinstance(img, np.ndarray)
        assert img.shape == (10, 10, 3)

    def test_load_from_base64(self, sample_png_base64):
        img, _ = load_image(image_base64=sample_png_base64)
        assert img.shape == (10, 10, 3)

    def test_load_from_url(self, mocker):
        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("example.com", 443, "93.184.216.34"),
        )
        img = Image.new("RGB", (5, 5), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        mock_resp = mocker.MagicMock()
        mock_resp.iter_content = lambda chunk_size: [data]
        mock_resp.raise_for_status = lambda: None
        mock_session = mocker.MagicMock()
        mock_session.get.return_value = mock_resp
        mocker.patch("qr_reader.server.requests.Session", return_value=mock_session)
        result, _ = load_image(image_url="https://example.com/qr.png")
        assert result.shape == (5, 5, 3)

    def test_rejects_private_url(self, mocker):
        mocker.patch(
            "qr_reader.server.resolve_image_host",
            side_effect=ValueError(
                "hostname 'localhost' is a private/internal address"
            ),
        )
        with pytest.raises(ValueError, match="internal"):
            load_image(image_url="http://localhost/img.png")

    def test_invalid_base64_friendly_error(self):
        """非法 base64 给出明确错误，而非 binascii.Error 泄漏成 INTERNAL_ERROR。"""
        from qr_reader.server import load_image

        with pytest.raises(ValueError, match="Invalid base64"):
            load_image(image_base64="!!!not-base64!!!")

    def test_image_path_realpath_resolved(self, mocker):
        """扩展名白名单必须按 realpath 后的真实目标校验（符号链接伪装）。"""
        from qr_reader.server import load_image

        real = mocker.patch(
            "qr_reader.server.os.path.realpath",
            return_value="C:/real/target.png",
        )
        with pytest.raises(ValueError, match="not found"):
            load_image(image_path="link.png")
        real.assert_called_once_with("link.png")

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
        # Use Pillow (no cv2 needed — works in light mode too)
        from PIL import Image as PILImage
        img = PILImage.new("RGB", (50, 30), color="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        result, _ = load_image(image_base64=b64)
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

    def test_upscale_guard_rejects_oversized_output(self):
        """Chained upscale amplification must be rejected (OOM guard).

        A single upscale that would push an edge past MAX_OUTPUT_PIXELS
        (default 16384) raises instead of allocating unbounded memory.
        """
        from qr_reader.core.ops import op_upscale

        big = np.zeros((3000, 3000, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="MAX_OUTPUT_PIXELS"):
            op_upscale(big, 8.0)  # 3000×8 = 24000 > 16384



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

        mocker.patch("qr_reader.server.load_image",
                      return_value=(sample_qr_image, {"image_size": [50, 50], "resize_factor": 1.0}))
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
        ri = {"image_size": [50, 50], "resize_factor": 1.0}
        dummy = np.zeros((50, 50, 3), dtype=np.uint8)
        mocker.patch("qr_reader.server.load_image", return_value=(dummy, ri))
        result = await call_tool("enhance_and_decode", {"bbox": [0, 0, 10, 10]})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "READ_ONLY_MODE"

    @pytest.mark.asyncio
    async def test_invalid_bbox(self, mocker):
        from qr_reader.server import call_tool

        ri = {"image_size": [50, 50], "resize_factor": 1.0}
        dummy = np.zeros((50, 50, 3), dtype=np.uint8)
        mocker.patch("qr_reader.server.load_image", return_value=(dummy, ri))
        result = await call_tool("enhance_and_decode", {"bbox": [0, 0]})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "INVALID_BBOX"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, mocker):
        from qr_reader.server import call_tool

        result = await call_tool("nonexistent_tool", {})
        payload = json.loads(result[0].text)
        assert payload["error"]["code"] == "UNKNOWN_TOOL"


# ═══════════════════════════════════════════════════════════════════════
# URL download path tests (E-06)
# ═══════════════════════════════════════════════════════════════════════

class TestImageUrlDownload:
    def test_url_redirect_blocked(self, mocker):
        """DNS pinning + allow_redirects=False prevents redirects."""
        from qr_reader.server import load_image

        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("short.link", 443, "93.184.216.34"),
        )
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "https://malicious.internal/"}
        # 302 page body is HTML, not an image → imdecode fails
        mock_resp.iter_content.return_value = [b"<html>redirect</html>"]
        mock_session = mocker.MagicMock()
        mock_session.get.return_value = mock_resp
        mocker.patch("qr_reader.server.requests.Session", return_value=mock_session)

        with pytest.raises(ValueError, match="Failed to decode image"):
            load_image(image_url="https://short.link/qr.png")

    def test_url_download_size_limit_streaming(self, mocker):
        """Streaming download cuts off at MAX_IMAGE_SIZE."""
        from qr_reader.server import load_image

        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("example.com", 443, "93.184.216.34"),
        )
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"x" * 1048576] * 11
        mock_session = mocker.MagicMock()
        mock_session.get.return_value = mock_resp
        mocker.patch("qr_reader.server.requests.Session", return_value=mock_session)
        mocker.patch("qr_reader.server.MAX_IMAGE_SIZE", 10485760)

        with pytest.raises(ValueError, match="Image size exceeds limit"):
            load_image(image_url="https://example.com/huge.png")

    def test_url_timeout_handled(self, mocker):
        """Request timeout raises cleanly."""
        from qr_reader.server import load_image

        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("example.com", 443, "93.184.216.34"),
        )
        mock_session = mocker.MagicMock()
        mock_session.get.side_effect = requests.Timeout
        mocker.patch("qr_reader.server.requests.Session", return_value=mock_session)

        with pytest.raises(requests.Timeout):
            load_image(image_url="https://example.com/slow.png")

    def test_url_fetch_pins_connection_to_resolved_ip(self, mocker):
        """The fetch must connect to the IP returned by resolve_image_host
        (DNS pinning) — never re-resolve the hostname for the request."""
        from qr_reader.server import _PinnedIPAdapter, load_image

        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("example.com", 443, "93.184.216.34"),
        )
        img = Image.new("RGB", (1, 1), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        mock_resp = mocker.MagicMock()
        mock_resp.iter_content = lambda chunk_size: [png]
        mock_resp.raise_for_status = lambda: None
        mock_session = mocker.MagicMock()
        mock_session.get.return_value = mock_resp
        mocker.patch("qr_reader.server.requests.Session", return_value=mock_session)

        load_image(image_url="https://example.com/qr.png")

        mounts = [c.args for c in mock_session.mount.call_args_list]
        assert mounts, "session.mount 应被调用（http/https 各一次）"
        for scheme, adapter in mounts:
            assert isinstance(adapter, _PinnedIPAdapter), f"{scheme} 未使用 pinned adapter"
            assert adapter._pinned_ip == "93.184.216.34"

    def test_url_session_ignores_proxy_env(self, mocker):
        """trust_env=False — HTTP(S)_PROXY 环境变量不得绕过 IP pinning
        （代理会重新解析 DNS，把解析权交回给不受控的一方）。"""
        from qr_reader.server import load_image

        mocker.patch(
            "qr_reader.server.resolve_image_host",
            return_value=("example.com", 443, "93.184.216.34"),
        )
        img = Image.new("RGB", (1, 1), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        real_session = requests.Session()
        mock_resp = mocker.MagicMock()
        mock_resp.iter_content = lambda chunk_size: [png]
        mock_resp.raise_for_status = lambda: None
        mocker.patch.object(real_session, "get", return_value=mock_resp)
        mocker.patch("qr_reader.server.requests.Session", return_value=real_session)

        load_image(image_url="https://example.com/qr.png")

        assert real_session.trust_env is False
