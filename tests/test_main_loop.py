"""Tests for the multi-market orchestration in main.py."""

import numpy as np
import pandas as pd
import pytest

from screener import main as main_mod
from screener.config import Market, Rule, ScreenerConfig, Strategy, Theme, load_config


def _ohlcv(n: int = 260, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n),
    }, index=idx)


class TestTradingDayGuard:
    def test_24_7_always_true(self) -> None:
        assert main_mod.is_previous_trading_day("24-7") is True
        assert main_mod.is_previous_trading_day("crypto") is True

    def test_real_calendar_returns_bool(self) -> None:
        assert isinstance(main_mod.is_previous_trading_day("XNYS"), bool)


class TestScreenMarket:
    def test_skips_closed_market(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main_mod, "is_previous_trading_day", lambda *a, **k: False)
        market = Market(id="us_stocks", display_name="US", symbol_provider="sp500-scrape")
        config = ScreenerConfig(strategies=[], etf_list=[])
        messages, screened = main_mod.screen_market(market, config)
        assert messages == []
        assert screened == 0

    def test_produces_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main_mod, "is_previous_trading_day", lambda *a, **k: True)
        monkeypatch.setattr(main_mod, "get_market_symbols", lambda m: ["AAA", "BBB"])
        monkeypatch.setattr(main_mod, "fetch_market_data", lambda *a, **k: {"AAA": _ohlcv(seed=1), "BBB": _ohlcv(seed=2)})
        monkeypatch.setattr(main_mod, "fetch_headlines", lambda *a, **k: [])

        config = ScreenerConfig(
            strategies=[Strategy("All", "", "daily", [Rule("rsi", ">", 0)])],
            etf_list=[],
            news_enabled=False,
        )
        market = Market(id="crypto", display_name="Crypto", source="binance",
                        calendar="24-7", symbol_provider="symbol-list", symbols=["AAA", "BBB"])
        messages, screened = main_mod.screen_market(market, config)
        assert screened == 2
        assert len(messages) >= 1

    def test_market_scoping_excludes_strategy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(main_mod, "is_previous_trading_day", lambda *a, **k: True)
        monkeypatch.setattr(main_mod, "get_market_symbols", lambda m: ["AAA"])
        monkeypatch.setattr(main_mod, "fetch_market_data", lambda *a, **k: {"AAA": _ohlcv(seed=3)})

        # Strategy scoped only to us_stocks -> crypto market has no strategies.
        config = ScreenerConfig(
            strategies=[Strategy("US only", "", "daily", [Rule("rsi", ">", 0)], markets=["us_stocks"])],
            etf_list=[],
            news_enabled=False,
        )
        market = Market(id="crypto", display_name="Crypto", calendar="24-7", symbol_provider="symbol-list")
        messages, screened = main_mod.screen_market(market, config)
        assert messages == []  # no scoped strategies and no themes -> nothing built

    def test_overview_sent_when_no_strategies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regression: removing all strategies must not suppress the market overview.
        monkeypatch.setattr(main_mod, "is_previous_trading_day", lambda *a, **k: True)
        monkeypatch.setattr(main_mod, "get_market_symbols", lambda m: ["AAA", "BBB"])
        monkeypatch.setattr(main_mod, "fetch_market_data", lambda *a, **k: {"AAA": _ohlcv(seed=4), "BBB": _ohlcv(seed=5)})

        config = ScreenerConfig(
            strategies=[],  # all strategies removed
            etf_list=[],
            news_enabled=False,
            themes=[Theme(id="t", market="crypto", label="ทดสอบ", symbols=["AAA", "BBB"])],
        )
        market = Market(id="crypto", display_name="Crypto", calendar="24-7", symbol_provider="symbol-list")
        messages, screened = main_mod.screen_market(market, config)
        assert len(messages) == 1  # overview-only message still ships
        assert "ภาพรวมตลาด" in messages[0]["altText"]


class TestStrategiesEnabledFlag:
    def test_default_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STRATEGIES_ENABLED", raising=False)
        assert main_mod._strategies_enabled() is True

    def test_false_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRATEGIES_ENABLED", "false")
        assert main_mod._strategies_enabled() is False

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STRATEGIES_ENABLED", "FALSE")
        assert main_mod._strategies_enabled() is False


class TestBackwardCompatConfig:
    def test_missing_markets_synthesizes_us_market(self, tmp_path) -> None:
        cfg = tmp_path / "config.json"
        cfg.write_text(
            '{"strategies": [], "etf_list": ["SPY", "QQQ"]}', encoding="utf-8"
        )
        config = load_config(cfg)
        assert len(config.markets) == 1
        m = config.markets[0]
        assert m.id == "us_stocks"
        assert m.symbol_provider == "sp500-scrape"
        assert "SPY" in m.symbols
