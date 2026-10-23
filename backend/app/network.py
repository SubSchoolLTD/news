"""Public-only outbound sockets. Resolve once and connect to the checked numeric IP.

The original request hostname remains in httpcore's origin, preserving TLS SNI and
certificate verification. The pinned httpx/httpcore versions are integration-tested.
"""
import ipaddress
import socket
import httpcore
import httpx


class PublicNetworkBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError("Outbound connections must use public IP addresses.")
        last = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout=timeout, local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        if last:
            raise last
        raise ValueError("The public source could not be reached.")


def public_transport():
    transport = httpx.HTTPTransport(retries=0)
    transport._pool._network_backend = PublicNetworkBackend()
    return transport
