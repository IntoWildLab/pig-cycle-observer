"""Lightweight coordination for stateful pig-cycle data fetching."""

from __future__ import annotations

from typing import Optional

import requests

from .moa_weekly import (
    DEFAULT_TIMEOUT_SECONDS,
    MoaWeeklyRecord,
    fetch_latest_weekly_increment,
    iter_recent_weekly_records,
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


def run_moa_weekly_history(
    storage: PigCycleStorage,
    *,
    target_total_records: int = 6,
    max_pages: int = 2,
    max_articles: int = 6,
    max_requests: int = 8,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> list[tuple[MoaWeeklyRecord, MoaWeeklySaveStatus]]:
    """Fetch and persist a small, stateful MOA weekly history window."""
    if target_total_records < 1:
        raise ValueError("target_total_records must be at least 1")

    collection_dates = storage.get_moa_weekly_collection_dates()
    if len(collection_dates) >= target_total_records:
        return []

    known_urls = storage.get_moa_weekly_processed_urls()
    saved: list[tuple[MoaWeeklyRecord, MoaWeeklySaveStatus]] = []
    records = iter_recent_weekly_records(
        known_urls=known_urls,
        max_pages=max_pages,
        max_articles=max_articles,
        max_requests=max_requests,
        timeout=timeout,
        session=session,
    )
    try:
        for record in records:
            status = storage.save_moa_weekly(record)
            saved.append((record, status))
            collection_dates.add(record.collection_date)
            if len(collection_dates) >= target_total_records:
                break
    finally:
        close = getattr(records, "close", None)
        if callable(close):
            close()
    return saved


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
