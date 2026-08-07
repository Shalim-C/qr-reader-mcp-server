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


def is_private_url(url: str) -> bool:
    """Check whether a URL targets an internal/private address.

    Returns True if the URL should be blocked.

    Layers:
      1. Scheme must be http or https.
      2. Hostname in known blocklist → blocked.
      3. If hostname is an IP literal → validate directly.
      4. If hostname is a domain → resolve DNS and validate every IP.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return True

    hostname = parsed.hostname
    if not hostname:
        return True

    # -- Block known internal hostnames -----------------------------------
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return True

    # -- Direct IP literal ------------------------------------------------
    if _is_private_ip(hostname):
        return True

    # -- DNS resolution ---------------------------------------------------
    # Resolve the hostname and check every returned IP.  A single private
    # IP in the result set means the URL is dangerous (DNS rebinding).
    # If resolution fails, we don't block — the subsequent HTTP request
    # will also fail, so there's no practical attack window.
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False

    for item in addrinfo:
        ip_str = item[4][0]
        if _is_private_ip(str(ip_str)):
            return True

    return False
