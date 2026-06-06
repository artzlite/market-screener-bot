"""Tests for strategy evaluation logic."""

import pytest

from screener.config import Rule, ScreenerConfig, Strategy
from screener.strategies import evaluate_rule, evaluate_strategy, run_screener


class TestEvaluateRule:
    """Tests for single rule evaluation."""

    @pytest.mark.parametrize("operator,value,indicator_value,expected", [
        ("<", 30, 25.0, True),
        ("<", 30, 30.0, False),
        ("<", 30, 35.0, False),
        ("<=", 30, 30.0, True),
        ("<=", 30, 25.0, True),
        ("<=", 30, 35.0, False),
        (">", 70, 75.0, True),
        (">", 70, 70.0, False),
        (">", 70, 65.0, False),
        (">=", 70, 70.0, True),
        (">=", 70, 75.0, True),
        (">=", 70, 65.0, False),
        ("==", 1, 1.0, True),
        ("==", 1, 0.0, False),
        ("!=", 0, 1.0, True),
        ("!=", 0, 0.0, False),
    ], ids=[
        "lt_true", "lt_equal_false", "lt_false",
        "le_equal_true", "le_true", "le_false",
        "gt_true", "gt_equal_false", "gt_false",
        "ge_equal_true", "ge_true", "ge_false",
        "eq_true", "eq_false",
        "ne_true", "ne_false",
    ])
    def test_operator_evaluation(
        self, operator: str, value: float, indicator_value: float, expected: bool
    ) -> None:
        """Test all supported operators with various values."""
        rule = Rule(indicator="stochastic_k", operator=operator, value=value)
        indicators = {"stochastic_k": indicator_value}
        assert evaluate_rule(indicators, rule) == expected

    def test_missing_indicator_returns_false(self) -> None:
        """Rule should return False if the indicator is not present in values."""
        rule = Rule(indicator="stochastic_k", operator="<", value=30)
        indicators = {"rsi": 25.0}  # stochastic_k is missing
        assert evaluate_rule(indicators, rule) is False

    def test_none_indicator_value_returns_false(self) -> None:
        """Rule should return False if the indicator value is None."""
        rule = Rule(indicator="rsi", operator="<", value=30)
        indicators = {"rsi": None}
        assert evaluate_rule(indicators, rule) is False

    def test_unknown_operator_returns_false(self) -> None:
        """Rule with unknown operator should return False."""
        rule = Rule(indicator="rsi", operator="~=", value=30)
        indicators = {"rsi": 25.0}
        assert evaluate_rule(indicators, rule) is False


class TestEvaluateStrategy:
    """Tests for strategy evaluation (AND logic across rules)."""

    def test_all_rules_must_match(self) -> None:
        """Strategy should only match when ALL rules are satisfied."""
        strategy = Strategy(
            name="Test",
            description="Test strategy",
            timeframe="daily",
            rules=[
                Rule(indicator="stochastic_k", operator="<", value=30),
                Rule(indicator="rsi", operator="<", value=30),
            ],
        )
        # Both conditions met
        indicators = {"stochastic_k": 20.0, "rsi": 25.0}
        assert evaluate_strategy(indicators, strategy) is True

    def test_partial_match_returns_false(self) -> None:
        """Strategy should fail if any rule is not satisfied."""
        strategy = Strategy(
            name="Test",
            description="Test strategy",
            timeframe="daily",
            rules=[
                Rule(indicator="stochastic_k", operator="<", value=30),
                Rule(indicator="rsi", operator="<", value=30),
            ],
        )
        # Only one condition met
        indicators = {"stochastic_k": 20.0, "rsi": 55.0}
        assert evaluate_strategy(indicators, strategy) is False

    def test_empty_rules_returns_false(self) -> None:
        """Strategy with no rules should return False (not match everything)."""
        strategy = Strategy(
            name="Empty",
            description="No rules",
            timeframe="daily",
            rules=[],
        )
        indicators = {"stochastic_k": 20.0, "rsi": 25.0}
        assert evaluate_strategy(indicators, strategy) is False

    def test_single_rule_strategy(self) -> None:
        """Strategy with single rule should work correctly."""
        strategy = Strategy(
            name="Single Rule",
            description="One rule only",
            timeframe="daily",
            rules=[Rule(indicator="macd_crossover", operator="==", value=1)],
        )
        assert evaluate_strategy({"macd_crossover": 1.0}, strategy) is True
        assert evaluate_strategy({"macd_crossover": 0.0}, strategy) is False


