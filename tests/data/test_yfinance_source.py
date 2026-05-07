"""Unit tests for the yfinance adapter.

We don't hit Yahoo. Instead, we subclass YFinanceSource and override `_download`
to return a synthetic pandas frame with the same shape Yahoo returns. If pandas
isn't available in the environment, the integration is skipped.
"""

from datetime import date
from decimal import Decimal

import pytest

from ai_agent.data import DataSourceError, SymbolNotFoundError
from ai_agent.data.yfinance_source import YFinanceSource

pd = pytest.importorskip("pandas")


def _fake_frame() -> "pd.DataFrame":
    idx = pd.DatetimeIndex(["2026-01-02", "2026-01-03"], name="Date")
    return pd.DataFrame(
        {
            "Open": [100.00, 100.80],
            "High": [101.50, 102.10],
            "Low": [99.50, 100.20],
            "Close": [100.80, 101.90],
            "Adj Close": [100.50, 101.55],
            "Volume": [12345678, 11223344],
        },
        index=idx,
    )


class _StubYF(YFinanceSource):
    def __init__(self, df) -> None:
        super().__init__()
        self._df = df

    def _download(self, symbol, start, end):
        return self._df


def test_parses_synthetic_frame() -> None:
    src = _StubYF(_fake_frame())
    series = src.get_daily("aapl", date(2026, 1, 1), date(2026, 1, 31))

    assert series.symbol == "AAPL"
    assert len(series) == 2
    p0 = series.points[0]
    assert p0.trading_date == date(2026, 1, 2)
    assert p0.open == Decimal("100.00")
    assert p0.adj_close == Decimal("100.5")
    assert p0.volume == 12345678
    assert p0.source == "yfinance"


def test_empty_frame_raises_symbol_not_found() -> None:
    src = _StubYF(pd.DataFrame())
    with pytest.raises(SymbolNotFoundError):
        src.get_daily("ZZZZ", date(2026, 1, 1), date(2026, 1, 31))


def test_start_after_end_rejected() -> None:
    src = _StubYF(_fake_frame())
    with pytest.raises(ValueError):
        src.get_daily("AAPL", date(2026, 2, 1), date(2026, 1, 1))


def test_malformed_frame_raises_data_source_error() -> None:
    df = pd.DataFrame({"Foo": [1, 2]}, index=pd.DatetimeIndex(["2026-01-02", "2026-01-03"]))
    src = _StubYF(df)
    with pytest.raises(DataSourceError):
        src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))
