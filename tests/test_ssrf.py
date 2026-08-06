"""Tests for SSRF protection in url_utils.is_private_url."""

import pytest
from qr_reader.core.url_utils import is_private_url


class TestIsPrivateUrl:
    # --- 应被阻止的 URL ---

    @pytest.mark.parametrize("url", [
        "http://localhost/path",
        "http://0.0.0.0/path",
        "http://127.0.0.1/path",
        "http://10.0.0.1/path",
        "http://172.16.0.1/path",
        "http://192.168.1.1/path",
        "http://169.254.1.1/path",        # link-local
        "https://[::1]/path",              # IPv6 loopback
        "https://[fc00::1]/path",           # IPv6 private (ULA)
        "https://[fe80::1]/path",           # IPv6 link-local
    ])
    def test_private_urls_blocked(self, url):
        assert is_private_url(url) is True

    # --- 应被允许的 URL ---

    @pytest.mark.parametrize("url", [
        "https://example.com/img.png",
        "http://8.8.8.8/img.png",
        "https://github.com/raw/repo/main/qr.png",
    ])
    def test_public_urls_allowed(self, url):
        assert is_private_url(url) is False

    # --- 非 http/https scheme 应被阻止 ---

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com",
        "dict://localhost:11211",
    ])
    def test_non_http_schemes_blocked(self, url):
        assert is_private_url(url) is True
