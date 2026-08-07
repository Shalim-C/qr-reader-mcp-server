"""Tests for decoder module.

Tests both backends independently:
  - pyzbar path  (mock _decode_with_pyzbar + set _PYZBAR_AVAILABLE=True)
  - OpenCV path  (mock _decode_with_opencv + set _PYZBAR_AVAILABLE=False)
  - Fallback path (pyzbar returns empty → OpenCV kicks in)
"""

import numpy as np

from qr_reader.core.decoder import (
    clamp_bbox,
    decode_qr_from_image,
    decode_qr_from_region,
    detect_qr_regions,
)
from qr_reader.core.ops import _points_to_bbox

# ---------------------------------------------------------------------------
# Fake decoded result — mimics pyzbar output format
# ---------------------------------------------------------------------------

def _fake_result(content: str, qr_type: str = "QRCODE",
                 x=0, y=0, w=100, h=100) -> dict:
    """Return a dict matching the real decode output format."""
    return {
        "content": content if content else None,
        "bbox": [x, y, w, h],
        "type": qr_type,
        "raw_bytes": content.encode("utf-8").hex() if content else "",
    }


# ---------------------------------------------------------------------------
# decode_qr_from_image — pyzbar path
# ---------------------------------------------------------------------------

class TestDecodeQrFromImagePyzbar:
    def test_empty_image_no_results(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar", return_value=[])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert results == []

    def test_single_qr_decoded(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar",
                      return_value=[_fake_result("https://example.com")])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 1
        assert results[0]["content"] == "https://example.com"
        assert results[0]["type"] == "QRCODE"
        assert len(results[0]["bbox"]) == 4

    def test_all_barcode_types_decoded(self, mocker, monkeypatch):
        """EAN13 and QRCODE both decoded — no type filtering."""
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar", return_value=[
            _fake_result("qr content", "QRCODE"),
            _fake_result("123456789012", "EAN13"),
        ])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 2

    def test_multiple_qr_codes(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar", return_value=[
            _fake_result("first", "QRCODE", 0, 0, 50, 50),
            _fake_result("second", "QR_CODE", 100, 100, 50, 50),
        ])
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 2

    def test_none_content_on_empty_decode(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar",
                      return_value=[_fake_result("")])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert results[0]["content"] is None

    def test_pyzbar_empty_falls_back_to_opencv(self, mocker, monkeypatch):
        """Pyzbar returns [] → OpenCV fallback kicks in."""
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar", return_value=[])
        mocker.patch("qr_reader.core.ops.qr_decode_opencv",
                      return_value=[_fake_result("opencv-fallback")])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 1
        assert results[0]["content"] == "opencv-fallback"


# ---------------------------------------------------------------------------
# decode_qr_from_image — OpenCV path (pyzbar unavailable)
# ---------------------------------------------------------------------------

class TestDecodeQrFromImageOpencv:
    def test_opencv_used_when_pyzbar_unavailable(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", False)
        mocker.patch("qr_reader.core.ops.qr_decode_opencv",
                      return_value=[_fake_result("opencv-only")])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 1
        assert results[0]["content"] == "opencv-only"

    def test_opencv_empty_when_nothing_found(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", False)
        mocker.patch("qr_reader.core.ops.qr_decode_opencv", return_value=[])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert results == []


# ---------------------------------------------------------------------------
# decode_qr_from_region
# ---------------------------------------------------------------------------

class TestDecodeQrFromRegion:
    def test_crops_and_decodes(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar",
                      return_value=[_fake_result("cropped-content")])
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        results = decode_qr_from_region(img, [50, 50, 100, 100])
        assert len(results) == 1
        assert results[0]["content"] == "cropped-content"

    def test_bbox_clamped_to_image_bounds(self, mocker, monkeypatch):
        monkeypatch.setattr("qr_reader.core.decoder._PYZBAR_AVAILABLE", True)
        mocker.patch("qr_reader.core.decoder._decode_with_pyzbar",
                      return_value=[_fake_result("clamped")])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_region(img, [-10, -10, 200, 200])
        assert len(results) == 1

    def test_zero_or_negative_size_returns_empty(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert decode_qr_from_region(img, [500, 500, 100, 100]) == []


# ---------------------------------------------------------------------------
# detect_qr_regions
# ---------------------------------------------------------------------------

class TestDetectQrRegions:
    def test_detected_when_finder_patterns_found(self, mocker):
        mocker.patch("qr_reader.core.ops.qr_detect", return_value=True)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert detect_qr_regions(img) is True

    def test_not_detected_when_nothing_found(self, mocker):
        mocker.patch("qr_reader.core.ops.qr_detect", return_value=False)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        assert detect_qr_regions(img) is False

    def test_accepts_grayscale_input(self, mocker):
        mocker.patch("qr_reader.core.ops.qr_detect", return_value=True)
        gray = np.zeros((100, 100), dtype=np.uint8)
        assert detect_qr_regions(gray) is True

    def test_returns_none_when_detection_unavailable(self, mocker):
        """In light mode (no cv2), qr_detect returns None → detect_qr_regions returns None."""
        mocker.patch("qr_reader.core.ops.qr_detect", return_value=None)
        gray = np.zeros((100, 100), dtype=np.uint8)
        assert detect_qr_regions(gray) is None


# ---------------------------------------------------------------------------
# clamp_bbox
# ---------------------------------------------------------------------------

class TestClampBbox:
    IMG = (200, 300, 3)

    def test_within_bounds_passes_through(self):
        x, y, w, h = clamp_bbox([10, 20, 50, 60], self.IMG)
        assert (x, y, w, h) == (10, 20, 50, 60)

    def test_negative_coordinates_snap_to_zero(self):
        x, y, w, h = clamp_bbox([-5, -10, 50, 50], self.IMG)
        assert (x, y, w, h) == (0, 0, 50, 50)

    def test_overflow_clamped_to_image_bounds(self):
        x, y, w, h = clamp_bbox([280, 180, 50, 50], self.IMG)
        assert (x, y, w, h) == (280, 180, 20, 20)

    def test_zero_size_bbox_allowed(self):
        x, y, w, h = clamp_bbox([10, 10, 0, 0], self.IMG)
        assert (x, y, w, h) == (10, 10, 0, 0)

    def test_completely_outside_image_clamped_to_edge(self):
        """Before: outside image → negative sizes. Now: properly clamped to edge."""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        x, y, w, h = clamp_bbox([500, 500, 100, 100], img.shape)
        # x and y are clamped to image bounds
        assert (x, y) == (9, 9)
        # w and h are reduced to fit within remaining space
        assert w == 1 and h == 1


# ---------------------------------------------------------------------------
# _points_to_bbox
# ---------------------------------------------------------------------------

class TestPointsToBbox:
    def test_valid_quadrilateral(self):
        pts = np.array([[[10, 20]], [[50, 20]], [[50, 60]], [[10, 60]]], dtype=np.float32)
        bbox = _points_to_bbox(pts)
        assert bbox == [10, 20, 40, 40]

    def test_rotated_quadrilateral(self):
        pts = np.array([[[30, 10]], [[60, 30]], [[30, 50]], [[0, 30]]], dtype=np.float32)
        bbox = _points_to_bbox(pts)
        assert bbox == [0, 10, 60, 40]

    def test_none_returns_zero_bbox(self):
        assert _points_to_bbox(None) == [0, 0, 0, 0]

    def test_empty_returns_zero_bbox(self):
        assert _points_to_bbox(np.array([])) == [0, 0, 0, 0]
