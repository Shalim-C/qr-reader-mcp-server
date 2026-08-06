"""Unified image operations layer.

Routes to cv2 when available, falls back to Pillow + numpy when not.
This lets the "light" install skip opencv-python (~100MB) while keeping
all core functionality: image loading, quality analysis, and enhancement.

When cv2 is absent:
  - Image loading       → Pillow + numpy
  - Laplacian blur      → numpy 3×3 kernel convolution
  - Upscale / sharpen   → Pillow ImageEnhance / ImageFilter
  - Contrast adjustment → Pillow ImageEnhance.Contrast
  - Denoise            → Pillow ImageFilter.SMOOTH_MORE (degraded)
  - QR detect/decode   → unavailable (pyzbar is the primary backend anyway)
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("qr-reader-mcp.ops")

# ---------------------------------------------------------------------------
# cv2 availability
# ---------------------------------------------------------------------------
_CV2_AVAILABLE = False
try:
    import cv2  # noqa: F401
    _CV2_AVAILABLE = True
except ImportError:
    pass

# Lazy imports for Pillow fallback
_PIL_IMAGE: type | None = None
_PIL_IMAGE_ENHANCE: object | None = None
_PIL_IMAGE_FILTER: object | None = None


def _ensure_pillow():
    global _PIL_IMAGE, _PIL_IMAGE_ENHANCE, _PIL_IMAGE_FILTER
    if _PIL_IMAGE is None:
        from PIL import Image as _Img
        from PIL import ImageEnhance as _Enh, ImageFilter as _Flt
        _PIL_IMAGE = _Img
        _PIL_IMAGE_ENHANCE = _Enh
        _PIL_IMAGE_FILTER = _Flt


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_image_bytes(img_bytes: bytes, max_long_edge: int = 2560) -> np.ndarray:
    """Load image bytes → numpy array (H×W×C BGR when cv2, RGB when Pillow).

    When cv2 is absent, returns RGB — callers that need BGR should convert.
    Auto-resizes if longer edge exceeds max_long_edge.
    """
    if _CV2_AVAILABLE:
        import cv2
        arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise ValueError("Failed to decode image — unsupported format or corrupt data")
        h, w = arr.shape[:2]
        longer = max(h, w)
        if longer > max_long_edge:
            scale = max_long_edge / longer
            new_w, new_h = int(w * scale), int(h * scale)
            arr = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
            logger.info("Auto-resized %dx%d → %dx%d (limit=%dpx)", w, h, new_w, new_h, max_long_edge)
        return arr
    else:
        _ensure_pillow()
        from io import BytesIO
        img = _PIL_IMAGE.open(BytesIO(img_bytes)).convert("RGB")
        w, h = img.size
        longer = max(w, h)
        if longer > max_long_edge:
            scale = max_long_edge / longer
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), _PIL_IMAGE.LANCZOS)
            logger.info("Auto-resized %dx%d → %dx%d (limit=%dpx)", w, h, new_w, new_h, max_long_edge)
        return np.array(img)


def image_to_bytes(arr: np.ndarray, fmt: str = "png", channel_order: str = "auto") -> bytes:
    """Encode a numpy image array to bytes (PNG/JPEG).

    Args:
        arr: H×W×C image array.
        fmt: Output format — "png" or "jpg".
        channel_order: "bgr", "rgb", or "auto" (default).
            "auto" heuristically detects BGR by comparing blue vs red
            channel means in the center region.
    """
    if channel_order == "auto":
        if arr.ndim == 3 and arr.shape[2] >= 3:
            h, w = arr.shape[:2]
            # Sample center 25% of the image
            cy, cx = h // 2, w // 2
            ch, cw = max(h // 4, 1), max(w // 4, 1)
            center = arr[cy - ch:cy + ch, cx - cw:cx + cw, :3]
            # BGR heuristic: blue channel tends to be dimmer than red
            # when the image is a real-world photo (sky, faces, etc.).
            # For QR codes this is unreliable, so default to RGB if close.
            b_mean = center[:, :, 0].mean()
            r_mean = center[:, :, 2].mean()
            channel_order = "bgr" if r_mean > b_mean * 1.1 else "rgb"
        else:
            channel_order = "rgb"

    if _CV2_AVAILABLE:
        import cv2
        if channel_order == "rgb":
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode(f".{fmt}", arr)
        return buf.tobytes()
    else:
        _ensure_pillow()
        from io import BytesIO
        if channel_order == "bgr":
            arr = arr[:, :, ::-1]  # BGR → RGB
        img = _PIL_IMAGE.fromarray(arr)
        buf = BytesIO()
        img.save(buf, format=fmt.upper() if fmt != "jpg" else "JPEG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Quality analysis (no cv2 needed — pure numpy)
# ---------------------------------------------------------------------------

def laplacian_variance(arr: np.ndarray) -> float:
    """Compute Laplacian variance (blur score) with a 3×3 kernel.

    Equivalent to cv2.Laplacian(gray, CV_64F).var().
    Higher values = sharper images.
    """
    if _CV2_AVAILABLE:
        import cv2
        gray = _to_gray(arr)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Pure numpy fallback — vectorized 3×3 convolution
    gray = _to_gray(arr).astype(np.float64)
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    h, w = gray.shape
    # Extract overlapping 3×3 patches via slicing (vectorized)
    lap = np.zeros((h - 2, w - 2), dtype=np.float64)
    for dy in range(3):
        for dx in range(3):
            if kernel[dy, dx] != 0:
                lap += kernel[dy, dx] * gray[dy:dy + h - 2, dx:dx + w - 2]
    return float(lap.var())


def image_contrast(arr: np.ndarray) -> float:
    """Compute contrast as (max − min) / 255."""
    gray = _to_gray(arr)
    return float(gray.max() - gray.min()) / 255.0


def glare_ratio(arr: np.ndarray) -> float:
    """Fraction of pixels with value > 240."""
    gray = _to_gray(arr)
    return float(np.sum(gray > 240)) / gray.size


def noise_level(arr: np.ndarray) -> float:
    """Estimate noise as std of residual after Gaussian smoothing."""
    if _CV2_AVAILABLE:
        import cv2
        gray = _to_gray(arr)
        smoothed = cv2.GaussianBlur(gray, (0, 0), 3)
        return float(np.std(gray.astype(float) - smoothed.astype(float)))
    # Pillow fallback — use a simple box blur
    gray = _to_gray(arr)
    from PIL import ImageFilter as _Flt
    _ensure_pillow()
    pil_img = _PIL_IMAGE.fromarray(gray)
    smoothed = np.array(pil_img.filter(_Flt.GaussianBlur(3)), dtype=float)
    return float(np.std(gray.astype(float) - smoothed))


# ---------------------------------------------------------------------------
# Enhancement operations
# ---------------------------------------------------------------------------

def op_upscale(arr: np.ndarray, scale: float) -> np.ndarray:
    """Scale image by factor. scale ∈ [1.0, 8.0]."""
    if _CV2_AVAILABLE:
        import cv2
        return cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _ensure_pillow()
    h, w = arr.shape[:2]
    new_w, new_h = int(w * scale), int(h * scale)
    img = _PIL_IMAGE.fromarray(arr)
    return np.array(img.resize((new_w, new_h), _PIL_IMAGE.LANCZOS))


def op_sharpen(arr: np.ndarray, strength: float) -> np.ndarray:
    """Sharpen with custom kernel. strength ∈ [0.3, 5.0].

    Uses the same 3×3 kernel公式 on both cv2 and Pillow paths
    for consistent output.  The kernel is:

        [-1 -1 -1]
        [-1 9s -1] / (9s − 8)   where s = strength
        [-1 -1 -1]

    A singularity exists at s ≈ 0.8889 where the denominator → 0;
    callers must guard this (server._validate_enhance_params handles it).
    """
    denom = 9 * strength - 8
    kernel = np.array([[-1, -1, -1], [-1, 9 * strength, -1], [-1, -1, -1]], dtype=np.float32) / denom

    if _CV2_AVAILABLE:
        import cv2
        return cv2.filter2D(arr, -1, kernel)

    # Pillow fallback — same kernel via numpy convolution
    _ensure_pillow()
    if arr.ndim == 3:
        # Per-channel convolution
        result = np.zeros_like(arr, dtype=np.float32)
        for c in range(arr.shape[2]):
            ch = arr[:, :, c].astype(np.float32)
            h, w = ch.shape
            padded = np.pad(ch, 1, mode='edge')
            conv = np.zeros_like(ch)
            for dy in range(3):
                for dx in range(3):
                    if kernel[dy, dx] != 0:
                        conv += kernel[dy, dx] * padded[dy:dy + h, dx:dx + w]
            result[:, :, c] = np.clip(conv, 0, 255)
        return result.astype(np.uint8)
    else:
        ch = arr.astype(np.float32)
        h, w = ch.shape
        padded = np.pad(ch, 1, mode='edge')
        conv = np.zeros_like(ch)
        for dy in range(3):
            for dx in range(3):
                if kernel[dy, dx] != 0:
                    conv += kernel[dy, dx] * padded[dy:dy + h, dx:dx + w]
        return np.clip(conv, 0, 255).astype(arr.dtype)


def op_contrast(arr: np.ndarray, alpha: float, beta: float = 0) -> np.ndarray:
    """Adjust contrast. alpha ∈ [0.5, 3.0]."""
    if _CV2_AVAILABLE:
        import cv2
        return cv2.convertScaleAbs(arr, alpha=alpha, beta=beta)
    _ensure_pillow()
    img = _PIL_IMAGE.fromarray(arr)
    enhancer = _PIL_IMAGE_ENHANCE.Contrast(img)
    # Pillow contrast: 1.0 = original, <1 = less, >1 = more
    return np.array(enhancer.enhance(alpha))


def op_denoise(arr: np.ndarray, h: int) -> np.ndarray:
    """Noise reduction. h ∈ [3, 30].

    When cv2 is absent this degrades to a simple bilateral-like smooth.
    """
    if _CV2_AVAILABLE:
        import cv2
        return cv2.fastNlMeansDenoisingColored(arr, None, h, h, 7, 21)
    _ensure_pillow()
    img = _PIL_IMAGE.fromarray(arr)
    # Degraded fallback — SMOOTH_MORE + light sharpen to preserve edges
    smoothed = img.filter(_PIL_IMAGE_FILTER.SMOOTH_MORE)
    return np.array(smoothed)


# ---------------------------------------------------------------------------
# QR detection / decode (cv2 only; unavailable in light mode)
# ---------------------------------------------------------------------------

def qr_detect(arr: np.ndarray) -> bool | None:
    """Detect QR finder patterns.

    Returns:
        True  — finder patterns found
        False — no finder patterns detected
        None  — detection unavailable (light mode, no cv2)
    """
    if not _CV2_AVAILABLE:
        logger.debug("QR detection unavailable (cv2 not installed)")
        return None
    import cv2
    gray = _to_gray(arr)
    detector = cv2.QRCodeDetector()
    retval, _ = detector.detect(gray)
    return bool(retval)


def qr_decode_opencv(arr: np.ndarray) -> list[dict]:
    """Decode QR codes via OpenCV. Returns [] in light mode."""
    if not _CV2_AVAILABLE:
        return []
    import cv2
    gray = _to_gray(arr)
    detector = cv2.QRCodeDetector()
    results: list[dict] = []
    try:
        ret = detector.detectAndDecode(gray)
        if isinstance(ret, tuple) and len(ret) >= 2 and ret[0]:
            content = ret[1]
            pts = ret[2] if len(ret) > 2 else None
            bbox = _points_to_bbox(pts) if pts is not None else [0, 0, 0, 0]
            results.append({
                "content": content,
                "bbox": bbox,
                "type": "QRCODE",
                "raw_bytes": content.encode("utf-8").hex(),
            })
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_gray(arr: np.ndarray) -> np.ndarray:
    """Convert a 3-channel array to grayscale, or return as-is if already 2D."""
    if arr.ndim == 2:
        return arr
    # BGR → gray via weighted sum (same as cv2.COLOR_BGR2GRAY)
    if _CV2_AVAILABLE:
        import cv2
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    # Pillow path: assume RGB
    return np.dot(arr[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)


def _points_to_bbox(pts) -> list[int]:
    """Convert OpenCV corner points to [x, y, w, h]."""
    if pts is None or len(pts) == 0:
        return [0, 0, 0, 0]
    pts = pts.reshape(-1, 2)
    x_min = int(np.min(pts[:, 0]))
    y_min = int(np.min(pts[:, 1]))
    x_max = int(np.max(pts[:, 0]))
    y_max = int(np.max(pts[:, 1]))
    return [x_min, y_min, max(0, x_max - x_min), max(0, y_max - y_min)]


def is_cv2_available() -> bool:
    return _CV2_AVAILABLE
