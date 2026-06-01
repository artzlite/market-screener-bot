import logging

import pandas as pd
import yfinance as yf

from screener.config import ScreenerConfig

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def fetch_daily_data(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Download daily OHLCV data for all tickers using yfinance.

    Downloads in batches for reliability. Tickers that fail are skipped with a warning.

    Args:
        tickers: List of ticker symbols.
        period: Data period (e.g., '6mo', '1y', '2y').

    Returns:
        Dict mapping ticker symbol to its OHLCV DataFrame.
    """
    result: dict[str, pd.DataFrame] = {}

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        batch_str = " ".join(batch)
        logger.info(
            "Downloading batch %d/%d (%d tickers)",
            i // BATCH_SIZE + 1,
            (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE,
            len(batch),
        )

        try:
            data = yf.download(
                batch_str, period=period, group_by="ticker", auto_adjust=True, progress=False, threads=True
            )

            if len(batch) == 1:
                # Single ticker handling
                ticker = batch[0]
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                if not data.empty:
                    result[ticker] = data.dropna(how="all")
            else:
                # Multiple tickers: data is grouped by ticker
                for ticker in batch:
                    try:
                        ticker_data = data[ticker].dropna(how="all")
                        if not ticker_data.empty:
                            result[ticker] = ticker_data
                    except KeyError:
                        logger.warning("No data returned for %s", ticker)
        except Exception as e:
            logger.warning("Batch download failed: %s", e)

    logger.info("Successfully downloaded data for %d/%d tickers", len(result), len(tickers))
    return result


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
