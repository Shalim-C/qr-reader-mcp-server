"""L2 component-level benchmarks — decoder, diagnosis, enhancement pipeline.

Tests decode_qr_from_image, decode_qr_from_region, classify_result,
and apply_operations — covering both pyzbar and OpenCV fallback paths.
"""

import numpy as np
from qr_reader.core.decoder import decode_qr_from_image, decode_qr_from_region
from qr_reader.core.diagnosis import classify_result
from qr_reader.server import apply_operations


# ---------------------------------------------------------------------------
# decode_qr_from_image
# ---------------------------------------------------------------------------

def test_decode_clean_qr(benchmark, qr_clean):
    """Single clean QR — primary pyzbar path."""
    benchmark(decode_qr_from_image, qr_clean)


def test_decode_no_qr(benchmark, no_qr_photo):
    """No QR code — fast path (pyzbar returns empty quickly)."""
    benchmark(decode_qr_from_image, no_qr_photo)


def test_decode_blurry_qr(benchmark, qr_blurry):
    """Blurry QR — may trigger OpenCV fallback if pyzbar fails."""
    benchmark(decode_qr_from_image, qr_blurry)


def test_decode_multi_qr(benchmark, qr_multi):
    """Two QR codes — multi-decode path."""
    benchmark(decode_qr_from_image, qr_multi)


# ---------------------------------------------------------------------------
# decode_qr_from_region
# ---------------------------------------------------------------------------

def test_decode_region_full(benchmark, qr_clean):
    """Crop and decode — region covers the whole image."""
    h, w = qr_clean.shape[:2]
    benchmark(decode_qr_from_region, qr_clean, [0, 0, w, h])


def test_decode_region_partial(benchmark, qr_clean):
    """Crop and decode — tight crop around QR center."""
    h, w = qr_clean.shape[:2]
    benchmark(decode_qr_from_region, qr_clean, [w // 4, h // 4, w // 2, h // 2])


# ---------------------------------------------------------------------------
# classify_result
# ---------------------------------------------------------------------------

def test_classify_success(benchmark, qr_clean):
    """Classify a successful decode."""
    results = [{"content": "https://example.com", "type": "QRCODE"}]
    benchmark(classify_result, qr_clean, True, True, results)


def test_classify_no_qr_found(benchmark, no_qr_photo):
    """Classify — no QR detected at all."""
    benchmark(classify_result, no_qr_photo, False, False, [])


def test_classify_retryable(benchmark, qr_blurry):
    """Classify — QR detected but decode failed (retryable)."""
    benchmark(classify_result, qr_blurry, True, False, [])


# ---------------------------------------------------------------------------
# apply_operations
# ---------------------------------------------------------------------------

def test_apply_upscale_2x(benchmark, bgr_small):
    benchmark(apply_operations, bgr_small, [{"op": "upscale", "params": {"scale": 2.0}}])


def test_apply_sharpen(benchmark, bgr_medium):
    benchmark(apply_operations, bgr_medium, [{"op": "sharpen", "params": {"strength": 1.5}}])


def test_apply_chain_3ops(benchmark, bgr_medium):
    """upscale → sharpen → contrast."""
    ops = [
        {"op": "upscale", "params": {"scale": 2.0}},
        {"op": "sharpen", "params": {"strength": 1.5}},
        {"op": "adjust_contrast", "params": {"alpha": 1.2}},
    ]
    benchmark(apply_operations, bgr_medium, ops)


def test_apply_full_chain_5ops(benchmark, bgr_small):
    """upscale → sharpen → contrast → denoise → sharpen."""
    ops = [
        {"op": "upscale", "params": {"scale": 2.0}},
        {"op": "sharpen", "params": {"strength": 1.5}},
        {"op": "adjust_contrast", "params": {"alpha": 1.2}},
        {"op": "denoise", "params": {"h": 10}},
        {"op": "sharpen", "params": {"strength": 1.0}},
    ]
    benchmark(apply_operations, bgr_small, ops)
