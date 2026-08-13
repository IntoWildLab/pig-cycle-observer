"""Plain-text snapshot of locally persisted pig-cycle data."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Sequence

from .sow_monthly import SowMonthlyRecord, SowSourceType
from .storage import PigCycleStorage


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "暂无"


def _format_price(value: float | None) -> str:
    return f"{value:.2f} 元/公斤" if value is not None else "暂无"


def _format_change(value: float | None) -> str:
    return f"{value:g}%" if value is not None else "暂无"


def _format_sow_record(record: SowMonthlyRecord) -> list[str]:
    return [
        f"- 来源类型：{record.source_type.value}",
        f"  - 数据月份：{record.month}",
        f"  - 存栏：{record.sow_inventory:g} 万头",
        f"  - 官方环比：{_format_change(record.mom_change)}",
        f"  - 官方同比：{_format_change(record.yoy_change)}",
        f"  - 发布日期：{_format_date(record.publish_date)}",
        f"  - 来源 URL：{record.source_url}",
    ]


def _format_sow_history(records: list[SowMonthlyRecord]) -> list[str]:
    lines: list[str] = []
    for index, record in enumerate(records):
        lines.append(f"- {record.month}：{record.sow_inventory:g} 万头")
        if index > 0:
            previous = records[index - 1]
            absolute_change = record.sow_inventory - previous.sow_inventory
            if previous.sow_inventory == 0:
                percentage = "暂无"
            else:
                percentage = f"{absolute_change / previous.sow_inventory * 100:+.2f}%"
            lines.append(
                f"  - 较上一条记录：{absolute_change:+g} 万头，{percentage}"
            )
        lines.extend(
            [
                f"  - 官方环比：{_format_change(record.mom_change)}",
                f"  - 官方同比：{_format_change(record.yoy_change)}",
                f"  - 发布日期：{_format_date(record.publish_date)}",
                f"  - 来源 URL：{record.source_url}",
            ]
        )
    lines.append(f"所示记录方向：{_describe_sow_direction(records)}")
    return lines


def _describe_sow_direction(records: list[SowMonthlyRecord]) -> str:
    if len(records) < 2:
        return "记录不足"
    changes = [
        current.sow_inventory - previous.sow_inventory
        for previous, current in zip(records, records[1:])
    ]
    if all(change < 0 for change in changes):
        return "连续下降"
    if all(change > 0 for change in changes):
        return "连续上升"
    if all(change == 0 for change in changes):
        return "持平"
    return "混合"


def build_pig_cycle_snapshot(storage: PigCycleStorage) -> str:
    """Build a read-only Chinese snapshot from the local SQLite database."""
    counts = storage.get_record_counts()
    weekly_urls = storage.get_moa_weekly_processed_urls()
    sow_urls = storage.get_sow_monthly_processed_urls()
    weekly = storage.get_latest_moa_weekly_record()
    sow_records = storage.get_latest_sow_monthly_records_by_source()

    lines = [
        "猪周期 V2 数据快照",
        "",
        "数据库概况",
        f"- MOA 周度记录：{counts['moa_weekly']}",
        f"- 母猪月度记录：{counts['sow_monthly']}",
        f"- 已处理来源：{counts['processed_sources']}",
        f"  - MOA 周度：{len(weekly_urls)}",
        f"  - 母猪月度：{len(sow_urls)}",
        "",
        "最新 MOA 周度",
    ]
    if weekly is None:
        lines.append("- 暂无周度数据")
    else:
        lines.extend(
            [
                f"- 数据日期：{weekly.collection_date.isoformat()}",
                f"- 发布日期：{weekly.publish_date.isoformat()}",
                f"- 周期标签：{weekly.period_label}",
                f"- 仔猪：{_format_price(weekly.piglet_price)}",
                f"- 生猪：{_format_price(weekly.live_hog_price)}",
                f"- 玉米：{_format_price(weekly.corn_price)}",
                f"- 豆粕：{_format_price(weekly.soybean_meal_price)}",
                f"- 育肥猪配合饲料：{_format_price(weekly.fattening_feed_price)}",
                f"- 派生猪粮比：{weekly.derived_pig_corn_ratio:.2f}",
                f"- 来源：{weekly.source_url}",
            ]
        )

    lines.extend(["", "能繁母猪月度最新数据（按来源）"])
    if not sow_records:
        lines.append("- 暂无母猪数据")
    else:
        for record in sow_records:
            lines.extend(_format_sow_record(record))

    source_types = sorted(
        {source_type for _, source_type in storage.get_sow_monthly_business_keys()},
        key=lambda source_type: source_type.value,
    )
    if not source_types:
        lines.extend(["", "能繁母猪历史", "- 暂无母猪历史数据"])
    else:
        for source_type in source_types:
            history = storage.get_sow_monthly_history(
                source_type=source_type,
                limit=6,
            )
            lines.extend(["", f"能繁母猪历史（{source_type.value}）"])
            lines.extend(_format_sow_history(history))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Print a local pig-cycle snapshot for one SQLite database."""
    parser = argparse.ArgumentParser(description="显示本地猪周期 V2 数据快照")
    parser.add_argument("database", help="猪周期 SQLite 数据库路径")
    args = parser.parse_args(argv)
    print(build_pig_cycle_snapshot(PigCycleStorage(args.database)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
