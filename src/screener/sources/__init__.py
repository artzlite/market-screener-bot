"""Market data source adapters.

Each source exposes ``fetch(symbols, period) -> dict[str, pd.DataFrame]`` returning
OHLCV DataFrames with columns ``Open/High/Low/Close/Volume`` and a tz-aware
``DatetimeIndex`` — the shared contract consumed by ``indicators.py``.
"""
