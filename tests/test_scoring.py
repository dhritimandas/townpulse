from app.scoring import compute_score, latency_point, median_latency


def test_latency_point_clamped():
    assert latency_point(None) == 0.0
    assert latency_point(0) == 1.0
    assert latency_point(5000) == 0.0
    assert latency_point(10000) == 0.0
    assert latency_point(2500) == 0.5


def test_median_latency():
    assert median_latency([]) is None
    assert median_latency([100]) == 100
    assert median_latency([100, 200, 300]) == 200


def test_compute_score_all_good():
    score = compute_score(alive_now=True, uptime_24h=1.0, docs_ok=True, p50_latency_ms=0)
    assert score == 100.0


def test_compute_score_all_bad():
    score = compute_score(alive_now=False, uptime_24h=0.0, docs_ok=False, p50_latency_ms=None)
    assert score == 0.0


def test_compute_score_weights_isolated():
    assert compute_score(alive_now=True, uptime_24h=0.0, docs_ok=False, p50_latency_ms=None) == 40.0
    assert compute_score(alive_now=False, uptime_24h=1.0, docs_ok=False, p50_latency_ms=None) == 35.0
    assert compute_score(alive_now=False, uptime_24h=0.0, docs_ok=True, p50_latency_ms=None) == 15.0
    assert compute_score(alive_now=False, uptime_24h=0.0, docs_ok=False, p50_latency_ms=0) == 10.0
