from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
import requests

from src.pig_cycle.moa_weekly import (
    DEFAULT_USER_AGENT,
    MAX_HISTORY_ARTICLES,
    MAX_HISTORY_PAGES,
    MAX_HISTORY_REQUESTS,
    MoaWeeklyDataError,
    _get_html,
    discover_weekly_article_urls,
    fetch_latest_weekly_increment,
    fetch_recent_weekly_records,
    iter_recent_weekly_records,
    parse_weekly_record,
    sort_and_deduplicate_records,
)


def _article_html(publish_date: str, intro: str, prices: str) -> str:
    return f"""<html><head><title>畜产品和饲料集贸市场价格情况</title></head><body>
    <div>发布时间：{publish_date}</div><p>{intro}</p><p>{prices}</p></body></html>"""


PRICES_JULY = (
    "全国仔猪平均价格21.64元/公斤，全国生猪平均价格10.48元/公斤。"
    "全国玉米平均价格2.48元/公斤，全国豆粕平均价格3.18元/公斤，"
    "育肥猪配合饲料平均价格3.36元/公斤。"
)


def test_parse_weekly_record_uses_body_collection_date() -> None:
    record = parse_weekly_record(
        _article_html("2026-07-07", "7月第1周（采集日为7月2日）", PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/example.htm",
    )
    assert record.collection_date == date(2026, 7, 2)
    assert record.publish_date == date(2026, 7, 7)
    assert record.period_label == "7月第1周"
    assert (record.piglet_price, record.live_hog_price, record.corn_price) == (21.64, 10.48, 2.48)
    assert (record.soybean_meal_price, record.fattening_feed_price) == (3.18, 3.36)


def test_parse_collection_date_across_realistic_html_text_nodes() -> None:
    intro = (
        "<span>7月第5周</span>"
        "<span>（采集日</span><span>为</span>"
        "<span>7月</span><span>30日）</span>"
    )

    record = parse_weekly_record(
        _article_html("2026-08-04", intro, PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/realistic-nodes.htm",
    )

    assert record.collection_date == date(2026, 7, 30)
    assert record.period_label == "7月第5周"


def test_parse_collection_date_with_spaces_and_nbsp() -> None:
    intro = "7\xa0月 第\xa05 周 (采集日\xa0为 7\xa0月 30\xa0日)"

    record = parse_weekly_record(
        _article_html("2026-08-04", intro, PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/spaced.htm",
    )

    assert record.collection_date == date(2026, 7, 30)
    assert record.period_label == "7月第5周"


def test_parse_prices_across_realistic_html_text_nodes() -> None:
    prices = """
        <span>全国</span><span>仔猪</span><span>平均价格</span>
        <span>23.00</span><span>元</span><span>/</span><span>公斤</span>
        <span>全国</span><span>生猪</span><span>平均价格</span>
        <span>14.25</span><span>元</span><span>/</span><span>公斤</span>
        <span>全国</span><span>玉米</span><span>平均价格</span>
        <span>2.50</span><span>元</span><span>/</span><span>公斤</span>
        <span>全国</span><span>豆粕</span><span>平均价格</span>
        <span>3.23</span><span>元</span><span>/</span><span>公斤</span>
        <span>育肥猪配合饲料</span><span>平均价格</span>
        <span>3.36</span><span>元</span><span>/</span><span>公斤</span>
    """

    record = parse_weekly_record(
        _article_html("2026-08-04", "7月第5周（采集日为7月30日）", prices),
        source_url="https://xmsyj.moa.gov.cn/jcyj/realistic-prices.htm",
    )

    assert record.piglet_price == 23.00
    assert record.live_hog_price == 14.25
    assert record.corn_price == 2.50
    assert record.soybean_meal_price == 3.23
    assert record.fattening_feed_price == 3.36


def test_parse_previous_week_prices_and_collection_date() -> None:
    prices = (
        "全国仔猪平均价格21.67元/公斤；全国生猪平均价格10.06元/公斤；"
        "全国玉米平均价格2.48元/公斤；全国豆粕平均价格3.18元/公斤；"
        "育肥猪配合饲料平均价格3.36元/公斤。"
    )
    record = parse_weekly_record(
        _article_html("2026-07-01", "6月第4周（采集日为6月25日）", prices),
        source_url="https://xmsyj.moa.gov.cn/jcyj/example-2.htm",
    )
    assert record.collection_date == date(2026, 6, 25)
    assert (record.piglet_price, record.live_hog_price, record.corn_price) == (21.67, 10.06, 2.48)
    assert (record.soybean_meal_price, record.fattening_feed_price) == (3.18, 3.36)


def test_derived_pig_corn_ratio_keeps_float_precision() -> None:
    record = parse_weekly_record(
        _article_html("2026-07-07", "7月第1周（采集日为7月2日）", PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/example.htm",
    )
    assert record.derived_pig_corn_ratio == pytest.approx(10.48 / 2.48)


def test_index_discovery_selects_weekly_report_and_excludes_slaughter_price() -> None:
    html = """<ul>
      <li><a href="./202607/t20260707_1.htm">7月第1周畜产品和饲料集贸市场价格情况</a></li>
      <li><a href="./202607/t20260707_2.htm">生猪定点屠宰企业生猪收购和白条肉出厂价格情况</a></li>
      <li><a href="./other.htm">其他监测信息</a></li>
    </ul>"""
    assert discover_weekly_article_urls(html) == [
        "https://xmsyj.moa.gov.cn/jcyj/202607/t20260707_1.htm"
    ]


def test_records_are_sorted_and_deduplicated_by_collection_date() -> None:
    first = parse_weekly_record(
        _article_html("2026-07-07", "7月第1周（采集日为7月2日）", PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/old.htm",
    )
    earlier = replace(first, collection_date=date(2026, 6, 25), publish_date=date(2026, 7, 1))
    corrected = replace(first, publish_date=date(2026, 7, 8), source_url="https://xmsyj.moa.gov.cn/jcyj/new.htm")
    result = sort_and_deduplicate_records([first, earlier, corrected])
    assert [item.collection_date for item in result] == [date(2026, 6, 25), date(2026, 7, 2)]
    assert result[1].source_url.endswith("new.htm")


def test_january_publication_can_have_previous_year_collection_date() -> None:
    record = parse_weekly_record(
        _article_html("2026-01-06", "12月第5周（采集日为12月31日）", PRICES_JULY),
        source_url="https://xmsyj.moa.gov.cn/jcyj/cross-year.htm",
    )
    assert record.collection_date == date(2025, 12, 31)
    assert record.publish_date == date(2026, 1, 6)


def test_missing_required_price_raises_instead_of_filling_zero() -> None:
    missing_corn = "全国仔猪平均价格21.64元/公斤，全国生猪平均价格10.48元/公斤。"
    with pytest.raises(MoaWeeklyDataError, match="corn_price"):
        parse_weekly_record(
            _article_html("2026-07-07", "7月第1周（采集日为7月2日）", missing_corn),
            source_url="https://xmsyj.moa.gov.cn/jcyj/broken.htm",
        )


def test_optional_historical_prices_are_none_when_absent() -> None:
    core_prices = (
        "全国仔猪平均价格21.64元/公斤，全国生猪平均价格10.48元/公斤，"
        "全国玉米平均价格2.48元/公斤。"
    )
    record = parse_weekly_record(
        _article_html("2026-07-07", "7月第1周（采集日为7月2日）", core_prices),
        source_url="https://xmsyj.moa.gov.cn/jcyj/historical.htm",
    )
    assert record.soybean_meal_price is None
    assert record.fattening_feed_price is None


class _FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        encoding: str = "utf-8",
        apparent_encoding: str = "utf-8",
        status_code: int = 200,
        url: str = "https://xmsyj.moa.gov.cn/jcyj/example.htm",
    ) -> None:
        self.content = text.encode("utf-8")
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding
        self.status_code = status_code
        self.url = url

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, pages: dict[str, str | _FakeResponse]) -> None:
        self.pages = pages
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, float, bool]] = []

    def get(self, url: str, *, timeout: float, allow_redirects: bool) -> _FakeResponse:
        self.calls.append((url, timeout, allow_redirects))
        value = self.pages[url]
        if isinstance(value, _FakeResponse):
            return value
        return _FakeResponse(value, url=url)

    def close(self) -> None:
        pass


def test_http_layer_decodes_utf8_bytes_despite_iso_8859_1_response_encoding() -> None:
    html = _article_html(
        "2026-08-04",
        "7月第5周（采集日为7月30日）",
        PRICES_JULY,
    )
    response = _FakeResponse(
        html,
        encoding="ISO-8859-1",
        apparent_encoding="utf-8",
    )
    session = _FakeSession({})
    session.get = lambda url, *, timeout, allow_redirects: response

    decoded_html = _get_html(session, "https://xmsyj.moa.gov.cn/jcyj/example.htm", 7.5)
    record = parse_weekly_record(
        decoded_html,
        source_url="https://xmsyj.moa.gov.cn/jcyj/example.htm",
    )

    assert "7月第5周（采集日为7月30日）" in decoded_html
    assert record.collection_date == date(2026, 7, 30)


def test_fetcher_paginates_with_timeout_and_returns_sorted_unique_records() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first_article = f"{base}202607/first.htm"
    duplicate_article = f"{base}202607/corrected.htm"
    earlier_article = f"{base}202607/earlier.htm"
    pages = {
        base: f'<a href="{first_article}">7月第1周畜产品和饲料集贸市场价格情况</a>',
        first_article: _article_html("2026-07-07", "7月第1周（采集日为7月2日）", PRICES_JULY),
        f"{base}index_1.htm": (
            f'<a href="{duplicate_article}">7月第1周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{earlier_article}">6月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        duplicate_article: _article_html("2026-07-08", "7月第1周（采集日为7月2日）", PRICES_JULY),
        earlier_article: _article_html(
            "2026-07-01",
            "6月第4周（采集日为6月25日）",
            PRICES_JULY,
        ),
    }
    session = _FakeSession(pages)

    records = fetch_recent_weekly_records(min_weeks=2, max_pages=2, timeout=7.5, session=session)

    assert [record.collection_date for record in records] == [date(2026, 6, 25), date(2026, 7, 2)]
    assert records[-1].publish_date == date(2026, 7, 8)
    assert all(timeout == 7.5 for _, timeout, _ in session.calls)
    assert all(allow_redirects is False for _, _, allow_redirects in session.calls)
    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_fetcher_reports_when_max_pages_cannot_supply_requested_weeks() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    session = _FakeSession({base: "<html><body>no target reports</body></html>"})

    with pytest.raises(MoaWeeklyDataError, match=r"Only found 0.*scanning 1.*required 1"):
        fetch_recent_weekly_records(min_weeks=1, max_pages=1, session=session)


def test_incremental_fetches_only_homepage_when_there_is_no_new_article() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    session = _FakeSession({base: "<html><body>no reports</body></html>"})

    assert fetch_latest_weekly_increment(session=session) is None
    assert [url for url, _, _ in session.calls] == [base]


def test_incremental_fetches_at_most_one_new_article() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first = f"{base}first.htm"
    second = f"{base}second.htm"
    session = _FakeSession({
        base: (
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{second}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })

    record = fetch_latest_weekly_increment(session=session)

    assert record is not None and record.collection_date == date(2026, 7, 30)
    assert [url for url, _, _ in session.calls] == [base, first]
    assert all("index_1" not in url for url, _, _ in session.calls)


def test_incremental_skips_known_url_before_requesting_one_unknown_article() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    known = f"{base}known.htm"
    fresh = f"{base}fresh.htm"
    session = _FakeSession({
        base: (
            f'<a href="{known}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{fresh}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        fresh: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })

    record = fetch_latest_weekly_increment(known_urls={known}, session=session)

    assert record is not None
    assert [url for url, _, _ in session.calls] == [base, fresh]


def test_incremental_known_date_returns_none_without_requesting_second_article() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first = f"{base}first.htm"
    second = f"{base}second.htm"
    session = _FakeSession({
        base: (
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{second}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })

    assert fetch_latest_weekly_increment(known_dates={date(2026, 7, 30)}, session=session) is None
    assert [url for url, _, _ in session.calls] == [base, first]


def test_incremental_rejects_third_party_candidate_without_requesting_it() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    third_party = "https://example.com/report.htm"
    session = _FakeSession({
        base: f'<a href="{third_party}">7月第5周畜产品和饲料集贸市场价格情况</a>',
    })

    assert fetch_latest_weekly_increment(session=session) is None
    assert [url for url, _, _ in session.calls] == [base]


@pytest.mark.parametrize("status", [403, 429])
def test_incremental_block_status_stops_immediately(status: int) -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    article = f"{base}blocked.htm"
    session = _FakeSession({
        base: f'<a href="{article}">7月第5周畜产品和饲料集贸市场价格情况</a>',
        article: _FakeResponse("blocked", status_code=status, url=article),
    })

    with pytest.raises(MoaWeeklyDataError, match=str(status)):
        fetch_latest_weekly_increment(session=session)

    assert [url for url, _, _ in session.calls] == [base, article]


def test_redirect_is_not_followed() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    article = f"{base}redirect.htm"
    session = _FakeSession({
        base: f'<a href="{article}">7月第5周畜产品和饲料集贸市场价格情况</a>',
        article: _FakeResponse("redirect", status_code=302, url=article),
    })

    with pytest.raises(MoaWeeklyDataError, match="redirect"):
        fetch_latest_weekly_increment(session=session)

    assert [url for url, _, _ in session.calls] == [base, article]
    assert all(allow_redirects is False for _, _, allow_redirects in session.calls)


def test_incremental_captcha_page_stops_after_homepage() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    session = _FakeSession({base: "<p>请先完成人机验证</p>"})

    with pytest.raises(MoaWeeklyDataError, match="captcha"):
        fetch_latest_weekly_increment(session=session)

    assert [url for url, _, _ in session.calls] == [base]


def test_history_parameter_hard_limits() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    session = _FakeSession({base: ""})

    with pytest.raises(ValueError, match="max_pages"):
        fetch_recent_weekly_records(max_pages=MAX_HISTORY_PAGES + 1, session=session)
    with pytest.raises(ValueError, match="max_articles"):
        fetch_recent_weekly_records(max_articles=MAX_HISTORY_ARTICLES + 1, session=session)
    with pytest.raises(ValueError, match="max_requests"):
        fetch_recent_weekly_records(max_requests=MAX_HISTORY_REQUESTS + 1, session=session)
    assert session.calls == []


def test_history_request_budget_prevents_article_request() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    article = f"{base}article.htm"
    session = _FakeSession({
        base: f'<a href="{article}">7月第5周畜产品和饲料集贸市场价格情况</a>',
    })

    with pytest.raises(MoaWeeklyDataError, match="request budget exhausted"):
        fetch_recent_weekly_records(min_weeks=1, max_pages=1, max_requests=1, session=session)

    assert [url for url, _, _ in session.calls] == [base]


def test_history_article_limit_is_hard() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first = f"{base}first.htm"
    second = f"{base}second.htm"
    session = _FakeSession({
        base: (
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{second}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })

    with pytest.raises(MoaWeeklyDataError, match="article limit exhausted"):
        fetch_recent_weekly_records(
            min_weeks=2,
            max_pages=1,
            max_articles=1,
            session=session,
        )

    assert [url for url, _, _ in session.calls] == [base, first]


def test_history_stops_immediately_after_reaching_min_weeks() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first = f"{base}first.htm"
    second = f"{base}second.htm"
    session = _FakeSession({
        base: (
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{second}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })

    records = fetch_recent_weekly_records(min_weeks=1, max_pages=1, session=session)

    assert len(records) == 1
    assert [url for url, _, _ in session.calls] == [base, first]


def test_history_iterator_streams_unknown_articles_without_date_deduplication() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    known = f"{base}known.htm"
    first = f"{base}first.htm"
    correction = f"{base}correction.htm"
    session = _FakeSession({
        base: (
            f'<a href="{known}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{correction}">7月第5周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
        correction: _article_html("2026-08-05", "7月第5周（采集日为7月30日）", PRICES_JULY),
    })
    records = iter_recent_weekly_records(
        known_urls={known}, max_pages=1, max_articles=2, max_requests=3, session=session
    )

    first_record = next(records)
    assert first_record.source_url == first
    assert [url for url, _, _ in session.calls] == [base, first]
    second_record = next(records)
    assert second_record.source_url == correction
    assert first_record.collection_date == second_record.collection_date
    assert [url for url, _, _ in session.calls] == [base, first, correction]
    records.close()


def test_history_iterator_request_and_article_limits_are_hard() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    first = f"{base}first.htm"
    second = f"{base}second.htm"
    pages = {
        base: (
            f'<a href="{first}">7月第5周畜产品和饲料集贸市场价格情况</a>'
            f'<a href="{second}">7月第4周畜产品和饲料集贸市场价格情况</a>'
        ),
        first: _article_html("2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY),
    }
    session = _FakeSession(pages)
    records = iter_recent_weekly_records(
        max_pages=1, max_articles=1, max_requests=2, session=session
    )
    assert next(records).source_url == first
    with pytest.raises(MoaWeeklyDataError, match="article limit exhausted"):
        next(records)
    assert [url for url, _, _ in session.calls] == [base, first]

    budget_session = _FakeSession(pages)
    budget_records = iter_recent_weekly_records(
        max_pages=1, max_articles=2, max_requests=1, session=budget_session
    )
    with pytest.raises(MoaWeeklyDataError, match="request budget exhausted"):
        next(budget_records)
    assert [url for url, _, _ in budget_session.calls] == [base]


def test_history_iterator_closes_only_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    article = f"{base}article.htm"

    class TrackingSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__({
                base: f'<a href="{article}">7月第5周畜产品和饲料集贸市场价格情况</a>',
                article: _article_html(
                    "2026-08-04", "7月第5周（采集日为7月30日）", PRICES_JULY
                ),
            })
            self.closed = False

        def close(self) -> None:
            self.closed = True

    owned = TrackingSession()
    monkeypatch.setattr("src.pig_cycle.moa_weekly.requests.Session", lambda: owned)
    records = iter_recent_weekly_records()
    assert next(records).source_url == article
    assert owned.closed is False
    records.close()
    assert owned.closed is True

    caller = TrackingSession()
    caller_records = iter_recent_weekly_records(max_pages=1, session=caller)
    next(caller_records)
    caller_records.close()
    assert caller.closed is False
