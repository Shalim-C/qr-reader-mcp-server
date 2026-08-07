"""QR code geometric distortion analysis.

Detects perspective / physical deformation by analyzing the three
Finder Patterns as reported by OpenCV QRCodeDetector.  In light mode
(no cv2) returns None for all metrics — the diagnosis engine handles
this as "unknown" (same pattern as qr_detect).

Metrics:
  right_angle_deviation  — degrees from 90° at the right-angle corner
  leg_ratio              — shorter / longer leg at right-angle corner (1.0 = square)
  diagonal_ratio         — shorter / longer quadrilateral diagonal (1.0 = rectangle)
  is_distorted           — True when any metric exceeds threshold
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("qr-reader-mcp.distortion")

# ---------------------------------------------------------------------------
# Thresholds (calibrated against ISO/IEC 15415 grid non-uniformity
# and axial non-uniformity tolerance ranges; tune once real-world
# dataset is available — T2-1 roadmap)
# ---------------------------------------------------------------------------
ANGLE_THRESHOLD = 15.0     # degrees — below this is "acceptable perspective"
LEG_RATIO_THRESHOLD = 0.7  # shorter/longer — below this is significant skew
DIAG_RATIO_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_distortion(
    arr: np.ndarray,
    bbox: list[int] | None = None,
) -> dict | None:
    """Analyze geometric distortion of a QR code.

    Uses OpenCV QRCodeDetector.detect() to locate the three finder
    patterns, then computes angular / ratio metrics.

    Args:
        arr: Image (H×W or H×W×C, BGR or grayscale — cv2 tolerant).
        bbox: Optional [x, y, w, h] to crop before detection.
            Speeds up detection on large images.

    Returns:
        dict with keys right_angle_deviation, leg_ratio,
        diagonal_ratio, is_distorted, suggestion; or None when
        detection is unavailable (light mode) or finder patterns
        cannot be reliably located.
    """
    from qr_reader.core.ops import is_cv2_available

    if not is_cv2_available():
        logger.debug("Distortion analysis unavailable (cv2 not installed)")
        return None

    import cv2

    # -- Optional region crop ------------------------------------------------
    roi = arr
    offset_x, offset_y = 0, 0
    if bbox is not None:
        x, y, w, h = bbox
        roi = arr[y:y + h, x:x + w]
        offset_x, offset_y = x, y

    # -- Finder pattern detection -------------------------------------------
    detector = cv2.QRCodeDetector()
    gray = _to_gray(roi)
    retval, points = detector.detect(gray)

    if not retval or points is None:
        logger.debug("QRCodeDetector.detect() returned no finder patterns")
        return None

    # OpenCV returns corners as (1, 4, 2) — corners of the QR *symbol*
    # (not just finder patterns). We reconstruct finder-pattern centers
    # from the four corners.
    try:
        corners = points.reshape(4, 2)
    except ValueError:
        logger.debug("Unexpected points shape from QRCodeDetector: %s", points.shape)
        return None

    # Finder-pattern centers are approximated at 1/6 from each aligned
    # corner.  Corner ordering (OpenCV): top-left, top-right,
    # bottom-right, bottom-left.
    fp_centers = _finder_centers_from_corners(corners, offset_x, offset_y)

    return _compute_metrics(fp_centers)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_gray(arr: np.ndarray) -> np.ndarray:
    """Convert to grayscale, passthrough if already 2-D."""
    if arr.ndim == 2:
        return arr
    import cv2
    return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)


def _finder_centers_from_corners(
    corners: np.ndarray,
    offset_x: int = 0,
    offset_y: int = 0,
) -> np.ndarray:
    """Approximate three finder-pattern centers from the four QR corners.

    OpenCV returns the four corners of the QR symbol bounding quadrilateral
    (top-left, top-right, bottom-right, bottom-left).  Each finder pattern
    sits at roughly 1/6 of the way along both adjacent edges from its corner.

    Returns 3×2 ndarray of (x, y) centers, offset applied.
    """
    tl, tr, br, bl = corners  # top-left, top-right, bottom-right, bottom-left

    # Finder pattern at top-left: 1/6 along top edge + 1/6 along left edge
    fp_tl_x = tl[0] + (tr[0] - tl[0]) / 6 + (bl[0] - tl[0]) / 6
    fp_tl_y = tl[1] + (tr[1] - tl[1]) / 6 + (bl[1] - tl[1]) / 6

    # Finder pattern at top-right: 1/6 along top edge (reverse) + 1/6 along right edge
    fp_tr_x = tr[0] + (tl[0] - tr[0]) / 6 + (br[0] - tr[0]) / 6
    fp_tr_y = tr[1] + (tl[1] - tr[1]) / 6 + (br[1] - tr[1]) / 6

    # Finder pattern at bottom-left: 1/6 along bottom edge + 1/6 along left edge (reverse)
    fp_bl_x = bl[0] + (br[0] - bl[0]) / 6 + (tl[0] - bl[0]) / 6
    fp_bl_y = bl[1] + (br[1] - bl[1]) / 6 + (tl[1] - bl[1]) / 6

    centers = np.array([
        [fp_tl_x + offset_x, fp_tl_y + offset_y],
        [fp_tr_x + offset_x, fp_tr_y + offset_y],
        [fp_bl_x + offset_x, fp_bl_y + offset_y],
    ], dtype=np.float64)

    return centers


def _compute_metrics(points: np.ndarray) -> dict:
    """Compute distortion metrics from three finder-pattern centers.

    Args:
        points: 3×2 ndarray — finder pattern centers (x, y).

    Returns:
        dict with right_angle_deviation, leg_ratio, diagonal_ratio,
        is_distorted, suggestion.
    """
    # -- Three sides of the triangle -----------------------------------------
    d01 = float(np.linalg.norm(points[0] - points[1]))
    d12 = float(np.linalg.norm(points[1] - points[2]))
    d20 = float(np.linalg.norm(points[2] - points[0]))

    # Guard: degenerate triangle
    if d01 < 2 or d12 < 2 or d20 < 2:
        return {
            "right_angle_deviation": 90.0,
            "leg_ratio": 0.0,
            "diagonal_ratio": 0.0,
            "is_distorted": True,
            "suggestion": (
                "Finder pattern triangle is degenerate — QR code may be "
                "too small, severely damaged, or not a QR code"
            ),
        }

    # -- Identify the right-angle corner (longest side = hypotenuse) ---------
    edges = sorted([(d01, 0, 1), (d12, 1, 2), (d20, 2, 0)],
                   key=lambda e: e[0], reverse=True)
    _hyp, ca, cb = edges[0]          # hypotenuse endpoints
    right_idx = 3 - ca - cb             # right-angle corner index

    # -- Leg ratio -----------------------------------------------------------
    leg_a = float(np.linalg.norm(points[right_idx] - points[ca]))
    leg_b = float(np.linalg.norm(points[right_idx] - points[cb]))
    if leg_a < 1 or leg_b < 1:
        leg_ratio = 0.0
    else:
        leg_ratio = round(min(leg_a, leg_b) / max(leg_a, leg_b), 4)

    # -- Right-angle deviation -----------------------------------------------
    va = points[ca] - points[right_idx]
    vb = points[cb] - points[right_idx]
    cos_angle = float(np.dot(va, vb) / (leg_a * leg_b))
    # Clamp to [-1, 1] (floating point noise near boundary)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    angle_dev = round(abs(90.0 - float(np.degrees(np.arccos(cos_angle)))), 2)

    # -- Diagonal ratio (perspective skew, comparing quadrilateral diagonals) -
    # The fourth point (finder pattern at bottom-right does not exist, but
    # we estimate it from the two-leg right triangle: fp_br ≈ fp_tr + fp_bl − fp_tl
    fp_br = points[1] + points[2] - points[0]
    diag_1 = float(np.linalg.norm(points[0] - fp_br))
    diag_2 = float(np.linalg.norm(points[1] - points[2]))
    if diag_1 < 1 or diag_2 < 1:
        diag_ratio = 0.0
    else:
        diag_ratio = round(min(diag_1, diag_2) / max(diag_1, diag_2), 4)

    # -- Judgment ------------------------------------------------------------
    distorted = (
        angle_dev > ANGLE_THRESHOLD
        or leg_ratio < LEG_RATIO_THRESHOLD
        or diag_ratio < DIAG_RATIO_THRESHOLD
    )

    # Build human-readable suggestion
    reasons: list[str] = []
    if angle_dev > ANGLE_THRESHOLD:
        reasons.append(f"right-angle deviation {angle_dev}° exceeds {ANGLE_THRESHOLD}°")
    if leg_ratio < LEG_RATIO_THRESHOLD:
        reasons.append(f"leg ratio {leg_ratio} below {LEG_RATIO_THRESHOLD}")
    if diag_ratio < DIAG_RATIO_THRESHOLD:
        reasons.append(f"diagonal ratio {diag_ratio} below {DIAG_RATIO_THRESHOLD}")

    return {
        "right_angle_deviation": angle_dev,
        "leg_ratio": leg_ratio,
        "diagonal_ratio": diag_ratio,
        "is_distorted": distorted,
        "suggestion": (
            "Perspective distortion detected — try a straighter angle and retry. "
            + "; ".join(reasons)
        ) if distorted else None,
    }
