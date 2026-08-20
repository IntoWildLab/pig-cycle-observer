from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from src.pig_cycle.calibration_coverage import inspect_calibration_dataset
from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


def _trend(count: int) -> NumericTrendFeatures:
    value = 10.0 if count else None
    return NumericTrendFeatures(
        observation_count=count,
        latest_value=value,
        previous_value=None,
        latest_change=None,
        latest_change_pct=None,
        window_start_value=value,
        cumulative_change=None,
        cumulative_change_pct=None,
        consecutive_up_count=0,
        consecutive_down_count=0,
        latest_streak_direction=None,
        observation_keys=tuple(date(2026, 1, index + 1) for index in range(count)),
        interval_units=tuple(1 for _ in range(max(count - 1, 0))),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _outcome(horizon: int, status: ForwardOutcomeStatus) -> ForwardOutcome:
    available = status is ForwardOutcomeStatus.AVAILABLE
    return ForwardOutcome(
        horizon_weeks=horizon,
        target_date=date(2026, 3, 1),
        status=status,
        actual_collection_date=date(2026, 3, 1) if available else None,
        price=11.0 if available else None,
        return_from_start=0.10 if available else None,
        offset_days=0 if available else None,
        source_url="https://example/outcome" if available else None,
    )


def _row(
    day: int,
    *,
    quality: CalibrationQualityStatus = CalibrationQualityStatus.COMPLETE,
    horizons: tuple[int, ...] = (4, 12),
    statuses: tuple[ForwardOutcomeStatus, ...] | None = None,
    with_start: bool = True,
    source_type: SowSourceType = SowSourceType.NBS,
    trend_counts: tuple[int, int, int, int, int] = (1, 1, 1, 1, 1),
) -> CalibrationRow:
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)
    if statuses is None:
        statuses = tuple(ForwardOutcomeStatus.AVAILABLE for _ in horizons)
    trends = tuple(_trend(count) for count in trend_counts)
    return CalibrationRow(
        cutoff=cutoff,
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trends[0],
        piglet_trend=trends[1],
        corn_trend=trends[2],
        pig_corn_ratio_trend=trends[3],
        sow_source_type=source_type,
        sow_trend=trends[4],
        start_collection_date=date(2026, 1, 1) if with_start else None,
        start_price=10.0 if with_start else None,
        start_source_url="https://example/start" if with_start else None,
        outcomes=(
            tuple(_outcome(horizon, status) for horizon, status in zip(horizons, statuses))
            if with_start
            else ()
        ),
        quality_status=quality,
    )


def test_empty_dataset_returns_zero_coverage_for_requested_horizons() -> None:
    report = inspect_calibration_dataset((), horizon_weeks=(12, 4))

    assert report.total_rows == 0
    assert report.first_cutoff is None
    assert report.last_cutoff is None
    assert (
        report.complete_count,
        report.input_incomplete_count,
        report.outcome_incomplete_count,
        report.incomplete_count,
    ) == (0, 0, 0, 0)
    assert (report.rows_with_start, report.rows_without_start) == (0, 0)
    assert [coverage.horizon_weeks for coverage in report.outcome_coverage] == [
        12,
        4,
    ]
    assert all(
        (
            coverage.available_count,
            coverage.not_matured_count,
            coverage.missing_count,
            coverage.absent_count,
        )
        == (0, 0, 0, 0)
        for coverage in report.outcome_coverage
    )
    assert all(
        (
            coverage.rows_with_observations,
            coverage.rows_without_observations,
            coverage.sum_observation_counts,
            coverage.min_observation_count,
            coverage.max_observation_count,
        )
        == (0, 0, 0, None, None)
        for coverage in report.trend_coverage
    )


def test_single_complete_row_is_fully_counted() -> None:
    row = _row(0)

    report = inspect_calibration_dataset((row,), horizon_weeks=(4, 12))

    assert report.total_rows == 1
    assert report.first_cutoff == row.cutoff
    assert report.last_cutoff == row.cutoff
    assert report.complete_count == 1
    assert (report.rows_with_start, report.rows_without_start) == (1, 0)
    assert all(coverage.available_count == 1 for coverage in report.outcome_coverage)


def test_all_quality_states_are_counted_and_cutoffs_retained() -> None:
    dataset = (
        _row(0, quality=CalibrationQualityStatus.COMPLETE),
        _row(
            1,
            quality=CalibrationQualityStatus.INPUT_INCOMPLETE,
            trend_counts=(1, 1, 1, 1, 0),
        ),
        _row(
            2,
            quality=CalibrationQualityStatus.OUTCOME_INCOMPLETE,
            statuses=(ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.MISSING),
        ),
        _row(
            3,
            quality=CalibrationQualityStatus.INCOMPLETE,
            with_start=False,
            trend_counts=(0, 0, 0, 0, 0),
        ),
    )

    report = inspect_calibration_dataset(dataset, horizon_weeks=(4, 12))

    assert (
        report.complete_count,
        report.input_incomplete_count,
        report.outcome_incomplete_count,
        report.incomplete_count,
    ) == (1, 1, 1, 1)
    assert sum(item.count for item in report.quality_cutoffs) == report.total_rows
    assert tuple(item.cutoffs for item in report.quality_cutoffs) == tuple(
        (dataset[index].cutoff,) for index in range(4)
    )


