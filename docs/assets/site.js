import { REPLAY_DAYS, buildReplay } from "./replay.mjs";

const el = (id) => document.getElementById(id);
const setText = (id, value) => { el(id).textContent = value; };
const number = new Intl.NumberFormat("en-CA");
const percent = new Intl.NumberFormat("en-CA", { style: "percent", maximumFractionDigits: 2 });
const reportDate = new Intl.DateTimeFormat("en-CA", { dateStyle: "medium", timeZone: "UTC" });
const palette = ["#1f6e57", "#629984", "#bd9061", "#7d9073", "#a2bcb0"];
const mint = "#248064";
const warm = "#a14a2e";
const decimal = (value, places = 1) => Number(value).toFixed(places);
const ratio = (value) => percent.format(value);
const money = (value, places = 2) => {
  const size = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (size >= 1e6) return `${sign}$${decimal(size / 1e6, places)}M`;
  if (size >= 1e3) return `${sign}$${decimal(size / 1e3, places)}k`;
  return `${sign}$${decimal(size, places)}`;
};
const monthDate = (value) => reportDate.format(new Date(`${value}T00:00:00Z`));

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function svg(parent, tag, attrs, text) {
  const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value);
  if (text !== undefined) item.textContent = text;
  parent.append(item);
  return item;
}

function titledMark(parent, tag, attrs, label) {
  svg(svg(parent, tag, attrs), "title", {}, label);
}

function scale([min, max], [low, high]) {
  return (value) => low + (value - min) * (high - low) / (max - min);
}

function gridLine(chart, x1, y1, x2, y2) {
  svg(chart, "line", { x1, x2, y1, y2, class: "chart-grid-line" });
}

function axisText(chart, x, y, value, options = {}) {
  svg(chart, "text", { x, y, class: "chart-axis", "text-anchor": "middle", ...options }, value);
}

function pathLine(values, x, y, xKey, yKey) {
  return values.map((row, index) => `${index === 0 ? "M" : "L"}${x(row[xKey]).toFixed(2)},${y(row[yKey]).toFixed(2)}`).join(" ");
}

function roundedDomain(values, step) {
  const minimum = Math.floor(Math.min(...values) / step) * step;
  return [minimum, Math.max(minimum + step, Math.ceil(Math.max(...values) / step) * step)];
}

function drawBenefits(rows) {
  if (!rows?.length) return;
  const chart = el("hero-chart");
  chart.replaceChildren();
  const frame = { left: 56, right: 585, top: 24, bottom: 224 };
  const domain = roundedDomain([0, ...rows.map((row) => row.amount)], 10e6);
  const x = scale([1, rows.at(-1).year], [frame.left, frame.right]);
  const y = scale(domain, [frame.bottom, frame.top]);
  const step = (domain[1] - domain[0]) / 4;
  for (let i = 0; i <= 4; i += 1) {
    const amount = domain[0] + i * step;
    gridLine(chart, frame.left, y(amount), frame.right, y(amount));
    axisText(chart, frame.left - 9, y(amount) + 4, decimal(amount / 1e6, 0), { "text-anchor": "end" });
  }
  [1, 15, 30, 45, 60].forEach((year) => {
    gridLine(chart, x(year), frame.top, x(year), frame.bottom);
    axisText(chart, x(year), frame.bottom + 22, `Y${year}`);
  });
  const line = pathLine(rows, x, y, "year", "amount");
  svg(chart, "path", { d: `${line} L${x(rows.at(-1).year)},${frame.bottom} L${frame.left},${frame.bottom} Z`, fill: "#7dc1a5", opacity: .22 });
  svg(chart, "path", { d: line, fill: "none", stroke: "#bbedd5", "stroke-width": 3, "stroke-linejoin": "round" });
  const peak = rows.reduce((a, b) => a.amount > b.amount ? a : b);
  titledMark(chart, "circle", { cx: x(peak.year), cy: y(peak.amount), r: 5, fill: "#d7e6b9", stroke: "#183e33", "stroke-width": 2 }, `Peak · year ${peak.year} · CAD ${money(peak.amount)}`);
}

