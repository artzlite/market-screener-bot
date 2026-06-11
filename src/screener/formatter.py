import json
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone

from screener.market_summary import ThemeSummary
from screener.strategies import ScreenerResult

logger = logging.getLogger(__name__)

ICT = timezone(timedelta(hours=7))

_POSITIVE_COLOR = "#27AE60"
_NEGATIVE_COLOR = "#E74C3C"
_MUTED_COLOR = "#8C8C8C"

# Thai labels for the common look-back windows; falls back to "{n} วัน".
_LOOKBACK_LABELS_TH = {1: "1 วัน", 5: "1 สัปดาห์", 20: "1 เดือน", 60: "3 เดือน"}

# How many themes to pack into a single overview bubble before splitting.
THEMES_PER_BUBBLE = 4


def _get_strategy_color(strategy_name: str) -> str:
    """Get header color based on strategy type."""
    name_lower = strategy_name.lower()
    if "overbought" in name_lower or "bearish" in name_lower:
        return "#E74C3C"  # Red for sell signals
    return "#27AE60"  # Green for buy signals


def _get_signal_emoji(strategy_name: str) -> str:
    """Get signal emoji based on strategy type."""
    name_lower = strategy_name.lower()
    if "overbought" in name_lower or "bearish" in name_lower:
        return "🔴"
    return "🟢"


def _build_quickchart_url(prices: list[float]) -> str:
    """Generate a QuickChart sparkline URL for the price history."""
    if not prices:
        return ""
    # Slice to last 30 days to save URL space and round to 1 decimal place
    recent_prices = prices[-30:]
    data_str = "[" + ",".join(f"{p:.1f}" for p in recent_prices) + "]"
    chart_json = f"{{type:'sparkline',data:{{datasets:[{{data:{data_str},borderColor:'rgba(74,144,226,1)',fill:false}}]}}}}"
    encoded = urllib.parse.quote(chart_json)
    return f"https://quickchart.io/chart?c={encoded}&w=300&h=100"


def _format_ticker_row(result: ScreenerResult, strategy_name: str) -> list[dict]:
    """Format a single ticker row for the Flex Message body.

    Returns a list of box components (ticker+price line, then indicators line).
    """
    indicator_parts = []
    vals = result.indicator_values

    if vals.get("stochastic_k") is not None:
        current = vals["stochastic_k"]
        prev = vals.get("stochastic_k_5d")
        if prev is not None:
            indicator_parts.append(f"Stoch (5d): {prev:.1f} ➔ {current:.1f}")
        else:
            indicator_parts.append(f"Stoch: {current:.1f}")

    if vals.get("rsi") is not None:
        current = vals["rsi"]
        prev = vals.get("rsi_5d")
        if prev is not None:
            indicator_parts.append(f"RSI (5d): {prev:.1f} ➔ {current:.1f}")
        else:
            indicator_parts.append(f"RSI: {current:.1f}")

    if vals.get("macd_crossover") is not None and vals["macd_crossover"] != 0:
        indicator_parts.append("MACD: ✅" if vals["macd_crossover"] == 1 else "MACD: ❌")

    # Compact volume / momentum line (only fields that are present)
    momentum_parts = []
    if vals.get("rvol") is not None:
        momentum_parts.append(f"RVOL {vals['rvol']:.1f}×")
    if vals.get("adx") is not None:
        momentum_parts.append(f"ADX {vals['adx']:.0f}")
    if vals.get("roc") is not None:
        momentum_parts.append(f"ROC {vals['roc']:+.1f}%")
    if vals.get("atr") is not None:
        momentum_parts.append(f"ATR {vals['atr']:.2f}")
    if momentum_parts:
        indicator_parts.append(" · ".join(momentum_parts))

    indicators_text = "\n".join(indicator_parts) if indicator_parts else "—"

    change_pct = vals.get("change_pct", 0.0)
    change_color = "#27AE60" if change_pct >= 0 else "#E74C3C"
    change_text = f"{change_pct:+.2f}%"

    left_contents: list[dict] = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": result.ticker, "weight": "bold", "size": "sm", "flex": 1},
                {"type": "text", "text": f"${result.close_price:.2f}", "size": "sm", "align": "start", "flex": 1},
                {"type": "text", "text": change_text, "size": "sm", "align": "end", "color": change_color, "flex": 1},
            ],
        },
        {
            "type": "text",
            "text": indicators_text,
            "size": "xs",
            "color": "#8C8C8C",
            "margin": "sm",
            "wrap": True,
        },
    ]

    # News headlines (best-effort; only rendered when present)
    for item in result.headlines:
        title = item.get("title", "")
        if not title:
            continue
        if len(title) > 45:
            title = title[:44] + "…"
        left_contents.append({
            "type": "text",
            "text": f"📰 {title}",
            "size": "xxs",
            "color": "#A0A0A0",
            "wrap": True,
        })

    left_col = {
        "type": "box",
        "layout": "vertical",
        "flex": 2,
        "contents": left_contents,
    }

    contents = [left_col]

    if vals.get("history_close_30d"):
        chart_url = _build_quickchart_url(vals["history_close_30d"])
        if chart_url:
            contents.append({
                "type": "image",
                "url": chart_url,
                "flex": 1,
                "size": "sm",
                "aspectMode": "fit",
            })

    return [
        {
            "type": "box",
            "layout": "horizontal",
            "alignItems": "center",
            "contents": contents,
        }
    ]


