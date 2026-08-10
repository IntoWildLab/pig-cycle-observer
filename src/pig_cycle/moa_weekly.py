"""Acquire weekly livestock and feed market prices from China's MOA website."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests

MOA_MONITORING_URL = "https://xmsyj.moa.gov.cn/jcyj/"
TARGET_TITLE = "畜产品和饲料集贸市场价格情况"
EXCLUDED_TITLE = "生猪定点屠宰企业生猪收购和白条肉出厂价格情况"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_MAX_PAGES = 12
MAX_HISTORY_PAGES = 12
MAX_HISTORY_ARTICLES = 60
MAX_HISTORY_REQUESTS = MAX_HISTORY_PAGES + MAX_HISTORY_ARTICLES
INCREMENTAL_REQUEST_BUDGET = 2
MOA_OFFICIAL_HOSTS = frozenset(
    {
        "moa.gov.cn",
        "www.moa.gov.cn",
        "scs.moa.gov.cn",
        "xmsyj.moa.gov.cn",
        "jhs.moa.gov.cn",
    }
)
_BLOCK_PAGE_MARKERS = (
    "验证码",
    "人机验证",
    "访问过于频繁",
    "请求过于频繁",
    "访问受限",
    "禁止访问",
    "登录后访问",
    "请先登录",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "pig-cycle-observer/2.0"
)


class MoaWeeklyDataError(RuntimeError):
    """Raised when MOA discovery, download, or parsing cannot produce valid data."""


@dataclass
class _RequestBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise MoaWeeklyDataError(
                f"MOA weekly request budget exhausted ({self.used}/{self.limit})"
            )
        self.used += 1


@dataclass(frozen=True)
class MoaWeeklyRecord:
    collection_date: date
    publish_date: date
    period_label: str
    piglet_price: float
    live_hog_price: float
    corn_price: float
    soybean_meal_price: Optional[float]
    fattening_feed_price: Optional[float]
    derived_pig_corn_ratio: float
    source_url: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        self._href = attributes.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


def _html_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return " ".join(parser.parts)


def discover_weekly_article_urls(index_html: str, *, index_url: str = MOA_MONITORING_URL) -> list[str]:
    """Return target weekly-report URLs from one monitoring index page."""
    parser = _LinkExtractor()
    parser.feed(index_html)
    urls: list[str] = []
    seen: set[str] = set()
    for href, title in parser.links:
        normalized_title = re.sub(r"\s+", "", title)
        if TARGET_TITLE not in normalized_title or EXCLUDED_TITLE in normalized_title:
            continue
        absolute_url = urljoin(index_url, href)
        try:
            _validate_moa_url(absolute_url)
        except MoaWeeklyDataError:
            continue
        if absolute_url not in seen:
            seen.add(absolute_url)
            urls.append(absolute_url)
    return urls


def _parse_publish_date(text: str) -> date:
    patterns = (
        r"(?:发布时间|发布日期|时间)\s*[：:]?\s*(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?",
        r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)",
        r"(?<!\d)(20\d{2})年(\d{1,2})月(\d{1,2})日",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return date(*(int(value) for value in match.groups()))
    raise MoaWeeklyDataError("MOA weekly report publish_date not found")


def _parse_collection_date(text: str, publish_date: date) -> tuple[str, date]:
    period_match = re.search(
        r"(\d{1,2}\s*月\s*第\s*\d{1,2}\s*周)\s*[（(]?\s*"
        r"采集日\s*为\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        text,
    )
    if not period_match:
        raise MoaWeeklyDataError("MOA weekly report collection_date/period_label not found")
    period_label, month_text, day_text = period_match.groups()
    period_label = re.sub(r"\s+", "", period_label)
    month, day = int(month_text), int(day_text)
    try:
        collected = date(publish_date.year, month, day)
        if collected > publish_date:
            collected = date(publish_date.year - 1, month, day)
    except ValueError as exc:
        raise MoaWeeklyDataError(f"Invalid collection_date in MOA weekly report: {month}月{day}日") from exc
    return period_label, collected


def _parse_price(text: str, label_pattern: str, field_name: str, *, required: bool) -> Optional[float]:
    compact_text = re.sub(r"\s+", "", text)
    match = re.search(rf"{label_pattern}\s*([0-9]+(?:\.[0-9]+)?)\s*元\s*/\s*公斤", compact_text)
    if match:
        return float(match.group(1))
    if required:
        raise MoaWeeklyDataError(f"MOA weekly report required field missing: {field_name}")
    return None


def parse_weekly_record(html: str, *, source_url: str) -> MoaWeeklyRecord:
    """Parse one MOA weekly-report article without making a network request."""
    text = _html_text(html)
    published = _parse_publish_date(text)
    period_label, collected = _parse_collection_date(text, published)
    piglet = _parse_price(text, r"全国仔猪平均价格", "piglet_price", required=True)
    live_hog = _parse_price(text, r"全国生猪平均价格", "live_hog_price", required=True)
    corn = _parse_price(text, r"全国玉米平均价格", "corn_price", required=True)
    soybean_meal = _parse_price(text, r"全国豆粕平均价格", "soybean_meal_price", required=False)
    fattening_feed = _parse_price(text, r"育肥猪配合饲料平均价格", "fattening_feed_price", required=False)
    assert piglet is not None and live_hog is not None and corn is not None
    if corn <= 0:
        raise MoaWeeklyDataError("MOA weekly report corn_price must be greater than zero")
    return MoaWeeklyRecord(
        collection_date=collected,
        publish_date=published,
        period_label=period_label,
        piglet_price=piglet,
        live_hog_price=live_hog,
        corn_price=corn,
        soybean_meal_price=soybean_meal,
        fattening_feed_price=fattening_feed,
        derived_pig_corn_ratio=live_hog / corn,
        source_url=source_url,
    )


def _index_url(page_number: int) -> str:
    return MOA_MONITORING_URL if page_number == 0 else urljoin(MOA_MONITORING_URL, f"index_{page_number}.htm")


def _validate_moa_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or host not in MOA_OFFICIAL_HOSTS:
        raise MoaWeeklyDataError(f"URL is not an allowed MOA official source: {url}")
    if parsed.username or parsed.password:
        raise MoaWeeklyDataError("MOA URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MoaWeeklyDataError("MOA URL contains an invalid port") from exc
    if port not in {None, 80, 443}:
        raise MoaWeeklyDataError("MOA URL uses a non-standard port")


def _reject_block_page(html: str) -> None:
    compact = re.sub(r"\s+", "", html)
    if any(marker in compact for marker in _BLOCK_PAGE_MARKERS):
        raise MoaWeeklyDataError("MOA returned a captcha, anti-bot, or login page")


def _get_html(
    session: requests.Session,
    url: str,
    timeout: float,
    *,
    budget: Optional[_RequestBudget] = None,
) -> str:
    _validate_moa_url(url)
    if budget is not None:
        budget.consume()
    try:
        response = session.get(url, timeout=timeout, allow_redirects=False)
        status = int(response.status_code)
        if status in {403, 429}:
            raise MoaWeeklyDataError(f"MOA returned HTTP {status}; acquisition stopped")
        if 300 <= status < 400:
            raise MoaWeeklyDataError("MOA returned a redirect; automatic redirects are disabled")
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MoaWeeklyDataError(f"Failed to download MOA page {url}: {exc}") from exc
    final_url = str(getattr(response, "url", url) or url)
    _validate_moa_url(final_url)
    html = response.content.decode("utf-8")
    _reject_block_page(html)
    return html


def sort_and_deduplicate_records(records: Iterable[MoaWeeklyRecord]) -> list[MoaWeeklyRecord]:
    """Keep the latest-published row for each collection date and sort ascending."""
    by_collection_date: dict[date, MoaWeeklyRecord] = {}
    for record in records:
        previous = by_collection_date.get(record.collection_date)
        if previous is None or record.publish_date > previous.publish_date:
            by_collection_date[record.collection_date] = record
    return sorted(by_collection_date.values(), key=lambda item: item.collection_date)


def fetch_recent_weekly_records(
    min_weeks: int = 26,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_articles: int = MAX_HISTORY_ARTICLES,
    max_requests: int = MAX_HISTORY_REQUESTS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> list[MoaWeeklyRecord]:
    """Rebuild at least ``min_weeks`` unique records directly from MOA pages."""
    if min_weeks < 1:
        raise ValueError("min_weeks must be at least 1")
    if not 1 <= max_pages <= MAX_HISTORY_PAGES:
        raise ValueError(f"max_pages must be between 1 and {MAX_HISTORY_PAGES}")
    if not 1 <= max_articles <= MAX_HISTORY_ARTICLES:
        raise ValueError(f"max_articles must be between 1 and {MAX_HISTORY_ARTICLES}")
    if not 1 <= max_requests <= MAX_HISTORY_REQUESTS:
        raise ValueError(f"max_requests must be between 1 and {MAX_HISTORY_REQUESTS}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    owns_session = session is None
    http = session or requests.Session()
    http.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    records: list[MoaWeeklyRecord] = []
    visited_articles: set[str] = set()
    budget = _RequestBudget(max_requests)
    article_requests = 0
    try:
        for page_number in range(max_pages):
            index_url = _index_url(page_number)
            index_html = _get_html(http, index_url, timeout, budget=budget)
            for article_url in discover_weekly_article_urls(index_html, index_url=index_url):
                if article_url in visited_articles:
                    continue
                if article_requests >= max_articles:
                    raise MoaWeeklyDataError(
                        f"MOA weekly history article limit exhausted ({article_requests}/{max_articles})"
                    )
                visited_articles.add(article_url)
                article_requests += 1
                records.append(
                    parse_weekly_record(
                        _get_html(http, article_url, timeout, budget=budget),
                        source_url=article_url,
                    )
                )
                unique_records = sort_and_deduplicate_records(records)
                if len(unique_records) >= min_weeks:
                    return unique_records[-min_weeks:]
    finally:
        if owns_session:
            http.close()
    raise MoaWeeklyDataError(
        f"Only found {len(sort_and_deduplicate_records(records))} unique MOA weekly records "
        f"after scanning {max_pages} index pages; required {min_weeks}"
    )


def fetch_latest_weekly_increment(
    *,
    known_urls: Optional[Iterable[str]] = None,
    known_dates: Optional[Iterable[date | str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> Optional[MoaWeeklyRecord]:
    """Fetch at most one unknown article from the first MOA index page."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    known_url_set = set(known_urls or ())
    known_date_set = {
        value.isoformat() if isinstance(value, date) else str(value)
        for value in (known_dates or ())
    }
    owns_session = session is None
    http = session or requests.Session()
    http.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    budget = _RequestBudget(INCREMENTAL_REQUEST_BUDGET)
    try:
        index_html = _get_html(http, MOA_MONITORING_URL, timeout, budget=budget)
        for article_url in discover_weekly_article_urls(index_html, index_url=MOA_MONITORING_URL):
            if article_url in known_url_set:
                continue
            record = parse_weekly_record(
                _get_html(http, article_url, timeout, budget=budget),
                source_url=article_url,
            )
            if record.collection_date.isoformat() in known_date_set:
                return None
            return record
        return None
    finally:
        if owns_session:
            http.close()


def export_weekly_records_csv(records: Iterable[MoaWeeklyRecord], path: str | Path) -> Path:
    """Explicitly export records for local inspection; CSV is never a fetch prerequisite."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(MoaWeeklyRecord.__dataclass_fields__)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in sort_and_deduplicate_records(records):
            row = asdict(record)
            row["collection_date"] = record.collection_date.isoformat()
            row["publish_date"] = record.publish_date.isoformat()
            writer.writerow(row)
    return destination
