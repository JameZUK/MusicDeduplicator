"""Who may use the dashboard.

Two modes:
  none      no login, but only clients whose address is in the allowlist (by
            default loopback and the private LAN ranges).
  authelia  every request must come from a trusted reverse proxy and carry the
            Remote-User header it sets after login; nothing else is accepted.

Independently of the mode, state-changing requests need the session's CSRF token
and, if the browser sends an Origin, it must match the Host. In 'none' mode the
Host header must also be a name this server answers to, which defeats DNS
rebinding (a public page resolving its own name to this LAN address).
"""

from __future__ import annotations

import ipaddress
import secrets
import socket
from dataclasses import dataclass, field

DEFAULT_ALLOW = ['127.0.0.0/8', '::1/128', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7']


def _networks(cidrs: list[str]) -> list[ipaddress._BaseNetwork]:
    return [ipaddress.ip_network(c, strict=False) for c in cidrs]


def _in(addr: str, nets) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split('%')[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in nets)


class Denied(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class AccessPolicy:
    mode: str = 'none'
    allow: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOW))
    trusted_proxies: list[str] = field(default_factory=list)
    hostnames: list[str] = field(default_factory=list)
    user_header: str = 'Remote-User'
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    def __post_init__(self):
        if self.mode not in ('none', 'authelia'):
            raise ValueError(f"unknown auth mode {self.mode!r}")
        if self.mode == 'authelia' and not self.trusted_proxies:
            raise ValueError("--auth authelia needs --trusted-proxy (the reverse proxy's address)")
        self._allow = _networks(self.allow)
        self._proxies = _networks(self.trusted_proxies)
        names = {'localhost', socket.gethostname().lower(), socket.getfqdn().lower()}
        self._hostnames = names | {h.lower() for h in self.hostnames}

    def _host_ok(self, host: str | None) -> bool:
        if not host:
            return False
        name = host.lower()
        if name.startswith('['):                       # [::1]:8650
            name = name[1:name.find(']')]
        elif name.count(':') == 1:
            name = name.split(':')[0]
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return name in self._hostnames

    def check(self, client: str, headers) -> str | None:
        """Returns the user name (None if anonymous) or raises Denied."""
        if self.mode == 'authelia':
            if not _in(client, self._proxies):
                raise Denied(403, "requests must come through the login proxy")
            user = (headers.get(self.user_header) or '').strip()
            if not user:
                raise Denied(401, "not logged in")
            return user
        if not _in(client, self._allow):
            raise Denied(403, "this address is not allowed to use the dashboard")
        if not self._host_ok(headers.get('Host')):
            raise Denied(403, "unrecognised host name; add it with --hostname")
        return None

    def check_write(self, headers) -> None:
        if not secrets.compare_digest(headers.get('X-CSRF-Token') or '', self.csrf_token):
            raise Denied(403, "missing or wrong CSRF token")
        origin = headers.get('Origin')
        if origin:
            origin_host = origin.split('://', 1)[-1].rstrip('/')
            if origin_host.lower() != (headers.get('Host') or '').lower():
                raise Denied(403, "cross-site request refused")
