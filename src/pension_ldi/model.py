"""Defined-benefit valuation, joint asset/rate risk and a duration hedge."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .market import ASSET_NAMES, CURVE_TENORS, YIELD_COLUMNS

ASSET_WEIGHTS = (0.30, 0.35, 0.15, 0.10, 0.10)
RATE_SLEEVES = ("long_bonds", "credit")
MONTHS_PER_YEAR = 12
SWAP_TENOR = 15
BP = 1e-4


def curve_weights(times: np.ndarray) -> np.ndarray:
    """Linear zero-rate interpolation, with flat endpoints beyond the knots."""
    identity = np.eye(len(CURVE_TENORS))
    return np.column_stack([np.interp(times, CURVE_TENORS, row) for row in identity])


def discount_factors(times: np.ndarray, curve: np.ndarray, spread: float = 0.0) -> np.ndarray:
    times = np.asarray(times, dtype=float)
    curve = np.asarray(curve, dtype=float)
    return np.exp(-(curve @ curve_weights(times).T + spread) * times)


@dataclass(frozen=True)
class CashFlows:
    times: np.ndarray
    payments: np.ndarray
    spread: float = 0.0

    def value(self, curve: np.ndarray, elapsed: float = 0.0) -> np.ndarray:
        """Ex-payment value on the current curve at remaining maturities."""
        outstanding = self.times > elapsed
        terms = self.times[outstanding] - elapsed
        return discount_factors(terms, curve, self.spread) @ self.payments[outstanding]

    def key_rate_dv01(self, curve: np.ndarray) -> np.ndarray:
        """Positive CAD loss per basis point rise at each zero-rate knot."""
        pv_by_payment = discount_factors(self.times, curve, self.spread) * self.payments
        return BP * ((pv_by_payment * self.times) @ curve_weights(self.times))


def par_cash_flows(curve: np.ndarray, tenor: int, spread: float = 0.0) -> CashFlows:
    """Fixed-rate par bond with semiannual coupons per dollar face."""
    times = np.arange(0.5, tenor + 0.5, 0.5)
    discounts = discount_factors(times, curve, spread)
    payments = np.full(len(times), (1.0 - discounts[-1]) / discounts.sum())
    payments[-1] += 1
    return CashFlows(times, payments, spread)


@dataclass(frozen=True)
class Plan:
    curve: np.ndarray
    assets: np.ndarray
    liabilities: CashFlows
    rate_sleeves: tuple[CashFlows, CashFlows]

    @property
    def liability_pv(self) -> float:
        return float(self.liabilities.value(self.curve))

    @property
    def first_year_benefit(self) -> float:
        return float(self.liabilities.payments[self.liabilities.times <= 1.0].sum())

    @property
    def initial_surplus(self) -> float:
        return float(self.assets.sum() - self.liability_pv)

    @property
    def key_rate_dv01(self) -> np.ndarray:
        return self.liabilities.key_rate_dv01(self.curve)

    @property
    def duration(self) -> float:
        return self.liability_dv01 / (BP * self.liability_pv)

    @property
    def asset_key_rate_dv01(self) -> np.ndarray:
        return sum(
            self.assets[ASSET_NAMES.index(name)] * sleeve.key_rate_dv01(self.curve)
            for name, sleeve in zip(RATE_SLEEVES, self.rate_sleeves)
        )

    @property
    def asset_dv01(self) -> float:
        return float(self.asset_key_rate_dv01.sum())

    @property
    def liability_dv01(self) -> float:
        return float(self.key_rate_dv01.sum())

    @property
    def natural_hedge_ratio(self) -> float:
        return self.asset_dv01 / self.liability_dv01


def make_plan(
    curve: np.ndarray,
    *,
    liability_pv: float = 1e9,
    funding_ratio: float = 1.05,
    liability_duration: float = 15.0,
    liability_spread: float = 0.005,
) -> Plan:
    """Size a fictional closed DB book with 60 annual nominal payments.

    A hump-shaped runoff schedule is calibrated to the selected initial PV
    and continuously compounded parallel duration. Benefits are fixed CAD.
    """
    curve = np.asarray(curve, dtype=float)
    if curve.shape != (len(CURVE_TENORS),) or not np.isfinite(curve).all():
        raise ValueError("Expected a finite vector with one zero yield per curve knot")
    settings = (liability_pv, funding_ratio, liability_duration, liability_spread)
    if not np.isfinite(settings).all() or min(liability_pv, funding_ratio) <= 0:
        raise ValueError("The plan requires finite settings and positive PV and funding ratio")
    if not 1 < liability_duration < 60:
        raise ValueError("Liability duration must be strictly between 1 and 60 years")

    years = np.arange(1.0, 61.0)
    zero = curve @ curve_weights(years).T

    def present_weights(decay: float) -> np.ndarray:
        log_pv = np.log(years) - (decay + zero + liability_spread) * years
        return np.exp(log_pv - log_pv.max())

    def duration_gap(decay: float) -> float:
        weights = present_weights(decay)
        return (weights @ years) / weights.sum() - liability_duration

    decay = brentq(duration_gap, -50, 50)
    weights = present_weights(decay)
    payments = liability_pv * weights / weights.sum() / discount_factors(
        years, curve, liability_spread
    )
    liabilities = CashFlows(years, payments, liability_spread)
    assets = liability_pv * funding_ratio * np.asarray(ASSET_WEIGHTS)
    sleeves = (par_cash_flows(curve, 20), par_cash_flows(curve, 8, spread=0.009))
    return Plan(curve.copy(), assets, liabilities, sleeves)


def asset_rate_ratios(plan: Plan, curve: np.ndarray, elapsed: float = 0.0) -> np.ndarray:
    """Full rate repricing ratios for bond and credit sleeves, one elsewhere.

    The normalization keeps rate carry out of these ratios because ETF
    residuals already include carry. Spread is fixed for the direct curve
    effect. Corporate spread moves remain embedded in the credit residual.
    """
    curve = np.asarray(curve, dtype=float)
    ratios = np.ones((*curve.shape[:-1], len(ASSET_NAMES)))
    for name, sleeve in zip(RATE_SLEEVES, plan.rate_sleeves):
        ratios[..., ASSET_NAMES.index(name)] = (
            sleeve.value(curve, elapsed) / sleeve.value(plan.curve, elapsed)
        )
    return ratios


def swap_par_rate(plan: Plan) -> float:
    """Annual fixed rate for a 15-year single-curve spot swap."""
    times = np.arange(1.0, SWAP_TENOR + 1)
    discount = discount_factors(times, plan.curve)
    return float((1 - discount[-1]) / discount.sum())


def swap_value(
    plan: Plan, notional: float, curve: np.ndarray, elapsed: int = 0
) -> np.ndarray:
    """Receive-fixed swap value plus first net coupon at the one-year horizon.

    Annual resets and payments coincide. Positive notional receives fixed.
    For an instantaneous stress, elapsed=0 gives clean change from par. At
    elapsed=1, include the coupon fixed by the initial one-year forward.
    """
    if elapsed not in (0, 1):
        raise ValueError("Swap valuation supports the trade date or first annual reset")
    times = np.arange(1.0, SWAP_TENOR + 1 - elapsed)
    discount = discount_factors(times, curve)
    fixed = swap_par_rate(plan)
    value = fixed * discount.sum(axis=-1) + discount[..., -1] - 1
    if elapsed:
        initial_discount = discount_factors(np.ones(1), plan.curve)[0]
        value += fixed - (1 / initial_discount - 1)
    return notional * value


def swap_key_rate_dv01(plan: Plan) -> np.ndarray:
    """Key-rate DV01 per CAD 1 of 15Y receive-fixed swap notional."""
    times = np.arange(1.0, SWAP_TENOR + 1)
    coupon_and_principal = np.full(len(times), swap_par_rate(plan))
    coupon_and_principal[-1] += 1
    return CashFlows(times, coupon_and_principal).key_rate_dv01(plan.curve)


def overlay_for(plan: Plan, hedge_ratio: float) -> float:
    """Signed swap notional targeting total asset plus swap DV01 / liability DV01."""
    if not np.isfinite(hedge_ratio) or not 0 <= hedge_ratio <= 1:
        raise ValueError("The hedge ratio must be between 0 and 1")
    return float(
        (hedge_ratio * plan.liability_dv01 - plan.asset_dv01) / swap_key_rate_dv01(plan).sum()
    )


@dataclass(frozen=True)
class Calibration:
    mean: np.ndarray
    covariance: np.ndarray
    observations: int
    start_date: str
    end_date: str
    smoothing_alpha: float
    pe_smoothed_vol: float
    pe_desmoothed_vol: float
    asset_volatilities: dict[str, float]
    factor_names: tuple[str, ...]


def appraisal_demo(
    proxy_returns: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray]:
    """Apply and invert hypothetical NAV smoothing of a listed PE log-return proxy.

    The inversion recovers the listed input by construction. The smoothed
    path is a teaching example, not an observed private fund NAV.
    """
    values = np.asarray(proxy_returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("The appraisal demonstration requires at least two finite returns")
    if not np.isfinite(alpha) or not 0 <= alpha < 1:
        raise ValueError("Appraisal smoothing alpha must be in [0, 1)")
    reported = np.empty_like(values)
    reported[0] = values[0]
    for index in range(1, len(values)):
        reported[index] = (1 - alpha) * values[index] + alpha * reported[index - 1]
    corrected = reported.copy()
    corrected[1:] = (reported[1:] - alpha * reported[:-1]) / (1 - alpha)
    return reported, corrected


def fit_market(monthly: pd.DataFrame, *, smoothing_alpha: float = 0.55) -> Calibration:
    """Estimate the monthly joint distribution of sleeve residuals and zero yields."""
    if not isinstance(monthly.index, pd.DatetimeIndex) or len(monthly) < 16:
        raise ValueError("Calibration requires at least 16 dated monthly levels")
    months = monthly.index.to_period("M")
    if not (np.diff(months.asi8) == 1).all():
        raise ValueError("Calibration requires consecutive, ordered calendar months")

    levels = monthly.loc[:, list(ASSET_NAMES)].to_numpy(dtype=float)
    curves = monthly.loc[:, list(YIELD_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(levels).all() or np.any(levels <= 0) or not np.isfinite(curves).all():
        raise ValueError("Calibration requires positive asset levels and finite zero rates")

    returns = np.diff(np.log(levels), axis=0)
    pe_index = ASSET_NAMES.index("private_equity")
    smoothed, corrected = appraisal_demo(returns[:, pe_index], smoothing_alpha)
    returns[:, pe_index] = corrected
    asset_vol = returns.std(axis=0, ddof=1) * np.sqrt(MONTHS_PER_YEAR)

    # Approximate each month's rate exposure with the same constant-tenor
    # structural sleeve as the projected book, re-parred at the prior curve.
    residuals = returns.copy()
    for name, tenor, spread in (("long_bonds", 20, 0.0), ("credit", 8, 0.009)):
        shocked_values = [
            par_cash_flows(previous, tenor, spread).value(current)
            for previous, current in zip(curves[:-1], curves[1:])
        ]
        residuals[:, ASSET_NAMES.index(name)] -= np.log(shocked_values)
    joint = np.column_stack((residuals, np.diff(curves, axis=0)))
    annualize = np.sqrt(MONTHS_PER_YEAR)
    return Calibration(
        mean=joint.mean(axis=0),
        covariance=np.cov(joint, rowvar=False),
        observations=len(joint),
        start_date=monthly.index[1].strftime("%Y-%m-%d"),
        end_date=monthly.index[-1].strftime("%Y-%m-%d"),
        smoothing_alpha=float(smoothing_alpha),
        pe_smoothed_vol=float(smoothed.std(ddof=1) * annualize),
        pe_desmoothed_vol=float(corrected.std(ddof=1) * annualize),
        asset_volatilities=dict(zip(ASSET_NAMES, map(float, asset_vol))),
        factor_names=(*ASSET_NAMES, *YIELD_COLUMNS),
    )


@dataclass(frozen=True)
class Simulation:
    plan: Plan
    calibration: Calibration
    curves: np.ndarray
    liabilities: np.ndarray
    sleeve_pnl: np.ndarray
    unhedged_assets: np.ndarray
    rate_mismatch: np.ndarray
    unit_swap_pnl: np.ndarray
    seed: int

    @property
    def paths(self) -> int:
        return len(self.liabilities)


def run_simulation(
    plan: Plan, calibration: Calibration, *, paths: int = 20_000, seed: int = 20261107
) -> Simulation:
    """Sample a one-year joint Gaussian law with IID monthly increments.

    Twelve monthly log-return increments compound risky exposures. Absolute
    yield changes add. Each path reprices the remaining liability payments
    and the rate sleeve cash flows. The first benefit is paid from assets.
    """
    if paths < 2:
        raise ValueError("Run at least two Monte Carlo paths")
    annual_cov = MONTHS_PER_YEAR * calibration.covariance
    eigenvalues, eigenvectors = np.linalg.eigh(annual_cov)
    tolerance = np.finfo(float).eps * len(eigenvalues) * max(1.0, abs(eigenvalues[-1]))
    if eigenvalues[0] < -tolerance:
        raise ValueError("Annual covariance must be positive semidefinite")
    factor = eigenvectors * np.sqrt(np.maximum(eigenvalues, 0))
    innovations = np.random.default_rng(seed).standard_normal((paths, len(eigenvalues)))
    shocks = MONTHS_PER_YEAR * calibration.mean + innovations @ factor.T
    asset_factors = len(ASSET_NAMES)
    curves = plan.curve + shocks[:, asset_factors:]
    projected_residual = plan.assets * np.exp(shocks[:, :asset_factors])
    projected_assets = projected_residual * asset_rate_ratios(plan, curves, elapsed=1)
    liabilities = plan.liabilities.value(curves, elapsed=1)
    base_aged_liability = plan.liabilities.value(plan.curve, elapsed=1)

    return Simulation(
        plan=plan,
        calibration=calibration,
        curves=curves,
        liabilities=liabilities,
        sleeve_pnl=projected_residual - plan.assets,
        unhedged_assets=projected_assets.sum(axis=1) - plan.first_year_benefit,
        rate_mismatch=(projected_assets - projected_residual).sum(axis=1)
        - (liabilities - base_aged_liability),
        unit_swap_pnl=swap_value(plan, 1.0, curves, elapsed=1),
        seed=seed,
    )


@dataclass(frozen=True)
class Metrics:
    hedge_ratio: float
    swap_notional: float
    surplus_at_risk: float
    expected_surplus: float
    underfunded_probability: float
    funding_ratio: np.ndarray
    surplus: np.ndarray
    surplus_volatility: float
    euler: dict[str, float]


def evaluate(simulation: Simulation, hedge_ratio: float) -> Metrics:
    """Measure one-year downside and allocate the standard deviation by Euler.

    SaR is opening surplus minus the fifth percentile of end-year surplus.
    The attribution is covariance with total surplus divided by surplus
    volatility. A negative contribution indicates diversification.
    """
    notional = overlay_for(simulation.plan, hedge_ratio)
    swap_pnl = notional * simulation.unit_swap_pnl
    assets = simulation.unhedged_assets + swap_pnl
    surplus = assets - simulation.liabilities
    funding_ratio = assets / simulation.liabilities
    volatility = float(surplus.std(ddof=1))
    components = np.column_stack((simulation.sleeve_pnl, simulation.rate_mismatch + swap_pnl))
    if volatility:
        centered = components - components.mean(axis=0)
        contribution = (surplus - surplus.mean()) @ centered / ((len(surplus) - 1) * volatility)
    else:
        contribution = np.zeros(components.shape[1])
    return Metrics(
        hedge_ratio=float(hedge_ratio),
        swap_notional=notional,
        surplus_at_risk=float(simulation.plan.initial_surplus - np.quantile(surplus, 0.05)),
        expected_surplus=float(surplus.mean()),
        underfunded_probability=float(np.mean(funding_ratio < 1.0)),
        funding_ratio=funding_ratio,
        surplus=surplus,
        surplus_volatility=volatility,
        euler=dict(zip((*ASSET_NAMES, "rate_mismatch"), map(float, contribution))),
    )


def frontier(simulation: Simulation, ratios: np.ndarray) -> list[Metrics]:
    """Evaluate all hedge targets using common random numbers."""
    return [evaluate(simulation, ratio) for ratio in ratios]
