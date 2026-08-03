import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    pass


def validate_public_http_url(url):
    """Reject unsupported schemes and hostnames resolving to non-public IPs."""
    try:
        parsed = urlsplit((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UnsafeURLError("URL must use HTTP or HTTPS and include a hostname")
        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise UnsafeURLError("Localhost URLs are not allowed")
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not address.is_global:
                raise UnsafeURLError("Private, loopback, and link-local targets are not allowed")
        return parsed.geturl()
    except (socket.gaierror, ValueError) as exc:
        if isinstance(exc, UnsafeURLError):
            raise
        raise UnsafeURLError("URL hostname could not be validated") from exc
