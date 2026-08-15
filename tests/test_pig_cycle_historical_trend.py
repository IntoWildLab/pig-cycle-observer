import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.pig_cycle.historical_trend import (
    calculate_moa_weekly_trend_as_of_system,
    calculate_sow_inventory_trend_as_of_system,
)
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.storage import PigCycleRevisionDataError, PigCycleStorage
from src.pig_cycle.trend import (
    MoaWeeklyMetric,
    TrendIntervalUnit,
    calculate_moa_weekly_trend,
)


@pytest.fixture
def storage(tmp_path: Path) -> PigCycleStorage:
    result = PigCycleStorage(tmp_path / "pig-cycle.sqlite3")
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
    save_status: str | None = "inserted",
    sets_current: int = 1,
    ingest_origin: str = "normal_ingest",
    piglet_price: float = 20.0,
    live_hog_price: float = 10.0,
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
            ) VALUES (?, ?, 'test week', ?, ?, ?, 3.2, 3.4, ?, ?, ?, ?, ?, ?, ?)
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
                save_status,
                sets_current,
                ingest_origin,
            ),
        )
        connection.commit()


def _insert_sow_revision(
    storage: PigCycleStorage,
    *,
    month: str,
    source_type: SowSourceType,
    inventory: float,
    observed_at: str,
    source_url: str,
    fingerprint: str,
    publish_date: str | None = None,
) -> None:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO sow_monthly_record_revisions (
                month, source_type, sow_inventory, mom_change, yoy_change,
                publish_date, source_url, payload_fingerprint, observed_at,
                save_status, sets_current, ingest_origin
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, 'inserted', 1, 'normal_ingest')
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


