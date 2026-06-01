import logging
import sys
from datetime import datetime, timezone, timedelta

import exchange_calendars as xcals

from screener.config import load_config
from screener.data_fetcher import fetch_daily_data, resample_to_weekly
from screener.formatter import build_flex_messages
from screener.indicators import calculate_all_indicators
from screener.notifier import LineNotifier
from screener.strategies import run_screener
from screener.tickers import get_all_tickers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ICT = timezone(timedelta(hours=7))


def is_previous_trading_day() -> bool:
    """Check if the previous business day was a NYSE trading day.

    Returns:
        True if the most recent weekday before today was a NYSE trading session.
    """
    nyse = xcals.get_calendar("XNYS")
    today = datetime.now(ICT).date()

    # Find the previous business day
    from datetime import timedelta as td

    check_date = today - td(days=1)
    while check_date.weekday() >= 5:  # Skip weekends
        check_date -= td(days=1)

    # Convert to pandas Timestamp for exchange_calendars
    import pandas as pd

    check_ts = pd.Timestamp(check_date)

    return nyse.is_session(check_ts)


def main() -> None:
    """Run the daily screener pipeline."""
    logger.info("=" * 60)
    logger.info("Market Screener Bot — Starting")
    logger.info("=" * 60)

    notifier: LineNotifier | None = None

    try:
        # 1. Initialize LINE notifier
        notifier = LineNotifier()

        # 2. Load configuration
        config = load_config()
        logger.info("Loaded %d strategies", len(config.strategies))

        # 3. Check if previous day was a trading day
        if not is_previous_trading_day():
            logger.info("Previous day was not a NYSE trading session. Skipping.")
            return

        # 4. Build ticker universe
        tickers = get_all_tickers(config)
        logger.info("Ticker universe: %d tickers", len(tickers))

        # 5. Fetch market data
        logger.info("Fetching daily data...")
        daily_data = fetch_daily_data(tickers, period=config.data_period)

        logger.info("Resampling to weekly...")
        weekly_data = resample_to_weekly(daily_data)

        # 6. Calculate indicators
        logger.info("Calculating indicators...")
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

        logger.info(
            "Calculated indicators: %d daily, %d weekly",
            len(daily_indicators),
            len(weekly_indicators),
        )

        # 7. Run strategies
        logger.info("Running strategies...")
        strategy_results = run_screener(daily_indicators, weekly_indicators, config)

        # 8. Build and send LINE messages
        total_signals = sum(len(r) for r in strategy_results.values())
        logger.info("Total signals found: %d", total_signals)

        flex_messages = build_flex_messages(strategy_results, len(daily_indicators), config.etf_list)

        logger.info("Sending %d LINE message(s)...", len(flex_messages))
        notifier.send_flex_messages(flex_messages)

        # 9. Summary
        logger.info("=" * 60)
        logger.info("Screening complete!")
        logger.info("Tickers screened: %d", len(daily_indicators))
        logger.info("Total signals: %d", total_signals)
        for name, results in strategy_results.items():
            logger.info("  %s: %d matches", name, len(results))
            if results:
                for r in results:
                    vals = []
                    # Gather and format indicator values that are present and not None
                    for k, v in r.indicator_values.items():
                        if k not in ("close", "history_close_30d") and v is not None:
                            vals.append(f"{k}: {v}")
                    vals_str = ", ".join(vals)
                    logger.info("    - %-5s | Close: %-7.2f | %s", r.ticker, r.close_price, vals_str)
        logger.info("=" * 60)

    except Exception as e:
        logger.exception("Screener failed: %s", e)

        # Send error alert via LINE if possible
        if notifier:
            notifier.send_error_alert(str(e))

        sys.exit(1)


if __name__ == "__main__":
    main()
