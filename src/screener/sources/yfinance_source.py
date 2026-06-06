"""yfinance OHLCV source.

Downloads daily OHLCV in batches and returns the shared DataFrame contract
(columns Open/High/Low/Close/Volume, tz-aware DatetimeIndex).
"""
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def fetch(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Download daily OHLCV data for all symbols using yfinance.

    Downloads in batches for reliability. Symbols that fail are skipped with a warning.

    Args:
        symbols: List of ticker symbols (yfinance format, e.g. "AAPL", "PTT.BK", "GC=F").
        period: Data period (e.g., '6mo', '1y', '2y').

    Returns:
        Dict mapping symbol to its OHLCV DataFrame.
    """
    result: dict[str, pd.DataFrame] = {}

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]
        batch_str = " ".join(batch)
        logger.info(
            "Downloading batch %d/%d (%d symbols)",
            i // BATCH_SIZE + 1,
            (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE,
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

    logger.info("yfinance: downloaded data for %d/%d symbols", len(result), len(symbols))
    return result
