from __future__ import annotations

import pytest
import requests

from src.pig_cycle.sow_discovery import (
    MAX_REQUESTS_PER_RUN,
    RequestBudgetExceeded,
    SowDiscoveryError,
    discover_latest_sow_record,
    extract_sow_candidate_urls,
)
from src.pig_cycle.sow_monthly import SowSourceType


INDEX_URL = "https://www.moa.gov.cn/news/index.html"


def _article(month: str, inventory: int = 3996) -> bytes:
    year, month_number = month.split("-")
    return f"""<html><body><div>发布时间：{year}-{month_number}-20</div>
    <p>{year}年{int(month_number)}月末全国能繁母猪存栏{inventory}万头。</p>
    </body></html>""".encode()


class _Response:
    def __init__(self, content: bytes, *, url: str, status: int = 200) -> None:
        self.content = content
        self.url = url
        self.status_code = status
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float, allow_redirects: bool) -> _Response:
        self.calls.append(url)
        assert len(self.calls) <= MAX_REQUESTS_PER_RUN
        assert timeout > 0
        assert allow_redirects is False
        if url not in self.responses:
            raise AssertionError(f"Unexpected request: {url}")
        return self.responses[url]


def _index(*links: tuple[str, str]) -> bytes:
    return "".join(f'<a href="{href}">{title}</a>' for href, title in links).encode()


def _session(index: bytes, articles: dict[str, bytes | tuple[bytes, int]]) -> _Session:
    responses = {INDEX_URL: _Response(index, url=INDEX_URL)}
    for url, value in articles.items():
        content, status = value if isinstance(value, tuple) else (value, 200)
        responses[url] = _Response(content, url=url, status=status)
    return _Session(responses)


def test_single_index_parsing_and_relative_url_resolution() -> None:
    html = _index(("../2026/report.html", "生猪生产情况")).decode()

    candidates = extract_sow_candidate_urls(html, index_url=INDEX_URL)

    assert candidates == ["https://www.moa.gov.cn/2026/report.html"]


def test_non_official_candidate_is_rejected() -> None:
    html = _index(
        ("https://example.com/report", "生猪生产情况"),
        ("/official.html", "农业生产情况"),
    ).decode()

    assert extract_sow_candidate_urls(html, index_url=INDEX_URL) == [
        "https://www.moa.gov.cn/official.html"
    ]


def test_only_two_candidates_are_selected() -> None:
    html = _index(
        ("/a.html", "生猪生产情况"),
        ("/b.html", "农业经济运行"),
        ("/c.html", "畜牧生产情况"),
    ).decode()

    assert extract_sow_candidate_urls(html, index_url=INDEX_URL) == [
        "https://www.moa.gov.cn/a.html",
        "https://www.moa.gov.cn/b.html",
    ]


@pytest.mark.parametrize("value", [0, 6, 100])
def test_max_requests_outside_hard_range_is_rejected(value: int) -> None:
    session = _session(b"", {})

    with pytest.raises(ValueError, match="max_requests"):
        discover_latest_sow_record(INDEX_URL, max_requests=value, session=session)

    assert session.calls == []


@pytest.mark.parametrize("value", [0, 3])
def test_max_candidates_outside_hard_range_is_rejected(value: int) -> None:
    session = _session(b"", {})

    with pytest.raises(ValueError, match="max_candidates"):
        discover_latest_sow_record(INDEX_URL, max_candidates=value, session=session)

    assert session.calls == []


def test_index_and_one_successful_candidate_use_two_requests() -> None:
    article_url = "https://www.moa.gov.cn/a.html"
    session = _session(_index((article_url, "生猪生产情况")), {article_url: _article("2026-05")})

    record = discover_latest_sow_record(INDEX_URL, session=session)

    assert record.month == "2026-05"
    assert session.calls == [INDEX_URL, article_url]


def test_second_candidate_is_tried_after_first_has_no_sow_data() -> None:
    first = "https://www.moa.gov.cn/a.html"
    second = "https://www.moa.gov.cn/b.html"
    session = _session(
        _index((first, "生猪生产情况"), (second, "农业生产情况")),
        {first: "<p>普通农业新闻</p>".encode("utf-8"), second: _article("2026-05")},
    )

    record = discover_latest_sow_record(INDEX_URL, session=session)

    assert record.month == "2026-05"
    assert session.calls == [INDEX_URL, first, second]


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_candidate_stops_discovery(status: int) -> None:
    first = "https://www.moa.gov.cn/a.html"
    second = "https://www.moa.gov.cn/b.html"
    session = _session(
        _index((first, "生猪生产情况"), (second, "农业生产情况")),
        {first: (b"blocked", status), second: _article("2026-05")},
    )

    with pytest.raises(SowDiscoveryError, match="blocked"):
        discover_latest_sow_record(INDEX_URL, session=session)

    assert session.calls == [INDEX_URL, first]


def test_budget_exhaustion_prevents_next_request() -> None:
    first = "https://www.moa.gov.cn/a.html"
    second = "https://www.moa.gov.cn/b.html"
    session = _session(
        _index((first, "生猪生产情况"), (second, "农业生产情况")),
        {first: "<p>普通农业新闻</p>".encode("utf-8"), second: _article("2026-05")},
    )

    with pytest.raises(RequestBudgetExceeded, match="budget exhausted"):
        discover_latest_sow_record(INDEX_URL, max_requests=2, session=session)

    assert session.calls == [INDEX_URL, first]


def test_known_url_is_skipped_without_article_request() -> None:
    known = "https://www.moa.gov.cn/a.html"
    fresh = "https://www.moa.gov.cn/b.html"
    session = _session(
        _index((known, "生猪生产情况"), (fresh, "农业生产情况")),
        {fresh: _article("2026-05")},
    )

    record = discover_latest_sow_record(INDEX_URL, known_urls={known}, session=session)

    assert record.month == "2026-05"
    assert session.calls == [INDEX_URL, fresh]


def test_newer_month_wins_when_two_candidates_parse() -> None:
    first = "https://www.moa.gov.cn/a.html"
    second = "https://www.moa.gov.cn/b.html"
    session = _session(
        _index((first, "生猪生产情况"), (second, "农业生产情况")),
        {first: _article("2026-05"), second: _article("2026-06")},
    )

    record = discover_latest_sow_record(INDEX_URL, session=session)

    assert record.month == "2026-06"
    assert len(session.calls) == 3


def test_nbs_wins_same_quarter_end_month() -> None:
    moa_url = "https://www.moa.gov.cn/a.html"
    nbs_url = "https://www.stats.gov.cn/b.html"
    session = _session(
        _index((moa_url, "生猪生产情况"), (nbs_url, "国民经济运行")),
        {moa_url: _article("2026-06", 3800), nbs_url: _article("2026-06", 3780)},
    )

    record = discover_latest_sow_record(INDEX_URL, session=session)

    assert record.source_type is SowSourceType.NBS
    assert record.sow_inventory == 3780


def test_no_pagination_url_is_ever_requested() -> None:
    article_url = "https://www.moa.gov.cn/a.html"
    session = _session(_index((article_url, "生猪生产情况")), {article_url: _article("2026-05")})

    discover_latest_sow_record(INDEX_URL, session=session)

    assert all("index_" not in url for url in session.calls)
    assert len(session.calls) <= MAX_REQUESTS_PER_RUN
