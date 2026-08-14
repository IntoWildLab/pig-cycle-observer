"""Parse official monthly sow-capacity statements without network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


NORMAL_CAPACITY_2026 = 3750.0  # 10,000 head
CAPACITY_RED_LOW_UPPER = 0.88
CAPACITY_YELLOW_LOW_UPPER = 0.92
CAPACITY_GREEN_UPPER = 1.03
CAPACITY_YELLOW_HIGH_UPPER = 1.06
_QUARTER_END_MONTHS = {"一": 3, "二": 6, "三": 9, "四": 12}
_CHANGE_DIRECTIONS = r"增长|上升|增加|下降|减少|下调"
_SOW_INVENTORY_PATTERN = re.compile(
    r"(?:全国)?能繁母猪存栏(?:量)?"
    r"(?:为|达到|达|下调至|上调至|降至|升至)?"
    r"([0-9]+(?:\.[0-9]+)?)万头"
)


class SowMonthlyDataError(ValueError):
    """Raised when official text cannot produce a reliable monthly record."""


class SowSourceType(str, Enum):
    """Declared provenance of an official monthly sow-inventory value."""

    NBS = "nbs"
    MOA_ESTIMATE = "moa_estimate"
    MOA_REPORTED = "moa_reported"


@dataclass(frozen=True)
class SowMonthlyRecord:
    """One official monthly sow-inventory observation.

    ``sow_inventory`` is measured in 10,000 head. Percentage changes use
    percentage-point values, so ``-0.5`` means a decline of 0.5%.
    """

    month: str
    sow_inventory: float
    mom_change: Optional[float]
    yoy_change: Optional[float]
    publish_date: Optional[date]
    source_type: SowSourceType
    source_url: str


def capacity_ratio(
    sow_inventory: float,
    normal_capacity: float = NORMAL_CAPACITY_2026,
) -> float:
    """Return inventory divided by the configured normal capacity."""
    if normal_capacity <= 0:
        raise ValueError("normal_capacity must be greater than zero")
    return float(sow_inventory) / float(normal_capacity)


def capacity_zone(ratio: float) -> str:
    """Map a capacity ratio to the official production-control zone."""
    if ratio < CAPACITY_RED_LOW_UPPER:
        return "red_low"
    if ratio < CAPACITY_YELLOW_LOW_UPPER:
        return "yellow_low"
    if ratio <= CAPACITY_GREEN_UPPER:
        return "green"
    if ratio <= CAPACITY_YELLOW_HIGH_UPPER:
        return "yellow_high"
    return "red_high"


def _parse_source_type(value: SowSourceType | str) -> SowSourceType:
    try:
        return value if isinstance(value, SowSourceType) else SowSourceType(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in SowSourceType)
        raise SowMonthlyDataError(f"Unsupported sow source_type; expected one of: {allowed}") from exc


def _parse_month(text: str, publish_date: Optional[date]) -> str:
    explicit_quarter = re.search(r"(20\d{2})\s*年\s*([一二三四])\s*季度\s*末", text)
    if explicit_quarter:
        year = int(explicit_quarter.group(1))
        month = _QUARTER_END_MONTHS[explicit_quarter.group(2)]
    else:
        explicit_month = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*末", text)
        if explicit_month:
            year, month = (int(value) for value in explicit_month.groups())
        else:
            year_end = re.search(r"(20\d{2})\s*年\s*末", text)
            if year_end:
                year, month = int(year_end.group(1)), 12
            else:
                quarter_only = re.search(r"([一二三四])\s*季度\s*末", text)
                if quarter_only:
                    month = _QUARTER_END_MONTHS[quarter_only.group(1)]
                    if publish_date is None or month > publish_date.month:
                        raise SowMonthlyDataError(
                            "Sow inventory quarter year is ambiguous; provide an explicit year"
                        )
                    year = publish_date.year
                else:
                    month_only = re.search(r"(?<!\d)(\d{1,2})\s*月\s*末", text)
                    if not month_only or publish_date is None:
                        raise SowMonthlyDataError(
                            "Sow inventory month is ambiguous; provide an explicit year or publish_date"
                        )
                    month = int(month_only.group(1))
                    year = publish_date.year - 1 if month > publish_date.month else publish_date.year

    if not 1 <= month <= 12:
        raise SowMonthlyDataError(f"Invalid sow inventory month: {month}")
    return f"{year:04d}-{month:02d}"


def _parse_inventory(text: str) -> float:
    match = _SOW_INVENTORY_PATTERN.search(text)
    if not match:
        raise SowMonthlyDataError("Official text is missing sow_inventory in 10,000 head")
    return float(match.group(1))


def _sow_change_scope(text: str) -> tuple[str, ...]:
    clauses = [part for part in re.split(r"[。！？；\r\n]+", text) if part]
    for index, clause in enumerate(clauses):
        inventory_match = _SOW_INVENTORY_PATTERN.search(clause)
        if inventory_match is None:
            continue

        scope = [clause[inventory_match.start():]]
        if index + 1 < len(clauses) and re.match(r"^(?:同比|环比)", clauses[index + 1]):
            scope.append(clauses[index + 1])
        return tuple(scope)
    return ()


def _parse_change(clauses: tuple[str, ...], prefix: str) -> Optional[float]:
    pattern = re.compile(
        rf"{prefix}(?:(?:{_CHANGE_DIRECTIONS})"
        r"[0-9]+(?:\.[0-9]+)?万头[，,]?)?"
        rf"({_CHANGE_DIRECTIONS})([0-9]+(?:\.[0-9]+)?)%"
    )
    for clause in clauses:
        match = pattern.search(clause)
        if match:
            direction, value_text = match.groups()
            value = float(value_text)
            return -value if direction in {"下降", "减少", "下调"} else value
    return None


def parse_sow_monthly_record(
    text: str,
    *,
    source_url: str,
    source_type: SowSourceType | str,
    publish_date: Optional[date] = None,
) -> SowMonthlyRecord:
    """Parse one caller-supplied official statement without fetching data."""
    compact_text = re.sub(r"\s+", "", text)
    change_scope = _sow_change_scope(compact_text)
    return SowMonthlyRecord(
        month=_parse_month(compact_text, publish_date),
        sow_inventory=_parse_inventory(compact_text),
        mom_change=_parse_change(change_scope, "环比"),
        yoy_change=_parse_change(change_scope, "同比"),
        publish_date=publish_date,
        source_type=_parse_source_type(source_type),
        source_url=source_url,
    )
