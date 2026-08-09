"""Budgeted discovery of sow records from one caller-supplied official index."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable, Optional
from urllib.parse import urljoin

import requests

from .sow_monthly import SowMonthlyDataError, SowMonthlyRecord, SowSourceType
from .sow_official import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    SowOfficialFetchError,
    _decode_utf8,
    _reject_block_or_login_page,
    _validate_official_url,
    fetch_sow_record_from_official_url,
)


MAX_REQUESTS_PER_RUN = 5
MAX_CANDIDATES_PER_RUN = 2
_TITLE_KEYWORDS = ("生猪", "农业", "畜牧", "国民经济", "生产情况", "经济运行")


class SowDiscoveryError(SowMonthlyDataError):
    """Raised when bounded official discovery cannot safely return a record."""


class RequestBudgetExceeded(SowDiscoveryError):
    """Raised before a request would exceed the configured hard budget."""


@dataclass
class RequestBudget:
    limit: int
    used: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_REQUESTS_PER_RUN:
            raise ValueError(f"max_requests must be between 1 and {MAX_REQUESTS_PER_RUN}")

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RequestBudgetExceeded(
                f"Official discovery request budget exhausted ({self.used}/{self.limit})"
            )
        self.used += 1


class _BudgetedSession:
    """Count every GET before delegating it to the caller's serial session."""

    def __init__(self, session: requests.Session, budget: RequestBudget) -> None:
        self._session = session
        self._budget = budget
        self.headers = session.headers

    def get(self, url: str, **kwargs):
        self._budget.consume()
        return self._session.get(url, **kwargs)


class _ArticleLinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


def extract_sow_candidate_urls(
    index_html: str,
    *,
    index_url: str,
    max_candidates: int = MAX_CANDIDATES_PER_RUN,
    known_urls: Optional[Iterable[str]] = None,
) -> list[str]:
    """Return at most two relevant, allow-listed links in index display order."""
    if not 1 <= max_candidates <= MAX_CANDIDATES_PER_RUN:
        raise ValueError(f"max_candidates must be between 1 and {MAX_CANDIDATES_PER_RUN}")
    _validate_official_url(index_url)
    known = set(known_urls or ())
    parser = _ArticleLinkExtractor()
    parser.feed(index_html)
    candidates: list[str] = []
    seen: set[str] = set()
    for href, title in parser.links:
        if not any(keyword in title for keyword in _TITLE_KEYWORDS):
            continue
        candidate = urljoin(index_url, href)
        try:
            _validate_official_url(candidate)
        except SowOfficialFetchError:
            continue
        if candidate in known or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _fetch_index_html(
    session: _BudgetedSession,
    index_url: str,
    timeout: float,
) -> str:
    try:
        response = session.get(index_url, timeout=timeout, allow_redirects=False)
    except requests.RequestException as exc:
        raise SowDiscoveryError(f"Failed to fetch official index {index_url}: {exc}") from exc
    status = int(response.status_code)
    if status in {403, 429}:
        raise SowDiscoveryError(f"Official index returned HTTP {status}; discovery stopped")
    if 300 <= status < 400:
        raise SowDiscoveryError("Official index returned a redirect; discovery stopped")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SowDiscoveryError(f"Official index returned HTTP {status}; discovery stopped") from exc
    final_url = str(getattr(response, "url", index_url) or index_url)
    _validate_official_url(final_url)
    html = _decode_utf8(response.content, "Official index response")
    _reject_block_or_login_page(html)
    return html


def _is_terminal_candidate_error(exc: SowOfficialFetchError) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "http 403",
            "http 429",
            "captcha",
            "anti-bot",
            "login page",
            "redirect",
            "failed to fetch",
        )
    )


def _select_latest(records: list[SowMonthlyRecord]) -> SowMonthlyRecord:
    latest_month = max(record.month for record in records)
    latest = [record for record in records if record.month == latest_month]
    month_number = int(latest_month[-2:])
    if month_number in {3, 6, 9, 12}:
        nbs = next((record for record in latest if record.source_type is SowSourceType.NBS), None)
        if nbs is not None:
            return nbs
    return latest[0]


def discover_latest_sow_record(
    index_url: str,
    *,
    max_requests: int = MAX_REQUESTS_PER_RUN,
    max_candidates: int = MAX_CANDIDATES_PER_RUN,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
    known_urls: Optional[Iterable[str]] = None,
) -> SowMonthlyRecord:
    """Read one official index and inspect at most two candidates serially."""
    if not 1 <= max_candidates <= MAX_CANDIDATES_PER_RUN:
        raise ValueError(f"max_candidates must be between 1 and {MAX_CANDIDATES_PER_RUN}")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    _validate_official_url(index_url)
    budget = RequestBudget(max_requests)
    owns_session = session is None
    raw_session = session or requests.Session()
    budgeted = _BudgetedSession(raw_session, budget)
    budgeted.headers.update(
        {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    )
    try:
        index_html = _fetch_index_html(budgeted, index_url, timeout)
        candidates = extract_sow_candidate_urls(
            index_html,
            index_url=index_url,
            max_candidates=max_candidates,
            known_urls=known_urls,
        )
        records: list[SowMonthlyRecord] = []
        for candidate_url in candidates:
            try:
                records.append(
                    fetch_sow_record_from_official_url(
                        candidate_url,
                        timeout=timeout,
                        session=budgeted,
                    )
                )
            except RequestBudgetExceeded:
                raise
            except SowOfficialFetchError as exc:
                if _is_terminal_candidate_error(exc):
                    raise SowDiscoveryError(
                        f"Official candidate access was blocked; discovery stopped: {exc}"
                    ) from exc
                continue
            except SowMonthlyDataError:
                continue
        if not records:
            raise SowDiscoveryError("No reliable sow record found within the bounded candidate set")
        return _select_latest(records)
    finally:
        if owns_session:
            raw_session.close()
