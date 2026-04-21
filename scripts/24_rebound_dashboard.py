"""Phase 24 -- render dashboards/rebound_rates.html.

A single-purpose page that answers: after a missed 3 / missed 2 / missed
terminal FT, what are the chances of OREB vs DREB? With Wilson 95% CIs, a
side-by-side chart, a home/away split, and a stats-explainer block.
"""
from __future__ import annotations

import json
import logging
import subprocess

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("24_rebound_dashboard")

SRC = config.REPORTS_DIR / "rebound_rates.json"
SLICE_SRC = config.REPORTS_DIR / "rebound_slices.json"
OUT = config.DASHBOARDS_DIR / "rebound_rates.html"


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Rebound rates by miss type -- EuroLeague HCA</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.js"></script>
<style>
  :root{--bg:#0b0d10;--panel:#13171d;--panel2:#1a1f27;--ink:#e7ecf1;--muted:#b6bfcc;
    --dim:#7a8595;--accent:#6eb0ff;--pos:#3ccf8e;--neg:#ef5a5a;--warn:#f5b73a;
    --hair:rgba(255,255,255,.07)}
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.5;
    letter-spacing:-0.01em;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:32px 24px 96px}
  .back{color:var(--accent);font-size:13px;text-decoration:none}
  .hero{padding:24px 0 16px;border-bottom:1px solid var(--hair)}
  .eyebrow{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
  h1{font-size:30px;font-weight:700;line-height:1.08;letter-spacing:-0.02em;margin:0 0 8px}
  h1 .lead{color:var(--accent)}
  .sub{color:var(--muted);max-width:780px;margin:0}
  .meta{color:var(--dim);font-size:12px;margin-top:12px}

  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:28px 0}
  .kpi{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:16px}
  .kpi .v{font-size:26px;font-weight:700;letter-spacing:-0.02em;line-height:1.1;display:block;font-variant-numeric:tabular-nums}
  .kpi .v.pos{color:var(--pos)} .kpi .v.neu{color:var(--accent)} .kpi .v.warn{color:var(--warn)}
  .kpi .k{color:var(--dim);font-size:12px;margin-top:4px;display:block}
  .kpi .n{color:var(--dim);font-size:11px;margin-top:8px;display:block;font-variant-numeric:tabular-nums}

  h2{font-size:20px;font-weight:600;letter-spacing:-0.02em;margin:36px 0 8px}
  .card{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:20px;margin-top:16px}
  .card h3{margin:0 0 8px;font-size:15px;font-weight:600}
  .card .sub{color:var(--muted);font-size:13px;margin-bottom:16px}
  .chart-wrap{position:relative;width:100%;height:360px}

  table.tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  table.tbl th,table.tbl td{padding:8px 10px;border-bottom:1px solid var(--hair);text-align:left}
  table.tbl th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  table.tbl td.num{font-variant-numeric:tabular-nums;text-align:right}
  table.tbl td.name{color:var(--ink);font-weight:500}
  .chip{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;
    background:rgba(255,255,255,.05);color:var(--muted);font-weight:500}
  .chip.up{background:rgba(60,207,142,.12);color:var(--pos)}
  .chip.down{background:rgba(239,90,90,.12);color:var(--neg)}

  .splitbtns{display:inline-flex;gap:4px;background:var(--panel2);padding:4px;border-radius:8px;margin-bottom:12px}
  .splitbtns button{background:transparent;border:none;color:var(--muted);padding:6px 12px;border-radius:6px;
    font-family:inherit;font-size:12px;cursor:pointer;font-weight:500}
  .splitbtns button.active{background:var(--panel);color:var(--ink)}

  /* Filter bar */
  .filterbar{margin:22px 0 8px;padding:16px;background:var(--panel);border:1px solid var(--hair);border-radius:12px;
    display:grid;grid-template-columns:1.7fr 1fr auto;gap:16px;align-items:start}
  @media (max-width:900px){.filterbar{grid-template-columns:1fr}}
  .filter h4{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin:0 0 6px;font-weight:500}
  .chips{display:flex;flex-wrap:wrap;gap:6px;max-height:116px;overflow-y:auto;padding:2px}
  .fchip{padding:5px 10px;font-size:12px;font-weight:500;border-radius:14px;background:var(--panel2);
    color:var(--muted);border:1px solid var(--hair);cursor:pointer;transition:all .12s;user-select:none;
    white-space:nowrap}
  .fchip:hover{border-color:var(--accent);color:var(--ink)}
  .fchip.active{background:var(--accent);color:#0b0d10;border-color:var(--accent);font-weight:600}
  .actions{display:flex;flex-direction:column;gap:6px;align-items:stretch}
  .btn{padding:7px 12px;font-size:12px;font-weight:600;border-radius:6px;background:var(--panel2);
    color:var(--muted);border:1px solid var(--hair);cursor:pointer}
  .btn:hover{border-color:var(--accent);color:var(--ink)}
  .scope{color:var(--dim);font-size:11px;margin-top:6px;text-align:right}
  .scope strong{color:var(--ink);font-variant-numeric:tabular-nums}
  .warning{background:rgba(245,183,58,.06);border-left:3px solid var(--warn);padding:10px 14px;
    border-radius:4px;margin-top:8px;color:var(--muted);font-size:12.5px;line-height:1.5;display:none}
  .warning.show{display:block} .warning strong{color:var(--warn)}

  .reading{background:rgba(110,176,255,.04);border-left:3px solid var(--accent);
    padding:14px 18px;border-radius:4px;margin-top:16px;color:var(--muted);font-size:13.5px;line-height:1.65}
  .reading strong{color:var(--ink)}

  .statsgrid{display:grid;grid-template-columns:140px 1fr;gap:12px 20px;margin-top:12px}
  .statsgrid dt{color:var(--ink);font-weight:600;font-size:13px}
  .statsgrid dd{margin:0;color:var(--muted);font-size:13px;line-height:1.55}
  .statsgrid dd code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;background:rgba(255,255,255,.05);padding:1px 5px;border-radius:4px}

  footer{margin-top:48px;color:var(--dim);font-size:12px;border-top:1px solid var(--hair);padding-top:16px}
  code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;
    background:rgba(255,255,255,.05);padding:1px 5px;border-radius:4px}

  @media (max-width:640px){ h1{font-size:24px} .wrap{padding:24px 16px 64px}
    .statsgrid{grid-template-columns:1fr}
  }
