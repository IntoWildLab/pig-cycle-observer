from datetime import date

import pytest

from src.pig_cycle.sow_monthly import (
    NORMAL_CAPACITY_2026,
    SowMonthlyDataError,
    SowSourceType,
    capacity_ratio,
    capacity_zone,
    parse_sow_monthly_record,
)


SOURCE_URL = "https://example.gov.cn/official-sow-report"


def _parse(text: str, *, published: date = date(2026, 6, 10)):
    return parse_sow_monthly_record(
        text,
        source_url=SOURCE_URL,
        source_type=SowSourceType.MOA_REPORTED,
        publish_date=published,
    )


def test_parse_inventory_and_signed_monthly_and_yearly_changes() -> None:
    record = _parse("现将有关情况通报：5月末能繁母猪存栏3996万头，环比增长0.2%，同比下降6.2%。")

    assert record.month == "2026-05"
    assert record.sow_inventory == 3996
    assert record.mom_change == 0.2
    assert record.yoy_change == -6.2


def test_missing_changes_remain_none() -> None:
    record = _parse("1月末全国能繁母猪存栏量4062万头", published=date(2026, 2, 10))

    assert record.month == "2026-01"
    assert record.sow_inventory == 4062
    assert record.mom_change is None
    assert record.yoy_change is None


def test_explicit_year_end_is_december() -> None:
    record = _parse("截至2025年末，全国能繁母猪存栏下调至3961万头", published=date(2026, 1, 20))

    assert record.month == "2025-12"
    assert record.sow_inventory == 3961


def test_month_only_uses_previous_year_when_published_in_january() -> None:
    record = _parse("12月末能繁母猪存栏3961万头", published=date(2026, 1, 20))

    assert record.month == "2025-12"


def test_explicit_year_month_wins_across_year_boundary() -> None:
    record = _parse(
        "2025年12月末能繁母猪存栏3961万头",
        published=date(2026, 1, 20),
    )

    assert record.month == "2025-12"


@pytest.mark.parametrize("word", ["增长", "上升", "增加"])
def test_positive_change_words(word: str) -> None:
    record = _parse(f"5月末能繁母猪存栏3996万头，环比{word}0.5%")

    assert record.mom_change == 0.5


@pytest.mark.parametrize("word", ["下降", "减少", "下调"])
def test_negative_change_words(word: str) -> None:
    record = _parse(f"5月末能繁母猪存栏3996万头，同比{word}6.2%")

    assert record.yoy_change == -6.2


def test_missing_inventory_raises_instead_of_filling_zero() -> None:
    with pytest.raises(SowMonthlyDataError, match="sow_inventory"):
        _parse("5月末能繁母猪环比增长0.2%")


def test_ambiguous_month_without_publish_date_raises() -> None:
    with pytest.raises(SowMonthlyDataError, match="month is ambiguous"):
        parse_sow_monthly_record(
            "5月末能繁母猪存栏3996万头",
            source_url=SOURCE_URL,
            source_type="nbs",
        )


def test_source_type_must_be_declared_from_supported_values() -> None:
    with pytest.raises(SowMonthlyDataError, match="source_type"):
        parse_sow_monthly_record(
            "2026年5月末能繁母猪存栏3996万头",
            source_url=SOURCE_URL,
            source_type="guessed",
        )


def test_capacity_ratio_is_not_rounded() -> None:
    assert capacity_ratio(3961) == 3961 / NORMAL_CAPACITY_2026


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.8799, "red_low"),
        (0.88, "yellow_low"),
        (0.9199, "yellow_low"),
        (0.92, "green"),
        (1.03, "green"),
        (1.0301, "yellow_high"),
        (1.06, "yellow_high"),
        (1.0601, "red_high"),
    ],
)
def test_capacity_zone_boundaries(ratio: float, expected: str) -> None:
    assert capacity_zone(ratio) == expected
