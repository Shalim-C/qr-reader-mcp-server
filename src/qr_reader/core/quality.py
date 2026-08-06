"""Image quality analysis module.

Provides Laplacian blur detection, contrast, glare, and noise metrics
that feed into the diagnosis engine.
"""

import cv2
import numpy as np


def analyze_image_quality(img: np.ndarray) -> dict:
    """Analyze image quality and return four scalar metrics.

    Args:
        img: BGR or grayscale image (H × W × C or H × W).

    Returns:
        dict with keys: blur_score, contrast, glare_ratio, noise_level.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    contrast = float(gray.max() - gray.min()) / 255.0
    glare_ratio = float(np.sum(gray > 240)) / gray.size
    noise_level = float(np.std(
        gray.astype(float) - cv2.GaussianBlur(gray, (0, 0), 3).astype(float)
    ))
    return {
        "blur_score": round(blur_score, 4),
        "contrast": round(contrast, 4),
        "glare_ratio": round(glare_ratio, 4),
        "noise_level": round(noise_level, 4),
    }


def is_too_blur(blur_score: float, threshold: float = 50.0) -> bool:
    """Return True if the Laplacian variance is below the threshold."""
    return blur_score < threshold


def is_low_contrast(contrast: float, threshold: float = 0.15) -> bool:
    """Return True if contrast is below the threshold."""
    return contrast < threshold


def has_glare(glare_ratio: float, threshold: float = 0.3) -> bool:
    """Return True if the glare ratio exceeds the threshold."""
    return glare_ratio > threshold