</style>
</head>
<body>
<div class="wrap">
  <a class="back" href="index.html">&larr; back to dashboard index</a>

  <div class="hero">
    <div class="eyebrow" style="color:#6eb0ff"><span style="display:inline-block;width:8px;height:8px;background:#6eb0ff;border-radius:50%;margin-right:6px;vertical-align:middle"></span>Track B &middot; game dynamics &middot; <a href="explorer.html" style="color:#6eb0ff;text-decoration:none">team+season explorer</a></div>
    <h1>2-point misses are rebounded by the offense <span class="lead">3.8pp more often</span> than 3-point misses.</h1>
    <p class="sub">Terminal free-throw misses are the hardest to offensive-rebound -- only 16.6% of them end on an OREB, vs 28-32% for field goals. Every rate is reported with a Wilson 95% CI; pairwise differences use a pooled two-proportion z-test.</p>
    <div class="meta">__N_GAMES__ games &middot; __N_SEASONS__ seasons &middot; 201k rebound-eligible misses</div>
  </div>

  <!-- FILTER BAR -->
  <div class="filterbar">
    <div class="filter" id="filter-team">
      <h4>Teams (click to toggle; empty = all 36) &middot; <span id="team-count" style="color:var(--accent)">all 36</span></h4>
      <div class="chips" id="team-chips"></div>
    </div>
    <div class="filter" id="filter-season">
      <h4>Seasons (click to toggle; empty = all 10) &middot; <span id="season-count" style="color:var(--accent)">all 10</span></h4>
      <div class="chips" id="season-chips"></div>
    </div>
    <div class="actions">
      <button class="btn" id="btn-clear">Clear all</button>
      <button class="btn" id="btn-last3">Last 3 seasons</button>
      <button class="btn" id="btn-covid">COVID slice</button>
      <div class="scope"><strong id="scope-misses">0</strong> misses in scope &middot;
        <strong id="scope-teams">36</strong> teams &middot;
        <strong id="scope-seasons">10</strong> seasons</div>
    </div>
  </div>
  <div class="warning" id="low-n-warning"><strong>Small sample.</strong> Your selection has fewer than 200 rebound-eligible misses in at least one miss-type cell. Confidence intervals will be wide; don't over-interpret small differences.</div>

  <div class="kpis" id="kpi-strip"></div>

  <h2>OREB vs DREB by miss type</h2>
  <div class="splitbtns">
    <button class="split-btn active" data-split="all">All shots</button>
    <button class="split-btn" data-split="home">Home shooter</button>
    <button class="split-btn" data-split="away">Away shooter</button>
  </div>
  <div class="card">
    <h3>Rebound-outcome probability after each miss type</h3>
    <p class="sub">Bars show OREB% and DREB%. Thin lines on each bar are the 95% Wilson confidence interval. "Other" is shot-clock violations, ball out of bounds, period endings -- rebound-eligible but neither OREB nor DREB.</p>
    <div class="chart-wrap"><canvas id="bars"></canvas></div>
  </div>

  <h2>Exact numbers</h2>
  <div class="card">
    <p class="sub">Conditional interpretation: "of rebounded" shows the share assuming a rebound actually happened (n_D / (n_D + n_O)). Useful because "other" varies across miss types.</p>
    <table class="tbl"><thead><tr>
      <th>Miss type</th><th class="num">n</th>
      <th class="num">OREB %</th><th class="num">OREB 95% CI</th>
      <th class="num">DREB %</th><th class="num">DREB 95% CI</th>
      <th class="num">OREB share of rebounded</th>
    </tr></thead><tbody id="table-body"></tbody></table>
  </div>

  <h2>Pairwise comparisons (all-split)</h2>
  <div class="card">
    <p class="sub">Pooled two-proportion z-test on the OREB rate. Z measures how many standard errors apart the two rates are; p is the two-sided significance. Differences larger than about +/- 0.5 pp are statistically resolvable at this sample size.</p>
    <table class="tbl"><thead><tr>
      <th>Comparison</th>
      <th class="num">OREB rate A</th><th class="num">OREB rate B</th>
      <th class="num">A - B</th><th class="num">z</th><th class="num">p</th>
    </tr></thead><tbody id="comp-body"></tbody></table>
  </div>

  <h2>How to read the numbers</h2>
  <div class="card">
    <dl class="statsgrid">
      <dt>OREB rate</dt>
      <dd>P(offensive rebound | miss of this type). Computed as count of OREBs divided by count of misses.</dd>

      <dt>DREB rate</dt>
      <dd>P(defensive rebound | miss of this type).</dd>

      <dt>"other"</dt>
      <dd>Miss was followed by a non-rebound possession-ending event within the next 3 PBP rows: shot-clock violation, ball out of bounds, end of period, etc. Small on FG misses (~2-5%), small on FT misses (~4%).</dd>

      <dt>Wilson 95% CI</dt>
      <dd>A proportion confidence interval that behaves correctly near the boundaries (0% and 100%). Much more honest than the textbook normal-approx when the probability is far from 50%. Interpretation: if you reran 10 more seasons, the true probability would land inside <code>[lo, hi]</code> 95% of the time.</dd>

      <dt>Two-proportion z-test</dt>
      <dd>Tests whether two rates are different. Formula: <code>z = (p1 - p2) / sqrt(p_pool (1 - p_pool) (1/n1 + 1/n2))</code>. Convert to a two-sided p-value with the standard normal CDF. On our sample sizes (80k+ each), any diff &gt; ~0.3 pp is statistically significant. Significance here is a very weak claim; look at the magnitude.</dd>

      <dt>"Of rebounded" share</dt>
      <dd>If the miss was rebounded (by either team), the share that went to the offense. This controls for the "other" bucket varying across miss types. On FG misses, 30% of rebounds go to the offense; on FT misses, only 17%.</dd>

      <dt>Terminal FT</dt>
      <dd>We only count the last FT in a trip. Earlier FTs in a 2-of-2 or 3-of-3 sequence are not rebound-eligible -- the next PBP event is the next FT in the same trip, not a rebound. Detection: an FT is "terminal" if the next PBP event is not another FT by the same shooter.</dd>

      <dt>Lookahead window</dt>
      <dd>For each miss we look at the next 3 events to classify the rebound. This handles the common case where a missed 2 is recorded with a block annotation (AG/FV) just before the actual rebound. Window &lt;= 3 captures the rebound but avoids bleeding into the next possession.</dd>
    </dl>
  </div>

  <h2>What this means</h2>
  <div class="card">
    <div class="reading">
      <strong>Why 2PT misses get offensive-rebounded more than 3PT misses.</strong> A 2-pointer miss comes from closer to the rim, so the ball is more likely to come off short, bouncing back toward offensive players already positioned near the paint. 3PT misses produce longer, less predictable trajectories, which favor the defender who is already facing the ball and has better angles. The commonly-quoted "long rebounds favor the offense" intuition is contradicted by our data: in EuroLeague, longer shots favor the defense.
      <br/><br/>
      <strong>Why terminal FT misses almost always go to the defense.</strong> Defensive players occupy the two box positions on the lane; the shooter is at the line and can't follow their own shot quickly; the ball trajectory is predictable. The 17% OREB rate is basically the rate at which the ball either bounces unpredictably off the rim or a defender loses positioning.
      <br/><br/>
      <strong>A small home-court rebounding signal.</strong> Home shooters OREB their own misses 29.1% of the time (on 3PT) vs 27.7% when shooting on the road -- a 1.4 pp home edge. On 2PT misses the home-away gap is smaller (32.4% vs 31.9%). This is a minor contributor to the league-wide +3.88pt HCA, consistent with our mechanism decomposition finding that possession-level efficiency, not rebound margin, drives the bulk of home-court advantage.
    </div>
  </div>

  <footer>
    Data: silver-layer PBP (<code>fact_game_event.parquet</code>), 1.51M events across 2,896 games and 10 EuroLeague seasons.
    Methodology: terminal-FT detection via forward lookup, rebound outcome classified via 3-event forward window, Wilson 95% CIs, pooled two-proportion z-test for pairwise comparisons.
    <br/>Build <code>__SHA__</code> &middot; see <a href="reports/rebound_rates.json" style="color:var(--accent)">rebound_rates.json</a> for all 9 rows.
  </footer>
