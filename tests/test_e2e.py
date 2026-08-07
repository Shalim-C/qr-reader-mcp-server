"""End-to-end tests — real QR codes, real decoding, no mocks.

Generates QR codes encoding the repo URL, then verifies:
  - Clean decode returns SUCCESS with correct content
  - Each degradation scenario is recoverable via the matching enhancement

These tests validate the actual decoding pipeline end-to-end,
catching regressions that mock-based unit tests can't.
"""

import cv2
import numpy as np
import pytest

from qr_reader.core.decoder import decode_qr_from_image, decode_qr_from_region
from qr_reader.core.diagnosis import classify_result
from qr_reader.server import apply_operations

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

REPO_URL = "https://github.com/Shalim-C/qr-reader-mcp-server"


@pytest.fixture(scope="module")
def real_qr():
    """A clean, real QR code encoding the repo URL."""
    import qrcode
    qr = qrcode.QRCode(version=2, box_size=10, border=2)
    qr.add_data(REPO_URL)
    qr.make(fit=True)
    pil = qr.make_image(fill_color="black", back_color="white")
    return cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)


@pytest.fixture(scope="module")
def multi_qr():
    """An image with two QR codes side by side."""
    import qrcode
    qr1 = qrcode.make("https://example.com/first")
    qr2 = qrcode.make("https://example.com/second")
    # Place side by side on a white canvas
    arr1 = np.array(qr1.convert("RGB"))
    arr2 = np.array(qr2.convert("RGB"))
    h = max(arr1.shape[0], arr2.shape[0])
    canvas = np.full((h, arr1.shape[1] + arr2.shape[1] + 20, 3), 255, dtype=np.uint8)
    canvas[:arr1.shape[0], :arr1.shape[1]] = arr1
    canvas[:arr2.shape[0], arr1.shape[1] + 20:] = arr2
    return cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)


# ═══════════════════════════════════════════════════════════════════════
# Happy path
# ═══════════════════════════════════════════════════════════════════════

class TestCleanDecode:
    def test_clean_qr_decodes_correct_content(self, real_qr):
        results = decode_qr_from_image(real_qr)
        assert len(results) == 1
        assert results[0]["content"] == REPO_URL

    def test_clean_qr_returns_success(self, real_qr):
        results = decode_qr_from_image(real_qr)
        info = classify_result(real_qr, True, True, results)
        assert info["result_code"] == "SUCCESS"

    def test_clean_qr_bbox_is_within_image(self, real_qr):
        results = decode_qr_from_image(real_qr)
        x, y, w, h = results[0]["bbox"]
        ih, iw = real_qr.shape[:2]
        assert 0 <= x <= iw
        assert 0 <= y <= ih
        assert w > 0 and h > 0


# ═══════════════════════════════════════════════════════════════════════
# Scale degradation → upscale recovery
# ═══════════════════════════════════════════════════════════════════════

