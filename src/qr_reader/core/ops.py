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
from typing import Any

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

# Lazy imports for Pillow fallback (Any typed — assigned dynamically in _ensure_pillow)
_PIL_IMAGE: Any = None
_PIL_IMAGE_ENHANCE: Any = None
_PIL_IMAGE_FILTER: Any = None


def _ensure_pillow():
    global _PIL_IMAGE, _PIL_IMAGE_ENHANCE, _PIL_IMAGE_FILTER
    if _PIL_IMAGE is None:
        from PIL import Image as _Img
        from PIL import ImageEnhance as _Enh
        from PIL import ImageFilter as _Flt
        _PIL_IMAGE = _Img
        _PIL_IMAGE_ENHANCE = _Enh
        _PIL_IMAGE_FILTER = _Flt


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_image_bytes(
    img_bytes: bytes, max_long_edge: int = 2560
) -> tuple[np.ndarray, dict]:
    """Load image bytes → (numpy array (H×W×C RGB), resize_info).

    Auto-resizes if longer edge exceeds max_long_edge.
    resize_info contains image_size, resize_factor, and original_size (if resized).
    Returns RGB regardless of backend (cv2 natively returns BGR).
    """
    if _CV2_AVAILABLE:
        import cv2
        arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise ValueError("Failed to decode image — unsupported format or corrupt data")
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)  # normalize to RGB
        h, w = arr.shape[:2]
        orig_w, orig_h = w, h
        longer = max(h, w)
        if longer > max_long_edge:
            scale = max_long_edge / longer
            new_w, new_h = int(w * scale), int(h * scale)
            arr = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
            h, w = new_h, new_w
            logger.info("Auto-resized %dx%d → %dx%d (limit=%dpx)", orig_h, orig_w, h, w, max_long_edge)
        return arr, _resize_info(w, h, orig_w, orig_h)
    else:
        _ensure_pillow()
        from io import BytesIO
        try:
            img = _PIL_IMAGE.open(BytesIO(img_bytes)).convert("RGB")
        except Exception:  # noqa: BLE001 — Pillow raises many types, all should become ValueError
            raise ValueError("Failed to decode image — unsupported format or corrupt data")
        orig_w, orig_h = img.size
        w, h = orig_w, orig_h
        longer = max(w, h)
        if longer > max_long_edge:
            scale = max_long_edge / longer
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), _PIL_IMAGE.LANCZOS)
            w, h = new_w, new_h
            logger.info("Auto-resized %dx%d → %dx%d (limit=%dpx)", orig_w, orig_h, w, h, max_long_edge)
        return np.array(img), _resize_info(w, h, orig_w, orig_h)

def _resize_info(w: int, h: int, orig_w: int, orig_h: int) -> dict:
    """Build resize metadata dict for Agent bbox mapping."""
    info: dict = {"image_size": [h, w], "resize_factor": round(w / orig_w, 4)}
    if orig_w != w or orig_h != h:
        info["original_size"] = [orig_h, orig_w]
    return info


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
        channel_order = "rgb"  # load_image_bytes always returns RGB now

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
        bio = BytesIO()
        img.save(bio, format=fmt.upper() if fmt != "jpg" else "JPEG")
        return bio.getvalue()


# ---------------------------------------------------------------------------
# Quality analysis (no cv2 needed — pure numpy)
# ---------------------------------------------------------------------------

def laplacian_variance(arr: np.ndarray, gray: np.ndarray | None = None) -> float:
    """Compute Laplacian variance (blur score) with a 3×3 kernel.

    Equivalent to cv2.Laplacian(gray, CV_64F).var().
    Higher values = sharper images.

    Args:
        arr: Source image.
        gray: Pre-computed grayscale array (avoids redundant _to_gray).
    """
    if gray is not None:
        g = gray.astype(np.float64) if gray.dtype != np.float64 else gray
    elif _CV2_AVAILABLE:
        import cv2
        g = _to_gray(arr).astype(np.float64)
        return float(cv2.Laplacian(g, cv2.CV_64F).var())
    else:
        g = _to_gray(arr).astype(np.float64)

    if _CV2_AVAILABLE and gray is not None:
        import cv2
        return float(cv2.Laplacian(g, cv2.CV_64F).var())

    # Pure numpy fallback — vectorized 3×3 convolution
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    h, w = g.shape
    if h < 3 or w < 3:
        return 0.0  # image too small for Laplacian
    # Extract overlapping 3×3 patches via slicing (vectorized)
    lap = np.zeros((h - 2, w - 2), dtype=np.float64)
    for dy in range(3):
        for dx in range(3):
            if kernel[dy, dx] != 0:
                lap += kernel[dy, dx] * g[dy:dy + h - 2, dx:dx + w - 2]
    return float(lap.var())


