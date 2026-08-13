"""Lightweight coordination for stateful pig-cycle data fetching."""

from __future__ import annotations

from typing import Optional

import requests

from .moa_weekly import (
    DEFAULT_TIMEOUT_SECONDS,
    MoaWeeklyRecord,
    fetch_latest_weekly_increment,
)
from .sow_monthly import SowMonthlyRecord
from .sow_official import (
    DEFAULT_TIMEOUT_SECONDS as SOW_DEFAULT_TIMEOUT_SECONDS,
    fetch_sow_record_from_official_url,
)
from .storage import (
    MoaWeeklySaveStatus,
    PigCycleStorage,
    SowMonthlySaveStatus,
)


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


def run_sow_monthly_official_url(
    storage: PigCycleStorage,
    url: str,
    *,
    timeout: float = SOW_DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> tuple[SowMonthlyRecord, SowMonthlySaveStatus] | None:
    """Fetch and persist one explicit official sow URL unless already processed."""
    known_urls = storage.get_sow_monthly_processed_urls()
    if url in known_urls:
        return None
    record = fetch_sow_record_from_official_url(
        url,
        timeout=timeout,
        session=session,
    )
    return record, storage.save_sow_monthly(record)
