"""Diagnosis and result classification engine.

Produces one of five result codes:
  SUCCESS                  — decoded cleanly
  SUCCESS_WITH_WARNING     — decoded but content is empty/garbled
  RETRYABLE                — quality issue, agent can try enhance / auto_enhance
  NO_QR_FOUND              — no QR code detected at all
  QR_UNRECOVERABLE         — QR found / suspected but image is clear, code damaged

v0.2.0: Replaced tree-based decision with weighted multi-metric fusion.
The quality_score (0=perfect, 1=worst) is the primary signal; thresholds
are calibrated through the T2-1 real-world dataset roadmap.
"""

import os

import numpy as np

from qr_reader.core.quality import (
    analyze_image_quality,
)

# ---------------------------------------------------------------------------
# Thresholds  (all tuneable via env; T2-1 dataset calibration will set
#              data-driven defaults)
# ---------------------------------------------------------------------------

THRESHOLDS = {
    "blur": float(os.getenv("QR_BLUR_THRESHOLD", "50.0")),
}

# Quality-score boundaries for result-code classification.
SCORE_GOOD = 0.18   # below this = all individual metrics are healthy
SCORE_MODERATE = 0.35  # below this = some issues, retryable

# Normalization anchors (tuneable via env; the "perfect" end of each metric's scale)
CONTRAST_PERFECT = float(os.getenv("QR_CONTRAST_PERFECT", "0.50"))
MODULATION_PERFECT = float(os.getenv("QR_MODULATION_PERFECT", "0.70"))
GLARE_MAX = float(os.getenv("QR_GLARE_MAX", "0.30"))
NOISE_MAX = float(os.getenv("QR_NOISE_MAX", "50.0"))
ANGLE_MAX = float(os.getenv("QR_ANGLE_MAX", "30.0"))
LEG_RATIO_MIN = float(os.getenv("QR_LEG_RATIO_MIN", "0.60"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_warning(content: str | None) -> dict | None:
    """Inspect decoded content for quality warnings."""
    if content is None or content == "":
        return {"warning": "empty_content", "detail": "QR code is valid but contains no data"}
    if any(ord(c) < 32 and c not in "\n\r\t" for c in content):
        return {"warning": "garbled",
                "detail": "Content contains non-printable characters, decoding may be corrupt"}
    return None


def _compute_quality_score(
    quality: dict,
    distortion: dict | None = None,
    modulation: float | None = None,
) -> dict:
    """Compute a unified quality score (0=perfect, 1=terrible) from
    all available metrics.

    Each metric is normalised to [0, 1] where 0 = ideal, 1 = worst-case.
    The contribution of each metric to the final score is tracked so the
    caller can identify the primary issue.

    Returns:
        dict with keys: score, contributions, primary_issue.
        contributions is {metric_name: normalised_value}, sorted desc.
    """
    contrib: dict[str, float] = {}

    # ---- blur: high laplacian var = sharp, low = blurry -------------------
    blur_score = quality.get("blur_score", 100)
    if blur_score > 0:
        contrib["blur"] = round(min(1.0, THRESHOLDS["blur"] / blur_score), 4)
    else:
        contrib["blur"] = 1.0

    # ---- contrast: high = good --------------------------------------------
    contrast = quality.get("contrast", 0.5)
    contrib["contrast"] = round(max(0.0, 1.0 - contrast / CONTRAST_PERFECT), 4)

    # ---- glare: high = bad ------------------------------------------------
    glare = quality.get("glare_ratio", 0.0)
    contrib["glare"] = round(min(1.0, glare / GLARE_MAX), 4)

    # ---- noise: high = bad ------------------------------------------------
    noise = quality.get("noise_level", 0.0)
    contrib["noise"] = round(min(1.0, noise / NOISE_MAX), 4)

    # ---- modulation: high = good (ISO 15415) ------------------------------
    if modulation is not None and modulation > 0:
        contrib["modulation"] = round(max(0.0, 1.0 - modulation / MODULATION_PERFECT), 4)
    else:
        contrib["modulation"] = 0.0  # no data → don't penalize

    # ---- distortion: composite of angle + leg-ratio -----------------------
    if distortion is not None:
        angle_dev = distortion.get("right_angle_deviation", 0.0)
        leg_ratio = distortion.get("leg_ratio", 1.0)
        angle_penalty = min(1.0, angle_dev / ANGLE_MAX)
        leg_penalty = max(0.0, min(1.0, (1.0 - leg_ratio) / (1.0 - LEG_RATIO_MIN)))
        contrib["distortion"] = round(0.5 * angle_penalty + 0.5 * leg_penalty, 4)
    else:
        contrib["distortion"] = 0.0  # no data → don't penalize

    # ---- weighted sum (RMS — penalizes extreme single-metric failures) ----
    n_metrics = len(contrib)
    if n_metrics > 0:
        score = round(float(np.sqrt(sum(v * v for v in contrib.values()) / n_metrics)), 4)
    else:
        score = 0.0

    # Sort contributions descending → primary issue is the top one
    sorted_contrib = sorted(contrib.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_contrib[0][0] if sorted_contrib and sorted_contrib[0][1] > 0.1 else None

    return {
        "score": score,
        "contributions": {k: v for k, v in sorted_contrib},
        "primary_issue": primary,
    }


def _build_suggestion(
    primary_issue: str | None,
    quality_score: float,
    decode_success: bool,
) -> str | None:
    """Generate an Agent-targeted suggestion based on the primary issue."""
    if decode_success:
        return None

    suggestions = {
        "blur": (
            "Image is blurry — try re-shooting with better focus, "
            "or call auto_enhance to attempt sharpening recovery"
        ),
        "contrast": (
            "Insufficient contrast — try adjusting lighting and retry, "
            "or call auto_enhance to attempt contrast recovery"
        ),
        "glare": (
            "Glare detected — try adjusting the shooting angle and retry"
        ),
        "noise": (
            "High image noise — try in better lighting, "
            "or call auto_enhance to attempt denoising"
        ),
        "modulation": (
            "Low symbol contrast (ISO 15415 modulation) — the QR code "
            "printing quality may be insufficient; try a different source"
        ),
        "distortion": (
            "Perspective or physical distortion detected — try shooting "
            "from a straighter angle (perpendicular to the code surface)"
        ),
    }

    if primary_issue and primary_issue in suggestions:
        return suggestions[primary_issue]

    if quality_score > SCORE_MODERATE:
        return (
            "Multiple quality issues detected — consider re-shooting "
            "in better conditions (more light, straight angle, steady hand)"
        )

    if quality_score < SCORE_GOOD:
        return (
            "Image quality is acceptable but decoding still failed — "
            "the QR code may be damaged or use an unsupported encoding"
        )

    return "Image has moderate quality issues — try auto_enhance to recover"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def diagnose_single_result(result: dict) -> dict:
    """Annotate a single decode result with a result_code."""
    warning = _check_warning(result.get("content"))
    if warning:
        return {**result, "result_code": "SUCCESS_WITH_WARNING", **warning}
    return {**result, "result_code": "SUCCESS"}


def classify_result(
    img: np.ndarray,
    qr_detected: bool | None,
    decode_success: bool,
    decoded_results: list,
    distortion_info: dict | None = None,
    modulation: float | None = None,
) -> dict:
    """Classify a decode attempt and return structured result information.

    Args:
        img: Source image (RGB/BGR or grayscale).
        qr_detected: Whether any QR-like shapes were found, or None
            when detection is unavailable (light mode / no cv2).
        decode_success: Whether at least one QR was decoded.
        decoded_results: List of raw decode results.
        distortion_info: Optional distortion analysis dict from
            distortion.analyze_distortion().
        modulation: Optional ISO 15415 modulation value (0-1).

    Returns:
        dict with keys: result_code, analysis, suggestion, results (if success).
    """
    quality = analyze_image_quality(img)
    fusion = _compute_quality_score(quality, distortion_info, modulation)
    qscore = fusion["score"]
    primary = fusion["primary_issue"]

    # ---- Success path (decode worked, regardless of quality) ---------------
    if decode_success:
        annotated = [diagnose_single_result(r) for r in decoded_results]
        has_warning = any(r["result_code"] == "SUCCESS_WITH_WARNING" for r in annotated)
        analysis: dict = {
            "total_detected": len(annotated),
            "quality": quality,
            "quality_score": qscore,
        }
        if distortion_info is not None:
            analysis["distortion"] = distortion_info
        if modulation is not None:
            analysis["modulation"] = modulation
        return {
            "result_code": "SUCCESS_WITH_WARNING" if has_warning else "SUCCESS",
            "results": annotated,
            "analysis": analysis,
            "suggestion": None,
        }

    # ---- Decode failed — classify by quality + detection ------------------

    # Build analysis payload
    analysis = {
        "quality": quality,
        "quality_score": qscore,
        "contributions": fusion["contributions"],
    }
    if primary:
        analysis["primary_issue"] = primary
    if distortion_info is not None:
        analysis["distortion"] = distortion_info
    if modulation is not None:
        analysis["modulation"] = modulation

    suggestion = _build_suggestion(primary, qscore, decode_success)

    # -- No QR detected ----------------------------------------------------
    if qr_detected is False:
        # OpenCV explicitly found no QR-like regions. A missing finder
        # pattern means there is no QR code in the image — not a degraded
        # one — so enhancement cannot recover anything. Treating poor
        # quality as RETRYABLE here wastes an agent turn on images that
        # contain no code (e.g. a blank or scenery photo).
        #
        # Quality issues are still surfaced in `suggestion` (blur/contrast/
        # glare guidance), so an agent can decide to call auto_enhance
        # manually when it suspects a code may be present.
        return {
            "result_code": "NO_QR_FOUND",
            "analysis": analysis,
            "suggestion": suggestion or "No QR code detected in the image",
        }

    # -- Detection unavailable (light mode) --------------------------------
    if qr_detected is None:
        # In light mode, we can't confirm QR existence.
        # Still RETRYABLE — auto_enhance may help.
        if qscore < SCORE_GOOD:
            # Image is good but decode failed → could be no QR at all
            return {
                "result_code": "RETRYABLE",
                "analysis": analysis,
                "suggestion": (
                    "Image quality is acceptable but no QR decoded. "
                    "Without OpenCV (light install), cannot detect whether "
                    "QR codes exist. Install 'full' extras for detector-based "
                    "diagnosis, or try auto_enhance."
                ),
            }
        return {
            "result_code": "RETRYABLE",
            "analysis": analysis,
            "suggestion": suggestion,
        }

    # -- QR detected but decode failed -------------------------------------
    if qscore < SCORE_GOOD:
        # Clean image, QR found, still can't decode → permanently damaged
        return {
            "result_code": "QR_UNRECOVERABLE",
            "analysis": analysis,
            "suggestion": (
                "QR code detected, image quality is acceptable, but decoding "
                "failed — the QR code may be damaged, use an unsupported "
                "encoding, or be too small (< 21×21 modules)"
            ),
        }

    # Moderate / poor quality → retryable
    return {
        "result_code": "RETRYABLE",
        "analysis": analysis,
        "suggestion": suggestion,
    }
