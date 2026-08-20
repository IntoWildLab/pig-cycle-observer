from datetime import date, datetime, timedelta

import pytest

from src.pig_cycle.cutoff_generator import generate_month_end_cutoffs


def test_generates_three_month_end_cutoffs_in_ascending_order() -> None:
    cutoffs = generate_month_end_cutoffs(date(2026, 1, 1), date(2026, 3, 1))

    assert [(cutoff.year, cutoff.month, cutoff.day) for cutoff in cutoffs] == [
        (2026, 1, 31),
        (2026, 2, 28),
        (2026, 3, 31),
    ]


def test_handles_leap_year_february() -> None:
    (cutoff,) = generate_month_end_cutoffs(date(2024, 2, 1), date(2024, 2, 1))

    assert cutoff.date() == date(2024, 2, 29)


@pytest.mark.parametrize(
    ("month", "expected_day"),
    [
        (date(2026, 4, 1), 30),
        (date(2026, 7, 1), 31),
    ],
)
def test_handles_different_month_lengths(month: date, expected_day: int) -> None:
    (cutoff,) = generate_month_end_cutoffs(month, month)

    assert cutoff.day == expected_day


def test_uses_fixed_utc_plus_eight_timezone() -> None:
    (cutoff,) = generate_month_end_cutoffs(date(2026, 7, 1), date(2026, 7, 1))

    assert cutoff.utcoffset() == timedelta(hours=8)


def test_uses_last_microsecond_of_month() -> None:
    (cutoff,) = generate_month_end_cutoffs(date(2026, 7, 1), date(2026, 7, 1))

    assert (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) == (
        23,
        59,
        59,
        999999,
    )


@pytest.mark.parametrize(
    ("start_month", "end_month"),
    [
        (date(2026, 7, 15), date(2026, 8, 1)),
        (date(2026, 7, 1), date(2026, 8, 15)),
        (datetime(2026, 7, 1), date(2026, 8, 1)),
    ],
)
def test_rejects_inputs_that_are_not_month_start_dates(
    start_month: date,
    end_month: date,
) -> None:
    with pytest.raises(ValueError):
        generate_month_end_cutoffs(start_month, end_month)


def test_rejects_start_month_after_end_month() -> None:
    with pytest.raises(ValueError):
        generate_month_end_cutoffs(date(2026, 8, 1), date(2026, 7, 1))


def test_single_month_returns_one_cutoff_in_a_tuple() -> None:
    cutoffs = generate_month_end_cutoffs(date(2026, 7, 1), date(2026, 7, 1))

    assert isinstance(cutoffs, tuple)
    assert cutoffs == (
        datetime.fromisoformat("2026-07-31T23:59:59.999999+08:00"),
    )
