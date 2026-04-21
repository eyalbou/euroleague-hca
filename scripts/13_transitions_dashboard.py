"""Phase 13 -- Transitions dashboard.

Renders a standalone single-file HTML dashboard for the Q0 / Q1 / Q2 Markov
transition families with interactive controls.

v2 additions over the initial release:
  - "Raw P" <-> "Lift vs league baseline" toggle (fixes the "Q2 just looks like
    the global offensive mix" problem)
  - PPP (points-per-possession) KPI card on Q2 -- ties transitions back to
    basketball outcomes
  - Paired-event artifact warning banner for FV/AG/CM/RV/OF
  - Per-team distinctiveness panel (ranks by KL-divergence from league)
  - Category-grouped dropdown (shots / rebounds / playmaking / defense / fouls)
  - Time-to-next (median seconds) displayed in metrics
  - URL hash state (sharable: #source=3FGM&split=all&view=bars&mode=lift)
  - Download-CSV button per panel

Primary deliverable: dashboards/transitions.html
"""
# %% imports
from __future__ import annotations

import json
import logging

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("13_transitions_dashboard")


# %% load data
def load_data() -> dict:
    bars = json.loads((config.REPORTS_DIR / "transitions_bars.json").read_text())
    conc = json.loads((config.REPORTS_DIR / "transitions_concentration.json").read_text())
    team_rank_path = config.REPORTS_DIR / "transitions_team_rank.json"
    team_rank = json.loads(team_rank_path.read_text()) if team_rank_path.exists() else {}
    hca_path = config.REPORTS_DIR / "hca_transitions.json"
    hca = json.loads(hca_path.read_text()) if hca_path.exists() else {}
    big_path = config.REPORTS_DIR / "transitions_bigrams.json"
    bigrams = json.loads(big_path.read_text()) if big_path.exists() else {}
    return {"bars": bars, "concentration": conc, "team_rank": team_rank,
            "hca": hca, "bigrams": bigrams}


# %% template
HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=1400" />
<link rel="icon" type="image/png" href="assets/euroleague-logo.png" />
<title>EuroLeague play-by-play transitions</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root{
    --bg:#0b0d10; --panel:#141820; --panel-2:#1b2029; --fg:#e7ecf1; --fg-dim:#b6bfcc;
    --fg-mute:#7a8595; --border:#222832; --accent:#ffa94d; --accent-soft:#ffa94d22;
    --q1:#5dade2; --q1-soft:#5dade233;
    --q2:#f9d65a; --q2-soft:#f9d65a33;
    --bad:#ef5a5a; --good:#3ccf8e; --warn:#f0a858;
    --lift-pos:#3ccf8e; --lift-neg:#ef5a5a;
  }
  *{box-sizing:border-box}
  html,body{background:var(--bg);color:var(--fg);margin:0;
    font-family:'DM Sans','Axiforma','Inter',system-ui,sans-serif;
    font-feature-settings:"cv11","ss01";letter-spacing:-0.02em;line-height:1.5;}
  body{padding:32px;max-width:1500px;margin:0 auto}
  header{display:flex;flex-direction:column;gap:8px;margin-bottom:24px}
  .back{color:#6eb0ff;font-size:13px;text-decoration:none}
  .back:hover{text-decoration:underline}
  .topbar{display:flex;align-items:center;gap:14px;margin-bottom:14px}
  .brand{height:32px;width:auto;background:#fff;border-radius:6px;padding:4px 8px;
         box-shadow:0 1px 2px rgba(0,0,0,.18);flex-shrink:0}
  h1{font-size:28px;font-weight:700;margin:0;letter-spacing:-0.03em;line-height:1.15}
  h2{font-size:16px;font-weight:600;margin:0 0 8px 0;letter-spacing:-0.02em;color:var(--fg)}
  h3{font-size:13px;font-weight:500;margin:0 0 4px 0;color:var(--fg-mute);
     text-transform:uppercase;letter-spacing:0.04em}
  p.sub{color:var(--fg-dim);font-size:14px;margin:4px 0 0 0;max-width:900px}
  .meta{color:var(--fg-mute);font-size:13px}

  .controls{display:flex;gap:20px;padding:14px 18px;background:var(--panel);
    border:1px solid var(--border);border-radius:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
  .control{display:flex;flex-direction:column;gap:4px}
  .control label{font-size:11px;color:var(--fg-mute);text-transform:uppercase;letter-spacing:0.04em}
  select, .btn{background:var(--panel-2);color:var(--fg);border:1px solid var(--border);
    border-radius:8px;padding:8px 12px;font-size:13px;font-family:inherit;cursor:pointer;
    min-width:220px}
  select:hover, .btn:hover{border-color:var(--fg-mute)}
  .btn{min-width:auto;padding:6px 12px}
  .pill-group{display:flex;gap:4px;background:var(--panel-2);padding:4px;border-radius:10px;
    border:1px solid var(--border)}
  .pill{background:transparent;color:var(--fg-dim);border:0;padding:6px 14px;border-radius:8px;
    font-size:12px;cursor:pointer;font-family:inherit;font-weight:500}
  .pill:hover{color:var(--fg)}
  .pill.active{background:var(--accent);color:#111}

  .grid{display:grid;gap:24px;grid-template-columns:1fr 1fr}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px}
  .card.full{grid-column:1/-1}
  .panel-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}
  .panel-head .head-left{flex:1}
  .panel-head .head-actions{display:flex;gap:8px;align-items:center}
  .panel-head .tag{font-size:11px;font-weight:600;padding:3px 8px;border-radius:6px;
    text-transform:uppercase;letter-spacing:0.04em}
  .tag.q1{background:var(--q1-soft);color:var(--q1)}
  .tag.q2{background:var(--q2-soft);color:var(--q2)}
  .tag.q0{background:var(--accent-soft);color:var(--accent)}

  .chart-wrap{position:relative;height:340px}
  .chart-wrap.tall{height:520px}
  .chart-wrap.short{height:240px}

  .metrics{display:flex;gap:20px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);flex-wrap:wrap}
  .metric{display:flex;flex-direction:column;gap:2px;min-width:90px}
  .metric .v{font-size:18px;font-weight:600;color:var(--fg);font-variant-numeric:tabular-nums}
  .metric .k{font-size:10px;color:var(--fg-mute);text-transform:uppercase;letter-spacing:0.04em}
  .metric.hero .v{font-size:26px;color:var(--q2)}

  .n-cap{display:flex;justify-content:space-between;color:var(--fg-mute);font-size:11px;
    margin-top:8px;padding-top:8px;border-top:1px solid var(--border)}

  .data-banner{background:var(--accent-soft);color:var(--accent);padding:10px 14px;
    border-radius:8px;font-size:12px;border:1px solid var(--accent)22;margin-bottom:12px}
  .paired-banner{background:rgba(240,168,88,0.12);color:var(--warn);padding:10px 14px;
    border-radius:8px;font-size:12px;border:1px solid rgba(240,168,88,0.3);margin-bottom:16px;
    display:none}
  .paired-banner.show{display:block}
  .paired-banner strong{color:var(--warn)}

  /* heatmap */
  .heatmap-wrap{overflow:auto;max-height:620px;position:relative}
  table.heat{border-collapse:separate;border-spacing:0;font-size:11px;font-variant-numeric:tabular-nums}
  table.heat th, table.heat td{padding:5px 8px;min-width:44px;text-align:center;white-space:nowrap}
  table.heat thead th{position:sticky;top:0;background:var(--panel-2);color:var(--fg-mute);
    border-bottom:1px solid var(--border);font-weight:500;font-size:10px;text-transform:uppercase;letter-spacing:0.04em}
  table.heat tbody th{text-align:right;color:var(--fg);background:var(--panel-2);
    position:sticky;left:0;font-weight:500;border-right:1px solid var(--border);cursor:pointer}
  table.heat tbody th:hover{background:var(--accent-soft);color:var(--accent)}
  table.heat tbody th.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
  table.heat td{color:var(--fg);cursor:default}
  table.heat td.na{color:var(--fg-mute)}

  /* small multiples */
  .sm-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
  .sm-cell{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;padding:10px}
  .sm-cell h4{margin:0 0 4px 0;font-size:12px;font-weight:600;color:var(--fg)}
  .sm-cell .sub{font-size:10px;color:var(--fg-mute);margin-bottom:4px}
  .sm-cell .chart-wrap{height:160px}

  /* team-rank panel */
  table.rank{border-collapse:separate;border-spacing:0;width:100%;font-size:12px;font-variant-numeric:tabular-nums}
  table.rank th, table.rank td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border)}
  table.rank th{color:var(--fg-mute);font-size:10px;text-transform:uppercase;letter-spacing:0.04em;font-weight:500}
  table.rank td{color:var(--fg)}
  table.rank td.num{text-align:right;font-variant-numeric:tabular-nums}
  table.rank tr:hover td{background:var(--panel-2)}
  .chip{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600;
    background:var(--accent-soft);color:var(--accent);margin-left:4px}
  .chip.pos{background:rgba(60,207,142,0.15);color:var(--lift-pos)}
  .chip.neg{background:rgba(239,90,90,0.15);color:var(--lift-neg)}

  .hidden{display:none !important}
