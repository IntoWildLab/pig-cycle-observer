"""Pure, transparent trend features for persisted pig-cycle observations.

The optional ``as_of`` filter prevents currently available records published
after a historical cutoff from entering a calculation. The current storage
keeps only the effective business record, however, so this cannot reconstruct
older versions that were later replaced by official revisions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from .moa_weekly import MoaWeeklyRecord
from .sow_monthly import SowMonthlyRecord, SowSourceType


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class TrendIntervalUnit(str, Enum):
    DAYS = "days"
    MONTHS = "months"


class MoaWeeklyMetric(str, Enum):
    PIGLET_PRICE = "piglet_price"
    LIVE_HOG_PRICE = "live_hog_price"
    CORN_PRICE = "corn_price"
    DERIVED_PIG_CORN_RATIO = "derived_pig_corn_ratio"


@dataclass(frozen=True)
class NumericTrendFeatures:
    observation_count: int
    latest_value: float | None
    previous_value: float | None
    latest_change: float | None
    latest_change_pct: float | None
    window_start_value: float | None
    cumulative_change: float | None
    cumulative_change_pct: float | None
    consecutive_up_count: int
    consecutive_down_count: int
    latest_streak_direction: TrendDirection | None
    observation_keys: tuple[date | str, ...]
    interval_units: tuple[int, ...]
    interval_unit: TrendIntervalUnit | None
    has_irregular_intervals: bool | None


def calculate_moa_weekly_trend(
    records: Sequence[MoaWeeklyRecord],
    *,
    metric: MoaWeeklyMetric,
    as_of: date | None = None,
) -> NumericTrendFeatures:
    """Calculate one supported MOA metric without interpreting cycle state."""
    if not isinstance(metric, MoaWeeklyMetric):
        raise TypeError("metric must be a MoaWeeklyMetric")
    filtered = [
        record for record in records if as_of is None or record.publish_date <= as_of
    ]
    ordered = sorted(filtered, key=lambda record: record.collection_date)
    keys = tuple(record.collection_date for record in ordered)
    _reject_duplicate_keys(keys, "collection_date")
    values = tuple(_finite_value(getattr(record, metric.value), metric.value) for record in ordered)
    intervals = tuple((current - previous).days for previous, current in zip(keys, keys[1:]))
    return _calculate_numeric_features(
        values,
        keys=keys,
        intervals=intervals,
        interval_unit=TrendIntervalUnit.DAYS,
        expected_interval=7,
    )


def calculate_sow_inventory_trend(
    records: Sequence[SowMonthlyRecord],
    *,
    source_type: SowSourceType,
    as_of: date | None = None,
) -> NumericTrendFeatures:
    """Calculate inventory features for exactly one declared sow source type."""
    if not isinstance(source_type, SowSourceType):
        raise TypeError("source_type must be a SowSourceType")
    if any(record.source_type is not source_type for record in records):
        raise ValueError("all sow records must match source_type")
    filtered = [
        record
        for record in records
        if as_of is None
        or (record.publish_date is not None and record.publish_date <= as_of)
    ]
    ordered = sorted(filtered, key=lambda record: record.month)
    keys = tuple(record.month for record in ordered)
    _reject_duplicate_keys(keys, "month")
    values = tuple(
        _finite_value(record.sow_inventory, "sow_inventory") for record in ordered
    )
    intervals = tuple(
        _month_distance(previous, current)
        for previous, current in zip(keys, keys[1:])
    )
    expected_interval = 3 if source_type is SowSourceType.NBS else 1
    return _calculate_numeric_features(
        values,
        keys=keys,
        intervals=intervals,
        interval_unit=TrendIntervalUnit.MONTHS,
        expected_interval=expected_interval,
    )


def _calculate_numeric_features(
    values: tuple[float, ...],
    *,
    keys: tuple[date | str, ...],
    intervals: tuple[int, ...],
    interval_unit: TrendIntervalUnit,
    expected_interval: int,
) -> NumericTrendFeatures:
    count = len(values)
    latest = values[-1] if count else None
    start = values[0] if count else None
    previous = values[-2] if count >= 2 else None
    latest_change = latest - previous if latest is not None and previous is not None else None
    cumulative_change = latest - start if count >= 2 and latest is not None and start is not None else None
    latest_change_pct = (
        latest_change / previous * 100
        if latest_change is not None and previous != 0
        else None
    )
    cumulative_change_pct = (
        cumulative_change / start * 100
        if cumulative_change is not None and start != 0
        else None
    )
    direction, up_count, down_count = _terminal_streak(values)
    return NumericTrendFeatures(
        observation_count=count,
        latest_value=latest,
        previous_value=previous,
        latest_change=latest_change,
        latest_change_pct=latest_change_pct,
        window_start_value=start,
        cumulative_change=cumulative_change,
        cumulative_change_pct=cumulative_change_pct,
        consecutive_up_count=up_count,
        consecutive_down_count=down_count,
        latest_streak_direction=direction,
        observation_keys=keys,
        interval_units=intervals,
        interval_unit=interval_unit,
        has_irregular_intervals=(
            None if count < 2 else any(value != expected_interval for value in intervals)
        ),
    )


def _terminal_streak(
    values: tuple[float, ...],
) -> tuple[TrendDirection | None, int, int]:
    if len(values) < 2:
        return None, 0, 0
    changes = tuple(current - previous for previous, current in zip(values, values[1:]))
    latest = changes[-1]
    if latest == 0:
        return TrendDirection.FLAT, 0, 0
    if latest > 0:
        count = 0
        for change in reversed(changes):
            if change <= 0:
                break
            count += 1
        return TrendDirection.UP, count, 0
    count = 0
    for change in reversed(changes):
        if change >= 0:
            break
        count += 1
    return TrendDirection.DOWN, 0, count


def _finite_value(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _reject_duplicate_keys(keys: tuple[date | str, ...], field_name: str) -> None:
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate {field_name} observations are not allowed")


def _month_distance(previous: str, current: str) -> int:
    previous_year, previous_month = (int(part) for part in previous.split("-"))
    current_year, current_month = (int(part) for part in current.split("-"))
    return (current_year - previous_year) * 12 + current_month - previous_month