function drawFrontier(rows, baseline, selected) {
  const chart = el("frontier-chart");
  chart.replaceChildren();
  const frame = { left: 75, right: 528, top: 23, bottom: 267 };
  const xDomain = roundedDomain(rows.map((row) => row.sar95), 15e6);
  const yDomain = roundedDomain(rows.map((row) => row.expected_surplus), .25e6);
  const x = scale(xDomain, [frame.left, frame.right]);
  const y = scale(yDomain, [frame.bottom, frame.top]);
  for (let value = xDomain[0]; value <= xDomain[1]; value += 15e6) {
    gridLine(chart, x(value), frame.top, x(value), frame.bottom);
    axisText(chart, x(value), frame.bottom + 19, decimal(value / 1e6, 0));
  }
  for (let value = yDomain[0]; value <= yDomain[1]; value += .25e6) {
    gridLine(chart, frame.left, y(value), frame.right, y(value));
    axisText(chart, frame.left - 9, y(value) + 4, decimal(value / 1e6, 2), { "text-anchor": "end" });
  }
  axisText(chart, (frame.left + frame.right) / 2, 317, "95% SaR (CAD M)");
  axisText(chart, 18, (frame.top + frame.bottom) / 2, "Expected surplus (CAD M)", { transform: `rotate(-90 18 ${(frame.top + frame.bottom) / 2})` });
  svg(chart, "path", {
    d: pathLine(rows, x, y, "sar95", "expected_surplus"),
    stroke: "#698d7c", "stroke-width": 2.7, fill: "none", "stroke-linecap": "round",
  });
  rows.filter((_, index) => index % 10 === 0).forEach((row) => {
    titledMark(chart, "circle", { cx: x(row.sar95), cy: y(row.expected_surplus), r: 3, fill: "#719d87" },
      `${ratio(row.hedge_ratio)} target · ${money(row.sar95)} SaR · ${money(row.expected_surplus)} expected surplus`);
  });
  const baseX = x(baseline.sar95), baseY = y(baseline.expected_surplus);
  titledMark(chart, "rect", {
    x: baseX - 5, y: baseY - 5, width: 10, height: 10,
    transform: `rotate(45 ${baseX} ${baseY})`, fill: "#9f733e",
  }, `Natural book · ${ratio(baseline.hedge_ratio)} coverage`);
  const selectedX = x(selected.sar95), selectedY = y(selected.expected_surplus);
  titledMark(chart, "circle", { cx: selectedX, cy: selectedY, r: 11, fill: "none", stroke: mint, "stroke-width": 2, opacity: .6 }, `Selected · ${ratio(selected.hedge_ratio)}`);
  titledMark(chart, "circle", { cx: selectedX, cy: selectedY, r: 5.5, fill: mint, stroke: "#fffefa", "stroke-width": 1.4 }, `${money(selected.sar95)} SaR`);
}

function drawDistribution(edges, selected, paths) {
  const chart = el("distribution-chart");
  chart.replaceChildren();
  const frame = { left: 63, right: 530, top: 23, bottom: 267 };
  const histogram = selected.funding_histogram;
  const counts = histogram.map((count) => count / paths);
  const ceiling = roundedDomain([0, ...counts], .025)[1];
  const x = scale([edges[0], edges.at(-1)], [frame.left, frame.right]);
  const y = scale([0, ceiling], [frame.bottom, frame.top]);
  for (let i = 0; i <= 4; i += 1) {
    const share = i * ceiling / 4;
    gridLine(chart, frame.left, y(share), frame.right, y(share));
    axisText(chart, frame.left - 9, y(share) + 4, ratio(share), { "text-anchor": "end" });
  }
  [0.75, 1.00, 1.25, 1.50].forEach((tick) => axisText(chart, x(tick), frame.bottom + 19, ratio(tick)));
  axisText(chart, (frame.left + frame.right) / 2, 317, "Assets / liability PV");
  counts.forEach((count, i) => {
    const top = y(count);
    const color = edges[i + 1] <= 1 ? "#b36a4f" : "#519077";
    titledMark(chart, "rect", {
      x: x(edges[i]) + .5, y: top, width: Math.max(1, x(edges[i + 1]) - x(edges[i]) - 1),
      height: frame.bottom - top, fill: color, rx: 1,
    }, `${ratio(edges[i])} to ${ratio(edges[i + 1])} · ${number.format(histogram[i])} paths`);
  });
  svg(chart, "line", { x1: x(1), x2: x(1), y1: frame.top, y2: frame.bottom, stroke: "#973a2a", "stroke-dasharray": "5 4", "stroke-width": 1.5 });
  axisText(chart, x(1) + 5, frame.top + 11, "100% funded", { "text-anchor": "start", class: "chart-key-label" });
}