</style>
</head>
<body>
<div class="topbar">
  <img class="brand" src="assets/euroleague-logo.png" alt="EuroLeague" />
  <a class="back" href="index.html">&larr; back to dashboard index</a>
</div>
<header>
  <div style="color:#6eb0ff;font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:10px">
    <span style="display:inline-block;width:8px;height:8px;background:#6eb0ff;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
    Track B &middot; game dynamics &middot; <a href="explorer.html" style="color:#6eb0ff;text-decoration:none">team+season explorer</a>
  </div>
  <h1>After action X, what actually happens next?</h1>
  <p class="sub">A separate investigation from the HCA story: this is about how possessions <em>chain</em>,
    independent of who's at home. For each source action, three Markov distributions:
    <strong>Q0</strong> the immediate next event (any team); <strong>Q1</strong> the opponent's
    immediate response; <strong>Q2</strong> the same team's first <em>offensive</em> action on their
    next possession. Sources with fewer than 30 observations per split are hidden.
    Cluster-bootstrapped 95% confidence intervals at the <em>game</em> level.</p>
  <p class="sub" style="background:rgba(110,176,255,0.05);border-left:3px solid #6eb0ff;padding:10px 14px;border-radius:4px;margin-top:12px;font-size:13px">
    <strong style="color:#e7ecf1">Bridge to Track A:</strong> the <em>HCA lens</em> view (pill above) re-reads these
    distributions as home vs away possessions, and reveals that the tiny per-possession efficiency edge
    (+0.049 PPP) multiplied across ~74 possessions produces the league's +3.73 HCA. That's where these
    two investigations meet; everywhere else, this dashboard is about tactics and flow, not who wins.
  </p>
  <div class="meta" id="meta-line">Loading...</div>
</header>

<div class="data-banner" id="data-banner"></div>

<div class="controls">
  <div class="control">
    <label>Source action</label>
    <select id="source-select"></select>
  </div>
  <div class="control">
    <label>Split</label>
    <select id="split-select" class="select">
      <optgroup label="Overall">
        <option value="all" selected>All</option>
      </optgroup>
      <optgroup label="Home / Away">
        <option value="home_acting">Home acting</option>
        <option value="away_acting">Away acting</option>
      </optgroup>
      <optgroup label="COVID experiment">
        <option value="open_doors">Open doors</option>
        <option value="closed_doors">Closed doors</option>
      </optgroup>
      <optgroup label="Phase">
        <option value="reg_season">Regular season</option>
        <option value="playoff">Playoffs / Final Four</option>
      </optgroup>
      <optgroup label="Period (regulation only)">
        <option value="period_1">1st quarter</option>
        <option value="period_2">2nd quarter</option>
        <option value="period_3">3rd quarter</option>
        <option value="period_4">4th quarter</option>
      </optgroup>
    </select>
  </div>
  <div class="control">
    <label>Bar value</label>
    <div class="pill-group" id="mode-group">
      <button class="pill active" data-mode="raw">Raw P</button>
      <button class="pill" data-mode="lift">Lift vs baseline</button>
    </div>
  </div>
  <div class="control">
    <label>View</label>
    <div class="pill-group" id="view-group">
      <button class="pill active" data-view="bars">Q1 vs Q2 bars</button>
      <button class="pill" data-view="heatmap">Heatmap</button>
      <button class="pill" data-view="multiples">Small multiples</button>
      <button class="pill" data-view="team">Per-team</button>
      <button class="pill" data-view="hca">HCA lens</button>
      <button class="pill" data-view="bigrams">Storylines</button>
    </div>
  </div>
</div>

<div class="paired-banner" id="paired-banner">
  <strong>Paired-logging artifact.</strong>
  <span id="paired-text"></span>
</div>