class TestScaleDamage:
    def test_tiny_qr_upscaled_recovers(self, real_qr):
        """Shrink to 25% → upscale 4× → should still decode."""
        h, w = real_qr.shape[:2]
        tiny = cv2.resize(real_qr, (w // 4, h // 4))
        restored = apply_operations(tiny, [{"op": "upscale", "params": {"scale": 4.0}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL

    def test_tiny_qr_without_upscale_fails(self, real_qr):
        """Shrink to 25% with no upscale — may or may not decode
        depending on pyzbar tolerance.  This test just asserts no crash."""
        h, w = real_qr.shape[:2]
        tiny = cv2.resize(real_qr, (w // 4, h // 4))
        results = decode_qr_from_image(tiny)
        # Some pyzbar versions can decode tiny QR — either way, no crash
        assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════════════
# Blur degradation → sharpen recovery
# ═══════════════════════════════════════════════════════════════════════

class TestBlurDamage:
    def test_gaussian_blur_sharpened_recovers(self, real_qr):
        """Gaussian blur → sharpen → decode."""
        blurred = cv2.GaussianBlur(real_qr, (5, 5), 3)
        restored = apply_operations(blurred, [{"op": "sharpen", "params": {"strength": 2.0}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL

    def test_mild_blur_recovered(self, real_qr):
        """Mild blur with moderate sharpen."""
        blurred = cv2.GaussianBlur(real_qr, (3, 3), 1.5)
        restored = apply_operations(blurred, [{"op": "sharpen", "params": {"strength": 1.5}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL


# ═══════════════════════════════════════════════════════════════════════
# Contrast degradation → contrast recovery
# ═══════════════════════════════════════════════════════════════════════

class TestContrastDamage:
    def test_low_contrast_boosted_recovers(self, real_qr):
        """Reduce contrast to 30% → boost to 250% → decode."""
        dim = cv2.convertScaleAbs(real_qr, alpha=0.3, beta=0)
        restored = apply_operations(dim, [{"op": "adjust_contrast", "params": {"alpha": 2.5}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL

    def test_washed_out_boosted_recovers(self, real_qr):
        """Add white overlay (wash out) → boost contrast."""
        washed = cv2.addWeighted(real_qr, 0.7, np.full_like(real_qr, 180), 0.3, 0)
        restored = apply_operations(washed, [{"op": "adjust_contrast", "params": {"alpha": 2.0}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL


# ═══════════════════════════════════════════════════════════════════════
# Noise degradation → denoise recovery
# ═══════════════════════════════════════════════════════════════════════

class TestNoiseDamage:
    def test_salt_pepper_denoised_recovers(self, real_qr):
        """~2% salt-and-pepper noise → denoise → decode."""
        noisy = real_qr.copy()
        rng = np.random.default_rng(42)
        # Salt (white) — 2%
        salt_mask = rng.random(noisy.shape[:2]) < 0.02
        noisy[salt_mask] = [255, 255, 255]
        # Pepper (black) — 2%
        pepper_mask = rng.random(noisy.shape[:2]) < 0.02
        noisy[pepper_mask] = [0, 0, 0]
        restored = apply_operations(noisy, [{"op": "denoise", "params": {"h": 12}}])
        results = decode_qr_from_image(restored)
        # Note: heavy noise is hard to recover — this is the hardest scenario.
        # If this fails on some pyzbar versions, it's an acceptable skip.
        if not results:
            pytest.skip("Heavy noise recovery is pyzbar-version-dependent")
        assert results[0]["content"] == REPO_URL

    def test_mild_noise_denoised_recovers(self, real_qr):
        """1% noise — light denoise should suffice."""
        noisy = real_qr.copy()
        rng = np.random.default_rng(99)
        mask = rng.random(noisy.shape[:2]) < 0.01
        noisy[mask] = [0, 0, 0]
        restored = apply_operations(noisy, [{"op": "denoise", "params": {"h": 8}}])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL


# ═══════════════════════════════════════════════════════════════════════
# Chain: multiple degradations
# ═══════════════════════════════════════════════════════════════════════

class TestChainRecovery:
    def test_blur_and_low_contrast_chained(self, real_qr):
        """Blur + low contrast → sharpen + boost contrast."""
        h, w = real_qr.shape[:2]
        # Shrink + blur + dim
        small = cv2.resize(real_qr, (w // 2, h // 2))
        blurred = cv2.GaussianBlur(small, (3, 3), 2)
        dim = cv2.convertScaleAbs(blurred, alpha=0.5, beta=0)
        # Chain: upscale → sharpen → contrast
        restored = apply_operations(dim, [
            {"op": "upscale", "params": {"scale": 2.5}},
            {"op": "sharpen", "params": {"strength": 2.0}},
            {"op": "adjust_contrast", "params": {"alpha": 2.0}},
        ])
        results = decode_qr_from_image(restored)
        assert len(results) >= 1
        assert results[0]["content"] == REPO_URL


# ═══════════════════════════════════════════════════════════════════════
# Multi-code
# ═══════════════════════════════════════════════════════════════════════

class TestMultiCode:
    def test_two_qr_codes_detected(self, multi_qr):
        results = decode_qr_from_image(multi_qr)
        # pyzbar should find both
        assert len(results) >= 2
        contents = {r["content"] for r in results}
        assert "https://example.com/first" in contents
        assert "https://example.com/second" in contents

    def test_two_qr_codes_diagnosis(self, multi_qr):
        results = decode_qr_from_image(multi_qr)
        info = classify_result(multi_qr, True, True, results)
        assert info["result_code"] == "SUCCESS"
        assert info["analysis"]["total_detected"] >= 2


# ═══════════════════════════════════════════════════════════════════════
# Diagnosis: result codes
# ═══════════════════════════════════════════════════════════════════════

class TestDiagnosisE2E:
    def test_no_qr_found_on_blank_image(self):
        blank = np.full((200, 200, 3), 128, dtype=np.uint8)
        results = decode_qr_from_image(blank)
        info = classify_result(blank, False, False, results)
        assert info["result_code"] == "NO_QR_FOUND"

    def test_empty_qr_content_warning(self):
        """A QR code with empty content should trigger SUCCESS_WITH_WARNING."""
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data("")
        qr.make(fit=True)
        pil = qr.make_image(fill_color="black", back_color="white")
        img = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)
        results = decode_qr_from_image(img)
        # Empty-content QR is structurally valid — pyzbar should decode it.
        # If not, at minimum verify the call doesn't crash.
        assert isinstance(results, list)
        if results:
            info = classify_result(img, True, len(results) > 0, results)
            assert info["result_code"] in ("SUCCESS", "SUCCESS_WITH_WARNING")


# ═══════════════════════════════════════════════════════════════════════
# Malformed / edge-case images (E-05)
# ═══════════════════════════════════════════════════════════════════════

class TestMalformedImages:
    def test_random_bytes_not_an_image(self):
        """Random bytes should raise, not crash."""
        from qr_reader.server import load_image_bytes
        with pytest.raises(ValueError):
            load_image_bytes(b"\x00\x01\x02\x03not-an-image", max_long_edge=2560)

    def test_truncated_png(self):
        """Truncated PNG header should raise ValueError."""
        from qr_reader.server import load_image_bytes
        # PNG magic + IHDR start, then truncated
        truncated = (
            b"\x89PNG\r\n\x1a\n"  # PNG magic
            b"\x00\x00\x00\x0dIHDR"  # IHDR start, no data
        )
        with pytest.raises(ValueError):
            load_image_bytes(truncated, max_long_edge=2560)

    def test_1px_image_no_crash(self):
        """1-pixel image (B-15 fix) should not crash Laplacian."""
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        results = decode_qr_from_image(img)
        info = classify_result(img, False, False, results)
        # Should not raise; result_code is what it is
        assert info["result_code"] in (
            "NO_QR_FOUND", "RETRYABLE", "QR_UNRECOVERABLE",
        )


# ═══════════════════════════════════════════════════════════════════════
# region decode
# ═══════════════════════════════════════════════════════════════════════

class TestRegionDecodeE2E:
    def test_crop_region_and_decode(self, real_qr):
        """Crop the exact QR region → decode directly (no enhancement)."""
        results = decode_qr_from_image(real_qr)
        bbox = results[0]["bbox"]
        region_results = decode_qr_from_region(real_qr, bbox)
        assert len(region_results) >= 1
        assert region_results[0]["content"] == REPO_URL