def format_strategy_bubble(
    display_name: str,
    display_results: list[ScreenerResult],
    total_count: int,
    show_more_count: int = 0,
) -> dict:
    """Build a Flex Message bubble for one strategy's results."""
    color = _get_strategy_color(display_name)
    emoji = _get_signal_emoji(display_name)

    # Header
    header = {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {"type": "text", "text": f"{emoji} {display_name}", "color": "#FFFFFF", "weight": "bold", "size": "md"},
        ],
        "backgroundColor": color,
        "paddingAll": "15px",
    }

    # Body - ticker rows
    body_contents: list[dict] = []

    for i, result in enumerate(display_results):
        if i > 0:
            body_contents.append({"type": "separator", "margin": "sm"})
        body_contents.extend(_format_ticker_row(result, display_name))

    if show_more_count > 0:
        body_contents.append({"type": "separator", "margin": "sm"})
        body_contents.append({
            "type": "text",
            "text": f"... and {show_more_count} more",
            "size": "xs",
            "color": "#8C8C8C",
            "margin": "sm",
        })

    body = {
        "type": "box",
        "layout": "vertical",
        "contents": body_contents,
        "paddingAll": "15px",
        "spacing": "sm",
    }

    # Footer
    footer = {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "text",
                "text": f"{total_count} ticker{'s' if total_count != 1 else ''} matched",
                "size": "xs",
                "color": "#8C8C8C",
                "align": "center",
            },
        ],
        "paddingAll": "10px",
    }

    return {
        "type": "bubble",
        "size": "kilo",
        "header": header,
        "body": body,
        "footer": footer,
    }


def format_summary_bubble(
    total_tickers: int,
    strategy_results: dict[str, list[ScreenerResult]],
    etf_list: list[str],
    market_label: str = "",
    tz_offset: int = 7,
) -> dict:
    """Build a summary bubble showing screening overview."""
    now = datetime.now(timezone(timedelta(hours=tz_offset)))
    total_signals = sum(len(results) for results in strategy_results.values())
    title = f"📊 {market_label} Summary" if market_label else "📊 Daily Screener Summary"

    strategy_lines: list[dict] = []
    for name, results in strategy_results.items():
        # Only split into Stocks/ETFs when an ETF list is provided (US market).
        if etf_list:
            stocks = [r for r in results if r.ticker not in etf_list]
            etfs = [r for r in results if r.ticker in etf_list]
        else:
            stocks = list(results)
            etfs = []
        emoji = _get_signal_emoji(name)

        stocks_label = f"{emoji} {name} - Stocks" if etf_list else f"{emoji} {name}"
        if stocks or etfs:
            if stocks:
                strategy_lines.append({
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": stocks_label, "size": "xs", "flex": 4, "wrap": True},
                        {"type": "text", "text": str(len(stocks)), "size": "xs", "align": "end", "flex": 1, "weight": "bold"},
                    ],
                })
            if etfs:
                strategy_lines.append({
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"{emoji} {name} - ETFs", "size": "xs", "flex": 4, "wrap": True},
                        {"type": "text", "text": str(len(etfs)), "size": "xs", "align": "end", "flex": 1, "weight": "bold"},
                    ],
                })
        else:
            strategy_lines.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"{emoji} {name}", "size": "xs", "flex": 4, "wrap": True},
                    {"type": "text", "text": "0", "size": "xs", "align": "end", "flex": 1, "weight": "bold"},
                ],
            })

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": title,
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "md",
                },
            ],
            "backgroundColor": "#4A90D9",
            "paddingAll": "15px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": now.strftime("%A, %B %d, %Y"), "size": "xs", "color": "#8C8C8C"},
                {"type": "separator", "margin": "md"},
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "Tickers screened", "size": "sm", "flex": 3},
                        {
                            "type": "text",
                            "text": str(total_tickers),
                            "size": "sm",
                            "weight": "bold",
                            "align": "end",
                            "flex": 1,
                        },
                    ],
                    "margin": "md",
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": "Total signals", "size": "sm", "flex": 3},
                        {
                            "type": "text",
                            "text": str(total_signals),
                            "size": "sm",
                            "weight": "bold",
                            "align": "end",
                            "flex": 1,
                        },
                    ],
                },
                {"type": "separator", "margin": "md"},
                *strategy_lines,
            ],
            "paddingAll": "15px",
            "spacing": "sm",
        },
    }


