from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.trend import (
    MoaWeeklyMetric,
    NumericTrendFeatures,
    TrendDirection,
    TrendIntervalUnit,
    calculate_moa_weekly_trend,
    calculate_sow_inventory_trend,
)


def _weekly(
    collection_date: date,
    value: float,
    *,
    publish_date: date | None = None,
) -> MoaWeeklyRecord:
    return MoaWeeklyRecord(
        collection_date=collection_date,
        publish_date=publish_date or collection_date,
        period_label="测试周",
        piglet_price=value,
        live_hog_price=value,
        corn_price=value,
        soybean_meal_price=None,
        fattening_feed_price=None,
        derived_pig_corn_ratio=value,
        source_url=f"https://xmsyj.moa.gov.cn/{collection_date}.htm",
    )


def _sow(
    month: str,
    value: float,
    *,
    source_type: SowSourceType = SowSourceType.NBS,
    publish_date: date | None = date(2026, 7, 16),
) -> SowMonthlyRecord:
    return SowMonthlyRecord(
        month=month,
        sow_inventory=value,
        mom_change=None,
        yoy_change=None,
        publish_date=publish_date,
        source_type=source_type,
        source_url=f"https://example.gov.cn/{source_type.value}/{month}.htm",
    )


def _moa(values: list[float], *, day_step: int = 7) -> NumericTrendFeatures:
    records = [
        _weekly(date(2026, 7, 2 + index * day_step), value)
        for index, value in enumerate(values)
    ]
    return calculate_moa_weekly_trend(records, metric=MoaWeeklyMetric.PIGLET_PRICE)


def test_moa_empty_and_single_observation() -> None:
    empty = _moa([])
    assert empty.observation_count == 0
    assert empty.latest_value is None and empty.previous_value is None
    assert empty.latest_change is None and empty.cumulative_change is None
    assert empty.latest_streak_direction is None
    assert empty.interval_units == ()
    assert empty.interval_unit is TrendIntervalUnit.DAYS
    assert empty.has_irregular_intervals is None

    single = _moa([2.0])
    assert single.latest_value == single.window_start_value == 2.0
    assert single.cumulative_change is None
    assert single.latest_streak_direction is None


@pytest.mark.parametrize(
    ("values", "direction", "up_count", "down_count"),
    [
        ([1.0, 2.0], TrendDirection.UP, 1, 0),
        ([2.0, 1.0], TrendDirection.DOWN, 0, 1),
        ([1.0, 1.0], TrendDirection.FLAT, 0, 0),
        ([1.0, 2.0, 3.0], TrendDirection.UP, 2, 0),
        ([3.0, 2.0, 1.0], TrendDirection.DOWN, 0, 2),
        ([1.0, 2.0, 3.0, 2.0, 1.0], TrendDirection.DOWN, 0, 2),
        ([1.0, 2.0, 2.0], TrendDirection.FLAT, 0, 0),
    ],
)
def test_terminal_streak_semantics(
    values: list[float],
    direction: TrendDirection,
    up_count: int,
    down_count: int,
) -> None:
    result = _moa(values)
    assert result.latest_streak_direction is direction
    assert result.consecutive_up_count == up_count
    assert result.consecutive_down_count == down_count


def test_changes_percentages_and_zero_denominators() -> None:
    result = _moa([2.0, 3.0, 4.0])
    assert result.previous_value == 3.0
    assert result.latest_change == 1.0
    assert result.latest_change_pct == pytest.approx(100 / 3)
    assert result.cumulative_change == 2.0
    assert result.cumulative_change_pct == 100.0

    zero_start = _moa([0.0, 2.0, 3.0])
    assert zero_start.cumulative_change == 3.0
    assert zero_start.cumulative_change_pct is None
    zero_previous = _moa([1.0, 0.0, 2.0])
    assert zero_previous.latest_change == 2.0
    assert zero_previous.latest_change_pct is None


def test_moa_sorts_without_mutating_input_and_tracks_intervals() -> None:
    later = _weekly(date(2026, 7, 9), 2.0)
    earlier = _weekly(date(2026, 7, 2), 1.0)
    records = [later, earlier]
    before = records.copy()
    result = calculate_moa_weekly_trend(records, metric=MoaWeeklyMetric.LIVE_HOG_PRICE)
    assert result.observation_keys == (date(2026, 7, 2), date(2026, 7, 9))
    assert result.interval_units == (7,)
    assert result.has_irregular_intervals is False
    assert records == before

    irregular = calculate_moa_weekly_trend(
        [_weekly(date(2026, 7, 2), 1), _weekly(date(2026, 7, 16), 2)],
        metric=MoaWeeklyMetric.CORN_PRICE,
    )
    assert irregular.interval_units == (14,)
    assert irregular.has_irregular_intervals is True


