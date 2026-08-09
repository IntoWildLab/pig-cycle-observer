from datetime import date

import pytest
import requests

from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.sow_official import (
    OFFICIAL_HOSTS,
    SowOfficialFetchError,
    _require_national_sow_content,
    _response_kind,
    fetch_sow_record_from_official_url,
)


HTML = """<html><body>
<div>发布时间：2026-06-10</div>
<p>2026年5月末全国能繁母猪存栏3996万头，环比增长0.2%，同比下降6.2%。</p>
</body></html>"""


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        status_code: int = 200,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://www.moa.gov.cn/report.htm",
    ) -> None:
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, float, bool]] = []

    def get(self, url: str, *, timeout: float, allow_redirects: bool) -> _Response:
        self.calls.append((url, timeout, allow_redirects))
        return self.response


@pytest.mark.parametrize("host", ["stats.gov.cn", "www.stats.gov.cn"])
def test_nbs_hosts_are_allowed_and_map_to_nbs(host: str) -> None:
    url = f"https://{host}/report.htm"
    session = _Session(_Response(HTML.encode(), url=url))

    record = fetch_sow_record_from_official_url(url, session=session)

    assert record.source_type is SowSourceType.NBS


@pytest.mark.parametrize(
    "host",
    sorted(OFFICIAL_HOSTS - {"stats.gov.cn", "www.stats.gov.cn"}),
)
def test_moa_and_agri_hosts_are_allowed_and_map_to_reported(host: str) -> None:
    url = f"https://{host}/report.htm"
    session = _Session(_Response(HTML.encode(), url=url))

    record = fetch_sow_record_from_official_url(url, session=session)

    assert record.source_type is SowSourceType.MOA_REPORTED


def test_non_official_host_is_rejected_without_request() -> None:
    session = _Session(_Response(HTML.encode()))

    with pytest.raises(SowOfficialFetchError, match="allowed official"):
        fetch_sow_record_from_official_url("https://example.com/report", session=session)

    assert session.calls == []


@pytest.mark.parametrize("status", [403, 429])
def test_block_status_stops_after_one_request(status: int) -> None:
    session = _Session(_Response(b"blocked", status_code=status))

    with pytest.raises(SowOfficialFetchError, match=str(status)):
        fetch_sow_record_from_official_url("https://www.moa.gov.cn/report.htm", session=session)

    assert len(session.calls) == 1


def test_other_http_error_is_not_retried() -> None:
    session = _Session(_Response(b"error", status_code=500))

    with pytest.raises(SowOfficialFetchError, match="HTTP 500"):
        fetch_sow_record_from_official_url("https://www.moa.gov.cn/report.htm", session=session)

    assert len(session.calls) == 1


def test_html_body_and_publish_date_are_parsed() -> None:
    session = _Session(_Response(HTML.encode()))

    record = fetch_sow_record_from_official_url(
        "https://www.moa.gov.cn/report.htm",
        timeout=7.5,
        session=session,
    )

    assert record.month == "2026-05"
    assert record.publish_date == date(2026, 6, 10)
    assert record.sow_inventory == 3996
    assert session.calls == [("https://www.moa.gov.cn/report.htm", 7.5, False)]


def test_local_sow_data_is_rejected() -> None:
    local_html = """<div>发布时间：2026-06-10</div>
    <p>2026年5月末山东省能繁母猪存栏3996万头。</p>"""
    session = _Session(_Response(local_html.encode()))

    with pytest.raises(SowOfficialFetchError, match="local"):
        fetch_sow_record_from_official_url("https://www.moa.gov.cn/local.htm", session=session)


def test_page_mixing_local_and_national_sow_data_is_rejected() -> None:
    mixed_html = """<div>发布时间：2026-06-10</div>
    <p>山东能繁母猪存栏500万头。</p>
    <p>2026年5月末全国能繁母猪存栏3996万头。</p>"""
    session = _Session(_Response(mixed_html.encode()))

    with pytest.raises(SowOfficialFetchError, match="local"):
        fetch_sow_record_from_official_url("https://www.moa.gov.cn/mixed.htm", session=session)


def test_nbs_sow_clause_inherits_adjacent_national_hog_context() -> None:
    text = (
        "二季度末，全国生猪存栏42491万头。"
        "其中，能繁母猪存栏3780万头。"
    )

    _require_national_sow_content(text)


def test_nbs_visible_slash_publish_date_drives_quarter_month() -> None:
    url = "https://www.stats.gov.cn/sj/zxfbhjd/202607/t20260716_1964140.html"
    html = """<html><body>
    <div>2026/07/16 10:00</div>
    <p>二季度末，全国生猪存栏42491万头……</p>
    <p>其中，能繁母猪存栏3780万头……</p>
    </body></html>"""
    session = _Session(_Response(html.encode(), url=url))

    record = fetch_sow_record_from_official_url(url, session=session)

    assert record.publish_date == date(2026, 7, 16)
    assert record.month == "2026-06"
    assert record.sow_inventory == 3780.0
    assert record.source_type is SowSourceType.NBS


def test_local_sow_clause_does_not_inherit_unrelated_national_context() -> None:
    text = (
        "全国生猪生产保持稳定，市场供应充足。"
        "其中，四川省能繁母猪存栏500万头。"
    )

    with pytest.raises(SowOfficialFetchError, match="local"):
        _require_national_sow_content(text)


def test_pdf_url_is_recognized() -> None:
    assert _response_kind("https://www.stats.gov.cn/report.PDF", "text/html") == "pdf"


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://www.stats.gov.cn/report.csv", "csv"),
        ("https://www.stats.gov.cn/report.xlsx", "xlsx"),
        ("https://www.stats.gov.cn/report.xls", "xls"),
    ],
)
def test_official_file_extensions_are_recognized(url: str, kind: str) -> None:
    assert _response_kind(url, "text/html") == kind


def test_pdf_text_extraction_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_pdf(_content: bytes) -> str:
        raise SowOfficialFetchError("Failed to extract text from official PDF")

    monkeypatch.setattr("src.pig_cycle.sow_official._extract_pdf_text", fail_pdf)
    session = _Session(
        _Response(
            b"%PDF-invalid",
            content_type="application/pdf",
            url="https://www.stats.gov.cn/report.pdf",
        )
    )

    with pytest.raises(SowOfficialFetchError, match="Failed to extract"):
        fetch_sow_record_from_official_url("https://www.stats.gov.cn/report.pdf", session=session)


def test_missing_sow_content_is_rejected() -> None:
    session = _Session(_Response("<p>普通统计公报</p>".encode()))

    with pytest.raises(SowOfficialFetchError, match="does not contain"):
        fetch_sow_record_from_official_url("https://www.stats.gov.cn/report.htm", session=session)


def test_explicit_historical_month_is_not_replaced_by_publish_month() -> None:
    html = """<div>发布时间：2026-01-20</div>
    <p>2025年12月末全国能繁母猪存栏3961万头。</p>"""
    session = _Session(_Response(html.encode()))

    record = fetch_sow_record_from_official_url("https://www.moa.gov.cn/report.htm", session=session)

    assert record.month == "2025-12"
    assert record.publish_date == date(2026, 1, 20)


def test_captcha_page_is_rejected_without_fallback() -> None:
    html = "<p>全国能繁母猪数据需要人机验证</p>"
    session = _Session(_Response(html.encode()))

    with pytest.raises(SowOfficialFetchError, match="captcha"):
        fetch_sow_record_from_official_url("https://www.moa.gov.cn/report.htm", session=session)

    assert len(session.calls) == 1
