"""URL validation utilities for SSRF protection."""

import ipaddress
from urllib.parse import urlparse

# 仅 http/https，拒绝 file:// / ftp:// 等
_ALLOWED_SCHEMES = {"http", "https"}


def is_private_url(url: str) -> bool:
    """检查 URL 是否指向内网/私有地址，防止 SSRF。

    Returns True if the URL should be blocked.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return True

    hostname = parsed.hostname
    if not hostname:
        return True

    # 常见内网主机名
    if hostname in ("localhost", "0.0.0.0", "::1"):
        return True

    # 尝试解析 IP 地址
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        # 不是 IP 地址（是域名），不阻止——DNS 解析后的 SSRF 风险
        # 由 requests 层和 timeout 限制，这里不覆盖
        return False
