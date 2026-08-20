from datetime import date, datetime, timedelta, timezone

import pytest

from src.pig_cycle import full_calibration_builder as builder
from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


_CUTOFF = datetime(2026, 7, 31, 23, 59, 59, tzinfo=timezone.utc)
_EVALUATION_CUTOFF = datetime(2027, 2, 1, tzinfo=timezone.utc)
_STORAGE = object()


def _trend(observation_count: int = 1) -> NumericTrendFeatures:
    has_data = observation_count > 0
    return NumericTrendFeatures(
        observation_count=observation_count,
        latest_value=10.0 if has_data else None,
        previous_value=None,
        latest_change=None,
        latest_change_pct=None,
        window_start_value=10.0 if has_data else None,
        cumulative_change=None,
        cumulative_change_pct=None,
        consecutive_up_count=0,
        consecutive_down_count=0,
        latest_streak_direction=None,
        observation_keys=(date(2026, 7, 30),) if has_data else (),
        interval_units=(),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _input_row(
    quality: CalibrationQualityStatus = CalibrationQualityStatus.OUTCOME_INCOMPLETE,
    *,
    with_start: bool = True,
) -> CalibrationRow:
    trend = _trend()
    return CalibrationRow(
        cutoff=_CUTOFF,
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trend,
        piglet_trend=trend,
        corn_trend=trend,
        pig_corn_ratio_trend=trend,
        sow_source_type=SowSourceType.NBS,
        sow_trend=trend,
        start_collection_date=date(2026, 7, 30) if with_start else None,
        start_price=10.0 if with_start else None,
        start_source_url="https://example/start" if with_start else None,
        outcomes=(),
        quality_status=quality,
    )


def _outcome(
    horizon: int,
    status: ForwardOutcomeStatus = ForwardOutcomeStatus.AVAILABLE,
) -> ForwardOutcome:
    available = status is ForwardOutcomeStatus.AVAILABLE
    return ForwardOutcome(
        horizon_weeks=horizon,
        target_date=date(2026, 8, 27),
        status=status,
        actual_collection_date=date(2026, 8, 27) if available else None,
        price=11.0 if available else None,
        return_from_start=0.10 if available else None,
        offset_days=0 if available else None,
        source_url="https://example/outcome" if available else None,
    )


def _build(**overrides: object) -> CalibrationRow:
    arguments = {
        "sow_source_type": SowSourceType.NBS,
        "horizon_weeks": (4, 12),
        "evaluation_cutoff": _EVALUATION_CUTOFF,
        "max_offset_days": 3,
    }
    arguments.update(overrides)
    return builder.build_full_system_calibration_row(
        _STORAGE,  # type: ignore[arg-type]
        _CUTOFF,
        **arguments,  # type: ignore[arg-type]
    )


def _patch_stages(
    monkeypatch: pytest.MonkeyPatch,
    input_row: CalibrationRow,
    statuses: dict[int, ForwardOutcomeStatus] | None = None,
) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(
        builder,
        "build_system_calibration_input_row",
        lambda storage, cutoff, *, sow_source_type: input_row,
    )

    def fake_outcome(
        storage: object,
        row: CalibrationRow,
        *,
        horizon_weeks: int,
        evaluation_cutoff: datetime,
        max_offset_days: int,
    ) -> ForwardOutcome:
        calls.append(horizon_weeks)
        status = (statuses or {}).get(
            horizon_weeks, ForwardOutcomeStatus.AVAILABLE
        )
        return _outcome(horizon_weeks, status)

    monkeypatch.setattr(builder, "build_system_forward_outcome", fake_outcome)
    return calls


def test_complete_input_and_available_outcomes_finalize_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stages(monkeypatch, _input_row())

    row = _build()

    assert row.quality_status is CalibrationQualityStatus.COMPLETE
    assert [outcome.status for outcome in row.outcomes] == [
        ForwardOutcomeStatus.AVAILABLE,
        ForwardOutcomeStatus.AVAILABLE,
    ]


def test_incomplete_input_with_start_still_builds_available_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_stages(
        monkeypatch,
        _input_row(CalibrationQualityStatus.INCOMPLETE),
    )

    row = _build()

    assert calls == [4, 12]
    assert row.quality_status is CalibrationQualityStatus.INPUT_INCOMPLETE


def test_missing_start_skips_outcome_builder_and_preserves_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_stages(
        monkeypatch,
        _input_row(CalibrationQualityStatus.INCOMPLETE, with_start=False),
    )

    row = _build()

    assert calls == []
    assert row.outcomes == ()
    assert row.quality_status is CalibrationQualityStatus.INCOMPLETE


@pytest.mark.parametrize(
    "incomplete_status",
    [ForwardOutcomeStatus.NOT_MATURED, ForwardOutcomeStatus.MISSING],
)
def test_mixed_outcome_states_are_all_preserved(
    monkeypatch: pytest.MonkeyPatch,
    incomplete_status: ForwardOutcomeStatus,
) -> None:
    calls = _patch_stages(
        monkeypatch,
        _input_row(),
        {12: incomplete_status},
    )

    row = _build()

    assert calls == [4, 12]
    assert [outcome.status for outcome in row.outcomes] == [
        ForwardOutcomeStatus.AVAILABLE,
        incomplete_status,
    ]
    assert row.quality_status is CalibrationQualityStatus.OUTCOME_INCOMPLETE


def test_caller_horizon_order_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_stages(monkeypatch, _input_row())

    row = _build(horizon_weeks=(24, 4, 12))

    assert calls == [24, 4, 12]
    assert tuple(outcome.horizon_weeks for outcome in row.outcomes) == (24, 4, 12)


@pytest.mark.parametrize("horizons", [[4], "4,12"])
def test_horizons_must_be_a_tuple(horizons: object) -> None:
    with pytest.raises(TypeError, match="must be a tuple"):
        _build(horizon_weeks=horizons)


def test_horizons_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _build(horizon_weeks=())


@pytest.mark.parametrize("horizons", [(True,), (4.0,), ("4",)])
def test_horizon_items_must_be_integers(horizons: tuple[object, ...]) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        _build(horizon_weeks=horizons)


@pytest.mark.parametrize("horizons", [(0,), (-1,)])
def test_horizons_must_be_positive(horizons: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        _build(horizon_weeks=horizons)


def test_duplicate_horizons_are_rejected_before_building_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_input(*args: object, **kwargs: object) -> CalibrationRow:
        nonlocal called
        called = True
        return _input_row()

    monkeypatch.setattr(builder, "build_system_calibration_input_row", fake_input)

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _build(horizon_weeks=(4, 4))
    assert called is False


@pytest.mark.parametrize("value", [True, 1.5, "3"])
def test_max_offset_days_must_be_an_integer(value: object) -> None:
    with pytest.raises(TypeError, match="max_offset_days must be an integer"):
        _build(max_offset_days=value)


def test_max_offset_days_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="max_offset_days must be at least 0"):
        _build(max_offset_days=-1)


def test_evaluation_cutoff_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="must be timezone-aware"):
        _build(evaluation_cutoff=datetime(2027, 2, 1))


