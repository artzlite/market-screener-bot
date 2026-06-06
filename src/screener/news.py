"""Best-effort news headlines via yfinance's built-in news.

yfinance's ``.news`` is undocumented and its schema varies between versions and
asset classes, so every call here is wrapped to return ``[]`` on any failure —
news is decorative and must never break the screening pipeline.
"""
import logging

logger = logging.getLogger(__name__)


def _news_symbol(symbol: str) -> str:
    """Map a screening symbol to the symbol yfinance news understands.

    Crypto perp/spot pairs like ``BTCUSDT`` have no yfinance news; map them to
    the Yahoo crypto ticker ``BTC-USD``. Other symbols pass through unchanged.
    """
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USD"
    if symbol.endswith("USD") and "-" not in symbol and len(symbol) > 3:
        return symbol[:-3] + "-USD"
    return symbol


def _extract(item: dict) -> dict | None:
    """Normalize one yfinance news item across schema versions."""
    # Newer yfinance nests fields under "content"; older versions are flat.
    content = item.get("content", item) if isinstance(item, dict) else {}
    title = content.get("title") or item.get("title")
    if not title:
        return None
    publisher = (
        content.get("provider", {}).get("displayName")
        if isinstance(content.get("provider"), dict)
        else content.get("publisher") or item.get("publisher", "")
    )
    link = ""
    if isinstance(content.get("canonicalUrl"), dict):
        link = content["canonicalUrl"].get("url", "")
    link = link or content.get("link") or item.get("link", "")
    return {"title": str(title), "publisher": str(publisher or ""), "link": str(link or "")}


def fetch_headlines(symbol: str, count: int = 3) -> list[dict]:
    """Return up to ``count`` recent headlines for ``symbol``.

    Best-effort: returns ``[]`` on any error or if no news is available.

    Args:
        symbol: Screening symbol (US ticker, ``.BK``, or crypto pair).
        count: Maximum number of headlines.

    Returns:
        List of dicts with ``title``, ``publisher``, ``link``.
    """
    if count <= 0:
        return []
    try:
        import yfinance as yf

        raw = yf.Ticker(_news_symbol(symbol)).news or []
        headlines = []
        for item in raw:
            parsed = _extract(item)
            if parsed:
                headlines.append(parsed)
            if len(headlines) >= count:
                break
        return headlines
    except Exception as e:  # pragma: no cover - network/library variance
        logger.debug("News fetch failed for %s: %s", symbol, e)
        return []
