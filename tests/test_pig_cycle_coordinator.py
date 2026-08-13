from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.pig_cycle.coordinator as coordinator_module
from src.pig_cycle.coordinator import (
    run_moa_weekly_history,
    run_moa_weekly_increment,
    run_sow_monthly_official_url,
)
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.sow_monthly import (
    SowMonthlyDataError,
    SowMonthlyRecord,
    SowSourceType,
)
from src.pig_cycle.storage import (
    MoaWeeklySaveStatus,
    PigCycleStorage,
    SowMonthlySaveStatus,
)


URL_A = "https://xmsyj.moa.gov.cn/jcyj/weekly-a.htm"
URL_B = "https://xmsyj.moa.gov.cn/jcyj/weekly-b.htm"
SOW_URL_A = "https://www.stats.gov.cn/sow-a.htm"
SOW_URL_B = "https://www.stats.gov.cn/sow-b.htm"


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


def _sow_record(
    *,
    sow_inventory: float = 3780.0,
    publish_date: date | None = date(2026, 7, 16),
    source_type: SowSourceType = SowSourceType.NBS,
    source_url: str = SOW_URL_A,
) -> SowMonthlyRecord:
    return SowMonthlyRecord(
        month="2026-06",
        sow_inventory=sow_inventory,
        mom_change=-0.1,
        yoy_change=-2.3,
        publish_date=publish_date,
        source_type=source_type,
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


def _sow_processed_at(storage: PigCycleStorage, source_url: str) -> str:
    with closing(sqlite3.connect(storage.db_path)) as connection:
        row = connection.execute(
            """
            SELECT processed_at FROM processed_sources
            WHERE record_kind = 'sow_monthly' AND source_url = ?
            """,
            (source_url,),
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


def test_sow_known_url_is_skipped_before_fetch_and_timestamp_is_unchanged(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_sow_monthly(_sow_record())
    before = _sow_processed_at(storage, SOW_URL_A)
    calls = 0

    def fail_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal calls
        calls += 1
        raise AssertionError("known URL must not be fetched")

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fail_fetch)
    monkeypatch.setattr(
        storage,
        "save_sow_monthly",
        lambda record: (_ for _ in ()).throw(AssertionError("known URL must not be saved")),
    )

    assert run_sow_monthly_official_url(storage, SOW_URL_A) is None
    assert calls == 0
    assert _sow_processed_at(storage, SOW_URL_A) == before


@pytest.mark.parametrize(
    "source_type",
    [SowSourceType.NBS, SowSourceType.MOA_REPORTED],
)
def test_sow_unknown_url_is_inserted_with_source_type_unchanged(
    storage: PigCycleStorage,
    monkeypatch: pytest.MonkeyPatch,
    source_type: SowSourceType,
) -> None:
    url = SOW_URL_A if source_type is SowSourceType.NBS else "https://www.moa.gov.cn/sow.htm"
    record = _sow_record(source_type=source_type, source_url=url)
    calls: list[tuple[str, float, object]] = []

    def fake_fetch(
        requested_url: str, *, timeout: float, session: object
    ) -> SowMonthlyRecord:
        calls.append((requested_url, timeout, session))
        return record

    fake_session = object()
    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)

    assert run_sow_monthly_official_url(
        storage, url, timeout=7.5, session=fake_session
    ) == (record, SowMonthlySaveStatus.INSERTED)
    assert calls == [(url, 7.5, fake_session)]
    assert storage.get_sow_monthly_business_keys() == {("2026-06", source_type)}
    assert storage.get_sow_monthly_processed_urls() == {url}


def test_sow_same_business_key_newer_url_is_updated_and_both_urls_remain(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_sow_monthly(_sow_record())
    revised = _sow_record(
        sow_inventory=3790.0,
        publish_date=date(2026, 7, 17),
        source_url=SOW_URL_B,
    )
    calls = 0

    def fake_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal calls
        calls += 1
        return revised

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)

    assert run_sow_monthly_official_url(storage, SOW_URL_B) == (
        revised,
        SowMonthlySaveStatus.UPDATED,
    )
    assert calls == 1
    assert storage.get_sow_monthly_processed_urls() == {SOW_URL_A, SOW_URL_B}
    assert storage.get_latest_sow_monthly_records_by_source() == [revised]


@pytest.mark.parametrize(
    ("current", "incoming", "expected"),
    [
        (
            _sow_record(),
            _sow_record(source_url=SOW_URL_B),
            SowMonthlySaveStatus.UNCHANGED,
        ),
        (
            _sow_record(),
            _sow_record(publish_date=date(2026, 7, 15), source_url=SOW_URL_B),
            SowMonthlySaveStatus.OLDER_IGNORED,
        ),
        (
            _sow_record(),
            _sow_record(sow_inventory=3790.0, source_url=SOW_URL_B),
            SowMonthlySaveStatus.CONFLICT,
        ),
        (
            _sow_record(publish_date=None),
            _sow_record(
                sow_inventory=3790.0,
                publish_date=None,
                source_url=SOW_URL_B,
            ),
            SowMonthlySaveStatus.ORDER_UNKNOWN,
        ),
    ],
)
def test_sow_storage_statuses_are_returned_without_coordinator_reimplementation(
    storage: PigCycleStorage,
    monkeypatch: pytest.MonkeyPatch,
    current: SowMonthlyRecord,
    incoming: SowMonthlyRecord,
    expected: SowMonthlySaveStatus,
) -> None:
    storage.save_sow_monthly(current)
    monkeypatch.setattr(
        coordinator_module,
        "fetch_sow_record_from_official_url",
        lambda *args, **kwargs: incoming,
    )

    assert run_sow_monthly_official_url(storage, incoming.source_url) == (
        incoming,
        expected,
    )


def test_sow_second_run_skips_url_saved_by_first_run(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _sow_record(source_url=SOW_URL_B)
    calls = 0

    def fake_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal calls
        calls += 1
        return record

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)

    assert run_sow_monthly_official_url(storage, SOW_URL_B) == (
        record,
        SowMonthlySaveStatus.INSERTED,
    )
    before = _sow_processed_at(storage, SOW_URL_B)
    assert run_sow_monthly_official_url(storage, SOW_URL_B) is None
    assert calls == 1
    assert _sow_processed_at(storage, SOW_URL_B) == before


def test_sow_fetch_error_propagates_without_retry_or_storage_changes(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = SowMonthlyDataError("parse failed")
    calls = 0

    def fail_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal calls
        calls += 1
        raise expected

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fail_fetch)

    with pytest.raises(SowMonthlyDataError) as raised:
        run_sow_monthly_official_url(storage, SOW_URL_A)

    assert raised.value is expected
    assert calls == 1
    assert storage.get_sow_monthly_business_keys() == set()
    assert storage.get_sow_monthly_processed_urls() == set()


@pytest.mark.parametrize(
    "error",
    [ValueError("mapping conflict"), sqlite3.OperationalError("write failed")],
)
def test_sow_save_error_propagates_without_retry(
    storage: PigCycleStorage,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    record = _sow_record()
    fetch_calls = 0
    save_calls = 0

    def fake_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal fetch_calls
        fetch_calls += 1
        return record

    def fail_save(value: SowMonthlyRecord) -> SowMonthlySaveStatus:
        nonlocal save_calls
        save_calls += 1
        raise error

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)
    monkeypatch.setattr(storage, "save_sow_monthly", fail_save)

    with pytest.raises(type(error)) as raised:
        run_sow_monthly_official_url(storage, SOW_URL_A)

    assert raised.value is error
    assert fetch_calls == 1
    assert save_calls == 1


def test_sow_missing_database_fails_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "missing.sqlite3"
    storage = PigCycleStorage(db_path)
    called = False

    def fake_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal called
        called = True
        return _sow_record()

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)

    with pytest.raises(FileNotFoundError):
        run_sow_monthly_official_url(storage, SOW_URL_A)
    assert called is False
    assert not db_path.exists()


