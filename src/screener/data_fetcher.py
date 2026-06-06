import logging

import pandas as pd

from screener.config import Market
from screener.sources import binance_source, yfinance_source

logger = logging.getLogger(__name__)


def fetch_daily_data(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Download daily OHLCV data via yfinance (backward-compatible wrapper).

    Args:
        tickers: List of ticker symbols.
        period: Data period (e.g., '6mo', '1y', '2y').

    Returns:
        Dict mapping ticker symbol to its OHLCV DataFrame.
    """
    return yfinance_source.fetch(tickers, period)


def fetch_market_data(
    market: Market,
    symbols: list[str],
    period: str = "1y",
    binance_base_url: str = "https://data-api.binance.vision",
    binance_market: str = "spot",
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for a market's symbols using the market's configured source.

    Args:
        market: The market whose ``source`` selects the fetcher.
        symbols: Resolved symbol list for this market.
        period: Data period.
        binance_base_url: Base URL for the Binance source.
        binance_market: "spot" or "futures" for the Binance source.

    Returns:
        Dict mapping symbol to its OHLCV DataFrame.
    """
    if market.source == "binance":
        return binance_source.fetch(
            symbols, period=period, base_url=binance_base_url, market=binance_market
        )
    return yfinance_source.fetch(symbols, period)


def resample_to_weekly(daily_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Resample daily OHLCV data to weekly candles.

    Args:
        daily_data: Dict mapping ticker to daily OHLCV DataFrame.

    Returns:
        Dict mapping ticker to weekly OHLCV DataFrame.
    """
    weekly_data: dict[str, pd.DataFrame] = {}

    for ticker, df in daily_data.items():
        try:
            weekly = df.resample("W").agg({
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }).dropna()
            if not weekly.empty:
                weekly_data[ticker] = weekly
        except Exception as e:
            logger.warning("Failed to resample %s to weekly: %s", ticker, e)

    return weekly_data
