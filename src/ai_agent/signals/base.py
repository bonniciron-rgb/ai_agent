"""Core Signal interface used by the validation harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import pandas as pd


@dataclass
class SignalContext:
    """Inputs available to a signal at a single (symbol, as_of) decision point."""

    symbol: str
    as_of: date
    bars: pd.DataFrame  # OHLCV indexed by trading_date, INCLUDES the as_of bar


@dataclass
class SignalResult:
    """Output of a signal evaluation at one point in time."""

    score: float  # in [-1.0, 1.0]; >0 = bullish, <0 = bearish, 0 = neutral
    confidence: float = 1.0  # in [0.0, 1.0]; 0 = "no opinion"
    notes: list[str] = field(default_factory=list)


class Signal(Protocol):
    """A signal is anything with a name, version, and a compute() method."""

    name: str
    version: str

    def compute(self, ctx: SignalContext) -> SignalResult: ...
