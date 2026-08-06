"""Tests for diagnosis module — mocks quality to isolate classification logic."""

import numpy as np
import pytest
from qr_reader.core.diagnosis import (
    _check_warning,
    diagnose_single_result,
    classify_result,
)


# ---------------------------------------------------------------------------
# _check_warning
# ---------------------------------------------------------------------------

class TestCheckWarning:
    def test_none_content(self):
        w = _check_warning(None)
        assert w is not None
        assert w["warning"] == "empty_content"

    def test_empty_string(self):
        w = _check_warning("")
        assert w is not None
        assert w["warning"] == "empty_content"

    def test_normal_content(self):
        assert _check_warning("https://example.com") is None

    def test_control_characters_in_content(self):
        w = _check_warning("hello\x00world")
        assert w is not None
        assert w["warning"] == "garbled"

    def test_newline_tab_are_ok(self):
        """\\n \\r \\t are allowed control chars."""
        assert _check_warning("line1\nline2\r\ttab") is None

    def test_chinese_text(self):
        assert _check_warning("你好世界") is None


# ---------------------------------------------------------------------------
# diagnose_single_result
# ---------------------------------------------------------------------------

class TestDiagnoseSingleResult:
    def test_normal_result_returns_success(self):
        r = diagnose_single_result({"content": "https://a.com", "type": "QRCODE"})
        assert r["result_code"] == "SUCCESS"

    def test_empty_content_returns_warning(self):
        r = diagnose_single_result({"content": "", "type": "QRCODE"})
        assert r["result_code"] == "SUCCESS_WITH_WARNING"
        assert r["warning"] == "empty_content"


# ---------------------------------------------------------------------------
# classify_result — five branches
# ---------------------------------------------------------------------------

GOOD_QUALITY = {
    "blur_score": 200.0,
    "contrast": 0.8,
    "glare_ratio": 0.1,
    "noise_level": 5.0,
}
BLUR_QUALITY = {
    "blur_score": 20.0,
    "contrast": 0.8,
    "glare_ratio": 0.1,
    "noise_level": 5.0,
}
DARK_QUALITY = {
    "blur_score": 200.0,
    "contrast": 0.05,
    "glare_ratio": 0.1,
    "noise_level": 5.0,
}
GLARE_QUALITY = {
    "blur_score": 200.0,
    "contrast": 0.8,
    "glare_ratio": 0.5,
    "noise_level": 5.0,
}


class TestClassifyResult:
    def test_no_qr_blur(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=BLUR_QUALITY)
        info = classify_result(img=None, qr_detected=False, decode_success=False, decoded_results=[])
        assert info["result_code"] == "NO_QR_FOUND"
        assert info["analysis"]["primary_issue"] == "too_blur"

    def test_no_qr_dark(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=DARK_QUALITY)
        info = classify_result(img=None, qr_detected=False, decode_success=False, decoded_results=[])
        assert info["result_code"] == "NO_QR_FOUND"
        assert info["analysis"]["primary_issue"] == "too_dark"

    def test_no_qr_generic(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        info = classify_result(img=None, qr_detected=False, decode_success=False, decoded_results=[])
        assert info["result_code"] == "NO_QR_FOUND"
        assert info["analysis"]["primary_issue"] == "no_qr"

    def test_found_but_blur_retryable(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=BLUR_QUALITY)
        info = classify_result(img=None, qr_detected=True, decode_success=False, decoded_results=[])
        assert info["result_code"] == "RETRYABLE"
        assert info["analysis"]["primary_issue"] == "blur"

    def test_found_but_glare_retryable(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GLARE_QUALITY)
        info = classify_result(img=None, qr_detected=True, decode_success=False, decoded_results=[])
        assert info["result_code"] == "RETRYABLE"
        assert info["analysis"]["primary_issue"] == "glare"

    def test_found_but_unrecoverable(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        info = classify_result(img=None, qr_detected=True, decode_success=False, decoded_results=[])
        assert info["result_code"] == "QR_UNRECOVERABLE"

    def test_success_plain(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        results = [{"content": "https://x.com", "type": "QRCODE"}]
        info = classify_result(img=None, qr_detected=True, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS"
        assert info["suggestion"] is None

    def test_success_with_warning(self, mocker):
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        results = [{"content": "", "type": "QRCODE"}]
        info = classify_result(img=None, qr_detected=True, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS_WITH_WARNING"

    def test_qr_detected_none_decode_success(self, mocker):
        """Light mode — no detection info but decode succeeded."""
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        results = [{"content": "https://x.com", "type": "QRCODE"}]
        info = classify_result(img=None, qr_detected=None, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS"

    def test_qr_detected_none_decode_fail_blur(self, mocker):
        """Light mode — decode failed, blur detected."""
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=BLUR_QUALITY)
        info = classify_result(img=None, qr_detected=None, decode_success=False, decoded_results=[])
        assert info["result_code"] == "RETRYABLE"
        assert "blur" in info["analysis"]["primary_issue"]

    def test_qr_detected_none_decode_fail_glare(self, mocker):
        """Light mode — decode failed, glare detected."""
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GLARE_QUALITY)
        info = classify_result(img=None, qr_detected=None, decode_success=False, decoded_results=[])
        assert info["result_code"] == "RETRYABLE"
        assert "glare" in info["analysis"]["primary_issue"]

    def test_qr_detected_none_decode_fail_unknown(self, mocker):
        """Light mode — decode failed, image looks fine."""
        mocker.patch("qr_reader.core.diagnosis.analyze_image_quality", return_value=GOOD_QUALITY)
        info = classify_result(img=None, qr_detected=None, decode_success=False, decoded_results=[])
        assert info["result_code"] == "RETRYABLE"
        assert info["analysis"]["primary_issue"] == "unknown"
