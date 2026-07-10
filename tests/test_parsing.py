from app.parsing import (
    distinct_probe_hosts,
    is_absolute_http_url,
    normalize_name,
    normalize_tags,
    parse_endpoints,
)


def test_parse_endpoints_handles_crlf_and_variable_spacing():
    raw = (
        "GET  https://a.example/one\r\n"
        "POST https://a.example/two\r\n"
        "GET https://b.example/three"
    )
    result = parse_endpoints(raw)
    assert result.n_lines == 3
    assert result.n_failed == 0
    assert [(e.method, e.url) for e in result.endpoints] == [
        ("GET", "https://a.example/one"),
        ("POST", "https://a.example/two"),
        ("GET", "https://b.example/three"),
    ]


def test_parse_endpoints_handles_plain_lf():
    raw = "GET https://a.example/one\nGET https://a.example/two"
    result = parse_endpoints(raw)
    assert result.n_parsed == 2


def test_parse_endpoints_none_and_blank():
    assert parse_endpoints(None).endpoints == []
    assert parse_endpoints("   \r\n  \n").endpoints == []


def test_parse_endpoints_skips_garbage_lines_as_failures():
    raw = "GET https://a.example/one\r\nnot a valid line\r\nPUT https://a.example/two"
    result = parse_endpoints(raw)
    assert result.n_parsed == 2
    assert result.n_failed == 1


def test_parse_endpoints_detects_placeholder():
    result = parse_endpoints("GET https://a.example/contracts/{contract_id}/status")
    assert result.endpoints[0].has_placeholder is True

    result_no_placeholder = parse_endpoints("GET https://a.example/contracts")
    assert result_no_placeholder.endpoints[0].has_placeholder is False


def test_distinct_probe_hosts_dedupes_across_endpoints_and_methods():
    result = parse_endpoints(
        "GET https://a.example/one\r\nPOST https://a.example/two\r\nGET https://b.example/three"
    )
    assert distinct_probe_hosts(result.endpoints) == ["https://a.example", "https://b.example"]


def test_is_absolute_http_url():
    assert is_absolute_http_url("https://a.example/one") is True
    assert is_absolute_http_url("http://a.example") is True
    assert is_absolute_http_url("/leaderboard") is False
    assert is_absolute_http_url("relative/path") is False


def test_distinct_probe_hosts_skips_relative_paths():
    # Observed in the live registry: some skills declare relative-path
    # endpoints (e.g. "GET /leaderboard") with no host of their own.
    result = parse_endpoints("GET /leaderboard\r\nGET https://a.example/two")
    assert distinct_probe_hosts(result.endpoints) == ["https://a.example"]


def test_normalize_tags_comma_and_space_and_null():
    assert normalize_tags("contract, a2a,  SOW") == ["contract", "a2a", "sow"]
    assert normalize_tags("contract a2a SOW") == ["contract", "a2a", "sow"]
    assert normalize_tags(None) == []
    assert normalize_tags("   ") == []


def test_normalize_name():
    assert normalize_name("  TrustLedger  ") == "trustledger"
    assert normalize_name(None) == ""