def test_sow_uninitialized_database_fails_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "uninitialized.sqlite3"
    with closing(sqlite3.connect(db_path)):
        pass
    storage = PigCycleStorage(db_path)
    called = False

    def fake_fetch(*args: object, **kwargs: object) -> SowMonthlyRecord:
        nonlocal called
        called = True
        return _sow_record()

    monkeypatch.setattr(coordinator_module, "fetch_sow_record_from_official_url", fake_fetch)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        run_sow_monthly_official_url(storage, SOW_URL_A)
    assert called is False


def test_history_returns_without_network_when_target_is_already_met(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_moa_weekly(_weekly_record())
    monkeypatch.setattr(
        coordinator_module,
        "iter_recent_weekly_records",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("network must not start")),
    )
    assert run_moa_weekly_history(storage, target_total_records=1) == []


def test_history_streams_each_record_to_storage_and_stops_at_target(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _weekly_record(source_url=URL_A)
    second = replace(
        first,
        collection_date=date(2026, 7, 23),
        publish_date=date(2026, 7, 28),
        source_url=URL_B,
    )
    third = replace(second, collection_date=date(2026, 7, 16), source_url="https://xmsyj.moa.gov.cn/jcyj/weekly-c.htm")
    yielded = 0
    received: dict[str, object] = {}

    def fake_iterator(**kwargs: object):
        nonlocal yielded
        received.update(kwargs)
        for record in (first, second, third):
            yielded += 1
            yield record

    monkeypatch.setattr(coordinator_module, "iter_recent_weekly_records", fake_iterator)
    result = run_moa_weekly_history(
        storage,
        target_total_records=2,
        max_pages=2,
        max_articles=6,
        max_requests=8,
        timeout=7.5,
        session=object(),
    )
    assert result == [
        (first, MoaWeeklySaveStatus.INSERTED),
        (second, MoaWeeklySaveStatus.INSERTED),
    ]
    assert yielded == 2
    assert received["known_urls"] == set()
    assert "known_dates" not in received
    assert storage.get_moa_weekly_processed_urls() == {URL_A, URL_B}


def test_history_same_date_urls_both_reach_storage(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _weekly_record(source_url=URL_A)
    revised = replace(first, publish_date=date(2026, 8, 5), source_url=URL_B)
    monkeypatch.setattr(
        coordinator_module,
        "iter_recent_weekly_records",
        lambda **kwargs: iter((first, revised)),
    )
    result = run_moa_weekly_history(storage, target_total_records=2)
    assert result == [
        (first, MoaWeeklySaveStatus.INSERTED),
        (revised, MoaWeeklySaveStatus.UPDATED),
    ]
    assert storage.get_moa_weekly_processed_urls() == {URL_A, URL_B}


def test_history_save_error_stops_iterator_and_propagates(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _weekly_record()
    consumed = 0
    closed = False

    def fake_iterator(**kwargs: object):
        nonlocal consumed, closed
        try:
            consumed += 1
            yield record
            consumed += 1
            yield replace(record, source_url=URL_B)
        finally:
            closed = True

    expected = sqlite3.OperationalError("write failed")
    monkeypatch.setattr(coordinator_module, "iter_recent_weekly_records", fake_iterator)
    monkeypatch.setattr(storage, "save_moa_weekly", lambda value: (_ for _ in ()).throw(expected))
    with pytest.raises(sqlite3.OperationalError) as raised:
        run_moa_weekly_history(storage)
    assert raised.value is expected
    assert consumed == 1
    assert closed is True
