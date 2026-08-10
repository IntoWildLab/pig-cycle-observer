import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import src.pig_cycle.storage as storage_module
from src.pig_cycle.storage import PigCycleStorage


TABLES = {"moa_weekly_records", "sow_monthly_records", "processed_sources"}


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