def test_moa_as_of_duplicates_metric_and_finite_validation() -> None:
    visible = _weekly(date(2026, 7, 2), 1.0, publish_date=date(2026, 7, 7))
    future = _weekly(date(2026, 7, 9), 2.0, publish_date=date(2026, 7, 20))
    result = calculate_moa_weekly_trend(
        [visible, future], metric=MoaWeeklyMetric.PIGLET_PRICE, as_of=date(2026, 7, 10)
    )
    assert result.observation_keys == (visible.collection_date,)

    with pytest.raises(ValueError, match="duplicate collection_date"):
        calculate_moa_weekly_trend(
            [visible, replace(visible, source_url="https://xmsyj.moa.gov.cn/revision.htm")],
            metric=MoaWeeklyMetric.PIGLET_PRICE,
        )
    with pytest.raises(TypeError, match="MoaWeeklyMetric"):
        calculate_moa_weekly_trend([visible], metric="piglet_price")  # type: ignore[arg-type]
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            calculate_moa_weekly_trend(
                [replace(visible, piglet_price=value)], metric=MoaWeeklyMetric.PIGLET_PRICE
            )


def test_sow_empty_single_and_quarterly_intervals() -> None:
    empty = calculate_sow_inventory_trend([], source_type=SowSourceType.NBS)
    assert empty.observation_count == 0
    assert empty.interval_unit is TrendIntervalUnit.MONTHS
    assert empty.has_irregular_intervals is None

    single = calculate_sow_inventory_trend(
        [_sow("2026-06", 3780)], source_type=SowSourceType.NBS
    )
    assert single.latest_value == 3780
    assert single.cumulative_change is None

    regular = calculate_sow_inventory_trend(
        [_sow("2026-06", 3780), _sow("2025-12", 3961), _sow("2026-03", 3904)],
        source_type=SowSourceType.NBS,
    )
    assert regular.observation_keys == ("2025-12", "2026-03", "2026-06")
    assert regular.interval_units == (3, 3)
    assert regular.has_irregular_intervals is False
    assert regular.consecutive_down_count == 2

    missing_quarter = calculate_sow_inventory_trend(
        [_sow("2025-12", 3961), _sow("2026-06", 3780)],
        source_type=SowSourceType.NBS,
    )
    assert missing_quarter.interval_units == (6,)
    assert missing_quarter.has_irregular_intervals is True


@pytest.mark.parametrize(
    ("months", "irregular"),
    [(("2026-05", "2026-06"), False), (("2026-04", "2026-06"), True)],
)
def test_monthly_moa_interval_expectation(
    months: tuple[str, str], irregular: bool
) -> None:
    records = [
        _sow(month, 3900 + index, source_type=SowSourceType.MOA_REPORTED)
        for index, month in enumerate(months)
    ]
    result = calculate_sow_inventory_trend(
        records, source_type=SowSourceType.MOA_REPORTED
    )
    assert result.has_irregular_intervals is irregular


def test_sow_rejects_mixed_sources_and_duplicate_months() -> None:
    nbs = _sow("2026-06", 3780)
    reported = _sow(
        "2026-05", 3900, source_type=SowSourceType.MOA_REPORTED
    )
    with pytest.raises(ValueError, match="source_type"):
        calculate_sow_inventory_trend([nbs, reported], source_type=SowSourceType.NBS)
    with pytest.raises(ValueError, match="duplicate month"):
        calculate_sow_inventory_trend(
            [nbs, replace(nbs, source_url="https://example.gov.cn/revision.htm")],
            source_type=SowSourceType.NBS,
        )


def test_sow_as_of_excludes_future_and_unknown_publication_without_mutation() -> None:
    visible = _sow("2026-03", 3904, publish_date=date(2026, 4, 17))
    future = _sow("2026-06", 3780, publish_date=date(2026, 7, 16))
    unknown = _sow("2025-12", 3961, publish_date=None)
    records = [future, unknown, visible]
    before = records.copy()
    result = calculate_sow_inventory_trend(
        records, source_type=SowSourceType.NBS, as_of=date(2026, 5, 1)
    )
    assert result.observation_keys == ("2026-03",)
    assert records == before


def test_result_is_frozen_and_contains_no_analysis_fields() -> None:
    result = _moa([1.0, 2.0])
    with pytest.raises(FrozenInstanceError):
        result.observation_count = 99  # type: ignore[misc]
    fields = set(result.__dataclass_fields__)
    assert "cycle_stage" not in fields
    assert "confidence" not in fields
    assert "investment_advice" not in fields
    assert not any(
        phrase in repr(result)
        for phrase in ("趋势确认", "投资建议", "买入", "卖出")
    )
