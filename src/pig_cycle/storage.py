"""Local SQLite schema for the isolated pig-cycle data layer."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from .moa_weekly import MoaWeeklyRecord
from .sow_monthly import SowMonthlyRecord, SowSourceType


class MoaWeeklySaveStatus(str, Enum):
    """Outcome of persisting one successfully parsed MOA weekly record."""

    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    OLDER_IGNORED = "older_ignored"
    CONFLICT = "conflict"


class SowMonthlySaveStatus(str, Enum):
    """Outcome of persisting one successfully parsed monthly sow record."""

    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    OLDER_IGNORED = "older_ignored"
    CONFLICT = "conflict"
    ORDER_UNKNOWN = "order_unknown"


class PigCycleRevisionDataError(ValueError):
    """A stored revision cannot be interpreted safely for historical replay."""

    def __init__(
        self,
        *,
        table: str,
        revision_id: object,
        field: str,
        detail: str,
    ) -> None:
        self.table = table
        self.revision_id = revision_id
        self.field = field
        super().__init__(
            f"Invalid revision evidence in {table} revision_id={revision_id} "
            f"field={field}: {detail}"
        )


@dataclass(frozen=True)
class RevisionBaselineIssue:
    record_kind: str
    business_key: str
    source_type: str | None
    source_url: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class RevisionBaselineAudit:
    weekly_current_count: int
    weekly_insertable_count: int
    weekly_inserted_count: int
    weekly_existing_count: int
    weekly_updated_at_evidence_count: int
    weekly_import_time_fallback_count: int
    sow_current_count: int
    sow_insertable_count: int
    sow_inserted_count: int
    sow_existing_count: int
    sow_updated_at_evidence_count: int
    sow_import_time_fallback_count: int
    warnings: tuple[RevisionBaselineIssue, ...]
    blockers: tuple[RevisionBaselineIssue, ...]
    ready_to_apply: bool
    complete: bool
    applied: bool
    imported_at: str


@dataclass(frozen=True)
class _RevisionBaselineEntry:
    record_kind: str
    business_key: str
    source_type: str | None
    record: MoaWeeklyRecord | SowMonthlyRecord
    payload_fingerprint: str
    observed_at: str


@dataclass(frozen=True)
class _RevisionBaselinePlan:
    audit: RevisionBaselineAudit
    entries: tuple[_RevisionBaselineEntry, ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_float(value: object, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if number == 0.0:
        number = 0.0
    return number.hex()


def _optional_canonical_float(value: object | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _canonical_float(value, field_name=field_name)


def _canonical_payload_fingerprint(payload: dict[str, object]) -> str:
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _moa_weekly_payload_fingerprint(record: MoaWeeklyRecord) -> str:
    return _canonical_payload_fingerprint(
        {
            "schema": "moa_weekly.v1",
            "collection_date": record.collection_date.isoformat(),
            "publish_date": record.publish_date.isoformat(),
            "period_label": record.period_label,
            "piglet_price": _canonical_float(
                record.piglet_price, field_name="piglet_price"
            ),
            "live_hog_price": _canonical_float(
                record.live_hog_price, field_name="live_hog_price"
            ),
            "corn_price": _canonical_float(record.corn_price, field_name="corn_price"),
            "soybean_meal_price": _optional_canonical_float(
                record.soybean_meal_price, field_name="soybean_meal_price"
            ),
            "fattening_feed_price": _optional_canonical_float(
                record.fattening_feed_price, field_name="fattening_feed_price"
            ),
        }
    )


def _sow_monthly_payload_fingerprint(record: SowMonthlyRecord) -> str:
    return _canonical_payload_fingerprint(
        {
            "schema": "sow_monthly.v1",
            "month": record.month,
            "source_type": record.source_type.value,
            "sow_inventory": _canonical_float(
                record.sow_inventory, field_name="sow_inventory"
            ),
            "mom_change": _optional_canonical_float(
                record.mom_change, field_name="mom_change"
            ),
            "yoy_change": _optional_canonical_float(
                record.yoy_change, field_name="yoy_change"
            ),
            "publish_date": (
                record.publish_date.isoformat() if record.publish_date is not None else None
            ),
        }
    )


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS moa_weekly_records (
        collection_date TEXT PRIMARY KEY,
        publish_date TEXT NOT NULL,
        period_label TEXT NOT NULL,
        piglet_price REAL NOT NULL,
        live_hog_price REAL NOT NULL,
        corn_price REAL NOT NULL,
        soybean_meal_price REAL,
        fattening_feed_price REAL,
        derived_pig_corn_ratio REAL NOT NULL,
        source_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sow_monthly_records (
        month TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK (
            source_type IN ('nbs', 'moa_reported', 'moa_estimate')
        ),
        sow_inventory REAL NOT NULL,
        mom_change REAL,
        yoy_change REAL,
        publish_date TEXT,
        source_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (month, source_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processed_sources (
        record_kind TEXT NOT NULL CHECK (
            record_kind IN ('moa_weekly', 'sow_monthly')
        ),
        source_url TEXT NOT NULL,
        business_key TEXT NOT NULL,
        source_type TEXT CHECK (
            source_type IS NULL
            OR source_type IN ('nbs', 'moa_reported', 'moa_estimate')
        ),
        publish_date TEXT,
        processed_at TEXT NOT NULL,
        PRIMARY KEY (record_kind, source_url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS moa_weekly_record_revisions (
        revision_id INTEGER PRIMARY KEY,
        collection_date TEXT NOT NULL,
        publish_date TEXT NOT NULL,
        period_label TEXT NOT NULL,
        piglet_price REAL NOT NULL,
        live_hog_price REAL NOT NULL,
        corn_price REAL NOT NULL,
        soybean_meal_price REAL,
        fattening_feed_price REAL,
        derived_pig_corn_ratio REAL NOT NULL,
        source_url TEXT NOT NULL,
        payload_fingerprint TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        save_status TEXT,
        sets_current INTEGER NOT NULL CHECK (sets_current IN (0, 1)),
        ingest_origin TEXT NOT NULL CHECK (
            ingest_origin IN ('normal_ingest', 'baseline_import')
        ),
        UNIQUE (source_url, payload_fingerprint),
        CHECK (
            (
                ingest_origin = 'baseline_import'
                AND save_status IS NULL
                AND sets_current = 1
            )
            OR
            (
                ingest_origin = 'normal_ingest'
                AND save_status IS NOT NULL
                AND (
                    (save_status IN ('inserted', 'updated') AND sets_current = 1)
                    OR
                    (
                        save_status IN ('unchanged', 'older_ignored', 'conflict')
                        AND sets_current = 0
                    )
                )
            )
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sow_monthly_record_revisions (
        revision_id INTEGER PRIMARY KEY,
        month TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK (
            source_type IN ('nbs', 'moa_reported', 'moa_estimate')
        ),
        sow_inventory REAL NOT NULL,
        mom_change REAL,
        yoy_change REAL,
        publish_date TEXT,
        source_url TEXT NOT NULL,
        payload_fingerprint TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        save_status TEXT,
        sets_current INTEGER NOT NULL CHECK (sets_current IN (0, 1)),
        ingest_origin TEXT NOT NULL CHECK (
            ingest_origin IN ('normal_ingest', 'baseline_import')
        ),
        UNIQUE (source_url, payload_fingerprint),
        CHECK (
            (
                ingest_origin = 'baseline_import'
                AND save_status IS NULL
                AND sets_current = 1
            )
            OR
            (
                ingest_origin = 'normal_ingest'
                AND save_status IS NOT NULL
                AND (
                    (save_status IN ('inserted', 'updated') AND sets_current = 1)
                    OR
                    (
                        save_status IN (
                            'unchanged', 'older_ignored', 'conflict', 'order_unknown'
                        )
                        AND sets_current = 0
                    )
                )
            )
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_moa_weekly_records_source_url
    ON moa_weekly_records (source_url)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sow_monthly_records_source_url
    ON sow_monthly_records (source_url)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_processed_sources_record_kind
    ON processed_sources (record_kind)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_processed_sources_business_key
    ON processed_sources (record_kind, business_key)
    """,
)


