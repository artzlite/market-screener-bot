import logging
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals
import pandas as pd

from screener.config import Market, ScreenerConfig, load_config
from screener.data_fetcher import fetch_market_data, resample_to_weekly
from screener.formatter import build_flex_messages
from screener.indicators import calculate_all_indicators
from screener.news import fetch_headlines
from screener.notifier import LineNotifier
from screener.strategies import ScreenerResult, run_screener
from screener.tickers import get_market_symbols

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ALWAYS_ON_CALENDARS = {"24-7", "24/7", "always", "crypto", ""}

# Display labels per market id (falls back to display_name).
_MARKET_EMOJI = {
    "us_stocks": "🇺🇸",
    "thai": "🇹🇭",
    "crypto": "₿",
    "commodities": "🛢️",
}


def is_previous_trading_day(calendar_code: str, tz_offset: int = 7) -> bool:
    """Check whether the previous business day was a trading session.

    Args:
        calendar_code: exchange_calendars code (e.g. "XNYS", "XBKK") or an
            always-on marker ("24-7") for markets like crypto.
        tz_offset: Hours from UTC used to determine "today".

    Returns:
        True if the most recent weekday before today was a trading session,
        or always True for 24/7 markets.
    """
    if calendar_code.lower() in ALWAYS_ON_CALENDARS:
        return True

    calendar = xcals.get_calendar(calendar_code)
    tz = timezone(timedelta(hours=tz_offset))
    today = datetime.now(tz).date()

    check_date = today - timedelta(days=1)
    while check_date.weekday() >= 5:  # Skip weekends
        check_date -= timedelta(days=1)

    return calendar.is_session(pd.Timestamp(check_date))


def _market_label(market: Market) -> str:
    """Build the display label for a market (emoji + name)."""
    emoji = _MARKET_EMOJI.get(market.id, "")
    return f"{emoji} {market.display_name}".strip()


def _enrich_with_news(
    strategy_results: dict[str, list[ScreenerResult]], config: ScreenerConfig
) -> None:
    """Attach best-effort news headlines to matched results (in place).

    Fetches once per unique ticker across all strategies to bound API calls.
    """
    if not config.news_enabled or config.news_count <= 0:
        return

    cache: dict[str, list[dict]] = {}
    for results in strategy_results.values():
        for result in results:
            if result.ticker not in cache:
                cache[result.ticker] = fetch_headlines(result.ticker, config.news_count)
            result.headlines = cache[result.ticker]


def screen_market(market: Market, config: ScreenerConfig) -> tuple[list[dict], int]:
    """Screen a single market and return (flex_messages, tickers_screened).

    Returns an empty message list when the market is closed or has no data.
    """
    label = _market_label(market)

    if not is_previous_trading_day(market.calendar, market.timezone_offset):
        logger.info("Skipping %s — previous day was not a trading session.", label)
        return [], 0

    symbols = get_market_symbols(market)
    if not symbols:
        logger.warning("%s has no symbols configured. Skipping.", label)
        return [], 0

    logger.info("Fetching %s data (%d symbols)...", label, len(symbols))
    daily_data = fetch_market_data(
        market,
        symbols,
        period=config.data_period,
        binance_base_url=config.binance_base_url,
        binance_market=config.binance_market,
    )
    weekly_data = resample_to_weekly(daily_data)

    daily_indicators: dict[str, dict[str, float | None]] = {}
    weekly_indicators: dict[str, dict[str, float | None]] = {}
    for ticker, df in daily_data.items():
        result = calculate_all_indicators(df, config)
        if result is not None:
            daily_indicators[ticker] = result
    for ticker, df in weekly_data.items():
        result = calculate_all_indicators(df, config)
        if result is not None:
            weekly_indicators[ticker] = result

    logger.info("%s: %d daily / %d weekly with indicators", label, len(daily_indicators), len(weekly_indicators))

    # Scope strategies to this market (empty markets list = all markets).
    market_strategies = [s for s in config.strategies if not s.markets or market.id in s.markets]
    if not market_strategies:
        logger.info("%s: no strategies scoped to this market. Skipping.", label)
        return [], len(daily_indicators)

    scoped_config = replace(config, strategies=market_strategies)
    strategy_results = run_screener(daily_indicators, weekly_indicators, scoped_config)

    total_signals = sum(len(r) for r in strategy_results.values())
    logger.info("%s: %d signals", label, total_signals)

    _enrich_with_news(strategy_results, config)

    # ETF split only applies to the S&P-scraped US market.
    etf_list = config.etf_list if market.symbol_provider == "sp500-scrape" else []
    flex_messages = build_flex_messages(
        strategy_results,
        len(daily_indicators),
        etf_list,
        market_label=label,
        tz_offset=market.timezone_offset,
    )
    return flex_messages, len(daily_indicators)


def main() -> None:
    """Run the daily multi-market screener pipeline."""
    logger.info("=" * 60)
    logger.info("Market Screener Bot — Starting")
    logger.info("=" * 60)

    notifier: LineNotifier | None = None

    try:
        notifier = LineNotifier()
        config = load_config()
        enabled_markets = [m for m in config.markets if m.enabled]
        logger.info("Loaded %d strategies across %d enabled market(s)", len(config.strategies), len(enabled_markets))

        all_messages: list[dict] = []
        total_screened = 0

        for market in enabled_markets:
            try:
                messages, screened = screen_market(market, config)
            except Exception as e:
                # One market failing must not abort the others.
                logger.exception("Market '%s' failed: %s", market.id, e)
                continue
            all_messages.extend(messages)
            total_screened += screened

        if not all_messages:
            logger.info("No markets produced messages (closed or no data). Nothing to send.")
            return

        logger.info("Sending %d LINE message(s) across %d market(s)...", len(all_messages), len(enabled_markets))
        notifier.send_flex_messages(all_messages)

        logger.info("=" * 60)
        logger.info("Screening complete! Tickers screened: %d", total_screened)
        logger.info("=" * 60)

    except Exception as e:
        logger.exception("Screener failed: %s", e)
        if notifier:
            notifier.send_error_alert(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
