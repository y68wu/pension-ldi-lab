"""Build the pension case study, report tables and browser data."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from .liquidity import LiquidityTerms, RateStress, StressInputs, liquidity_stress
from .market import ASSET_NAMES, CURVE_TENORS, load_curve, load_market
from .model import (
    asset_rate_ratios,
    evaluate,
    fit_market,
    make_plan,
    overlay_for,
    run_simulation,
    swap_value,
)

PATHS = 20_000
SEED = 20261107
LABELS = {
    "public_equity": "Public equity",
    "long_bonds": "Long bonds",
    "real_assets": "Real assets",
    "private_equity": "Private equity",
    "credit": "Credit",
    "rate_mismatch": "Net rate mismatch",
}
PROXIES = {
    "public_equity": "XIU + VFV",
    "long_bonds": "XLB",
    "real_assets": "ZRE + IGF",
    "private_equity": "PSP",
    "credit": "XCB",
}


def build_study(market, curve, as_of: str, *, paths: int = PATHS, seed: int = SEED) -> dict:
    """Build 101 common-path hedge cases and a separate no-overlay reference."""
    plan = make_plan(curve)
    calibration = fit_market(market)
    simulation = run_simulation(plan, calibration, paths=paths, seed=seed)
    starting_assets = dict(zip(ASSET_NAMES, map(float, plan.assets)))
    terms = LiquidityTerms(
        equity_value=starting_assets["public_equity"],
        long_bonds_value=starting_assets["long_bonds"],
        credit_value=starting_assets["credit"],
        private_equity_value=starting_assets["private_equity"],
        benefits_30d=float(plan.first_year_benefit) / 12,
    )
    stress = StressInputs()
    rate_grid = []
    for bps in range(0, 401, 10):
        shifted = plan.curve + bps / 10_000
        ratios = dict(zip(ASSET_NAMES, asset_rate_ratios(plan, shifted)))
        rate_grid.append(RateStress(
            bps, float(ratios["long_bonds"]), float(ratios["credit"]),
            float(swap_value(plan, 1.0, shifted)),
        ))
    reference_rate = next(rate for rate in rate_grid if rate.bps == stress.rate_shock_bps)

    # For each path the denominator is independent of the overlay and the
    # numerator is affine in notional, so the endpoints bound all histograms.
    low = evaluate(simulation, 0)
    high = evaluate(simulation, 1)
    floor = np.floor(min(low.funding_ratio.min(), high.funding_ratio.min()) * 40) / 40
    ceiling = np.ceil(max(low.funding_ratio.max(), high.funding_ratio.max()) * 40) / 40
    edges = np.linspace(floor, ceiling, max(1, int(round((ceiling - floor) * 40))) + 1)

    def summarize(ratio, metrics):
        notional = float(overlay_for(plan, ratio))
        stress_result = liquidity_stress(terms, reference_rate, stress, notional)
        counts = np.histogram(metrics.funding_ratio, bins=edges)[0]
        if counts.sum() != paths:
            raise ValueError("Funding-ratio bins must contain every Monte Carlo path")
        return {
            "hedge_ratio": float(ratio),
            "expected_surplus": float(metrics.expected_surplus),
            "sar95": float(metrics.surplus_at_risk),
            "surplus_volatility": float(metrics.surplus_volatility),
            "p_underfunded": float(metrics.underfunded_probability),
            "overlay_notional": notional,
            "funding_histogram": counts.tolist(),
            "funding_quantiles": np.quantile(metrics.funding_ratio, [0.05, 0.5, 0.95]).tolist(),
            "risk_contributions": [
                {"label": LABELS[name], "value": float(metrics.euler[name])} for name in LABELS
            ],
            "coverage": stress_result.coverage,
            "liquidity_buffer": stress_result.liquidity_buffer,
        }

    frontier = [summarize(ratio / 100, evaluate(simulation, ratio / 100)) for ratio in range(101)]
    natural = float(plan.natural_hedge_ratio)
    baseline = summarize(natural, evaluate(simulation, natural))
    policy = min((row for row in frontier if row["coverage"] >= 1),
                 key=lambda row: row["sar95"], default=None)
    assets = float(plan.assets.sum())
    liabilities = float(plan.liability_pv)
    return {
        "meta": {
            "as_of": as_of,
            "calibration_start": str(pd.Timestamp(calibration.start_date).date()),
            "calibration_end": str(pd.Timestamp(calibration.end_date).date()),
            "observations": int(calibration.observations),
            "paths": paths,
            "seed": seed,
            "initial_assets": assets,
            "initial_liabilities": liabilities,
            "initial_surplus": float(plan.initial_surplus),
            "initial_funding_ratio": assets / liabilities,
            "liability_duration": float(plan.duration),
            "liability_dv01": float(plan.liability_dv01),
            "asset_dv01": float(plan.asset_dv01),
            "natural_hedge_ratio": natural,
            "first_year_benefit": float(plan.first_year_benefit),
            "alpha": float(calibration.smoothing_alpha),
            "smoothed_private_vol": float(calibration.pe_smoothed_vol),
            "desmoothed_private_vol": float(calibration.pe_desmoothed_vol),
            "liquidity_constrained_min_sar_ratio": policy["hedge_ratio"] if policy else None,
        },
        "baseline": baseline,
        "frontier": frontier,
        "histogram_edges": edges.tolist(),
        "risk_contributions": baseline["risk_contributions"],
        "portfolio": [
            {"label": LABELS[key], "weight": value / assets, "proxy": PROXIES[key]}
            for key, value in starting_assets.items()
        ],
        "key_rates": [
            {"tenor": float(tenor), "liability_dv01": float(liability), "asset_dv01": float(asset)}
            for tenor, liability, asset in zip(
                CURVE_TENORS, plan.key_rate_dv01, plan.asset_key_rate_dv01
            )
        ],
        "benefits": [
            {"year": int(year), "amount": float(amount)}
            for year, amount in zip(plan.liabilities.times, plan.liabilities.payments)
        ],
        "liquidity": {
            "terms": asdict(terms),
            "rate_grid": [asdict(rate) for rate in rate_grid],
            "default": asdict(stress),
            "baseline": asdict(liquidity_stress(terms, reference_rate, stress, baseline["overlay_notional"])),
            "fully_hedged": asdict(liquidity_stress(terms, reference_rate, stress, frontier[-1]["overlay_notional"])),
        },
    }


def write_study(study: dict, reports: Path, figures: Path, website: Path) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    website.parent.mkdir(parents=True, exist_ok=True)
    website.write_text(json.dumps(study, allow_nan=False, separators=(",", ":")) + "\n", encoding="utf-8")
    scalar_columns = [
        "hedge_ratio", "expected_surplus", "sar95", "surplus_volatility", "p_underfunded", "overlay_notional",
        "coverage", "liquidity_buffer",
    ]
    pd.DataFrame(study["frontier"])[scalar_columns].to_csv(reports / "frontier.csv", index=False)
    reference = {"no overlay": study["baseline"], "100% DV01": study["frontier"][-1]}
    pd.DataFrame.from_dict(reference, orient="index")[scalar_columns].to_csv(
        reports / "comparison.csv", index_label="case"
    )
    pd.DataFrame([
        {"case": case, **entry} for case, row in reference.items() for entry in row["risk_contributions"]
    ]).to_csv(reports / "euler.csv", index=False)
    for key in ("benefits", "key_rates", "portfolio"):
        pd.DataFrame(study[key]).to_csv(reports / f"{key}.csv", index=False)
    pd.DataFrame.from_dict(
        {key: study["liquidity"][key] for key in ("baseline", "fully_hedged")}, orient="index"
    ).to_csv(reports / "liquidity.csv", index_label="case")
    (reports / "summary.json").write_text(
        json.dumps(study["meta"], indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    plot_summary(study, figures / "ldi-tradeoff.png")


def calibration_check(market: pd.DataFrame, curve, as_of: str, full: dict) -> pd.DataFrame:
    """Re-estimate the hedge decision over shorter historical windows."""
    studies = [("full sample", full)]
    for years in (10, 5):
        months = 12 * years + 1
        if len(market) > months:
            studies.append((f"trailing {years} years", build_study(market.iloc[-months:], curve, as_of)))
    records = []
    for name, study in studies:
        best = min(study["frontier"], key=lambda row: row["sar95"])
        records.append({
            "sample": name,
            "monthly_changes": study["meta"]["observations"],
            "no_overlay_sar95": study["baseline"]["sar95"],
            "minimum_sar_hedge_ratio": best["hedge_ratio"],
            "minimum_sar95": best["sar95"],
            "liquidity_constrained_hedge_ratio": study["meta"]["liquidity_constrained_min_sar_ratio"],
        })
    return pd.DataFrame(records)


def plot_summary(study: dict, output: Path) -> None:
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    ink, muted, green, rust = "#152d29", "#506963", "#136b57", "#a6432a"
    frame = pd.DataFrame(study["frontier"])
    baseline = study["baseline"]
    ratio = frame["hedge_ratio"]
    with plt.rc_context({
        "font.family": "DejaVu Sans", "font.size": 10.5, "text.color": ink,
        "axes.labelcolor": muted, "xtick.color": muted, "ytick.color": muted,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.spines.bottom": False,
        "axes.axisbelow": True, "xtick.major.size": 0, "ytick.major.size": 0,
    }):
        fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4))
        fig.subplots_adjust(left=.093, right=.97, top=.72, bottom=.21, wspace=.38)
        fig.text(.093, .91, "A pension hedge has two budgets", size=21, weight="bold")
        fig.text(.093, .83, "One-year funding risk and 30-day liquidity under the same DV01 hedge targets",
                 color=muted)
        left.plot(ratio, frame["sar95"] / 1e6, lw=2.6, color=green)
        left.set_title("95% surplus-at-risk", loc="left", weight="bold", pad=10)
        left.set_ylabel("Potential loss of surplus (CAD m)")
        right.axhline(0, color=muted, lw=.9)
        right.plot(ratio, frame["liquidity_buffer"] / 1e6, lw=2.6, color=rust)
        right.fill_between(ratio, frame["liquidity_buffer"] / 1e6, 0,
                           where=frame["liquidity_buffer"] < 0, color=rust, alpha=.11)
        right.set_title("30-day stressed cash buffer", loc="left", weight="bold", pad=10)
        right.set_ylabel("Cash resources less outflows (CAD m)")
        for axis, key, color in ((left, "sar95", green), (right, "liquidity_buffer", rust)):
            axis.set_xlabel("Target asset / liability DV01")
            axis.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
            axis.set_xticks(np.linspace(0, 1, 6))
            axis.set_xlim(-.02, 1.02)
            axis.grid(axis="y", color="#dbe8e4")
            axis.scatter([baseline["hedge_ratio"]], [baseline[key] / 1e6], marker="o", s=65,
                         facecolor="#ffffff", edgecolor=color, lw=2, zorder=3)
        fig.text(.093, .07, "Hollow markers show the existing bond hedge, before swaps. "
                 "Stress combines −30% equities, +200 bp rates and a 20% private equity call.",
                 color=muted, fontsize=9)
        fig.savefig(output, dpi=170, facecolor="#ffffff")
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", type=Path, default=Path("data/market.csv"))
    parser.add_argument("--curve", type=Path, default=Path("data/curve.csv"))
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    parser.add_argument("--figures", type=Path, default=Path("figures"))
    parser.add_argument("--website", type=Path, default=Path("docs/assets/results.json"))
    args = parser.parse_args()
    market = load_market(args.market)
    curve = load_curve(args.curve)
    date = str(pd.read_csv(args.curve, usecols=["date"]).iloc[0, 0])
    study = build_study(market, curve, date)
    write_study(study, args.reports, args.figures, args.website)
    calibration_check(market, curve, date, study).to_csv(
        args.reports / "calibration_check.csv", index=False
    )
    print(f"Snapshot {date}, {study['meta']['paths']:,} paths")
    print(pd.read_csv(args.reports / "comparison.csv").to_string(index=False))


if __name__ == "__main__":
    main()
