"""Diagnosis and result classification engine.

Produces one of five result codes:
  SUCCESS                  — decoded cleanly
  SUCCESS_WITH_WARNING     — decoded but content is empty/garbled
  RETRYABLE                — quality issue, agent can try enhance_and_decode
  NO_QR_FOUND              — no QR code detected at all
  QR_UNRECOVERABLE         — QR found but permanently unreadable
"""

import os

import numpy as np
from qr_reader.core.quality import (
    analyze_image_quality,
    is_too_blur,
    is_low_contrast,
    has_glare,
)

THRESHOLDS = {
    "blur": float(os.getenv("QR_BLUR_THRESHOLD", "50.0")),
    "contrast": float(os.getenv("QR_CONTRAST_THRESHOLD", "0.20")),
    "glare": float(os.getenv("QR_GLARE_THRESHOLD", "0.10")),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_warning(content: str | None) -> dict | None:
    """Inspect decoded content for quality warnings."""
    if content is None or content == "":
        return {"warning": "empty_content", "detail": "QR code is valid but contains no data"}
    # Non-printable characters (excluding common whitespace) indicate
    # corrupt or binary data.
    if any(ord(c) < 32 and c not in "\n\r\t" for c in content):
        return {"warning": "garbled", "detail": "Content contains non-printable characters, decoding may be corrupt"}
    return None


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
) -> dict:
    """Classify a decode attempt and return structured result information.

    Args:
        img: Source image (BGR or grayscale).
        qr_detected: Whether any QR-like shapes were found, or None
            when detection is unavailable (light mode / no cv2).
        decode_success: Whether at least one QR was decoded.
        decoded_results: List of raw decode results.

    Returns:
        dict with keys: result_code, analysis, suggestion, results (if success).
    """
    # -- Detection unavailable (light mode) — quality still informative -----
    if qr_detected is None:
        quality = analyze_image_quality(img)
        if decode_success:
            annotated = [diagnose_single_result(r) for r in decoded_results]
            has_warning = any(r["result_code"] == "SUCCESS_WITH_WARNING" for r in annotated)
            return {
                "result_code": "SUCCESS_WITH_WARNING" if has_warning else "SUCCESS",
                "results": annotated,
                "analysis": {"total_detected": len(annotated), "quality": quality},
                "suggestion": None,
            }
        # Decode failed but we can't tell if QR exists (no cv2)
        if is_too_blur(quality["blur_score"], THRESHOLDS["blur"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "blur", "quality": quality},
                "suggestion": "Image is blurry — try re-shooting with better focus, or install cv2 for finder-pattern detection",
            }
        if has_glare(quality["glare_ratio"], THRESHOLDS["glare"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "glare", "quality": quality},
                "suggestion": "Glare detected — try adjusting the angle and retry",
            }
        return {
            "result_code": "RETRYABLE",
            "analysis": {"primary_issue": "unknown", "quality": quality},
            "suggestion": "No QR code decoded. Without OpenCV (light install), the server cannot detect whether QR codes exist in the image. The image may contain no QR code, or may need enhancement — install 'full' extras (opencv-python) for detector-based diagnosis.",
        }

    quality = analyze_image_quality(img)

    # -- No QR found --------------------------------------------------------
    if not qr_detected:
        if is_too_blur(quality["blur_score"], THRESHOLDS["blur"]):
            return {
                "result_code": "NO_QR_FOUND",
                "analysis": {"primary_issue": "too_blur", "quality": quality},
                "suggestion": "Image is too blurry to locate QR codes — try re-shooting with better focus",
            }
        if is_low_contrast(quality["contrast"], THRESHOLDS["contrast"]):
            return {
                "result_code": "NO_QR_FOUND",
                "analysis": {"primary_issue": "too_dark", "quality": quality},
                "suggestion": "Image contrast is too low — try adjusting lighting and re-shooting",
            }
        return {
            "result_code": "NO_QR_FOUND",
            "analysis": {"primary_issue": "no_qr", "quality": quality},
            "suggestion": "No QR code detected in the image — verify the image contains a QR code",
        }

    # -- QR found but could not decode --------------------------------------
    if not decode_success:
        if is_too_blur(quality["blur_score"], THRESHOLDS["blur"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "blur", "quality": quality},
                "suggestion": "QR code region is blurry — try cropping and enlarging, then retry with enhance_and_decode",
            }
        if has_glare(quality["glare_ratio"], THRESHOLDS["glare"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "glare", "quality": quality},
                "suggestion": "Glare is covering the QR code — try adjusting the shooting angle and retry",
            }
        if is_low_contrast(quality["contrast"], THRESHOLDS["contrast"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "low_contrast", "quality": quality},
                "suggestion": "Insufficient contrast — try adjusting lighting and retry",
            }
        return {
            "result_code": "QR_UNRECOVERABLE",
            "analysis": {"primary_issue": "invalid_encoding", "quality": quality},
            "suggestion": "Image is clear but decoding still failed — QR code may be damaged or use an unsupported encoding",
        }

    # -- Success (possibly with warnings) -----------------------------------
    annotated = [diagnose_single_result(r) for r in decoded_results]
    has_warning = any(r["result_code"] == "SUCCESS_WITH_WARNING" for r in annotated)
    overall_code = "SUCCESS_WITH_WARNING" if has_warning else "SUCCESS"

    return {
        "result_code": overall_code,
        "results": annotated,
        "analysis": {"total_detected": len(annotated), "quality": quality},
        "suggestion": None,
    }
