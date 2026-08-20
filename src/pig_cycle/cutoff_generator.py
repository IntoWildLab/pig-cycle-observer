"""Deterministic calibration cutoff generation."""

from datetime import date, datetime, timedelta, timezone


_UTC_PLUS_EIGHT = timezone(timedelta(hours=8))


def generate_month_end_cutoffs(
    start_month: date,
    end_month: date,
) -> tuple[datetime, ...]:
    """Generate inclusive month-end cutoffs in fixed UTC+08:00."""

    _validate_month_start(start_month, "start_month")
    _validate_month_start(end_month, "end_month")
    if start_month > end_month:
        raise ValueError("start_month must not be after end_month")

    cutoffs: list[datetime] = []
    current_month = start_month
    while current_month <= end_month:
        next_month = _next_month(current_month)
        month_end = next_month - timedelta(days=1)
        cutoffs.append(
            datetime(
                month_end.year,
                month_end.month,
                month_end.day,
                23,
                59,
                59,
                999999,
                tzinfo=_UTC_PLUS_EIGHT,
            )
        )
        current_month = next_month

    return tuple(cutoffs)


def _validate_month_start(value: date, parameter_name: str) -> None:
    if type(value) is not date or value.day != 1:
        raise ValueError(
            f"{parameter_name} must be a date on the first day of a month"
        )


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)
