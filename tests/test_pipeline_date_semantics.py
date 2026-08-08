from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.core.pipeline import StockAnalysisPipeline


class _FetcherManager:
    def build_failed_fundamental_context(self, code, reason):
        return {"code": code, "reason": reason}


def _pipeline():
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh")
    pipeline.search_service = SimpleNamespace(news_window_days=3)
    pipeline.fetcher_manager = _FetcherManager()
    return pipeline


def _quote():
    return SimpleNamespace(
        name="test", price=10.5, open_price=10.2, pre_close=10.0,
        high=10.8, low=10.1, volume=1000, amount=10500,
        change_pct=5.0, source="test",
    )


def _trend():
    return SimpleNamespace(
        ma5=10.1, ma10=10.0, ma20=9.9, trend_status=SimpleNamespace(value="bull"),
        ma_alignment="bull", trend_strength="strong",
        bias_ma5=0.0, bias_ma10=0.0,
        volume_status=SimpleNamespace(value="normal"), volume_trend="flat",
        buy_signal=SimpleNamespace(value="hold"), signal_score=0,
        signal_reasons=[], risk_factors=[],
    )


@patch("src.core.pipeline.get_market_for_stock", return_value="cn")
@patch(
    "src.core.pipeline.get_market_now",
    return_value=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
)
def test_weekend_observation_does_not_replace_trading_date(_market_now, _market):
    context = {
        "code": "600519",
        "date": "2026-07-31",
        "today": {"date": "2026-07-31", "close": 10.0},
        "yesterday": {"close": 10.0},
    }

    enhanced = _pipeline()._enhance_context(context, _quote(), None, _trend())

    assert enhanced["trading_date"] == "2026-07-31"
    assert enhanced["observation_date"] == "2026-08-02"
    assert enhanced["date"] == "2026-07-31"
    assert enhanced["today"]["observation_date"] == "2026-08-02"


def test_missing_daily_bar_does_not_guess_trading_date():
    context = {
        "code": "600519",
        "date": "2026-08-02",
        "today": {"close": 10.0},
        "data_missing": True,
    }

    enhanced = _pipeline()._enhance_context(context, None, None, None)

    assert "trading_date" not in enhanced
