"""Tests for image quality analysis module."""

import numpy as np
import pytest
from qr_reader.core.quality import (
    analyze_image_quality,
    is_too_blur,
    is_low_contrast,
    has_glare,
)


class TestAnalyzeImageQuality:
    def test_returns_four_keys(self):
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = analyze_image_quality(img)
        assert set(result.keys()) == {"blur_score", "contrast", "glare_ratio", "noise_level"}

    def test_all_black_image(self):
        """Fully black image — zero contrast, zero glare."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = analyze_image_quality(img)
        assert result["contrast"] == 0.0
        assert result["glare_ratio"] == 0.0

    def test_all_white_image(self):
        """Fully white image — zero contrast, max glare."""
        img = np.full((100, 100, 3), 255, dtype=np.uint8)
        result = analyze_image_quality(img)
        assert result["contrast"] == 0.0
        assert result["glare_ratio"] == 1.0

    def test_sharp_vs_blurry(self):
        """A sharp edge image should have higher blur_score than uniform."""
        sharp = np.zeros((100, 100), dtype=np.uint8)
        sharp[:, 50:] = 255
        blurry = np.full((100, 100), 128, dtype=np.uint8)
        sharp_score = analyze_image_quality(sharp)["blur_score"]
        blurry_score = analyze_image_quality(blurry)["blur_score"]
        assert sharp_score > blurry_score

    def test_grayscale_input(self):
        img = np.random.randint(0, 256, (50, 50), dtype=np.uint8)
        result = analyze_image_quality(img)
        assert all(k in result for k in ["blur_score", "contrast", "glare_ratio", "noise_level"])


class TestThresholds:
    def test_is_too_blur_below_threshold(self):
        assert is_too_blur(30.0, threshold=50.0) is True
        assert is_too_blur(60.0, threshold=50.0) is False

    def test_is_low_contrast(self):
        assert is_low_contrast(0.10, threshold=0.15) is True
        assert is_low_contrast(0.20, threshold=0.15) is False

    def test_has_glare(self):
        assert has_glare(0.35, threshold=0.3) is True
        assert has_glare(0.20, threshold=0.3) is False
