"""Build the safe, user-facing summary appended to aggregate run reports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional


RUN_SOURCE_ENV = "PIG_CYCLE_RUN_SOURCE"
_RUN_SOURCE_LABELS = {
    "local": "本地运行",
    "scheduled": "GitHub 定时运行",
    "manual": "GitHub 手动运行",
}


@dataclass(frozen=True)
class RunSummary:
    planned_count: int
    success_count: int
    failed_items: tuple[str, ...]
    elapsed_seconds: float
    data_dates: tuple[str, ...] = ()
    run_source: Optional[str] = None

    @property
    def failed_count(self) -> int:
        return max(0, self.planned_count - self.success_count)


def resolve_run_source(value: Optional[str] = None) -> str:
    """Return a fixed display label without echoing arbitrary environment data."""
    normalized = (value if value is not None else os.getenv(RUN_SOURCE_ENV, "local"))
    normalized = str(normalized or "local").strip().lower()
    return _RUN_SOURCE_LABELS.get(normalized, _RUN_SOURCE_LABELS["local"])


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed seconds as compact, readable Chinese text."""
    total_seconds = max(0, int(round(float(seconds or 0))))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"
    if minutes:
        return f"{minutes} 分 {seconds_part} 秒" if seconds_part else f"{minutes} 分"
    return f"{seconds_part} 秒"


def collect_data_dates(results: Iterable[object]) -> tuple[str, ...]:
    """Collect actual dates exposed by successful analysis market snapshots."""
    dates: list[str] = []
    for result in results:
        snapshot = getattr(result, "market_snapshot", None)
        if not isinstance(snapshot, dict):
            continue
        # Only an explicitly sourced completed daily-bar date is reliable here.
        value = str(snapshot.get("trading_date") or "").strip()
        if value and value.lower() not in {"未知", "unknown", "n/a", "none"}:
            dates.append(value)
    return tuple(dict.fromkeys(dates))


def render_run_summary(summary: RunSummary) -> str:
    """Render Markdown that remains readable in plain-text and HTML email paths."""
    lines = ["## 本次运行摘要", ""]
    if summary.data_dates:
        lines.append(f"- 数据日期：{'、'.join(summary.data_dates)}")
    lines.extend(
        [
            f"- 计划分析：{summary.planned_count} 个标的",
            f"- 成功完成：{summary.success_count} 个标的",
            f"- 分析失败：{summary.failed_count} 个标的",
        ]
    )
    if summary.failed_count and summary.failed_items:
        lines.append(f"- 失败标的：{'、'.join(summary.failed_items)}")
    lines.extend(
        [
            f"- 总运行耗时：{format_elapsed_time(summary.elapsed_seconds)}",
            f"- 运行来源：{resolve_run_source(summary.run_source)}",
        ]
    )
    return "\n".join(lines)


def append_run_summary(report: str, summary: Optional[RunSummary]) -> str:
    if summary is None:
        return report
    return f"{report.rstrip()}\n\n---\n\n{render_run_summary(summary)}\n"
