"""Build historical calibration inputs from System-Knowledge records."""

from __future__ import annotations

from datetime import datetime

from .calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    KnowledgeBasis,
)
from .sow_monthly import SowSourceType
from .storage import PigCycleStorage
from .trend import (
    MoaWeeklyMetric,
    calculate_moa_weekly_trend,
    calculate_sow_inventory_trend,
)


def build_system_calibration_input_row(
    storage: PigCycleStorage,
    cutoff: datetime,
    *,
    sow_source_type: SowSourceType,
) -> CalibrationRow:
    """Build one outcome-free calibration input at a System-Knowledge cutoff."""
    moa_records = storage.get_moa_weekly_records_as_of_system(cutoff)
    live_hog_trend = calculate_moa_weekly_trend(
        moa_records, metric=MoaWeeklyMetric.LIVE_HOG_PRICE
    )
    piglet_trend = calculate_moa_weekly_trend(
        moa_records, metric=MoaWeeklyMetric.PIGLET_PRICE
    )
    corn_trend = calculate_moa_weekly_trend(
        moa_records, metric=MoaWeeklyMetric.CORN_PRICE
    )
    pig_corn_ratio_trend = calculate_moa_weekly_trend(
        moa_records, metric=MoaWeeklyMetric.DERIVED_PIG_CORN_RATIO
    )

    latest_moa = moa_records[-1] if moa_records else None
    start_collection_date = (
        latest_moa.collection_date if latest_moa is not None else None
    )
    start_price = latest_moa.live_hog_price if latest_moa is not None else None
    start_source_url = latest_moa.source_url if latest_moa is not None else None

    sow_records = [
        record
        for record in storage.get_sow_monthly_records_as_of_system(cutoff)
        if record.source_type is sow_source_type
    ]
    sow_trend = calculate_sow_inventory_trend(
        sow_records,
        source_type=sow_source_type,
    )

    trends = (
        live_hog_trend,
        piglet_trend,
        corn_trend,
        pig_corn_ratio_trend,
        sow_trend,
    )
    has_basic_input = all(trend.observation_count > 0 for trend in trends) and (
        start_collection_date is not None
        and start_price is not None
        and start_source_url is not None
    )
    quality_status = (
        CalibrationQualityStatus.OUTCOME_INCOMPLETE
        if has_basic_input
        else CalibrationQualityStatus.INCOMPLETE
    )

    return CalibrationRow(
        cutoff=cutoff,
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=live_hog_trend,
        piglet_trend=piglet_trend,
        corn_trend=corn_trend,
        pig_corn_ratio_trend=pig_corn_ratio_trend,
        sow_source_type=sow_source_type,
        sow_trend=sow_trend,
        start_collection_date=start_collection_date,
        start_price=start_price,
        start_source_url=start_source_url,
        outcomes=(),
        quality_status=quality_status,
    )
