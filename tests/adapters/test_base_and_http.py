"""Adapter interface + polite HTTP client tests (all mocked, no network)."""
import pytest

from src.adapters import (
    available_sources,
    create_adapter,
    get_adapter_class,
)
from src.adapters.base import SourceAdapter
from src.adapters.http import FetchError, HttpClient, ManualReviewError
from src.models import Company, ResultStatus, SearchMode, SearchQuery


# ---------------------------------------------------------------------------
# Registry / interface
# ---------------------------------------------------------------------------

def test_builtin_adapters_registered():
    installed = available_sources()
    assert "fixture" in installed
    assert "generic" in installed


def test_unimplemented_sources_have_no_adapter():
    for key in ("greenhouse", "indeed", "linkedin", "workday"):
        assert get_adapter_class(key) is None


def test_create_adapter_unknown_raises():
    with pytest.raises(KeyError):
        create_adapter("does_not_exist")


def test_adapter_interface_is_complete():
    required = {"discover", "search", "fetch_jobs", "normalize", "health_check"}
    assert required <= set(dir(SourceAdapter))


def test_generic_adapter_returns_manual_review_without_network():
    adapter = create_adapter("generic")
    result = adapter.fetch_jobs(Company("Acme Cloud", "acmecloud.example"))
    assert result.status is ResultStatus.MANUAL_REVIEW
    assert result.reason
    assert result.recommended_action


def test_generic_adapter_reports_missing_careers_url():
    adapter = create_adapter("generic")
    result = adapter.discover(Company("No URL Co"))
    assert result.status is ResultStatus.MANUAL_REVIEW
    assert "companies.csv" in (result.recommended_action or "")


def test_fixture_adapter_board_mode_and_data():
    adapter = create_adapter("fixture")
    assert adapter.search_mode is SearchMode.BOARD
    assert adapter.is_test_source is True
    health = adapter.health_check()
    assert health.ok, health.detail
    result = adapter.search(SearchQuery())
    assert result.status is ResultStatus.OK
    assert len(result.jobs) >= 10


def test_fixture_adapter_company_filter():
    adapter = create_adapter("fixture")
    result = adapter.search(SearchQuery(company_name="Acme Cloud"))
    assert result.status is ResultStatus.OK
    assert result.jobs
    assert all("acme cloud" in j.payload["company_name"].lower()
               for j in result.jobs)


# ---------------------------------------------------------------------------
# HttpClient (mocked responses)
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _client(responses, **kwargs):
    session = FakeSession(responses)
    sleeps = []
    kwargs.setdefault("cache_ttl", 0)
    client = HttpClient(session=session, sleep_fn=sleeps.append,
                        clock=lambda: 0.0, **kwargs)
    return client, session, sleeps


def test_http_200_returns_body():
    client, session, _ = _client([FakeResponse(200, "hello")])
    assert client.get("https://example.com/a") == "hello"
    assert session.calls == 1


def test_http_caches_in_memory():
    client, session, _ = _client([FakeResponse(200, "hello")])
    client.get("https://example.com/a")
    client.get("https://example.com/a")
    assert session.calls == 1  # second call served from cache


def test_http_403_raises_manual_review_and_never_retries():
    client, session, _ = _client([FakeResponse(403, "forbidden")],
                                 max_retries=3)
    with pytest.raises(ManualReviewError) as exc:
        client.get("https://example.com/blocked")
    assert exc.value.http_status == 403
    assert session.calls == 1  # no retry on 403


def test_http_429_raises_manual_review():
    client, session, _ = _client([FakeResponse(429, "slow down")])
    with pytest.raises(ManualReviewError):
        client.get("https://example.com/limited")
    assert session.calls == 1


def test_http_captcha_challenge_is_manual_review():
    client, session, _ = _client(
        [FakeResponse(451, "<html>Please complete the CAPTCHA</html>")])
    with pytest.raises(ManualReviewError):
        client.get("https://example.com/captcha")
    assert session.calls == 1


def test_http_500_retries_with_backoff_then_succeeds():
    client, session, sleeps = _client(
        [FakeResponse(500, "err"), FakeResponse(200, "ok")],
        max_retries=2, backoff_factor=2.0)
    assert client.get("https://example.com/flaky") == "ok"
    assert session.calls == 2
    assert sleeps and sleeps[0] == 2.0  # exponential backoff


def test_http_500_exhausted_raises_fetch_error():
    client, session, _ = _client([FakeResponse(500, "err"),
                                  FakeResponse(500, "err")], max_retries=1)
    with pytest.raises(FetchError):
        client.get("https://example.com/down")
    assert session.calls == 2


def test_http_404_raises_fetch_error_without_retry():
    client, session, _ = _client([FakeResponse(404, "gone")])
    with pytest.raises(FetchError):
        client.get("https://example.com/missing")
    assert session.calls == 1


def test_http_rate_limit_sleeps_between_requests():
    client, session, sleeps = _client(
        [FakeResponse(200, "a"), FakeResponse(200, "b")], request_delay=1.5)
    client.get("https://example.com/1")
    client.get("https://example.com/2")
    assert session.calls == 2
    assert 1.5 in sleeps
