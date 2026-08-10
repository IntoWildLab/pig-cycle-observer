import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.pig_cycle.storage as storage_module
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.storage import MoaWeeklySaveStatus, PigCycleStorage


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
