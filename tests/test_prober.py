import time

import httpx
import respx

from app.prober import ProbeTarget, run_probe_cycle


@respx.mock
async def test_ok_probe_records_status_and_latency():
    respx.get("https://a.example/skill.md").mock(return_value=httpx.Response(200))
    targets = [ProbeTarget(skill_id="s1", target="https://a.example/skill.md", kind="docs")]

    results = await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")

    assert len(results) == 1
    result = results[0]
    assert result.ok is True
    assert result.status_code == 200
    assert result.latency_ms is not None
    assert result.error is None


@respx.mock
async def test_host_probe_401_counts_as_alive():
    respx.get("https://a.example/").mock(return_value=httpx.Response(401))
    targets = [ProbeTarget(skill_id="s1", target="https://a.example/", kind="host")]

    results = await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")

    assert results[0].ok is True
    assert results[0].status_code == 401


@respx.mock
async def test_endpoint_probe_401_does_not_count_as_alive():
    respx.get("https://a.example/secret").mock(return_value=httpx.Response(401))
    targets = [ProbeTarget(skill_id="s1", target="https://a.example/secret", kind="endpoint")]

    results = await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")

    assert results[0].ok is False


@respx.mock
async def test_connection_error_records_not_ok_with_error_message():
    respx.get("https://dead.example/").mock(side_effect=httpx.ConnectError("boom"))
    targets = [ProbeTarget(skill_id="s1", target="https://dead.example/", kind="host")]

    results = await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")

    assert results[0].ok is False
    assert results[0].status_code is None
    assert results[0].error is not None


@respx.mock
async def test_per_host_spacing_is_enforced(monkeypatch):
    """Two targets on the same host must not fire within the spacing window."""
    import app.prober as prober_module

    monkeypatch.setattr(prober_module, "PROBE_HOST_SPACING_SECONDS", 0.2)
    respx.get("https://a.example/one").mock(return_value=httpx.Response(200))
    respx.get("https://a.example/two").mock(return_value=httpx.Response(200))

    targets = [
        ProbeTarget(skill_id="s1", target="https://a.example/one", kind="endpoint"),
        ProbeTarget(skill_id="s1", target="https://a.example/two", kind="endpoint"),
    ]

    start = time.monotonic()
    await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.2


@respx.mock
async def test_different_hosts_are_not_spaced_apart(monkeypatch):
    import app.prober as prober_module

    monkeypatch.setattr(prober_module, "PROBE_HOST_SPACING_SECONDS", 5.0)
    respx.get("https://a.example/one").mock(return_value=httpx.Response(200))
    respx.get("https://b.example/one").mock(return_value=httpx.Response(200))

    targets = [
        ProbeTarget(skill_id="s1", target="https://a.example/one", kind="endpoint"),
        ProbeTarget(skill_id="s2", target="https://b.example/one", kind="endpoint"),
    ]

    start = time.monotonic()
    await run_probe_cycle(targets, ts="2026-07-10T10:00:00+00:00")
    elapsed = time.monotonic() - start
    assert elapsed < 5.0
