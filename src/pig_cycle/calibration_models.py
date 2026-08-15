"""Immutable experiment records for future historical calibration work."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from .sow_monthly import SowSourceType
from .trend import NumericTrendFeatures


class KnowledgeBasis(str, Enum):
    """Evidence basis used to construct a calibration input row."""

    SYSTEM_OBSERVED = "system_observed"


class ForwardOutcomeStatus(str, Enum):
    """Availability state of one requested forward outcome horizon."""

    AVAILABLE = "available"
    NOT_MATURED = "not_matured"
    MISSING = "missing"


@dataclass(frozen=True)
class ForwardOutcome:
    """One builder-produced realized outcome at a configurable horizon."""

    horizon_weeks: int
    target_date: date
    status: ForwardOutcomeStatus
    actual_collection_date: date | None
    price: float | None
    return_from_start: float | None
    offset_days: int | None
    source_url: str | None

    def __post_init__(self) -> None:
        if isinstance(self.horizon_weeks, bool) or not isinstance(
            self.horizon_weeks, int
        ):
            raise TypeError("horizon_weeks must be a positive integer")
        if self.horizon_weeks <= 0:
            raise ValueError("horizon_weeks must be greater than zero")
        if not isinstance(self.status, ForwardOutcomeStatus):
            raise TypeError("status must be a ForwardOutcomeStatus")

        actual_fields = (
            self.actual_collection_date,
            self.price,
            self.return_from_start,
            self.offset_days,
            self.source_url,
        )
        if self.status is ForwardOutcomeStatus.AVAILABLE:
            if any(value is None for value in actual_fields):
                raise ValueError("available outcome requires all actual outcome fields")
            _require_finite(self.price, "price")
            _require_finite(self.return_from_start, "return_from_start")
        elif any(value is not None for value in actual_fields):
            raise ValueError("non-available outcome requires all actual fields to be None")


class CalibrationQualityStatus(str, Enum):
    """Builder-assigned completeness status for one calibration row."""

    COMPLETE = "complete"
    INPUT_INCOMPLETE = "input_incomplete"
    OUTCOME_INCOMPLETE = "outcome_incomplete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class CalibrationRow:
    """Inputs and realized outcomes for one historical experiment cutoff."""

    cutoff: datetime
    knowledge_basis: KnowledgeBasis
    live_hog_trend: NumericTrendFeatures
    piglet_trend: NumericTrendFeatures
    corn_trend: NumericTrendFeatures
    pig_corn_ratio_trend: NumericTrendFeatures
    sow_source_type: SowSourceType
    sow_trend: NumericTrendFeatures
    start_collection_date: date | None
    start_price: float | None
    start_source_url: str | None
    outcomes: tuple[ForwardOutcome, ...]
    quality_status: CalibrationQualityStatus

    def __post_init__(self) -> None:
        if not isinstance(self.cutoff, datetime):
            raise TypeError("cutoff must be a timezone-aware datetime")
        if self.cutoff.tzinfo is None or self.cutoff.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")
        if not isinstance(self.knowledge_basis, KnowledgeBasis):
            raise TypeError("knowledge_basis must be a KnowledgeBasis")
        if not isinstance(self.sow_source_type, SowSourceType):
            raise TypeError("sow_source_type must be a SowSourceType")
        if not isinstance(self.quality_status, CalibrationQualityStatus):
            raise TypeError("quality_status must be a CalibrationQualityStatus")

        start_fields = (
            self.start_collection_date,
            self.start_price,
            self.start_source_url,
        )
        present_count = sum(value is not None for value in start_fields)
        if present_count not in (0, len(start_fields)):
            raise ValueError("start fields must either all be present or all be None")
        if self.start_price is not None:
            _require_finite(self.start_price, "start_price")

        if not isinstance(self.outcomes, tuple):
            raise TypeError("outcomes must be a tuple")
        if any(not isinstance(outcome, ForwardOutcome) for outcome in self.outcomes):
            raise TypeError("outcomes must contain only ForwardOutcome values")
        horizons = tuple(outcome.horizon_weeks for outcome in self.outcomes)
        if len(horizons) != len(set(horizons)):
            raise ValueError("outcomes must not contain duplicate horizon_weeks")


def _require_finite(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
