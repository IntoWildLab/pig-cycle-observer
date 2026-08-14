from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import src.pig_cycle.snapshot as snapshot_module
from src.pig_cycle.moa_weekly import MoaWeeklyRecord
from src.pig_cycle.snapshot import build_pig_cycle_snapshot, main
from src.pig_cycle.sow_monthly import SowMonthlyRecord, SowSourceType
from src.pig_cycle.storage import PigCycleStorage
from src.pig_cycle.trend import MoaWeeklyMetric


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
    sow_inventory: float = 3780.0,
) -> SowMonthlyRecord:
    return SowMonthlyRecord(
        month=month,
        sow_inventory=sow_inventory,
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
        "官方环比：-0.1%",
        "官方同比：2.3%",
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
    latest_section = text.split("能繁母猪月度最新数据（按来源）", 1)[1].split(
        "能繁母猪历史", 1
    )[0]

    assert "来源类型：nbs" in latest_section
    assert "来源类型：moa_reported" in latest_section
    assert latest_section.count("数据月份：2026-06") == 2


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
    assert "  - 官方环比：暂无" in text
    assert "  - 官方同比：暂无" in text
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


def test_sow_history_displays_mechanical_changes_and_real_publish_dates(
    storage: PigCycleStorage,
) -> None:
    records = [
        _sow_record(
            month="2025-12",
            sow_inventory=3961.0,
            publish_date=date(2026, 1, 19),
            mom_change=None,
            yoy_change=None,
            source_url="https://www.stats.gov.cn/2025-12.htm",
        ),
        _sow_record(
            month="2026-03",
            sow_inventory=3904.0,
            publish_date=date(2026, 4, 17),
            mom_change=None,
            yoy_change=None,
            source_url="https://www.stats.gov.cn/2026-03.htm",
        ),
        _sow_record(
            month="2026-06",
            sow_inventory=3780.0,
            publish_date=date(2026, 7, 16),
            mom_change=None,
            yoy_change=None,
            source_url="https://www.stats.gov.cn/2026-06.htm",
        ),
    ]
    for record in reversed(records):
        storage.save_sow_monthly(record)

    text = build_pig_cycle_snapshot(storage)

    history = text.split("能繁母猪历史（nbs）", 1)[1]
    assert history.index("2025-12：3961 万头") < history.index("2026-03：3904 万头")
    assert history.index("2026-03：3904 万头") < history.index("2026-06：3780 万头")
    assert "较上一条记录：-57 万头，-1.44%" in history
    assert "较上一条记录：-124 万头，-3.18%" in history
    assert "发布日期：2026-01-19" in history
    assert "所示记录方向：连续下降" in history
    assert "较上一条记录：" in history
    assert "较上一条记录：环比" not in history


def test_sow_history_keeps_sources_separate(storage: PigCycleStorage) -> None:
    storage.save_sow_monthly(
        _sow_record(
            month="2026-03",
            sow_inventory=3904.0,
            source_url="https://www.stats.gov.cn/2026-03.htm",
        )
    )
    storage.save_sow_monthly(
        _sow_record(
            month="2026-06",
            sow_inventory=3780.0,
            source_url="https://www.stats.gov.cn/2026-06.htm",
        )
    )
    storage.save_sow_monthly(
        _sow_record(
            month="2026-05",
            sow_inventory=4000.0,
            source_type=SowSourceType.MOA_REPORTED,
            source_url="https://www.moa.gov.cn/2026-05.htm",
        )
    )

    text = build_pig_cycle_snapshot(storage)
    reported_start = text.index("能繁母猪历史（moa_reported）")
    nbs_start = text.index("能繁母猪历史（nbs）")
    reported = text[reported_start:nbs_start]
    nbs = text[nbs_start:]

    assert "2026-03：3904 万头" in nbs
    assert "2026-06：3780 万头" in nbs
    assert "2026-05：4000 万头" not in nbs
    assert "2026-05：4000 万头" in reported
    assert "较上一条记录" not in reported
    assert "所示记录方向：记录不足" in reported


@pytest.mark.parametrize(
    ("inventories", "expected"),
    [
        ([3900.0, 3910.0, 3920.0], "连续上升"),
        ([3900.0, 3900.0, 3900.0], "持平"),
        ([3900.0, 3910.0, 3905.0], "混合"),
    ],
)
def test_sow_history_direction_is_a_mechanical_description(
    storage: PigCycleStorage,
    inventories: list[float],
    expected: str,
) -> None:
    for index, (month, inventory) in enumerate(
        zip(("2026-01", "2026-02", "2026-03"), inventories),
        start=1,
    ):
        storage.save_sow_monthly(
            _sow_record(
                month=month,
                sow_inventory=inventory,
                source_url=f"https://www.stats.gov.cn/{index}.htm",
            )
        )

    text = build_pig_cycle_snapshot(storage)

    assert f"所示记录方向：{expected}" in text
    for forbidden in ("产能去化期", "底部形成期", "买入", "卖出", "投资建议"):
        assert forbidden not in text


def test_empty_and_single_moa_weekly_history(storage: PigCycleStorage) -> None:
    assert "MOA 周度历史（最近 6 条）\n- 暂无周度历史数据" in build_pig_cycle_snapshot(storage)

    record = _weekly_record()
    storage.save_moa_weekly(record)
    text = build_pig_cycle_snapshot(storage)
    history = text.split("MOA 周度历史（最近 6 条）", 1)[1].split(
        "能繁母猪月度最新数据（按来源）", 1
    )[0]
    assert "较上一条记录" not in history
    assert "仔猪所示记录方向：记录不足" in history
    assert "生猪所示记录方向：记录不足" in history
    assert "猪粮比所示记录方向：记录不足" in history
    assert record.source_url not in history
    assert record.source_url in text.split("最新 MOA 周度", 1)[1].split(
        "MOA 周度历史（最近 6 条）", 1
    )[0]


def test_moa_weekly_history_displays_mechanical_changes_without_urls(
    storage: PigCycleStorage,
) -> None:
    first = replace(
        _weekly_record(),
        collection_date=date(2026, 7, 2),
        publish_date=date(2026, 7, 7),
        piglet_price=21.64,
        live_hog_price=10.48,
        derived_pig_corn_ratio=4.23,
        source_url="https://xmsyj.moa.gov.cn/jcyj/first.htm",
    )
    second = replace(
        first,
        collection_date=date(2026, 7, 9),
        publish_date=date(2026, 7, 14),
        piglet_price=22.43,
        live_hog_price=11.35,
        derived_pig_corn_ratio=4.58,
        soybean_meal_price=None,
        fattening_feed_price=None,
        source_url="https://xmsyj.moa.gov.cn/jcyj/second.htm",
    )
    storage.save_moa_weekly(second)
    storage.save_moa_weekly(first)

    text = build_pig_cycle_snapshot(storage)
    history = text.split("MOA 周度历史（最近 6 条）", 1)[1].split(
        "能繁母猪月度最新数据（按来源）", 1
    )[0]
    assert history.index("2026-07-02") < history.index("2026-07-09")
    assert "较上一条记录：+0.79 元/公斤，+3.65%" in history
    assert "较上一条记录：+0.87 元/公斤，+8.30%" in history
    assert "较上一条记录：+0.35，+8.27%" in history
    assert "发布日期：2026-07-14" in history
    assert "豆粕：暂无" in history
    assert "育肥猪配合饲料：暂无" in history
    assert first.source_url not in history and second.source_url not in history
    assert "环比" not in history


def test_moa_weekly_history_zero_previous_value_avoids_division(
    storage: PigCycleStorage,
) -> None:
    first = replace(
        _weekly_record(),
        collection_date=date(2026, 7, 2),
        piglet_price=0.0,
        live_hog_price=0.0,
        derived_pig_corn_ratio=0.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/zero.htm",
    )
    second = replace(
        first,
        collection_date=date(2026, 7, 9),
        piglet_price=1.0,
        live_hog_price=2.0,
        derived_pig_corn_ratio=3.0,
        source_url="https://xmsyj.moa.gov.cn/jcyj/nonzero.htm",
    )
    storage.save_moa_weekly(first)
    storage.save_moa_weekly(second)
    history = build_pig_cycle_snapshot(storage).split("MOA 周度历史（最近 6 条）", 1)[1]
    assert "较上一条记录：+1.00 元/公斤，暂无" in history
    assert "较上一条记录：+2.00 元/公斤，暂无" in history
    assert "较上一条记录：+3.00，暂无" in history


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.0, 2.0, 3.0], "连续上升"),
        ([3.0, 2.0, 1.0], "连续下降"),
        ([2.0, 2.0, 2.0], "持平"),
        ([1.0, 3.0, 2.0], "混合"),
    ],
)
def test_moa_weekly_history_direction_is_mechanical(
    storage: PigCycleStorage, values: list[float], expected: str
) -> None:
    for index, value in enumerate(values):
        storage.save_moa_weekly(
            replace(
                _weekly_record(),
                collection_date=date(2026, 7, 2 + index * 7),
                piglet_price=value,
                live_hog_price=value,
                derived_pig_corn_ratio=value,
                source_url=f"https://xmsyj.moa.gov.cn/jcyj/{index}.htm",
            )
        )
    text = build_pig_cycle_snapshot(storage)
    assert f"仔猪所示记录方向：{expected}" in text
    assert f"生猪所示记录方向：{expected}" in text
    assert f"猪粮比所示记录方向：{expected}" in text
    for forbidden in ("猪周期阶段", "价格见底", "拐点确认", "趋势确认", "景气改善", "投资建议"):
        assert forbidden not in text


