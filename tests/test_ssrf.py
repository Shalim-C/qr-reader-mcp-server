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
    ])
    def test_public_urls_allowed(self, url):
        assert is_private_url(url) is False

    def test_public_domain_allowed(self, mocker):
        """github.com should pass when DNS resolves to a public IP.
        Mock DNS to avoid local proxy interference (e.g. Steam++)."""
        mocker.patch("socket.getaddrinfo", return_value=[
            (2, 0, 0, "", ("140.82.121.3", 0)),  # real GitHub IP
        ])
        assert is_private_url("https://github.com/raw/repo/main/qr.png") is False

    # --- DNS rebinding / domain-based bypass ---------------------------------

    def test_localtest_me_blocked(self, mocker):
        """localtest.me resolves to 127.0.0.1 — must be blocked."""
        mocker.patch("socket.getaddrinfo", return_value=[
            (2, 0, 0, "", ("127.0.0.1", 0)),
        ])
        assert is_private_url("http://localtest.me/img.png") is True

    def test_cloud_metadata_hostname_blocked(self):
        """GCP metadata hostname — blocked by hostname blocklist."""
        assert is_private_url("http://metadata.google.internal/") is True

    def test_alibaba_metadata_blocked(self):
        """Alibaba Cloud metadata endpoint — blocked by hostname blocklist."""
        assert is_private_url("http://100.100.100.200/") is True

    def test_aws_metadata_blocked(self):
        """AWS metadata IP — blocked as link-local."""
        assert is_private_url("http://169.254.169.254/latest/meta-data/") is True

    # --- Non-standard IP notation bypass tests ------------------------------

    @pytest.mark.parametrize("url", [
        "http://2130706433/img.png",         # decimal = 127.0.0.1
        "http://0x7f000001/img.png",         # hex = 127.0.0.1
    ])
    def test_non_standard_ip_notation_allowed_then_blocked_by_dns(self, url, mocker):
        """Non-standard IP notations are not directly blocked;
        if the IP resolves to a private address, DNS check catches it.
        This test verifies the current behavior — if url_utils gains
        direct non-standard-IP parsing, update this test."""
        mocker.patch("socket.getaddrinfo", return_value=[
            (2, 0, 0, "", ("127.0.0.1", 0)),
        ])
        assert is_private_url(url) is True

    # --- 非 http/https scheme 应被阻止 ---

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com",
        "dict://localhost:11211",
    ])
    def test_non_http_schemes_blocked(self, url):
        assert is_private_url(url) is True
