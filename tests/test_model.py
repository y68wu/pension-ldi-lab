"""Numerical and accounting checks for the pension model."""

import numpy as np
import pandas as pd
import pytest

from pension_ldi.market import ASSET_NAMES, CURVE_TENORS, YIELD_COLUMNS
from pension_ldi.model import (
    BP,
    Calibration,
    appraisal_demo,
    asset_rate_ratios,
    evaluate,
    fit_market,
    frontier,
    make_plan,
    overlay_for,
    par_cash_flows,
    run_simulation,
    swap_key_rate_dv01,
    swap_value,
)


@pytest.fixture
def plan():
    return make_plan(np.linspace(0.02, 0.035, len(CURVE_TENORS)))


def test_liability_pv_duration_and_key_rates_match_central_bumps(plan):
    assert len(plan.liabilities.payments) == 60
    assert (plan.liabilities.payments > 0).all()
    assert plan.first_year_benefit == plan.liabilities.payments[0]
    assert plan.liability_pv == pytest.approx(1e9)
    assert plan.initial_surplus == pytest.approx(50e6)
    assert plan.duration == pytest.approx(15)
    knot_bumps = np.eye(len(CURVE_TENORS)) * BP
    central_dv01 = (
        plan.liabilities.value(plan.curve - knot_bumps)
        - plan.liabilities.value(plan.curve + knot_bumps)
    ) / 2
    np.testing.assert_allclose(plan.key_rate_dv01, central_dv01, rtol=5e-6)
    assert plan.liability_dv01 == pytest.approx(1.5e6)


def test_swap_target_includes_natural_asset_dv01(plan):
    assert swap_value(plan, 1.0, plan.curve) == pytest.approx(0, abs=1e-15)
    assert overlay_for(plan, 0) < 0
    assert overlay_for(plan, plan.natural_hedge_ratio) == pytest.approx(0)
    receive_fixed = overlay_for(plan, 1)
    assert receive_fixed > 0
    assert swap_value(plan, receive_fixed, plan.curve + 0.02) < 0
    swap_dv01 = (
        swap_value(plan, receive_fixed, plan.curve - BP)
        - swap_value(plan, receive_fixed, plan.curve + BP)
    ) / 2
    assert swap_dv01 == pytest.approx(receive_fixed * swap_key_rate_dv01(plan).sum(), rel=1e-6)
    assert plan.asset_dv01 + swap_dv01 == pytest.approx(plan.liability_dv01, rel=1e-6)


def test_asset_repricing_changes_only_direct_rate_sleeves(plan):
    np.testing.assert_allclose(asset_rate_ratios(plan, plan.curve, elapsed=1), 1)
    up = asset_rate_ratios(plan, plan.curve + 0.02)
    non_rate = [ASSET_NAMES.index(name) for name in ("public_equity", "real_assets", "private_equity")]
    np.testing.assert_allclose(up[non_rate], 1)
    assert 0 < up[ASSET_NAMES.index("long_bonds")] < up[ASSET_NAMES.index("credit")] < 1


def test_appraisal_demo_inverts_the_hypothetical_transform():
    raw = np.array([0.01, -0.07, 0.13, 0.02, -0.04, 0.03])
    smoothed, corrected = appraisal_demo(raw, alpha=0.55)
    np.testing.assert_allclose(corrected, raw)
    assert smoothed.std() < raw.std()
    with pytest.raises(ValueError, match="alpha"):
        appraisal_demo(raw, alpha=1)


def test_calibration_separates_structural_curve_move_from_bond_return(plan):
    rng = np.random.default_rng(73)
    curves = plan.curve + np.cumsum(rng.normal(0, 0.001, (30, len(CURVE_TENORS))), axis=0)
    residuals = rng.normal(0, 0.03, (len(curves) - 1, len(ASSET_NAMES)))
    returns = residuals.copy()
    for name, tenor, spread in (("long_bonds", 20, 0), ("credit", 8, 0.009)):
        reprice = [
            par_cash_flows(previous, tenor, spread).value(current)
            for previous, current in zip(curves[:-1], curves[1:])
        ]
        returns[:, ASSET_NAMES.index(name)] += np.log(reprice)
    levels = np.exp(np.vstack([np.zeros(len(ASSET_NAMES)), np.cumsum(returns, axis=0)]))
    dates = pd.date_range("2020-01-01", periods=len(curves), freq="MS")
    market = pd.DataFrame(np.column_stack((levels, curves)), index=dates, columns=(*ASSET_NAMES, *YIELD_COLUMNS))
    fit = fit_market(market)
    actual = np.column_stack((residuals, np.diff(curves, axis=0)))
    assert fit.observations == len(curves) - 1
    np.testing.assert_allclose(fit.mean, actual.mean(axis=0))
    np.testing.assert_allclose(fit.covariance, np.cov(actual, rowvar=False))
    with pytest.raises(ValueError, match="consecutive"):
        fit_market(market.drop(market.index[10]))


def calibration(vol=0.01):
    names = (*ASSET_NAMES, *YIELD_COLUMNS)
    return Calibration(
        mean=np.zeros(len(names)),
        covariance=np.diag([vol**2] * len(ASSET_NAMES) + [(vol / 10)**2] * len(YIELD_COLUMNS)),
        observations=100,
        start_date="2010-01-31",
        end_date="2018-04-30",
        smoothing_alpha=0.55,
        pe_smoothed_vol=0.1,
        pe_desmoothed_vol=0.2,
        asset_volatilities={name: 0.1 for name in ASSET_NAMES},
        factor_names=names,
    )


def test_year_one_benefit_rolls_out_of_both_sides(plan):
    sim = run_simulation(plan, calibration(0), paths=16)
    np.testing.assert_allclose(sim.unhedged_assets, plan.assets.sum() - plan.first_year_benefit)
    np.testing.assert_allclose(sim.liabilities, plan.liabilities.value(plan.curve, elapsed=1))
    assert sim.liabilities[0] != pytest.approx(plan.liability_pv)
    metrics = evaluate(sim, plan.natural_hedge_ratio)
    assert metrics.surplus_at_risk == pytest.approx(plan.initial_surplus - metrics.expected_surplus)
    assert metrics.underfunded_probability == float(metrics.funding_ratio[0] < 1)


def test_frontier_uses_matched_paths_and_euler_contributions_add(plan):
    fit = calibration()
    sim = run_simulation(plan, fit, paths=1000, seed=7)
    other = run_simulation(plan, fit, paths=1000, seed=7)
    np.testing.assert_array_equal(sim.curves, other.curves)
    outputs = frontier(sim, np.array([0, plan.natural_hedge_ratio, 1]))
    assert outputs[1].swap_notional == pytest.approx(0)
    for metrics in outputs:
        assert sum(metrics.euler.values()) == pytest.approx(metrics.surplus_volatility)
        np.testing.assert_allclose(metrics.surplus, (metrics.funding_ratio - 1) * sim.liabilities)
        assert metrics.underfunded_probability == pytest.approx(np.mean(metrics.surplus < 0))
    with pytest.raises(ValueError, match="between"):
        evaluate(sim, 1.01)