</div>

<script>
const DATA = __JSON__;
const SLICES = __SLICES__;

const SHOT_LABELS = {
  "3FGA": "Missed 3-pointer",
  "2FGA": "Missed 2-pointer",
  "FTA_terminal": "Missed terminal FT",
};
const COLORS = {
  pos: 'rgba(60,207,142,0.85)',
  neg: 'rgba(239,90,90,0.85)',
  other: 'rgba(122,133,149,0.5)',
};

const STATE = {teams: new Set(), seasons: new Set(), split: 'all'};
const TEAMS = [...new Set(SLICES.rows.map(r => r.team_id))].sort((a,b) => {
  // sort by total misses desc
  const score = (t) => SLICES.rows.filter(r => r.team_id === t).reduce((a,r)=>a+r.n_eligible,0);
  return score(b) - score(a);
});
const SEASONS = SLICES.meta.seasons;

// ---- Filter UI ----
function renderTeamChips() {
  const el = document.getElementById('team-chips');
  el.innerHTML = TEAMS.map(t => {
    const active = STATE.teams.has(t) ? 'active' : '';
    return `<span class="fchip ${active}" data-team="${t}">${t}</span>`;
  }).join('');
  document.getElementById('team-count').textContent = STATE.teams.size ? `${STATE.teams.size} selected` : 'all 36';
}
function renderSeasonChips() {
  const el = document.getElementById('season-chips');
  el.innerHTML = SEASONS.map(s => {
    const active = STATE.seasons.has(s) ? 'active' : '';
    return `<span class="fchip ${active}" data-season="${s}">${s}-${String(s+1).slice(2)}</span>`;
  }).join('');
  document.getElementById('season-count').textContent = STATE.seasons.size ? `${STATE.seasons.size} selected` : 'all 10';
}
document.getElementById('team-chips').addEventListener('click', (e) => {
  const c = e.target.closest('.fchip'); if (!c) return;
  const t = c.dataset.team;
  STATE.teams.has(t) ? STATE.teams.delete(t) : STATE.teams.add(t);
  renderTeamChips(); update();
});
document.getElementById('season-chips').addEventListener('click', (e) => {
  const c = e.target.closest('.fchip'); if (!c) return;
  const s = parseInt(c.dataset.season);
  STATE.seasons.has(s) ? STATE.seasons.delete(s) : STATE.seasons.add(s);
  renderSeasonChips(); update();
});
document.getElementById('btn-clear').addEventListener('click', () => {
  STATE.teams.clear(); STATE.seasons.clear();
  renderTeamChips(); renderSeasonChips(); update();
});
document.getElementById('btn-last3').addEventListener('click', () => {
  STATE.seasons = new Set(SEASONS.slice(-3)); renderSeasonChips(); update();
});
document.getElementById('btn-covid').addEventListener('click', () => {
  STATE.seasons = new Set([2019, 2020]); renderSeasonChips(); update();
});
document.querySelectorAll('.split-btn').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.split-btn').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    STATE.split = b.dataset.split;
    update();
  });
});

