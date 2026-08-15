"""Build one realized MOA outcome from System-Knowledge evidence."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .calibration_models import (
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from .storage import PigCycleStorage


_CHINA_BUSINESS_TIMEZONE = timezone(timedelta(hours=8))


def build_system_forward_outcome(
    storage: PigCycleStorage,
    row: CalibrationRow,
    *,
    horizon_weeks: int,
    evaluation_cutoff: datetime,
    max_offset_days: int,
) -> ForwardOutcome:
    """Build one forward live-hog outcome known by ``evaluation_cutoff``."""
    if row.knowledge_basis is not KnowledgeBasis.SYSTEM_OBSERVED:
        raise ValueError("row knowledge_basis must be system_observed")
    _require_integer(horizon_weeks, "horizon_weeks", minimum=1)
    _require_integer(max_offset_days, "max_offset_days", minimum=0)
    if not isinstance(evaluation_cutoff, datetime):
        raise TypeError("evaluation_cutoff must be a timezone-aware datetime")
    if evaluation_cutoff.tzinfo is None or evaluation_cutoff.utcoffset() is None:
        raise ValueError("evaluation_cutoff must be timezone-aware")
    if evaluation_cutoff < row.cutoff:
        raise ValueError("evaluation_cutoff must not be earlier than row cutoff")

    if (
        row.start_collection_date is None
        or row.start_price is None
        or row.start_source_url is None
    ):
        raise ValueError("row must contain complete start provenance")
    if not row.start_price > 0:
        raise ValueError("row start_price must be greater than zero")

    cutoff_china_date = row.cutoff.astimezone(_CHINA_BUSINESS_TIMEZONE).date()
    target_date = cutoff_china_date + timedelta(weeks=horizon_weeks)
    window_start = target_date - timedelta(days=max_offset_days)
    window_end = target_date + timedelta(days=max_offset_days)
    if window_start <= cutoff_china_date:
        raise ValueError("outcome window must be strictly after calibration cutoff date")

    evaluation_local_date = evaluation_cutoff.astimezone(
        _CHINA_BUSINESS_TIMEZONE
    ).date()
    if evaluation_local_date <= window_end:
        return _empty_outcome(
            horizon_weeks=horizon_weeks,
            target_date=target_date,
            status=ForwardOutcomeStatus.NOT_MATURED,
        )

    records = storage.get_moa_weekly_records_as_of_system(evaluation_cutoff)
    candidates = [
        record
        for record in records
        if window_start <= record.collection_date <= window_end
    ]
    if not candidates:
        return _empty_outcome(
            horizon_weeks=horizon_weeks,
            target_date=target_date,
            status=ForwardOutcomeStatus.MISSING,
        )

    selected = min(
        candidates,
        key=lambda record: (
            abs((record.collection_date - target_date).days),
            record.collection_date,
        ),
    )
    return ForwardOutcome(
        horizon_weeks=horizon_weeks,
        target_date=target_date,
        status=ForwardOutcomeStatus.AVAILABLE,
        actual_collection_date=selected.collection_date,
        price=selected.live_hog_price,
        return_from_start=selected.live_hog_price / row.start_price - 1,
        offset_days=(selected.collection_date - target_date).days,
        source_url=selected.source_url,
    )


def _empty_outcome(
    *,
    horizon_weeks: int,
    target_date: date,
    status: ForwardOutcomeStatus,
) -> ForwardOutcome:
    return ForwardOutcome(
        horizon_weeks=horizon_weeks,
        target_date=target_date,
        status=status,
        actual_collection_date=None,
        price=None,
        return_from_start=None,
        offset_days=None,
        source_url=None,
    )


def _require_integer(value: object, field_name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
