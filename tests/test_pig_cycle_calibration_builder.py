import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.pig_cycle.calibration_builder import build_system_calibration_input_row
from src.pig_cycle.calibration_models import (
    CalibrationQualityStatus,
    CalibrationRow,
    KnowledgeBasis,
)
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.storage import PigCycleRevisionDataError, PigCycleStorage


class _CountingStorage(PigCycleStorage):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.moa_reads = 0
        self.sow_reads = 0

    def get_moa_weekly_records_as_of_system(
        self, cutoff: datetime
    ) -> list[MoaWeeklyRecord]:
        self.moa_reads += 1
        return super().get_moa_weekly_records_as_of_system(cutoff)

    def get_sow_monthly_records_as_of_system(
        self, cutoff: datetime
    ) -> list[SowMonthlyRecord]:
        self.sow_reads += 1
        return super().get_sow_monthly_records_as_of_system(cutoff)


@pytest.fixture
def storage(tmp_path: Path) -> _CountingStorage:
    result = _CountingStorage(tmp_path / "pig-cycle.sqlite3")
    result.initialize_schema()
    return result


def _insert_moa_revision(
    storage: PigCycleStorage,
    *,
    collection_date: str = "2026-07-02",
    publish_date: str = "2026-07-06",
    observed_at: str = "2026-07-06T01:00:00+00:00",
    source_url: str = "https://example/weekly-a",
    fingerprint: str = "weekly-a",
    live_hog_price: float = 10.0,
    piglet_price: float = 20.0,
    corn_price: float = 2.5,
    derived_ratio: float = 4.0,
) -> None:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_record_revisions (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                payload_fingerprint, observed_at, save_status, sets_current,
                ingest_origin
            ) VALUES (?, ?, 'test week', ?, ?, ?, 3.2, 3.4, ?, ?, ?, ?,
                      'inserted', 1, 'normal_ingest')
            """,
            (
                collection_date,
                publish_date,
                piglet_price,
                live_hog_price,
                corn_price,
                derived_ratio,
                source_url,
                fingerprint,
                observed_at,
            ),
        )
        connection.commit()


def _insert_sow_revision(
    storage: PigCycleStorage,
    *,
    month: str = "2026-06",
    source_type: SowSourceType = SowSourceType.NBS,
    inventory: float = 3780.0,
    observed_at: str = "2026-07-16T01:00:00+00:00",
    source_url: str = "https://example/sow-a",
    fingerprint: str = "sow-a",
    publish_date: str | None = "2026-07-16",
) -> None:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO sow_monthly_record_revisions (
                month, source_type, sow_inventory, mom_change, yoy_change,
                publish_date, source_url, payload_fingerprint, observed_at,
                save_status, sets_current, ingest_origin
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?,
                      'inserted', 1, 'normal_ingest')
            """,
            (
                month,
                source_type.value,
                inventory,
                publish_date,
                source_url,
                fingerprint,
                observed_at,
            ),
        )
        connection.commit()


def _build(
    storage: PigCycleStorage,
    cutoff: datetime = datetime(2026, 8, 1, tzinfo=timezone.utc),
    source_type: SowSourceType = SowSourceType.NBS,
) -> CalibrationRow:
    return build_system_calibration_input_row(
        storage,
        cutoff,
        sow_source_type=source_type,
    )


def test_empty_historical_state_still_builds_incomplete_row(
    storage: _CountingStorage,
) -> None:
    row = _build(storage)

    assert row.knowledge_basis is KnowledgeBasis.SYSTEM_OBSERVED
    assert all(
        trend.observation_count == 0
        for trend in (
            row.live_hog_trend,
            row.piglet_trend,
            row.corn_trend,
            row.pig_corn_ratio_trend,
            row.sow_trend,
        )
    )
    assert (row.start_collection_date, row.start_price, row.start_source_url) == (
        None,
        None,
        None,
    )
    assert row.outcomes == ()
    assert row.quality_status is CalibrationQualityStatus.INCOMPLETE
    assert (storage.moa_reads, storage.sow_reads) == (1, 1)


