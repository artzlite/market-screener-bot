"""Shared test fixtures for market screener tests."""

import pandas as pd
import numpy as np
import pytest

from screener.config import ScreenerConfig, Strategy, Rule


@pytest.fixture
def sample_ohlcv_data() -> pd.DataFrame:
    """Generate 250 days of realistic OHLCV data for testing.

    Creates a slightly uptrending price series starting at $100 with
    realistic daily fluctuations, suitable for indicator calculations.
    """
    np.random.seed(42)
    n_days = 250
    dates = pd.bdate_range(start="2025-01-02", periods=n_days)

    # Generate a random walk with slight upward drift
    returns = np.random.normal(loc=0.0003, scale=0.015, size=n_days)
    close = 100 * np.cumprod(1 + returns)

    # Create realistic OHLCV from close prices
    high = close * (1 + np.abs(np.random.normal(0, 0.008, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.008, n_days)))
    open_price = close * (1 + np.random.normal(0, 0.005, n_days))
    volume = np.random.randint(1_000_000, 50_000_000, n_days)

    return pd.DataFrame({
        "Open": open_price,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


@pytest.fixture
def oversold_ohlcv_data() -> pd.DataFrame:
    """Generate OHLCV data that ends in a strong downtrend (oversold conditions).

    The last 20 days have a sharp decline to trigger Stochastic < 30 and RSI < 30.
    """
    np.random.seed(123)
    n_days = 250
    dates = pd.bdate_range(start="2025-01-02", periods=n_days)

    # Uptrend for most of the period, then sharp decline
    returns = np.concatenate([
        np.random.normal(loc=0.001, scale=0.01, size=n_days - 20),  # Uptrend
        np.random.normal(loc=-0.02, scale=0.005, size=20),           # Sharp drop
    ])
    close = 100 * np.cumprod(1 + returns)

    high = close * (1 + np.abs(np.random.normal(0, 0.005, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n_days)))
    open_price = close * (1 + np.random.normal(0, 0.003, n_days))
    volume = np.random.randint(1_000_000, 50_000_000, n_days)

    return pd.DataFrame({
        "Open": open_price,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


@pytest.fixture
def overbought_ohlcv_data() -> pd.DataFrame:
    """Generate OHLCV data that ends in a strong uptrend (overbought conditions).

    The last 20 days have a sharp rally to trigger Stochastic > 70 and RSI > 70.
    """
    np.random.seed(456)
    n_days = 250
    dates = pd.bdate_range(start="2025-01-02", periods=n_days)

    # Flat for most of the period, then sharp rally
    returns = np.concatenate([
        np.random.normal(loc=0.0002, scale=0.01, size=n_days - 20),  # Flat
        np.random.normal(loc=0.02, scale=0.005, size=20),             # Sharp rally
    ])
    close = 100 * np.cumprod(1 + returns)

    high = close * (1 + np.abs(np.random.normal(0, 0.005, n_days)))
    low = close * (1 - np.abs(np.random.normal(0, 0.005, n_days)))
    open_price = close * (1 + np.random.normal(0, 0.003, n_days))
    volume = np.random.randint(1_000_000, 50_000_000, n_days)

    return pd.DataFrame({
        "Open": open_price,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


@pytest.fixture
def default_config() -> ScreenerConfig:
    """Provide a default ScreenerConfig for testing."""
    return ScreenerConfig(
        strategies=[
            Strategy(
                name="Oversold Bounce (Daily)",
                description="Oversold on daily with uptrend filter",
                timeframe="daily",
                rules=[
                    Rule(indicator="stochastic_k", operator="<", value=30),
                    Rule(indicator="rsi", operator="<", value=30),
                    Rule(indicator="price_vs_sma200", operator=">", value=0),
                ],
            ),
            Strategy(
                name="Overbought Alert (Daily)",
                description="Overbought on daily timeframe",
                timeframe="daily",
                rules=[
                    Rule(indicator="stochastic_k", operator=">", value=70),
                    Rule(indicator="rsi", operator=">", value=70),
                ],
            ),
        ],
        etf_list=["SPY", "QQQ"],
    )
