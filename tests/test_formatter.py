"""Tests for LINE Flex Message formatting and size-aware splitting."""

import json

from screener import formatter
from screener.formatter import (
    MAX_BUBBLES_PER_CAROUSEL,
    MAX_CAROUSEL_BYTES,
    build_flex_messages,
)
from screener.strategies import ScreenerResult


def _result(ticker: str, with_news: bool = False) -> ScreenerResult:
    vals = {
        "stochastic_k": 20.0, "stochastic_k_5d": 40.0, "rsi": 25.0, "rsi_5d": 45.0,
        "macd_crossover": 1.0, "rvol": 2.4, "adx": 31.0, "roc": 3.2, "atr": 1.8,
        "change_pct": -1.5, "close": 100.0,
        "history_close_30d": [round(100 + i * 0.1, 2) for i in range(30)],
    }
    headlines = [{"title": "Some market-moving headline number %d" % i, "publisher": "X", "link": "http://x"}
                 for i in range(2)] if with_news else []
    return ScreenerResult(ticker=ticker, close_price=100.0, indicator_values=vals, headlines=headlines)


def _message_size(msg: dict) -> int:
    return len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))


class TestSizeAwareSplitting:
    def test_each_message_under_limits(self) -> None:
        # Many strategies, each with a full bubble of news-heavy rows -> many large bubbles.
        strategy_results = {
            f"Strategy {s}": [_result(f"SYM{s}{i}", with_news=True) for i in range(10)]
            for s in range(8)
        }
        messages = build_flex_messages(strategy_results, total_tickers=500, etf_list=[], market_label="🇺🇸 US")
        assert len(messages) >= 2  # forced to split
        for msg in messages:
            bubbles = msg["contents"]["contents"]
            assert len(bubbles) <= MAX_BUBBLES_PER_CAROUSEL
            assert _message_size(msg) <= MAX_CAROUSEL_BYTES

    def test_small_result_single_message(self) -> None:
        strategy_results = {"Only": [_result("AAA")]}
        messages = build_flex_messages(strategy_results, total_tickers=10, etf_list=[])
        assert len(messages) == 1
        # summary bubble + one strategy bubble
        assert len(messages[0]["contents"]["contents"]) == 2


class TestContent:
    def test_market_label_in_summary_title(self) -> None:
        messages = build_flex_messages({"S": [_result("AAA")]}, 10, [], market_label="₿ Crypto")
        summary = messages[0]["contents"]["contents"][0]
        title = summary["header"]["contents"][0]["text"]
        assert "₿ Crypto" in title

    def test_news_rendered_only_when_present(self) -> None:
        with_news = formatter._format_ticker_row(_result("AAA", with_news=True), "S")
        without_news = formatter._format_ticker_row(_result("BBB", with_news=False), "S")
        assert "📰" in json.dumps(with_news, ensure_ascii=False)
        assert "📰" not in json.dumps(without_news, ensure_ascii=False)
