"""L1 micro-benchmarks — pure image operations.

Covers laplacian_variance, image_contrast, glare_ratio, noise_level,
op_upscale, op_sharpen, op_contrast, op_denoise.
"""

import numpy as np
from qr_reader.core.ops import (
    glare_ratio,
    image_contrast,
    laplacian_variance,
    noise_level,
    op_contrast,
    op_denoise,
    op_sharpen,
    op_upscale,
)


# ---------------------------------------------------------------------------
# laplacian_variance (blur score) — CPU-bound numpy
# ---------------------------------------------------------------------------

def test_laplacian_variance_small(benchmark, gray_100):
    benchmark(laplacian_variance, gray_100)


def test_laplacian_variance_medium(benchmark, gray_500):
    benchmark(laplacian_variance, gray_500)


def test_laplacian_variance_1080p(benchmark, gray_1080p):
    benchmark(laplacian_variance, gray_1080p)


def test_laplacian_variance_chessboard(benchmark, chessboard):
    benchmark(laplacian_variance, chessboard)


# ---------------------------------------------------------------------------
# image_contrast
# ---------------------------------------------------------------------------

def test_image_contrast_small(benchmark, gray_100):
    benchmark(image_contrast, gray_100)


def test_image_contrast_1080p(benchmark, gray_1080p):
    benchmark(image_contrast, gray_1080p)


# ---------------------------------------------------------------------------
# glare_ratio
# ---------------------------------------------------------------------------

def test_glare_ratio_small(benchmark, gray_100):
    benchmark(glare_ratio, gray_100)


def test_glare_ratio_1080p(benchmark, gray_1080p):
    benchmark(glare_ratio, gray_1080p)


# ---------------------------------------------------------------------------
# noise_level
# ---------------------------------------------------------------------------

def test_noise_level_small(benchmark, gray_100):
    benchmark(noise_level, gray_100)


def test_noise_level_1080p(benchmark, gray_1080p):
    benchmark(noise_level, gray_1080p)


# ---------------------------------------------------------------------------
# op_upscale
# ---------------------------------------------------------------------------

def test_op_upscale_2x(benchmark, bgr_small):
    benchmark(op_upscale, bgr_small, 2.0)


def test_op_upscale_4x(benchmark, bgr_small):
    benchmark(op_upscale, bgr_small, 4.0)


def test_op_upscale_8x(benchmark, bgr_small):
    benchmark(op_upscale, bgr_small, 8.0)


# ---------------------------------------------------------------------------
# op_sharpen
# ---------------------------------------------------------------------------

def test_op_sharpen_mild(benchmark, bgr_medium):
    benchmark(op_sharpen, bgr_medium, 1.5)


def test_op_sharpen_strong(benchmark, bgr_medium):
    benchmark(op_sharpen, bgr_medium, 4.0)


# ---------------------------------------------------------------------------
# op_contrast
# ---------------------------------------------------------------------------

def test_op_contrast_boost(benchmark, bgr_medium):
    benchmark(op_contrast, bgr_medium, 1.5)


def test_op_contrast_reduce(benchmark, bgr_medium):
    benchmark(op_contrast, bgr_medium, 0.6)


# ---------------------------------------------------------------------------
# op_denoise
# ---------------------------------------------------------------------------

def test_op_denoise_light(benchmark, bgr_medium):
    benchmark(op_denoise, bgr_medium, 5)


def test_op_denoise_heavy(benchmark, bgr_medium):
    benchmark(op_denoise, bgr_medium, 25)
