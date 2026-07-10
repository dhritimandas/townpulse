"""Deterministic score computation (spec TOWN_PULSE_SPEC.md §4).

Pure functions; no DB or network access, so the score formula is directly
testable against fixed fixtures.
"""

import statistics

LATENCY_CLAMP_MS = 5000.0
WEIGHT_ALIVE = 0.40
WEIGHT_UPTIME_24H = 0.35
WEIGHT_DOCS_OK = 0.15
WEIGHT_LATENCY = 0.10


def latency_point(p50_latency_ms: float | None) -> float:
    """clamp(1 - p50_latency_ms/5000, 0, 1); no evidence of latency -> 0."""
    if p50_latency_ms is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - p50_latency_ms / LATENCY_CLAMP_MS))


def median_latency(latencies_ms: list[int]) -> float | None:
    """Median of successful-probe latencies, or None with no evidence."""
    if not latencies_ms:
        return None
    return statistics.median(latencies_ms)


def compute_score(
    *,
    alive_now: bool,
    uptime_24h: float,
    docs_ok: bool,
    p50_latency_ms: float | None,
) -> float:
    """score = 100 * (0.40*alive_now + 0.35*uptime_24h + 0.15*docs_ok + 0.10*latency_pt)."""
    return 100.0 * (
        WEIGHT_ALIVE * (1.0 if alive_now else 0.0)
        + WEIGHT_UPTIME_24H * uptime_24h
        + WEIGHT_DOCS_OK * (1.0 if docs_ok else 0.0)
        + WEIGHT_LATENCY * latency_point(p50_latency_ms)
    )
