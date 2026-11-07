import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildReplay, cashBreakdown, REPLAY_DAYS } from "../docs/assets/replay.mjs";

const study = JSON.parse(readFileSync(new URL("../docs/assets/results.json", import.meta.url), "utf8"));
const book = study.liquidity;
const defaultShock = book.default;

function near(actual, expected) {
  const tolerance = 1e-12 * Math.max(1, Math.abs(expected));
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} differs from ${expected}`);
}

test("replay endpoint matches the published Python stress for both reference hedges", () => {
  for (const [hedge, expected] of [
    [study.baseline, book.baseline],
    [study.frontier.at(-1), book.fully_hedged],
  ]) {
    const frames = buildReplay(book, hedge.overlay_notional, defaultShock);
    assert.equal(frames.length, REPLAY_DAYS + 1);
    assert.deepEqual(frames.at(-1).scenario, defaultShock);
    const { day, phase, scenario, ...results } = frames.at(-1);
    assert.equal(day, 30);
    assert.equal(phase, "Day 30 review");
    assert.deepEqual(results, cashBreakdown(book, hedge.overlay_notional, scenario));
    for (const [key, pythonKey] of [
      ["headroom", "liquidity_buffer"], ["coverage", "coverage"], ["resources", "resources"],
      ["outflows", "outflows"], ["variationMargin", "variation_margin"], ["capitalCall", "capital_call"],
      ["benefits", "benefit_payments"],
    ]) near(results[key], expected[pythonKey]);
  }
});

test("replay phases equity, rates, cash calls and benefits separately", () => {
  const frames = buildReplay(book, study.frontier.at(-1).overlay_notional, defaultShock);
  assert.equal(frames[0].coverage, null);
  assert.equal(frames[0].outflows, 0);
  assert.ok(frames[1].scenario.equity_drop > 0);
  assert.equal(frames[5].scenario.rate_shock_bps, 0);
  assert.ok(frames[6].variationMargin > 0);
  assert.equal(frames[14].scenario.equity_drop, defaultShock.equity_drop);
  assert.equal(frames[17].capitalCall, 0);
  near(frames[18].capitalCall, book.terms.private_equity_value * defaultShock.capital_call * 0.45);
  assert.equal(frames[21].scenario.rate_shock_bps, defaultShock.rate_shock_bps);
  assert.equal(frames[23].capitalCall, frames[18].capitalCall);
  near(frames[24].capitalCall, book.terms.private_equity_value * defaultShock.capital_call);
  for (const [day, frame] of frames.entries()) {
    assert.equal(frame.day, day);
    near(frame.benefits, book.terms.benefits_30d * day / REPLAY_DAYS);
    assert.ok(Number.isFinite(frame.headroom));
  }
});

test("interpolates fractional bps without replacing an exact stress point", () => {
  const notional = study.frontier.at(-1).overlay_notional;
  const at = (bps) => cashBreakdown(book, notional, { ...defaultShock, rate_shock_bps: bps });
  const lower = at(100);
  const upper = at(110);
  const center = at(105);
  for (const key of ["resources", "variationMargin", "headroom"]) {
    near(center[key], (lower[key] + upper[key]) / 2);
  }
  assert.throws(() => at(401), /within the modeled grid/);
});

test("zero market shocks keep resources flat and accrue only benefit payments", () => {
  const zeroShock = { equity_drop: 0, rate_shock_bps: 0, capital_call: 0 };
  const frames = buildReplay(book, study.frontier.at(-1).overlay_notional, zeroShock);
  for (const frame of frames) {
    assert.equal(frame.resources, frames[0].resources);
    assert.equal(frame.variationMargin, 0);
    assert.equal(frame.capitalCall, 0);
    assert.equal(frame.outflows, frame.benefits);
  }
  assert.equal(frames.at(-1).benefits, book.terms.benefits_30d);
});
