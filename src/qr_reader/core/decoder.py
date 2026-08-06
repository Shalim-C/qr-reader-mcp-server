"""QR code decoding core.

Wraps pyzbar to locate and decode QR codes from OpenCV images.
"""

import cv2
import numpy as np
from pyzbar import pyzbar


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


def detect_qr_positions(img: np.ndarray) -> list[dict]:
    """Detect QR code bounding boxes without decoding content.

    Returns:
        List of dicts with keys: bbox, type.
    """
    positions: list[dict] = []
    decoded_objects = pyzbar.decode(img)
    for obj in decoded_objects:
        if obj.type not in ("QRCODE", "QR_CODE"):
            continue
        x, y, w, h = obj.rect
        positions.append({"bbox": [x, y, w, h], "type": obj.type})
    return positions


def decode_qr_from_region(img: np.ndarray, bbox: list[int]) -> list[dict]:
    """Decode QR codes from a cropped region of the image.

    Args:
        img: Full BGR image.
        bbox: [x, y, width, height] of the target region.

    Returns:
        Same format as decode_qr_from_image.
    """
    x, y, w, h = bbox
    x = max(0, x)
    y = max(0, y)
    w = min(w, img.shape[1] - x)
    h = min(h, img.shape[0] - y)
    roi = img[y:y + h, x:x + w]
    return decode_qr_from_image(roi)