def test_start_and_no_start_coverage_and_absent_semantics() -> None:
    with_start = _row(0)
    without_start = _row(
        1,
        quality=CalibrationQualityStatus.INCOMPLETE,
        with_start=False,
    )

    report = inspect_calibration_dataset(
        (with_start, without_start), horizon_weeks=(4, 12)
    )

    assert (report.rows_with_start, report.rows_without_start) == (1, 1)
    assert report.rows_without_start_cutoffs == (without_start.cutoff,)
    assert all(coverage.absent_count == 1 for coverage in report.outcome_coverage)
    assert all(coverage.available_count == 1 for coverage in report.outcome_coverage)


def test_outcome_statuses_are_counted_separately_in_request_order() -> None:
    dataset = (
        _row(0, statuses=(ForwardOutcomeStatus.AVAILABLE,) * 3, horizons=(24, 4, 12)),
        _row(
            1,
            horizons=(24, 4, 12),
            statuses=(
                ForwardOutcomeStatus.NOT_MATURED,
                ForwardOutcomeStatus.MISSING,
                ForwardOutcomeStatus.AVAILABLE,
            ),
        ),
    )

    report = inspect_calibration_dataset(dataset, horizon_weeks=(24, 4, 12))

    assert tuple(item.horizon_weeks for item in report.outcome_coverage) == (24, 4, 12)
    assert (
        report.outcome_coverage[0].available_count,
        report.outcome_coverage[0].not_matured_count,
        report.outcome_coverage[0].missing_count,
    ) == (1, 1, 0)
    assert (
        report.outcome_coverage[1].available_count,
        report.outcome_coverage[1].not_matured_count,
        report.outcome_coverage[1].missing_count,
    ) == (1, 0, 1)


@pytest.mark.parametrize(
    "actual_horizons",
    [(4,), (4, 12, 24), (12, 4)],
    ids=["missing", "extra", "wrong-order"],
)
def test_start_row_must_exactly_match_requested_horizons(
    actual_horizons: tuple[int, ...],
) -> None:
    row = _row(0, horizons=actual_horizons)

    with pytest.raises(ValueError, match="must match requested"):
        inspect_calibration_dataset((row,), horizon_weeks=(4, 12))


def test_no_start_row_with_outcomes_is_rejected() -> None:
    row = _row(0, with_start=False, quality=CalibrationQualityStatus.INCOMPLETE)
    malformed = replace(row, outcomes=(_outcome(4, ForwardOutcomeStatus.MISSING),))

    with pytest.raises(ValueError, match="must have no outcomes"):
        inspect_calibration_dataset((malformed,), horizon_weeks=(4, 12))


def test_five_trend_coverages_sum_row_observation_counts() -> None:
    dataset = (
        _row(0, trend_counts=(0, 1, 2, 3, 4)),
        _row(1, trend_counts=(2, 0, 3, 1, 5)),
    )

    report = inspect_calibration_dataset(dataset, horizon_weeks=(4, 12))
    by_name = {coverage.trend_name: coverage for coverage in report.trend_coverage}

    assert tuple(by_name) == (
        "live_hog_trend",
        "piglet_trend",
        "corn_trend",
        "pig_corn_ratio_trend",
        "sow_trend",
    )
    assert (
        by_name["live_hog_trend"].rows_with_observations,
        by_name["live_hog_trend"].rows_without_observations,
        by_name["live_hog_trend"].sum_observation_counts,
        by_name["live_hog_trend"].min_observation_count,
        by_name["live_hog_trend"].max_observation_count,
    ) == (1, 1, 2, 0, 2)
    assert by_name["sow_trend"].sum_observation_counts == 9


@pytest.mark.parametrize("cutoffs", [(1, 0), (0, 0)])
def test_cutoffs_must_be_strictly_increasing(cutoffs: tuple[int, int]) -> None:
    dataset = tuple(_row(day) for day in cutoffs)

    with pytest.raises(ValueError, match="strictly increasing"):
        inspect_calibration_dataset(dataset, horizon_weeks=(4, 12))


def test_mixed_sow_source_type_is_rejected() -> None:
    dataset = (
        _row(0, source_type=SowSourceType.NBS),
        _row(1, source_type=SowSourceType.MOA_REPORTED),
    )

    with pytest.raises(ValueError, match="one sow_source_type"):
        inspect_calibration_dataset(dataset, horizon_weeks=(4, 12))


@pytest.mark.parametrize(
    ("horizons", "error_type"),
    [
        ([4], TypeError),
        ((), ValueError),
        ((True,), TypeError),
        ((4.0,), TypeError),
        ((0,), ValueError),
        ((-1,), ValueError),
        ((4, 4), ValueError),
    ],
)
def test_invalid_horizon_request_is_rejected(
    horizons: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        inspect_calibration_dataset((), horizon_weeks=horizons)  # type: ignore[arg-type]


def test_dataset_must_be_tuple_of_calibration_rows() -> None:
    with pytest.raises(TypeError, match="dataset must be a tuple"):
        inspect_calibration_dataset([], horizon_weeks=(4,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="only CalibrationRow"):
        inspect_calibration_dataset(("bad",), horizon_weeks=(4,))  # type: ignore[arg-type]
