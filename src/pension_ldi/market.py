"""Fetch public market proxies and align a monthly CAD calibration panel."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

SAMPLE_START = "2012-01-01"
SAMPLE_END = "2026-10-21"
DEFAULT_MARKET_PATH = Path("data/market.csv")
DEFAULT_CURVE_PATH = Path("data/curve.csv")
CURVE_URL = "https://www.bankofcanada.ca/stats/results/csv"
CURVE_TENORS = (0.25, 1, 2, 5, 10, 15, 20, 25, 30)
BOC_COLUMNS = {
    "ZC025YR": "y_0_25", "ZC100YR": "y_1", "ZC200YR": "y_2",
    "ZC500YR": "y_5", "ZC1000YR": "y_10", "ZC1500YR": "y_15",
    "ZC2000YR": "y_20", "ZC2500YR": "y_25", "ZC3000YR": "y_30",
}
YIELD_COLUMNS = tuple(BOC_COLUMNS.values())
ASSET_BASKETS = {
    "public_equity": {"XIU.TO": 0.5, "VFV.TO": 0.5},
    "long_bonds": {"XLB.TO": 1.0},
    "real_assets": {"ZRE.TO": 0.5, "IGF": 0.5},
    "private_equity": {"PSP": 1.0},
    "credit": {"XCB.TO": 1.0},
}
ASSET_NAMES = tuple(ASSET_BASKETS)
MARKET_COLUMNS = (*ASSET_NAMES, *YIELD_COLUMNS)
FX_TICKER = "USDCAD=X"
USD_TICKERS = ("IGF", "PSP")
TICKERS = tuple(ticker for basket in ASSET_BASKETS.values() for ticker in basket)
MONTH_END_TOLERANCE = pd.Timedelta(days=7)


def _validate(panel: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    if (
        panel.empty
        or not isinstance(panel.index, pd.DatetimeIndex)
        or panel.index.hasnans
        or panel.index.has_duplicates
        or not panel.index.is_monotonic_increasing
    ):
        raise ValueError("Require a nonempty, ordered panel with unique dates")
    if missing := set(columns).difference(panel.columns):
        raise ValueError(f"Missing data columns: {', '.join(sorted(missing))}")
    selected = panel.loc[:, list(columns)]
    if not np.isfinite(selected.to_numpy(dtype=float)).all():
        raise ValueError("Market levels and zero yields must be finite")
    return selected


def _consecutive_months(index: pd.DatetimeIndex) -> None:
    periods = index.to_period("M")
    expected = pd.period_range(periods.min(), periods.max(), freq="M")
    if not periods.equals(expected):
        raise ValueError("Calibration requires one joint observation per consecutive month")


def align_market(quotes: pd.DataFrame, curve: pd.DataFrame, end: str | pd.Timestamp) -> pd.DataFrame:
    """Use observed joint month-ends and chain monthly CAD proxy returns."""
    end_date = pd.Timestamp(end).normalize()
    completed_month_end = pd.offsets.MonthEnd().rollback(end_date)
    levels = quotes.loc[:, [*TICKERS, FX_TICKER]]
    joint = pd.concat([levels, curve.loc[:, list(YIELD_COLUMNS)]], axis=1, join="inner")
    joint = joint.sort_index().loc[:completed_month_end].dropna()
    joint = _validate(joint, (*TICKERS, FX_TICKER, *YIELD_COLUMNS))
    if (joint.loc[:, [*TICKERS, FX_TICKER]] <= 0).any().any():
        raise ValueError("Adjusted price levels and USD/CAD spot must be positive")

    month_ends = joint.groupby(joint.index.to_period("M")).tail(1)
    if len(month_ends) < 2:
        raise ValueError("Calibration requires at least two completed months")
    _consecutive_months(month_ends.index)
    gaps = month_ends.index + pd.offsets.MonthEnd(0) - month_ends.index
    if (gaps > MONTH_END_TOLERANCE).any() or month_ends.index[-1].to_period("M") != completed_month_end.to_period("M"):
        raise ValueError("Missing a joint market close within seven days of a completed month-end")

    cad_prices = month_ends.loc[:, list(TICKERS)].copy()
    cad_prices.loc[:, list(USD_TICKERS)] = cad_prices.loc[:, list(USD_TICKERS)].mul(
        month_ends[FX_TICKER], axis=0,
    )
    returns = cad_prices.pct_change(fill_method=None)
    asset_levels = pd.DataFrame(index=month_ends.index)
    for sleeve, weights in ASSET_BASKETS.items():
        weighted_returns = returns.loc[:, list(weights)] @ pd.Series(weights)
        asset_levels[sleeve] = 100 * (1 + weighted_returns.fillna(0)).cumprod()
    panel = asset_levels.join(month_ends.loc[:, list(YIELD_COLUMNS)]).rename_axis("date")
    return _validate(panel, MARKET_COLUMNS)


def load_market(path: str | Path = DEFAULT_MARKET_PATH) -> pd.DataFrame:
    """Read a locally downloaded monthly panel."""
    panel = _validate(_load_csv(path), MARKET_COLUMNS)
    _consecutive_months(panel.index)
    if (panel.loc[:, list(ASSET_NAMES)] <= 0).any().any():
        raise ValueError("Asset levels must be positive")
    return panel


def load_curve(path: str | Path = DEFAULT_CURVE_PATH) -> np.ndarray:
    """Read the separate dated BoC valuation snapshot in tenor order."""
    curve = _validate(_load_csv(path), YIELD_COLUMNS)
    if len(curve) != 1:
        raise ValueError("The valuation curve must have exactly one dated row")
    return curve.iloc[0].to_numpy(dtype=float)


def _load_csv(path: str | Path) -> pd.DataFrame:
    local_path = Path(path)
    if not local_path.is_file():
        raise FileNotFoundError(f"{local_path} is missing. Run python -m pension_ldi.market first.")
    return pd.read_csv(local_path, parse_dates=["date"], index_col="date")


def _yahoo_quotes(yf, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    # Sequential requests avoid simultaneous writes to yfinance's SQLite cache.
    series = {}
    for ticker in (*TICKERS, FX_TICKER):
        history = yf.Ticker(ticker).history(
            start=start.date().isoformat(),
            end=(end + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=False, actions=False, timeout=35,
        )
        column = "Close" if ticker == FX_TICKER else "Adj Close"
        if history.empty or column not in history or history[column].dropna().empty:
            raise RuntimeError(f"Yahoo Finance returned no {column} for {ticker}. Try again.")
        index = history.index.tz_localize(None).normalize()
        series[ticker] = pd.Series(history[column].to_numpy(dtype=float), index=index)
    return pd.DataFrame(series).rename_axis("date")


def _boc_curve(start: str, end: str) -> tuple[pd.DataFrame, str]:
    response = requests.get(
        CURVE_URL,
        params={
            "lookupPage": "lookup_yield_curve.php", "startRange": "1986-01-01",
            "searchRange": "", "dFrom": start, "dTo": end,
        },
        timeout=45,
    )
    response.raise_for_status()
    frame = pd.read_csv(
        BytesIO(response.content), skipinitialspace=True, na_values=["na"],
        usecols=["Date", *BOC_COLUMNS], parse_dates=["Date"], index_col="Date",
    )
    curve = frame.rename(columns=BOC_COLUMNS).rename_axis("date").sort_index().dropna()
    return _validate(curve, YIELD_COLUMNS), response.url


def _save_csv(frame: pd.DataFrame, path: Path) -> str:
    payload = frame.to_csv(float_format="%.12g", lineterminator="\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def download_market(
    start: str = SAMPLE_START,
    end: str = SAMPLE_END,
    market_path: Path = DEFAULT_MARKET_PATH,
    curve_path: Path = DEFAULT_CURVE_PATH,
    metadata_path: Path | None = None,
) -> dict:
    """Download source observations and save local CSVs and provenance."""
    import yfinance as yf

    start_date, end_date = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start_date >= end_date:
        raise ValueError("End date must be later than start date")
    start_iso, end_iso = start_date.date().isoformat(), end_date.date().isoformat()
    market_path, curve_path = Path(market_path), Path(curve_path)
    market_path.parent.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(market_path.parent / "cache" / "yfinance"))

    quotes = _yahoo_quotes(yf, start_date, end_date)
    curve, curve_source = _boc_curve(start_iso, end_iso)
    panel = align_market(quotes, curve, end_date)
    valuation = curve.loc[:end_date].tail(1)
    if valuation.empty or end_date - valuation.index[-1] > MONTH_END_TOLERANCE:
        raise ValueError("No complete BoC valuation curve within seven days of the requested date")

    metadata = {
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested_start": start_iso,
        "requested_end_inclusive": end_iso,
        "sample_first_date": panel.index[0].date().isoformat(),
        "sample_last_date": panel.index[-1].date().isoformat(),
        "sample_observations": len(panel),
        "sample_monthly_changes": len(panel) - 1,
        "curve_date": valuation.index[0].date().isoformat(),
        "market_csv_sha256": _save_csv(panel, market_path),
        "curve_csv_sha256": _save_csv(valuation, curve_path),
        "curve_tenors_years": CURVE_TENORS,
        "sources": {
            "asset_levels": "Yahoo Finance distribution-adjusted closes via yfinance",
            "usd_cad": "Yahoo Finance USDCAD=X close in CAD per USD via yfinance",
            "goc_zero_curve": curve_source,
        },
        "monthly_asset_baskets": ASSET_BASKETS,
        "converted_from_usd_to_cad": USD_TICKERS,
        "software": {"pandas": pd.__version__, "yfinance": yf.__version__},
    }
    provenance = Path(metadata_path) if metadata_path else market_path.with_name(f"{market_path.stem}_metadata.json")
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=SAMPLE_START)
    parser.add_argument("--end", default=SAMPLE_END, help="Inclusive valuation and download cutoff")
    parser.add_argument("--output", type=Path, default=DEFAULT_MARKET_PATH)
    parser.add_argument("--curve", type=Path, default=DEFAULT_CURVE_PATH)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    metadata = download_market(args.start, args.end, args.output, args.curve, args.metadata)
    print(
        f"Saved {metadata['sample_observations']} month-end observations "
        f"({metadata['sample_first_date']} to {metadata['sample_last_date']}) and the "
        f"{metadata['curve_date']} valuation curve."
    )


if __name__ == "__main__":
    main()
