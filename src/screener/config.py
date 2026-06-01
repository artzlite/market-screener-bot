import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Rule:
    """A single screening rule."""
    indicator: str
    operator: str
    value: float


@dataclass
class Strategy:
    """A named group of rules with AND logic."""
    name: str
    description: str
    timeframe: str  # "daily" or "weekly"
    rules: list[Rule]


@dataclass
class ScreenerConfig:
    """Complete screener configuration."""
    strategies: list[Strategy]
    etf_list: list[str]
    data_period: str = "1y"
    stochastic_k_period: int = 14
    stochastic_d_period: int = 3
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    sma_period: int = 200


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

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    strategies = []
    for s in raw.get("strategies", []):
        rules = [Rule(indicator=r["indicator"], operator=r["operator"], value=r["value"]) for r in s.get("rules", [])]
        strategies.append(Strategy(
            name=s["name"], description=s.get("description", ""), timeframe=s.get("timeframe", "daily"), rules=rules
        ))

    return ScreenerConfig(
        strategies=strategies,
        etf_list=raw.get("etf_list", []),
        data_period=raw.get("data_period", "1y"),
        stochastic_k_period=raw.get("stochastic_k_period", 14),
        stochastic_d_period=raw.get("stochastic_d_period", 3),
        rsi_period=raw.get("rsi_period", 14),
        macd_fast=raw.get("macd_fast", 12),
        macd_slow=raw.get("macd_slow", 26),
        macd_signal=raw.get("macd_signal", 9),
        sma_period=raw.get("sma_period", 200),
    )
