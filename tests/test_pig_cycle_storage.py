import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.pig_cycle.storage as storage_module
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.storage import (
    MoaWeeklySaveStatus,
    PigCycleStorage,
    SowMonthlySaveStatus,
)


TABLES = {"moa_weekly_records", "sow_monthly_records", "processed_sources"}


def _weekly_record(
    *,
    collection_date: date = date(2026, 7, 30),
    publish_date: date = date(2026, 8, 4),
    source_url: str = "https://xmsyj.moa.gov.cn/jcyj/weekly-a.htm",
    soybean_meal_price: float | None = 3.23,
    fattening_feed_price: float | None = 3.36,
) -> MoaWeeklyRecord:
    return MoaWeeklyRecord(
        collection_date=collection_date,
        publish_date=publish_date,
        period_label="7月第5周",
        piglet_price=23.0,
        live_hog_price=14.0,
        corn_price=2.5,
        soybean_meal_price=soybean_meal_price,
        fattening_feed_price=fattening_feed_price,
        derived_pig_corn_ratio=5.6,
        source_url=source_url,
    )


def _sow_record(
    *,
    month: str = "2026-06",
    source_type: SowSourceType = SowSourceType.MOA_REPORTED,
    publish_date: date | None = date(2026, 7, 10),
    source_url: str = "https://www.moa.gov.cn/sow-a.htm",
    mom_change: float | None = -0.1,
    yoy_change: float | None = -2.3,
) -> SowMonthlyRecord:
    return SowMonthlyRecord(
        month=month,
        sow_inventory=3780.0,
        mom_change=mom_change,
        yoy_change=yoy_change,
        publish_date=publish_date,
        source_type=source_type,
        source_url=source_url,
    )


def _fetch_one(db_path: Path, query: str, parameters: tuple[object, ...] = ()) -> sqlite3.Row:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(query, parameters).fetchone()
    assert row is not None
    return row


def _count(db_path: Path, table: str) -> int:
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def _timestamp_state(db_path: Path) -> tuple[list[tuple[object, ...]], ...]:
    with closing(sqlite3.connect(db_path)) as connection:
        weekly = connection.execute(
            "SELECT collection_date, created_at, updated_at FROM moa_weekly_records ORDER BY collection_date"
        ).fetchall()
        sow = connection.execute(
            "SELECT month, source_type, created_at, updated_at FROM sow_monthly_records ORDER BY month, source_type"
        ).fetchall()
        processed = connection.execute(
            """
            SELECT record_kind, source_url, processed_at
            FROM processed_sources
            ORDER BY record_kind, source_url
            """
        ).fetchall()
    return (weekly, sow, processed)


def _table_names(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _primary_key(db_path: Path, table: str) -> list[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in sorted(rows, key=lambda row: int(row[5])) if row[5]]


def _index_columns(db_path: Path, table: str) -> set[tuple[str, ...]]:
    with closing(sqlite3.connect(db_path)) as connection:
        indexes = connection.execute(f"PRAGMA index_list({table})").fetchall()
        return {
            tuple(
                str(row[2])
                for row in connection.execute(f"PRAGMA index_info({index[1]})").fetchall()
            )
            for index in indexes
        }


@pytest.fixture
def initialized_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "pig_cycle.sqlite3"
    PigCycleStorage(db_path).initialize_schema()
    return db_path


def test_initialize_schema_creates_three_tables(initialized_db: Path) -> None:
    assert _table_names(initialized_db) == TABLES


def test_business_tables_have_expected_primary_keys(initialized_db: Path) -> None:
    assert _primary_key(initialized_db, "moa_weekly_records") == ["collection_date"]
    assert _primary_key(initialized_db, "sow_monthly_records") == ["month", "source_type"]


def test_processed_sources_has_record_kind_url_primary_key(initialized_db: Path) -> None:
    assert _primary_key(initialized_db, "processed_sources") == ["record_kind", "source_url"]


def test_required_indexes_exist(initialized_db: Path) -> None:
    assert ("source_url",) in _index_columns(initialized_db, "moa_weekly_records")
    assert ("source_url",) in _index_columns(initialized_db, "sow_monthly_records")
    assert ("record_kind",) in _index_columns(initialized_db, "processed_sources")
    assert ("record_kind", "business_key") in _index_columns(initialized_db, "processed_sources")


@pytest.mark.parametrize("source_type", ["nbs", "moa_reported", "moa_estimate"])
def test_sow_source_type_check_accepts_supported_values(initialized_db: Path, source_type: str) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            INSERT INTO sow_monthly_records (
                month, source_type, sow_inventory, source_url, created_at, updated_at
            ) VALUES (?, ?, 3780, ?, ?, ?)
            """,
            ("2026-06", source_type, f"https://example/{source_type}", "now", "now"),
        )


def test_sow_source_type_check_rejects_unknown_value(initialized_db: Path) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO sow_monthly_records (
                    month, source_type, sow_inventory, source_url, created_at, updated_at
                ) VALUES ('2026-06', 'unknown', 3780, 'https://example/unknown', 'now', 'now')
                """
            )


