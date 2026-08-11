from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.snapshot import build_pig_cycle_snapshot, main
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.storage import PigCycleStorage


def _weekly_record(
    *,
    source_url: str = "https://xmsyj.moa.gov.cn/jcyj/weekly.htm",
    soybean_meal_price: float | None = 3.23,
    fattening_feed_price: float | None = 3.36,
) -> MoaWeeklyRecord:
    return MoaWeeklyRecord(
        collection_date=date(2026, 7, 30),
        publish_date=date(2026, 8, 4),
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
    source_type: SowSourceType = SowSourceType.NBS,
    source_url: str = "https://www.stats.gov.cn/sow.htm",
    publish_date: date | None = date(2026, 7, 16),
    mom_change: float | None = -0.1,
    yoy_change: float | None = 2.3,
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


@pytest.fixture
def storage(tmp_path: Path) -> PigCycleStorage:
    value = PigCycleStorage(tmp_path / "pig-cycle.sqlite3")
    value.initialize_schema()
    return value


def _timestamp_state(db_path: Path) -> tuple[list[tuple[object, ...]], ...]:
    with closing(sqlite3.connect(db_path)) as connection:
        weekly = connection.execute(
            "SELECT collection_date, created_at, updated_at FROM moa_weekly_records"
        ).fetchall()
        sow = connection.execute(
            "SELECT month, source_type, created_at, updated_at FROM sow_monthly_records"
        ).fetchall()
        processed = connection.execute(
            "SELECT record_kind, source_url, processed_at FROM processed_sources"
        ).fetchall()
    return weekly, sow, processed


def test_empty_database_snapshot(storage: PigCycleStorage) -> None:
    text = build_pig_cycle_snapshot(storage)

    assert "猪周期 V2 数据快照" in text
    assert "- MOA 周度记录：0" in text
    assert "- 母猪月度记录：0" in text
    assert "- 已处理来源：0" in text
    assert "  - MOA 周度：0" in text
    assert "  - 母猪月度：0" in text
    assert "- 暂无周度数据" in text
    assert "- 暂无母猪数据" in text


def test_weekly_snapshot_displays_all_fields(storage: PigCycleStorage) -> None:
    record = _weekly_record()
    storage.save_moa_weekly(record)

    text = build_pig_cycle_snapshot(storage)

    for expected in (
        "数据日期：2026-07-30",
        "发布日期：2026-08-04",
        "周期标签：7月第5周",
        "仔猪：23.00 元/公斤",
        "生猪：14.00 元/公斤",
        "玉米：2.50 元/公斤",
        "豆粕：3.23 元/公斤",
        "育肥猪配合饲料：3.36 元/公斤",
        "派生猪粮比：5.60",
        record.source_url,
    ):
        assert expected in text


def test_sow_snapshot_displays_all_fields(storage: PigCycleStorage) -> None:
    record = _sow_record()
    storage.save_sow_monthly(record)

    text = build_pig_cycle_snapshot(storage)

    for expected in (
        "来源类型：nbs",
        "数据月份：2026-06",
        "存栏：3780 万头",
        "环比：-0.1%",
        "同比：2.3%",
        "发布日期：2026-07-16",
        record.source_url,
    ):
        assert expected in text


def test_same_month_multiple_sow_sources_are_displayed(
    storage: PigCycleStorage,
) -> None:
    nbs = _sow_record()
    reported = replace(
        nbs,
        source_type=SowSourceType.MOA_REPORTED,
        source_url="https://www.moa.gov.cn/sow-reported.htm",
    )
    storage.save_sow_monthly(nbs)
    storage.save_sow_monthly(reported)

    text = build_pig_cycle_snapshot(storage)

    assert "来源类型：nbs" in text
    assert "来源类型：moa_reported" in text
    assert text.count("数据月份：2026-06") == 2


def test_each_sow_source_displays_its_own_latest_month(
    storage: PigCycleStorage,
) -> None:
    nbs = _sow_record(month="2026-06")
    reported = _sow_record(
        month="2026-05",
        source_type=SowSourceType.MOA_REPORTED,
        source_url="https://www.moa.gov.cn/sow-reported-may.htm",
    )
    storage.save_sow_monthly(nbs)
    storage.save_sow_monthly(reported)

    text = build_pig_cycle_snapshot(storage)

    assert "数据月份：2026-06" in text
    assert "数据月份：2026-05" in text
    assert nbs.source_url in text
    assert reported.source_url in text


def test_optional_none_values_are_displayed_as_unavailable(
    storage: PigCycleStorage,
) -> None:
    storage.save_moa_weekly(
        _weekly_record(soybean_meal_price=None, fattening_feed_price=None)
    )
    storage.save_sow_monthly(
        _sow_record(publish_date=None, mom_change=None, yoy_change=None)
    )

    text = build_pig_cycle_snapshot(storage)

    assert "- 豆粕：暂无" in text
    assert "- 育肥猪配合饲料：暂无" in text
    assert "  - 环比：暂无" in text
    assert "  - 同比：暂无" in text
    assert "  - 发布日期：暂无" in text


def test_processed_source_counts_include_remembered_revision_urls(
    storage: PigCycleStorage,
) -> None:
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

    text = build_pig_cycle_snapshot(storage)

    assert "- 已处理来源：3" in text
    assert "  - MOA 周度：2" in text
    assert "  - 母猪月度：1" in text


def test_build_snapshot_does_not_change_timestamps(
    storage: PigCycleStorage,
) -> None:
    storage.save_moa_weekly(_weekly_record())
    storage.save_sow_monthly(_sow_record())
    before = _timestamp_state(storage.db_path)

    build_pig_cycle_snapshot(storage)

    assert _timestamp_state(storage.db_path) == before


def test_missing_database_error_does_not_create_file(tmp_path: Path) -> None:
    db_path = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError):
        build_pig_cycle_snapshot(PigCycleStorage(db_path))

    assert not db_path.exists()


def test_uninitialized_schema_error_is_exposed(tmp_path: Path) -> None:
    db_path = tmp_path / "uninitialized.sqlite3"
    with closing(sqlite3.connect(db_path)):
        pass

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        build_pig_cycle_snapshot(PigCycleStorage(db_path))


def test_main_prints_snapshot_and_returns_zero(
    storage: PigCycleStorage, capsys: pytest.CaptureFixture[str]
) -> None:
    storage.save_moa_weekly(_weekly_record())
    expected = build_pig_cycle_snapshot(storage)

    assert main([str(storage.db_path)]) == 0

    assert capsys.readouterr().out == expected + "\n"
