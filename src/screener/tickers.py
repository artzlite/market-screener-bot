import logging

import pandas as pd
import requests

from io import StringIO
from screener.config import ScreenerConfig

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