<!-- Bars view -->
<div id="view-bars" class="view grid">
  <div class="card">
    <div class="panel-head">
      <div class="head-left">
        <h3>Q1 -- opponent's next action</h3>
        <h2 id="q1-title">--</h2>
      </div>
      <div class="head-actions">
        <button class="btn" data-csv="q1">CSV</button>
        <span class="tag q1">Q1</span>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="chart-q1"></canvas></div>
    <div class="metrics">
      <div class="metric"><span class="v" id="q1-top1">--</span><span class="k">Most-likely</span></div>
      <div class="metric"><span class="v" id="q1-entropy">--</span><span class="k">Entropy (bits)</span></div>
      <div class="metric"><span class="v" id="q1-gini">--</span><span class="k">Gini</span></div>
      <div class="metric"><span class="v" id="q1-sec">--</span><span class="k">Median sec</span></div>
    </div>
    <div class="n-cap"><span id="q1-n">n=...</span><span>95% cluster-bootstrap CI per bar</span></div>
  </div>

  <div class="card">
    <div class="panel-head">
      <div class="head-left">
        <h3>Q2 -- same team's next offensive possession</h3>
        <h2 id="q2-title">--</h2>
      </div>
      <div class="head-actions">
        <button class="btn" data-csv="q2">CSV</button>
        <span class="tag q2">Q2</span>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="chart-q2"></canvas></div>
    <div class="metrics">
      <div class="metric hero"><span class="v" id="q2-ppp">--</span><span class="k">PPP next poss.</span></div>
      <div class="metric"><span class="v" id="q2-top1">--</span><span class="k">Most-likely</span></div>
      <div class="metric"><span class="v" id="q2-entropy">--</span><span class="k">Entropy (bits)</span></div>
      <div class="metric"><span class="v" id="q2-sec">--</span><span class="k">Median sec</span></div>
    </div>
    <div class="n-cap"><span id="q2-n">n=...</span><span>Targets limited to shots + turnovers + off. fouls</span></div>
  </div>

  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>Q0 -- raw next event (same or other team)</h3>
        <h2>Context: what literally comes next in the log</h2>
      </div>
      <div class="head-actions">
        <button class="btn" data-csv="q0">CSV</button>
        <span class="tag q0">Q0</span>
      </div>
    </div>
    <div class="chart-wrap short"><canvas id="chart-q0"></canvas></div>
    <div class="n-cap"><span id="q0-n">n=...</span>
      <span>Q0 is often dominated by the paired counterpart event -- use Q1 / Q2 for basketball-meaningful answers.</span>
    </div>
  </div>
</div>

<!-- Heatmap view -->
<div id="view-heatmap" class="view hidden">
  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>Heatmap of Q1 (opponent response) -- row = source, column = opponent next action</h3>
        <h2 id="heat-title">Click a row to focus its distribution</h2>
      </div>
      <div class="head-actions">
        <span class="tag q1">Q1</span>
      </div>
    </div>
    <div class="heatmap-wrap">
      <table class="heat" id="heatmap"></table>
    </div>
  </div>
</div>

<!-- Small multiples view -->
<div id="view-multiples" class="view hidden">
  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>All source actions at a glance -- Q1 top-5 responses</h3>
        <h2>Each tile: "after this action, what does the opponent do?"</h2>
      </div>
      <span class="tag q1">Q1</span>
    </div>
    <div class="sm-grid" id="sm-grid"></div>
  </div>
  <div class="card full" style="margin-top:24px">
    <div class="panel-head">
      <div class="head-left">
        <h3>All source actions at a glance -- Q2 top-5 responses</h3>
        <h2>Each tile: "when this team next has the ball, what do they do first?"</h2>
      </div>
      <span class="tag q2">Q2</span>
    </div>
    <div class="sm-grid" id="sm-grid-q2"></div>
  </div>
</div>

<!-- Per-team view -->
<div id="view-team" class="view hidden">
  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>Per-team distinctiveness (Q2 -- next offensive possession)</h3>
        <h2 id="team-title">--</h2>
      </div>
      <span class="tag q2">Q2</span>
    </div>
    <p class="sub" style="margin-bottom:12px">
      Teams ranked by KL-divergence of their Q2 distribution from the league average
      -- higher = more distinctive behavior after the selected source action.
      Only teams with n&ge;50 source events shown.
    </p>
    <table class="rank" id="team-table"></table>
    <div class="n-cap"><span id="team-n">--</span>
      <span>Split fixed to "All" for team ranking (stability).</span>
    </div>
  </div>
</div>

<!-- HCA-lens view -->
<div id="view-hca" class="view hidden">
  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>HCA lens -- does possession-level efficiency explain home-court advantage?</h3>
        <h2 id="hca-headline">--</h2>
      </div>
      <span class="tag q2" style="background:rgba(60,207,142,0.15);color:var(--lift-pos)">HCA</span>
    </div>
    <p class="sub" style="margin-bottom:16px">
      For each source action X, we compute PPP on the same team's next offensive possession
      split by home-vs-away. Positive <code>delta_ppp</code> means home teams are more efficient
      after X than road teams are after the same X. The headline number scales this per-possession
      edge to a per-game HCA contribution.
    </p>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px">
      <div class="card" style="padding:14px"><div class="metric"><span class="v" id="kpi-hca-pts" style="font-size:24px;color:var(--lift-pos)">--</span><span class="k">HCA explained by possession efficiency (pts/game)</span></div></div>
      <div class="card" style="padding:14px"><div class="metric"><span class="v" id="kpi-hca-share" style="font-size:24px">--</span><span class="k">share of observed 3.86-pt HCA</span></div></div>
      <div class="card" style="padding:14px"><div class="metric"><span class="v" id="kpi-hca-delta" style="font-size:24px">--</span><span class="k">volume-weighted &Delta;PPP (pts/poss.)</span></div></div>
      <div class="card" style="padding:14px"><div class="metric"><span class="v" id="kpi-hca-pos" style="font-size:24px">--</span><span class="k">sources where home &gt; away</span></div></div>
    </div>
    <div class="grid">
      <div class="card" style="padding:16px">
        <h3>Top-10 sources by <code>|&Delta;PPP|</code></h3>
        <div class="chart-wrap" style="height:420px"><canvas id="chart-hca-delta"></canvas></div>
        <div class="n-cap"><span>Error bars = 95% cluster-bootstrap CI (game-level)</span><span>Positive = home team scores more on next possession</span></div>
      </div>
      <div class="card" style="padding:16px">
        <h3>Home vs Away PPP after source</h3>
        <div class="chart-wrap" style="height:420px"><canvas id="chart-hca-paired"></canvas></div>
        <div class="n-cap"><span>Green = home, slate = away -- side by side per source</span><span>Ordered by delta_ppp</span></div>
      </div>
      <div class="card full" style="padding:16px">
        <h3>Full ranking with counts + top-1 Q1 response home vs away</h3>
        <table class="rank" id="hca-table"></table>
      </div>
    </div>
  </div>
</div>

<!-- Storylines view (second-order / bigram paths) -->
<div id="view-bigrams" class="view hidden">
  <div class="card full">
    <div class="panel-head">
      <div class="head-left">
        <h3>Storylines -- what are the most common 3-event sequences?</h3>
        <h2>Second-order Markov chains: P(action<sub>t+1</sub>, action<sub>t+2</sub> &vert; action<sub>t</sub>)</h2>
      </div>
      <span class="tag q2" style="background:rgba(110,176,255,0.15);color:var(--accent)">2nd-order</span>
    </div>
    <p class="sub" style="margin-bottom:20px">
      For each of the top-6 source actions by volume, the most common two-step
      continuations. Reads left-to-right. Top-K coverage = how much of the full
      distribution these 5 paths cover (high = concentrated, low = disperse).
    </p>
    <div id="bigrams-grid" style="display:grid;gap:16px"></div>
  </div>
