"""Image quality analysis module.

Provides blur, contrast, glare, and noise metrics that feed into the
diagnosis engine.  All cv2 usage is routed through ops.py so the module
works in both full and light installs.
"""

import numpy as np
from qr_reader.core.ops import laplacian_variance, image_contrast, glare_ratio, noise_level


def analyze_image_quality(img: np.ndarray) -> dict:
    """Analyze image quality and return four scalar metrics.

    Args:
        img: RGB/BGR or grayscale image (H × W × C or H × W).

    Returns:
        dict with keys: blur_score, contrast, glare_ratio, noise_level.
    """
    return {
        "blur_score": round(laplacian_variance(img), 4),
        "contrast": round(image_contrast(img), 4),
        "glare_ratio": round(glare_ratio(img), 4),
        "noise_level": round(noise_level(img), 4),
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
