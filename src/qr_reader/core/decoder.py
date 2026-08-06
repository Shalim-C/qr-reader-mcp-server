"""QR code decoding core.

Primary backend: pyzbar (via system libzbar) — best accuracy across
damaged / blurred / multi-code scenarios.

Fallback backend: OpenCV QRCodeDetector (only available when cv2 is
installed).  Engages automatically when pyzbar is unavailable or when
pyzbar returns no results but OpenCV detects QR finder patterns.

In light mode (no cv2), only pyzbar is used — which is the primary
backend anyway.
"""

import logging
import numpy as np

logger = logging.getLogger("qr-reader-mcp.decoder")

# ── pyzbar availability check ──────────────────────────────────────────
_PYZBAR_AVAILABLE = False
try:
    from pyzbar import pyzbar  # noqa: F401
    _PYZBAR_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------

def _decode_with_pyzbar(img: np.ndarray) -> list[dict]:
    """Decode using pyzbar — best accuracy, supports multi-code."""
    results: list[dict] = []
    decoded_objects = pyzbar.decode(img)
    for obj in decoded_objects:
        if obj.type not in ("QRCODE", "QR_CODE"):
            continue
        content = obj.data.decode("utf-8", errors="replace")
        x, y, w, h = obj.rect
        results.append({
            "content": content if content else None,
            "bbox": [x, y, w, h],
            "type": obj.type,
            "raw_bytes": obj.data.hex(),
        })
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_qr_regions(img: np.ndarray) -> bool:
    """Detect whether the image contains any QR-code-like regions.

    Uses OpenCV QRCodeDetector.detect() when available; returns False
    in light mode (the diagnosis engine falls back to heuristic
    classification).
    """
    from qr_reader.core.ops import qr_detect
    return qr_detect(img)


def clamp_bbox(bbox: list[int], img_shape: tuple) -> tuple[int, int, int, int]:
    """Clamp a [x, y, w, h] bbox to image bounds, returning (x, y, w, h)."""
    x, y, w, h = bbox
    x = max(0, x)
    y = max(0, y)
    w = min(w, img_shape[1] - x)
    h = min(h, img_shape[0] - y)
    return x, y, w, h


def decode_qr_from_image(img: np.ndarray) -> list[dict]:
    """Decode all QR codes found in a full image.

    Primary: pyzbar (best accuracy).
    Fallback: OpenCV QRCodeDetector (when cv2 is installed).

    When pyzbar returns no results but OpenCV detects finder patterns,
    also tries OpenCV decode as a secondary pass.

    Returns:
        List of dicts, each with keys: content, bbox, type, raw_bytes.
    """
    # ── Primary: pyzbar ────────────────────────────────────────────────
    if _PYZBAR_AVAILABLE:
        results = _decode_with_pyzbar(img)
        if results:
            return results

    # ── Fallback / secondary pass: OpenCV ──────────────────────────────
    from qr_reader.core.ops import qr_decode_opencv, is_cv2_available
    opencv_results = qr_decode_opencv(img)
    if opencv_results:
        logger.info("QR decoded via OpenCV fallback (pyzbar=%s)", _PYZBAR_AVAILABLE)
    elif is_cv2_available():
        logger.debug("OpenCV decode attempted but returned no results")
    return opencv_results


def decode_qr_from_region(img: np.ndarray, bbox: list[int]) -> list[dict]:
    """Decode QR codes from a cropped region of the image.

    Args:
        img: Full image array.
        bbox: [x, y, width, height] of the target region.

    Returns:
        Same format as decode_qr_from_image.
    """
    x, y, w, h = clamp_bbox(bbox, img.shape)
    if w <= 0 or h <= 0:
        return []
    roi = img[y:y + h, x:x + w]
    return decode_qr_from_image(roi)
