"""Binance public klines OHLCV source.

Uses Binance's **public** kline REST endpoint — no API key required (the testnet
keys used by trading bots are only needed to place orders).

GitHub Actions runners have US IPs, and ``api.binance.com`` / ``fapi.binance.com``
return HTTP 451 from the US. The default base URL is therefore
``https://data-api.binance.vision`` (the geo-robust public market-data host).
For daily technical analysis, spot vs perpetual klines are immaterial.

Returns the shared DataFrame contract: columns Open/High/Low/Close/Volume and a
tz-aware (UTC) DatetimeIndex.
"""
import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://data-api.binance.vision"
MAX_LIMIT = 1000  # Binance per-request kline cap

# Approximate number of daily bars to request for a given yfinance-style period.
_PERIOD_TO_LIMIT = {
    "1mo": 35,
    "3mo": 100,
    "6mo": 190,
    "1y": 370,
    "2y": 740,
    "5y": 1000,  # capped by MAX_LIMIT
    "max": 1000,
}

_KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_buy_base",
    "taker_buy_quote", "ignore",
]


def _klines_path(market: str) -> str:
    return "/fapi/v1/klines" if market == "futures" else "/api/v3/klines"


def _period_to_limit(period: str) -> int:
    return min(_PERIOD_TO_LIMIT.get(period, 370), MAX_LIMIT)


def _request_klines(
    base_url: str, path: str, symbol: str, interval: str, limit: int
) -> list[list] | None:
    """Fetch a single batch of klines, retrying on HTTP 429. Returns None on failure."""
    url = base_url.rstrip("/") + path
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("Binance rate limited (429) for %s. Sleeping %ds", symbol, wait)
                time.sleep(wait)
                continue
            if resp.status_code == 451:
                logger.warning(
                    "Binance returned 451 (geo-restricted) for %s at %s. "
                    "Set binance_base_url to a permitted host.", symbol, base_url
                )
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Binance klines request failed for %s (attempt %d): %s", symbol, attempt, e)
            time.sleep(1)
    return None


def _klines_to_df(klines: list[list]) -> pd.DataFrame | None:
    """Convert raw Binance klines to the shared OHLCV DataFrame contract."""
    if not klines:
        return None

    df = pd.DataFrame(klines, columns=_KLINE_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    out = pd.DataFrame({
        "Open": df["open"].to_numpy(),
        "High": df["high"].to_numpy(),
        "Low": df["low"].to_numpy(),
        "Close": df["close"].to_numpy(),
        "Volume": df["volume"].to_numpy(),
    }, index=pd.DatetimeIndex(df["open_time"], name="Date"))

    out = out[~out.index.duplicated(keep="last")].sort_index()

    # Drop the still-forming (last) candle so we screen on closed bars only,
    # matching the "previous trading day" semantics used elsewhere.
    if len(out) > 1:
        out = out.iloc[:-1]
    return out


def fetch(
    symbols: list[str],
    period: str = "1y",
    base_url: str = DEFAULT_BASE_URL,
    market: str = "spot",
) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for crypto symbols from Binance public klines.

    Args:
        symbols: Binance symbols, e.g. ["BTCUSDT", "ETHUSDT"].
        period: yfinance-style period; mapped to a kline ``limit``.
        base_url: Binance host (default geo-robust public data host).
        market: "spot" or "futures" (selects the klines path).

    Returns:
        Dict mapping symbol to its OHLCV DataFrame. Failed symbols are skipped.
    """
    path = _klines_path(market)
    limit = _period_to_limit(period)
    result: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        klines = _request_klines(base_url, path, symbol, "1d", limit)
        if klines is None:
            continue
        df = _klines_to_df(klines)
        if df is not None and not df.empty:
            result[symbol] = df
        else:
            logger.warning("Binance returned no usable data for %s", symbol)
        time.sleep(0.15)  # gentle pacing

    logger.info("Binance: downloaded data for %d/%d symbols", len(result), len(symbols))
    return result
