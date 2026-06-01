import logging
import urllib.parse
from datetime import datetime, timezone, timedelta

from screener.strategies import ScreenerResult

logger = logging.getLogger(__name__)

ICT = timezone(timedelta(hours=7))


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
    data_str = "[" + ",".join(str(p) for p in prices) + "]"
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

    indicators_text = "\n".join(indicator_parts) if indicator_parts else "—"

    change_pct = vals.get("change_pct", 0.0)
    change_color = "#27AE60" if change_pct >= 0 else "#E74C3C"
    change_text = f"{change_pct:+.2f}%"

    left_col = {
        "type": "box",
        "layout": "vertical",
        "flex": 2,
        "contents": [
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
        ],
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
) -> dict:
    """Build a summary bubble showing screening overview."""
    now = datetime.now(ICT)
    total_signals = sum(len(results) for results in strategy_results.values())

    strategy_lines: list[dict] = []
    for name, results in strategy_results.items():
        stocks = [r for r in results if r.ticker not in etf_list]
        etfs = [r for r in results if r.ticker in etf_list]
        emoji = _get_signal_emoji(name)
        
        if stocks or etfs:
            if stocks:
                strategy_lines.append({
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"{emoji} {name} - Stocks", "size": "xs", "flex": 4, "wrap": True},
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
                    "text": "📊 Daily Screener Summary",
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
) -> list[dict]:
    """Build complete Flex Message payloads for LINE.

    Creates a carousel with a summary bubble + up to 2 bubbles per strategy/asset type with matches.
    Splits into multiple messages if exceeding LINE's 12-bubble carousel limit.

    Args:
        strategy_results: Dict of strategy name -> matched tickers.
        total_tickers: Total number of tickers screened.
        etf_list: List of ETF tickers to distinguish stocks vs ETFs.

    Returns:
        List of Flex Message dicts ready to send via LINE API.
    """
    bubbles: list[dict] = []

    # Summary bubble first
    bubbles.append(format_summary_bubble(total_tickers, strategy_results, etf_list))

    # Strategy bubbles (split into Stocks and ETFs, up to 2 bubbles each)
    for name, results in strategy_results.items():
        if not results:
            continue

        stocks = [r for r in results if r.ticker not in etf_list]
        etfs = [r for r in results if r.ticker in etf_list]

        for asset_type, asset_results in [("Stocks", stocks), ("ETFs", etfs)]:
            if not asset_results:
                continue

            total_count = len(asset_results)
            if total_count <= 10:
                display_name = f"{name} - {asset_type}"
                bubbles.append(format_strategy_bubble(display_name, asset_results, total_count))
            else:
                # Bubble 1 (1/2): first 10
                display_name_1 = f"{name} - {asset_type} (1/2)"
                bubbles.append(format_strategy_bubble(display_name_1, asset_results[:10], total_count))
                
                # Bubble 2 (2/2): next 10, plus show_more_count if total_count > 20
                display_name_2 = f"{name} - {asset_type} (2/2)"
                show_more_count = max(0, total_count - 20)
                bubbles.append(format_strategy_bubble(display_name_2, asset_results[10:20], total_count, show_more_count))

    # Split into chunks of 12 (LINE carousel limit)
    messages: list[dict] = []
    for i in range(0, len(bubbles), 12):
        chunk = bubbles[i : i + 12]
        messages.append({
            "type": "flex",
            "altText": "📊 Daily Stock Screener Results",
            "contents": {
                "type": "carousel",
                "contents": chunk,
            },
        })

    return messages
