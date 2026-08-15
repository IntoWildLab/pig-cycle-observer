import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    ForwardOutcome,
    ForwardOutcomeStatus,
    KnowledgeBasis,
)
from src.pig_cycle.forward_outcome_builder import build_system_forward_outcome
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import SowSourceType
from src.pig_cycle.storage import PigCycleRevisionDataError, PigCycleStorage
from src.pig_cycle.trend import NumericTrendFeatures, TrendIntervalUnit


class _CountingStorage(PigCycleStorage):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.moa_reads = 0

    def get_moa_weekly_records_as_of_system(
        self, cutoff: datetime
    ) -> list[MoaWeeklyRecord]:
        self.moa_reads += 1
        return super().get_moa_weekly_records_as_of_system(cutoff)


@pytest.fixture
def storage(tmp_path: Path) -> _CountingStorage:
    result = _CountingStorage(tmp_path / "pig-cycle.sqlite3")
    result.initialize_schema()
    return result


def _trend() -> NumericTrendFeatures:
    return NumericTrendFeatures(
        observation_count=1,
        latest_value=14.2,
        previous_value=None,
        latest_change=None,
        latest_change_pct=None,
        window_start_value=14.2,
        cumulative_change=None,
        cumulative_change_pct=None,
        consecutive_up_count=0,
        consecutive_down_count=0,
        latest_streak_direction=None,
        observation_keys=(date(2026, 7, 1),),
        interval_units=(),
        interval_unit=TrendIntervalUnit.DAYS,
        has_irregular_intervals=None,
    )


def _row(
    *,
    cutoff: datetime = datetime(2026, 7, 1, tzinfo=timezone.utc),
    start_price: float | None = 14.2,
) -> CalibrationRow:
    trend = _trend()
    has_start = start_price is not None
    return CalibrationRow(
        cutoff=cutoff,
        knowledge_basis=KnowledgeBasis.SYSTEM_OBSERVED,
        live_hog_trend=trend,
        piglet_trend=trend,
        corn_trend=trend,
        pig_corn_ratio_trend=trend,
        sow_source_type=SowSourceType.NBS,
        sow_trend=trend,
        start_collection_date=date(2026, 7, 1) if has_start else None,
        start_price=start_price,
        start_source_url="https://example/start" if has_start else None,
        outcomes=(),
        quality_status=CalibrationQualityStatus.OUTCOME_INCOMPLETE,
    )


