"""Tests for sector/theme rotation summaries and the Thai overview bubble."""

import json

import numpy as np
import pandas as pd

from screener.config import Theme
from screener.formatter import (
    MAX_BUBBLES_PER_CAROUSEL,
    MAX_CAROUSEL_BYTES,
    build_market_overview_messages,
)
from screener.market_summary import build_theme_summaries


def _series(changes: list[float]) -> pd.DataFrame:
    """Build a 60-bar OHLCV frame whose Close ends with the given daily returns.

    The last ``len(changes)`` returns are applied on top of a flat base so that
    look-back percentage changes are deterministic.
    """
    n = 60
    dates = pd.bdate_range(start="2025-01-01", periods=n)
    rets = np.concatenate([np.zeros(n - len(changes)), np.array(changes) / 100.0])
    close = 100 * np.cumprod(1 + rets)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000},
        index=dates,
    )


class TestBuildThemeSummaries:
    def test_aggregate_and_member_changes(self) -> None:
        # AAA up ~5% over the last 5 bars, BBB flat.
        up = _series([1, 1, 1, 1, 1])
        flat = _series([0, 0, 0, 0, 0])
        daily = {"AAA": up, "BBB": flat}
        theme = Theme(id="t", market="m", label="กลุ่มทดสอบ", symbols=["AAA", "BBB"])

        summaries = build_theme_summaries(daily, [theme], [5, 20])

        assert len(summaries) == 1
        s = summaries[0]
        assert s.label == "กลุ่มทดสอบ"
        # AAA ~+5.1%, BBB 0% -> average is positive but less than AAA alone.
        assert s.changes[5] is not None and 2.0 < s.changes[5] < 3.0
        # Members sorted strongest-first by the primary (20d) window.
        assert [m.symbol for m in s.members] == ["AAA", "BBB"]

    def test_missing_symbol_is_skipped(self) -> None:
        daily = {"AAA": _series([1, 1, 1])}
        theme = Theme(id="t", market="m", label="x", symbols=["AAA", "MISSING"])
        summaries = build_theme_summaries(daily, [theme], [5])
        assert [m.symbol for m in summaries[0].members] == ["AAA"]

    def test_theme_with_no_data_omitted(self) -> None:
        theme = Theme(id="t", market="m", label="x", symbols=["NOPE"])
        assert build_theme_summaries({}, [theme], [5, 20]) == []

    def test_short_history_yields_none(self) -> None:
        # 60 bars available but a 200-bar look-back has no reference point.
        daily = {"AAA": _series([1])}
        theme = Theme(id="t", market="m", label="x", symbols=["AAA"])
        s = build_theme_summaries(daily, [theme], [200])
        assert s == []  # all-None member is dropped, so theme is empty

    def test_themes_sorted_strongest_first(self) -> None:
        daily = {"UP": _series([2, 2, 2, 2, 2]), "DOWN": _series([-2, -2, -2, -2, -2])}
        themes = [
            Theme(id="weak", market="m", label="อ่อนแอ", symbols=["DOWN"]),
            Theme(id="strong", market="m", label="แข็งแกร่ง", symbols=["UP"]),
        ]
        summaries = build_theme_summaries(daily, themes, [5, 20])
        assert [s.label for s in summaries] == ["แข็งแกร่ง", "อ่อนแอ"]


class TestOverviewBubble:
    def _summaries(self, n_themes: int):
        daily = {f"SYM{i}": _series([1, -1, 1]) for i in range(n_themes * 3)}
        themes = [
            Theme(id=f"t{i}", market="m", label=f"ธีม {i}",
                  symbols=[f"SYM{i * 3 + j}" for j in range(3)])
            for i in range(n_themes)
        ]
        return build_theme_summaries(daily, themes, [5, 20])

    def test_empty_summaries_no_messages(self) -> None:
        assert build_market_overview_messages("🇹🇭 ไทย", [], [5, 20]) == []

    def test_title_is_thai_and_contains_label(self) -> None:
        msgs = build_market_overview_messages("₿ Crypto", self._summaries(2), [5, 20])
        assert len(msgs) == 1
        title = msgs[0]["contents"]["contents"][0]["header"]["contents"][0]["text"]
        assert "ภาพรวมตลาด" in title
        assert "₿ Crypto" in title

    def test_chunks_into_multiple_bubbles(self) -> None:
        # 10 themes -> ceil(10/4) = 3 bubbles, all within one carousel.
        msgs = build_market_overview_messages("🇺🇸 US", self._summaries(10), [5, 20])
        bubbles = [b for m in msgs for b in m["contents"]["contents"]]
        assert len(bubbles) == 3
        # Part labels appear when split.
        titles = [b["header"]["contents"][0]["text"] for b in bubbles]
        assert any("(1/3)" in t for t in titles)

    def test_messages_within_line_limits(self) -> None:
        msgs = build_market_overview_messages("🇺🇸 US", self._summaries(30), [5, 20])
        for msg in msgs:
            bubbles = msg["contents"]["contents"]
            assert len(bubbles) <= MAX_BUBBLES_PER_CAROUSEL
            size = len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
            assert size <= MAX_CAROUSEL_BYTES