function drawRisk(rows) {
  const bars = el("risk-bars");
  bars.replaceChildren();
  const max = Math.max(1, ...rows.map((row) => Math.abs(row.value)));
  const total = rows.reduce((value, row) => value + row.value, 0);
  rows.forEach(({ label, value }) => {
    const bar = node("div", "risk-line");
    const track = node("div", "risk-track");
    track.setAttribute("aria-hidden", "true");
    const fill = node("span", "risk-fill");
    const width = Math.abs(value) / max * 50;
    fill.style.width = `${width}%`;
    fill.style.left = `${value < 0 ? 50 - width : 50}%`;
    fill.dataset.negative = String(value < 0);
    track.append(fill);
    bar.append(node("span", "risk-name", label), track, node("strong", "risk-value", money(value)));
    bars.append(bar);
  });
  const footer = node("div", "risk-total");
  footer.append(node("span", "", "Total surplus volatility"), node("span", "", money(total)));
  bars.append(footer);
}

function drawAllocation(rows) {
  rows.forEach(({ label, weight, proxy }, index) => {
    const segment = node("span");
    segment.style.width = `${100 * weight}%`;
    segment.style.backgroundColor = palette[index % palette.length];
    el("allocation-strip").append(segment);
    const item = node("div");
    const name = node("dt");
    const swatch = node("i");
    swatch.style.backgroundColor = segment.style.backgroundColor;
    name.append(swatch, document.createTextNode(label));
    item.append(name, node("dd", "", ratio(weight)), node("small", "", proxy));
    el("allocation-list").append(item);
  });
}

function drawKeyRates(rows) {
  if (!rows?.length) return;
  const chart = el("key-rate-chart");
  el("key-rate-card").hidden = false;
  const frame = { left: 65, right: 750, top: 19, bottom: 192 };
  const max = Math.max(...rows.map((row) => Math.max(row.liability_dv01, row.asset_dv01)), 1);
  const range = roundedDomain([0, max], 100e3);
  const y = scale(range, [frame.bottom, frame.top]);
  const width = (frame.right - frame.left) / rows.length;
  for (let i = 0; i <= 4; i += 1) {
    const amount = i * range[1] / 4;
    gridLine(chart, frame.left, y(amount), frame.right, y(amount));
    axisText(chart, frame.left - 10, y(amount) + 4, decimal(amount / 1e3, 0), { "text-anchor": "end" });
  }
  rows.forEach((row, index) => {
    const mid = frame.left + (index + .5) * width;
    [["liability_dv01", -21, "#40816a", "Liability"], ["asset_dv01", 3, "#aa7b47", "Asset"]].forEach(([key, offset, color, label]) => {
      const value = row[key];
      titledMark(chart, "rect", { x: mid + offset, y: y(value), width: 18, height: frame.bottom - y(value), fill: color, rx: 2 }, `${row.tenor}Y · ${label} DV01 ${money(value)}`);
    });
    axisText(chart, mid, frame.bottom + 25, `${row.tenor === .25 ? "3M" : `${row.tenor}Y`}`);
  });
}

function drawCash(selected, data) {
  const { scenario } = data;
  const shortfall = data.headroom < 0;
  setText("stress-target", `${ratio(selected.hedge_ratio)} TARGET`);
  setText("stress-result-title", shortfall ? "Cash shortfall" : "Cash cushion");
  setText("stress-headroom", `CAD ${money(data.headroom)}`);
  el("stress-headroom").dataset.shortfall = String(shortfall);
  setText("stress-coverage", data.coverage === null ? "NO OUTFLOWS YET" : `${decimal(data.coverage, 2)}× COVERAGE`);
  setText("stress-applied", `Day ${data.day}: equity −${ratio(scenario.equity_drop)} · rates +${decimal(scenario.rate_shock_bps, 0)} bp · PE call ${ratio(scenario.capital_call)}`);
  const chart = el("stress-chart");
  chart.replaceChildren();
  const max = Math.max(data.resources, data.outflows, 1);
  [["Resources", data.resources, "#abd7bd"], ["Outflows", data.outflows, "#edbd93"]].forEach(([label, amount, color]) => {
    const bar = node("div", "cash-bar");
    const track = node("div", "cash-track");
    track.setAttribute("aria-hidden", "true");
    const fill = node("span");
    fill.style.width = `${100 * amount / max}%`;
    fill.style.backgroundColor = color;
    track.append(fill);
    bar.append(node("span", "", label), track, node("strong", "", money(amount)));
    chart.append(bar);
  });
  const breakdown = el("stress-breakdown");
  breakdown.replaceChildren();
  [
    ["Swap variation margin", data.variationMargin],
    ["Private capital call", data.capitalCall],
    ["30-day benefit payments", data.benefits],
  ].forEach(([label, amount]) => {
    const entry = node("div");
    entry.append(node("dt", "", label), node("dd", "", money(amount)));
    breakdown.append(entry);
  });
}