def image_contrast(arr: np.ndarray, gray: np.ndarray | None = None) -> float:
    """Compute contrast as grayscale standard deviation / 128.

    Robust to single-outlier influence (unlike max-min range).
    0.0 = perfectly flat, ~0.4 = normal, 1.0 = extreme.
    """
    g = gray if gray is not None else _to_gray(arr)
    return float(np.std(g)) / 128.0


def image_modulation(arr: np.ndarray, bbox: list[int]) -> float | None:
    """ISO 15415 Modulation — contrast within the QR symbol region.

    Uses Otsu threshold to separate dark/light modules, then computes
    (light_mean - dark_mean) / light_mean.  Returns None if the region
    cannot be segmented (monochrome or too small).

    Args:
        arr: Full image (H×W×C or H×W).
        bbox: [x, y, w, h] of the QR code region.
    """
    import cv2
    g = _to_gray(arr)
    x, y, w, h = bbox
    if w < 5 or h < 5:
        return None
    roi = g[y:y + h, x:x + w]
    # Otsu threshold to separate dark/light modules
    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = roi[binary == 0]
    light = roi[binary == 255]
    if len(dark) < 10 or len(light) < 10:
        return None
    dark_mean = float(np.mean(dark))
    light_mean = float(np.mean(light))
    if light_mean < 1.0:
        return None
    return float((light_mean - dark_mean) / light_mean)


def glare_ratio(arr: np.ndarray, gray: np.ndarray | None = None) -> float:
    """Spatial concentration of overexposed pixels — glare indicator.

    Divides image into a 4×4 grid and measures how unevenly bright pixels
    are distributed. Uniform white backgrounds produce low values (~0.05);
    localized glare spots produce higher values (≥0.10).
    """
    g = gray if gray is not None else _to_gray(arr)
    bright = g > 240
    overall = float(np.sum(bright)) / g.size

    # Very dark or very bright image → not glare
    if overall < 0.1 or overall > 0.9:
        return 0.0

    # Spatial distribution: compute bright ratio per grid cell
    h, w = g.shape
    gh, gw = max(1, h // 4), max(1, w // 4)
    cell_ratios: list[float] = []
    for i in range(4):
        y0, y1 = i * gh, min((i + 1) * gh, h)
        for j in range(4):
            x0, x1 = j * gw, min((j + 1) * gw, w)
            cell = bright[y0:y1, x0:x1]
            cell_ratios.append(float(np.sum(cell)) / cell.size)

    # High variance across cells = concentrated glare
    return float(np.std(cell_ratios))


def noise_level(arr: np.ndarray, gray: np.ndarray | None = None) -> float:
    """Estimate noise as std of residual after Gaussian smoothing."""
    g = gray if gray is not None else _to_gray(arr)
    if _CV2_AVAILABLE:
        import cv2
        smoothed = cv2.GaussianBlur(g, (0, 0), 3)
        return float(np.std(g.astype(float) - smoothed.astype(float)))
    # Pillow fallback — use a simple box blur
    from PIL import ImageFilter as _Flt
    _ensure_pillow()
    pil_img = _PIL_IMAGE.fromarray(g)
    smoothed = np.array(pil_img.filter(_Flt.GaussianBlur(3)), dtype=np.float64)
    return float(np.std(g.astype(float) - smoothed))  # type: ignore[arg-type]


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
    """Sharpen using standard unsharp mask.  strength=1.0 is neutral.

    cv2 path:  GaussianBlur + addWeighted (unsharp mask).
    Pillow path: ImageEnhance.Sharpness.
    No singularity — safe across the full (0.3, 5.0) range.
    """
    if _CV2_AVAILABLE:
        import cv2
        blurred = cv2.GaussianBlur(arr, (0, 0), 3)
        return cv2.addWeighted(arr, 1.0 + strength, blurred, -strength, 0)

    # Pillow fallback
    _ensure_pillow()
    from PIL import Image as _Img
    from PIL import ImageEnhance
    pil = _Img.fromarray(arr) if arr.ndim == 3 else _Img.fromarray(arr, mode="L")
    return np.array(ImageEnhance.Sharpness(pil).enhance(strength))


def op_contrast(arr: np.ndarray, alpha: float, beta: float = 0) -> np.ndarray:
    """Adjust contrast with linear transform: out = alpha * arr + beta.

    Same formula on both cv2 and Pillow paths for consistent output.
    """
    if _CV2_AVAILABLE:
        import cv2
        return cv2.convertScaleAbs(arr, alpha=alpha, beta=beta)
    # Pillow fallback — same linear transform
    return np.clip(alpha * arr.astype(np.float32) + beta, 0, 255).astype(np.uint8)


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
            if not isinstance(content, str):
                return results
            pts = ret[2] if len(ret) > 2 else None
            bbox = _points_to_bbox(pts) if pts is not None else [0, 0, 0, 0]
            results.append({
                "content": content,
                "bbox": bbox,
                "type": "QRCODE",
                "raw_bytes": content.encode("utf-8").hex(),
            })
    except Exception:
        logger.debug("Failed to decode a single OpenCV result", exc_info=True)
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
