"""Async probe pool enforcing the probe policy exactly (spec §3):

GET-only, never substitute {placeholder} values, never attempt auth, single
attempt per cycle, 10s timeout, global concurrency <= 8, >=20s spacing
between requests to the same host.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.config import (
    PROBE_CONCURRENCY,
    PROBE_HOST_SPACING_SECONDS,
    PROBE_TIMEOUT_SECONDS,
    USER_AGENT,
)

# Root-URL ("host" kind) probes accept these as evidence the host is up even
# though they aren't 2xx: the service answered, it just refused an
# unauthenticated request we never intended to authenticate. Docs and
# declared-endpoint probes don't get this allowance -- a 401/403/405 there
# is a real defect, not proof of life.
HOST_ALIVE_STATUS_CODES = frozenset({401, 403, 405})


@dataclass(frozen=True)
class ProbeTarget:
    skill_id: str
    target: str
    kind: str  # "docs" | "host" | "endpoint"


@dataclass(frozen=True)
class ProbeResult:
    skill_id: str
    target: str
    kind: str
    ts: str
    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None


class HostRateLimiter:
    """Serializes requests per host so consecutive requests to the same host
    are spaced by at least ``min_interval`` seconds. Different hosts run
    independently of each other and of this spacing.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._last_issued: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait_turn(self, host: str) -> None:
        async with self._locks[host]:
            now = time.monotonic()
            last = self._last_issued.get(host)
            if last is not None:
                elapsed = now - last
                if elapsed < self._min_interval:
                    await asyncio.sleep(self._min_interval - elapsed)
            self._last_issued[host] = time.monotonic()


def _host_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


async def _probe_one(
    client: httpx.AsyncClient,
    target: ProbeTarget,
    ts: str,
    semaphore: asyncio.Semaphore,
    limiter: HostRateLimiter,
) -> ProbeResult:
    await limiter.wait_turn(_host_of(target.target))
    async with semaphore:
        start = time.monotonic()
        try:
            resp = await client.get(target.target)
        except httpx.HTTPError as exc:
            return ProbeResult(
                skill_id=target.skill_id,
                target=target.target,
                kind=target.kind,
                ts=ts,
                ok=False,
                status_code=None,
                latency_ms=None,
                error=str(exc),
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        ok = resp.status_code < 400 or (
            target.kind == "host" and resp.status_code in HOST_ALIVE_STATUS_CODES
        )
        return ProbeResult(
            skill_id=target.skill_id,
            target=target.target,
            kind=target.kind,
            ts=ts,
            ok=ok,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            error=None,
        )


async def run_probe_cycle(
    targets: list[ProbeTarget],
    ts: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ProbeResult]:
    """Run every target exactly once, respecting global concurrency and
    per-host spacing. Returns one ProbeResult per target, in the same order
    as ``targets`` (asyncio.gather preserves input order).
    """
    semaphore = asyncio.Semaphore(PROBE_CONCURRENCY)
    limiter = HostRateLimiter(PROBE_HOST_SPACING_SECONDS)

    async def _run(active_client: httpx.AsyncClient) -> list[ProbeResult]:
        tasks = [_probe_one(active_client, t, ts, semaphore, limiter) for t in targets]
        return list(await asyncio.gather(*tasks))

    if client is not None:
        return await _run(client)

    timeout = httpx.Timeout(PROBE_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as new_client:
        return await _run(new_client)
