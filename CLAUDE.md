# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the screener locally (from repo root)
cd src && python -m screener.main

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_indicators.py -v

# Run with coverage
pytest tests/ --cov=screener --cov-report=term-missing

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | — | **Required** unless `LINE_NOTIFY_ENABLED=false` |
| `LINE_NOTIFY_ENABLED` | `true` | Set `false` for dry-run (no messages sent) |
| `LINE_BROADCAST_ENABLED` | `true` | `true` = Broadcast API (all followers); `false` = Push API (single user) |
| `LINE_USER_ID` | — | Required only when `LINE_BROADCAST_ENABLED=false`, or to receive error alerts |

For local testing without LINE credentials, set `LINE_NOTIFY_ENABLED=false`.

## Architecture

The bot is **multi-market**: `config.json` defines a list of `markets`, each with its own
data source, trading calendar, and symbol provider. `main.py` loops over enabled markets and
reuses one shared indicator/strategy engine, aggregating results grouped by market → strategy.

1. **`config.py`** — Loads `config.json` into typed dataclasses (`ScreenerConfig`, `Market`, `Strategy`, `Rule`). All strategy, market, and indicator parameters live in `config.json`. **Backward compatible**: a config with no `markets` key synthesizes a single US market from the legacy `etf_list`.

2. **`tickers.py`** — `get_market_symbols(market)` dispatches on `market.symbol_provider`: `sp500-scrape` (live Wikipedia list merged with the market's symbols/ETFs) or `symbol-list`/`set100-list` (explicit list from config). SET50/SET100 use a config-maintained `.BK` list, not scraping.

3. **`sources/`** — Pluggable data adapters, each exposing `fetch(symbols, period) -> dict[str, DataFrame]` with the shared OHLCV contract (Open/High/Low/Close/Volume, tz-aware index):
   - `yfinance_source.py` — US stocks/ETFs, Thai `.BK`, commodities/FX (`GC=F`, `EURUSD=X`).
   - `binance_source.py` — crypto via **public** klines (no API key). Defaults to `data-api.binance.vision` (geo-robust; `api.binance.com`/`fapi.binance.com` return HTTP 451 from US GitHub Actions runners). Drops the still-forming last candle.
   - `data_fetcher.py` — `fetch_market_data(market, ...)` dispatcher + `resample_to_weekly()`.

4. **`indicators.py`** — Pure, symbol-agnostic functions → flat `dict[str, float | None]` per ticker. Stochastic, RSI, MACD, SMA200, plus RVOL, ATR, ROC, SMA50, Bollinger (`bb_width`), ADX, 52-week distances (`dist_52w_high/low`), and `golden_cross` (1/-1/0).

5. **`strategies.py`** — `run_screener()` applies each strategy's AND-logic rules. `Strategy.markets` optionally scopes a strategy to specific market ids (empty = all). `ScreenerResult` carries an optional `headlines` list. Timeframe routing (`daily` vs `weekly`) happens here.

6. **`news.py`** — Best-effort `fetch_headlines(symbol, count)` via yfinance's built-in news; returns `[]` on any failure. Crypto symbols map `BTCUSDT → BTC-USD`. Called only on matched results to bound API calls.

7. **`formatter.py`** — Builds LINE Flex Message JSON, accepting a `market_label` (header prefix) and `tz_offset`. Stocks/ETFs split applies only when an `etf_list` is passed (US market). Renders a compact volume/momentum line and news headlines per row.

8. **`notifier.py`** — `LineNotifier` dispatches to Broadcast or Push API, with up to 2 retries. Error alerts always use Push API (sent only to `LINE_USER_ID`, never broadcast).

## Key Design Points

- **Strategy rules are AND-logic only** — OR logic requires separate strategy entries in `config.json`.
- **Indicator values are `float | None`** — a `None` value causes the rule to fail silently (ticker is skipped). New indicators that need long history (e.g. 52-week) are `None` until enough bars exist; `data_period` is `2y` so they're robust.
- **Per-market trading-day guard** — `is_previous_trading_day(calendar_code, tz_offset)` checks the market's exchange calendar (`XNYS`, `XBKK`); `24-7` markets (crypto) always run. A closed market is skipped; the rest still run.
- **One market failing never aborts the others** — `main.py` wraps each market in try/except.
- **LINE message batching** — LINE API accepts max 5 messages per request; `send_flex_messages()` splits automatically (and the formatter splits carousels at 12 bubbles).
- **`LINE_NOTIFY_ENABLED=false`** bypasses all credential checks — use this for local testing. Crypto needs **no** secrets (public Binance data).
- **`pytest` path** — `pyproject.toml` sets `pythonpath = ["src"]`, so tests import `screener.*` directly without installing the package.
