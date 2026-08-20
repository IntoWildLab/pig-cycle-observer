from datetime import date, datetime, timezone

import pytest

from src.pig_cycle.calibration_finalizer import finalize_calibration_row
from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


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
        observation_keys=(date(2026, 7, 2),),
        interval_units=(),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _row(
    quality_status: CalibrationQualityStatus = (
        CalibrationQualityStatus.OUTCOME_INCOMPLETE
    ),
    *,
    outcomes: tuple[ForwardOutcome, ...] = (),
) -> CalibrationRow:
    trend = _trend()
    return CalibrationRow(
        cutoff=datetime(2026, 7, 2, tzinfo=timezone.utc),
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trend,
        piglet_trend=trend,
        corn_trend=trend,
        pig_corn_ratio_trend=trend,
        sow_source_type=SowSourceType.NBS,
        sow_trend=trend,
        start_collection_date=date(2026, 7, 2),
        start_price=10.0,
        start_source_url="https://example/start",
        outcomes=outcomes,
        quality_status=quality_status,
    )


def _outcome(
    horizon_weeks: int,
    status: ForwardOutcomeStatus = ForwardOutcomeStatus.AVAILABLE,
) -> ForwardOutcome:
    available = status is ForwardOutcomeStatus.AVAILABLE
    return ForwardOutcome(
        horizon_weeks=horizon_weeks,
        target_date=date(2026, 7, 30),
        status=status,
        actual_collection_date=date(2026, 7, 30) if available else None,
        price=11.0 if available else None,
        return_from_start=0.10 if available else None,
        offset_days=0 if available else None,
        source_url="https://example/outcome" if available else None,
    )


@pytest.mark.parametrize(
    ("input_quality", "outcome_statuses", "expected_quality"),
    [
        (
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
            (ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.AVAILABLE),
            CalibrationQualityStatus.COMPLETE,
        ),
        (
            CalibrationQualityStatus.INCOMPLETE,
            (ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.AVAILABLE),
            CalibrationQualityStatus.INPUT_INCOMPLETE,
        ),
        (
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
            (ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.NOT_MATURED),
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
        ),
        (
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
            (ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.MISSING),
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
        ),
        (
            CalibrationQualityStatus.INCOMPLETE,
            (ForwardOutcomeStatus.AVAILABLE, ForwardOutcomeStatus.MISSING),
            CalibrationQualityStatus.INCOMPLETE,
        ),
        (
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
            (),
            CalibrationQualityStatus.OUTCOME_INCOMPLETE,
        ),
        (
            CalibrationQualityStatus.INCOMPLETE,
            (),
            CalibrationQualityStatus.INCOMPLETE,
        ),
    ],
)
def test_final_quality_uses_input_and_outcome_completeness(
    input_quality: CalibrationQualityStatus,
    outcome_statuses: tuple[ForwardOutcomeStatus, ...],
    expected_quality: CalibrationQualityStatus,
) -> None:
    input_row = _row(input_quality)
    outcomes = tuple(
        _outcome(index + 1, status)
        for index, status in enumerate(outcome_statuses)
    )

    finalized = finalize_calibration_row(input_row, outcomes=outcomes)

    assert finalized.quality_status is expected_quality
    assert finalized.outcomes == outcomes


def test_finalizer_returns_new_row_and_preserves_all_input_fields() -> None:
    input_row = _row()
    outcomes = (_outcome(12), _outcome(4))

    finalized = finalize_calibration_row(input_row, outcomes=outcomes)

    assert finalized is not input_row
    assert input_row.outcomes == ()
    assert input_row.quality_status is CalibrationQualityStatus.OUTCOME_INCOMPLETE
    for field_name in (
        "cutoff",
        "knowledge_basis",
        "live_hog_trend",
        "piglet_trend",
        "corn_trend",
        "pig_corn_ratio_trend",
        "sow_source_type",
        "sow_trend",
        "start_collection_date",
        "start_price",
        "start_source_url",
    ):
        assert getattr(finalized, field_name) == getattr(input_row, field_name)
    assert finalized.outcomes == outcomes
    assert [outcome.horizon_weeks for outcome in finalized.outcomes] == [12, 4]


def test_finalizer_rejects_input_row_with_existing_outcomes() -> None:
    with pytest.raises(ValueError, match="must not already contain outcomes"):
        finalize_calibration_row(
            _row(outcomes=(_outcome(4),)),
            outcomes=(_outcome(12),),
        )


@pytest.mark.parametrize(
    "quality_status",
    [CalibrationQualityStatus.COMPLETE, CalibrationQualityStatus.INPUT_INCOMPLETE],
)
def test_finalizer_rejects_invalid_starting_quality(
    quality_status: CalibrationQualityStatus,
) -> None:
    with pytest.raises(ValueError, match="invalid starting quality_status"):
        finalize_calibration_row(_row(quality_status), outcomes=(_outcome(4),))


def test_finalizer_rejects_mutable_outcomes_list() -> None:
    with pytest.raises(TypeError, match="outcomes must be a tuple"):
        finalize_calibration_row(
            _row(),
            outcomes=[_outcome(4)],  # type: ignore[arg-type]
        )


def test_finalizer_rejects_non_outcome_tuple_member() -> None:
    with pytest.raises(TypeError, match="only ForwardOutcome"):
        finalize_calibration_row(
            _row(),
            outcomes=(_outcome(4), "invalid"),  # type: ignore[arg-type]
        )


def test_duplicate_horizon_is_rejected_by_calibration_row_model() -> None:
    input_row = _row()
    duplicate_outcomes = (_outcome(4), _outcome(4))

    with pytest.raises(ValueError, match="duplicate horizon_weeks"):
        finalize_calibration_row(input_row, outcomes=duplicate_outcomes)