// ---- Wilson score interval (ported from Python) ----
function wilson(k, n, z=1.96) {
  if (n === 0) return [0, 0];
  const p = k / n;
  const denom = 1 + z*z/n;
  const center = (p + z*z/(2*n)) / denom;
  const halfw = z * Math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom;
  return [Math.max(0, center-halfw), Math.min(1, center+halfw)];
}
// ---- pooled two-proportion z ----
function twoProp(p1, n1, p2, n2) {
  if (!n1 || !n2) return {z: 0, p: 1};
  const pp = (p1*n1 + p2*n2) / (n1 + n2);
  const se = Math.sqrt(pp*(1-pp)*(1/n1 + 1/n2));
  if (se === 0) return {z: 0, p: 1};
  const z = (p1 - p2) / se;
  // standard normal cdf via erf approx
  const erf = (x) => {
    const sign = x < 0 ? -1 : 1; x = Math.abs(x);
    const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;
    const t = 1/(1+p*x);
    const y = 1 - (((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t * Math.exp(-x*x);
    return sign*y;
  };
  const cdf = (x) => 0.5*(1+erf(x/Math.SQRT2));
  return {z, p: 2*(1-cdf(Math.abs(z)))};
}

// ---- Aggregate slices under current filter ----
function filteredSlices() {
  const teamsSet = STATE.teams.size ? STATE.teams : null;
  const seasonsSet = STATE.seasons.size ? STATE.seasons : null;
  let rows = SLICES.rows.filter(r =>
    (!teamsSet || teamsSet.has(r.team_id)) &&
    (!seasonsSet || seasonsSet.has(r.season))
  );
  if (STATE.split === 'home') rows = rows.filter(r => r.is_home === 1);
  if (STATE.split === 'away') rows = rows.filter(r => r.is_home === 0);
  return rows;
}
function rollupByMissType(rows) {
  const out = {};
  for (const mt of ["3FGA", "2FGA", "FTA_terminal"]) {
    out[mt] = {n_eligible:0, n_dreb:0, n_oreb:0};
  }
  for (const r of rows) {
    if (!out[r.miss_type]) continue;
    out[r.miss_type].n_eligible += r.n_eligible;
    out[r.miss_type].n_dreb += r.n_dreb;
    out[r.miss_type].n_oreb += r.n_oreb;
  }
  return out;
}
function withStats(rollup) {
  const out = [];
  for (const mt of ["3FGA", "2FGA", "FTA_terminal"]) {
    const r = rollup[mt];
    const n = r.n_eligible;
    const p_o = n ? r.n_oreb/n : 0;
    const p_d = n ? r.n_dreb/n : 0;
    const [lo_o, hi_o] = wilson(r.n_oreb, n);
    const [lo_d, hi_d] = wilson(r.n_dreb, n);
    const reb = r.n_dreb + r.n_oreb;
    const oreb_share = reb ? r.n_oreb/reb : 0;
    out.push({shot_type: mt, n_eligible: n, n_dreb: r.n_dreb, n_oreb: r.n_oreb,
              p_oreb: p_o, p_dreb: p_d, lo_oreb: lo_o, hi_oreb: hi_o,
              lo_dreb: lo_d, hi_dreb: hi_d, oreb_share_of_rebounded: oreb_share});
  }
  return out;
}

// ---- Chart error bar plugin ----
const errorBarPlugin = {
  id: 'errorBars',
  afterDatasetsDraw(chart) {
    const {ctx, data, scales} = chart;
    const yScale = scales.y;
    data.datasets.forEach((ds, dsi) => {
      if (!ds._errorBars) return;
      const meta = chart.getDatasetMeta(dsi);
      meta.data.forEach((bar, i) => {
        const eb = ds._errorBars[i]; if (!eb) return;
        const yLo = yScale.getPixelForValue(eb.lo * 100);
        const yHi = yScale.getPixelForValue(eb.hi * 100);
        const x = bar.x;
        ctx.save(); ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, yLo); ctx.lineTo(x, yHi);
        ctx.moveTo(x-5, yLo); ctx.lineTo(x+5, yLo);
        ctx.moveTo(x-5, yHi); ctx.lineTo(x+5, yHi);
        ctx.stroke(); ctx.restore();
      });
    });
  },
};

let chart = null;
function renderChart(rows) {
  const labels = rows.map(r => SHOT_LABELS[r.shot_type] || r.shot_type);
  const orebPct = rows.map(r => +(r.p_oreb*100).toFixed(2));
  const drebPct = rows.map(r => +(r.p_dreb*100).toFixed(2));
  const otherPct = rows.map(r => +((1 - r.p_oreb - r.p_dreb)*100).toFixed(2));
  const orebCI = rows.map(r => ({lo: r.lo_oreb, hi: r.hi_oreb}));
  const drebCI = rows.map(r => ({lo: r.lo_dreb, hi: r.hi_dreb}));

  if (chart) chart.destroy();
  const ctx = document.getElementById('bars').getContext('2d');
  chart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {label: 'OREB %', data: orebPct, backgroundColor: COLORS.pos, _errorBars: orebCI},
        {label: 'DREB %', data: drebPct, backgroundColor: COLORS.neg, _errorBars: drebCI},
        {label: 'Other %', data: otherPct, backgroundColor: COLORS.other},
      ],
    },
    plugins: [errorBarPlugin],
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: {position:'bottom', labels: {color:'#b6bfcc', font:{family:'DM Sans', size:12}}},
        tooltip: {callbacks: {label: (c) => {
          const ds = c.dataset, i = c.dataIndex, v = c.parsed.y, row = rows[i];
          let extra = '';
          if (ds._errorBars) {
            const eb = ds._errorBars[i];
            extra = `  CI [${(eb.lo*100).toFixed(2)}-${(eb.hi*100).toFixed(2)}]`;
          }
          return `${ds.label}: ${v.toFixed(2)}%${extra}  (n=${row.n_eligible.toLocaleString()})`;
        }}},
      },
      scales: {
        y: {beginAtZero: true, max: 100, title:{display:true, text:'Probability (%)', color:'#b6bfcc'},
            ticks:{color:'#7a8595', callback:(v)=>v+'%'}, grid:{color:'rgba(255,255,255,0.05)'}},
        x: {ticks:{color:'#b6bfcc', font:{size:12, weight:500}}, grid:{display:false}},
      },
    },
  });
}

