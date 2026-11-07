"""Thirty-day liquidity waterfall for the synthetic pension plan."""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np


@dataclass(frozen=True)
class LiquidityTerms:
    equity_value: float
    long_bonds_value: float
    credit_value: float
    private_equity_value: float
    benefits_30d: float
    equity_monetizable: float = 0.20
    long_bonds_monetizable: float = 0.25
    credit_monetizable: float = 0.15
    equity_haircut: float = 0.05
    long_bonds_haircut: float = 0.03
    credit_haircut: float = 0.10

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{field.name} must be finite and nonnegative")
            if field.name.endswith(("monetizable", "haircut")) and value > 1:
                raise ValueError(f"{field.name} must not exceed one")


@dataclass(frozen=True)
class StressInputs:
    equity_drop: float = 0.30
    rate_shock_bps: int = 200
    capital_call: float = 0.20


@dataclass(frozen=True)
class RateStress:
    bps: int
    long_bonds_ratio: float
    credit_ratio: float
    unit_swap_pv: float


@dataclass(frozen=True)
class LiquidityResult:
    equity_resource: float
    long_bonds_resource: float
    credit_resource: float
    resources: float
    variation_margin: float
    capital_call: float
    benefit_payments: float
    outflows: float
    liquidity_buffer: float
    coverage: float | None


def liquidity_stress(
    terms: LiquidityTerms,
    rate: RateStress,
    inputs: StressInputs,
    overlay_notional: float,
) -> LiquidityResult:
    """Compare stressed net sale proceeds with cash demands in CAD.

    A positive overlay receives fixed and loses value on a rate rise. Variation
    margin consumes cash only for a loss. Gains and new borrowing are excluded
    from eligible resources. Call size is a fraction of the opening PE sleeve.
    """
    if not (0 <= inputs.equity_drop <= 1 and 0 <= inputs.capital_call <= 1):
        raise ValueError("The equity decline and private call must lie between zero and one")
    if inputs.rate_shock_bps != rate.bps:
        raise ValueError("The rate repricing must match the requested shock")
    if not all(np.isfinite(value) for value in (
        overlay_notional, rate.unit_swap_pv, rate.long_bonds_ratio, rate.credit_ratio
    )) or min(rate.long_bonds_ratio, rate.credit_ratio) <= 0:
        raise ValueError("Repricing values must be finite and asset ratios positive")

    equity = terms.equity_value * (1 - inputs.equity_drop)
    equity *= terms.equity_monetizable * (1 - terms.equity_haircut)
    bonds = terms.long_bonds_value * rate.long_bonds_ratio
    bonds *= terms.long_bonds_monetizable * (1 - terms.long_bonds_haircut)
    credit = terms.credit_value * rate.credit_ratio
    credit *= terms.credit_monetizable * (1 - terms.credit_haircut)
    resources = equity + bonds + credit
    vm = max(0.0, -overlay_notional * rate.unit_swap_pv)
    call = terms.private_equity_value * inputs.capital_call
    outflows = vm + call + terms.benefits_30d
    return LiquidityResult(
        equity, bonds, credit, resources, vm, call, terms.benefits_30d, outflows,
        resources - outflows, resources / outflows if outflows else None,
    )