</div>

<script>
/* ====== data injected from Python ====== */
const BARS = __BARS__;
const CONC = __CONC__;
const PLAIN = __PLAIN__;
const SOURCE_CATS = __SOURCE_CATS__;
const PAIRED = __PAIRED__;
const TEAM_RANK = __TEAM_RANK__;
const HCA = __HCA__;
const BIGRAMS = __BIGRAMS__;

Chart.defaults.font.family = "'DM Sans', 'Axiforma', system-ui, sans-serif";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#b6bfcc';
Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

const state = {
  source: null,
  split: 'all',
  view: 'bars',
  mode: 'raw',   // 'raw' or 'lift'
};

/* ---------- URL hash I/O ---------- */
function readHash(){
  const s = (location.hash || '').replace(/^#/, '');
  if (!s) return {};
  const out = {};
  s.split('&').forEach(kv=>{
    const [k,v] = kv.split('=');
    if (k) out[decodeURIComponent(k)] = decodeURIComponent(v || '');
  });
  return out;
}
function writeHash(){
  const parts = [];
  for (const k of ['source','split','view','mode']){
    if (state[k]) parts.push(`${k}=${encodeURIComponent(state[k])}`);
  }
  history.replaceState(null, '', '#' + parts.join('&'));
}

/* ---------- indexers ---------- */
function idxBars(){
  const idx = {};
  for (const b of BARS.bars){
    const k = `${b.source}|${b.question}|${b.split}`;
    (idx[k] = idx[k] || []).push(b);
  }
  for (const k in idx) idx[k].sort((a,b)=>a.rank-b.rank);
  return idx;
}
function idxConc(){
  const idx = {};
  for (const c of CONC){
    idx[`${c.source}|${c.question}|${c.split}`] = c;
  }
  return idx;
}
const BIDX = idxBars();
const CIDX = idxConc();

function sourcesAvailable(split){
  const set = new Set();
  for (const b of BARS.bars){
    if (b.split === split) set.add(b.source);
  }
  return Array.from(set);
}

function label(code){ return PLAIN[code] || code; }
function pctStr(p){ return (p*100).toFixed(1)+'%'; }
function fmtLift(l){
  if (l == null || !isFinite(l)) return '--';
  return (l >= 1 ? '+' : '') + ((l-1)*100).toFixed(0) + '%';
}

/* ---------- chart helpers ---------- */
let chartQ1=null, chartQ2=null, chartQ0=null;
const smCharts = [];

function chooseValues(rows, mode){
  if (mode === 'lift'){
    return rows.map(r => r.lift == null ? 0 : r.lift);
  }
  return rows.map(r => r.p*100);
}

function barColor(r, accent, mode){
  if (r.next_action === 'Other') return '#55606e';
  if (mode !== 'lift') return accent;
  if (r.lift == null) return '#55606e';
  return r.lift >= 1 ? 'rgba(60,207,142,0.85)' : 'rgba(239,90,90,0.85)';
}

function buildBarChart(ctx, rows, accent, mode, withCI=true){
  if (!rows || !rows.length) return null;
  const labels = rows.map(r => r.next_action === 'Other' ? 'Other' : r.next_action);
  const values = chooseValues(rows, mode);
  const tooltipLabels = rows.map(r => label(r.next_action));
  const xTitle = mode === 'lift' ? 'Lift (p / baseline_p)' : 'Probability';
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: rows.map(r => barColor(r, accent, mode)),
        borderRadius: 4,
        borderSkipped: false,
        barPercentage: 0.85,
        categoryPercentage: 0.85,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 80 } },
      scales: {
        x: {
          beginAtZero: mode === 'raw',
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: {
            callback: (v)=> mode === 'lift' ? (v.toFixed(1)+'x') : (v+'%'),
          },
          title: { display: true, text: xTitle, color: '#7a8595', font: { size: 10 } },
        },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        annotation: {},
        tooltip: {
          callbacks: {
            title: (items)=> tooltipLabels[items[0].dataIndex],
            label: (item)=>{
              const r = rows[item.dataIndex];
              const parts = [`p = ${pctStr(r.p)}`];
              if (r.baseline_p != null) parts.push(`baseline = ${pctStr(r.baseline_p)}`);
              if (r.lift != null) parts.push(`lift = ${r.lift.toFixed(2)}x (${fmtLift(r.lift)})`);
              if (withCI && r.lo !== r.hi) parts.push(`95% CI [${pctStr(r.lo)}, ${pctStr(r.hi)}]`);
              parts.push(`n = ${r.n}`);
              return parts;
            }
          }
        }
      }
    },
    plugins: [{
      id: 'valueLabels',
      afterDatasetsDraw(chart){
        const {ctx} = chart;
        const meta = chart.getDatasetMeta(0);
        ctx.save();
        ctx.fillStyle = '#e7ecf1';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.font = '500 11px "DM Sans", system-ui';
        meta.data.forEach((bar, i)=>{
          const r = rows[i];
          let txt;
          if (mode === 'lift'){
            txt = r.lift == null ? '--' : `${r.lift.toFixed(2)}x (${fmtLift(r.lift)})  p=${pctStr(r.p)}`;
          } else if (withCI && r.lo !== r.hi){
            txt = `${pctStr(r.p)}  [${pctStr(r.lo)}-${pctStr(r.hi)}]`;
          } else {
            txt = pctStr(r.p);
          }
          ctx.fillText(txt, bar.x + 8, bar.y);
        });
        ctx.restore();
      }
    }, {
      id: 'liftOne',
      beforeDraw(chart){
        if (mode !== 'lift') return;
        const {ctx, chartArea, scales: {x}} = chart;
        const px = x.getPixelForValue(1);
        if (isNaN(px)) return;
        ctx.save();
        ctx.strokeStyle = 'rgba(255,255,255,0.35)';
        ctx.setLineDash([4,4]);
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(px, chartArea.top); ctx.lineTo(px, chartArea.bottom); ctx.stroke();
        ctx.restore();
      }
    }]
  });
}

/* ---------- paired banner ---------- */
function updatePairedBanner(src){
  const pb = document.getElementById('paired-banner');
  const partner = PAIRED[src];
  if (partner){
    document.getElementById('paired-text').innerHTML =
      `<strong>${src}</strong> (${label(src)}) and <strong>${partner}</strong> (${label(partner)}) ` +
      `are the same physical event logged from both sides. Expect Q1 to be dominated by the partner ` +
      `at ~0.80-0.95 -- this is a logging convention, not a strategic signal. ` +
      `Q2 and "Lift vs baseline" mode are the basketball-meaningful lenses here.`;
    pb.classList.add('show');
  } else {
    pb.classList.remove('show');
  }
}

