from types import SimpleNamespace

from src.services.run_summary import RunSummary, collect_data_dates, render_run_summary


def _result(**snapshot):
    return SimpleNamespace(market_snapshot=snapshot)


def _render(results):
    return render_run_summary(RunSummary(
        planned_count=len(results),
        success_count=len(results),
        failed_items=(),
        elapsed_seconds=1,
        data_dates=collect_data_dates(results),
    ))


def test_summary_uses_trading_date_and_ignores_observation_date():
    rendered = _render([_result(
        trading_date="2026-07-31",
        observation_date="2026-08-02",
        date="2026-07-31",
    )])

    assert "数据日期：2026-07-31" in rendered
    assert "2026-08-02" not in rendered


def test_summary_omits_data_date_without_trading_date():
    rendered = _render([_result(observation_date="2026-08-02", date="2026-08-02")])

    assert "数据日期" not in rendered
    assert "2026-08-02" not in rendered


def test_summary_deduplicates_equal_trading_dates():
    dates = collect_data_dates([
        _result(trading_date="2026-07-31"),
        _result(trading_date="2026-07-31"),
    ])

    assert dates == ("2026-07-31",)


def test_summary_keeps_distinct_trading_dates():
    dates = collect_data_dates([
        _result(trading_date="2026-07-31"),
        _result(trading_date="2026-07-30"),
    ])

    assert dates == ("2026-07-31", "2026-07-30")
