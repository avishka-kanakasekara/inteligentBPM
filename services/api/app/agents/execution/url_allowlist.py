"""URL allowlist — arbitrary outbound HTTP is forbidden; SSRF targets blocked."""

from __future__ import annotations

from urllib.parse import urlparse

# Only explicitly allowlisted hosts may appear in tool outputs that reference URLs.
DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "example.supabase.co",
        "storage.googleapis.com",
        "mail.mock.local",
        "suppliers.mock.local",
        "purchasing.mock.local",
    }
)


def get_allowed_hosts() -> frozenset[str]:
    try:
        from app.config import get_settings

        return get_settings().outbound_allowlist_hosts or DEFAULT_ALLOWED_HOSTS
    except Exception:  # noqa: BLE001
        return DEFAULT_ALLOWED_HOSTS


def assert_url_allowed(url: str, *, allowed_hosts: frozenset[str] | None = None) -> None:
    hosts = allowed_hosts or get_allowed_hosts()
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError(f"URL scheme not allowed: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if host not in hosts:
        raise ValueError(f"Outbound URL host not on allowlist: {host}")


def sanitize_outbound_urls(payload: dict, *, allowed_hosts: frozenset[str] | None = None) -> dict:
    """Reject payloads containing non-allowlisted or SSRF-unsafe URLs."""
    from app.security.ssrf import assert_safe_outbound_url

    hosts = allowed_hosts or get_allowed_hosts()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str) and (
                    k.lower() in {"url", "href", "endpoint", "uri"}
                    or v.startswith("http://")
                    or v.startswith("https://")
                ):
                    if v.startswith("http"):
                        assert_safe_outbound_url(v, allowed_hosts=hosts, resolve_dns=False)
                else:
                    walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return payload