def test_snapshot_consumes_trend_layer_for_moa_and_sow(
    storage: PigCycleStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    weekly_calls: list[MoaWeeklyMetric] = []
    sow_calls: list[SowSourceType] = []
    real_weekly = snapshot_module.calculate_moa_weekly_trend
    real_sow = snapshot_module.calculate_sow_inventory_trend

    def weekly_spy(records: object, *, metric: MoaWeeklyMetric):
        weekly_calls.append(metric)
        return real_weekly(records, metric=metric)  # type: ignore[arg-type]

    def sow_spy(records: object, *, source_type: SowSourceType):
        sow_calls.append(source_type)
        return real_sow(records, source_type=source_type)  # type: ignore[arg-type]

    monkeypatch.setattr(snapshot_module, "calculate_moa_weekly_trend", weekly_spy)
    monkeypatch.setattr(snapshot_module, "calculate_sow_inventory_trend", sow_spy)
    storage.save_moa_weekly(_weekly_record())
    storage.save_sow_monthly(_sow_record())

    build_pig_cycle_snapshot(storage)

    assert weekly_calls == [
        MoaWeeklyMetric.PIGLET_PRICE,
        MoaWeeklyMetric.LIVE_HOG_PRICE,
        MoaWeeklyMetric.DERIVED_PIG_CORN_RATIO,
    ]
    assert sow_calls == [SowSourceType.NBS]


def test_moa_trend_summary_formats_features_and_keeps_whole_window_direction(
    storage: PigCycleStorage,
) -> None:
    values = (
        (date(2026, 7, 2), 21.64, 10.48, 4.23),
        (date(2026, 7, 9), 22.43, 11.35, 4.58),
        (date(2026, 7, 23), 22.00, 11.00, 4.50),
    )
    for index, (collection_date, piglet, hog, ratio) in enumerate(values):
        storage.save_moa_weekly(
            replace(
                _weekly_record(),
                collection_date=collection_date,
                publish_date=date(2026, 7, 7 + index * 7),
                piglet_price=piglet,
                live_hog_price=hog,
                derived_pig_corn_ratio=ratio,
                source_url=f"https://xmsyj.moa.gov.cn/jcyj/trend-{index}.htm",
            )
        )

    text = build_pig_cycle_snapshot(storage)
    summary = text.split("MOA 趋势特征摘要（当前展示窗口）", 1)[1].split(
        "能繁母猪月度最新数据（按来源）", 1
    )[0]
    assert "- 仔猪" in summary and "- 生猪" in summary and "- 猪粮比" in summary
    assert "窗口首尾变化：+1.66%" in summary
    assert "最新相邻变化：-1.92%" in summary
    assert "末端连续下降变化：1 次" in summary
    assert "观测间隔：存在不规则间隔（实际：7/14 天）" in summary
    assert "仔猪所示记录方向：混合" in text
    assert "生猪所示记录方向：混合" in text
    assert "连续下降 1 周" not in summary
    assert "周环比" not in summary
    assert not any(
        forbidden in summary
        for forbidden in ("周期阶段", "趋势确认", "confidence", "投资建议")
    )
    assert "-1.9197503343736073" not in summary


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.0, 2.0, 3.0], "末端连续上升变化：2 次"),
        ([3.0, 2.0, 1.0], "末端连续下降变化：2 次"),
        ([1.0, 2.0, 2.0], "末端相邻变化：持平"),
    ],
)
def test_moa_trend_summary_terminal_streak_text(
    storage: PigCycleStorage, values: list[float], expected: str
) -> None:
    for index, value in enumerate(values):
        storage.save_moa_weekly(
            replace(
                _weekly_record(),
                collection_date=date(2026, 7, 2 + index * 7),
                piglet_price=value,
                live_hog_price=value,
                derived_pig_corn_ratio=value,
                source_url=f"https://xmsyj.moa.gov.cn/jcyj/streak-{index}.htm",
            )
        )
    assert expected in build_pig_cycle_snapshot(storage)


