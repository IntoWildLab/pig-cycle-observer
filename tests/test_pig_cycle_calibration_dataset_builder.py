from datetime import date, datetime, timezone

import pytest

from src.pig_cycle import calibration_dataset_builder as builder
from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    KnowledgeBasis,
)
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


_STORAGE = object()
_EVALUATION_CUTOFF = datetime(2027, 1, 1, tzinfo=timezone.utc)
_CUTOFFS = (
    datetime(2026, 1, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
    datetime(2026, 2, 28, 23, 59, 59, 999999, tzinfo=timezone.utc),
    datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
)


def _trend() -> NumericTrendFeatures:
    return NumericTrendFeatures(
        observation_count=1,
        latest_value=10.0,
        previous_value=None,
        latest_change=None,
        latest_change_pct=None,
        window_start_value=10.0,
        cumulative_change=None,
        cumulative_change_pct=None,
        consecutive_up_count=0,
        consecutive_down_count=0,
        latest_streak_direction=None,
        observation_keys=(date(2026, 1, 29),),
        interval_units=(),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _row(
    cutoff: datetime,
    quality: CalibrationQualityStatus,
) -> CalibrationRow:
    trend = _trend()
    return CalibrationRow(
        cutoff=cutoff,
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trend,
        piglet_trend=trend,
        corn_trend=trend,
        pig_corn_ratio_trend=trend,
        sow_source_type=SowSourceType.NBS,
        sow_trend=trend,
        start_collection_date=date(2026, 1, 29),
        start_price=10.0,
        start_source_url="https://example/start",
        outcomes=(),
        quality_status=quality,
    )


def _build() -> tuple[CalibrationRow, ...]:
    return builder.build_monthly_system_calibration_dataset(
        _STORAGE,  # type: ignore[arg-type]
        date(2026, 1, 1),
        date(2026, 3, 1),
        sow_source_type=SowSourceType.NBS,
        horizon_weeks=(24, 4, 12),
        evaluation_cutoff=_EVALUATION_CUTOFF,
        max_offset_days=5,
    )


def test_builds_one_row_per_cutoff_and_preserves_cutoff_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[datetime] = []
    expected_rows = tuple(
        _row(cutoff, CalibrationQualityStatus.COMPLETE) for cutoff in _CUTOFFS
    )
    monkeypatch.setattr(
        builder,
        "generate_month_end_cutoffs",
        lambda start, end: _CUTOFFS,
    )

    def fake_row(storage: object, cutoff: datetime, **kwargs: object) -> CalibrationRow:
        calls.append(cutoff)
        return expected_rows[_CUTOFFS.index(cutoff)]

    monkeypatch.setattr(builder, "build_full_system_calibration_row", fake_row)

    result = _build()

    assert isinstance(result, tuple)
    assert result == expected_rows
    assert calls == list(_CUTOFFS)
    assert tuple(row.cutoff for row in result) == _CUTOFFS


def test_passes_identical_experiment_parameters_to_every_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        builder,
        "generate_month_end_cutoffs",
        lambda start, end: _CUTOFFS,
    )

    def fake_row(
        storage: object,
        cutoff: datetime,
        *,
        sow_source_type: SowSourceType,
        horizon_weeks: tuple[int, ...],
        evaluation_cutoff: datetime,
        max_offset_days: int,
    ) -> CalibrationRow:
        received.append(
            (
                storage,
                sow_source_type,
                horizon_weeks,
                evaluation_cutoff,
                max_offset_days,
            )
        )
        return _row(cutoff, CalibrationQualityStatus.COMPLETE)

    monkeypatch.setattr(builder, "build_full_system_calibration_row", fake_row)

    _build()

    assert received == [
        (_STORAGE, SowSourceType.NBS, (24, 4, 12), _EVALUATION_CUTOFF, 5)
    ] * 3


def test_preserves_rows_with_every_quality_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoffs = tuple(
        datetime(2026, month, 28, tzinfo=timezone.utc) for month in range(1, 5)
    )
    qualities = (
        CalibrationQualityStatus.COMPLETE,
        CalibrationQualityStatus.INPUT_INCOMPLETE,
        CalibrationQualityStatus.OUTCOME_INCOMPLETE,
        CalibrationQualityStatus.INCOMPLETE,
    )
    expected_rows = tuple(
        _row(cutoff, quality) for cutoff, quality in zip(cutoffs, qualities)
    )
    monkeypatch.setattr(
        builder,
        "generate_month_end_cutoffs",
        lambda start, end: cutoffs,
    )
    monkeypatch.setattr(
        builder,
        "build_full_system_calibration_row",
        lambda storage, cutoff, **kwargs: expected_rows[cutoffs.index(cutoff)],
    )

    result = _build()

    assert result == expected_rows
    assert tuple(row.quality_status for row in result) == qualities
    assert all(actual is expected for actual, expected in zip(result, expected_rows))


def test_cutoff_generator_error_propagates_before_row_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ValueError("invalid month")
    row_builder_called = False

    def fail_cutoffs(start: date, end: date) -> tuple[datetime, ...]:
        raise expected

    def fake_row(*args: object, **kwargs: object) -> CalibrationRow:
        nonlocal row_builder_called
        row_builder_called = True
        return _row(_CUTOFFS[0], CalibrationQualityStatus.COMPLETE)

    monkeypatch.setattr(builder, "generate_month_end_cutoffs", fail_cutoffs)
    monkeypatch.setattr(builder, "build_full_system_calibration_row", fake_row)

    with pytest.raises(ValueError) as error:
        _build()
    assert error.value is expected
    assert row_builder_called is False


def test_middle_row_error_stops_without_building_later_cutoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[datetime] = []
    expected = RuntimeError("February failed")
    monkeypatch.setattr(
        builder,
        "generate_month_end_cutoffs",
        lambda start, end: _CUTOFFS,
    )

    def fake_row(storage: object, cutoff: datetime, **kwargs: object) -> CalibrationRow:
        calls.append(cutoff)
        if cutoff is _CUTOFFS[1]:
            raise expected
        return _row(cutoff, CalibrationQualityStatus.COMPLETE)

    monkeypatch.setattr(builder, "build_full_system_calibration_row", fake_row)

    with pytest.raises(RuntimeError) as error:
        _build()
    assert error.value is expected
    assert calls == [_CUTOFFS[0], _CUTOFFS[1]]


def test_single_month_builds_single_row(monkeypatch: pytest.MonkeyPatch) -> None:
    cutoff = (_CUTOFFS[0],)
    expected = _row(cutoff[0], CalibrationQualityStatus.INCOMPLETE)
    monkeypatch.setattr(
        builder,
        "generate_month_end_cutoffs",
        lambda start, end: cutoff,
    )
    monkeypatch.setattr(
        builder,
        "build_full_system_calibration_row",
        lambda storage, generated_cutoff, **kwargs: expected,
    )

    result = builder.build_monthly_system_calibration_dataset(
        _STORAGE,  # type: ignore[arg-type]
        date(2026, 1, 1),
        date(2026, 1, 1),
        sow_source_type=SowSourceType.NBS,
        horizon_weeks=(4,),
        evaluation_cutoff=_EVALUATION_CUTOFF,
        max_offset_days=0,
    )

    assert result == (expected,)
    assert result[0] is expected
