import math

from ai_agent.features.regime import Regime, classify_regime


def test_unknown_when_inputs_missing() -> None:
    assert (
        classify_regime(close=None, sma_200=None, adx_14=None, bb_upper=None, bb_lower=None)
        is Regime.unknown
    )


def test_unknown_when_inputs_nan() -> None:
    assert (
        classify_regime(
            close=math.nan,
            sma_200=100.0,
            adx_14=30.0,
            bb_upper=110.0,
            bb_lower=90.0,
        )
        is Regime.unknown
    )


def test_strong_uptrend() -> None:
    assert (
        classify_regime(close=110.0, sma_200=100.0, adx_14=30.0, bb_upper=115.0, bb_lower=95.0)
        is Regime.trending_up
    )


def test_strong_downtrend() -> None:
    assert (
        classify_regime(close=90.0, sma_200=100.0, adx_14=30.0, bb_upper=110.0, bb_lower=85.0)
        is Regime.trending_down
    )


def test_ranging_when_adx_low() -> None:
    assert (
        classify_regime(close=100.0, sma_200=100.0, adx_14=10.0, bb_upper=105.0, bb_lower=95.0)
        is Regime.ranging
    )


def test_breakout_above_band_when_adx_mid() -> None:
    assert (
        classify_regime(close=120.0, sma_200=100.0, adx_14=22.0, bb_upper=115.0, bb_lower=95.0)
        is Regime.breakout
    )


def test_breakout_below_band_when_adx_mid() -> None:
    assert (
        classify_regime(close=80.0, sma_200=100.0, adx_14=22.0, bb_upper=110.0, bb_lower=90.0)
        is Regime.breakout
    )


def test_ranging_when_adx_mid_but_inside_bands() -> None:
    assert (
        classify_regime(close=100.0, sma_200=100.0, adx_14=22.0, bb_upper=110.0, bb_lower=90.0)
        is Regime.ranging
    )
