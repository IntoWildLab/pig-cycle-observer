"""Conservative single-URL acquisition for official sow-capacity records."""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse

import requests

from .sow_monthly import (
    SowMonthlyDataError,
    SowMonthlyRecord,
    SowSourceType,
    parse_sow_monthly_record,
)


OFFICIAL_HOSTS = frozenset(
    {
        "stats.gov.cn",
        "www.stats.gov.cn",
        "moa.gov.cn",
        "www.moa.gov.cn",
        "scs.moa.gov.cn",
        "xmsyj.moa.gov.cn",
        "jhs.moa.gov.cn",
        "agri.cn",
        "www.agri.cn",
    }
)
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_USER_AGENT = "pig-cycle-observer/2.0 (+official public data reader)"
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
_LOCALITY_NAMES = (
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古", "广西", "西藏",
    "宁夏", "新疆", "香港", "澳门", "台湾",
)


class SowOfficialFetchError(SowMonthlyDataError):
    """Raised when conservative official-source acquisition must stop."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _validate_official_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or host not in OFFICIAL_HOSTS:
        raise SowOfficialFetchError(f"URL is not an allowed official source: {url}")
    if parsed.username or parsed.password:
        raise SowOfficialFetchError("Official URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SowOfficialFetchError("Official URL contains an invalid port") from exc
    if port not in {None, 80, 443}:
        raise SowOfficialFetchError("Official URL uses a non-standard port")
    return host


def _source_type_for_host(host: str) -> SowSourceType:
    if host in {"stats.gov.cn", "www.stats.gov.cn"}:
        return SowSourceType.NBS
    return SowSourceType.MOA_REPORTED


def _decode_utf8(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SowOfficialFetchError(f"{label} is not valid UTF-8 text") from exc


def _extract_html_text(content: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(_decode_utf8(content, "Official HTML response"))
    return " ".join(parser.parts)


def _extract_csv_text(content: bytes) -> str:
    rows = csv.reader(io.StringIO(_decode_utf8(content, "Official CSV response")))
    return " ".join(cell.strip() for row in rows for cell in row if cell.strip())


def _extract_excel_text(content: bytes) -> str:
    try:
        import pandas as pd

        frame = pd.read_excel(io.BytesIO(content), sheet_name=0, header=None, dtype=str)
    except Exception as exc:
        raise SowOfficialFetchError("Failed to extract text from official Excel file") from exc
    values = frame.fillna("").astype(str).to_numpy().ravel()
    return " ".join(value.strip() for value in values if value.strip())


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = " ".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except Exception as exc:
        raise SowOfficialFetchError("Failed to extract text from official PDF") from exc
    if not text:
        raise SowOfficialFetchError("Official PDF contains no extractable text; OCR is not attempted")
    return text


def _response_kind(url: str, content_type: str) -> str:
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    if suffix in {".pdf", ".csv", ".xlsx", ".xls"}:
        return suffix[1:]
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "application/pdf":
        return "pdf"
    if normalized in {"text/csv", "application/csv"}:
        return "csv"
    if normalized in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        return "xlsx" if "openxmlformats" in normalized else "xls"
    return "html"


def _extract_response_text(url: str, content_type: str, content: bytes) -> str:
    kind = _response_kind(url, content_type)
    if kind == "pdf":
        return _extract_pdf_text(content)
    if kind == "csv":
        return _extract_csv_text(content)
    if kind in {"xlsx", "xls"}:
        return _extract_excel_text(content)
    return _extract_html_text(content)


def _parse_publish_date(text: str) -> Optional[date]:
    patterns = (
        r"(?:发布时间|发布日期|发布于|时间)\s*[：:]?\s*"
        r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})\s*日?",
        r"(?<!\d)(20\d{2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})(?!\d)",
        r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return date(*(int(value) for value in match.groups()))
            except ValueError as exc:
                raise SowOfficialFetchError("Official source contains an invalid publish_date") from exc
    return None


def _reject_block_or_login_page(text: str) -> None:
    compact = re.sub(r"\s+", "", text)
    if any(marker in compact for marker in _BLOCK_PAGE_MARKERS):
        raise SowOfficialFetchError("Official source returned a captcha, anti-bot, or login page")


def _require_national_sow_content(text: str) -> None:
    compact = re.sub(r"[\t\f\v ]+", "", text)
    if "能繁母猪" not in compact:
        raise SowOfficialFetchError("Official source does not contain sow inventory content")
    locality_context = rf"(?:{'|'.join(_LOCALITY_NAMES)}|[\u4e00-\u9fff]{{2,12}}(?:省|市|县|自治区|自治州))"
    locality_pattern = re.compile(rf"{locality_context}.{{0,8}}能繁母猪")
    statistical_continuation_pattern = re.compile(
        r"^(?:环比|同比)(?:增加|增长|上升|上调|减少|下降|下调|持平)"
    )
    sentences = [part.strip() for part in re.split(r"[。！？；\r\n]+", compact) if part.strip()]
    sow_sentences = [sentence for sentence in sentences if "能繁母猪" in sentence]
    if any(locality_pattern.search(sentence) for sentence in sow_sentences):
        raise SowOfficialFetchError("Official source contains local rather than nationwide sow data")

    for index, sentence in enumerate(sentences):
        if "能繁母猪" not in sentence:
            continue
        if re.search(r"全国(?:的)?能繁母猪", sentence):
            return

        sow_index = sentence.find("能繁母猪")
        inherited_clause = sentence[:sow_index]
        previous_sentence = sentences[index - 1] if index > 0 else ""
        inherits_national_context = "其中" in inherited_clause and (
            re.search(r"全国(?:的)?生猪存栏", previous_sentence)
            or re.search(r"全国(?:的)?生猪存栏.*其中", inherited_clause)
        )
        if not inherits_national_context and "其中" in inherited_clause and index >= 2:
            preceding_sentence = sentences[index - 2]
            is_statistical_continuation = (
                statistical_continuation_pattern.search(previous_sentence)
                and not re.search(locality_context, previous_sentence)
            )
            inherits_national_context = bool(
                is_statistical_continuation
                and re.search(r"全国(?:的)?生猪存栏", preceding_sentence)
            )
        if inherits_national_context:
            return

    raise SowOfficialFetchError("Sow inventory is not explicitly stated as nationwide data")


def fetch_sow_record_from_official_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> SowMonthlyRecord:
    """Fetch exactly one allow-listed official URL and parse one national record."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    host = _validate_official_url(url)
    owns_session = session is None
    http = session or requests.Session()
    http.headers.update({"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/pdf,text/csv,*/*"})
    try:
        try:
            response = http.get(url, timeout=timeout, allow_redirects=False)
        except requests.RequestException as exc:
            raise SowOfficialFetchError(f"Failed to fetch official source {url}: {exc}") from exc

        status = int(response.status_code)
        if status in {403, 429}:
            raise SowOfficialFetchError(f"Official source returned HTTP {status}; acquisition stopped")
        if 300 <= status < 400:
            raise SowOfficialFetchError("Official source returned a redirect; automatic redirects are disabled")
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SowOfficialFetchError(f"Official source returned HTTP {status}") from exc

        final_url = str(getattr(response, "url", url) or url)
        _validate_official_url(final_url)
        content_type = str(response.headers.get("Content-Type", ""))
        text = _extract_response_text(url, content_type, response.content)
        _reject_block_or_login_page(text)
        _require_national_sow_content(text)
        return parse_sow_monthly_record(
            text,
            source_url=url,
            source_type=_source_type_for_host(host),
            publish_date=_parse_publish_date(text),
        )
    finally:
        if owns_session:
            http.close()
