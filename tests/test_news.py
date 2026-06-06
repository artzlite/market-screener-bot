"""Tests for the best-effort news module."""

import pytest

from screener import news


class TestNewsSymbol:
    @pytest.mark.parametrize("symbol,expected", [
        ("BTCUSDT", "BTC-USD"),
        ("ETHUSDT", "ETH-USD"),
        ("AAPL", "AAPL"),
        ("PTT.BK", "PTT.BK"),
        ("GC=F", "GC=F"),
    ])
    def test_mapping(self, symbol: str, expected: str) -> None:
        assert news._news_symbol(symbol) == expected


class TestFetchHeadlines:
    def test_zero_count_returns_empty(self) -> None:
        assert news.fetch_headlines("AAPL", count=0) == []

    def test_exception_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("network down")

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _Boom)
        assert news.fetch_headlines("AAPL", count=3) == []

    def test_parses_flat_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Ticker:
            def __init__(self, *a, **k):
                self.news = [
                    {"title": "Apple soars", "publisher": "Reuters", "link": "http://x"},
                    {"title": "Apple dips", "publisher": "CNBC", "link": "http://y"},
                ]

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _Ticker)
        out = news.fetch_headlines("AAPL", count=1)
        assert len(out) == 1
        assert out[0]["title"] == "Apple soars"

    def test_parses_nested_content_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Ticker:
            def __init__(self, *a, **k):
                self.news = [
                    {"content": {
                        "title": "BTC rallies",
                        "provider": {"displayName": "CoinDesk"},
                        "canonicalUrl": {"url": "http://z"},
                    }},
                ]

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _Ticker)
        out = news.fetch_headlines("BTCUSDT", count=3)
        assert out[0]["title"] == "BTC rallies"
        assert out[0]["publisher"] == "CoinDesk"
        assert out[0]["link"] == "http://z"
