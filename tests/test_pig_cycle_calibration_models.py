from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


def _trend(observation_count: int = 0) -> NumericTrendFeatures:
    value = 10.0 if observation_count else None
    return NumericTrendFeatures(
        observation_count=observation_count,
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
        observation_keys=(() if observation_count == 0 else (date(2026, 7, 2),)),
        interval_units=(),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _outcome(
    *,
    horizon_weeks: int = 5,
    status: ForwardOutcomeStatus = ForwardOutcomeStatus.AVAILABLE,
) -> ForwardOutcome:
    available = status is ForwardOutcomeStatus.AVAILABLE
    return ForwardOutcome(
        horizon_weeks=horizon_weeks,
        target_date=date(2026, 8, 6),
        status=status,
        actual_collection_date=date(2026, 8, 6) if available else None,
        price=11.0 if available else None,
        return_from_start=0.10 if available else None,
        offset_days=0 if available else None,
        source_url="https://example/weekly" if available else None,
    )


def _row(
    *,
    sow_source_type: SowSourceType = SowSourceType.NBS,
    outcomes: tuple[ForwardOutcome, ...] = (),
    trend_observations: int = 1,
    start_price: float | None = 10.0,
) -> CalibrationRow:
    trend = _trend(trend_observations)
    has_start = start_price is not None
    return CalibrationRow(
        cutoff=datetime(2026, 7, 2, tzinfo=timezone.utc),
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trend,
        piglet_trend=trend,
        corn_trend=trend,
        pig_corn_ratio_trend=trend,
        sow_source_type=sow_source_type,
        sow_trend=trend,
        start_collection_date=date(2026, 7, 2) if has_start else None,
        start_price=start_price,
        start_source_url="https://example/start" if has_start else None,
        outcomes=outcomes,
        quality_status=CalibrationQualityStatus.COMPLETE,
    )


def test_enum_members_and_values_are_stable() -> None:
    assert list(KnowledgeBasis) == [KnowledgeBasis.SYSTEM_OBSERVED]
    assert KnowledgeBasis.SYSTEM_OBSERVED.value == "system_observed"
    assert {status.value for status in ForwardOutcomeStatus} == {
        "available",
        "not_matured",
        "missing",
    }
    assert {status.value for status in CalibrationQualityStatus} == {
        "complete",
        "input_incomplete",
        "outcome_incomplete",
        "incomplete",
    }


def test_available_forward_outcome_requires_all_actual_fields() -> None:
    outcome = _outcome()
    assert outcome.price == 11.0
    assert outcome.actual_collection_date == date(2026, 8, 6)

    with pytest.raises(ValueError, match="all actual outcome fields"):
        ForwardOutcome(
            horizon_weeks=4,
            target_date=date(2026, 7, 30),
            status=ForwardOutcomeStatus.AVAILABLE,
            actual_collection_date=None,
            price=11.0,
            return_from_start=0.10,
            offset_days=0,
            source_url="https://example/weekly",
        )


@pytest.mark.parametrize(
    "status",
    [ForwardOutcomeStatus.NOT_MATURED, ForwardOutcomeStatus.MISSING],
)
def test_non_available_forward_outcomes_require_empty_actual_fields(
    status: ForwardOutcomeStatus,
) -> None:
    assert _outcome(status=status).price is None

    with pytest.raises(ValueError, match="all actual fields to be None"):
        ForwardOutcome(
            horizon_weeks=4,
            target_date=date(2026, 7, 30),
            status=status,
            actual_collection_date=None,
            price=11.0,
            return_from_start=None,
            offset_days=None,
            source_url=None,
        )


@pytest.mark.parametrize("horizon_weeks", [0, -1])
def test_forward_outcome_rejects_non_positive_horizon(horizon_weeks: int) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        _outcome(horizon_weeks=horizon_weeks)


def test_calibration_row_accepts_configurable_horizons_and_zero_or_one_input() -> None:
    row = _row(
        outcomes=(_outcome(horizon_weeks=3), _outcome(horizon_weeks=17)),
        trend_observations=0,
        start_price=None,
    )
    assert [outcome.horizon_weeks for outcome in row.outcomes] == [3, 17]
    assert row.live_hog_trend.observation_count == 0
    assert row.start_collection_date is None
    assert row.start_price is None
    assert row.start_source_url is None

    one_observation = _row(trend_observations=1)
    assert one_observation.sow_trend.observation_count == 1


def test_calibration_row_rejects_naive_cutoff() -> None:
    row = _row()
    with pytest.raises(ValueError, match="timezone-aware"):
        CalibrationRow(
            **{
                **row.__dict__,
                "cutoff": datetime(2026, 7, 2),
            }
        )


def test_calibration_row_requires_consistent_start_provenance() -> None:
    row = _row()
    with pytest.raises(ValueError, match="start fields"):
        CalibrationRow(
            **{
                **row.__dict__,
                "start_source_url": None,
            }
        )


def test_calibration_row_rejects_duplicate_outcome_horizons() -> None:
    with pytest.raises(ValueError, match="duplicate horizon_weeks"):
        _row(outcomes=(_outcome(horizon_weeks=8), _outcome(horizon_weeks=8)))


def test_calibration_row_rejects_mutable_outcomes_list() -> None:
    with pytest.raises(TypeError, match="outcomes must be a tuple"):
        _row(outcomes=[_outcome()])  # type: ignore[arg-type]


def test_calibration_row_rejects_non_outcome_tuple_member() -> None:
    with pytest.raises(TypeError, match="only ForwardOutcome"):
        _row(outcomes=(_outcome(), "not-an-outcome"))  # type: ignore[arg-type]


@pytest.mark.parametrize("source_type", list(SowSourceType))
def test_calibration_row_preserves_declared_sow_source(
    source_type: SowSourceType,
) -> None:
    assert _row(sow_source_type=source_type).sow_source_type is source_type


def test_models_are_frozen() -> None:
    outcome = _outcome()
    row = _row(outcomes=(outcome,))

    with pytest.raises(FrozenInstanceError):
        outcome.price = 12.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        row.quality_status = CalibrationQualityStatus.INCOMPLETE  # type: ignore[misc]