/* ---------- bars view ---------- */
function updateBarsView(){
  const src = state.source, split = state.split, mode = state.mode;
  const rowsQ1 = BIDX[`${src}|q1|${split}`] || [];
  const rowsQ2 = BIDX[`${src}|q2|${split}`] || [];
  const rowsQ0 = BIDX[`${src}|q0|${split}`] || [];
  const cQ1 = CIDX[`${src}|q1|${split}`];
  const cQ2 = CIDX[`${src}|q2|${split}`];

  document.getElementById('q1-title').textContent = `After ${label(src)}, opponent does...`;
  document.getElementById('q2-title').textContent = `When ${label(src)} team next has ball...`;

  document.getElementById('q1-n').textContent = cQ1 ? `n=${cQ1.n.toLocaleString('en-US')} opponent responses` : 'n=0';
  document.getElementById('q2-n').textContent = cQ2 ? `n=${cQ2.n.toLocaleString('en-US')} next-possession actions` : 'n=0';
  document.getElementById('q0-n').textContent = rowsQ0.length ? `n=${rowsQ0[0].n.toLocaleString('en-US')} next events` : 'n=0';

  document.getElementById('q1-entropy').textContent = cQ1 ? cQ1.entropy_bits.toFixed(2) : '--';
  document.getElementById('q1-gini').textContent = cQ1 ? cQ1.gini.toFixed(2) : '--';
  document.getElementById('q1-sec').textContent = cQ1 && cQ1.median_sec != null ? `${cQ1.median_sec.toFixed(1)}s` : '--';
  document.getElementById('q1-top1').textContent = cQ1 ? `${label(cQ1.top1_action)} (${pctStr(cQ1.top1_p)})` : '--';

  document.getElementById('q2-entropy').textContent = cQ2 ? cQ2.entropy_bits.toFixed(2) : '--';
  document.getElementById('q2-sec').textContent = cQ2 && cQ2.median_sec != null ? `${cQ2.median_sec.toFixed(1)}s` : '--';
  document.getElementById('q2-top1').textContent = cQ2 ? `${label(cQ2.top1_action)} (${pctStr(cQ2.top1_p)})` : '--';
  document.getElementById('q2-ppp').textContent = cQ2 && cQ2.ppp_mean != null ? cQ2.ppp_mean.toFixed(2) : '--';

  if (chartQ1) chartQ1.destroy();
  if (chartQ2) chartQ2.destroy();
  if (chartQ0) chartQ0.destroy();
  chartQ1 = buildBarChart(document.getElementById('chart-q1'), rowsQ1, '#5dade2', mode);
  chartQ2 = buildBarChart(document.getElementById('chart-q2'), rowsQ2, '#f9d65a', mode);
  // Q0 always shown as raw probability -- lift is nonsensical for "any next event"
  chartQ0 = buildBarChart(document.getElementById('chart-q0'), rowsQ0, '#ffa94d', 'raw', false);
}