@pytest.mark.parametrize("record_kind", ["moa_weekly", "sow_monthly"])
def test_processed_record_kind_check_accepts_supported_values(initialized_db: Path, record_kind: str) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            INSERT INTO processed_sources (
                record_kind, source_url, business_key, processed_at
            ) VALUES (?, ?, '2026-06', 'now')
            """,
            (record_kind, f"https://example/{record_kind}"),
        )


def test_processed_checks_reject_unknown_values(initialized_db: Path) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO processed_sources (
                    record_kind, source_url, business_key, processed_at
                ) VALUES ('unknown', 'https://example/kind', '2026-06', 'now')
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO processed_sources (
                    record_kind, source_url, business_key, source_type, processed_at
                ) VALUES (
                    'sow_monthly', 'https://example/source', '2026-06', 'unknown', 'now'
                )
                """
            )


def test_schema_initialization_rolls_back_all_ddl_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "pig_cycle.sqlite3"
    monkeypatch.setattr(
        storage_module,
        "_SCHEMA_STATEMENTS",
        (storage_module._SCHEMA_STATEMENTS[0], "CREATE TABLE broken ("),
    )

    with pytest.raises(sqlite3.OperationalError):
        PigCycleStorage(db_path).initialize_schema()

    assert _table_names(db_path) == set()


def test_processed_sources_composite_primary_key_behavior(initialized_db: Path) -> None:
    source_url = "https://example/same-source"
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            INSERT INTO processed_sources (
                record_kind, source_url, business_key, processed_at
            ) VALUES ('moa_weekly', ?, '2026-07-30', 'now')
            """,
            (source_url,),
        )
        connection.execute(
            """
            INSERT INTO processed_sources (
                record_kind, source_url, business_key, processed_at
            ) VALUES ('sow_monthly', ?, '2026-07', 'now')
            """,
            (source_url,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO processed_sources (
                    record_kind, source_url, business_key, processed_at
                ) VALUES ('moa_weekly', ?, '2026-07-30', 'now')
                """,
                (source_url,),
            )


def test_initialize_schema_is_idempotent_and_preserves_data(tmp_path: Path) -> None:
    db_path = tmp_path / "pig_cycle.sqlite3"
    storage = PigCycleStorage(db_path)

    storage.initialize_schema()
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO moa_weekly_records (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, derived_pig_corn_ratio,
                source_url, created_at, updated_at
            ) VALUES (
                '2026-07-30', '2026-08-04', '7月第5周', 23.0,
                14.0, 2.5, 5.6, 'https://example/weekly', 'created', 'updated'
            )
            """
        )
        connection.commit()

    storage.initialize_schema()

    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT collection_date, source_url
            FROM moa_weekly_records
            """
        ).fetchone()
    assert row == ("2026-07-30", "https://example/weekly")


