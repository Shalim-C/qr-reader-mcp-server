"""QR code decoding core.

Wraps pyzbar to locate and decode QR codes from OpenCV images.
"""

import cv2
import numpy as np
from pyzbar import pyzbar


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

    Returns:
        List of dicts, each with keys: content, bbox, type, raw_bytes.
    """
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
