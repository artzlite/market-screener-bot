import logging
import operator
from dataclasses import dataclass
from typing import Callable

from screener.config import Rule, Strategy, ScreenerConfig

logger = logging.getLogger(__name__)

OPERATOR_MAP: dict[str, Callable] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass
class ScreenerResult:
    """Result for a single ticker that matched a strategy."""
    ticker: str
    close_price: float
    indicator_values: dict[str, float | None]


def evaluate_rule(indicator_values: dict[str, float | None], rule: Rule) -> bool:
    """Check if a single rule is satisfied.

    Args:
        indicator_values: Dict of indicator name -> value.
        rule: The rule to evaluate.

    Returns:
        True if the rule is satisfied, False otherwise.
    """
    value = indicator_values.get(rule.indicator)
    if value is None:
        return False

    op_func = OPERATOR_MAP.get(rule.operator)
    if op_func is None:
        logger.warning("Unknown operator '%s' in rule", rule.operator)
        return False

    return op_func(value, rule.value)


def evaluate_strategy(indicator_values: dict[str, float | None], strategy: Strategy) -> bool:
    """Check if ALL rules in a strategy are satisfied (AND logic).

    Args:
        indicator_values: Dict of indicator name -> value.
        strategy: The strategy with rules to evaluate.

    Returns:
        True if all rules pass, False if any rule fails.
    """
    if not strategy.rules:
        return False

    return all(evaluate_rule(indicator_values, rule) for rule in strategy.rules)


def run_screener(
    daily_indicators: dict[str, dict[str, float | None]],
    weekly_indicators: dict[str, dict[str, float | None]],
    config: ScreenerConfig,
) -> dict[str, list[ScreenerResult]]:
    """Run all strategies against all tickers.

    Args:
        daily_indicators: Dict of ticker -> daily indicator values.
        weekly_indicators: Dict of ticker -> weekly indicator values.
        config: Screener configuration.

    Returns:
        Dict mapping strategy name to list of ScreenerResult for matched tickers.
    """
    results: dict[str, list[ScreenerResult]] = {}

    for strategy in config.strategies:
        matched: list[ScreenerResult] = []

        # Choose the right timeframe data
        if strategy.timeframe == "weekly":
            indicators = weekly_indicators
        else:
            indicators = daily_indicators

        for ticker, values in indicators.items():
            if evaluate_strategy(values, strategy):
                matched.append(ScreenerResult(
                    ticker=ticker,
                    close_price=values.get("close", 0.0),
                    indicator_values=values,
                ))

        # Sort by absolute % change descending (largest movers first), then by ticker name
        matched.sort(key=lambda r: (-abs(r.indicator_values.get("change_pct") or 0.0), r.ticker))
        results[strategy.name] = matched

        if matched:
            logger.info("Strategy '%s': %d matches", strategy.name, len(matched))
        else:
            logger.info("Strategy '%s': no matches", strategy.name)

    return results
