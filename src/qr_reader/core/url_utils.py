"""URL validation utilities for SSRF protection.

Defense in depth:
  1. Scheme whitelist (http/https only)
  2. Hostname blocklist (localhost, metadata endpoints, etc.)
  3. DNS resolution + IP validation (every resolved IP checked)
  4. Redirect disabled at the HTTP client level (server.py)
"""

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}

# Hostnames that resolve to private/internal addresses at various cloud
# providers — these won't be caught by a simple IP check alone.
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "0.0.0.0",
    "::1",
    "metadata.google.internal",       # GCP
    "169.254.169.254",                # AWS / cloud-init
    "metadata.tencentyun.com",        # Tencent Cloud
    "100.100.100.200",                # Alibaba Cloud
})


def _is_private_ip(ip_str: str) -> bool:
    """Check whether an IP string is private/loopback/link-local/reserved.

    Returns True for any address that should be blocked.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # Not a valid IP literal — allow (hostname, will be DNS-resolved
        # separately).
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_image_host(url: str) -> tuple[str, int, str]:
    """Resolve a URL's hostname **once** and return (hostname, port, public_ip).

    The validation and the returned IP come from the same DNS resolution,
    so the subsequent request cannot be rebound to a different (private)
    address — this closes the DNS-rebinding TOCTOU window (validate with
    one lookup, connect with another).

    Raises ValueError with a human-readable reason when the URL must be
    blocked (bad scheme, blocked/private hostname, resolution failure,
    or any resolved IP being private).

    The caller is expected to pin the HTTP connection to the returned IP
    while keeping the original hostname for the Host header, SNI and TLS
    certificate verification.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"scheme '{parsed.scheme}' not allowed (http/https only)")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    # -- Block known internal hostnames -----------------------------------
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"hostname '{hostname}' is blocked")

    # -- Direct IP literal ------------------------------------------------
    if _is_private_ip(hostname):
        raise ValueError(f"hostname '{hostname}' is a private/internal address")

    # -- DNS resolution (single lookup, used for both check and connect) --
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise ValueError(f"invalid port in URL '{url}'") from None

    try:
        addrinfo = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ValueError(f"could not resolve hostname '{hostname}'") from None

    ips = [str(item[4][0]) for item in addrinfo]
    if not ips:
        raise ValueError(f"no addresses resolved for hostname '{hostname}'")

    # A single private IP in the result set means the URL is dangerous
    # (DNS rebinding) — reject the whole set.
    for ip in ips:
        if _is_private_ip(str(ip)):
            raise ValueError(f"resolved address '{ip}' is private/internal")

    return hostname, port, ips[0]


def is_private_url(url: str) -> bool:
    """Check whether a URL targets an internal/private address.

    Returns True if the URL should be blocked. Implemented on top of
    ``resolve_image_host`` so the two share the exact same validation
    logic and there is only one code path.
    """
    try:
        resolve_image_host(url)
        return False
    except ValueError:
        return True
