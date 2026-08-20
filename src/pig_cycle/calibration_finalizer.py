"""Finalize one calibration input row with caller-built forward outcomes."""

from __future__ import annotations

from dataclasses import replace

from .calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
)


def finalize_calibration_row(
    input_row: CalibrationRow,
    *,
    outcomes: tuple[ForwardOutcome, ...],
) -> CalibrationRow:
    """Return a finalized immutable row without recomputing inputs or outcomes."""
    if input_row.outcomes != ():
        raise ValueError("input_row must not already contain outcomes")
    if input_row.quality_status not in (
        CalibrationQualityStatus.OUTCOME_INCOMPLETE,
        CalibrationQualityStatus.INCOMPLETE,
    ):
        raise ValueError("input_row has an invalid starting quality_status")
    if not isinstance(outcomes, tuple):
        raise TypeError("outcomes must be a tuple")
    if any(not isinstance(outcome, ForwardOutcome) for outcome in outcomes):
        raise TypeError("outcomes must contain only ForwardOutcome values")

    input_complete = (
        input_row.quality_status is CalibrationQualityStatus.OUTCOME_INCOMPLETE
    )
    outcomes_complete = bool(outcomes) and all(
        outcome.status is ForwardOutcomeStatus.AVAILABLE for outcome in outcomes
    )
    if input_complete and outcomes_complete:
        quality_status = CalibrationQualityStatus.COMPLETE
    elif not input_complete and outcomes_complete:
        quality_status = CalibrationQualityStatus.INPUT_INCOMPLETE
    elif input_complete:
        quality_status = CalibrationQualityStatus.OUTCOME_INCOMPLETE
    else:
        quality_status = CalibrationQualityStatus.INCOMPLETE

    return replace(
        input_row,
        outcomes=outcomes,
        quality_status=quality_status,
    )
