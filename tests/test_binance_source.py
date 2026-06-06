"""Tests for the Binance public klines source."""

import time

import pandas as pd
import pytest

from screener.sources import binance_source


def _sample_klines(n: int = 5) -> list[list]:
    """Build n fake daily klines in Binance's array format."""
    start = 1_700_000_000_000  # ms
    day = 86_400_000
    out = []
    for i in range(n):
        open_t = start + i * day
        out.append([
            open_t,
            f"{100 + i}.0",      # open
            f"{105 + i}.0",      # high
            f"{95 + i}.0",       # low
            f"{102 + i}.0",      # close
            f"{1000 + i}.0",     # volume
            open_t + day - 1,    # close_time
            "0", 10, "0", "0", "0",
        ])
    return out


class TestKlinesToDf:
    def test_contract_columns_and_dtypes(self) -> None:
        df = binance_source._klines_to_df(_sample_klines(5))
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        for col in df.columns:
            assert df[col].dtype == float

    def test_index_is_utc_datetime(self) -> None:
        df = binance_source._klines_to_df(_sample_klines(5))
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"

    def test_drops_forming_last_candle(self) -> None:
        klines = _sample_klines(5)
        df = binance_source._klines_to_df(klines)
        # 5 klines in, last (still-forming) dropped -> 4 rows
        assert len(df) == 4

    def test_empty_returns_none(self) -> None:
        assert binance_source._klines_to_df([]) is None


class TestPeriodToLimit:
    def test_known_period(self) -> None:
        assert binance_source._period_to_limit("1y") == 370

    def test_caps_at_max(self) -> None:
        assert binance_source._period_to_limit("max") <= binance_source.MAX_LIMIT


class TestFetch:
    def test_fetch_builds_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            binance_source, "_request_klines", lambda *a, **k: _sample_klines(10)
        )
        result = binance_source.fetch(["BTCUSDT", "ETHUSDT"], period="1y")
        assert set(result.keys()) == {"BTCUSDT", "ETHUSDT"}
        assert not result["BTCUSDT"].empty

    def test_failed_symbol_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda *_: None)
        monkeypatch.setattr(binance_source, "_request_klines", lambda *a, **k: None)
        result = binance_source.fetch(["BTCUSDT"], period="1y")
        assert result == {}

    def test_spot_vs_futures_path(self) -> None:
        assert binance_source._klines_path("spot") == "/api/v3/klines"
        assert binance_source._klines_path("futures") == "/fapi/v1/klines"