def build_flex_messages(
    strategy_results: dict[str, list[ScreenerResult]],
    total_tickers: int,
    etf_list: list[str],
    market_label: str = "",
    tz_offset: int = 7,
) -> list[dict]:
    """Build complete Flex Message payloads for LINE.

    Creates a carousel with a summary bubble + up to 2 bubbles per strategy/asset type with matches.
    Splits into multiple messages if exceeding LINE's 12-bubble carousel limit.

    Args:
        strategy_results: Dict of strategy name -> matched tickers.
        total_tickers: Total number of tickers screened.
        etf_list: List of ETF tickers to distinguish stocks vs ETFs. When empty,
            no stocks/ETFs split is applied (used for non-US markets).
        market_label: Optional market name shown in headers (e.g. "🇺🇸 US Stocks").
        tz_offset: Hours from UTC for the summary timestamp.

    Returns:
        List of Flex Message dicts ready to send via LINE API.
    """
    prefix = f"{market_label} · " if market_label else ""
    bubbles: list[dict] = []

    # Summary bubble first
    bubbles.append(format_summary_bubble(total_tickers, strategy_results, etf_list, market_label, tz_offset))

    # Strategy bubbles (split into Stocks and ETFs only when an ETF list exists)
    for name, results in strategy_results.items():
        if not results:
            continue

        if etf_list:
            asset_groups = [
                ("Stocks", [r for r in results if r.ticker not in etf_list]),
                ("ETFs", [r for r in results if r.ticker in etf_list]),
            ]
        else:
            asset_groups = [("", list(results))]

        for asset_type, asset_results in asset_groups:
            if not asset_results:
                continue

            suffix = f" - {asset_type}" if asset_type else ""
            total_count = len(asset_results)
            if total_count <= 10:
                display_name = f"{prefix}{name}{suffix}"
                bubbles.append(format_strategy_bubble(display_name, asset_results, total_count))
            else:
                # Bubble 1 (1/2): first 10
                display_name_1 = f"{prefix}{name}{suffix} (1/2)"
                bubbles.append(format_strategy_bubble(display_name_1, asset_results[:10], total_count))

                # Bubble 2 (2/2): next 10, plus show_more_count if total_count > 20
                display_name_2 = f"{prefix}{name}{suffix} (2/2)"
                show_more_count = max(0, total_count - 20)
                bubbles.append(format_strategy_bubble(display_name_2, asset_results[10:20], total_count, show_more_count))

    alt_text = f"📊 {market_label} Screener Results" if market_label else "📊 Daily Stock Screener Results"
    return _bubbles_to_messages(bubbles, alt_text)


# ---------------------------------------------------------------------------
# Market-overview (sector/theme rotation) — Thai-language bubble
# ---------------------------------------------------------------------------


def _lookback_label(lookback: int) -> str:
    """Thai column header for a look-back window."""
    return _LOOKBACK_LABELS_TH.get(lookback, f"{lookback} วัน")


def _display_symbol(symbol: str) -> str:
    """Trim exchange/quote suffixes for a compact label (BTCUSDT → BTC)."""
    for suffix in ("USDT", ".BK", "=X", "=F"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)] or symbol
    return symbol


def _change_cell(value: float | None, *, weight: str | None = None) -> dict:
    """A right-aligned percentage cell, green for gains and red for losses."""
    if value is None:
        text, color = "–", _MUTED_COLOR
    else:
        text = f"{value:+.1f}%"
        color = _POSITIVE_COLOR if value >= 0 else _NEGATIVE_COLOR
    cell = {"type": "text", "text": text, "size": "xs", "align": "end", "flex": 2, "color": color}
    if weight:
        cell["weight"] = weight
    return cell


def _overview_row(label: str, changes: dict[int, float | None], lookbacks: list[int], *, header: bool) -> dict:
    """One row: a label on the left and a change cell per look-back on the right."""
    name_cell = {"type": "text", "text": label, "size": "xs", "flex": 5, "wrap": True}
    if header:
        name_cell["weight"] = "bold"
    contents = [name_cell]
    for lb in lookbacks:
        contents.append(_change_cell(changes.get(lb), weight="bold" if header else None))
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": contents,
        "margin": "md" if header else "sm",
    }