function renderKpis(rows) {
  const html = rows.map(r => {
    const label = SHOT_LABELS[r.shot_type] || r.shot_type;
    return `<div class="kpi">
      <span class="v neu">${(r.p_oreb*100).toFixed(1)}%</span>
      <span class="k">OREB rate after ${label.toLowerCase()}</span>
      <span class="n">n = ${r.n_eligible.toLocaleString()} &middot; CI [${(r.lo_oreb*100).toFixed(1)}-${(r.hi_oreb*100).toFixed(1)}]</span>
    </div>`;
  }).join('');
  document.getElementById('kpi-strip').innerHTML = html;
}

function renderTable(rows) {
  const tbody = document.getElementById('table-body');
  tbody.innerHTML = rows.map(r => {
    const label = SHOT_LABELS[r.shot_type] || r.shot_type;
    return `<tr>
      <td class="name">${label}</td>
      <td class="num">${r.n_eligible.toLocaleString()}</td>
      <td class="num">${(r.p_oreb*100).toFixed(2)}%</td>
      <td class="num">[${(r.lo_oreb*100).toFixed(2)}-${(r.hi_oreb*100).toFixed(2)}]</td>
      <td class="num">${(r.p_dreb*100).toFixed(2)}%</td>
      <td class="num">[${(r.lo_dreb*100).toFixed(2)}-${(r.hi_dreb*100).toFixed(2)}]</td>
      <td class="num">${(r.oreb_share_of_rebounded*100).toFixed(1)}%</td>
    </tr>`;
  }).join('');
}
function renderComparisons(rows) {
  const rateBy = Object.fromEntries(rows.map(r => [r.shot_type, r]));
  const pairs = [["3FGA","2FGA"], ["3FGA","FTA_terminal"], ["2FGA","FTA_terminal"]];
  const comps = pairs.map(([a,b]) => {
    const ra = rateBy[a], rb = rateBy[b];
    const {z, p} = twoProp(ra.p_oreb, ra.n_eligible, rb.p_oreb, rb.n_eligible);
    return {a, b, p_a: ra.p_oreb, p_b: rb.p_oreb,
            diff_pp: (ra.p_oreb - rb.p_oreb)*100, z, p};
  });
  const tbody = document.getElementById('comp-body');
  tbody.innerHTML = comps.map(c => {
    const la = SHOT_LABELS[c.a] || c.a;
    const lb = SHOT_LABELS[c.b] || c.b;
    const chip = c.diff_pp > 0
      ? `<span class="chip up">${c.diff_pp.toFixed(2)}pp</span>`
      : `<span class="chip down">${c.diff_pp.toFixed(2)}pp</span>`;
    const pFmt = c.p < 0.0001 ? '<0.0001' : c.p.toFixed(4);
    return `<tr>
      <td class="name">${la} vs ${lb}</td>
      <td class="num">${(c.p_a*100).toFixed(2)}%</td>
      <td class="num">${(c.p_b*100).toFixed(2)}%</td>
      <td class="num">${chip}</td>
      <td class="num">${c.z.toFixed(2)}</td>
      <td class="num">${pFmt}</td>
    </tr>`;
  }).join('');
}