def test_save_moa_weekly_inserts_record_and_processed_source(initialized_db: Path) -> None:
    record = _weekly_record()
    storage = PigCycleStorage(initialized_db)

    assert storage.save_moa_weekly(record) is MoaWeeklySaveStatus.INSERTED

    stored = _fetch_one(
        initialized_db,
        "SELECT * FROM moa_weekly_records WHERE collection_date = ?",
        (record.collection_date.isoformat(),),
    )
    processed = _fetch_one(
        initialized_db,
        "SELECT * FROM processed_sources WHERE record_kind = 'moa_weekly' AND source_url = ?",
        (record.source_url,),
    )
    assert stored["publish_date"] == record.publish_date.isoformat()
    assert stored["source_url"] == record.source_url
    assert stored["created_at"] == stored["updated_at"]
    assert processed["business_key"] == record.collection_date.isoformat()
    assert processed["source_type"] is None
    assert processed["publish_date"] == record.publish_date.isoformat()
    assert processed["processed_at"] == stored["created_at"]


def test_save_moa_weekly_identical_repeat_is_idempotent(initialized_db: Path) -> None:
    record = _weekly_record()
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(record)
    before = _fetch_one(initialized_db, "SELECT created_at, updated_at FROM moa_weekly_records")
    processed_before = _fetch_one(initialized_db, "SELECT processed_at FROM processed_sources")

    assert storage.save_moa_weekly(record) is MoaWeeklySaveStatus.UNCHANGED

    after = _fetch_one(initialized_db, "SELECT created_at, updated_at FROM moa_weekly_records")
    processed_after = _fetch_one(initialized_db, "SELECT processed_at FROM processed_sources")
    assert tuple(after) == tuple(before)
    assert tuple(processed_after) == tuple(processed_before)
    assert _count(initialized_db, "processed_sources") == 1