function drawReplayChart(frames) {
  const chart = el("replay-chart");
  chart.replaceChildren();
  const frame = { left: 68, right: 732, top: 22, bottom: 249 };
  const domain = roundedDomain([0, ...frames.flatMap((row) => [row.headroom, row.variationMargin])], 25e6);
  const x = scale([0, REPLAY_DAYS], [frame.left, frame.right]);
  const y = scale(domain, [frame.bottom, frame.top]);
  svg(chart, "rect", {
    x: frame.left, y: y(0), width: frame.right - frame.left, height: frame.bottom - y(0),
    fill: "#f3ba93", opacity: .08,
  });
  for (let i = 0; i <= 5; i += 1) {
    const value = domain[0] + (domain[1] - domain[0]) * i / 5;
    gridLine(chart, frame.left, y(value), frame.right, y(value));
    axisText(chart, frame.left - 11, y(value) + 4, decimal(value / 1e6, 0), { "text-anchor": "end" });
  }
  [0, 5, 10, 15, 20, 25, 30].forEach((day) => {
    gridLine(chart, x(day), frame.top, x(day), frame.bottom);
    axisText(chart, x(day), frame.bottom + 23, String(day));
  });
  svg(chart, "line", { x1: frame.left, x2: frame.right, y1: y(0), y2: y(0), class: "replay-zero" });
  axisText(chart, (frame.left + frame.right) / 2, 293, "SIMULATED DAY");
  const defs = svg(chart, "defs", {});
  const clip = svg(defs, "clipPath", { id: "replay-progress-clip" });
  const reveal = svg(clip, "rect", { x: frame.left - 8, y: 0, width: 0, height: 300 });
  const shown = svg(chart, "g", { "clip-path": "url(#replay-progress-clip)" });
  svg(shown, "path", { d: pathLine(frames, x, y, "day", "headroom"), class: "replay-headroom", fill: "none" });
  svg(shown, "path", { d: pathLine(frames, x, y, "day", "variationMargin"), class: "replay-margin", fill: "none" });
  const firstShortfall = frames.find((row) => row.headroom < 0);
  if (firstShortfall) {
    titledMark(shown, "circle", {
      cx: x(firstShortfall.day), cy: y(firstShortfall.headroom), r: 5.5,
      fill: "#f3ba93", stroke: "#18362d", "stroke-width": 2,
    }, `First modeled shortfall · day ${firstShortfall.day}`);
  }
  const cursor = svg(chart, "line", { y1: frame.top, y2: frame.bottom, class: "replay-cursor" });
  const headroom = svg(chart, "circle", { r: 5.5, fill: "#a9e7c9", stroke: "#18362d", "stroke-width": 2 });
  const margin = svg(chart, "circle", { r: 5.5, fill: "#f3ba93", stroke: "#18362d", "stroke-width": 2 });

  return (progress) => {
    const day = Math.floor(progress);
    const row = frames[day], next = frames[Math.min(day + 1, REPLAY_DAYS)];
    const fraction = progress - day;
    const pos = x(progress);
    const valueAt = (key) => y(row[key] + (next[key] - row[key]) * fraction);
    reveal.setAttribute("width", pos - frame.left + 8.5);
    cursor.setAttribute("x1", pos);
    cursor.setAttribute("x2", pos);
    headroom.setAttribute("cx", pos);
    headroom.setAttribute("cy", valueAt("headroom"));
    margin.setAttribute("cx", pos);
    margin.setAttribute("cy", valueAt("variationMargin"));
  };
}

