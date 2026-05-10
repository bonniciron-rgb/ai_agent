"""Tests for the signal runner — backtest_signal + save_backtest_result."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from ai_agent.data.base import BarPoint, BarSeries
from ai_agent.db.models import SignalBacktest
from ai_agent.signals.reference import AlwaysFlatSignal
from ai_agent.signals.runner import backtest_signal, save_backtest_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar_series(symbol: str, n: int = 300, start: date | None = None) -> BarSeries:
    """Generate *n* synthetic bars with a gentle uptrend."""
    start = start or date(2022, 1, 1)
    points = []
    for i in range(n):
        d = start + timedelta(days=i)
        close = Decimal(str(100.0 + i * 0.05))
        points.append(
            BarPoint(
                symbol=symbol,
                trading_date=d,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=1_000_000,
                source="synthetic",
            )
        )
    return BarSeries(symbol=symbol, points=points)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBacktestSignalAlwaysFlat:
    def test_no_trades_and_near_zero_sharpe(self, monkeypatch):
        aapl_bars = _make_bar_series("AAPL", n=300)
        spy_bars = _make_bar_series("SPY", n=300)

        def _fake_bars_from_db(symbol, *, days_back=300, ref_date=None):
            return aapl_bars if symbol.upper() == "AAPL" else spy_bars

        monkeypatch.setattr("ai_agent.signals.runner.bars_from_db", _fake_bars_from_db)

        result = backtest_signal(
            AlwaysFlatSignal(),
            symbols=["AAPL"],
            start=date(2022, 1, 1),
            end=date(2022, 10, 27),  # ~300 days into the series
            benchmark_symbol="SPY",
        )

        assert result.trade_count == 0
        # AlwaysFlatSignal never enters — sharpe could be 0.0 or very near 0
        if result.sharpe is not None:
            assert abs(result.sharpe) < 0.1


class TestBacktestSignalMissingSymbol:
    def test_empty_bars_skipped_no_crash(self, monkeypatch):
        spy_bars = _make_bar_series("SPY", n=300)

        def _fake_bars_from_db(symbol, *, days_back=300, ref_date=None):
            if symbol.upper() == "MISSING":
                return BarSeries(symbol="MISSING", points=[])
            return spy_bars

        monkeypatch.setattr("ai_agent.signals.runner.bars_from_db", _fake_bars_from_db)

        result = backtest_signal(
            AlwaysFlatSignal(),
            symbols=["MISSING"],
            start=date(2022, 1, 1),
            end=date(2022, 10, 27),
            benchmark_symbol="SPY",
        )

        # Should not crash; no usable symbols → empty result
        assert result.trade_count == 0
        assert result.per_symbol == {}

    def test_warns_on_insufficient_bars(self, monkeypatch, caplog):
        import logging

        spy_bars = _make_bar_series("SPY", n=300)

        def _fake_bars_from_db(symbol, *, days_back=300, ref_date=None):
            if symbol.upper() == "THIN":
                return BarSeries(symbol="THIN", points=[])
            return spy_bars

        monkeypatch.setattr("ai_agent.signals.runner.bars_from_db", _fake_bars_from_db)

        with caplog.at_level(logging.WARNING, logger="ai_agent.signals.runner"):
            backtest_signal(
                AlwaysFlatSignal(),
                symbols=["THIN"],
                start=date(2022, 1, 1),
                end=date(2022, 10, 27),
                benchmark_symbol="SPY",
            )

        assert any("THIN" in r.message for r in caplog.records)


class TestSaveBacktestResult:
    def test_persists_and_returns_id(self, in_memory_engine, monkeypatch):
        spy_bars = _make_bar_series("SPY", n=300)
        aapl_bars = _make_bar_series("AAPL", n=300)

        def _fake_bars_from_db(symbol, *, days_back=300, ref_date=None):
            return aapl_bars if symbol.upper() == "AAPL" else spy_bars

        monkeypatch.setattr("ai_agent.signals.runner.bars_from_db", _fake_bars_from_db)

        result = backtest_signal(
            AlwaysFlatSignal(),
            symbols=["AAPL"],
            start=date(2022, 1, 1),
            end=date(2022, 10, 27),
            benchmark_symbol="SPY",
        )

        row = save_backtest_result(result, notes="test run", engine=in_memory_engine)
        assert row.id is not None
        assert row.signal_name == "always_flat"
        assert row.signal_version == "v1"
        assert row.notes == "test run"

        with Session(in_memory_engine) as session:
            found = session.exec(select(SignalBacktest).where(SignalBacktest.id == row.id)).one()
        assert found.signal_name == "always_flat"
        assert found.trade_count == 0

    def test_round_trip_preserves_symbols_json(self, in_memory_engine, monkeypatch):
        spy_bars = _make_bar_series("SPY", n=300)
        aapl_bars = _make_bar_series("AAPL", n=300)
        msft_bars = _make_bar_series("MSFT", n=300)

        def _fake_bars_from_db(symbol, *, days_back=300, ref_date=None):
            mapping = {"AAPL": aapl_bars, "MSFT": msft_bars, "SPY": spy_bars}
            return mapping.get(symbol.upper(), BarSeries(symbol=symbol, points=[]))

        monkeypatch.setattr("ai_agent.signals.runner.bars_from_db", _fake_bars_from_db)

        result = backtest_signal(
            AlwaysFlatSignal(),
            symbols=["AAPL", "MSFT"],
            start=date(2022, 1, 1),
            end=date(2022, 10, 27),
            benchmark_symbol="SPY",
        )

        row = save_backtest_result(result, engine=in_memory_engine)
        import json

        assert json.loads(row.symbols_json) == result.symbols
