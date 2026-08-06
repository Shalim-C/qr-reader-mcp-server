"""Tests for classification module (does not require pyzbar)."""

import numpy as np
import pytest
from qr_reader.core.diagnosis import diagnose_single_result, classify_result


class TestDiagnoseSingleResult:
    def test_clean_content_returns_success(self):
        result = {"content": "https://example.com", "bbox": [0, 0, 100, 100], "type": "QRCODE"}
        annotated = diagnose_single_result(result)
        assert annotated["result_code"] == "SUCCESS"

    def test_none_content_returns_warning(self):
        result = {"content": None, "bbox": [0, 0, 100, 100], "type": "QRCODE"}
        annotated = diagnose_single_result(result)
        assert annotated["result_code"] == "SUCCESS_WITH_WARNING"
        assert annotated["warning"] == "empty_content"

    def test_empty_content_returns_warning(self):
        result = {"content": "", "bbox": [0, 0, 100, 100], "type": "QRCODE"}
        annotated = diagnose_single_result(result)
        assert annotated["result_code"] == "SUCCESS_WITH_WARNING"
        assert annotated["warning"] == "empty_content"

    def test_control_characters_returns_warning(self):
        result = {"content": "abc\x00def", "bbox": [0, 0, 100, 100], "type": "QRCODE"}
        annotated = diagnose_single_result(result)
        assert annotated["result_code"] == "SUCCESS_WITH_WARNING"
        assert annotated["warning"] == "garbled"

    def test_common_whitespace_is_not_garbled(self):
        result = {"content": "line1\nline2\tindented", "bbox": [0, 0, 100, 100], "type": "QRCODE"}
        annotated = diagnose_single_result(result)
        assert annotated["result_code"] == "SUCCESS"


class TestDiagnoseFailure:
    @pytest.fixture
    def black_img(self):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    @pytest.fixture
    def white_img(self):
        return np.full((100, 100, 3), 255, dtype=np.uint8)

    def test_no_qr_detected_blurry(self, black_img):
        info = classify_result(black_img, qr_detected=False, decode_success=False, decoded_results=[])
        assert info["result_code"] == "NO_QR_FOUND"

    def test_qr_detected_but_decode_failed(self, black_img):
        info = classify_result(black_img, qr_detected=True, decode_success=False, decoded_results=[])
        assert info["result_code"] in ("RETRYABLE", "QR_UNRECOVERABLE")

    def test_decode_success_with_clean_results(self, black_img):
        results = [{"content": "hello", "bbox": [0, 0, 50, 50], "type": "QRCODE"}]
        info = classify_result(black_img, qr_detected=True, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS"
        assert "results" in info
        assert len(info["results"]) == 1

    def test_decode_success_with_warning(self, black_img):
        results = [{"content": "", "bbox": [0, 0, 50, 50], "type": "QRCODE"}]
        info = classify_result(black_img, qr_detected=True, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS_WITH_WARNING"

    def test_mixed_results(self, black_img):
        results = [
            {"content": "good", "bbox": [0, 0, 50, 50], "type": "QRCODE"},
            {"content": "", "bbox": [100, 100, 50, 50], "type": "QRCODE"},
        ]
        info = classify_result(black_img, qr_detected=True, decode_success=True, decoded_results=results)
        assert info["result_code"] == "SUCCESS_WITH_WARNING"
        assert len(info["results"]) == 2

    def test_analysis_contains_quality(self, black_img):
        info = classify_result(black_img, qr_detected=False, decode_success=False, decoded_results=[])
        assert "quality" in info["analysis"]
        assert set(info["analysis"]["quality"].keys()) == {
            "blur_score", "contrast", "glare_ratio", "noise_level",
        }

    def test_suggestion_in_failure(self, black_img):
        info = classify_result(black_img, qr_detected=False, decode_success=False, decoded_results=[])
        assert info["suggestion"] is not None
        assert len(info["suggestion"]) > 0
