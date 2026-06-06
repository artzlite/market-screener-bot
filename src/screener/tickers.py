import logging
from io import StringIO

import pandas as pd
import requests

from screener.config import Market, ScreenerConfig

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> list[str]:

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/122.0 Safari/537.36"
            )
        }

        response = requests.get(
            SP500_WIKI_URL,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        html_io = StringIO(response.text)

        tables = pd.read_html(html_io)

        sp500_table = tables[0]

        tickers = (
            sp500_table["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .sort_values()
            .tolist()
        )

        return tickers

    except Exception as e:

        raise RuntimeError(
            f"Failed to fetch S&P 500 tickers: {e}"
        ) from e


def get_etf_tickers(config: ScreenerConfig) -> list[str]:
    """Get the curated ETF list from configuration."""
    return list(config.etf_list)


def get_all_tickers(config: ScreenerConfig) -> list[str]:
    """Build the complete ticker universe (S&P 500 + ETFs), deduplicated and sorted."""
    sp500 = get_sp500_tickers()
    etfs = get_etf_tickers(config)
    all_tickers = sorted(set(sp500 + etfs))
    logger.info("Total ticker universe: %d tickers (%d S&P 500 + %d ETFs)", len(all_tickers), len(sp500), len(etfs))
    return all_tickers


def get_market_symbols(market: Market) -> list[str]:
    """Resolve the symbol universe for a single market.

    Dispatches on ``market.symbol_provider``:
      - ``sp500-scrape``: live S&P 500 list merged with ``market.symbols`` (ETFs).
      - ``symbol-list`` / ``set100-list``: the explicit ``market.symbols`` list.

    SET50/SET100 use a config-maintained list (``set100-list``) rather than
    scraping: SET constituents change only quarterly and there is no stable
    machine-readable source, so a reviewable static list is more robust.

    Returns:
        Deduplicated, sorted list of symbols in the source's native format.
    """
    if market.symbol_provider == "sp500-scrape":
        base = get_sp500_tickers()
    else:
        base = []
    symbols = sorted(set(base + list(market.symbols)))
    logger.info("Market '%s': %d symbols", market.id, len(symbols))
    return symbols