def test_one_moa_and_sow_observation_are_basic_input_presence(
    storage: _CountingStorage,
) -> None:
    _insert_moa_revision(
        storage,
        publish_date="2027-01-01",
        live_hog_price=10.5,
        piglet_price=21.5,
        corn_price=2.25,
        derived_ratio=4.75,
    )
    _insert_sow_revision(storage, publish_date="2027-01-01")

    row = _build(storage)

    assert row.live_hog_trend.latest_value == 10.5
    assert row.piglet_trend.latest_value == 21.5
    assert row.corn_trend.latest_value == 2.25
    assert row.pig_corn_ratio_trend.latest_value == 4.75
    assert row.sow_trend.latest_value == 3780.0
    assert all(
        trend.observation_count == 1
        for trend in (
            row.live_hog_trend,
            row.piglet_trend,
            row.corn_trend,
            row.pig_corn_ratio_trend,
            row.sow_trend,
        )
    )
    assert row.quality_status is CalibrationQualityStatus.OUTCOME_INCOMPLETE
    assert row.outcomes == ()
    assert (storage.moa_reads, storage.sow_reads) == (1, 1)


def test_start_provenance_uses_latest_system_visible_moa_record(
    storage: _CountingStorage,
) -> None:
    _insert_moa_revision(storage)
    _insert_moa_revision(
        storage,
        collection_date="2026-07-09",
        observed_at="2026-07-13T01:00:00+00:00",
        source_url="https://example/weekly-latest",
        fingerprint="weekly-latest",
        live_hog_price=11.25,
    )
    _insert_sow_revision(storage)

    row = _build(storage)

    assert row.start_collection_date == date(2026, 7, 9)
    assert row.start_price == 11.25
    assert row.start_source_url == "https://example/weekly-latest"
    assert row.live_hog_trend.observation_count == 2


def test_builder_does_not_leak_current_table_payload(storage: _CountingStorage) -> None:
    _insert_moa_revision(storage, live_hog_price=10.0)
    _insert_sow_revision(storage)
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_records (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                created_at, updated_at
            ) VALUES ('2026-07-02', '2026-07-06', 'current', 99, 99, 2.5,
                      3.2, 3.4, 39.6, 'https://example/current', 'now', 'now')
            """
        )
        connection.commit()

    row = _build(storage)

    assert row.live_hog_trend.latest_value == 10.0
    assert row.start_price == 10.0
    assert row.start_source_url == "https://example/weekly-a"


def test_sow_source_is_strictly_isolated(storage: _CountingStorage) -> None:
    _insert_moa_revision(storage)
    _insert_sow_revision(storage, source_type=SowSourceType.NBS, inventory=3780.0)
    _insert_sow_revision(
        storage,
        source_type=SowSourceType.MOA_REPORTED,
        inventory=3999.0,
        source_url="https://example/sow-reported",
        fingerprint="sow-reported",
    )

    nbs = _build(storage, source_type=SowSourceType.NBS)
    reported = _build(storage, source_type=SowSourceType.MOA_REPORTED)
    estimate = _build(storage, source_type=SowSourceType.MOA_ESTIMATE)

    assert nbs.sow_trend.latest_value == 3780.0
    assert reported.sow_trend.latest_value == 3999.0
    assert estimate.sow_trend.observation_count == 0
    assert estimate.quality_status is CalibrationQualityStatus.INCOMPLETE


def test_non_utc_cutoff_is_normalized_by_reader(storage: _CountingStorage) -> None:
    _insert_moa_revision(storage)
    _insert_sow_revision(storage)

    row = _build(
        storage,
        datetime(2026, 8, 1, 8, tzinfo=timezone(timedelta(hours=8))),
    )

    assert row.quality_status is CalibrationQualityStatus.OUTCOME_INCOMPLETE


def test_naive_cutoff_error_propagates(storage: _CountingStorage) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _build(storage, datetime(2026, 8, 1))


@pytest.mark.parametrize(
    ("collection_date", "observed_at", "field"),
    [
        ("2026-07-07", "2026-07-06T15:00:00+00:00", "collection_date"),
        ("not-a-date", "2026-07-06T01:00:00+00:00", "collection_date"),
    ],
    ids=["future-business", "malformed-business-date"],
)
def test_revision_integrity_errors_propagate(
    storage: _CountingStorage,
    collection_date: str,
    observed_at: str,
    field: str,
) -> None:
    _insert_moa_revision(
        storage,
        collection_date=collection_date,
        observed_at=observed_at,
    )

    with pytest.raises(PigCycleRevisionDataError) as error:
        _build(storage)
    assert error.value.field == field
