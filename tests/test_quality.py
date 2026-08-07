"""Tests for quality module — pure numpy/cv2, no external dependencies."""

import cv2
import numpy as np
import pytest

from qr_reader.core.quality import (
    analyze_image_quality,
    has_glare,
    is_low_contrast,
    is_too_blur,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bgr(gray: np.ndarray) -> np.ndarray:
    """Convert 2D grayscale to 3-channel BGR for realistic input."""
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


# ---------------------------------------------------------------------------
# analyze_image_quality
# ---------------------------------------------------------------------------

class TestAnalyzeImageQuality:
    def test_pure_black(self):
        img = np.zeros((100, 100), dtype=np.uint8)
        q = analyze_image_quality(img)
        assert q["contrast"] == 0.0
        assert q["glare_ratio"] == 0.0
        assert q["noise_level"] == 0.0

    def test_pure_white(self):
        img = np.full((100, 100), 255, dtype=np.uint8)
        q = analyze_image_quality(img)
        assert q["contrast"] == 0.0
        assert q["glare_ratio"] == 0.0  # white background, not glare
        assert q["noise_level"] == 0.0

    def test_high_contrast_chessboard(self):
        """Chessboard gives contrast=1.0 and reasonable blur score."""
        img = np.zeros((100, 100), dtype=np.uint8)
        img[::2, ::2] = 255
        img[1::2, 1::2] = 255
        q = analyze_image_quality(img)
        assert q["contrast"] == pytest.approx(1.0, abs=0.01)

    def test_noise_increases_noise_level(self):
        """Residual-based noise metric: noisy > clean."""
        clean = np.full((100, 100), 128, dtype=np.uint8)
        noisy = clean.copy()
        noisy[::3, ::3] = 255
        noisy[1::3, 2::3] = 0
        q_clean = analyze_image_quality(clean)
        q_noisy = analyze_image_quality(noisy)
        assert q_noisy["noise_level"] > q_clean["noise_level"]

    def test_blur_reduces_blur_score(self):
        """Sharp edge → high blur_score; Gaussian blur → lower."""
        sharp = np.zeros((100, 100), dtype=np.uint8)
        sharp[40:60, :] = 255
        q_sharp = analyze_image_quality(sharp)
        blurred = cv2.GaussianBlur(sharp, (5, 5), 3)
        q_blur = analyze_image_quality(blurred)
        assert q_blur["blur_score"] < q_sharp["blur_score"]

    def test_accepts_bgr_input(self):
        """Should work with 3-channel BGR."""
        img = _bgr(np.zeros((100, 100), dtype=np.uint8))
        q = analyze_image_quality(img)
        assert "blur_score" in q

    def test_glare_detection(self):
        """Uneven bright-spot distribution — spatial variance detected as glare."""
        img = np.full((200, 200), 128, dtype=np.uint8)
        # Bright spot covering ~2 cells of the 4×4 grid
        img[10:110, 10:110] = 250
        q = analyze_image_quality(img)
        assert q["glare_ratio"] > 0.0

    def test_all_values_rounded_to_4_decimals(self):
        img = np.zeros((100, 100), dtype=np.uint8)
        q = analyze_image_quality(img)
        for v in q.values():
            # Round to 4 and back should be equal (no raw float noise)
            assert round(v, 4) == v


# ---------------------------------------------------------------------------
# Threshold helpers
# ---------------------------------------------------------------------------

class TestIsTooBlur:
    def test_below_threshold(self):
        assert is_too_blur(30.0, threshold=50.0) is True

    def test_above_threshold(self):
        assert is_too_blur(80.0, threshold=50.0) is False

    def test_exact_threshold(self):
        assert is_too_blur(50.0, threshold=50.0) is False  # strict <


class TestIsLowContrast:
    def test_below(self):
        assert is_low_contrast(0.1, threshold=0.15) is True

    def test_above(self):
        assert is_low_contrast(0.3, threshold=0.15) is False


class TestHasGlare:
    def test_above(self):
        assert has_glare(0.5, threshold=0.3) is True

    def test_below(self):
        assert has_glare(0.1, threshold=0.3) is False