def _insert_revision(
    storage: PigCycleStorage,
    *,
    collection_date: str,
    live_hog_price: float,
    observed_at: str = "2026-07-17T01:00:00+00:00",
    publish_date: str = "2026-07-17",
    source_url: str | None = None,
) -> None:
    source_url = source_url or f"https://example/{collection_date}"
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_record_revisions (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                payload_fingerprint, observed_at, save_status, sets_current,
                ingest_origin
            ) VALUES (?, ?, 'test week', 20, ?, 2.5, 3.2, 3.4, 4, ?, ?, ?,
                      'inserted', 1, 'normal_ingest')
            """,
            (
                collection_date,
                publish_date,
                live_hog_price,
                source_url,
                f"fingerprint-{collection_date}",
                observed_at,
            ),
        )
        connection.commit()


def _build(
    storage: PigCycleStorage,
    row: CalibrationRow | None = None,
    *,
    horizon_weeks: int = 2,
    evaluation_cutoff: datetime = datetime(2026, 7, 18, 16, tzinfo=timezone.utc),
    max_offset_days: int = 2,
) -> ForwardOutcome:
    return build_system_forward_outcome(
        storage,
        row or _row(),
        horizon_weeks=horizon_weeks,
        evaluation_cutoff=evaluation_cutoff,
        max_offset_days=max_offset_days,
    )


def test_exact_target_is_available_with_signed_return(storage: _CountingStorage) -> None:
    _insert_revision(storage, collection_date="2026-07-15", live_hog_price=15.1)

    outcome = _build(storage)

    assert outcome.status is ForwardOutcomeStatus.AVAILABLE
    assert outcome.target_date == date(2026, 7, 15)
    assert outcome.actual_collection_date == date(2026, 7, 15)
    assert outcome.offset_days == 0
    assert outcome.price == 15.1
    assert outcome.return_from_start == pytest.approx(15.1 / 14.2 - 1)
    assert storage.moa_reads == 1


@pytest.mark.parametrize(
    ("collection_date", "expected_offset"),
    [("2026-07-14", -1), ("2026-07-16", 1)],
    ids=["before", "after"],
)
def test_nearest_observation_preserves_signed_offset(
    storage: _CountingStorage,
    collection_date: str,
    expected_offset: int,
) -> None:
    _insert_revision(storage, collection_date=collection_date, live_hog_price=15.0)

    outcome = _build(storage)

    assert outcome.actual_collection_date == date.fromisoformat(collection_date)
    assert outcome.offset_days == expected_offset


def test_equal_distance_prefers_earlier_collection_date(
    storage: _CountingStorage,
) -> None:
    _insert_revision(storage, collection_date="2026-07-14", live_hog_price=14.9)
    _insert_revision(storage, collection_date="2026-07-16", live_hog_price=15.2)

    outcome = _build(storage)

    assert outcome.actual_collection_date == date(2026, 7, 14)
    assert outcome.offset_days == -1


def test_mature_window_without_candidate_is_missing(storage: _CountingStorage) -> None:
    _insert_revision(storage, collection_date="2026-07-12", live_hog_price=15.0)
    _insert_revision(
        storage,
        collection_date="2026-07-18",
        live_hog_price=15.0,
        observed_at="2026-07-18T01:00:00+00:00",
    )

    outcome = _build(storage)

    assert outcome.status is ForwardOutcomeStatus.MISSING
    assert (
        outcome.actual_collection_date,
        outcome.price,
        outcome.return_from_start,
        outcome.offset_days,
        outcome.source_url,
    ) == (None, None, None, None, None)
    assert storage.moa_reads == 1


def test_window_end_day_is_not_mature_and_does_not_read_storage(
    storage: _CountingStorage,
) -> None:
    outcome = _build(
        storage,
        evaluation_cutoff=datetime(2026, 7, 17, 8, tzinfo=timezone.utc),
    )

    assert outcome.status is ForwardOutcomeStatus.NOT_MATURED
    assert outcome.target_date == date(2026, 7, 15)
    assert (
        outcome.actual_collection_date,
        outcome.price,
        outcome.return_from_start,
        outcome.offset_days,
        outcome.source_url,
    ) == (None, None, None, None, None)
    assert storage.moa_reads == 0


def test_missing_start_provenance_and_non_positive_price_are_input_errors(
    storage: _CountingStorage,
) -> None:
    with pytest.raises(ValueError, match="complete start provenance"):
        _build(storage, _row(start_price=None))
    with pytest.raises(ValueError, match="greater than zero"):
        _build(storage, replace(_row(), start_price=0.0))
    assert storage.moa_reads == 0


@pytest.mark.parametrize("horizon_weeks", [0, -1])
def test_non_positive_horizon_is_rejected(
    storage: _CountingStorage,
    horizon_weeks: int,
) -> None:
    with pytest.raises(ValueError, match="horizon_weeks"):
        _build(storage, horizon_weeks=horizon_weeks)


def test_boolean_horizon_is_rejected(storage: _CountingStorage) -> None:
    with pytest.raises(TypeError, match="horizon_weeks"):
        _build(storage, horizon_weeks=True)  # type: ignore[arg-type]


def test_negative_and_boolean_max_offset_are_rejected(
    storage: _CountingStorage,
) -> None:
    with pytest.raises(ValueError, match="max_offset_days"):
        _build(storage, max_offset_days=-1)
    with pytest.raises(TypeError, match="max_offset_days"):
        _build(storage, max_offset_days=True)  # type: ignore[arg-type]


def test_window_cannot_touch_calibration_cutoff(storage: _CountingStorage) -> None:
    with pytest.raises(ValueError, match="strictly after"):
        _build(storage, horizon_weeks=1, max_offset_days=7)
    assert storage.moa_reads == 0


def test_evaluation_cutoff_must_be_aware_and_not_before_row_cutoff(
    storage: _CountingStorage,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _build(storage, evaluation_cutoff=datetime(2026, 7, 18))
    with pytest.raises(ValueError, match="not be earlier"):
        _build(
            storage,
            evaluation_cutoff=datetime(2026, 6, 30, tzinfo=timezone.utc),
        )


def test_non_utc_cutoffs_use_china_business_dates_and_same_instants(
    storage: _CountingStorage,
) -> None:
    row = _row(
        cutoff=datetime(2026, 7, 1, 23, 30, tzinfo=timezone(timedelta(hours=-4)))
    )
    _insert_revision(
        storage,
        collection_date="2026-07-09",
        live_hog_price=15.0,
        observed_at="2026-07-09T16:00:00+00:00",
    )

    outcome = _build(
        storage,
        row,
        horizon_weeks=1,
        max_offset_days=0,
        evaluation_cutoff=datetime(
            2026, 7, 10, 12, tzinfo=timezone(timedelta(hours=-4))
        ),
    )

    assert outcome.target_date == date(2026, 7, 9)
    assert outcome.status is ForwardOutcomeStatus.AVAILABLE


def test_future_publish_date_is_not_an_extra_visibility_filter(
    storage: _CountingStorage,
) -> None:
    _insert_revision(
        storage,
        collection_date="2026-07-15",
        live_hog_price=15.1,
        publish_date="2027-01-01",
    )

    assert _build(storage).status is ForwardOutcomeStatus.AVAILABLE


def test_current_table_does_not_leak_into_outcome(storage: _CountingStorage) -> None:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_records (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                created_at, updated_at
            ) VALUES ('2026-07-15', '2026-07-17', 'current', 20, 99, 2.5,
                      3.2, 3.4, 39.6, 'https://example/current', 'now', 'now')
            """
        )
        connection.commit()

    assert _build(storage).status is ForwardOutcomeStatus.MISSING


def test_return_uses_frozen_row_start_price(storage: _CountingStorage) -> None:
    _insert_revision(storage, collection_date="2026-07-01", live_hog_price=99.0)
    _insert_revision(storage, collection_date="2026-07-15", live_hog_price=15.1)

    outcome = _build(storage)

    assert outcome.return_from_start == pytest.approx(15.1 / 14.2 - 1)
    assert storage.moa_reads == 1


@pytest.mark.parametrize(
    ("collection_date", "observed_at"),
    [
        ("2026-07-18", "2026-07-17T15:00:00+00:00"),
        ("not-a-date", "2026-07-17T01:00:00+00:00"),
    ],
    ids=["future-business", "malformed-business-date"],
)
def test_reader_errors_propagate_from_mature_outcome(
    storage: _CountingStorage,
    collection_date: str,
    observed_at: str,
) -> None:
    _insert_revision(
        storage,
        collection_date=collection_date,
        live_hog_price=15.0,
        observed_at=observed_at,
    )

    with pytest.raises(PigCycleRevisionDataError):
        _build(storage)
