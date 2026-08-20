"""Orchestrate construction of one complete system calibration row."""

from __future__ import annotations

from datetime import datetime

from .calibration_builder import build_system_calibration_input_row
from .calibration_finalizer import finalize_calibration_row
from .calibration_models import CalibrationRow, ForwardOutcome
from .forward_outcome_builder import build_system_forward_outcome
from .sow_monthly import SowSourceType
from .storage import PigCycleStorage


def build_full_system_calibration_row(
    storage: PigCycleStorage,
    cutoff: datetime,
    *,
    sow_source_type: SowSourceType,
    horizon_weeks: tuple[int, ...],
    evaluation_cutoff: datetime,
    max_offset_days: int,
) -> CalibrationRow:
    """Build one calibration row by composing the existing stage builders."""

    _validate_horizons(horizon_weeks)
    _validate_evaluation_cutoff(evaluation_cutoff, cutoff)
    _require_integer(max_offset_days, "max_offset_days", minimum=0)

    input_row = build_system_calibration_input_row(
        storage,
        cutoff,
        sow_source_type=sow_source_type,
    )

    if input_row.start_collection_date is None:
        outcomes: tuple[ForwardOutcome, ...] = ()
    else:
        outcomes = tuple(
            build_system_forward_outcome(
                storage,
                input_row,
                horizon_weeks=horizon,
                evaluation_cutoff=evaluation_cutoff,
                max_offset_days=max_offset_days,
            )
            for horizon in horizon_weeks
        )

    return finalize_calibration_row(input_row, outcomes=outcomes)


def _validate_horizons(horizon_weeks: object) -> None:
    if not isinstance(horizon_weeks, tuple):
        raise TypeError("horizon_weeks must be a tuple")
    if not horizon_weeks:
        raise ValueError("horizon_weeks must not be empty")
    for horizon in horizon_weeks:
        _require_integer(horizon, "horizon_weeks item", minimum=1)
    if len(horizon_weeks) != len(set(horizon_weeks)):
        raise ValueError("horizon_weeks must not contain duplicates")


def _validate_evaluation_cutoff(
    evaluation_cutoff: object,
    cutoff: datetime,
) -> None:
    if not isinstance(evaluation_cutoff, datetime):
        raise TypeError("evaluation_cutoff must be a timezone-aware datetime")
    if evaluation_cutoff.tzinfo is None or evaluation_cutoff.utcoffset() is None:
        raise ValueError("evaluation_cutoff must be timezone-aware")
    if evaluation_cutoff < cutoff:
        raise ValueError("evaluation_cutoff must not be earlier than cutoff")


def _require_integer(value: object, field_name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
