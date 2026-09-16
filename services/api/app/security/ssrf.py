"""SSRF protection — block private/link-local/metadata targets and enforce host allowlists."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.agents.execution.url_allowlist import DEFAULT_ALLOWED_HOSTS, assert_url_allowed
from app.security.errors import AppError


class SSRFBlocked(AppError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message, code="SSRF_BLOCKED", status_code=400, details=details)


_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return True
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def assert_safe_outbound_url(
    url: str,
    *,
    allowed_hosts: frozenset[str] | None = None,
    resolve_dns: bool = True,
) -> None:
    """
    Validate outbound URL against allowlist and block SSRF to private/metadata targets.

    Does not perform the HTTP fetch — only safety checks for callers that will.
    """
    hosts = allowed_hosts or DEFAULT_ALLOWED_HOSTS
    try:
        assert_url_allowed(url, allowed_hosts=hosts)
    except ValueError as exc:
        raise SSRFBlocked(str(exc), details={"url_host": urlparse(url).hostname}) from exc

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _BLOCKED_HOSTNAMES and host not in hosts:
        raise SSRFBlocked("Outbound host is blocked for SSRF protection", details={"host": host})

    # Literal IP in URL
    try:
        ip = ipaddress.ip_address(host)
        if _ip_is_blocked(ip) and host not in hosts:
            raise SSRFBlocked("Outbound IP is not publicly routable", details={"ip": host})
        return
    except ValueError:
        pass

    if not resolve_dns:
        return

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFBlocked("Outbound host could not be resolved", details={"host": host}) from exc

    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_blocked(ip) and host not in hosts:
            raise SSRFBlocked(
                "Outbound host resolves to a blocked address",
                details={"host": host, "ip": str(ip)},
            )
