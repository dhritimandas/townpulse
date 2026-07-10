"""Pure parsing/normalization helpers for registry skill records.

No I/O; every function here is deterministic and unit-testable in isolation.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Registry lines look like "GET  https://host/path" with variable spacing and
# either \r\n or \n line endings (observed in the live registry snapshot).
_ENDPOINT_LINE_RE = re.compile(r"^\s*(GET|POST|PUT|DELETE|PATCH)\s+(\S+)\s*$")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


@dataclass(frozen=True)
class ParsedEndpoint:
    method: str
    url: str
    has_placeholder: bool


@dataclass(frozen=True)
class EndpointParseResult:
    endpoints: list[ParsedEndpoint]
    n_lines: int
    n_parsed: int
    n_failed: int


def parse_endpoints(raw: str | None) -> EndpointParseResult:
    """Parse a skill's raw multi-line "METHOD URL" endpoints field.

    Lines that don't match the ``METHOD URL`` shape are counted as failures
    and dropped, never raised -- a single malformed line must not take down
    a whole probe cycle.

    Example::

        result = parse_endpoints("GET  https://a.example/one\\r\\nPOST https://a.example/two")
        assert result.n_parsed == 2
    """
    if not raw or not raw.strip():
        return EndpointParseResult(endpoints=[], n_lines=0, n_parsed=0, n_failed=0)

    lines = [ln for ln in re.split(r"\r\n|\r|\n", raw) if ln.strip()]
    endpoints: list[ParsedEndpoint] = []
    n_failed = 0
    for line in lines:
        match = _ENDPOINT_LINE_RE.match(line)
        if not match:
            n_failed += 1
            continue
        method, url = match.group(1), match.group(2)
        endpoints.append(
            ParsedEndpoint(
                method=method,
                url=url,
                has_placeholder=bool(_PLACEHOLDER_RE.search(url)),
            )
        )
    return EndpointParseResult(
        endpoints=endpoints, n_lines=len(lines), n_parsed=len(endpoints), n_failed=n_failed
    )


def normalize_tags(raw: str | None) -> list[str]:
    """Normalize a free-text tags field into a lowercase token list.

    The registry stores tags as an unstructured string, sometimes
    comma-separated, sometimes space-separated, sometimes both, sometimes
    null.

    Example::

        assert normalize_tags("Escrow,  Payments") == ["escrow", "payments"]
    """
    if not raw:
        return []
    tokens = re.split(r"[,\s]+", raw.strip().lower())
    return [t for t in tokens if t]


def normalize_name(name: str | None) -> str:
    """Lowercase, trimmed name used to group resubmissions of the same skill."""
    return (name or "").strip().lower()


def is_absolute_http_url(url: str) -> bool:
    """True if the URL has an http(s) scheme and a host, so it's directly
    probeable. Some registry entries declare relative paths (e.g.
    ``/leaderboard``) as endpoints, which have no host to probe.
    """
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def distinct_probe_hosts(endpoints: list[ParsedEndpoint]) -> list[str]:
    """Return the sorted, deduplicated ``scheme://netloc`` for every endpoint
    URL, regardless of method -- the root-of-host probe target derives from
    every declared endpoint, not just the ones we're allowed to GET.
    """
    hosts: set[str] = set()
    for endpoint in endpoints:
        if is_absolute_http_url(endpoint.url):
            parts = urlsplit(endpoint.url)
            hosts.add(f"{parts.scheme}://{parts.netloc}")
    return sorted(hosts)
