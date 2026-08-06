"""Benchmark fixtures — synthetic test images generated at runtime.

All images are self-contained: no external files, no network.
Uses `qrcode` + `PIL` + `numpy` (already in dev deps).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import qrcode
from PIL import Image, ImageFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_qr(data: str = "https://example.com/bench",
             version: int = 1, box_size: int = 10, border: int = 4,
             fill: str = "black", back: str = "white") -> np.ndarray:
    """Generate a clean QR code as an RGB numpy array."""
    qr = qrcode.QRCode(version=version, box_size=box_size, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    pil = qr.make_image(fill_color=fill, back_color=back)
    return np.array(pil.convert("RGB"))


def _to_png_bytes(arr: np.ndarray) -> bytes:
    """Convert numpy array → PNG bytes (for load_image tests)."""
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Plain images (no QR)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def gray_100() -> np.ndarray:
    """100×100 constant-gray image."""
    return np.full((100, 100), 128, dtype=np.uint8)


@pytest.fixture(scope="session")
def gray_500() -> np.ndarray:
    """500×500 constant-gray image."""
    return np.full((500, 500), 128, dtype=np.uint8)


@pytest.fixture(scope="session")
def gray_1080p() -> np.ndarray:
    """1920×1080 constant-gray image."""
    return np.full((1080, 1920), 128, dtype=np.uint8)


@pytest.fixture(scope="session")
def bgr_small() -> np.ndarray:
    """Small 3-channel BGR image."""
    return np.full((100, 100, 3), 128, dtype=np.uint8)


@pytest.fixture(scope="session")
def bgr_medium() -> np.ndarray:
    """Medium 3-channel BGR image."""
    return np.full((500, 500, 3), 128, dtype=np.uint8)


@pytest.fixture(scope="session")
def chessboard() -> np.ndarray:
    """100×100 chessboard — high contrast, sharp edges."""
    img = np.zeros((100, 100), dtype=np.uint8)
    img[::2, ::2] = 255
    img[1::2, 1::2] = 255
    return img


# ---------------------------------------------------------------------------
# QR code images (clean + degraded variants)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qr_clean() -> np.ndarray:
    """Clean QR code, ~300×300 px."""
    return _make_qr("https://example.com/bench")


@pytest.fixture(scope="session")
def qr_clean_small() -> np.ndarray:
    """Small clean QR — version 1, box_size=4."""
    return _make_qr("https://example.com/small", version=1, box_size=4)


@pytest.fixture(scope="session")
def qr_blurry() -> np.ndarray:
    """Blurry QR — GaussianBlur sigma=3."""
    img = _make_qr("https://example.com/blur")
    pil = Image.fromarray(img).filter(ImageFilter.GaussianBlur(3))
    return np.array(pil)


@pytest.fixture(scope="session")
def qr_low_contrast() -> np.ndarray:
    """Low-contrast QR — fill=gray on gray background."""
    return _make_qr("https://example.com/low", fill="#555555", back="#888888")


@pytest.fixture(scope="session")
def qr_glare() -> np.ndarray:
    """QR with simulated glare — white overlay in top-left."""
    img = _make_qr("https://example.com/glare")
    img[0:80, 0:80] = [255, 255, 255]
    return img


@pytest.fixture(scope="session")
def qr_damaged() -> np.ndarray:
    """Partially damaged QR — black bar obscures center."""
    img = _make_qr("https://example.com/damaged")
    img[120:180, 50:250] = [0, 0, 0]
    return img


@pytest.fixture(scope="session")
def qr_multi() -> np.ndarray:
    """Image with 2 QR codes side by side on white canvas."""
    canvas = np.full((320, 640, 3), 255, dtype=np.uint8)
    left = _make_qr("https://example.com/first", box_size=6)
    right = _make_qr("https://example.com/second", box_size=6)
    canvas[15:15 + left.shape[0], 15:15 + left.shape[1]] = left
    canvas[15:15 + right.shape[0], 325:325 + right.shape[1]] = right
    return canvas


@pytest.fixture(scope="session")
def no_qr_photo() -> np.ndarray:
    """Small 'photo' image with no QR code — random pixel noise."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (300, 300, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# PNG bytes (for load_image tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qr_clean_png_bytes() -> bytes:
    return _to_png_bytes(_make_qr("https://example.com/bench"))


@pytest.fixture(scope="session")
def large_png_bytes() -> bytes:
    """4K image for scale tests."""
    img = Image.new("RGB", (3840, 2160), color="gray")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
