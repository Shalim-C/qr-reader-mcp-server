"""DNS-pinning HTTP transport for SSRF protection.

Closes the resolve-twice TOCTOU window: the caller validates a URL with a
single DNS resolution, then every connection is pinned to the validated
public IP while the Host header / SNI / TLS certificate verification keep
using the original hostname (virtual hosts and HTTPS keep working).

This module is imported by ``qr_reader.server``; it depends only on
``requests`` / ``urllib3`` and has no MCP coupling.
"""

from functools import partial

import requests.adapters
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import PoolManager
from urllib3.util.connection import create_connection


class _PinnedHTTPConnection(HTTPConnection):
    """HTTP connection that connects to a pre-resolved IP instead of
    re-resolving the hostname (the request itself must not trigger a
    second DNS lookup — that lookup is the rebinding window)."""

    def __init__(self, host: str, pinned_ip: str, **kw):
        super().__init__(host, **kw)
        self._pinned_ip = pinned_ip

    def _new_conn(self):
        return create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
            socket_options=self.socket_options,
        )


class _PinnedHTTPSConnection(HTTPSConnection):
    """HTTPS variant. The TCP connection goes to the pinned IP while
    ``host`` stays the original hostname, so the Host header, SNI and
    TLS certificate verification all keep using the real name."""

    def __init__(self, host: str, pinned_ip: str, **kw):
        super().__init__(host, **kw)
        self._pinned_ip = pinned_ip

    def _new_conn(self):
        return create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
            socket_options=self.socket_options,
        )


class _PinnedHTTPConnectionPool(HTTPConnectionPool):
    """HTTP pool whose connections go to the pinned IP."""

    def __init__(self, host: str, port: int | None = None, *, pinned_ip: str | None = None, **kw):
        super().__init__(host, port, **kw)
        if pinned_ip is None:
            raise ValueError("pinned_ip is required for _PinnedHTTPConnectionPool")
        # urllib3 calls ConnectionCls(host, port, **kw); a partial bound to
        # the pinned IP is call-compatible even though it is not a class.
        self.ConnectionCls = partial(_PinnedHTTPConnection, pinned_ip=pinned_ip)  # type: ignore[assignment]


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
    """HTTPS pool whose TCP connections go to the pinned IP while SNI /
    TLS verification keep using the original hostname."""

    def __init__(self, host: str, port: int | None = None, *, pinned_ip: str | None = None, **kw):
        super().__init__(host, port, **kw)
        if pinned_ip is None:
            raise ValueError("pinned_ip is required for _PinnedHTTPSConnectionPool")
        self.ConnectionCls = partial(_PinnedHTTPSConnection, pinned_ip=pinned_ip)  # type: ignore[assignment]


class _PinnedPoolManager(PoolManager):
    """PoolManager that routes every scheme through pinned pools."""

    def __init__(self, pinned_ip: str, **kw):
        super().__init__(**kw)
        # pool_classes_by_scheme is typed as dict[str, type]; partial is
        # call-compatible with pool_cls(host, port, **request_context).
        self.pool_classes_by_scheme["http"] = partial(  # type: ignore[assignment]
            _PinnedHTTPConnectionPool, pinned_ip=pinned_ip
        )
        self.pool_classes_by_scheme["https"] = partial(  # type: ignore[assignment]
            _PinnedHTTPSConnectionPool, pinned_ip=pinned_ip
        )


class _PinnedIPAdapter(requests.adapters.HTTPAdapter):
    """Adapter that pins every connection to one pre-validated IP."""

    def __init__(self, pinned_ip: str, *args, **kwargs):
        # Must be set BEFORE super().__init__(): HTTPAdapter.__init__ calls
        # self.init_poolmanager(), which reads self._pinned_ip.
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = _PinnedPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            pinned_ip=self._pinned_ip,
            **pool_kwargs,
        )