function update() {
  const slice = filteredSlices();
  const rollup = rollupByMissType(slice);
  const rows = withStats(rollup);
  const totalMisses = rows.reduce((a,r) => a + r.n_eligible, 0);
  // scope readout
  document.getElementById('scope-misses').textContent = totalMisses.toLocaleString();
  document.getElementById('scope-teams').textContent = STATE.teams.size || 36;
  document.getElementById('scope-seasons').textContent = STATE.seasons.size || 10;
  // low-n warning
  const lowN = rows.some(r => r.n_eligible < 200);
  document.getElementById('low-n-warning').classList.toggle('show', lowN);
  renderKpis(rows);
  renderChart(rows);
  renderTable(rows);
  renderComparisons(rows);
}

renderTeamChips(); renderSeasonChips(); update();
</script>
</body></html>
"""


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(config.PROJECT_ROOT), stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "dev"


def main() -> None:
    data = json.loads(SRC.read_text())
    slices = json.loads(SLICE_SRC.read_text())
    n_games = data["meta"]["n_games"]
    n_seasons = len(data["meta"]["seasons"])
    html = (HTML
            .replace("__JSON__", json.dumps(data))
            .replace("__SLICES__", json.dumps(slices))
            .replace("__N_GAMES__", f"{n_games:,}")
            .replace("__N_SEASONS__", str(n_seasons))
            .replace("__SHA__", _git_sha()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    log.info("wrote %s (%.1f KB)", OUT, OUT.stat().st_size / 1024)


if __name__ == "__main__":
    main()