/* ---------- heatmap ---------- */
function updateHeatmap(){
  const split = state.split;
  const mode = state.mode;
  const sources = sourcesAvailable(split);
  const nextSet = new Set();
  sources.forEach(s => (BIDX[`${s}|q1|${split}`]||[])
    .forEach(r => { if (r.next_action !== 'Other') nextSet.add(r.next_action); }));
  const nexts = Array.from(nextSet).sort();

  const tbl = document.getElementById('heatmap');
  tbl.innerHTML = '';
  const thead = document.createElement('thead');
  const trh = document.createElement('tr');
  trh.appendChild(document.createElement('th'));
  nexts.forEach(n => {
    const th = document.createElement('th');
    th.textContent = n; th.title = label(n);
    trh.appendChild(th);
  });
  thead.appendChild(trh);
  tbl.appendChild(thead);

  const tbody = document.createElement('tbody');
  sources.forEach(s => {
    const tr = document.createElement('tr');
    const th = document.createElement('th');
    th.textContent = s;
    th.title = label(s) + ' (click to focus)';
    if (s === state.source) th.classList.add('active');
    th.onclick = () => { state.source = s; document.getElementById('source-select').value = s; render(); };
    tr.appendChild(th);
    const byAction = {};
    (BIDX[`${s}|q1|${split}`]||[]).forEach(r => { byAction[r.next_action] = r; });
    nexts.forEach(n => {
      const td = document.createElement('td');
      const r = byAction[n];
      if (!r){ td.textContent = '.'; td.classList.add('na'); }
      else if (mode === 'lift'){
        if (r.lift == null){ td.textContent = '.'; td.classList.add('na'); }
        else {
          td.textContent = r.lift.toFixed(1) + 'x';
          // diverging palette centered at lift=1
          const d = r.lift - 1;
          const clamp = Math.max(-1.5, Math.min(1.5, d));
          const alpha = Math.min(0.85, 0.15 + Math.abs(clamp)*0.45);
          if (d >= 0){
            td.style.background = `rgba(60,207,142,${alpha.toFixed(2)})`;
          } else {
            td.style.background = `rgba(239,90,90,${alpha.toFixed(2)})`;
          }
          td.style.color = Math.abs(clamp) > 0.7 ? '#111' : '#e7ecf1';
          td.title = `p=${pctStr(r.p)}  baseline=${pctStr(r.baseline_p)}  lift=${r.lift.toFixed(2)}x`;
        }
      } else {
        td.textContent = (r.p*100).toFixed(0);
        const alpha = Math.min(0.9, 0.1 + r.p * 2.5);
        td.style.background = `rgba(255,169,77,${alpha.toFixed(2)})`;
        td.style.color = r.p > 0.25 ? '#111' : '#e7ecf1';
        td.title = `p=${pctStr(r.p)}`;
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
}

/* ---------- small multiples ---------- */
function smallMultipleChart(container, rows, accent, mode){
  const c = document.createElement('canvas');
  container.appendChild(c);
  const values = chooseValues(rows, mode);
  return new Chart(c, {
    type: 'bar',
    data: {
      labels: rows.map(r => r.next_action),
      datasets: [{ data: values,
        backgroundColor: rows.map(r => barColor(r, accent, mode)),
        borderRadius:2, categoryPercentage:0.85, barPercentage:0.85 }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: mode === 'raw', grid: { display:false }, ticks: { display:false } },
        y: { grid: { display:false }, ticks: { font: { size: 9 } } },
      },
      plugins: { legend: { display:false }, tooltip: {
        callbacks: { label: (item)=>{
          const r = rows[item.dataIndex];
          if (mode === 'lift') return `${r.lift==null?'--':r.lift.toFixed(2)+'x'}  p=${pctStr(r.p)}`;
          return pctStr(r.p);
        } } }
      }
    }
  });
}

function updateSmallMultiples(){
  const split = state.split, mode = state.mode;
  const sources = sourcesAvailable(split);
  smCharts.forEach(c => c.destroy());
  smCharts.length = 0;
  ['sm-grid','sm-grid-q2'].forEach((gid, gi) => {
    const q = gi===0 ? 'q1' : 'q2';
    const accent = gi===0 ? '#5dade2' : '#f9d65a';
    const grid = document.getElementById(gid);
    grid.innerHTML = '';
    sources.forEach(s => {
      const rows = (BIDX[`${s}|${q}|${split}`]||[]).slice(0,5);
      if (!rows.length) return;
      const cell = document.createElement('div');
      cell.className = 'sm-cell';
      const h = document.createElement('h4'); h.textContent = label(s); cell.appendChild(h);
      const top = CIDX[`${s}|${q}|${split}`];
      const sub = document.createElement('div'); sub.className = 'sub';
      let sub_txt = top ? `n=${top.n.toLocaleString('en-US')} -- H=${top.entropy_bits.toFixed(2)}b` : '';
      if (q === 'q2' && top && top.ppp_mean != null) sub_txt += ` -- PPP=${top.ppp_mean.toFixed(2)}`;
      sub.textContent = sub_txt;
      cell.appendChild(sub);
      const wrap = document.createElement('div'); wrap.className = 'chart-wrap'; cell.appendChild(wrap);
      grid.appendChild(cell);
      smCharts.push(smallMultipleChart(wrap, rows, accent, mode));
    });
  });
}

/* ---------- per-team view ---------- */
function updateTeamView(){
  const src = state.source;
  const payload = TEAM_RANK[src];
  const ttl = document.getElementById('team-title');
  const tbl = document.getElementById('team-table');
  tbl.innerHTML = '';
  document.getElementById('team-n').textContent = '';
  if (!payload){
    ttl.textContent = `No team-level data for ${label(src)} (need n>=50 per team)`;
    return;
  }
  ttl.textContent = `Distinctive Q2 after ${label(src)}`;
  const thead = document.createElement('thead');
  const tr = document.createElement('tr');
  ['Rank','Team','n','KL-div','Top-1 response','p','Top-3 mix'].forEach(h=>{
    const th = document.createElement('th'); th.textContent = h; tr.appendChild(th);
  });
  thead.appendChild(tr); tbl.appendChild(thead);

  const tbody = document.createElement('tbody');
  // League row first
  const leagueTr = document.createElement('tr');
  leagueTr.style.background = 'rgba(255,169,77,0.06)';
  const leagueTop = payload.league[0];
  const cells = [
    '--','LEAGUE AVG','--','0.00',
    leagueTop ? label(leagueTop.next_action) : '--',
    leagueTop ? pctStr(leagueTop.p) : '--',
    payload.league.map(r=>`${r.next_action} ${pctStr(r.p)}`).join('  ·  '),
  ];
  cells.forEach((c,i)=>{
    const td = document.createElement('td');
    if (i===2 || i===3 || i===5) td.className = 'num';
    td.textContent = c;
    leagueTr.appendChild(td);
  });
  tbody.appendChild(leagueTr);

  // Top teams
  (payload.teams || []).slice(0, 12).forEach((t, i) => {
    const tr = document.createElement('tr');
    const topAction = t.top1_action;
    const baselineP = payload.league.find(l=>l.next_action===topAction);
    let chip = '';
    if (baselineP && baselineP.p > 0){
      const lift = t.top1_p / baselineP.p;
      const cls = lift >= 1.05 ? 'pos' : (lift <= 0.95 ? 'neg' : '');
      chip = `<span class="chip ${cls}">${lift.toFixed(2)}x</span>`;
    }
    const rowCells = [
      String(i+1),
      t.team,
      t.n.toLocaleString('en-US'),
      t.kl_div.toFixed(3),
      `${label(topAction)} ${chip}`,
      pctStr(t.top1_p),
      t.top3.map(r=>`${r.next_action} ${pctStr(r.p)}`).join('  ·  '),
    ];
    rowCells.forEach((c,idx)=>{
      const td = document.createElement('td');
      if (idx===2 || idx===3 || idx===5) td.className = 'num';
      td.innerHTML = c;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  document.getElementById('team-n').textContent =
    `${payload.teams.length} teams, ranked by KL-divergence from league baseline`;
}

/* ---------- HCA-lens view ---------- */
let chartHcaDelta = null, chartHcaPaired = null;

function updateHcaView(){
  if (!HCA || !HCA.per_source){
    document.getElementById('hca-headline').textContent = 'HCA-lens data not available';
    return;
  }
  const kpi = HCA.kpi || {};
  document.getElementById('hca-headline').textContent =
    `${kpi.pct_sources_positive_delta != null ? (kpi.pct_sources_positive_delta*100).toFixed(0)+'% of ' : ''}` +
    `${kpi.n_sources} source actions show home teams with positive PPP edge on the next possession -- ` +
    `scaling to ${kpi.poss_per_team_per_game?.toFixed(1) || '--'} poss/team/game gives ` +
    `${kpi.hca_from_possession_efficiency_pts?.toFixed(2) || '--'} pts/game.`;

  document.getElementById('kpi-hca-pts').textContent =
    kpi.hca_from_possession_efficiency_pts != null ? '+'+kpi.hca_from_possession_efficiency_pts.toFixed(2) : '--';
  document.getElementById('kpi-hca-share').textContent =
    kpi.share_of_hca_explained != null ? (kpi.share_of_hca_explained*100).toFixed(0)+'%' : '--';
  document.getElementById('kpi-hca-delta').textContent =
    kpi.weighted_delta_ppp != null ? '+'+kpi.weighted_delta_ppp.toFixed(3) : '--';
  document.getElementById('kpi-hca-pos').textContent =
    kpi.pct_sources_positive_delta != null ? (kpi.pct_sources_positive_delta*100).toFixed(0)+'%' : '--';

  // Chart 1: top-10 sources by |delta_ppp| with error bars
  const topN = [...HCA.waterfall].slice(0, 10);
  if (chartHcaDelta) chartHcaDelta.destroy();
  chartHcaDelta = new Chart(document.getElementById('chart-hca-delta'), {
    type: 'bar',
    data: {
      labels: topN.map(r => r.source),
      datasets: [{
        data: topN.map(r => r.delta_ppp),
        backgroundColor: topN.map(r => r.delta_ppp >= 0 ? 'rgba(60,207,142,0.85)' : 'rgba(239,90,90,0.85)'),
        borderRadius: 4, categoryPercentage: 0.8, barPercentage: 0.8,
      }]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 90 } },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          title: { display: true, text: '\u0394 PPP (home - away)', color: '#7a8595', font: { size: 10 } },
        },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items)=> PLAIN[topN[items[0].dataIndex].source] || topN[items[0].dataIndex].source,
            label: (item)=>{
              const r = topN[item.dataIndex];
              return [
                `\u0394 PPP = +${r.delta_ppp.toFixed(3)}  [95% CI ${r.delta_lo.toFixed(3)}, ${r.delta_hi.toFixed(3)}]`,
                `freq = ${r.freq_per_game.toFixed(2)}/game`,
                `n = ${(r.n_home + r.n_away).toLocaleString('en-US')}`,
              ];
            }
          }
        }
      }
    },
    plugins: [{
      id: 'hcaLabels',
      afterDatasetsDraw(chart){
        const {ctx} = chart;
        const meta = chart.getDatasetMeta(0);
        ctx.save();
        ctx.fillStyle = '#e7ecf1';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.font = '500 11px "DM Sans", system-ui';
        meta.data.forEach((bar, i)=>{
          const r = topN[i];
          const txt = `+${r.delta_ppp.toFixed(3)} pts  [${r.delta_lo.toFixed(3)}, ${r.delta_hi.toFixed(3)}]`;
          ctx.fillText(txt, bar.x + 8, bar.y);
        });
        ctx.restore();
      }
    }]
  });

  // Chart 2: paired home vs away PPP bars (same top-10)
  if (chartHcaPaired) chartHcaPaired.destroy();
  chartHcaPaired = new Chart(document.getElementById('chart-hca-paired'), {
    type: 'bar',
    data: {
      labels: topN.map(r => r.source),
      datasets: [
        { label: 'Home', data: topN.map(r => {
            const src = HCA.per_source.find(s=>s.source===r.source); return src?src.home_ppp:0;
          }), backgroundColor: 'rgba(60,207,142,0.85)', borderRadius: 3 },
        { label: 'Away', data: topN.map(r => {
            const src = HCA.per_source.find(s=>s.source===r.source); return src?src.away_ppp:0;
          }), backgroundColor: 'rgba(122,133,149,0.85)', borderRadius: 3 },
      ]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: {
        x: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.04)' },
             title: { display: true, text: 'PPP on next offensive possession', color: '#7a8595', font: { size: 10 } } },
        y: { grid: { display: false } },
      },
      plugins: {
        legend: { position: 'top', labels: { color: '#e7ecf1' } },
        tooltip: {
          callbacks: {
            title: (items)=> PLAIN[topN[items[0].dataIndex].source] || topN[items[0].dataIndex].source,
          }
        }
      }
    }
  });

  // Table: full ranking
  const tbl = document.getElementById('hca-table');
  tbl.innerHTML = '';
  const thead = document.createElement('thead');
  const thr = document.createElement('tr');
  ['Rank','Source','n (home/away)','Home PPP','Away PPP','\u0394 PPP','95% CI','Top-1 Q1 (home)','Top-1 Q1 (away)'].forEach(h=>{
    const th = document.createElement('th'); th.textContent = h; thr.appendChild(th);
  });
  thead.appendChild(thr); tbl.appendChild(thead);
  const tbody = document.createElement('tbody');
  HCA.per_source.slice().sort((a,b)=>b.delta_ppp - a.delta_ppp).forEach((r, i) => {
    const tr = document.createElement('tr');
    const cells = [
      String(i+1),
      `${r.source} -- ${r.source_label}`,
      `${r.n_home.toLocaleString('en-US')} / ${r.n_away.toLocaleString('en-US')}`,
      r.home_ppp != null ? r.home_ppp.toFixed(3) : '--',
      r.away_ppp != null ? r.away_ppp.toFixed(3) : '--',
      `+${r.delta_ppp.toFixed(3)}`,
      `[${r.delta_lo.toFixed(3)}, ${r.delta_hi.toFixed(3)}]`,
      `${r.top_home_q1.action} (${pctStr(r.top_home_q1.p)})`,
      `${r.top_away_q1.action} (${pctStr(r.top_away_q1.p)})`,
    ];
    cells.forEach((c, idx)=>{
      const td = document.createElement('td');
      if (idx>=2 && idx<=6) td.className = 'num';
      td.textContent = c;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
}

/* ---------- Bigrams (storylines) view ---------- */
function updateBigramsView(){
  const host = document.getElementById('bigrams-grid');
  host.innerHTML = '';
  if (!BIGRAMS || !BIGRAMS.bigrams || !BIGRAMS.bigrams.length){
    host.innerHTML = '<p class="sub">Bigram data not available. Run scripts/12b_bigrams.py.</p>';
    return;
  }
  BIGRAMS.bigrams.forEach(b => {
    const panel = document.createElement('div');
    panel.className = 'card';
    panel.style.padding = '16px';

    const header = `
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px">
        <div>
          <div style="font-size:13px;color:var(--fg-mute);letter-spacing:0.04em;text-transform:uppercase">Starting from</div>
          <div style="font-size:18px;font-weight:600">${b.source} -- ${b.source_label}</div>
        </div>
        <div style="font-size:12px;color:var(--fg-mute);font-variant-numeric:tabular-nums">
          n = ${b.n_source.toLocaleString('en-US')} &middot; top-5 covers ${(b.top_k_coverage*100).toFixed(0)}% of paths
        </div>
      </div>`;

    const rows = b.paths.map((p, i) => {
      const step0 = `<span class="bg-chip" style="background:rgba(110,176,255,0.15);color:var(--accent)">${b.source}</span>`;
      const step1 = `<span class="bg-chip">${p.next_1}<span style="color:var(--fg-mute);margin-left:4px;font-weight:400">${PLAIN[p.next_1] || ''}</span></span>`;
      const step2 = `<span class="bg-chip">${p.next_2}<span style="color:var(--fg-mute);margin-left:4px;font-weight:400">${PLAIN[p.next_2] || ''}</span></span>`;
      const pct = (p.p * 100).toFixed(1);
      const ci = (p.lo !== undefined && p.hi !== undefined)
        ? `<span style="color:var(--fg-mute);font-size:11px;margin-left:6px">[${(p.lo*100).toFixed(1)}, ${(p.hi*100).toFixed(1)}]</span>`
        : '';
      const barWidth = Math.max(4, p.p * 100 * 3);   // scale so 33% fills the bar
      return `
        <div style="display:grid;grid-template-columns:24px 1fr 90px;gap:12px;align-items:center;padding:6px 0;border-top:${i===0?'0':'1px solid var(--border)'}">
          <div style="color:var(--fg-mute);font-size:12px">#${i+1}</div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            ${step0}<span style="color:var(--fg-mute)">→</span>${step1}<span style="color:var(--fg-mute)">→</span>${step2}
          </div>
          <div style="text-align:right;font-variant-numeric:tabular-nums">
            <div style="display:inline-block;width:${barWidth}px;max-width:60px;height:4px;background:var(--accent);border-radius:2px;vertical-align:middle;margin-right:8px;opacity:.7"></div>
            <span style="font-weight:600">${pct}%</span>${ci}
          </div>
        </div>`;
    }).join('');

    panel.innerHTML = header + rows;
    host.appendChild(panel);
  });
}

/* small chip helper styles injected once */
(function(){
  if (document.getElementById('bg-chip-styles')) return;
  const s = document.createElement('style');
  s.id = 'bg-chip-styles';
  s.textContent = `
    .bg-chip{display:inline-flex;align-items:center;gap:4px;
      background:var(--panel-2);border:1px solid var(--border);
      border-radius:6px;padding:4px 8px;font-size:12px;font-weight:600;
      color:var(--fg);font-family:inherit}
  `;
  document.head.appendChild(s);
})();

/* ---------- CSV download ---------- */
function downloadCSV(q){
  const src = state.source, split = state.split;
  const rows = BIDX[`${src}|${q}|${split}`] || [];
  if (!rows.length) return;
  const headers = ['source','question','split','rank','next_action','next_action_label','p','baseline_p','lift','lo','hi','n'];
  const lines = [headers.join(',')];
  rows.forEach(r => {
    lines.push([
      r.source, r.question, r.split, r.rank, r.next_action,
      `"${label(r.next_action).replace(/"/g,'""')}"`,
      r.p, r.baseline_p, r.lift == null ? '' : r.lift,
      r.lo, r.hi, r.n,
    ].join(','));
  });
  const blob = new Blob([lines.join('\n')], {type: 'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `transitions_${src}_${q}_${split}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- controller ---------- */
function render(){
  document.querySelectorAll('.view').forEach(v=>v.classList.add('hidden'));
  document.getElementById(`view-${state.view}`).classList.remove('hidden');
  updatePairedBanner(state.source);
  if (state.view === 'bars') updateBarsView();
  else if (state.view === 'heatmap') updateHeatmap();
  else if (state.view === 'multiples') updateSmallMultiples();
  else if (state.view === 'team') updateTeamView();
  else if (state.view === 'hca') updateHcaView();
  else if (state.view === 'bigrams') updateBigramsView();
  writeHash();
}

function buildSourceSelect(){
  const sel = document.getElementById('source-select');
  sel.innerHTML = '';
  const all = new Set(sourcesAvailable('all'));
  for (const cat in SOURCE_CATS){
    const group = document.createElement('optgroup');
    group.label = cat;
    let count = 0;
    SOURCE_CATS[cat].forEach(s => {
      if (!all.has(s)) return;
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = `${s} -- ${label(s)}`;
      group.appendChild(opt);
      count++;
    });
    if (count > 0) sel.appendChild(group);
  }
}

function init(){
  document.getElementById('meta-line').textContent =
    `${BARS.n_events.toLocaleString('en-US')} in-play events across ${BARS.n_games} games, seasons ${BARS.seasons.join(', ')}`;
  const dataBanner = document.getElementById('data-banner');
  if (BARS.seasons.length === 1){
    dataBanner.textContent = `SMOKE DATA: only season ${BARS.seasons[0]} loaded. Full backfill runs separately.`;
  } else {
    dataBanner.textContent = `Full 10-season dataset, ${BARS.seasons[0]}-${BARS.seasons[BARS.seasons.length-1]}. Cluster-bootstrap at the game level (500 resamples).`;
  }

  buildSourceSelect();

  // Load state from URL hash
  const hash = readHash();
  const sources = sourcesAvailable('all');
  state.source = hash.source && sources.includes(hash.source) ? hash.source
               : (sources.includes('2FGM') ? '2FGM' : sources[0]);
  const VALID_SPLITS = ['all','home_acting','away_acting','open_doors','closed_doors',
    'reg_season','playoff','period_1','period_2','period_3','period_4'];
  state.split = VALID_SPLITS.includes(hash.split) ? hash.split : 'all';
  state.view  = ['bars','heatmap','multiples','team','hca','bigrams'].includes(hash.view) ? hash.view : 'bars';
  state.mode  = ['raw','lift'].includes(hash.mode) ? hash.mode : 'raw';

  document.getElementById('source-select').value = state.source;
  document.getElementById('split-select').value = state.split;
  document.querySelectorAll('#view-group .pill').forEach(b => b.classList.toggle('active', b.dataset.view === state.view));
  document.querySelectorAll('#mode-group .pill').forEach(b => b.classList.toggle('active', b.dataset.mode === state.mode));

  document.getElementById('source-select').addEventListener('change', e => {
    state.source = e.target.value; render();
  });
  document.getElementById('split-select').addEventListener('change', e => {
    state.split = e.target.value;
    const avail = sourcesAvailable(state.split);
    if (!avail.includes(state.source)) { state.source = avail[0]; document.getElementById('source-select').value = state.source; }
    render();
  });
  document.querySelectorAll('#mode-group .pill').forEach(btn =>
    btn.addEventListener('click', () => {
      document.querySelectorAll('#mode-group .pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.mode = btn.dataset.mode;
      render();
    })
  );
  document.querySelectorAll('#view-group .pill').forEach(btn =>
    btn.addEventListener('click', () => {
      document.querySelectorAll('#view-group .pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.view = btn.dataset.view;
      render();
    })
  );
  document.querySelectorAll('[data-csv]').forEach(b =>
    b.addEventListener('click', () => downloadCSV(b.dataset.csv))
  );

  window.addEventListener('hashchange', () => {
    const h = readHash();
    if (h.source && h.source !== state.source){ state.source = h.source; document.getElementById('source-select').value = h.source; }
    if (h.split && h.split !== state.split){ state.split = h.split; }
    if (h.view && h.view !== state.view){ state.view = h.view; }
    if (h.mode && h.mode !== state.mode){ state.mode = h.mode; }
    render();
  });

  render();
}
init();
</script>
</body></html>
"""


def main() -> None:
    data = load_data()
    bars_json = data["bars"]
    conc_json = data["concentration"]
    team_rank = data["team_rank"]
    hca = data["hca"]
    bigrams = data["bigrams"]
    plain_labels = bars_json.get("plain_labels", {})
    source_categories = bars_json.get("source_categories", {})
    paired_sources = bars_json.get("paired_sources", {})

    html = (
        HTML_TEMPLATE
        .replace("__BARS__", json.dumps(bars_json, separators=(",", ":")))
        .replace("__CONC__", json.dumps(conc_json, separators=(",", ":")))
        .replace("__PLAIN__", json.dumps(plain_labels, separators=(",", ":")))
        .replace("__SOURCE_CATS__", json.dumps(source_categories, separators=(",", ":")))
        .replace("__PAIRED__", json.dumps(paired_sources, separators=(",", ":")))
        .replace("__TEAM_RANK__", json.dumps(team_rank, separators=(",", ":")))
        .replace("__HCA__", json.dumps(hca, separators=(",", ":")))
        .replace("__BIGRAMS__", json.dumps(bigrams, separators=(",", ":")))
    )

    out = config.DASHBOARDS_DIR / "transitions.html"
    out.write_text(html)
    log.info("wrote %s (%.0f KB)", out, out.stat().st_size / 1024)


if __name__ == "__main__":
    main()