class PigCycleStorage:
    """Own the local SQLite schema without coupling to the V1 database layer."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize_schema(self) -> None:
        """Create the first-version pig-cycle tables and indexes atomically."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("BEGIN")
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def audit_revision_baseline(self) -> RevisionBaselineAudit:
        """Audit current rows against revision coverage without changing SQLite."""
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        database_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            imported_at = _utc_now()
            plan = self._build_revision_baseline_plan(connection, imported_at=imported_at)
            connection.rollback()
            return plan.audit
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def bootstrap_revision_baseline(self) -> RevisionBaselineAudit:
        """Append missing baseline revisions atomically after a fresh audit."""
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            imported_at = _utc_now()
            plan = self._build_revision_baseline_plan(connection, imported_at=imported_at)
            if not plan.audit.ready_to_apply:
                connection.rollback()
                return plan.audit

            weekly_inserted = 0
            sow_inserted = 0
            for entry in plan.entries:
                if entry.record_kind == "moa_weekly":
                    self._insert_moa_baseline_revision(connection, entry)
                    weekly_inserted += 1
                else:
                    self._insert_sow_baseline_revision(connection, entry)
                    sow_inserted += 1

            post_plan = self._build_revision_baseline_plan(
                connection, imported_at=imported_at
            )
            if not post_plan.audit.complete:
                raise RuntimeError("Revision baseline post-write audit is incomplete")
            connection.commit()
            return replace(
                post_plan.audit,
                weekly_insertable_count=plan.audit.weekly_insertable_count,
                weekly_inserted_count=weekly_inserted,
                sow_insertable_count=plan.audit.sow_insertable_count,
                sow_inserted_count=sow_inserted,
                applied=(weekly_inserted + sow_inserted > 0),
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _build_revision_baseline_plan(
        self,
        connection: sqlite3.Connection,
        *,
        imported_at: str,
    ) -> _RevisionBaselinePlan:
        connection.execute(
            "SELECT 1 FROM moa_weekly_record_revisions LIMIT 1"
        ).fetchone()
        connection.execute(
            "SELECT 1 FROM sow_monthly_record_revisions LIMIT 1"
        ).fetchone()
        imported_dt = self._parse_utc_timestamp(imported_at)
        if imported_dt is None:
            raise ValueError("imported_at must be a valid UTC timestamp")

        warnings: list[RevisionBaselineIssue] = []
        blockers: list[RevisionBaselineIssue] = []
        entries: list[_RevisionBaselineEntry] = []
        current_records: dict[
            tuple[str, str, str | None], MoaWeeklyRecord | SowMonthlyRecord
        ] = {}
        existing_counts = {"moa_weekly": 0, "sow_monthly": 0}
        evidence_counts = {"moa_weekly": 0, "sow_monthly": 0}
        fallback_counts = {"moa_weekly": 0, "sow_monthly": 0}

        weekly_rows = connection.execute(
            "SELECT * FROM moa_weekly_records ORDER BY collection_date"
        ).fetchall()
        sow_rows = connection.execute(
            "SELECT * FROM sow_monthly_records ORDER BY month, source_type"
        ).fetchall()

        for row in weekly_rows:
            try:
                record = self._moa_record_from_row(row)
                key = ("moa_weekly", record.collection_date.isoformat(), None)
                current_records[key] = record
                self._plan_baseline_record(
                    connection, record_kind="moa_weekly", business_key=key[1],
                    source_type=None, record=record, updated_at=row["updated_at"],
                    imported_at=imported_at, imported_dt=imported_dt,
                    warnings=warnings, blockers=blockers, entries=entries,
                    existing_counts=existing_counts, evidence_counts=evidence_counts,
                    fallback_counts=fallback_counts,
                )
            except (TypeError, ValueError, OverflowError) as exc:
                blockers.append(self._baseline_issue(
                    "moa_weekly", str(row["collection_date"]), None,
                    str(row["source_url"]), "current_record_invalid",
                    f"Current row cannot produce a valid domain fingerprint: {exc}",
                ))

        for row in sow_rows:
            try:
                record = self._sow_record_from_row(row)
                key = ("sow_monthly", record.month, record.source_type.value)
                current_records[key] = record
                self._plan_baseline_record(
                    connection, record_kind="sow_monthly", business_key=record.month,
                    source_type=record.source_type.value, record=record,
                    updated_at=row["updated_at"], imported_at=imported_at,
                    imported_dt=imported_dt, warnings=warnings, blockers=blockers,
                    entries=entries, existing_counts=existing_counts,
                    evidence_counts=evidence_counts, fallback_counts=fallback_counts,
                )
            except (TypeError, ValueError, OverflowError) as exc:
                blockers.append(self._baseline_issue(
                    "sow_monthly", str(row["month"]), str(row["source_type"]),
                    str(row["source_url"]), "current_record_invalid",
                    f"Current row cannot produce a valid domain fingerprint: {exc}",
                ))

        self._check_projected_replay(
            connection,
            current_records=current_records,
            planned_entries=entries,
            blockers=blockers,
        )
        ready = not blockers
        complete = ready and not entries
        audit = RevisionBaselineAudit(
            weekly_current_count=len(weekly_rows),
            weekly_insertable_count=sum(
                entry.record_kind == "moa_weekly" for entry in entries
            ),
            weekly_inserted_count=0,
            weekly_existing_count=existing_counts["moa_weekly"],
            weekly_updated_at_evidence_count=evidence_counts["moa_weekly"],
            weekly_import_time_fallback_count=fallback_counts["moa_weekly"],
            sow_current_count=len(sow_rows),
            sow_insertable_count=sum(
                entry.record_kind == "sow_monthly" for entry in entries
            ),
            sow_inserted_count=0,
            sow_existing_count=existing_counts["sow_monthly"],
            sow_updated_at_evidence_count=evidence_counts["sow_monthly"],
            sow_import_time_fallback_count=fallback_counts["sow_monthly"],
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            ready_to_apply=ready,
            complete=complete,
            applied=False,
            imported_at=imported_at,
        )
        return _RevisionBaselinePlan(audit=audit, entries=tuple(entries))

    def _plan_baseline_record(
        self,
        connection: sqlite3.Connection,
        *,
        record_kind: str,
        business_key: str,
        source_type: str | None,
        record: MoaWeeklyRecord | SowMonthlyRecord,
        updated_at: object,
        imported_at: str,
        imported_dt: datetime,
        warnings: list[RevisionBaselineIssue],
        blockers: list[RevisionBaselineIssue],
        entries: list[_RevisionBaselineEntry],
        existing_counts: dict[str, int],
        evidence_counts: dict[str, int],
        fallback_counts: dict[str, int],
    ) -> None:
        source_url = record.source_url
        fingerprint = (
            _moa_weekly_payload_fingerprint(record)
            if record_kind == "moa_weekly"
            else _sow_monthly_payload_fingerprint(record)
        )
        observed_at, used_fallback = self._baseline_observed_at(
            updated_at,
            imported_at=imported_at,
            imported_dt=imported_dt,
            record_kind=record_kind,
            business_key=business_key,
            source_type=source_type,
            source_url=source_url,
            warnings=warnings,
        )
        if used_fallback:
            fallback_counts[record_kind] += 1
        else:
            evidence_counts[record_kind] += 1

        self._audit_processed_source(
            connection,
            record_kind=record_kind,
            business_key=business_key,
            source_type=source_type,
            record=record,
            current_updated_at=updated_at,
            warnings=warnings,
            blockers=blockers,
        )

        table = (
            "moa_weekly_record_revisions"
            if record_kind == "moa_weekly"
            else "sow_monthly_record_revisions"
        )
        existing = connection.execute(
            f"SELECT * FROM {table} WHERE source_url = ? AND payload_fingerprint = ?",
            (source_url, fingerprint),
        ).fetchone()
        if existing is None:
            entries.append(
                _RevisionBaselineEntry(
                    record_kind=record_kind,
                    business_key=business_key,
                    source_type=source_type,
                    record=record,
                    payload_fingerprint=fingerprint,
                    observed_at=observed_at,
                )
            )
            return

        existing_record = (
            self._moa_record_from_row(existing)
            if record_kind == "moa_weekly"
            else self._sow_record_from_row(existing)
        )
        if existing_record != record:
            blockers.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    source_url,
                    "existing_revision_payload_mismatch",
                    "Existing revision identity does not match the full current payload",
                )
            )
            return
        if not self._valid_current_seed_metadata(existing):
            blockers.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    source_url,
                    "existing_revision_not_current_seed",
                    "Existing revision cannot serve as a current-state replay seed",
                )
            )
            return
        existing_counts[record_kind] += 1

    @staticmethod
    def _parse_utc_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            return None
        return parsed.astimezone(timezone.utc)

    def _baseline_observed_at(
        self,
        updated_at: object,
        *,
        imported_at: str,
        imported_dt: datetime,
        record_kind: str,
        business_key: str,
        source_type: str | None,
        source_url: str,
        warnings: list[RevisionBaselineIssue],
    ) -> tuple[str, bool]:
        parsed = self._parse_utc_timestamp(updated_at)
        if parsed is not None and parsed <= imported_dt:
            return parsed.isoformat(), False
        warnings.append(
            self._baseline_issue(
                record_kind,
                business_key,
                source_type,
                source_url,
                "import_time_fallback",
                "Current updated_at is not usable UTC evidence; import time will be used",
            )
        )
        return imported_at, True

    def _audit_processed_source(
        self,
        connection: sqlite3.Connection,
        *,
        record_kind: str,
        business_key: str,
        source_type: str | None,
        record: MoaWeeklyRecord | SowMonthlyRecord,
        current_updated_at: object,
        warnings: list[RevisionBaselineIssue],
        blockers: list[RevisionBaselineIssue],
    ) -> None:
        processed = connection.execute(
            """
            SELECT * FROM processed_sources
            WHERE record_kind = ? AND source_url = ?
            """,
            (record_kind, record.source_url),
        ).fetchone()
        if processed is None:
            warnings.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_source_missing",
                    "Current source URL is absent from processed_sources",
                )
            )
            return

        if processed["business_key"] != business_key:
            blockers.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_business_key_mismatch",
                    "Processed source URL maps to a different business key",
                )
            )
        if processed["source_type"] != source_type:
            blockers.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_source_type_mismatch",
                    "Processed source URL maps to a different source type",
                )
            )

        current_publish_date = (
            record.publish_date.isoformat() if record.publish_date is not None else None
        )
        if processed["publish_date"] != current_publish_date:
            warnings.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_publish_date_mismatch",
                    "Processed source publish_date differs from the current payload",
                )
            )

        processed_dt = self._parse_utc_timestamp(processed["processed_at"])
        if processed_dt is None:
            warnings.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_at_invalid",
                    "processed_at is not a valid UTC timestamp",
                )
            )
            return
        updated_dt = self._parse_utc_timestamp(current_updated_at)
        if updated_dt is not None and processed_dt > updated_dt:
            warnings.append(
                self._baseline_issue(
                    record_kind,
                    business_key,
                    source_type,
                    record.source_url,
                    "processed_after_current_updated_at",
                    "processed_at is later than current updated_at",
                )
            )

    @staticmethod
    def _valid_current_seed_metadata(row: sqlite3.Row) -> bool:
        if row["sets_current"] != 1:
            return False
        if row["ingest_origin"] == "baseline_import":
            return row["save_status"] is None
        return row["ingest_origin"] == "normal_ingest" and row["save_status"] in (
            "inserted",
            "updated",
        )

    def _check_projected_replay(
        self,
        connection: sqlite3.Connection,
        *,
        current_records: dict[
            tuple[str, str, str | None], MoaWeeklyRecord | SowMonthlyRecord
        ],
        planned_entries: list[_RevisionBaselineEntry],
        blockers: list[RevisionBaselineIssue],
    ) -> None:
        planned_by_key = {
            (entry.record_kind, entry.business_key, entry.source_type): entry
            for entry in planned_entries
        }
        for key, current in current_records.items():
            record_kind, business_key, source_type = key
            table = (
                "moa_weekly_record_revisions"
                if record_kind == "moa_weekly"
                else "sow_monthly_record_revisions"
            )
            key_column = "collection_date" if record_kind == "moa_weekly" else "month"
            source_filter = "" if source_type is None else " AND source_type = ?"
            parameters: tuple[object, ...] = (
                (business_key,)
                if source_type is None
                else (business_key, source_type)
            )
            rows = connection.execute(
                f"""
                SELECT * FROM {table}
                WHERE {key_column} = ?{source_filter} AND sets_current = 1
                ORDER BY observed_at ASC, revision_id ASC
                """,
                parameters,
            ).fetchall()
            candidates: list[tuple[datetime, int, MoaWeeklyRecord | SowMonthlyRecord]] = []
            for row in rows:
                observed = self._parse_utc_timestamp(row["observed_at"])
                if observed is None:
                    blockers.append(
                        self._baseline_issue(
                            record_kind,
                            business_key,
                            source_type,
                            current.source_url,
                            "revision_observed_at_invalid",
                            "A current-setting revision has an invalid observed_at",
                        )
                    )
                    continue
                restored = (
                    self._moa_record_from_row(row)
                    if record_kind == "moa_weekly"
                    else self._sow_record_from_row(row)
                )
                candidates.append((observed, int(row["revision_id"]), restored))

            planned = planned_by_key.get(key)
            if planned is not None:
                observed = self._parse_utc_timestamp(planned.observed_at)
                assert observed is not None
                candidates.append((observed, 2**63 - 1, planned.record))
            if candidates and max(candidates, key=lambda item: (item[0], item[1]))[2] != current:
                blockers.append(
                    self._baseline_issue(
                        record_kind,
                        business_key,
                        source_type,
                        current.source_url,
                        "replay_current_mismatch",
                        "Final current-setting revision does not match the current table",
                    )
                )

    @staticmethod
    def _baseline_issue(
        record_kind: str,
        business_key: str,
        source_type: str | None,
        source_url: str,
        reason_code: str,
        detail: str,
    ) -> RevisionBaselineIssue:
        return RevisionBaselineIssue(
            record_kind=record_kind,
            business_key=business_key,
            source_type=source_type,
            source_url=source_url,
            reason_code=reason_code,
            detail=detail,
        )

    @staticmethod
    def _insert_moa_baseline_revision(
        connection: sqlite3.Connection, entry: _RevisionBaselineEntry
    ) -> None:
        record = entry.record
        assert isinstance(record, MoaWeeklyRecord)
        connection.execute(
            """
            INSERT INTO moa_weekly_record_revisions (
                collection_date, publish_date, period_label, piglet_price,
                live_hog_price, corn_price, soybean_meal_price,
                fattening_feed_price, derived_pig_corn_ratio, source_url,
                payload_fingerprint, observed_at, save_status, sets_current,
                ingest_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, 'baseline_import')
            """,
            (
                record.collection_date.isoformat(),
                record.publish_date.isoformat(),
                record.period_label,
                record.piglet_price,
                record.live_hog_price,
                record.corn_price,
                record.soybean_meal_price,
                record.fattening_feed_price,
                record.derived_pig_corn_ratio,
                record.source_url,
                entry.payload_fingerprint,
                entry.observed_at,
            ),
        )

    @staticmethod
    def _insert_sow_baseline_revision(
        connection: sqlite3.Connection, entry: _RevisionBaselineEntry
    ) -> None:
        record = entry.record
        assert isinstance(record, SowMonthlyRecord)
        connection.execute(
            """
            INSERT INTO sow_monthly_record_revisions (
                month, source_type, sow_inventory, mom_change, yoy_change,
                publish_date, source_url, payload_fingerprint, observed_at,
                save_status, sets_current, ingest_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, 'baseline_import')
            """,
            (
                record.month,
                record.source_type.value,
                record.sow_inventory,
                record.mom_change,
                record.yoy_change,
                record.publish_date.isoformat() if record.publish_date is not None else None,
                record.source_url,
                entry.payload_fingerprint,
                entry.observed_at,
            ),
        )

    def save_moa_weekly(self, record: MoaWeeklyRecord) -> MoaWeeklySaveStatus:
        """Persist one MOA weekly record and remember its source atomically."""
        now = _utc_now()
        collection_date = record.collection_date.isoformat()
        publish_date = record.publish_date.isoformat()
        payload_fingerprint = _moa_weekly_payload_fingerprint(record)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            processed = connection.execute(
                """
                SELECT business_key
                FROM processed_sources
                WHERE record_kind = 'moa_weekly' AND source_url = ?
                """,
                (record.source_url,),
            ).fetchone()
            if processed is not None and processed["business_key"] != collection_date:
                raise ValueError(
                    "MOA weekly source URL is already mapped to a different collection_date"
                )
            if processed is None:
                connection.execute(
                    """
                    INSERT INTO processed_sources (
                        record_kind, source_url, business_key, source_type,
                        publish_date, processed_at
                    ) VALUES ('moa_weekly', ?, ?, NULL, ?, ?)
                    """,
                    (record.source_url, collection_date, publish_date, now),
                )

            current = connection.execute(
                """
                SELECT *
                FROM moa_weekly_records
                WHERE collection_date = ?
                """,
                (collection_date,),
            ).fetchone()
            if current is None:
                connection.execute(
                    """
                    INSERT INTO moa_weekly_records (
                        collection_date, publish_date, period_label, piglet_price,
                        live_hog_price, corn_price, soybean_meal_price,
                        fattening_feed_price, derived_pig_corn_ratio, source_url,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        collection_date,
                        publish_date,
                        record.period_label,
                        record.piglet_price,
                        record.live_hog_price,
                        record.corn_price,
                        record.soybean_meal_price,
                        record.fattening_feed_price,
                        record.derived_pig_corn_ratio,
                        record.source_url,
                        now,
                        now,
                    ),
                )
                status = MoaWeeklySaveStatus.INSERTED
            elif publish_date > current["publish_date"]:
                connection.execute(
                    """
                    UPDATE moa_weekly_records
                    SET publish_date = ?, period_label = ?, piglet_price = ?,
                        live_hog_price = ?, corn_price = ?, soybean_meal_price = ?,
                        fattening_feed_price = ?, derived_pig_corn_ratio = ?,
                        source_url = ?, updated_at = ?
                    WHERE collection_date = ?
                    """,
                    (
                        publish_date,
                        record.period_label,
                        record.piglet_price,
                        record.live_hog_price,
                        record.corn_price,
                        record.soybean_meal_price,
                        record.fattening_feed_price,
                        record.derived_pig_corn_ratio,
                        record.source_url,
                        now,
                        collection_date,
                    ),
                )
                status = MoaWeeklySaveStatus.UPDATED
            elif publish_date < current["publish_date"]:
                status = MoaWeeklySaveStatus.OLDER_IGNORED
            elif self._moa_business_content(record) == self._stored_moa_business_content(current):
                status = MoaWeeklySaveStatus.UNCHANGED
            else:
                status = MoaWeeklySaveStatus.CONFLICT

            connection.execute(
                """
                INSERT INTO moa_weekly_record_revisions (
                    collection_date, publish_date, period_label, piglet_price,
                    live_hog_price, corn_price, soybean_meal_price,
                    fattening_feed_price, derived_pig_corn_ratio, source_url,
                    payload_fingerprint, observed_at, save_status, sets_current,
                    ingest_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal_ingest')
                ON CONFLICT(source_url, payload_fingerprint) DO NOTHING
                """,
                (
                    collection_date,
                    publish_date,
                    record.period_label,
                    record.piglet_price,
                    record.live_hog_price,
                    record.corn_price,
                    record.soybean_meal_price,
                    record.fattening_feed_price,
                    record.derived_pig_corn_ratio,
                    record.source_url,
                    payload_fingerprint,
                    now,
                    status.value,
                    int(
                        status
                        in (MoaWeeklySaveStatus.INSERTED, MoaWeeklySaveStatus.UPDATED)
                    ),
                ),
            )

            connection.commit()
            return status
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _moa_business_content(record: MoaWeeklyRecord) -> tuple[object, ...]:
        return (
            record.period_label,
            record.piglet_price,
            record.live_hog_price,
            record.corn_price,
            record.soybean_meal_price,
            record.fattening_feed_price,
            record.derived_pig_corn_ratio,
        )

    @staticmethod
    def _stored_moa_business_content(row: sqlite3.Row) -> tuple[object, ...]:
        return (
            row["period_label"],
            row["piglet_price"],
            row["live_hog_price"],
            row["corn_price"],
            row["soybean_meal_price"],
            row["fattening_feed_price"],
            row["derived_pig_corn_ratio"],
        )

    def save_sow_monthly(self, record: SowMonthlyRecord) -> SowMonthlySaveStatus:
        """Persist one monthly sow record and remember its source atomically."""
        now = _utc_now()
        source_type = record.source_type.value
        publish_date = record.publish_date.isoformat() if record.publish_date is not None else None
        payload_fingerprint = _sow_monthly_payload_fingerprint(record)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            processed = connection.execute(
                """
                SELECT business_key, source_type
                FROM processed_sources
                WHERE record_kind = 'sow_monthly' AND source_url = ?
                """,
                (record.source_url,),
            ).fetchone()
            if processed is not None and (
                processed["business_key"] != record.month
                or processed["source_type"] != source_type
            ):
                raise ValueError(
                    "Sow monthly source URL is already mapped to a different month or source_type"
                )
            if processed is None:
                connection.execute(
                    """
                    INSERT INTO processed_sources (
                        record_kind, source_url, business_key, source_type,
                        publish_date, processed_at
                    ) VALUES ('sow_monthly', ?, ?, ?, ?, ?)
                    """,
                    (record.source_url, record.month, source_type, publish_date, now),
                )

            current = connection.execute(
                """
                SELECT *
                FROM sow_monthly_records
                WHERE month = ? AND source_type = ?
                """,
                (record.month, source_type),
            ).fetchone()
            if current is None:
                connection.execute(
                    """
                    INSERT INTO sow_monthly_records (
                        month, source_type, sow_inventory, mom_change, yoy_change,
                        publish_date, source_url, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.month,
                        source_type,
                        record.sow_inventory,
                        record.mom_change,
                        record.yoy_change,
                        publish_date,
                        record.source_url,
                        now,
                        now,
                    ),
                )
                status = SowMonthlySaveStatus.INSERTED
            else:
                current_publish_date = current["publish_date"]
                content_matches = self._sow_business_content(record) == self._stored_sow_business_content(current)
                if publish_date is None or current_publish_date is None:
                    status = (
                        SowMonthlySaveStatus.UNCHANGED
                        if content_matches
                        else SowMonthlySaveStatus.ORDER_UNKNOWN
                    )
                elif publish_date > current_publish_date:
                    connection.execute(
                        """
                        UPDATE sow_monthly_records
                        SET sow_inventory = ?, mom_change = ?, yoy_change = ?,
                            publish_date = ?, source_url = ?, updated_at = ?
                        WHERE month = ? AND source_type = ?
                        """,
                        (
                            record.sow_inventory,
                            record.mom_change,
                            record.yoy_change,
                            publish_date,
                            record.source_url,
                            now,
                            record.month,
                            source_type,
                        ),
                    )
                    status = SowMonthlySaveStatus.UPDATED
                elif publish_date < current_publish_date:
                    status = SowMonthlySaveStatus.OLDER_IGNORED
                elif content_matches:
                    status = SowMonthlySaveStatus.UNCHANGED
                else:
                    status = SowMonthlySaveStatus.CONFLICT

            connection.execute(
                """
                INSERT INTO sow_monthly_record_revisions (
                    month, source_type, sow_inventory, mom_change, yoy_change,
                    publish_date, source_url, payload_fingerprint, observed_at,
                    save_status, sets_current, ingest_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal_ingest')
                ON CONFLICT(source_url, payload_fingerprint) DO NOTHING
                """,
                (
                    record.month,
                    source_type,
                    record.sow_inventory,
                    record.mom_change,
                    record.yoy_change,
                    publish_date,
                    record.source_url,
                    payload_fingerprint,
                    now,
                    status.value,
                    int(
                        status
                        in (SowMonthlySaveStatus.INSERTED, SowMonthlySaveStatus.UPDATED)
                    ),
                ),
            )

            connection.commit()
            return status
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _sow_business_content(record: SowMonthlyRecord) -> tuple[object, ...]:
        return (record.sow_inventory, record.mom_change, record.yoy_change)

    @staticmethod
    def _stored_sow_business_content(row: sqlite3.Row) -> tuple[object, ...]:
        return (row["sow_inventory"], row["mom_change"], row["yoy_change"])

    def get_moa_weekly_processed_urls(self) -> set[str]:
        """Return every successfully processed MOA weekly source URL."""
        return self._get_processed_source_urls("moa_weekly")

    def get_sow_monthly_processed_urls(self) -> set[str]:
        """Return every successfully processed monthly sow source URL."""
        return self._get_processed_source_urls("sow_monthly")

    def get_moa_weekly_collection_dates(self) -> set[date]:
        """Return the collection dates of current MOA weekly records."""
        rows = self._read_rows("SELECT collection_date FROM moa_weekly_records")
        return {date.fromisoformat(row["collection_date"]) for row in rows}

    def get_sow_monthly_business_keys(self) -> set[tuple[str, SowSourceType]]:
        """Return every current monthly sow business key."""
        rows = self._read_rows("SELECT month, source_type FROM sow_monthly_records")
        return {(row["month"], SowSourceType(row["source_type"])) for row in rows}

    def get_record_counts(self) -> dict[str, int]:
        """Return current row counts for the three pig-cycle tables."""
        rows = self._read_rows(
            """
            SELECT
                (SELECT COUNT(*) FROM moa_weekly_records) AS moa_weekly,
                (SELECT COUNT(*) FROM sow_monthly_records) AS sow_monthly,
                (SELECT COUNT(*) FROM processed_sources) AS processed_sources
            """
        )
        row = rows[0]
        return {
            "moa_weekly": int(row["moa_weekly"]),
            "sow_monthly": int(row["sow_monthly"]),
            "processed_sources": int(row["processed_sources"]),
        }

    def get_latest_moa_weekly_record(self) -> MoaWeeklyRecord | None:
        """Return the record with the latest collection date, if present."""
        rows = self._read_rows(
            """
            SELECT collection_date, publish_date, period_label, piglet_price,
                   live_hog_price, corn_price, soybean_meal_price,
                   fattening_feed_price, derived_pig_corn_ratio, source_url
            FROM moa_weekly_records
            ORDER BY collection_date DESC
            LIMIT 1
            """
        )
        if not rows:
            return None
        return self._moa_record_from_row(rows[0])

    def get_moa_weekly_history(
        self,
        *,
        limit: int | None = None,
    ) -> list[MoaWeeklyRecord]:
        """Return current MOA weekly records in ascending collection-date order."""
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise TypeError("limit must be a positive integer or None")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")

        columns = """
            collection_date, publish_date, period_label, piglet_price,
            live_hog_price, corn_price, soybean_meal_price,
            fattening_feed_price, derived_pig_corn_ratio, source_url
        """
        if limit is None:
            rows = self._read_rows(
                f"""
                SELECT {columns}
                FROM moa_weekly_records
                ORDER BY collection_date ASC
                """
            )
        else:
            rows = self._read_rows(
                f"""
                SELECT {columns}
                FROM (
                    SELECT {columns}
                    FROM moa_weekly_records
                    ORDER BY collection_date DESC
                    LIMIT ?
                )
                ORDER BY collection_date ASC
                """,
                (limit,),
            )
        return [self._moa_record_from_row(row) for row in rows]

    def get_moa_weekly_records_as_of_system(
        self,
        cutoff: datetime,
    ) -> list[MoaWeeklyRecord]:
        """Replay MOA revisions visible to the system through ``cutoff``."""
        rows = self._revision_rows_as_of_system(
            table="moa_weekly_record_revisions",
            cutoff=cutoff,
            key_fields=("collection_date",),
            non_current_statuses=("unchanged", "older_ignored", "conflict"),
        )
        return [self._moa_record_from_row(row) for row in rows]

    @staticmethod
    def _moa_record_from_row(row: sqlite3.Row) -> MoaWeeklyRecord:
        return MoaWeeklyRecord(
            collection_date=date.fromisoformat(row["collection_date"]),
            publish_date=date.fromisoformat(row["publish_date"]),
            period_label=row["period_label"],
            piglet_price=row["piglet_price"],
            live_hog_price=row["live_hog_price"],
            corn_price=row["corn_price"],
            soybean_meal_price=row["soybean_meal_price"],
            fattening_feed_price=row["fattening_feed_price"],
            derived_pig_corn_ratio=row["derived_pig_corn_ratio"],
            source_url=row["source_url"],
        )

    def get_latest_sow_monthly_records_by_source(self) -> list[SowMonthlyRecord]:
        """Return each source type's latest current monthly sow record."""
        rows = self._read_rows(
            """
            SELECT current.month, current.sow_inventory, current.mom_change,
                   current.yoy_change, current.publish_date,
                   current.source_type, current.source_url
            FROM sow_monthly_records AS current
            WHERE current.month = (
                SELECT MAX(candidate.month)
                FROM sow_monthly_records AS candidate
                WHERE candidate.source_type = current.source_type
            )
            ORDER BY current.source_type ASC
            """
        )
        return [self._sow_record_from_row(row) for row in rows]

    def get_sow_monthly_history(
        self,
        *,
        source_type: SowSourceType,
        limit: int | None = None,
    ) -> list[SowMonthlyRecord]:
        """Return current records for one source type in ascending month order."""
        if not isinstance(source_type, SowSourceType):
            raise TypeError("source_type must be a SowSourceType")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise TypeError("limit must be a positive integer or None")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")

        columns = """
            month, sow_inventory, mom_change, yoy_change,
            publish_date, source_type, source_url
        """
        if limit is None:
            rows = self._read_rows(
                f"""
                SELECT {columns}
                FROM sow_monthly_records
                WHERE source_type = ?
                ORDER BY month ASC
                """,
                (source_type.value,),
            )
        else:
            rows = self._read_rows(
                f"""
                SELECT {columns}
                FROM (
                    SELECT {columns}
                    FROM sow_monthly_records
                    WHERE source_type = ?
                    ORDER BY month DESC
                    LIMIT ?
                )
                ORDER BY month ASC
                """,
                (source_type.value, limit),
            )
        return [self._sow_record_from_row(row) for row in rows]

    def get_sow_monthly_records_as_of_system(
        self,
        cutoff: datetime,
    ) -> list[SowMonthlyRecord]:
        """Replay sow revisions visible to the system through ``cutoff``."""
        rows = self._revision_rows_as_of_system(
            table="sow_monthly_record_revisions",
            cutoff=cutoff,
            key_fields=("month", "source_type"),
            non_current_statuses=(
                "unchanged",
                "older_ignored",
                "conflict",
                "order_unknown",
            ),
        )
        return [self._sow_record_from_row(row) for row in rows]

    @staticmethod
    def _sow_record_from_row(row: sqlite3.Row) -> SowMonthlyRecord:
        return SowMonthlyRecord(
            month=row["month"],
            sow_inventory=row["sow_inventory"],
            mom_change=row["mom_change"],
            yoy_change=row["yoy_change"],
            publish_date=(
                date.fromisoformat(row["publish_date"])
                if row["publish_date"] is not None
                else None
            ),
            source_type=SowSourceType(row["source_type"]),
            source_url=row["source_url"],
        )

    def _get_processed_source_urls(self, record_kind: str) -> set[str]:
        rows = self._read_rows(
            "SELECT source_url FROM processed_sources WHERE record_kind = ?",
            (record_kind,),
        )
        return {row["source_url"] for row in rows}

    @staticmethod
    def _normalize_system_cutoff(cutoff: datetime) -> datetime:
        if not isinstance(cutoff, datetime):
            raise TypeError("cutoff must be a timezone-aware datetime")
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must be timezone-aware")
        return cutoff.astimezone(timezone.utc)

    def _revision_rows_as_of_system(
        self,
        *,
        table: str,
        cutoff: datetime,
        key_fields: tuple[str, ...],
        non_current_statuses: tuple[str, ...],
    ) -> list[sqlite3.Row]:
        normalized_cutoff = self._normalize_system_cutoff(cutoff)
        rows = self._read_rows(f"SELECT * FROM {table} ORDER BY revision_id ASC")
        effective: dict[tuple[object, ...], tuple[datetime, int, sqlite3.Row]] = {}

        for row in rows:
            revision_id = row["revision_id"]
            observed_at = self._parse_utc_timestamp(row["observed_at"])
            if observed_at is None:
                raise PigCycleRevisionDataError(
                    table=table,
                    revision_id=revision_id,
                    field="observed_at",
                    detail="must be a parseable timezone-aware UTC timestamp",
                )
            self._validate_revision_metadata(
                row,
                table=table,
                non_current_statuses=non_current_statuses,
            )
            if observed_at > normalized_cutoff or row["sets_current"] == 0:
                continue

            key = tuple(row[field] for field in key_fields)
            candidate = (observed_at, int(revision_id), row)
            current = effective.get(key)
            if current is None or candidate[:2] > current[:2]:
                effective[key] = candidate

        return [
            entry[2]
            for _, entry in sorted(
                effective.items(),
                key=lambda item: item[0],
            )
        ]

    @staticmethod
    def _validate_revision_metadata(
        row: sqlite3.Row,
        *,
        table: str,
        non_current_statuses: tuple[str, ...],
    ) -> None:
        revision_id = row["revision_id"]
        origin = row["ingest_origin"]
        status = row["save_status"]
        sets_current = row["sets_current"]

        if sets_current not in (0, 1):
            raise PigCycleRevisionDataError(
                table=table,
                revision_id=revision_id,
                field="sets_current",
                detail="must be 0 or 1",
            )
        if origin == "baseline_import":
            valid = status is None and sets_current == 1
        elif origin == "normal_ingest":
            valid = (
                status in ("inserted", "updated") and sets_current == 1
            ) or (status in non_current_statuses and sets_current == 0)
        else:
            raise PigCycleRevisionDataError(
                table=table,
                revision_id=revision_id,
                field="ingest_origin",
                detail="is not a supported revision origin",
            )
        if not valid:
            raise PigCycleRevisionDataError(
                table=table,
                revision_id=revision_id,
                field="save_status/sets_current",
                detail="combination is inconsistent with ingest_origin",
            )

    def _read_rows(
        self,
        query: str,
        parameters: tuple[object, ...] = (),
    ) -> list[sqlite3.Row]:
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        database_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