def test_save_moa_weekly_same_content_new_url_only_remembers_source(initialized_db: Path) -> None:
    first = _weekly_record()
    second = replace(first, source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-b.htm")
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)
    before = _fetch_one(initialized_db, "SELECT source_url, updated_at FROM moa_weekly_records")

    assert storage.save_moa_weekly(second) is MoaWeeklySaveStatus.UNCHANGED

    after = _fetch_one(initialized_db, "SELECT source_url, updated_at FROM moa_weekly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_moa_weekly_newer_publication_updates_current_record(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter(("2026-08-04T01:00:00+00:00", "2026-08-05T01:00:00+00:00"))
    monkeypatch.setattr(storage_module, "_utc_now", lambda: next(times))
    first = _weekly_record()
    corrected = replace(
        first,
        publish_date=date(2026, 8, 5),
        piglet_price=24.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-correction.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)

    assert storage.save_moa_weekly(corrected) is MoaWeeklySaveStatus.UPDATED

    stored = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_records")
    assert stored["publish_date"] == "2026-08-05"
    assert stored["piglet_price"] == 24.0
    assert stored["source_url"] == corrected.source_url
    assert stored["created_at"] == "2026-08-04T01:00:00+00:00"
    assert stored["updated_at"] == "2026-08-05T01:00:00+00:00"
    assert _count(initialized_db, "processed_sources") == 2


def test_save_moa_weekly_older_publication_is_ignored_but_remembered(initialized_db: Path) -> None:
    current = _weekly_record()
    older = replace(
        current,
        publish_date=date(2026, 8, 3),
        piglet_price=20.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-older.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(current)
    before = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_records")

    assert storage.save_moa_weekly(older) is MoaWeeklySaveStatus.OLDER_IGNORED

    after = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_moa_weekly_same_publication_conflict_is_remembered(initialized_db: Path) -> None:
    current = _weekly_record()
    conflicting = replace(
        current,
        live_hog_price=15.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-conflict.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(current)
    before = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_records")

    assert storage.save_moa_weekly(conflicting) is MoaWeeklySaveStatus.CONFLICT

    after = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_moa_weekly_rejects_source_remapped_to_another_date(initialized_db: Path) -> None:
    first = _weekly_record()
    remapped = replace(first, collection_date=date(2026, 8, 6))
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)

    with pytest.raises(ValueError, match="different collection_date"):
        storage.save_moa_weekly(remapped)

    assert _count(initialized_db, "moa_weekly_records") == 1
    assert _count(initialized_db, "processed_sources") == 1
    processed = _fetch_one(initialized_db, "SELECT business_key FROM processed_sources")
    assert processed["business_key"] == first.collection_date.isoformat()


def test_save_moa_weekly_preserves_null_optional_prices(initialized_db: Path) -> None:
    record = _weekly_record(soybean_meal_price=None, fattening_feed_price=None)

    assert PigCycleStorage(initialized_db).save_moa_weekly(record) is MoaWeeklySaveStatus.INSERTED

    stored = _fetch_one(
        initialized_db,
        "SELECT soybean_meal_price, fattening_feed_price FROM moa_weekly_records",
    )
    assert stored["soybean_meal_price"] is None
    assert stored["fattening_feed_price"] is None


def test_save_moa_weekly_rolls_back_processed_source_when_business_insert_fails(
    initialized_db: Path,
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_moa_weekly_insert
            BEFORE INSERT ON moa_weekly_records
            BEGIN
                SELECT RAISE(ABORT, 'forced test failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced test failure"):
        PigCycleStorage(initialized_db).save_moa_weekly(_weekly_record())

    assert _count(initialized_db, "moa_weekly_records") == 0
    assert _count(initialized_db, "processed_sources") == 0


def test_save_sow_monthly_inserts_record_and_processed_source(initialized_db: Path) -> None:
    record = _sow_record()

    assert PigCycleStorage(initialized_db).save_sow_monthly(record) is SowMonthlySaveStatus.INSERTED

    stored = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    processed = _fetch_one(initialized_db, "SELECT * FROM processed_sources")
    assert stored["month"] == record.month
    assert stored["source_type"] == record.source_type.value
    assert stored["sow_inventory"] == record.sow_inventory
    assert stored["created_at"] == stored["updated_at"]
    assert processed["record_kind"] == "sow_monthly"
    assert processed["business_key"] == record.month
    assert processed["source_type"] == record.source_type.value
    assert processed["publish_date"] == record.publish_date.isoformat()
    assert processed["processed_at"] == stored["created_at"]


def test_save_sow_monthly_keeps_different_source_types_for_same_month(initialized_db: Path) -> None:
    reported = _sow_record()
    nbs = replace(
        reported,
        source_type=SowSourceType.NBS,
        source_url="https://www.stats.gov.cn/sow-nbs.htm",
    )
    storage = PigCycleStorage(initialized_db)

    assert storage.save_sow_monthly(reported) is SowMonthlySaveStatus.INSERTED
    assert storage.save_sow_monthly(nbs) is SowMonthlySaveStatus.INSERTED
    assert _count(initialized_db, "sow_monthly_records") == 2
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_identical_repeat_is_idempotent(initialized_db: Path) -> None:
    record = _sow_record()
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(record)
    before = _fetch_one(initialized_db, "SELECT created_at, updated_at FROM sow_monthly_records")
    processed_before = _fetch_one(initialized_db, "SELECT processed_at FROM processed_sources")

    assert storage.save_sow_monthly(record) is SowMonthlySaveStatus.UNCHANGED

    after = _fetch_one(initialized_db, "SELECT created_at, updated_at FROM sow_monthly_records")
    processed_after = _fetch_one(initialized_db, "SELECT processed_at FROM processed_sources")
    assert tuple(after) == tuple(before)
    assert tuple(processed_after) == tuple(processed_before)
    assert _count(initialized_db, "processed_sources") == 1


def test_save_sow_monthly_same_content_new_url_only_remembers_source(initialized_db: Path) -> None:
    first = _sow_record()
    second = replace(first, source_url="https://www.moa.gov.cn/sow-b.htm")
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)
    before = _fetch_one(initialized_db, "SELECT source_url, updated_at FROM sow_monthly_records")

    assert storage.save_sow_monthly(second) is SowMonthlySaveStatus.UNCHANGED

    after = _fetch_one(initialized_db, "SELECT source_url, updated_at FROM sow_monthly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_newer_publication_updates_current_record(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter(("2026-07-10T01:00:00+00:00", "2026-07-11T01:00:00+00:00"))
    monkeypatch.setattr(storage_module, "_utc_now", lambda: next(times))
    first = _sow_record()
    corrected = replace(
        first,
        sow_inventory=3790.0,
        publish_date=date(2026, 7, 11),
        source_url="https://www.moa.gov.cn/sow-correction.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)

    assert storage.save_sow_monthly(corrected) is SowMonthlySaveStatus.UPDATED

    stored = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    assert stored["sow_inventory"] == 3790.0
    assert stored["publish_date"] == "2026-07-11"
    assert stored["source_url"] == corrected.source_url
    assert stored["created_at"] == "2026-07-10T01:00:00+00:00"
    assert stored["updated_at"] == "2026-07-11T01:00:00+00:00"
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_older_publication_is_ignored_but_remembered(initialized_db: Path) -> None:
    current = _sow_record()
    older = replace(
        current,
        sow_inventory=3770.0,
        publish_date=date(2026, 7, 9),
        source_url="https://www.moa.gov.cn/sow-older.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(current)
    before = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")

    assert storage.save_sow_monthly(older) is SowMonthlySaveStatus.OLDER_IGNORED

    after = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_same_publication_conflict_is_remembered(initialized_db: Path) -> None:
    current = _sow_record()
    conflicting = replace(
        current,
        sow_inventory=3790.0,
        source_url="https://www.moa.gov.cn/sow-conflict.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(current)
    before = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")

    assert storage.save_sow_monthly(conflicting) is SowMonthlySaveStatus.CONFLICT

    after = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_without_dates_same_content_is_unchanged(initialized_db: Path) -> None:
    first = _sow_record(publish_date=None)
    second = replace(first, source_url="https://www.moa.gov.cn/sow-undated-b.htm")
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)

    assert storage.save_sow_monthly(second) is SowMonthlySaveStatus.UNCHANGED
    assert _count(initialized_db, "processed_sources") == 2


def test_save_sow_monthly_without_dates_changed_content_has_unknown_order(initialized_db: Path) -> None:
    first = _sow_record(publish_date=None)
    changed = replace(
        first,
        sow_inventory=3790.0,
        source_url="https://www.moa.gov.cn/sow-undated-changed.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)
    before = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")

    assert storage.save_sow_monthly(changed) is SowMonthlySaveStatus.ORDER_UNKNOWN

    after = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


@pytest.mark.parametrize("current_date,new_date", [(None, date(2026, 7, 10)), (date(2026, 7, 10), None)])
def test_save_sow_monthly_one_missing_date_changed_content_has_unknown_order(
    initialized_db: Path, current_date: date | None, new_date: date | None
) -> None:
    first = _sow_record(publish_date=current_date)
    changed = replace(
        first,
        sow_inventory=3790.0,
        publish_date=new_date,
        source_url="https://www.moa.gov.cn/sow-mixed-date.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)
    before = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")

    assert storage.save_sow_monthly(changed) is SowMonthlySaveStatus.ORDER_UNKNOWN

    after = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_records")
    assert tuple(after) == tuple(before)


@pytest.mark.parametrize("current_date,new_date", [(None, date(2026, 7, 10)), (date(2026, 7, 10), None)])
def test_save_sow_monthly_one_missing_date_same_content_does_not_fill_publish_date(
    initialized_db: Path, current_date: date | None, new_date: date | None
) -> None:
    first = _sow_record(publish_date=current_date)
    same = replace(
        first,
        publish_date=new_date,
        source_url="https://www.moa.gov.cn/sow-mixed-same.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)
    before = _fetch_one(initialized_db, "SELECT publish_date, source_url, updated_at FROM sow_monthly_records")

    assert storage.save_sow_monthly(same) is SowMonthlySaveStatus.UNCHANGED

    after = _fetch_one(initialized_db, "SELECT publish_date, source_url, updated_at FROM sow_monthly_records")
    assert tuple(after) == tuple(before)
    assert _count(initialized_db, "processed_sources") == 2


@pytest.mark.parametrize(
    "remapped",
    [
        _sow_record(month="2026-07"),
        _sow_record(source_type=SowSourceType.NBS),
    ],
    ids=["different-month", "different-source-type"],
)
def test_save_sow_monthly_rejects_source_remapping(
    initialized_db: Path, remapped: SowMonthlyRecord
) -> None:
    first = _sow_record()
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)

    with pytest.raises(ValueError, match="different month or source_type"):
        storage.save_sow_monthly(remapped)

    assert _count(initialized_db, "sow_monthly_records") == 1
    assert _count(initialized_db, "processed_sources") == 1
    processed = _fetch_one(initialized_db, "SELECT business_key, source_type FROM processed_sources")
    assert tuple(processed) == (first.month, first.source_type.value)


def test_save_sow_monthly_preserves_null_changes(initialized_db: Path) -> None:
    record = _sow_record(mom_change=None, yoy_change=None)

    assert PigCycleStorage(initialized_db).save_sow_monthly(record) is SowMonthlySaveStatus.INSERTED

    stored = _fetch_one(initialized_db, "SELECT mom_change, yoy_change FROM sow_monthly_records")
    assert stored["mom_change"] is None
    assert stored["yoy_change"] is None


def test_save_sow_monthly_rolls_back_processed_source_when_business_insert_fails(
    initialized_db: Path,
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_sow_monthly_insert
            BEFORE INSERT ON sow_monthly_records
            BEGIN
                SELECT RAISE(ABORT, 'forced sow test failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced sow test failure"):
        PigCycleStorage(initialized_db).save_sow_monthly(_sow_record())

    assert _count(initialized_db, "sow_monthly_records") == 0
    assert _count(initialized_db, "processed_sources") == 0


def test_get_moa_weekly_processed_urls_includes_all_processed_outcomes(initialized_db: Path) -> None:
    first = _weekly_record()
    newer = replace(
        first,
        publish_date=date(2026, 8, 5),
        piglet_price=24.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-newer.htm",
    )
    older = replace(
        first,
        publish_date=date(2026, 8, 3),
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-older-known.htm",
    )
    conflict = replace(
        newer,
        live_hog_price=15.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-conflict-known.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)
    storage.save_moa_weekly(newer)
    storage.save_moa_weekly(older)
    storage.save_moa_weekly(conflict)

    assert storage.get_moa_weekly_processed_urls() == {
        first.source_url,
        newer.source_url,
        older.source_url,
        conflict.source_url,
    }
    assert _fetch_one(initialized_db, "SELECT source_url FROM moa_weekly_records")["source_url"] == newer.source_url


def test_get_sow_monthly_processed_urls_includes_non_current_sources(initialized_db: Path) -> None:
    first = _sow_record()
    conflict = replace(
        first,
        sow_inventory=3790.0,
        source_url="https://www.moa.gov.cn/sow-known-conflict.htm",
    )
    unknown_order = replace(
        first,
        sow_inventory=3800.0,
        publish_date=None,
        source_url="https://www.moa.gov.cn/sow-known-undated.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(first)
    storage.save_sow_monthly(conflict)
    storage.save_sow_monthly(unknown_order)

    assert storage.get_sow_monthly_processed_urls() == {
        first.source_url,
        conflict.source_url,
        unknown_order.source_url,
    }


def test_get_moa_weekly_collection_dates_returns_python_dates(initialized_db: Path) -> None:
    first = _weekly_record()
    second = replace(
        first,
        collection_date=date(2026, 8, 6),
        publish_date=date(2026, 8, 11),
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-next.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)
    storage.save_moa_weekly(second)

    result = storage.get_moa_weekly_collection_dates()

    assert result == {date(2026, 7, 30), date(2026, 8, 6)}
    assert all(isinstance(value, date) for value in result)


def test_get_sow_monthly_business_keys_preserves_source_type(initialized_db: Path) -> None:
    reported = _sow_record()
    nbs = replace(
        reported,
        source_type=SowSourceType.NBS,
        source_url="https://www.stats.gov.cn/sow-known-nbs.htm",
    )
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(reported)
    storage.save_sow_monthly(nbs)

    assert storage.get_sow_monthly_business_keys() == {
        ("2026-06", SowSourceType.MOA_REPORTED),
        ("2026-06", SowSourceType.NBS),
    }


def test_processed_url_readers_keep_record_kinds_separate(initialized_db: Path) -> None:
    weekly = _weekly_record()
    sow = _sow_record()
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(weekly)
    storage.save_sow_monthly(sow)

    assert storage.get_moa_weekly_processed_urls() == {weekly.source_url}
    assert storage.get_sow_monthly_processed_urls() == {sow.source_url}


def test_known_state_reads_do_not_change_timestamps(initialized_db: Path) -> None:
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(_weekly_record())
    storage.save_sow_monthly(_sow_record())
    before = _timestamp_state(initialized_db)

    storage.get_moa_weekly_processed_urls()
    storage.get_sow_monthly_processed_urls()
    storage.get_moa_weekly_collection_dates()
    storage.get_sow_monthly_business_keys()
    storage.get_record_counts()
    storage.get_latest_moa_weekly_record()
    storage.get_latest_sow_monthly_records_by_source()

    assert _timestamp_state(initialized_db) == before


def test_known_state_reads_return_empty_sets_for_initialized_empty_database(initialized_db: Path) -> None:
    storage = PigCycleStorage(initialized_db)

    assert storage.get_moa_weekly_processed_urls() == set()
    assert storage.get_sow_monthly_processed_urls() == set()
    assert storage.get_moa_weekly_collection_dates() == set()
    assert storage.get_sow_monthly_business_keys() == set()


def test_get_record_counts_returns_exact_table_counts(initialized_db: Path) -> None:
    storage = PigCycleStorage(initialized_db)
    assert storage.get_record_counts() == {
        "moa_weekly": 0,
        "sow_monthly": 0,
        "processed_sources": 0,
    }

    weekly = _weekly_record()
    storage.save_moa_weekly(weekly)
    storage.save_moa_weekly(
        replace(
            weekly,
            publish_date=date(2026, 8, 5),
            source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-revision.htm",
        )
    )
    storage.save_sow_monthly(_sow_record())

    assert storage.get_record_counts() == {
        "moa_weekly": 1,
        "sow_monthly": 1,
        "processed_sources": 3,
    }


def test_get_latest_moa_weekly_record_uses_collection_date(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    latest = replace(
        _weekly_record(),
        collection_date=date(2026, 8, 6),
        publish_date=date(2026, 8, 11),
        period_label="8月第1周",
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-latest.htm",
    )
    older_with_later_publication = replace(
        _weekly_record(),
        collection_date=date(2026, 7, 23),
        publish_date=date(2026, 8, 12),
        source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-old-corrected.htm",
    )
    storage.save_moa_weekly(latest)
    storage.save_moa_weekly(older_with_later_publication)

    result = storage.get_latest_moa_weekly_record()

    assert isinstance(result, MoaWeeklyRecord)
    assert result == latest


def test_get_latest_moa_weekly_record_returns_none_for_empty_table(
    initialized_db: Path,
) -> None:
    assert PigCycleStorage(initialized_db).get_latest_moa_weekly_record() is None


def test_get_latest_moa_weekly_record_restores_null_optional_prices(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    record = _weekly_record(soybean_meal_price=None, fattening_feed_price=None)
    storage.save_moa_weekly(record)

    result = storage.get_latest_moa_weekly_record()

    assert result is not None
    assert result.soybean_meal_price is None
    assert result.fattening_feed_price is None


def test_get_latest_sow_monthly_records_selects_latest_per_source(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    reported_old = replace(
        _sow_record(),
        month="2026-04",
        source_url="https://www.moa.gov.cn/sow-reported-old.htm",
    )
    reported_latest = replace(
        _sow_record(),
        month="2026-05",
        source_url="https://www.moa.gov.cn/sow-reported-latest.htm",
    )
    nbs_old = replace(
        _sow_record(),
        month="2026-05",
        source_type=SowSourceType.NBS,
        source_url="https://www.stats.gov.cn/sow-nbs-old.htm",
    )
    nbs_latest = replace(
        _sow_record(),
        month="2026-06",
        source_type=SowSourceType.NBS,
        source_url="https://www.stats.gov.cn/sow-nbs-latest.htm",
    )
    for record in (reported_old, reported_latest, nbs_old, nbs_latest):
        storage.save_sow_monthly(record)

    result = storage.get_latest_sow_monthly_records_by_source()

    assert result == [reported_latest, nbs_latest]
    assert all(isinstance(record.source_type, SowSourceType) for record in result)


def test_get_latest_sow_monthly_records_keeps_same_month_sources(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    reported = _sow_record()
    nbs = replace(
        reported,
        source_type=SowSourceType.NBS,
        source_url="https://www.stats.gov.cn/sow-same-month.htm",
    )
    storage.save_sow_monthly(reported)
    storage.save_sow_monthly(nbs)

    assert storage.get_latest_sow_monthly_records_by_source() == [reported, nbs]


def test_get_latest_sow_monthly_records_restores_null_fields(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    record = _sow_record(publish_date=None, mom_change=None, yoy_change=None)
    storage.save_sow_monthly(record)

    result = storage.get_latest_sow_monthly_records_by_source()

    assert result == [record]
    assert result[0].publish_date is None
    assert result[0].mom_change is None
    assert result[0].yoy_change is None


@pytest.mark.parametrize(
    "method_name",
    [
        "get_moa_weekly_processed_urls",
        "get_sow_monthly_processed_urls",
        "get_moa_weekly_collection_dates",
        "get_sow_monthly_business_keys",
        "get_record_counts",
        "get_latest_moa_weekly_record",
        "get_latest_sow_monthly_records_by_source",
    ],
)
def test_known_state_reads_reject_missing_database_without_creating_it(
    tmp_path: Path, method_name: str
) -> None:
    db_path = tmp_path / "missing.sqlite3"
    storage = PigCycleStorage(db_path)

    with pytest.raises(FileNotFoundError):
        getattr(storage, method_name)()

    assert not db_path.exists()


@pytest.mark.parametrize(
    "method_name",
    [
        "get_moa_weekly_processed_urls",
        "get_sow_monthly_processed_urls",
        "get_moa_weekly_collection_dates",
        "get_sow_monthly_business_keys",
        "get_record_counts",
        "get_latest_moa_weekly_record",
        "get_latest_sow_monthly_records_by_source",
    ],
)
def test_known_state_reads_expose_uninitialized_schema_error(
    tmp_path: Path, method_name: str
) -> None:
    db_path = tmp_path / "uninitialized.sqlite3"
    with closing(sqlite3.connect(db_path)):
        pass
    storage = PigCycleStorage(db_path)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        getattr(storage, method_name)()

    assert _table_names(db_path) == set()
