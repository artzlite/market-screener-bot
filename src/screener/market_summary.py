"""Sector/theme rotation summary built from already-fetched daily OHLCV.

This module turns the per-market ``daily_data`` (the same DataFrames used for
indicators) into a high-level overview: for each configured :class:`Theme` it
computes every member's percentage change over a few look-back windows
(e.g. 5d = 1 week, 20d = 1 month) and the theme's average move.

No additional data is fetched — themes only reference symbols the market
already tracks, so this is a cheap, best-effort enrichment.
"""

from dataclasses import dataclass

import pandas as pd

from screener.config import Theme


@dataclass
class MemberChange:
    """One symbol's percentage change per look-back window."""
    symbol: str
    changes: dict[int, float | None]  # lookback (bars) -> pct change


@dataclass
class ThemeSummary:
    """A theme's aggregate move plus its member breakdown."""
    label: str
    changes: dict[int, float | None]  # lookback -> average pct change
    members: list[MemberChange]


def _pct_change(df: pd.DataFrame, lookback: int) -> float | None:
    """Percentage change of Close over ``lookback`` bars, or None if too short."""
    close = df["Close"].dropna()
    if len(close) <= lookback:
        return None
    last = close.iloc[-1]
    prev = close.iloc[-1 - lookback]
    if pd.isna(last) or pd.isna(prev) or prev == 0:
        return None
    return float((last / prev - 1) * 100)


def _average(values: list[float | None]) -> float | None:
    """Mean of the non-None values, or None when all are missing."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return float(sum(present) / len(present))


def build_theme_summaries(
    daily_data: dict[str, pd.DataFrame],
    themes: list[Theme],
    lookbacks: list[int],
) -> list[ThemeSummary]:
    """Compute theme summaries, sorted strongest-first by the longest look-back.

    Args:
        daily_data: Ticker -> daily OHLCV DataFrame (the fetched market data).
        themes: Themes scoped to the current market.
        lookbacks: Bar counts to measure change over (e.g. ``[5, 20]``). The
            last entry is treated as the primary window for sorting.

    Returns:
        List of :class:`ThemeSummary`, themes with no available data omitted.
        Members within a theme and themes overall are sorted by the primary
        window's change, descending (strongest first).
    """
    if not lookbacks:
        return []
    primary = lookbacks[-1]
    summaries: list[ThemeSummary] = []

    for theme in themes:
        members: list[MemberChange] = []
        for symbol in theme.symbols:
            df = daily_data.get(symbol)
            if df is None or df.empty:
                continue
            changes = {lb: _pct_change(df, lb) for lb in lookbacks}
            if all(v is None for v in changes.values()):
                continue
            members.append(MemberChange(symbol=symbol, changes=changes))

        if not members:
            continue

        agg = {lb: _average([m.changes.get(lb) for m in members]) for lb in lookbacks}
        members.sort(key=lambda m: _sort_key(m.changes.get(primary)))
        summaries.append(ThemeSummary(label=theme.label, changes=agg, members=members))

    summaries.sort(key=lambda s: _sort_key(s.changes.get(primary)))
    return summaries


def _sort_key(value: float | None) -> tuple[bool, float]:
    """Sort helper: present values descending, missing values last."""
    return (value is None, -(value or 0.0))