function setupReplay(book) {
  const scrub = el("replay-scrub");
  const play = el("replay-play");
  const restart = el("replay-restart");
  const speed = el("replay-speed");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let selected, frames, moveChart;
  let progress = REPLAY_DAYS;
  let drawnDay = -1;
  let request = null;
  let previousTime = null;

  function render() {
    const day = Math.floor(progress);
    moveChart(reducedMotion.matches ? day : progress);
    if (day === drawnDay) return;
    drawnDay = day;
    const row = frames[day];
    scrub.value = day;
    scrub.setAttribute("aria-valuetext", `Day ${day} of ${REPLAY_DAYS}`);
    setText("replay-day", `Day ${day} / ${REPLAY_DAYS}`);
    setText("replay-phase", row.phase);
    setText("replay-buffer", money(row.headroom));
    setText("replay-vm", money(row.variationMargin));
    drawCash(selected, row);
  }

  function pause() {
    if (request !== null) cancelAnimationFrame(request);
    request = null;
    previousTime = null;
    play.setAttribute("aria-pressed", "false");
    play.textContent = progress === REPLAY_DAYS ? "Replay" : "Play";
  }

  function tick(time) {
    if (previousTime !== null) {
      const seconds = Math.min(time - previousTime, 100) / 1000;
      progress = Math.min(REPLAY_DAYS, progress + seconds * 3.3 * Number(speed.value));
      render();
    }
    previousTime = time;
    if (progress < REPLAY_DAYS) {
      request = requestAnimationFrame(tick);
    } else {
      pause();
      const final = frames.at(-1);
      const result = final.headroom < 0 ? "cash shortfall" : "cash headroom";
      setText("replay-status", `Replay complete. Day ${REPLAY_DAYS} ${result}: CAD ${money(Math.abs(final.headroom))}.`);
    }
  }

  function start(reset = true) {
    pause();
    if (reset || progress === REPLAY_DAYS) progress = 0;
    render();
    play.setAttribute("aria-pressed", "true");
    play.textContent = "Pause";
    setText("replay-status", `Playing from day ${Math.floor(progress)}.`);
    request = requestAnimationFrame(tick);
  }

  play.addEventListener("click", () => {
    if (request === null) start(false);
    else {
      pause();
      setText("replay-status", `Paused at day ${Math.floor(progress)}.`);
    }
  });
  restart.addEventListener("click", () => start());
  scrub.addEventListener("input", () => {
    progress = Number(scrub.value);
    pause();
    render();
    setText("replay-status", `Showing day ${progress}.`);
  });

  return {
    launch() {
      el("replay").scrollIntoView({ behavior: reducedMotion.matches ? "instant" : "smooth", block: "start" });
      start();
    },
    update(row, scenario) {
      selected = row;
      frames = buildReplay(book, row.overlay_notional, scenario);
      moveChart = drawReplayChart(frames);
      drawnDay = -1;
      for (const control of [play, restart, scrub, speed]) control.disabled = false;
      render();
      if (request === null) {
        pause();
        setText("replay-status", progress === REPLAY_DAYS
          ? "Showing the end of the scenario. Replay to see how it develops."
          : `Showing day ${Math.floor(progress)} with the selected hedge.`);
      }
    },
  };
}

