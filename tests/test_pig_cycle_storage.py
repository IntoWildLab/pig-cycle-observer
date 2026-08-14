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


TABLES = {
    "moa_weekly_records",
    "sow_monthly_records",
    "processed_sources",
    "moa_weekly_record_revisions",
    "sow_monthly_record_revisions",
}


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


def _fetch_all(
    db_path: Path, query: str, parameters: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(query, parameters).fetchall()


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


def _column_contract(db_path: Path, table: str) -> dict[str, tuple[str, int, int]]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        str(row[1]): (str(row[2]), int(row[3]), int(row[5]))
        for row in rows
    }


def _table_sql(db_path: Path, table: str) -> str:
    row = _fetch_one(
        db_path,
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    )
    return str(row["sql"])


def _insert_moa_revision(
    connection: sqlite3.Connection,
    *,
    collection_date: str = "2026-07-30",
    publish_date: str | None = "2026-08-04",
    source_url: str = "https://example/weekly-a",
    fingerprint: str = "fingerprint-a",
    save_status: str | None = "inserted",
    sets_current: int = 1,
    ingest_origin: str = "normal_ingest",
    soybean_meal_price: float | None = None,
    fattening_feed_price: float | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO moa_weekly_record_revisions (
            collection_date, publish_date, period_label, piglet_price,
            live_hog_price, corn_price, soybean_meal_price,
            fattening_feed_price, derived_pig_corn_ratio, source_url,
            payload_fingerprint, observed_at, save_status, sets_current,
            ingest_origin
        ) VALUES (?, ?, '7月第5周', 23.0, 14.0, 2.5, ?, ?, 5.6, ?, ?, ?, ?, ?, ?)
        """,
        (
            collection_date,
            publish_date,
            soybean_meal_price,
            fattening_feed_price,
            source_url,
            fingerprint,
            "2026-08-15T01:00:00+00:00",
            save_status,
            sets_current,
            ingest_origin,
        ),
    )


def _insert_sow_revision(
    connection: sqlite3.Connection,
    *,
    month: str = "2026-06",
    source_type: str = "nbs",
    publish_date: str | None = "2026-07-16",
    source_url: str = "https://example/sow-a",
    fingerprint: str = "fingerprint-a",
    save_status: str | None = "inserted",
    sets_current: int = 1,
    ingest_origin: str = "normal_ingest",
    mom_change: float | None = None,
    yoy_change: float | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO sow_monthly_record_revisions (
            month, source_type, sow_inventory, mom_change, yoy_change,
            publish_date, source_url, payload_fingerprint, observed_at,
            save_status, sets_current, ingest_origin
        ) VALUES (?, ?, 3780.0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            month,
            source_type,
            mom_change,
            yoy_change,
            publish_date,
            source_url,
            fingerprint,
            "2026-08-15T01:00:00+00:00",
            save_status,
            sets_current,
            ingest_origin,
        ),
    )


@pytest.fixture
def initialized_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "pig_cycle.sqlite3"
    PigCycleStorage(db_path).initialize_schema()
    return db_path


def test_initialize_schema_creates_current_and_revision_tables(initialized_db: Path) -> None:
    assert _table_names(initialized_db) == TABLES
    assert _count(initialized_db, "moa_weekly_record_revisions") == 0
    assert _count(initialized_db, "sow_monthly_record_revisions") == 0


def test_revision_tables_have_exact_column_contract(initialized_db: Path) -> None:
    assert _column_contract(initialized_db, "moa_weekly_record_revisions") == {
        "revision_id": ("INTEGER", 0, 1),
        "collection_date": ("TEXT", 1, 0),
        "publish_date": ("TEXT", 1, 0),
        "period_label": ("TEXT", 1, 0),
        "piglet_price": ("REAL", 1, 0),
        "live_hog_price": ("REAL", 1, 0),
        "corn_price": ("REAL", 1, 0),
        "soybean_meal_price": ("REAL", 0, 0),
        "fattening_feed_price": ("REAL", 0, 0),
        "derived_pig_corn_ratio": ("REAL", 1, 0),
        "source_url": ("TEXT", 1, 0),
        "payload_fingerprint": ("TEXT", 1, 0),
        "observed_at": ("TEXT", 1, 0),
        "save_status": ("TEXT", 0, 0),
        "sets_current": ("INTEGER", 1, 0),
        "ingest_origin": ("TEXT", 1, 0),
    }
    assert _column_contract(initialized_db, "sow_monthly_record_revisions") == {
        "revision_id": ("INTEGER", 0, 1),
        "month": ("TEXT", 1, 0),
        "source_type": ("TEXT", 1, 0),
        "sow_inventory": ("REAL", 1, 0),
        "mom_change": ("REAL", 0, 0),
        "yoy_change": ("REAL", 0, 0),
        "publish_date": ("TEXT", 0, 0),
        "source_url": ("TEXT", 1, 0),
        "payload_fingerprint": ("TEXT", 1, 0),
        "observed_at": ("TEXT", 1, 0),
        "save_status": ("TEXT", 0, 0),
        "sets_current": ("INTEGER", 1, 0),
        "ingest_origin": ("TEXT", 1, 0),
    }


@pytest.mark.parametrize(
    "table",
    ["moa_weekly_record_revisions", "sow_monthly_record_revisions"],
)
def test_revision_id_is_integer_primary_key_without_autoincrement(
    initialized_db: Path, table: str
) -> None:
    assert _primary_key(initialized_db, table) == ["revision_id"]
    assert "AUTOINCREMENT" not in _table_sql(initialized_db, table).upper()


@pytest.mark.parametrize(
    "table",
    ["moa_weekly_record_revisions", "sow_monthly_record_revisions"],
)
def test_revision_tables_only_have_source_fingerprint_unique_index(
    initialized_db: Path, table: str
) -> None:
    assert _index_columns(initialized_db, table) == {
        ("source_url", "payload_fingerprint")
    }
    with closing(sqlite3.connect(initialized_db)) as connection:
        assert connection.execute(f"PRAGMA foreign_key_list({table})").fetchall() == []


@pytest.mark.parametrize("kind", ["moa", "sow"])
def test_revision_source_fingerprint_uniqueness_contract(
    initialized_db: Path, kind: str
) -> None:
    insert = _insert_moa_revision if kind == "moa" else _insert_sow_revision
    with closing(sqlite3.connect(initialized_db)) as connection:
        insert(connection)
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection)
        insert(connection, fingerprint="fingerprint-b")
        insert(connection, source_url="https://example/source-b")


@pytest.mark.parametrize("kind", ["moa", "sow"])
def test_revision_tables_allow_same_business_key_and_publish_date(
    initialized_db: Path, kind: str
) -> None:
    insert = _insert_moa_revision if kind == "moa" else _insert_sow_revision
    with closing(sqlite3.connect(initialized_db)) as connection:
        insert(connection)
        insert(
            connection,
            source_url="https://example/source-b",
            fingerprint="fingerprint-b",
            save_status="conflict",
            sets_current=0,
        )


@pytest.mark.parametrize(
    ("status", "sets_current"),
    [
        ("inserted", 1),
        ("updated", 1),
        ("unchanged", 0),
        ("older_ignored", 0),
        ("conflict", 0),
    ],
)
def test_moa_revision_accepts_valid_normal_status_combinations(
    initialized_db: Path, status: str, sets_current: int
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        _insert_moa_revision(
            connection,
            source_url=f"https://example/{status}",
            save_status=status,
            sets_current=sets_current,
        )


@pytest.mark.parametrize(
    ("status", "sets_current"),
    [
        (None, 1),
        ("inserted", 0),
        ("updated", 0),
        ("unchanged", 1),
        ("conflict", 1),
        ("order_unknown", 0),
    ],
)
def test_moa_revision_rejects_invalid_normal_status_combinations(
    initialized_db: Path, status: str | None, sets_current: int
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_moa_revision(
                connection,
                save_status=status,
                sets_current=sets_current,
            )


@pytest.mark.parametrize(
    ("status", "sets_current"),
    [
        ("inserted", 1),
        ("updated", 1),
        ("unchanged", 0),
        ("older_ignored", 0),
        ("conflict", 0),
        ("order_unknown", 0),
    ],
)
def test_sow_revision_accepts_valid_normal_status_combinations(
    initialized_db: Path, status: str, sets_current: int
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        _insert_sow_revision(
            connection,
            source_url=f"https://example/{status}",
            save_status=status,
            sets_current=sets_current,
        )


@pytest.mark.parametrize(
    ("status", "sets_current"),
    [
        (None, 1),
        ("inserted", 0),
        ("updated", 0),
        ("unchanged", 1),
        ("conflict", 1),
        ("order_unknown", 1),
        ("unknown", 0),
    ],
)
def test_sow_revision_rejects_invalid_normal_status_combinations(
    initialized_db: Path, status: str | None, sets_current: int
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_sow_revision(
                connection,
                save_status=status,
                sets_current=sets_current,
            )


@pytest.mark.parametrize("kind", ["moa", "sow"])
def test_revision_baseline_contract(initialized_db: Path, kind: str) -> None:
    insert = _insert_moa_revision if kind == "moa" else _insert_sow_revision
    with closing(sqlite3.connect(initialized_db)) as connection:
        insert(
            connection,
            ingest_origin="baseline_import",
            save_status=None,
            sets_current=1,
        )
        for status, sets_current in (("inserted", 1), (None, 0)):
            with pytest.raises(sqlite3.IntegrityError):
                insert(
                    connection,
                    source_url=f"https://example/invalid-{status}-{sets_current}",
                    ingest_origin="baseline_import",
                    save_status=status,
                    sets_current=sets_current,
                )


@pytest.mark.parametrize("kind", ["moa", "sow"])
def test_revision_rejects_unknown_origin_and_invalid_boolean(
    initialized_db: Path, kind: str
) -> None:
    insert = _insert_moa_revision if kind == "moa" else _insert_sow_revision
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, ingest_origin="unknown")
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, sets_current=2)


@pytest.mark.parametrize("source_type", ["nbs", "moa_reported", "moa_estimate"])
def test_sow_revision_source_type_and_optional_fields(
    initialized_db: Path, source_type: str
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        _insert_sow_revision(
            connection,
            source_type=source_type,
            publish_date=None,
            mom_change=None,
            yoy_change=None,
            source_url=f"https://example/{source_type}",
        )


def test_sow_revision_rejects_unknown_source_type(initialized_db: Path) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_sow_revision(connection, source_type="unknown")


def test_moa_revision_nullable_prices_and_required_publish_date(
    initialized_db: Path,
) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        _insert_moa_revision(
            connection,
            soybean_meal_price=None,
            fattening_feed_price=None,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_moa_revision(
                connection,
                publish_date=None,
                source_url="https://example/missing-date",
            )


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


def test_additive_revision_schema_preserves_existing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "existing.sqlite3"
    storage = PigCycleStorage(db_path)
    current_only_statements = tuple(
        statement
        for statement in storage_module._SCHEMA_STATEMENTS
        if "_record_revisions" not in statement
    )
    with monkeypatch.context() as context:
        context.setattr(storage_module, "_SCHEMA_STATEMENTS", current_only_statements)
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

    assert _table_names(db_path) == TABLES
    assert _fetch_one(
        db_path,
        "SELECT collection_date, source_url FROM moa_weekly_records",
    )["source_url"] == "https://example/weekly"
    assert _count(db_path, "moa_weekly_record_revisions") == 0
    assert _count(db_path, "sow_monthly_record_revisions") == 0


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
    assert _count(initialized_db, "moa_weekly_record_revisions") == 1
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
    assert _count(initialized_db, "moa_weekly_record_revisions") == 0


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
    assert _count(initialized_db, "sow_monthly_record_revisions") == 1
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
    assert _count(initialized_db, "sow_monthly_record_revisions") == 0


def test_moa_weekly_v1_golden_fingerprint() -> None:
    assert storage_module._moa_weekly_payload_fingerprint(_weekly_record()) == (
        "c07202c8795f202c9afd8be60fb2877d3c08fbcdddf3b8882facedf9740419ca"
    )


def test_sow_monthly_v1_golden_fingerprint() -> None:
    assert storage_module._sow_monthly_payload_fingerprint(_sow_record()) == (
        "0fd1734a13450eb808505ab1a6ccc515a20c8abb360ac3a897f1a21f92cadbb0"
    )


def test_moa_fingerprint_identity_fields() -> None:
    record = _weekly_record()
    fingerprint = storage_module._moa_weekly_payload_fingerprint(record)

    assert storage_module._moa_weekly_payload_fingerprint(record) == fingerprint
    assert storage_module._moa_weekly_payload_fingerprint(
        replace(record, source_url="https://example/other")
    ) == fingerprint
    assert storage_module._moa_weekly_payload_fingerprint(
        replace(record, derived_pig_corn_ratio=99.0)
    ) == fingerprint
    assert storage_module._moa_weekly_payload_fingerprint(
        replace(record, piglet_price=23.1)
    ) != fingerprint
    assert storage_module._moa_weekly_payload_fingerprint(
        replace(record, publish_date=date(2026, 8, 5))
    ) != fingerprint
    assert len(fingerprint) == 64
    assert fingerprint == fingerprint.lower()


def test_moa_fingerprint_optional_and_signed_zero_are_stable() -> None:
    null_record = _weekly_record(soybean_meal_price=None, fattening_feed_price=None)
    assert storage_module._moa_weekly_payload_fingerprint(null_record) == (
        storage_module._moa_weekly_payload_fingerprint(replace(null_record))
    )
    assert storage_module._moa_weekly_payload_fingerprint(
        replace(null_record, soybean_meal_price=-0.0)
    ) == storage_module._moa_weekly_payload_fingerprint(
        replace(null_record, soybean_meal_price=0.0)
    )


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), float("-inf")])
def test_moa_fingerprint_rejects_invalid_numeric_values(invalid: object) -> None:
    record = replace(_weekly_record(), piglet_price=invalid)
    error = TypeError if isinstance(invalid, bool) else ValueError
    with pytest.raises(error):
        storage_module._moa_weekly_payload_fingerprint(record)


def test_sow_fingerprint_identity_fields() -> None:
    record = _sow_record(mom_change=None, yoy_change=None, publish_date=None)
    fingerprint = storage_module._sow_monthly_payload_fingerprint(record)

    assert storage_module._sow_monthly_payload_fingerprint(
        replace(record, source_url="https://example/other")
    ) == fingerprint
    assert storage_module._sow_monthly_payload_fingerprint(
        replace(record, sow_inventory=3780)
    ) == fingerprint
    assert storage_module._sow_monthly_payload_fingerprint(
        replace(record, sow_inventory=3781.0)
    ) != fingerprint
    assert storage_module._sow_monthly_payload_fingerprint(
        replace(record, source_type=SowSourceType.NBS)
    ) != fingerprint
    assert storage_module._sow_monthly_payload_fingerprint(
        replace(record, publish_date=date(2026, 7, 10))
    ) != fingerprint
    assert storage_module._sow_monthly_payload_fingerprint(record) == fingerprint


@pytest.mark.parametrize("invalid", [False, float("nan"), float("inf"), float("-inf")])
def test_sow_fingerprint_rejects_invalid_numeric_values(invalid: object) -> None:
    record = replace(_sow_record(), sow_inventory=invalid)
    error = TypeError if isinstance(invalid, bool) else ValueError
    with pytest.raises(error):
        storage_module._sow_monthly_payload_fingerprint(record)


def test_save_moa_weekly_appends_inserted_revision_with_complete_payload(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_module, "_utc_now", lambda: "2026-08-15T01:02:03+00:00")
    record = _weekly_record()

    assert PigCycleStorage(initialized_db).save_moa_weekly(record) is MoaWeeklySaveStatus.INSERTED

    revision = _fetch_one(initialized_db, "SELECT * FROM moa_weekly_record_revisions")
    assert revision["collection_date"] == record.collection_date.isoformat()
    assert revision["publish_date"] == record.publish_date.isoformat()
    assert revision["period_label"] == record.period_label
    assert revision["piglet_price"] == record.piglet_price
    assert revision["live_hog_price"] == record.live_hog_price
    assert revision["corn_price"] == record.corn_price
    assert revision["soybean_meal_price"] == record.soybean_meal_price
    assert revision["fattening_feed_price"] == record.fattening_feed_price
    assert revision["derived_pig_corn_ratio"] == record.derived_pig_corn_ratio
    assert revision["source_url"] == record.source_url
    assert revision["payload_fingerprint"] == storage_module._moa_weekly_payload_fingerprint(record)
    assert revision["observed_at"] == "2026-08-15T01:02:03+00:00"
    assert revision["save_status"] == "inserted"
    assert revision["sets_current"] == 1
    assert revision["ingest_origin"] == "normal_ingest"


@pytest.mark.parametrize(
    "candidate, expected_status",
    [
        (
            replace(
                _weekly_record(),
                publish_date=date(2026, 8, 5),
                piglet_price=24.0,
                source_url="https://example/weekly-updated",
            ),
            MoaWeeklySaveStatus.UPDATED,
        ),
        (
            replace(_weekly_record(), source_url="https://example/weekly-unchanged"),
            MoaWeeklySaveStatus.UNCHANGED,
        ),
        (
            replace(
                _weekly_record(),
                publish_date=date(2026, 8, 3),
                source_url="https://example/weekly-older",
            ),
            MoaWeeklySaveStatus.OLDER_IGNORED,
        ),
        (
            replace(
                _weekly_record(),
                live_hog_price=15.0,
                source_url="https://example/weekly-conflict",
            ),
            MoaWeeklySaveStatus.CONFLICT,
        ),
    ],
    ids=["updated", "unchanged", "older", "conflict"],
)
def test_save_moa_weekly_appends_revision_for_each_status(
    initialized_db: Path,
    candidate: MoaWeeklyRecord,
    expected_status: MoaWeeklySaveStatus,
) -> None:
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(_weekly_record())

    assert storage.save_moa_weekly(candidate) is expected_status

    revisions = _fetch_all(
        initialized_db,
        "SELECT source_url, save_status, sets_current FROM moa_weekly_record_revisions ORDER BY revision_id",
    )
    assert len(revisions) == 2
    assert revisions[0]["save_status"] == "inserted"
    assert revisions[1]["source_url"] == candidate.source_url
    assert revisions[1]["save_status"] == expected_status.value
    assert revisions[1]["sets_current"] == int(expected_status is MoaWeeklySaveStatus.UPDATED)


def test_save_sow_monthly_appends_inserted_revision_with_complete_payload(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_module, "_utc_now", lambda: "2026-08-15T02:03:04+00:00")
    record = _sow_record()

    assert PigCycleStorage(initialized_db).save_sow_monthly(record) is SowMonthlySaveStatus.INSERTED

    revision = _fetch_one(initialized_db, "SELECT * FROM sow_monthly_record_revisions")
    assert revision["month"] == record.month
    assert revision["source_type"] == record.source_type.value
    assert revision["sow_inventory"] == record.sow_inventory
    assert revision["mom_change"] == record.mom_change
    assert revision["yoy_change"] == record.yoy_change
    assert revision["publish_date"] == record.publish_date.isoformat()
    assert revision["source_url"] == record.source_url
    assert revision["payload_fingerprint"] == storage_module._sow_monthly_payload_fingerprint(record)
    assert revision["observed_at"] == "2026-08-15T02:03:04+00:00"
    assert revision["save_status"] == "inserted"
    assert revision["sets_current"] == 1
    assert revision["ingest_origin"] == "normal_ingest"


@pytest.mark.parametrize(
    "candidate, expected_status",
    [
        (
            replace(
                _sow_record(),
                sow_inventory=3790.0,
                publish_date=date(2026, 7, 11),
                source_url="https://example/sow-updated",
            ),
            SowMonthlySaveStatus.UPDATED,
        ),
        (
            replace(_sow_record(), source_url="https://example/sow-unchanged"),
            SowMonthlySaveStatus.UNCHANGED,
        ),
        (
            replace(
                _sow_record(),
                publish_date=date(2026, 7, 9),
                source_url="https://example/sow-older",
            ),
            SowMonthlySaveStatus.OLDER_IGNORED,
        ),
        (
            replace(
                _sow_record(),
                sow_inventory=3790.0,
                source_url="https://example/sow-conflict",
            ),
            SowMonthlySaveStatus.CONFLICT,
        ),
        (
            replace(
                _sow_record(publish_date=None),
                sow_inventory=3790.0,
                source_url="https://example/sow-order-unknown",
            ),
            SowMonthlySaveStatus.ORDER_UNKNOWN,
        ),
    ],
    ids=["updated", "unchanged", "older", "conflict", "order-unknown"],
)
def test_save_sow_monthly_appends_revision_for_each_status(
    initialized_db: Path,
    candidate: SowMonthlyRecord,
    expected_status: SowMonthlySaveStatus,
) -> None:
    initial = _sow_record(publish_date=None) if expected_status is SowMonthlySaveStatus.ORDER_UNKNOWN else _sow_record()
    storage = PigCycleStorage(initialized_db)
    storage.save_sow_monthly(initial)

    assert storage.save_sow_monthly(candidate) is expected_status

    revisions = _fetch_all(
        initialized_db,
        "SELECT source_url, save_status, sets_current FROM sow_monthly_record_revisions ORDER BY revision_id",
    )
    assert len(revisions) == 2
    assert revisions[0]["save_status"] == "inserted"
    assert revisions[1]["source_url"] == candidate.source_url
    assert revisions[1]["save_status"] == expected_status.value
    assert revisions[1]["sets_current"] == int(expected_status is SowMonthlySaveStatus.UPDATED)


@pytest.mark.parametrize("kind", ["weekly", "sow"])
def test_same_url_same_fingerprint_does_not_refresh_revision(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    times = iter(("2026-08-15T01:00:00+00:00", "2026-08-16T01:00:00+00:00"))
    monkeypatch.setattr(storage_module, "_utc_now", lambda: next(times))
    storage = PigCycleStorage(initialized_db)
    record = _weekly_record() if kind == "weekly" else _sow_record()
    save = storage.save_moa_weekly if kind == "weekly" else storage.save_sow_monthly
    table = "moa_weekly_record_revisions" if kind == "weekly" else "sow_monthly_record_revisions"

    save(record)
    assert save(record).value == "unchanged"

    assert _count(initialized_db, table) == 1
    revision = _fetch_one(initialized_db, f"SELECT observed_at, save_status FROM {table}")
    assert tuple(revision) == ("2026-08-15T01:00:00+00:00", "inserted")


def test_same_url_changed_payload_appends_revision_without_refreshing_processed_at(
    initialized_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter(("2026-08-15T01:00:00+00:00", "2026-08-16T01:00:00+00:00"))
    monkeypatch.setattr(storage_module, "_utc_now", lambda: next(times))
    first = _weekly_record()
    changed = replace(first, publish_date=date(2026, 8, 5), piglet_price=24.0)
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)

    assert storage.save_moa_weekly(changed) is MoaWeeklySaveStatus.UPDATED

    assert _count(initialized_db, "moa_weekly_record_revisions") == 2
    processed = _fetch_one(initialized_db, "SELECT processed_at FROM processed_sources")
    assert processed["processed_at"] == "2026-08-15T01:00:00+00:00"


def test_derived_ratio_only_change_does_not_create_official_revision(initialized_db: Path) -> None:
    first = _weekly_record()
    changed = replace(first, derived_pig_corn_ratio=5.7)
    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(first)

    assert storage.save_moa_weekly(changed) is MoaWeeklySaveStatus.CONFLICT
    assert _count(initialized_db, "moa_weekly_record_revisions") == 1


def test_revision_insert_failure_rolls_back_current_and_processed(initialized_db: Path) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_revision_insert
            BEFORE INSERT ON moa_weekly_record_revisions
            BEGIN
                SELECT RAISE(ABORT, 'forced revision failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced revision failure"):
        PigCycleStorage(initialized_db).save_moa_weekly(_weekly_record())

    assert _count(initialized_db, "moa_weekly_record_revisions") == 0
    assert _count(initialized_db, "moa_weekly_records") == 0
    assert _count(initialized_db, "processed_sources") == 0


def test_processed_source_failure_leaves_no_partial_revision_or_current(initialized_db: Path) -> None:
    with closing(sqlite3.connect(initialized_db)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_processed_insert
            BEFORE INSERT ON processed_sources
            BEGIN
                SELECT RAISE(ABORT, 'forced processed failure');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="forced processed failure"):
        PigCycleStorage(initialized_db).save_moa_weekly(_weekly_record())

    assert _count(initialized_db, "moa_weekly_record_revisions") == 0
    assert _count(initialized_db, "moa_weekly_records") == 0
    assert _count(initialized_db, "processed_sources") == 0


def test_save_without_revision_schema_rolls_back_existing_table_mutations(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        for statement in storage_module._SCHEMA_STATEMENTS:
            if "_record_revisions" not in statement:
                connection.execute(statement)
        connection.commit()

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        PigCycleStorage(db_path).save_moa_weekly(_weekly_record())

    assert _count(db_path, "moa_weekly_records") == 0
    assert _count(db_path, "processed_sources") == 0


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
    storage.get_sow_monthly_history(source_type=SowSourceType.MOA_REPORTED)

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


def test_get_moa_weekly_history_is_sorted_and_restores_complete_records(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    records = [
        replace(
            _weekly_record(),
            collection_date=collection_date,
            publish_date=publish_date,
            soybean_meal_price=None if index == 1 else 3.23,
            fattening_feed_price=None if index == 1 else 3.36,
            source_url=f"https://xmsyj.moa.gov.cn/jcyj/{index}.htm",
        )
        for index, (collection_date, publish_date) in enumerate(
            (
                (date(2026, 7, 16), date(2026, 7, 21)),
                (date(2026, 7, 2), date(2026, 7, 7)),
                (date(2026, 7, 9), date(2026, 7, 14)),
            )
        )
    ]
    for record in records:
        storage.save_moa_weekly(record)

    result = storage.get_moa_weekly_history()

    assert result == [records[1], records[2], records[0]]
    assert all(isinstance(record, MoaWeeklyRecord) for record in result)
    assert result[0].soybean_meal_price is None
    assert result[0].fattening_feed_price is None


def test_get_moa_weekly_history_limit_selects_latest_then_returns_ascending(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    for index, collection_date in enumerate(
        (date(2026, 7, 2), date(2026, 7, 9), date(2026, 7, 16))
    ):
        storage.save_moa_weekly(
            replace(
                _weekly_record(),
                collection_date=collection_date,
                source_url=f"https://xmsyj.moa.gov.cn/jcyj/{index}.htm",
            )
        )

    result = storage.get_moa_weekly_history(limit=2)

    assert [record.collection_date for record in result] == [
        date(2026, 7, 9),
        date(2026, 7, 16),
    ]


def test_get_moa_weekly_history_empty_and_invalid_limits(initialized_db: Path) -> None:
    storage = PigCycleStorage(initialized_db)
    assert storage.get_moa_weekly_history() == []
    for limit in (0, -1):
        with pytest.raises(ValueError, match="greater than zero"):
            storage.get_moa_weekly_history(limit=limit)
    for limit in (1.5, "2", True):
        with pytest.raises(TypeError, match="positive integer"):
            storage.get_moa_weekly_history(limit=limit)  # type: ignore[arg-type]


def test_get_moa_weekly_history_missing_uninitialized_and_read_only(
    tmp_path: Path, initialized_db: Path
) -> None:
    missing = tmp_path / "missing-moa-history.sqlite3"
    with pytest.raises(FileNotFoundError):
        PigCycleStorage(missing).get_moa_weekly_history()
    assert not missing.exists()

    uninitialized = tmp_path / "uninitialized-moa-history.sqlite3"
    with closing(sqlite3.connect(uninitialized)):
        pass
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        PigCycleStorage(uninitialized).get_moa_weekly_history()

    storage = PigCycleStorage(initialized_db)
    storage.save_moa_weekly(_weekly_record())
    before = _timestamp_state(initialized_db)
    storage.get_moa_weekly_history()
    assert _timestamp_state(initialized_db) == before


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


def test_get_sow_monthly_history_is_sorted_and_isolated_by_source(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    nbs_records = [
        replace(
            _sow_record(),
            month=month,
            source_type=SowSourceType.NBS,
            source_url=f"https://www.stats.gov.cn/{month}.htm",
        )
        for month in ("2026-06", "2025-12", "2026-03")
    ]
    reported = replace(
        _sow_record(),
        month="2026-05",
        source_url="https://www.moa.gov.cn/reported.htm",
    )
    for record in (*nbs_records, reported):
        storage.save_sow_monthly(record)

    result = storage.get_sow_monthly_history(source_type=SowSourceType.NBS)

    assert [record.month for record in result] == ["2025-12", "2026-03", "2026-06"]
    assert all(record.source_type is SowSourceType.NBS for record in result)
    assert reported not in result


def test_get_sow_monthly_history_limit_selects_latest_then_returns_ascending(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    for month in ("2025-12", "2026-03", "2026-06"):
        storage.save_sow_monthly(
            replace(
                _sow_record(),
                month=month,
                source_type=SowSourceType.NBS,
                source_url=f"https://www.stats.gov.cn/{month}.htm",
            )
        )

    result = storage.get_sow_monthly_history(
        source_type=SowSourceType.NBS,
        limit=2,
    )

    assert [record.month for record in result] == ["2026-03", "2026-06"]


def test_get_sow_monthly_history_restores_null_fields_and_empty_source(
    initialized_db: Path,
) -> None:
    storage = PigCycleStorage(initialized_db)
    record = _sow_record(publish_date=None, mom_change=None, yoy_change=None)
    storage.save_sow_monthly(record)

    assert storage.get_sow_monthly_history(
        source_type=SowSourceType.MOA_REPORTED
    ) == [record]
    assert storage.get_sow_monthly_history(source_type=SowSourceType.NBS) == []


@pytest.mark.parametrize("limit", [0, -1])
def test_get_sow_monthly_history_rejects_non_positive_limit(
    initialized_db: Path, limit: int
) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        PigCycleStorage(initialized_db).get_sow_monthly_history(
            source_type=SowSourceType.NBS,
            limit=limit,
        )


@pytest.mark.parametrize("limit", [1.5, "2", True])
def test_get_sow_monthly_history_rejects_non_integer_limit(
    initialized_db: Path, limit: object
) -> None:
    with pytest.raises(TypeError, match="positive integer"):
        PigCycleStorage(initialized_db).get_sow_monthly_history(
            source_type=SowSourceType.NBS,
            limit=limit,  # type: ignore[arg-type]
        )


def test_get_sow_monthly_history_requires_source_type_enum(
    initialized_db: Path,
) -> None:
    with pytest.raises(TypeError, match="SowSourceType"):
        PigCycleStorage(initialized_db).get_sow_monthly_history(
            source_type="nbs",  # type: ignore[arg-type]
        )


def test_get_sow_monthly_history_missing_and_uninitialized_database(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-history.sqlite3"
    with pytest.raises(FileNotFoundError):
        PigCycleStorage(missing).get_sow_monthly_history(
            source_type=SowSourceType.NBS
        )
    assert not missing.exists()

    uninitialized = tmp_path / "uninitialized-history.sqlite3"
    with closing(sqlite3.connect(uninitialized)):
        pass
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        PigCycleStorage(uninitialized).get_sow_monthly_history(
            source_type=SowSourceType.NBS
        )


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
