from src.analyzer import GeminiAnalyzer


def _snapshot(context):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    return analyzer._build_market_snapshot(context)


def test_snapshot_exposes_verified_trading_and_observation_dates():
    snapshot = _snapshot({
        "trading_date": "2026-07-31",
        "observation_date": "2026-08-02",
        "today": {"close": 10.0},
    })

    assert snapshot["date"] == "2026-07-31"
    assert snapshot["trading_date"] == "2026-07-31"
    assert snapshot["observation_date"] == "2026-08-02"


def test_observation_date_cannot_stand_in_for_snapshot_date():
    snapshot = _snapshot({
        "date": "2026-08-02",
        "observation_date": "2026-08-02",
        "today": {"close": 10.0},
    })

    assert "date" not in snapshot
    assert "trading_date" not in snapshot
    assert snapshot["observation_date"] == "2026-08-02"