class TestRunScreener:
    """Tests for the full screener pipeline."""

    def test_run_screener_groups_by_strategy(self) -> None:
        """Results should be grouped by strategy name."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Oversold",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="stochastic_k", operator="<", value=30)],
                ),
                Strategy(
                    name="Overbought",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="stochastic_k", operator=">", value=70)],
                ),
            ],
            etf_list=[],
        )

        daily_indicators = {
            "AAPL": {"stochastic_k": 20.0, "close": 189.50},
            "MSFT": {"stochastic_k": 75.0, "close": 412.30},
            "TSLA": {"stochastic_k": 50.0, "close": 250.00},
        }

        results = run_screener(daily_indicators, {}, config)

        assert "Oversold" in results
        assert "Overbought" in results
        assert len(results["Oversold"]) == 1
        assert results["Oversold"][0].ticker == "AAPL"
        assert len(results["Overbought"]) == 1
        assert results["Overbought"][0].ticker == "MSFT"

    def test_run_screener_uses_weekly_for_weekly_strategy(self) -> None:
        """Weekly strategy should use weekly_indicators, not daily."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Weekly Oversold",
                    description="",
                    timeframe="weekly",
                    rules=[Rule(indicator="stochastic_k", operator="<", value=30)],
                ),
            ],
            etf_list=[],
        )

        daily_indicators = {
            "AAPL": {"stochastic_k": 20.0, "close": 189.50},  # Oversold daily
        }
        weekly_indicators = {
            "AAPL": {"stochastic_k": 50.0, "close": 189.50},  # NOT oversold weekly
        }

        results = run_screener(daily_indicators, weekly_indicators, config)
        assert len(results["Weekly Oversold"]) == 0  # Should NOT match weekly

    def test_run_screener_no_matches(self) -> None:
        """Screener should return empty lists when no tickers match."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Impossible",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="rsi", operator="<", value=0)],  # Impossible
                ),
            ],
            etf_list=[],
        )

        daily_indicators = {"AAPL": {"rsi": 50.0, "close": 189.50}}
        results = run_screener(daily_indicators, {}, config)
        assert results["Impossible"] == []

    def test_run_screener_results_sorted_by_ticker(self) -> None:
        """Results within each strategy should be sorted by ticker name."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Test",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="rsi", operator="<", value=50)],
                ),
            ],
            etf_list=[],
        )

        daily_indicators = {
            "TSLA": {"rsi": 30.0, "close": 250.00},
            "AAPL": {"rsi": 25.0, "close": 189.50},
            "MSFT": {"rsi": 28.0, "close": 412.30},
        }

        results = run_screener(daily_indicators, {}, config)
        tickers = [r.ticker for r in results["Test"]]
        assert tickers == ["AAPL", "MSFT", "TSLA"]

    def test_new_indicator_rules_evaluate(self) -> None:
        """Strategies referencing new indicator keys should match correctly."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Golden Cross",
                    description="",
                    timeframe="daily",
                    rules=[
                        Rule(indicator="golden_cross", operator="==", value=1),
                        Rule(indicator="adx", operator=">=", value=20),
                    ],
                ),
            ],
            etf_list=[],
        )
        daily = {
            "AAA": {"golden_cross": 1.0, "adx": 30.0, "close": 10.0, "change_pct": 1.0},
            "BBB": {"golden_cross": 0.0, "adx": 30.0, "close": 10.0, "change_pct": 1.0},
            "CCC": {"golden_cross": 1.0, "adx": 10.0, "close": 10.0, "change_pct": 1.0},
        }
        results = run_screener(daily, {}, config)
        tickers = [r.ticker for r in results["Golden Cross"]]
        assert tickers == ["AAA"]

    def test_strategy_with_markets_field_runs(self) -> None:
        """A Strategy carrying a markets scope still evaluates normally in run_screener."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Scoped",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="rsi", operator="<", value=50)],
                    markets=["crypto"],
                ),
            ],
            etf_list=[],
        )
        daily = {"AAA": {"rsi": 25.0, "close": 10.0, "change_pct": 0.0}}
        results = run_screener(daily, {}, config)
        assert len(results["Scoped"]) == 1

    def test_screener_result_contains_indicator_values(self) -> None:
        """ScreenerResult should contain the ticker's indicator values."""
        config = ScreenerConfig(
            strategies=[
                Strategy(
                    name="Test",
                    description="",
                    timeframe="daily",
                    rules=[Rule(indicator="rsi", operator="<", value=50)],
                ),
            ],
            etf_list=[],
        )

        daily_indicators = {
            "AAPL": {"rsi": 25.0, "stochastic_k": 20.0, "close": 189.50},
        }

        results = run_screener(daily_indicators, {}, config)
        result = results["Test"][0]
        assert result.ticker == "AAPL"
        assert result.close_price == 189.50
        assert result.indicator_values["rsi"] == 25.0
        assert result.indicator_values["stochastic_k"] == 20.0
