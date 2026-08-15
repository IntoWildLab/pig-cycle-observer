"""Thin System-Knowledge reader to mechanical trend adapters."""

from __future__ import annotations

from datetime import datetime

from .storage import PigCycleStorage
from .sow_monthly import SowSourceType
from .trend import (
    MoaWeeklyMetric,
    NumericTrendFeatures,
    calculate_moa_weekly_trend,
    calculate_sow_inventory_trend,
)


def calculate_moa_weekly_trend_as_of_system(
    storage: PigCycleStorage,
    cutoff: datetime,
    *,
    metric: MoaWeeklyMetric,
) -> NumericTrendFeatures:
    """Calculate a MOA trend from revisions known to the system by ``cutoff``."""
    records = storage.get_moa_weekly_records_as_of_system(cutoff)
    return calculate_moa_weekly_trend(records, metric=metric)


def calculate_sow_inventory_trend_as_of_system(
    storage: PigCycleStorage,
    cutoff: datetime,
    *,
    source_type: SowSourceType,
) -> NumericTrendFeatures:
    """Calculate one sow source's trend from system-visible revisions."""
    records = [
        record
        for record in storage.get_sow_monthly_records_as_of_system(cutoff)
        if record.source_type is source_type
    ]
    return calculate_sow_inventory_trend(records, source_type=source_type)
