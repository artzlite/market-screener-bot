import numpy as np
import pandas as pd

from screener.config import ScreenerConfig


def calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Calculate Stochastic %K and %D.

    %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
    %D = SMA of %K

    Args:
        df: OHLCV DataFrame with 'High', 'Low', 'Close' columns.
        k_period: Lookback period for %K calculation.
        d_period: SMA period for %D calculation.

    Returns:
        DataFrame with 'stochastic_k' and 'stochastic_d' columns.
    """
    lowest_low = df["Low"].rolling(window=k_period).min()
    highest_high = df["High"].rolling(window=k_period).max()

    k = ((df["Close"] - lowest_low) / (highest_high - lowest_low)) * 100
    d = k.rolling(window=d_period).mean()

    return pd.DataFrame({"stochastic_k": k, "stochastic_d": d}, index=df.index)


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index.

    Uses exponential moving average (Wilder's smoothing) for RS calculation.

    Args:
        df: DataFrame with 'Close' column.
        period: RSI lookback period.

    Returns:
        Series with RSI values.
    """
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi.name = "rsi"
    return rsi


def calculate_macd(
    df: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """Calculate MACD line, signal line, histogram, and crossover signal.

    Args:
        df: DataFrame with 'Close' column.
        fast_period: Fast EMA period.
        slow_period: Slow EMA period.
        signal_period: Signal line EMA period.

    Returns:
        DataFrame with 'macd_line', 'macd_signal', 'macd_histogram', and 'macd_crossover' columns.
        macd_crossover: 1 = bullish crossover, -1 = bearish crossover, 0 = no crossover.
    """
    fast_ema = df["Close"].ewm(span=fast_period, adjust=False).mean()
    slow_ema = df["Close"].ewm(span=slow_period, adjust=False).mean()

    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    # Crossover detection: compare current and previous bar
    prev_diff = macd_line.shift(1) - signal_line.shift(1)
    curr_diff = macd_line - signal_line

    crossover = pd.Series(0, index=df.index, dtype=int)
    crossover[(prev_diff <= 0) & (curr_diff > 0)] = 1   # Bullish crossover
    crossover[(prev_diff >= 0) & (curr_diff < 0)] = -1  # Bearish crossover

    return pd.DataFrame({
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
        "macd_crossover": crossover,
    }, index=df.index)


def calculate_sma(df: pd.DataFrame, period: int = 200) -> pd.Series:
    """Calculate Simple Moving Average.

    Args:
        df: DataFrame with 'Close' column.
        period: SMA lookback period.

    Returns:
        Series with SMA values.
    """
    sma = df["Close"].rolling(window=period).mean()
    sma.name = "sma"
    return sma


def calculate_all_indicators(df: pd.DataFrame, config: ScreenerConfig) -> dict[str, float] | None:
    """Calculate all indicators and return the latest bar's values as a flat dict.

    Args:
        df: OHLCV DataFrame for a single ticker.
        config: Screener configuration with indicator parameters.

    Returns:
        Dict with indicator names as keys and latest values as floats.
        Returns None if there's insufficient data for calculation.
    """
    if df.empty or len(df) < config.sma_period:
        return None

    try:
        stochastic = calculate_stochastic(df, config.stochastic_k_period, config.stochastic_d_period)
        rsi = calculate_rsi(df, config.rsi_period)
        macd = calculate_macd(df, config.macd_fast, config.macd_slow, config.macd_signal)
        sma = calculate_sma(df, config.sma_period)

        latest_close = df["Close"].iloc[-1]
        latest_sma = sma.iloc[-1]
        prev_close = df["Close"].iloc[-2] if len(df) > 1 else latest_close
        change_pct = float(((latest_close - prev_close) / prev_close) * 100) if prev_close != 0 else 0.0

        # Handle NaN values
        if pd.isna(latest_sma) or latest_sma == 0:
            price_vs_sma = None
        else:
            price_vs_sma = float(latest_close / latest_sma)

        result = {
            "stochastic_k": _safe_float(stochastic["stochastic_k"].iloc[-1]),
            "stochastic_k_5d": _safe_float(stochastic["stochastic_k"].iloc[-6]),
            "stochastic_d": _safe_float(stochastic["stochastic_d"].iloc[-1]),
            "rsi": _safe_float(rsi.iloc[-1]),
            "rsi_5d": _safe_float(rsi.iloc[-6]),
            "macd_line": _safe_float(macd["macd_line"].iloc[-1]),
            "macd_signal": _safe_float(macd["macd_signal"].iloc[-1]),
            "macd_histogram": _safe_float(macd["macd_histogram"].iloc[-1]),
            "macd_crossover": _safe_float(macd["macd_crossover"].iloc[-1]),
            "sma": _safe_float(latest_sma),
            "price_vs_sma200": price_vs_sma,
            "close": float(latest_close),
            "change_pct": round(change_pct, 2),
            "history_close_30d": [round(float(x), 2) for x in df["Close"].tail(30).tolist()],
        }

        # Return None if any critical indicator is NaN
        if any(v is None for k, v in result.items() if k in ("stochastic_k", "rsi")):
            return None

        return result
    except Exception:
        return None


def _safe_float(value: object) -> float | None:
    """Convert value to float, returning None for NaN/inf."""
    try:
        f = float(value)
        if pd.isna(f) or np.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None
