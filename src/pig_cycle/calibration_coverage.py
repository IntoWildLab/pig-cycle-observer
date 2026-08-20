"""Pure descriptive coverage inspection for calibration datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcomeStatus,
)


@dataclass(frozen=True)
class CalibrationOutcomeCoverage:
    horizon_weeks: int
    available_count: int
    not_matured_count: int
    missing_count: int
    absent_count: int


@dataclass(frozen=True)
class CalibrationTrendCoverage:
    trend_name: str
    rows_with_observations: int
    rows_without_observations: int
    sum_observation_counts: int
    min_observation_count: int | None
    max_observation_count: int | None


@dataclass(frozen=True)
class CalibrationQualityCutoffs:
    quality_status: CalibrationQualityStatus
    count: int
    cutoffs: tuple[datetime, ...]


@dataclass(frozen=True)
class CalibrationCoverageReport:
    total_rows: int
    first_cutoff: datetime | None
    last_cutoff: datetime | None
    complete_count: int
    input_incomplete_count: int
    outcome_incomplete_count: int
    incomplete_count: int
    rows_with_start: int
    rows_without_start: int
    rows_without_start_cutoffs: tuple[datetime, ...]
    quality_cutoffs: tuple[CalibrationQualityCutoffs, ...]
    outcome_coverage: tuple[CalibrationOutcomeCoverage, ...]
    trend_coverage: tuple[CalibrationTrendCoverage, ...]


_QUALITY_ORDER = (
    CalibrationQualityStatus.COMPLETE,
    CalibrationQualityStatus.INPUT_INCOMPLETE,
    CalibrationQualityStatus.OUTCOME_INCOMPLETE,
    CalibrationQualityStatus.INCOMPLETE,
)

_TREND_FIELDS = (
    "live_hog_trend",
    "piglet_trend",
    "corn_trend",
    "pig_corn_ratio_trend",
    "sow_trend",
)


def inspect_calibration_dataset(
    dataset: tuple[CalibrationRow, ...],
    *,
    horizon_weeks: tuple[int, ...],
) -> CalibrationCoverageReport:
    """Describe dataset coverage without rebuilding or filtering any row."""

    _validate_inputs(dataset, horizon_weeks)

    quality_cutoff_map = {
        quality: tuple(row.cutoff for row in dataset if row.quality_status is quality)
        for quality in _QUALITY_ORDER
    }
    rows_without_start_cutoffs = tuple(
        row.cutoff for row in dataset if row.start_collection_date is None
    )

    outcome_counts = {
        horizon: {
            ForwardOutcomeStatus.AVAILABLE: 0,
            ForwardOutcomeStatus.NOT_MATURED: 0,
            ForwardOutcomeStatus.MISSING: 0,
            "absent": 0,
        }
        for horizon in horizon_weeks
    }
    for row in dataset:
        if row.start_collection_date is None:
            for horizon in horizon_weeks:
                outcome_counts[horizon]["absent"] += 1
            continue
        for outcome in row.outcomes:
            outcome_counts[outcome.horizon_weeks][outcome.status] += 1

    outcome_coverage = tuple(
        CalibrationOutcomeCoverage(
            horizon_weeks=horizon,
            available_count=outcome_counts[horizon][
                ForwardOutcomeStatus.AVAILABLE
            ],
            not_matured_count=outcome_counts[horizon][
                ForwardOutcomeStatus.NOT_MATURED
            ],
            missing_count=outcome_counts[horizon][ForwardOutcomeStatus.MISSING],
            absent_count=outcome_counts[horizon]["absent"],
        )
        for horizon in horizon_weeks
    )

    trend_coverage = tuple(
        _inspect_trend(dataset, trend_name) for trend_name in _TREND_FIELDS
    )
    quality_counts = {
        quality: len(quality_cutoff_map[quality]) for quality in _QUALITY_ORDER
    }
    total_rows = len(dataset)

    return CalibrationCoverageReport(
        total_rows=total_rows,
        first_cutoff=dataset[0].cutoff if dataset else None,
        last_cutoff=dataset[-1].cutoff if dataset else None,
        complete_count=quality_counts[CalibrationQualityStatus.COMPLETE],
        input_incomplete_count=quality_counts[
            CalibrationQualityStatus.INPUT_INCOMPLETE
        ],
        outcome_incomplete_count=quality_counts[
            CalibrationQualityStatus.OUTCOME_INCOMPLETE
        ],
        incomplete_count=quality_counts[CalibrationQualityStatus.INCOMPLETE],
        rows_with_start=total_rows - len(rows_without_start_cutoffs),
        rows_without_start=len(rows_without_start_cutoffs),
        rows_without_start_cutoffs=rows_without_start_cutoffs,
        quality_cutoffs=tuple(
            CalibrationQualityCutoffs(
                quality_status=quality,
                count=quality_counts[quality],
                cutoffs=quality_cutoff_map[quality],
            )
            for quality in _QUALITY_ORDER
        ),
        outcome_coverage=outcome_coverage,
        trend_coverage=trend_coverage,
    )


def _validate_inputs(
    dataset: object,
    horizon_weeks: object,
) -> None:
    if type(dataset) is not tuple:
        raise TypeError("dataset must be a tuple")
    if any(not isinstance(row, CalibrationRow) for row in dataset):
        raise TypeError("dataset must contain only CalibrationRow values")

    if type(horizon_weeks) is not tuple:
        raise TypeError("horizon_weeks must be a tuple")
    if not horizon_weeks:
        raise ValueError("horizon_weeks must not be empty")
    for horizon in horizon_weeks:
        if isinstance(horizon, bool) or not isinstance(horizon, int):
            raise TypeError("horizon_weeks items must be integers")
        if horizon <= 0:
            raise ValueError("horizon_weeks items must be greater than zero")
    if len(horizon_weeks) != len(set(horizon_weeks)):
        raise ValueError("horizon_weeks must not contain duplicates")

    cutoffs = tuple(row.cutoff for row in dataset)
    if any(current <= previous for previous, current in zip(cutoffs, cutoffs[1:])):
        raise ValueError("dataset cutoffs must be strictly increasing")

    source_types = {row.sow_source_type for row in dataset}
    if len(source_types) > 1:
        raise ValueError("dataset rows must use one sow_source_type")

    for row in dataset:
        actual_horizons = tuple(outcome.horizon_weeks for outcome in row.outcomes)
        if row.start_collection_date is None:
            if actual_horizons:
                raise ValueError("row without start provenance must have no outcomes")
        elif actual_horizons != horizon_weeks:
            raise ValueError(
                "row with start provenance must match requested horizon_weeks"
            )


def _inspect_trend(
    dataset: tuple[CalibrationRow, ...],
    trend_name: str,
) -> CalibrationTrendCoverage:
    counts = tuple(getattr(row, trend_name).observation_count for row in dataset)
    rows_with_observations = sum(count >= 1 for count in counts)
    return CalibrationTrendCoverage(
        trend_name=trend_name,
        rows_with_observations=rows_with_observations,
        rows_without_observations=len(counts) - rows_with_observations,
        sum_observation_counts=sum(counts),
        min_observation_count=min(counts) if counts else None,
        max_observation_count=max(counts) if counts else None,
    )
