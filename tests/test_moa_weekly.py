from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.pig_cycle.moa_weekly import (
    DEFAULT_USER_AGENT,
    MoaWeeklyDataError,
    _get_html,
    discover_weekly_article_urls,
    fetch_recent_weekly_records,
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
    ) -> None:
        self.content = text.encode("utf-8")
        self.encoding = encoding
        self.apparent_encoding = apparent_encoding

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding)

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, *, timeout: float) -> _FakeResponse:
        self.calls.append((url, timeout))
        return _FakeResponse(self.pages[url])


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
    session.get = lambda url, *, timeout: response

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
    assert all(timeout == 7.5 for _, timeout in session.calls)
    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_fetcher_reports_when_max_pages_cannot_supply_requested_weeks() -> None:
    base = "https://xmsyj.moa.gov.cn/jcyj/"
    session = _FakeSession({base: "<html><body>no target reports</body></html>"})

    with pytest.raises(MoaWeeklyDataError, match=r"Only found 0.*scanning 1.*required 1"):
        fetch_recent_weekly_records(min_weeks=1, max_pages=1, session=session)