def _insert_current_moa(storage: PigCycleStorage, record: MoaWeeklyRecord) -> None:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_records (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'now', 'now')
            """,
            (
                record.collection_date.isoformat(),
                record.publish_date.isoformat(),
                record.period_label,
                record.piglet_price,
                record.live_hog_price,
                record.corn_price,
                record.soybean_meal_price,
                record.fattening_feed_price,
                record.derived_pig_corn_ratio,
                record.source_url,
            ),
        )
        connection.commit()


def test_moa_cutoff_before_and_exactly_at_baseline(storage: PigCycleStorage) -> None:
    observed_at = datetime(2026, 8, 15, 1, tzinfo=timezone.utc)
    _insert_moa_revision(
        storage,
        observed_at=observed_at.isoformat(),
        ingest_origin="baseline_import",
        save_status=None,
    )

    before = calculate_moa_weekly_trend_as_of_system(
        storage,
        observed_at - timedelta(microseconds=1),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )
    at_seed = calculate_moa_weekly_trend_as_of_system(
        storage,
        observed_at,
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )

    assert before.observation_count == 0
    assert before.latest_value is None
    assert at_seed.observation_count == 1
    assert at_seed.latest_value == 20.0


def test_moa_cutoffs_use_updates_and_ignore_non_current_evidence(
    storage: PigCycleStorage,
) -> None:
    _insert_moa_revision(storage, piglet_price=20.0)
    _insert_moa_revision(
        storage,
        source_url="https://example/weekly-evidence",
        fingerprint="weekly-evidence",
        observed_at="2026-07-07T01:00:00+00:00",
        save_status="conflict",
        sets_current=0,
        piglet_price=99.0,
    )
    _insert_moa_revision(
        storage,
        source_url="https://example/weekly-update",
        fingerprint="weekly-update",
        observed_at="2026-07-08T01:00:00+00:00",
        save_status="updated",
        piglet_price=22.0,
        publish_date="2027-01-01",
    )

    between = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 7, 7, 12, tzinfo=timezone.utc),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )
    after = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 7, 8, 1, tzinfo=timezone.utc),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )

    assert between.latest_value == 20.0
    assert after.latest_value == 22.0


@pytest.mark.parametrize(
    ("dates", "expected_intervals", "irregular"),
    [
        (("2026-07-02", "2026-07-09", "2026-07-16"), (7, 7), False),
        (("2026-07-02", "2026-07-16"), (14,), True),
    ],
    ids=["regular", "irregular"],
)
def test_moa_multiple_business_dates_preserve_interval_semantics(
    storage: PigCycleStorage,
    dates: tuple[str, ...],
    expected_intervals: tuple[int, ...],
    irregular: bool,
) -> None:
    for index, business_date in enumerate(dates):
        _insert_moa_revision(
            storage,
            collection_date=business_date,
            observed_at=f"2026-07-{20 + index:02d}T01:00:00+00:00",
            source_url=f"https://example/weekly-{index}",
            fingerprint=f"weekly-{index}",
            piglet_price=20.0 + index,
        )

    result = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )

    assert result.observation_keys == tuple(date.fromisoformat(value) for value in dates)
    assert result.interval_units == expected_intervals
    assert result.interval_unit is TrendIntervalUnit.DAYS
    assert result.has_irregular_intervals is irregular


def test_moa_uses_stored_derived_ratio_without_recalculation(
    storage: PigCycleStorage,
) -> None:
    _insert_moa_revision(
        storage,
        live_hog_price=10.0,
        corn_price=2.0,
        derived_ratio=9.25,
    )

    result = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        metric=MoaWeeklyMetric.DERIVED_PIG_CORN_RATIO,
    )

    assert result.latest_value == 9.25
    assert result.latest_value != 10.0 / 2.0


def test_sow_source_types_are_isolated_with_their_natural_intervals(
    storage: PigCycleStorage,
) -> None:
    rows = [
        ("2025-12", SowSourceType.NBS, 3961.0, "2026-01-20T01:00:00+00:00"),
        ("2026-03", SowSourceType.NBS, 3904.0, "2026-04-20T01:00:00+00:00"),
        ("2026-01", SowSourceType.MOA_REPORTED, 3950.0, "2026-02-20T01:00:00+00:00"),
        ("2026-02", SowSourceType.MOA_REPORTED, 3940.0, "2026-03-20T01:00:00+00:00"),
        ("2026-01", SowSourceType.MOA_ESTIMATE, 3955.0, "2026-02-21T01:00:00+00:00"),
        ("2026-02", SowSourceType.MOA_ESTIMATE, 3945.0, "2026-03-21T01:00:00+00:00"),
    ]
    for index, (month, source_type, inventory, observed_at) in enumerate(rows):
        _insert_sow_revision(
            storage,
            month=month,
            source_type=source_type,
            inventory=inventory,
            observed_at=observed_at,
            source_url=f"https://example/{source_type.value}/{month}",
            fingerprint=f"sow-{index}",
        )

    cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
    nbs = calculate_sow_inventory_trend_as_of_system(
        storage, cutoff, source_type=SowSourceType.NBS
    )
    reported = calculate_sow_inventory_trend_as_of_system(
        storage, cutoff, source_type=SowSourceType.MOA_REPORTED
    )
    estimate = calculate_sow_inventory_trend_as_of_system(
        storage, cutoff, source_type=SowSourceType.MOA_ESTIMATE
    )

    assert nbs.observation_keys == ("2025-12", "2026-03")
    assert nbs.interval_units == (3,)
    assert nbs.has_irregular_intervals is False
    assert reported.observation_keys == ("2026-01", "2026-02")
    assert reported.interval_units == (1,)
    assert reported.has_irregular_intervals is False
    assert estimate.observation_keys == ("2026-01", "2026-02")
    assert estimate.interval_units == (1,)
    assert estimate.has_irregular_intervals is False


def test_zero_and_one_observation_keep_existing_trend_semantics(
    storage: PigCycleStorage,
) -> None:
    empty = calculate_sow_inventory_trend_as_of_system(
        storage,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type=SowSourceType.NBS,
    )
    _insert_sow_revision(
        storage,
        month="2025-12",
        source_type=SowSourceType.NBS,
        inventory=3961.0,
        observed_at="2026-01-20T01:00:00+00:00",
        source_url="https://example/nbs/2025-12",
        fingerprint="nbs-2025-12",
    )
    single = calculate_sow_inventory_trend_as_of_system(
        storage,
        datetime(2026, 1, 21, tzinfo=timezone.utc),
        source_type=SowSourceType.NBS,
    )

    assert empty.observation_count == 0
    assert empty.latest_value is None
    assert empty.interval_unit is TrendIntervalUnit.MONTHS
    assert single.observation_count == 1
    assert single.latest_value == 3961.0
    assert single.latest_change is None
    assert single.has_irregular_intervals is None


def test_historical_trend_never_leaks_different_current_payload(
    storage: PigCycleStorage,
) -> None:
    _insert_moa_revision(storage, piglet_price=20.0)
    current = MoaWeeklyRecord(
        collection_date=date(2026, 7, 2),
        publish_date=date(2026, 7, 6),
        period_label="current only",
        piglet_price=99.0,
        live_hog_price=99.0,
        corn_price=2.5,
        soybean_meal_price=3.2,
        fattening_feed_price=3.4,
        derived_pig_corn_ratio=39.6,
        source_url="https://example/current-only",
    )
    _insert_current_moa(storage, current)

    result = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )

    assert result.latest_value == 20.0


def test_late_cutoff_matches_current_records_and_trend(storage: PigCycleStorage) -> None:
    records = [
        MoaWeeklyRecord(
            collection_date=date(2026, 7, 2),
            publish_date=date(2026, 7, 6),
            period_label="test week",
            piglet_price=20.0,
            live_hog_price=10.0,
            corn_price=2.5,
            soybean_meal_price=3.2,
            fattening_feed_price=3.4,
            derived_pig_corn_ratio=4.0,
            source_url="https://example/weekly-1",
        ),
        MoaWeeklyRecord(
            collection_date=date(2026, 7, 9),
            publish_date=date(2026, 7, 13),
            period_label="test week",
            piglet_price=21.0,
            live_hog_price=10.5,
            corn_price=2.5,
            soybean_meal_price=3.2,
            fattening_feed_price=3.4,
            derived_pig_corn_ratio=4.2,
            source_url="https://example/weekly-2",
        ),
    ]
    for index, record in enumerate(records):
        _insert_current_moa(storage, record)
        _insert_moa_revision(
            storage,
            collection_date=record.collection_date.isoformat(),
            publish_date=record.publish_date.isoformat(),
            observed_at=f"2026-07-{14 + index:02d}T01:00:00+00:00",
            source_url=record.source_url,
            fingerprint=f"weekly-{index}",
            piglet_price=record.piglet_price,
            live_hog_price=record.live_hog_price,
            corn_price=record.corn_price,
            derived_ratio=record.derived_pig_corn_ratio,
        )

    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)
    system_records = storage.get_moa_weekly_records_as_of_system(cutoff)
    current_records = storage.get_moa_weekly_history()

    assert system_records == current_records
    assert calculate_moa_weekly_trend(
        current_records, metric=MoaWeeklyMetric.PIGLET_PRICE
    ) == calculate_moa_weekly_trend_as_of_system(
        storage, cutoff, metric=MoaWeeklyMetric.PIGLET_PRICE
    )


def test_non_utc_cutoff_is_normalized_by_reader(storage: PigCycleStorage) -> None:
    _insert_moa_revision(storage)

    result = calculate_moa_weekly_trend_as_of_system(
        storage,
        datetime(2026, 7, 6, 9, tzinfo=timezone(timedelta(hours=8))),
        metric=MoaWeeklyMetric.PIGLET_PRICE,
    )

    assert result.observation_count == 1


def test_reader_integrity_errors_propagate_through_wrapper(
    storage: PigCycleStorage,
) -> None:
    _insert_moa_revision(
        storage,
        collection_date="2026-07-07",
        observed_at="2026-07-06T15:00:00+00:00",
    )

    with pytest.raises(PigCycleRevisionDataError) as error:
        calculate_moa_weekly_trend_as_of_system(
            storage,
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            metric=MoaWeeklyMetric.PIGLET_PRICE,
        )
    assert error.value.field == "collection_date"


def test_publish_date_is_not_an_extra_system_visibility_filter(
    storage: PigCycleStorage,
) -> None:
    _insert_moa_revision(
        storage,
        publish_date="2027-01-01",
        observed_at="2026-07-06T01:00:00+00:00",
    )
    _insert_sow_revision(
        storage,
        month="2026-06",
        source_type=SowSourceType.NBS,
        inventory=3780.0,
        publish_date="2027-01-01",
        observed_at="2026-07-16T01:00:00+00:00",
        source_url="https://example/nbs/2026-06",
        fingerprint="nbs-2026-06",
    )

    cutoff = datetime(2026, 8, 1, tzinfo=timezone.utc)
    moa = calculate_moa_weekly_trend_as_of_system(
        storage, cutoff, metric=MoaWeeklyMetric.PIGLET_PRICE
    )
    sow = calculate_sow_inventory_trend_as_of_system(
        storage, cutoff, source_type=SowSourceType.NBS
    )

    assert moa.observation_count == 1
    assert sow.observation_count == 1
