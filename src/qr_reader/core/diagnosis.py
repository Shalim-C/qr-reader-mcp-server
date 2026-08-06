"""Diagnosis and result classification engine.

Produces one of five result codes:
  SUCCESS                  — decoded cleanly
  SUCCESS_WITH_WARNING     — decoded but content is empty/garbled
  RETRYABLE                — quality issue, agent can try enhance_and_decode
  NO_QR_FOUND              — no QR code detected at all
  QR_UNRECOVERABLE         — QR found but permanently unreadable
"""

import numpy as np
from qr_reader.core.quality import (
    analyze_image_quality,
    is_too_blur,
    is_low_contrast,
    has_glare,
)

THRESHOLDS = {
    "blur": 50.0,
    "contrast": 0.15,
    "glare": 0.3,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_warning(content: str | None) -> dict | None:
    """Inspect decoded content for quality warnings."""
    if content is None or content == "":
        return {"warning": "empty_content", "detail": "QR code is valid but contains no data"}
    try:
        content.encode("utf-8")
    except UnicodeEncodeError:
        return {"warning": "garbled", "detail": "Content contains non-UTF-8 characters, possibly binary data or garbled text"}
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
    qr_detected: bool,
    decode_success: bool,
    decoded_results: list,
) -> dict:
    """Classify a decode attempt and return structured result information.

    Args:
        img: Source image (BGR or grayscale).
        qr_detected: Whether any QR-like shapes were found.
        decode_success: Whether at least one QR was decoded.
        decoded_results: List of raw decode results.

    Returns:
        dict with keys: result_code, analysis, suggestion, results (if success).
    """
    quality = analyze_image_quality(img)

    # -- No QR found --------------------------------------------------------
    if not qr_detected:
        if is_too_blur(quality["blur_score"]):
            return {
                "result_code": "NO_QR_FOUND",
                "analysis": {"primary_issue": "too_blur", "quality": quality},
                "suggestion": "Image is too blurry to locate QR codes — try re-shooting with better focus",
            }
        if is_low_contrast(quality["contrast"]):
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
        if is_too_blur(quality["blur_score"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "blur", "quality": quality},
                "suggestion": "QR code region is blurry — try cropping and enlarging, then retry with enhance_and_decode",
            }
        if has_glare(quality["glare_ratio"]):
            return {
                "result_code": "RETRYABLE",
                "analysis": {"primary_issue": "glare", "quality": quality},
                "suggestion": "Glare is covering the QR code — try adjusting the shooting angle and retry",
            }
        if is_low_contrast(quality["contrast"]):
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
