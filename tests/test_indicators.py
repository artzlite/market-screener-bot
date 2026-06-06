"""Tests for technical indicator calculations."""

import pandas as pd
import pytest

from screener.indicators import (
    calculate_adx,
    calculate_all_indicators,
    calculate_atr,
    calculate_bollinger,
    calculate_macd,
    calculate_roc,
    calculate_rsi,
    calculate_rvol,
    calculate_sma,
    calculate_stochastic,
)


class TestStochastic:
    """Tests for Stochastic %K and %D calculation."""

    def test_stochastic_returns_correct_columns(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Stochastic should return DataFrame with stochastic_k and stochastic_d columns."""
        result = calculate_stochastic(sample_ohlcv_data)
        assert "stochastic_k" in result.columns
        assert "stochastic_d" in result.columns

    def test_stochastic_range_is_0_to_100(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Stochastic %K values should be between 0 and 100."""
        result = calculate_stochastic(sample_ohlcv_data)
        valid_k = result["stochastic_k"].dropna()
        assert (valid_k >= 0).all()
        assert (valid_k <= 100).all()

    def test_stochastic_oversold_detection(self, oversold_ohlcv_data: pd.DataFrame) -> None:
        """Stochastic %K should be < 30 for oversold data."""
        result = calculate_stochastic(oversold_ohlcv_data)
        latest_k = result["stochastic_k"].iloc[-1]
        assert latest_k < 30, f"Expected Stochastic %K < 30 for oversold data, got {latest_k:.2f}"

    def test_stochastic_overbought_detection(self, overbought_ohlcv_data: pd.DataFrame) -> None:
        """Stochastic %K should be > 70 for overbought data."""
        result = calculate_stochastic(overbought_ohlcv_data)
        latest_k = result["stochastic_k"].iloc[-1]
        assert latest_k > 70, f"Expected Stochastic %K > 70 for overbought data, got {latest_k:.2f}"

    def test_stochastic_custom_periods(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """Stochastic should respect custom k_period and d_period."""
        result_default = calculate_stochastic(sample_ohlcv_data, k_period=14, d_period=3)
        result_custom = calculate_stochastic(sample_ohlcv_data, k_period=5, d_period=5)
        # Different parameters should produce different values
        assert not result_default["stochastic_k"].equals(result_custom["stochastic_k"])

    def test_stochastic_d_is_smoother_than_k(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """%D (SMA of %K) should have lower standard deviation than %K."""
        result = calculate_stochastic(sample_ohlcv_data)
        k_std = result["stochastic_k"].dropna().std()
        d_std = result["stochastic_d"].dropna().std()
        assert d_std < k_std, f"%D std ({d_std:.2f}) should be < %K std ({k_std:.2f})"


class TestRSI:
    """Tests for RSI calculation."""

    def test_rsi_range_is_0_to_100(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """RSI values should be between 0 and 100."""
        result = calculate_rsi(sample_ohlcv_data)
        valid_rsi = result.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_rsi_oversold_detection(self, oversold_ohlcv_data: pd.DataFrame) -> None:
        """RSI should be < 30 for oversold data."""
        result = calculate_rsi(oversold_ohlcv_data)
        latest_rsi = result.iloc[-1]
        assert latest_rsi < 30, f"Expected RSI < 30 for oversold data, got {latest_rsi:.2f}"

    def test_rsi_overbought_detection(self, overbought_ohlcv_data: pd.DataFrame) -> None:
        """RSI should be > 70 for overbought data."""
        result = calculate_rsi(overbought_ohlcv_data)
        latest_rsi = result.iloc[-1]
        assert latest_rsi > 70, f"Expected RSI > 70 for overbought data, got {latest_rsi:.2f}"

    def test_rsi_custom_period(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """RSI should produce different results with different periods."""
        rsi_14 = calculate_rsi(sample_ohlcv_data, period=14)
        rsi_7 = calculate_rsi(sample_ohlcv_data, period=7)
        assert not rsi_14.equals(rsi_7)

    def test_rsi_name_is_set(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """RSI Series should have name 'rsi'."""
        result = calculate_rsi(sample_ohlcv_data)
        assert result.name == "rsi"


class TestMACD:
    """Tests for MACD calculation."""

    def test_macd_returns_correct_columns(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """MACD should return DataFrame with expected columns."""
        result = calculate_macd(sample_ohlcv_data)
        expected_cols = {"macd_line", "macd_signal", "macd_histogram", "macd_crossover"}
        assert set(result.columns) == expected_cols

    def test_macd_histogram_equals_line_minus_signal(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """MACD histogram should equal MACD line minus signal line."""
        result = calculate_macd(sample_ohlcv_data)
        expected_hist = result["macd_line"] - result["macd_signal"]
        pd.testing.assert_series_equal(result["macd_histogram"], expected_hist, check_names=False)

    def test_macd_crossover_values(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """MACD crossover should only contain -1, 0, or 1."""
        result = calculate_macd(sample_ohlcv_data)
        valid_values = {-1, 0, 1}
        assert set(result["macd_crossover"].unique()).issubset(valid_values)

    def test_macd_crossover_detects_bullish(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """MACD should detect at least one bullish crossover in sample data."""
        result = calculate_macd(sample_ohlcv_data)
        bullish_count = (result["macd_crossover"] == 1).sum()
        assert bullish_count > 0, "Expected at least one bullish MACD crossover in sample data"

    def test_macd_custom_periods(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """MACD should produce different results with different periods."""
        result_default = calculate_macd(sample_ohlcv_data, fast_period=12, slow_period=26, signal_period=9)
        result_custom = calculate_macd(sample_ohlcv_data, fast_period=8, slow_period=21, signal_period=5)
        assert not result_default["macd_line"].equals(result_custom["macd_line"])


class TestSMA:
    """Tests for SMA calculation."""

    def test_sma_matches_pandas_rolling(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """SMA should match pandas rolling mean."""
        result = calculate_sma(sample_ohlcv_data, period=20)
        expected = sample_ohlcv_data["Close"].rolling(window=20).mean()
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_sma_200_has_nan_for_first_199_bars(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """200-period SMA should have NaN for the first 199 data points."""
        result = calculate_sma(sample_ohlcv_data, period=200)
        assert result.iloc[:199].isna().all()
        assert not pd.isna(result.iloc[199])

    def test_sma_name_is_set(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """SMA Series should have name 'sma'."""
        result = calculate_sma(sample_ohlcv_data)
        assert result.name == "sma"


class TestNewIndicators:
    """Tests for the volume / momentum / breakout indicators."""

    def test_rvol_excludes_current_bar(self, sample_ohlcv_data: pd.DataFrame) -> None:
        """RVOL baseline must exclude the current bar (no look-ahead)."""
        result = calculate_rvol(sample_ohlcv_data, period=20)
        # Manually compute the expected ratio for the last bar.
        avg = sample_ohlcv_data["Volume"].iloc[-21:-1].mean()
        expected = sample_ohlcv_data["Volume"].iloc[-1] / avg
        assert result.iloc[-1] == pytest.approx(expected, rel=1e-6)

    def test_rvol_is_positive(self, sample_ohlcv_data: pd.DataFrame) -> None:
        result = calculate_rvol(sample_ohlcv_data).dropna()
        assert (result > 0).all()

    def test_atr_is_non_negative(self, sample_ohlcv_data: pd.DataFrame) -> None:
        result = calculate_atr(sample_ohlcv_data).dropna()
        assert (result >= 0).all()

    def test_roc_matches_formula(self, sample_ohlcv_data: pd.DataFrame) -> None:
        result = calculate_roc(sample_ohlcv_data, period=12)
        close = sample_ohlcv_data["Close"]
        expected = (close.iloc[-1] / close.iloc[-13] - 1) * 100
        assert result.iloc[-1] == pytest.approx(expected, rel=1e-6)

    def test_bollinger_width_non_negative(self, sample_ohlcv_data: pd.DataFrame) -> None:
        result = calculate_bollinger(sample_ohlcv_data)
        width = result["bb_width"].dropna()
        assert (width >= 0).all()
        assert (result["bb_upper"].dropna() >= result["bb_lower"].dropna()).all()

    def test_adx_range_is_0_to_100(self, sample_ohlcv_data: pd.DataFrame) -> None:
        result = calculate_adx(sample_ohlcv_data).dropna()
        assert (result >= 0).all()
        assert (result <= 100).all()


class TestCalculateAllIndicators:
    """Tests for the combined indicator calculation function."""

    def test_returns_all_expected_keys(self, sample_ohlcv_data: pd.DataFrame, default_config) -> None:
        """calculate_all_indicators should return all expected indicator keys."""
        result = calculate_all_indicators(sample_ohlcv_data, default_config)
        assert result is not None
        expected_keys = {
            "stochastic_k", "stochastic_k_5d", "stochastic_d", "rsi", "rsi_5d",
            "macd_line", "macd_signal", "macd_histogram", "macd_crossover",
            "sma", "price_vs_sma200", "close", "history_close_30d", "change_pct",
            "sma50", "rvol", "atr", "roc", "bb_upper", "bb_lower", "bb_width",
            "adx", "dist_52w_high", "dist_52w_low", "golden_cross",
        }
        assert set(result.keys()) == expected_keys

    def test_returns_none_for_insufficient_data(self, default_config) -> None:
        """Should return None when data has fewer bars than SMA period."""
        short_data = pd.DataFrame({
            "Open": [100] * 50,
            "High": [105] * 50,
            "Low": [95] * 50,
            "Close": [100] * 50,
            "Volume": [1000000] * 50,
        }, index=pd.bdate_range(start="2025-01-02", periods=50))

        result = calculate_all_indicators(short_data, default_config)
        assert result is None

    def test_returns_none_for_empty_dataframe(self, default_config) -> None:
        """Should return None for empty DataFrame."""
        empty_df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        result = calculate_all_indicators(empty_df, default_config)
        assert result is None

    def test_close_price_matches_last_bar(self, sample_ohlcv_data: pd.DataFrame, default_config) -> None:
        """The 'close' value should match the last closing price."""
        result = calculate_all_indicators(sample_ohlcv_data, default_config)
        assert result is not None
        assert result["close"] == pytest.approx(float(sample_ohlcv_data["Close"].iloc[-1]), rel=1e-6)

    def test_price_vs_sma200_ratio(self, sample_ohlcv_data: pd.DataFrame, default_config) -> None:
        """price_vs_sma200 should be close / sma200."""
        result = calculate_all_indicators(sample_ohlcv_data, default_config)
        assert result is not None
        if result["sma"] is not None and result["sma"] != 0:
            expected_ratio = result["close"] / result["sma"]
            assert result["price_vs_sma200"] == pytest.approx(expected_ratio, rel=1e-4)