def test_evaluation_cutoff_must_not_precede_cutoff() -> None:
    with pytest.raises(ValueError, match="must not be earlier"):
        _build(evaluation_cutoff=_CUTOFF - timedelta(seconds=1))


def test_input_builder_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = RuntimeError("input failed")

    def fail(*args: object, **kwargs: object) -> CalibrationRow:
        raise expected

    monkeypatch.setattr(builder, "build_system_calibration_input_row", fail)

    with pytest.raises(RuntimeError) as error:
        _build()
    assert error.value is expected


def test_outcome_builder_error_propagates_without_skipping_horizon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        builder,
        "build_system_calibration_input_row",
        lambda *args, **kwargs: _input_row(),
    )
    calls: list[int] = []
    expected = ValueError("outcome failed")

    def fail_on_second(
        storage: object,
        row: CalibrationRow,
        *,
        horizon_weeks: int,
        evaluation_cutoff: datetime,
        max_offset_days: int,
    ) -> ForwardOutcome:
        calls.append(horizon_weeks)
        if horizon_weeks == 12:
            raise expected
        return _outcome(horizon_weeks)

    monkeypatch.setattr(builder, "build_system_forward_outcome", fail_on_second)

    with pytest.raises(ValueError) as error:
        _build(horizon_weeks=(4, 12, 24))
    assert error.value is expected
    assert calls == [4, 12]


def test_final_row_preserves_input_trends_and_start_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_row = _input_row()
    _patch_stages(monkeypatch, input_row)

    row = _build(horizon_weeks=(4,))

    assert row.live_hog_trend is input_row.live_hog_trend
    assert row.piglet_trend is input_row.piglet_trend
    assert row.corn_trend is input_row.corn_trend
    assert row.pig_corn_ratio_trend is input_row.pig_corn_ratio_trend
    assert row.sow_trend is input_row.sow_trend
    assert row.start_collection_date == input_row.start_collection_date
    assert row.start_price == input_row.start_price
    assert row.start_source_url == input_row.start_source_url
