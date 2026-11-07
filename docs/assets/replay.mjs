/** Thirty-day illustrative replay of the pension liquidity stress. */
export const REPLAY_DAYS = 30;

function rateAt(grid, basisPoints) {
  if (!Number.isFinite(basisPoints) || basisPoints < grid[0].bps || basisPoints > grid.at(-1).bps) {
    throw new RangeError("Choose a rate shock within the modeled grid.");
  }
  const index = grid.findIndex((point) => point.bps >= basisPoints);
  const upper = grid[index];
  if (upper.bps === basisPoints) return upper;
  const lower = grid[index - 1];
  const weight = (basisPoints - lower.bps) / (upper.bps - lower.bps);
  const interpolate = (field) => lower[field] + weight * (upper[field] - lower[field]);
  return {
    long_bonds_ratio: interpolate("long_bonds_ratio"),
    credit_ratio: interpolate("credit_ratio"),
    unit_swap_pv: interpolate("unit_swap_pv"),
  };
}

export function cashBreakdown(book, overlayNotional, scenario, benefitsFraction = 1) {
  const { terms, rate_grid: grid } = book;
  const { equity_drop: equityDrop, rate_shock_bps: basisPoints, capital_call: call } = scenario;
  if (![equityDrop, call, benefitsFraction].every((value) => value >= 0 && value <= 1)) {
    throw new RangeError("Drawdown, capital call and benefit fractions must be between zero and one.");
  }
  if (!Number.isFinite(overlayNotional)) throw new RangeError("Use a finite hedge notional.");
  const rate = rateAt(grid, basisPoints);
  const equity = terms.equity_value * (1 - equityDrop) * terms.equity_monetizable * (1 - terms.equity_haircut);
  const longBonds = terms.long_bonds_value * rate.long_bonds_ratio * terms.long_bonds_monetizable * (1 - terms.long_bonds_haircut);
  const credit = terms.credit_value * rate.credit_ratio * terms.credit_monetizable * (1 - terms.credit_haircut);
  const variationMargin = Math.max(0, -overlayNotional * rate.unit_swap_pv);
  const capitalCall = terms.private_equity_value * call;
  const benefits = terms.benefits_30d * benefitsFraction;
  const resources = equity + longBonds + credit;
  const outflows = variationMargin + capitalCall + benefits;
  return {
    resources, outflows, headroom: resources - outflows, coverage: outflows > 0 ? resources / outflows : null,
    variationMargin, capitalCall, benefits,
  };
}

const PHASES = [
  [0, "Opening position"],
  [1, "Equity repricing"],
  [6, "Rates and collateral"],
  [18, "First capital call"],
  [19, "Margin and benefits"],
  [24, "Second capital call"],
  [25, "Remaining benefits"],
  [30, "Day 30 review"],
];

function ease(day, start, end) {
  const progress = Math.max(0, Math.min(1, (day - start) / (end - start)));
  return progress * progress * (3 - 2 * progress);
}

/** Phase in a user's selected endpoint shocks with a fixed demonstration schedule.
 *
 * Market repricing and collateral build over multiple days. Capital calls
 * settle in two tranches. Each day is a stressed liquidity budget using
 * stressed resources and cumulative scheduled payments, with no trading.
 */
export function buildReplay(book, overlayNotional, endpoint) {
  return Array.from({ length: REPLAY_DAYS + 1 }, (_, day) => {
    const scenario = {
      equity_drop: endpoint.equity_drop * ease(day, 0, 14),
      rate_shock_bps: endpoint.rate_shock_bps * ease(day, 5, 21),
      capital_call: endpoint.capital_call * (day < 18 ? 0 : day < 24 ? 0.45 : 1),
    };
    const phase = PHASES.findLast(([start]) => day >= start)[1];
    return {
      day, phase, scenario,
      ...cashBreakdown(book, overlayNotional, scenario, day / REPLAY_DAYS),
    };
  });
}
