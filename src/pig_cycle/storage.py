"""Local SQLite schema for the isolated pig-cycle data layer."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    def save_moa_weekly(self, record: MoaWeeklyRecord) -> MoaWeeklySaveStatus:
        """Persist one MOA weekly record and remember its source atomically."""
        now = _utc_now()
        collection_date = record.collection_date.isoformat()
        publish_date = record.publish_date.isoformat()
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
        row = rows[0]
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
        return [
            SowMonthlyRecord(
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
            for row in rows
        ]

    def _get_processed_source_urls(self, record_kind: str) -> set[str]:
        rows = self._read_rows(
            "SELECT source_url FROM processed_sources WHERE record_kind = ?",
            (record_kind,),
        )
        return {row["source_url"] for row in rows}

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