def _theme_block(summary: ThemeSummary, lookbacks: list[int]) -> list[dict]:
    """Theme header row (aggregate) followed by indented member rows."""
    primary = summary.changes.get(lookbacks[-1])
    arrow = "🔻" if (primary is not None and primary < 0) else "🔺"
    block: list[dict] = [_overview_row(f"{arrow} {summary.label}", summary.changes, lookbacks, header=True)]
    for member in summary.members:
        block.append(_overview_row(f"   {_display_symbol(member.symbol)}", member.changes, lookbacks, header=False))
    return block


def format_market_overview_bubble(
    market_label: str,
    summaries: list[ThemeSummary],
    lookbacks: list[int],
    tz_offset: int = 7,
    part: tuple[int, int] | None = None,
) -> dict:
    """Build one Thai market-overview bubble for a slice of themes."""
    now = datetime.now(timezone(timedelta(hours=tz_offset)))
    title = f"📊 ภาพรวมตลาด {market_label}".strip()
    if part:
        title += f" ({part[0]}/{part[1]})"

    # Column-header row labelling each look-back window.
    column_header = _overview_row("กลุ่ม / เธีม", dict.fromkeys(lookbacks), lookbacks, header=True)
    column_header["contents"][0]["color"] = _MUTED_COLOR
    for i, lb in enumerate(lookbacks, start=1):
        column_header["contents"][i] = {
            "type": "text", "text": _lookback_label(lb), "size": "xxs",
            "align": "end", "flex": 2, "color": _MUTED_COLOR, "weight": "bold",
        }

    body_contents: list[dict] = [
        {"type": "text", "text": now.strftime("%A, %B %d, %Y"), "size": "xs", "color": _MUTED_COLOR},
        column_header,
        {"type": "separator", "margin": "sm"},
    ]
    for i, summary in enumerate(summaries):
        if i > 0:
            body_contents.append({"type": "separator", "margin": "sm"})
        body_contents.extend(_theme_block(summary, lookbacks))

    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [{"type": "text", "text": title, "color": "#FFFFFF", "weight": "bold", "size": "md", "wrap": True}],
            "backgroundColor": "#34495E",
            "paddingAll": "15px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": body_contents,
            "paddingAll": "15px",
            "spacing": "sm",
        },
    }


def build_market_overview_messages(
    market_label: str,
    summaries: list[ThemeSummary],
    lookbacks: list[int],
    tz_offset: int = 7,
) -> list[dict]:
    """Build LINE flex message(s) for a market's sector/theme overview.

    Themes are chunked into bubbles (``THEMES_PER_BUBBLE`` each) and packed into
    carousels honoring LINE's bubble-count and 50 KB limits.

    Returns an empty list when there are no summaries.
    """
    if not summaries or not lookbacks:
        return []

    chunks = [summaries[i : i + THEMES_PER_BUBBLE] for i in range(0, len(summaries), THEMES_PER_BUBBLE)]
    total = len(chunks)
    bubbles = [
        format_market_overview_bubble(
            market_label, chunk, lookbacks, tz_offset,
            part=(idx, total) if total > 1 else None,
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]
    return _bubbles_to_messages(bubbles, f"📊 ภาพรวมตลาด {market_label}".strip())


# LINE limits: a carousel may hold at most 12 bubbles, and the JSON that defines
# a single flex message must be ≤ 50 KB. With sparkline images + news lines a full
# 12-bubble carousel can exceed 50 KB, so we also split by serialized byte size.
MAX_BUBBLES_PER_CAROUSEL = 10
MAX_CAROUSEL_BYTES = 48_000  # margin under LINE's 50 KB hard limit


def _carousel_message(bubbles: list[dict], alt_text: str) -> dict:
    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {"type": "carousel", "contents": bubbles},
    }


def _message_bytes(bubbles: list[dict], alt_text: str) -> int:
    payload = _carousel_message(bubbles, alt_text)
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _bubbles_to_messages(bubbles: list[dict], alt_text: str) -> list[dict]:
    """Pack bubbles into flex messages, honoring both the bubble-count and 50 KB limits."""
    messages: list[dict] = []
    current: list[dict] = []

    for bubble in bubbles:
        candidate = current + [bubble]
        too_many = len(candidate) > MAX_BUBBLES_PER_CAROUSEL
        too_big = _message_bytes(candidate, alt_text) > MAX_CAROUSEL_BYTES
        if current and (too_many or too_big):
            messages.append(_carousel_message(current, alt_text))
            current = [bubble]
        else:
            current = candidate

    if current:
        messages.append(_carousel_message(current, alt_text))

    return messages
