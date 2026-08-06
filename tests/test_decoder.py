"""Tests for decoder module — mocks pyzbar to avoid system zbar dependency."""

from collections import namedtuple
import numpy as np
import pytest
from qr_reader.core.decoder import (
    decode_qr_from_image,
    decode_qr_from_region,
)


# ---------------------------------------------------------------------------
# Fake pyzbar objects — mimic real pyzbar.Decoded structure
# ---------------------------------------------------------------------------

Rect = namedtuple("Rect", ["left", "top", "width", "height"])


class FakeDecoded:
    def __init__(self, content: str, qr_type: str = "QRCODE", x=0, y=0, w=100, h=100):
        self.data = content.encode("utf-8")
        self.type = qr_type
        self.rect = Rect(left=x, top=y, width=w, height=h)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDecodeQrFromImage:
    def test_empty_image_no_results(self, mocker):
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert results == []

    def test_single_qr_decoded(self, mocker):
        fake = FakeDecoded("https://example.com")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 1
        assert results[0]["content"] == "https://example.com"
        assert results[0]["type"] == "QRCODE"
        assert len(results[0]["bbox"]) == 4

    def test_skips_non_qr_barcodes(self, mocker):
        fake_qr = FakeDecoded("qr content", "QRCODE")
        fake_ean = FakeDecoded("123456789012", "EAN13")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake_qr, fake_ean])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 1
        assert results[0]["type"] == "QRCODE"

    def test_multiple_qr_codes(self, mocker):
        fakes = [
            FakeDecoded("first", "QRCODE", 0, 0, 50, 50),
            FakeDecoded("second", "QR_CODE", 100, 100, 50, 50),
        ]
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=fakes)
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert len(results) == 2

    def test_none_content_on_empty_decode(self, mocker):
        fake = FakeDecoded("", "QRCODE")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        assert results[0]["content"] is None


class TestDecodeQrFromRegion:
    def test_crops_and_decodes(self, mocker):
        fake = FakeDecoded("cropped-content", "QRCODE")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake])
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        results = decode_qr_from_region(img, [50, 50, 100, 100])
        assert len(results) == 1
        assert results[0]["content"] == "cropped-content"

    def test_bbox_clamped_to_image_bounds(self, mocker):
        fake = FakeDecoded("clamped", "QRCODE")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        # bbox extends beyond image — should be clamped
        results = decode_qr_from_region(img, [-10, -10, 200, 200])
        assert len(results) == 1

    def test_empty_operations_list_is_allowed(self, mocker):
        """无增强操作时也应正常工作（仅裁剪+解码）。"""
        fake = FakeDecoded("plain-crop", "QRCODE")
        mocker.patch("qr_reader.core.decoder.pyzbar.decode", return_value=[fake])
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        results = decode_qr_from_region(img, [0, 0, 50, 50])
        assert len(results) == 1
        assert results[0]["content"] == "plain-crop"
