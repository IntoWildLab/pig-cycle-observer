"""Lightweight coordination for stateful pig-cycle data fetching."""

from __future__ import annotations

from typing import Optional

import requests

from .moa_weekly import (
    DEFAULT_TIMEOUT_SECONDS,
    MoaWeeklyRecord,
    fetch_latest_weekly_increment,
)
from .storage import MoaWeeklySaveStatus, PigCycleStorage


def run_moa_weekly_increment(
    storage: PigCycleStorage,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> tuple[MoaWeeklyRecord, MoaWeeklySaveStatus] | None:
    """Fetch and persist at most one MOA weekly record not seen by URL."""
    known_urls = storage.get_moa_weekly_processed_urls()
    record = fetch_latest_weekly_increment(
        known_urls=known_urls,
        known_dates=None,
        timeout=timeout,
        session=session,
    )
    if record is None:
        return None
    return record, storage.save_moa_weekly(record)