def test_empty_and_single_moa_trend_summary_behavior(storage: PigCycleStorage) -> None:
    assert "MOA 趋势特征摘要" not in build_pig_cycle_snapshot(storage)

    storage.save_moa_weekly(_weekly_record())
    text = build_pig_cycle_snapshot(storage)
    summary = text.split("MOA 趋势特征摘要（当前展示窗口）", 1)[1].split(
        "能繁母猪月度最新数据（按来源）", 1
    )[0]
    assert summary.count("窗口首尾变化：暂无") == 3
    assert summary.count("最新相邻变化：暂无") == 3
    assert summary.count("末端连续变化：记录不足") == 3
    assert "观测间隔：记录不足，无法检查" in summary


def test_trend_percentage_avoids_negative_zero() -> None:
    assert snapshot_module._format_trend_percentage(-0.004) == "0.00%"
    assert snapshot_module._format_trend_percentage(6.2) == "+6.20%"
    assert snapshot_module._format_trend_percentage(-0.8) == "-0.80%"


def test_sow_trend_summaries_are_isolated_by_source(storage: PigCycleStorage) -> None:
    for month, inventory in (("2025-12", 3961.0), ("2026-03", 3904.0), ("2026-06", 3780.0)):
        storage.save_sow_monthly(
            _sow_record(
                month=month,
                sow_inventory=inventory,
                source_url=f"https://www.stats.gov.cn/{month}.htm",
            )
        )
    for month, inventory in (("2026-05", 3900.0), ("2026-06", 3910.0)):
        storage.save_sow_monthly(
            _sow_record(
                month=month,
                sow_inventory=inventory,
                source_type=SowSourceType.MOA_REPORTED,
                source_url=f"https://www.moa.gov.cn/{month}.htm",
            )
        )

    text = build_pig_cycle_snapshot(storage)
    assert "趋势特征摘要（nbs，当前展示窗口）" in text
    assert "窗口首尾变化：-4.57%" in text
    assert "最新相邻变化：-3.18%" in text
    assert "末端连续下降变化：2 次" in text
    assert "观测间隔：符合预期间隔（实际：3/3 个月）" in text
    assert "趋势特征摘要（moa_reported，当前展示窗口）" in text
    assert "观测间隔：符合预期间隔（实际：1 个月）" in text
    assert "连续下降 2 个月" not in text
    assert "月环比" not in text
