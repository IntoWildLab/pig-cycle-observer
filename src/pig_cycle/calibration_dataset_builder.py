"""Build monthly calibration datasets from the existing row orchestration."""

from __future__ import annotations

from datetime import date, datetime

from .calibration_models import CalibrationRow
from .cutoff_generator import generate_month_end_cutoffs
from .full_calibration_builder import build_full_system_calibration_row
from .sow_monthly import SowSourceType
from .storage import PigCycleStorage


def build_monthly_system_calibration_dataset(
    storage: PigCycleStorage,
    start_month: date,
    end_month: date,
    *,
    sow_source_type: SowSourceType,
    horizon_weeks: tuple[int, ...],
    evaluation_cutoff: datetime,
    max_offset_days: int,
) -> tuple[CalibrationRow, ...]:
    """Build one calibration row for each generated monthly cutoff."""

    cutoffs = generate_month_end_cutoffs(start_month, end_month)
    return tuple(
        build_full_system_calibration_row(
            storage,
            cutoff,
            sow_source_type=sow_source_type,
            horizon_weeks=horizon_weeks,
            evaluation_cutoff=evaluation_cutoff,
            max_offset_days=max_offset_days,
        )
        for cutoff in cutoffs
    )
