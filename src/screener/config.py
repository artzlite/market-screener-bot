import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SUMMARY_LOOKBACKS = [5, 20]


@dataclass
class Rule:
    """A single screening rule."""
    indicator: str
    operator: str
    value: float


@dataclass
class Strategy:
    """A named group of rules with AND logic.

    ``markets`` optionally scopes the strategy to specific market ids. An empty
    list (the default) means the strategy applies to every market.
    """
    name: str
    description: str
    timeframe: str  # "daily" or "weekly"
    rules: list[Rule]
    markets: list[str] = field(default_factory=list)


@dataclass
class Theme:
    """A named basket of symbols used for the market-overview summary.

    Themes group already-tracked symbols (no extra data is fetched) so the bot
    can report sector/theme rotation, e.g. "พลังงาน (Energy) -10%".

    Attributes:
        id: Stable identifier.
        market: Market id this theme belongs to (matches ``Market.id``).
        label: Human-readable (Thai) label shown in the overview bubble.
        symbols: Symbols that make up the theme; must be a subset of the
            market's tracked symbols.
    """
    id: str
    market: str
    label: str
    symbols: list[str] = field(default_factory=list)


@dataclass
class Market:
    """A screening universe with its own data source and trading calendar.

    Attributes:
        id: Stable identifier used to scope strategies and group results.
        display_name: Human-readable name shown in notifications.
        source: Data source — "yfinance" or "binance".
        calendar: exchange_calendars code ("XNYS", "XBKK") or "24-7" for always-on.
        symbol_provider: "sp500-scrape", "symbol-list", or "set100-list".
        timezone_offset: Hours from UTC, used for the trading-day guard and display.
        asset_type: Optional label (e.g. "Crypto", "FX") shown in the card.
        symbols: Explicit symbols (used by symbol-list/set100-list, merged for sp500-scrape).
        enabled: Whether this market is screened.
    """
    id: str
    display_name: str
    source: str = "yfinance"
    calendar: str = "XNYS"
    symbol_provider: str = "symbol-list"
    timezone_offset: int = 7
    asset_type: str = ""
    symbols: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class ScreenerConfig:
    """Complete screener configuration."""
    strategies: list[Strategy]
    etf_list: list[str]
    markets: list[Market] = field(default_factory=list)
    themes: list[Theme] = field(default_factory=list)
    data_period: str = "1y"
    stochastic_k_period: int = 14
    stochastic_d_period: int = 3
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    sma_period: int = 200
    # New volume / momentum / breakout indicator params
    sma_short_period: int = 50
    rvol_period: int = 20
    atr_period: int = 14
    roc_period: int = 12
    bb_period: int = 20
    bb_std: float = 2.0
    adx_period: int = 14
    high_low_period: int = 252
    # News
    news_enabled: bool = True
    news_count: int = 3
    # Market-overview summary (sector/theme rotation bubble)
    summary_enabled: bool = True
    summary_lookbacks: list[int] = field(default_factory=lambda: [5, 20])
    # Binance source (public market data — no API key needed).
    # data-api.binance.vision is geo-robust (works on US GitHub Actions runners).
    binance_base_url: str = "https://data-api.binance.vision"
    binance_market: str = "spot"  # "spot" or "futures"


def _parse_market(m: dict) -> Market:
    """Build a Market from a raw config dict."""
    return Market(
        id=m["id"],
        display_name=m.get("display_name", m["id"]),
        source=m.get("source", "yfinance"),
        calendar=m.get("calendar", "XNYS"),
        symbol_provider=m.get("symbol_provider", "symbol-list"),
        timezone_offset=m.get("timezone_offset", 7),
        asset_type=m.get("asset_type", ""),
        symbols=list(m.get("symbols", [])),
        enabled=m.get("enabled", True),
    )


def load_config(config_path: str | Path | None = None) -> ScreenerConfig:
    """Load and validate configuration from JSON file.

    Args:
        config_path: Path to config.json. Defaults to config.json in project root.

    Returns:
        Validated ScreenerConfig instance.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config is invalid.
    """
    if config_path is None:
        # Default: look for config.json in project root (2 levels up from this file)
        config_path = Path(__file__).parent.parent.parent / "config.json"

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)

    strategies = []
    for s in raw.get("strategies", []):
        rules = [Rule(indicator=r["indicator"], operator=r["operator"], value=r["value"]) for r in s.get("rules", [])]
        strategies.append(Strategy(
            name=s["name"],
            description=s.get("description", ""),
            timeframe=s.get("timeframe", "daily"),
            rules=rules,
            markets=list(s.get("markets", [])),
        ))

    etf_list = raw.get("etf_list", [])

    themes = [
        Theme(
            id=t["id"],
            market=t["market"],
            label=t.get("label", t["id"]),
            symbols=list(t.get("symbols", [])),
        )
        for t in raw.get("themes", [])
    ]

    markets = [_parse_market(m) for m in raw.get("markets", [])]
    if not markets:
        # Backward compatibility: synthesize a single US market from the legacy
        # config so existing config.json files keep working unchanged.
        markets = [Market(
            id="us_stocks",
            display_name="US Stocks & ETFs",
            source="yfinance",
            calendar="XNYS",
            symbol_provider="sp500-scrape",
            timezone_offset=7,
            symbols=list(etf_list),
        )]

    return ScreenerConfig(
        strategies=strategies,
        etf_list=etf_list,
        markets=markets,
        themes=themes,
        data_period=raw.get("data_period", "1y"),
        stochastic_k_period=raw.get("stochastic_k_period", 14),
        stochastic_d_period=raw.get("stochastic_d_period", 3),
        rsi_period=raw.get("rsi_period", 14),
        macd_fast=raw.get("macd_fast", 12),
        macd_slow=raw.get("macd_slow", 26),
        macd_signal=raw.get("macd_signal", 9),
        sma_period=raw.get("sma_period", 200),
        sma_short_period=raw.get("sma_short_period", 50),
        rvol_period=raw.get("rvol_period", 20),
        atr_period=raw.get("atr_period", 14),
        roc_period=raw.get("roc_period", 12),
        bb_period=raw.get("bb_period", 20),
        bb_std=raw.get("bb_std", 2.0),
        adx_period=raw.get("adx_period", 14),
        high_low_period=raw.get("high_low_period", 252),
        news_enabled=raw.get("news_enabled", True),
        news_count=raw.get("news_count", 3),
        summary_enabled=raw.get("summary_enabled", True),
        summary_lookbacks=list(raw.get("summary_lookbacks", DEFAULT_SUMMARY_LOOKBACKS)),
        binance_base_url=raw.get("binance_base_url", "https://data-api.binance.vision"),
        binance_market=raw.get("binance_market", "spot"),
    )