function main(data) {
  const { meta, baseline, frontier, liquidity, portfolio, benefits, key_rates: keyRates, histogram_edges: edges } = data;
  const slider = el("hedge-ratio");
  const full = frontier.at(-1);
  const unconstrained = frontier.reduce((a, b) => a.sar95 <= b.sar95 ? a : b);
  const withCash = frontier.find((point) => point.hedge_ratio === meta.liquidity_constrained_min_sar_ratio);
  const keys = ["equity", "rates", "call"];
  const presets = [el("hedge-natural"), el("hedge-sample"), el("hedge-full")];
  let selected = baseline;
  let scenario = { ...liquidity.default };
  const replay = setupReplay(liquidity);

  function readControls() {
    return {
      equity_drop: Number(el("stress-equity").value) / 100,
      rate_shock_bps: Number(el("stress-rates").value),
      capital_call: Number(el("stress-call").value) / 100,
    };
  }

  function updateStressLabels() {
    const next = readControls();
    setText("stress-equity-value", ratio(next.equity_drop));
    setText("stress-rates-value", `${next.rate_shock_bps} bp`);
    setText("stress-call-value", `${ratio(next.capital_call)} of PE sleeve`);
  }

  function fillStressControls(values) {
    el("stress-equity").value = values.equity_drop * 100;
    el("stress-rates").value = values.rate_shock_bps;
    el("stress-call").value = values.capital_call * 100;
    updateStressLabels();
  }

  function renderHedge(row, clicked) {
    selected = row;
    slider.value = Math.round(selected.hedge_ratio * 100);
    const target = ratio(selected.hedge_ratio);
    const natural = selected === baseline;
    slider.setAttribute("aria-valuetext", natural ? `Natural hedge ${target}` : `${target} target coverage`);
    setText("hedge-output", natural ? `${target} natural` : target);
    setText("hedge-sar", money(selected.sar95));
    setText("hedge-surplus", money(selected.expected_surplus));
    setText("hedge-under", ratio(selected.p_underfunded));
    setText("hedge-notional", money(Math.abs(selected.overlay_notional)));
    setText("hedge-direction", selected.overlay_notional === 0 ? "No overlay" : selected.overlay_notional > 0 ? "Receive fixed · CAD notional" : "Pay fixed · CAD notional");
    setText("frontier-current", natural ? "NATURAL BOOK" : `${target} TARGET`);
    setText("distribution-under", `${ratio(selected.p_underfunded)} UNDER 100%`);
    setText("attribution-target", natural ? "NATURAL BOOK" : `${target} TARGET`);
    presets.forEach((button) => button.setAttribute("aria-pressed", String(button === clicked)));
    drawFrontier(frontier, baseline, selected);
    drawDistribution(edges, selected, meta.paths);
    drawRisk(selected.risk_contributions ?? data.risk_contributions);
    replay.update(selected, scenario);
  }

  setText("hero-funding", ratio(meta.initial_funding_ratio));
  setText("hero-duration", `${decimal(meta.liability_duration)} yrs`);
  setText("hero-natural", ratio(meta.natural_hedge_ratio));
  setText("hero-paths", number.format(meta.paths));
  setText("meta-window", `${monthDate(meta.calibration_start)} – ${monthDate(meta.calibration_end)}`);
  setText("meta-as-of", monthDate(meta.as_of));
  drawBenefits(benefits);
  drawAllocation(portfolio);
  drawKeyRates(keyRates);
  const callout = el("tradeoff-callout");
  if (withCash) {
    callout.append(node("strong", "", "DEFAULT CASH-STRESS COMPARISON"),
      node("span", "", `The lowest 95% SaR occurs at ${ratio(unconstrained.hedge_ratio)}, with ${money(Math.abs(unconstrained.liquidity_buffer))} ${unconstrained.liquidity_buffer < 0 ? "cash shortfall" : "cash headroom"}. Among targets that cover the cash stress, ${ratio(withCash.hedge_ratio)} gives the lowest SaR.`));
    callout.hidden = false;
  }

  slider.disabled = false;
  presets[1].disabled = !withCash;
  if (withCash) presets[1].textContent = `${ratio(withCash.hedge_ratio)} · default cash screen`;
  slider.addEventListener("input", () => renderHedge(frontier[Number(slider.value)]));
  presets[0].addEventListener("click", () => renderHedge(baseline, presets[0]));
  presets[1].addEventListener("click", () => renderHedge(withCash, presets[1]));
  presets[2].addEventListener("click", () => renderHedge(full, presets[2]));
  keys.forEach((key) => el(`stress-${key}`).addEventListener("input", updateStressLabels));
  el("stress-form").addEventListener("submit", (event) => {
    event.preventDefault();
    scenario = readControls();
    replay.update(selected, scenario);
    replay.launch();
  });
  el("stress-sample").addEventListener("click", () => {
    scenario = { ...liquidity.default };
    fillStressControls(scenario);
    renderHedge(full, presets[2]);
    replay.launch();
  });
  fillStressControls(scenario);
  renderHedge(baseline, presets[0]);
}

try {
  const response = await fetch("assets/results.json");
  if (!response.ok) throw new Error(`Results request failed (${response.status}).`);
  main(await response.json());
} catch (error) {
  console.error(error);
  el("data-error").hidden = false;
}
