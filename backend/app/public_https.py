"""Bounded HTTPS requests to merchant-supplied public endpoints."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit


def endpoint(url):
    if not isinstance(url, str) or not url.isascii() or any(ord(char) <= 32 or char == "\\" for char in url):
        raise ValueError("Enter a public HTTPS URL")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443)
            or parts.username is not None or parts.password is not None or parts.fragment):
        raise ValueError("Enter a public HTTPS URL on port 443")
    return parts


def _addresses(host):
    try:
        addresses = tuple(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(
            host, 443, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise ValueError("The public endpoint could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError("The endpoint must resolve only to public addresses")
    if not addresses:
        raise ValueError("The public endpoint could not be resolved")
    return addresses


def verify_url(url):
    _addresses(endpoint(url).hostname)


def request(method, url, *, body=None, headers=None, limit=1024 * 1024):
    parts = endpoint(url)
    address = _addresses(parts.hostname)[0]
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    client = http.client.HTTPSConnection(parts.hostname, 443, timeout=8, context=ssl.create_default_context())
    # Pin the validated address while keeping TLS certificate and SNI checks on the hostname.
    client._create_connection = lambda _address, timeout, source: socket.create_connection(
        (address, 443), timeout, source)
    try:
        client.request(method, target, body=body, headers=headers or {})
        response = client.getresponse()
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("The endpoint response is too large")
        return response.status, dict(response.getheaders()), payload
    finally:
        client.close()
