"""QR code decoding core.

Primary backend: pyzbar (via system libzbar) — best accuracy across
damaged / blurred / multi-code scenarios.

Fallback backend: OpenCV QRCodeDetector — zero system dependency,
usable immediately after `pip install`.  Engages automatically when
pyzbar is not installed or when pyzbar returns no results but OpenCV
detects QR finder patterns.

OpenCV QRCodeDetector is also used for pure detection (without decode)
to distinguish "found but unreadable" from "not found at all", feeding
into the diagnosis engine.
"""

import logging
import cv2
import numpy as np

logger = logging.getLogger("qr-reader-mcp.decoder")

# ── OpenCV QR detector — used for pure detection ───────────────────────
_qr_detector = cv2.QRCodeDetector()

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


def _decode_with_opencv(img: np.ndarray) -> list[dict]:
    """Decode using OpenCV QRCodeDetector — zero system dep.

    Tries detectMulti first (multi-code, OpenCV 4.7+), then falls
    back to single-code detectAndDecode.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    results: list[dict] = []

    # ── Multi-code path (OpenCV 4.7+) ──────────────────────────────────
    try:
        multi_result = _qr_detector.detectMulti(gray)
        if isinstance(multi_result, tuple):
            retval = multi_result[0]
            if retval and len(multi_result) >= 3:
                decoded_info = multi_result[1]
                points = multi_result[2] if len(multi_result) > 2 else None
            else:
                decoded_info = []
                points = None
        else:
            decoded_info = []
            points = None

        if decoded_info:
            for i, content in enumerate(decoded_info):
                if not content:
                    continue
                pts = points[i] if points is not None and i < len(points) else None
                bbox = _points_to_bbox(pts) if pts is not None else [0, 0, 0, 0]
                results.append({
                    "content": content,
                    "bbox": bbox,
                    "type": "QRCODE",
                    "raw_bytes": content.encode("utf-8").hex(),
                })
            if results:
                return results
    except (cv2.error, AttributeError, ValueError, IndexError):
        pass  # detectMulti unavailable — fall through to single-code

    # ── Single-code path ───────────────────────────────────────────────
    try:
        result = _qr_detector.detectAndDecode(gray)
        if isinstance(result, tuple) and len(result) >= 2 and result[0]:
            decoded_info = result[1]
            pts = result[2] if len(result) > 2 else None
            if decoded_info:
                bbox = _points_to_bbox(pts) if pts is not None else [0, 0, 0, 0]
                results.append({
                    "content": decoded_info,
                    "bbox": bbox,
                    "type": "QRCODE",
                    "raw_bytes": decoded_info.encode("utf-8").hex(),
                })
    except (cv2.error, AttributeError, ValueError):
        pass

    return results


def _points_to_bbox(pts) -> list[int]:
    """Convert OpenCV corner points [[x,y],...] to [x, y, w, h]."""
    if pts is None or len(pts) == 0:
        return [0, 0, 0, 0]
    pts = pts.reshape(-1, 2)
    x_min = int(np.min(pts[:, 0]))
    y_min = int(np.min(pts[:, 1]))
    x_max = int(np.max(pts[:, 0]))
    y_max = int(np.max(pts[:, 1]))
    return [x_min, y_min, max(0, x_max - x_min), max(0, y_max - y_min)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_qr_regions(img: np.ndarray) -> bool:
    """Detect whether the image contains any QR-code-like regions.

    Uses OpenCV's QRCodeDetector.detect() which looks for finder
    patterns without attempting to decode.  This allows downstream
    code to distinguish "found but unreadable" (→ RETRYABLE) from
    "nothing here" (→ NO_QR_FOUND).

    Args:
        img: BGR or grayscale image.

    Returns:
        True if at least one QR code region was detected.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    retval, _ = _qr_detector.detect(gray)
    return retval


def clamp_bbox(bbox: list[int], img_shape: tuple) -> tuple[int, int, int, int]:
    """Clamp a [x, y, w, h] bbox to image bounds, returning (x, y, w, h).

    Negative coordinates are snapped to 0, and width/height are capped
    so the region does not exceed the image dimensions.
    """
    x, y, w, h = bbox
    x = max(0, x)
    y = max(0, y)
    w = min(w, img_shape[1] - x)
    h = min(h, img_shape[0] - y)
    return x, y, w, h


def decode_qr_from_image(img: np.ndarray) -> list[dict]:
    """Decode all QR codes found in a full image.

    Primary: pyzbar (best accuracy).
    Fallback: OpenCV QRCodeDetector (zero system dep, single/multi-code).

    When pyzbar returns no results but OpenCV detects finder patterns,
    also tries OpenCV decode as a secondary pass — catching cases where
    pyzbar fails on unusual encoding but OpenCV succeeds.

    Returns:
        List of dicts, each with keys: content, bbox, type, raw_bytes.
    """
    # ── Primary: pyzbar ────────────────────────────────────────────────
    if _PYZBAR_AVAILABLE:
        results = _decode_with_pyzbar(img)
        if results:
            return results

    # ── Fallback / secondary pass: OpenCV ──────────────────────────────
    opencv_results = _decode_with_opencv(img)
    if opencv_results:
        logger.info("QR decoded via OpenCV fallback (pyzbar=%s)", _PYZBAR_AVAILABLE)
    return opencv_results


def decode_qr_from_region(img: np.ndarray, bbox: list[int]) -> list[dict]:
    """Decode QR codes from a cropped region of the image.

    Args:
        img: Full BGR image.
        bbox: [x, y, width, height] of the target region.

    Returns:
        Same format as decode_qr_from_image.
    """
    x, y, w, h = clamp_bbox(bbox, img.shape)
    if w <= 0 or h <= 0:
        return []
    roi = img[y:y + h, x:x + w]
    return decode_qr_from_image(roi)
