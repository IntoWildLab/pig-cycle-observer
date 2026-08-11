from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.pig_cycle.coordinator as coordinator_module
from src.pig_cycle.coordinator import run_moa_weekly_increment
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.storage import MoaWeeklySaveStatus, PigCycleStorage


URL_A = "https://xmsyj.moa.gov.cn/jcyj/weekly-a.htm"
URL_B = "https://xmsyj.moa.gov.cn/jcyj/weekly-b.htm"


def _weekly_record(
    *,
    publish_date: date = date(2026, 8, 4),
    source_url: str = URL_A,
) -> MoaWeeklyRecord:
    return MoaWeeklyRecord(
        collection_date=date(2026, 7, 30),
        publish_date=publish_date,
        period_label="7月第5周",
        piglet_price=23.0,
        live_hog_price=14.0,
        corn_price=2.5,
        soybean_meal_price=3.23,
        fattening_feed_price=3.36,
        derived_pig_corn_ratio=5.6,
        source_url=source_url,
    )


@pytest.fixture
def storage(tmp_path: Path) -> PigCycleStorage:
    value = PigCycleStorage(tmp_path / "pig-cycle.sqlite3")
    value.initialize_schema()
    return value


def _processed_at(storage: PigCycleStorage, source_url: str) -> str:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        row = connection.execute(
            """
            SELECT processed_at FROM processed_sources
            WHERE record_kind = 'moa_weekly' AND source_url = ?
            """,
            (source_url,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _weekly_source_url(storage: PigCycleStorage) -> str:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        row = connection.execute(
            "SELECT source_url FROM moa_weekly_records WHERE collection_date = '2026-07-30'"
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_processed_urls_are_passed_and_known_dates_are_disabled(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_moa_weekly(_weekly_record())
    received: dict[str, object] = {}

    def fake_fetcher(**kwargs: object) -> None:
        received.update(kwargs)
        return None

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    assert run_moa_weekly_increment(storage, timeout=7.5, session=object()) is None
    assert received["known_urls"] == {URL_A}
    assert received["known_dates"] is None
    assert received["timeout"] == 7.5


def test_none_result_does_not_save(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        coordinator_module, "fetch_latest_weekly_increment", lambda **kwargs: None
    )
    save_calls = 0

    def fail_if_saved(record: MoaWeeklyRecord) -> MoaWeeklySaveStatus:
        nonlocal save_calls
        save_calls += 1
        raise AssertionError("save_moa_weekly must not be called")

    monkeypatch.setattr(storage, "save_moa_weekly", fail_if_saved)

    assert run_moa_weekly_increment(storage) is None
    assert save_calls == 0
    assert storage.get_moa_weekly_processed_urls() == set()


def test_new_record_is_inserted_and_source_is_remembered(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _weekly_record()
    monkeypatch.setattr(
        coordinator_module, "fetch_latest_weekly_increment", lambda **kwargs: record
    )

    assert run_moa_weekly_increment(storage) == (record, MoaWeeklySaveStatus.INSERTED)
    assert storage.get_moa_weekly_collection_dates() == {date(2026, 7, 30)}
    assert storage.get_moa_weekly_processed_urls() == {URL_A}


def test_same_date_newer_url_updates_and_keeps_both_sources(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_moa_weekly(_weekly_record())
    revised = replace(
        _weekly_record(), publish_date=date(2026, 8, 5), source_url=URL_B
    )
    received: dict[str, object] = {}

    def fake_fetcher(**kwargs: object) -> MoaWeeklyRecord:
        received.update(kwargs)
        return revised

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    assert run_moa_weekly_increment(storage) == (revised, MoaWeeklySaveStatus.UPDATED)
    assert received["known_urls"] == {URL_A}
    assert received["known_dates"] is None
    assert _weekly_source_url(storage) == URL_B
    assert storage.get_moa_weekly_processed_urls() == {URL_A, URL_B}


def test_next_run_sees_the_newly_processed_url(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_moa_weekly(_weekly_record())
    revised = replace(
        _weekly_record(), publish_date=date(2026, 8, 5), source_url=URL_B
    )
    seen: list[set[str]] = []

    def fake_fetcher(**kwargs: object) -> MoaWeeklyRecord | None:
        known_urls = set(kwargs["known_urls"])
        seen.append(known_urls)
        return revised if URL_B not in known_urls else None

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    assert run_moa_weekly_increment(storage) == (revised, MoaWeeklySaveStatus.UPDATED)
    assert run_moa_weekly_increment(storage) is None
    assert seen == [{URL_A}, {URL_A, URL_B}]


def test_reading_processed_urls_does_not_refresh_processed_at(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_moa_weekly(_weekly_record())
    before = _processed_at(storage, URL_A)
    monkeypatch.setattr(
        coordinator_module, "fetch_latest_weekly_increment", lambda **kwargs: None
    )

    assert run_moa_weekly_increment(storage) is None
    assert _processed_at(storage, URL_A) == before


def test_fetch_error_propagates_without_saving(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = RuntimeError("fetch failed")

    def fail_fetch(**kwargs: object) -> None:
        raise expected

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fail_fetch)

    with pytest.raises(RuntimeError) as raised:
        run_moa_weekly_increment(storage)

    assert raised.value is expected
    assert storage.get_moa_weekly_processed_urls() == set()
    assert storage.get_moa_weekly_collection_dates() == set()


@pytest.mark.parametrize(
    "error",
    [ValueError("mapping conflict"), sqlite3.OperationalError("write failed")],
)
def test_save_error_propagates(
    storage: PigCycleStorage,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    record = _weekly_record()
    monkeypatch.setattr(
        coordinator_module, "fetch_latest_weekly_increment", lambda **kwargs: record
    )

    def fail_save(value: MoaWeeklyRecord) -> MoaWeeklySaveStatus:
        raise error

    monkeypatch.setattr(storage, "save_moa_weekly", fail_save)

    with pytest.raises(type(error)) as raised:
        run_moa_weekly_increment(storage)

    assert raised.value is error


@pytest.mark.parametrize("outcome", [None, RuntimeError("fetch failed")])
def test_fetcher_is_called_only_once_without_retry(
    storage: PigCycleStorage,
    monkeypatch: pytest.MonkeyPatch,
    outcome: object,
) -> None:
    calls = 0

    def fake_fetcher(**kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return None

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    if isinstance(outcome, Exception):
        with pytest.raises(type(outcome)):
            run_moa_weekly_increment(storage)
    else:
        assert run_moa_weekly_increment(storage) is None
    assert calls == 1


def test_missing_database_fails_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = PigCycleStorage(tmp_path / "missing.sqlite3")
    called = False

    def fake_fetcher(**kwargs: object) -> None:
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    with pytest.raises(FileNotFoundError):
        run_moa_weekly_increment(storage)
    assert called is False


def test_uninitialized_schema_fails_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "uninitialized.sqlite3"
    with closing(sqlite3.connect(db_path)):
        pass
    storage = PigCycleStorage(db_path)
    called = False

    def fake_fetcher(**kwargs: object) -> None:
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(coordinator_module, "fetch_latest_weekly_increment", fake_fetcher)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        run_moa_weekly_increment(storage)
    assert called is False
