"""Phase J -- Team & Season Explorer dashboard.

Interactive filtering by team (multi-select) and season (multi-select) with
live KPI + chart updates. All data shipped as inline JSON; aggregation runs
client-side for <100 ms response.
"""
from __future__ import annotations

import json
import logging
import subprocess

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("28_team_explorer_dashboard")

SRC = config.REPORTS_DIR / "team_explorer.json"
OUT = config.DASHBOARDS_DIR / "explorer.html"


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Team &amp; Season Explorer -- EuroLeague HCA</title>
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
  .wrap{max-width:1200px;margin:0 auto;padding:28px 24px 96px}
  h1{font-size:28px;font-weight:700;line-height:1.08;letter-spacing:-0.02em;margin:0 0 6px}
  h1 .lead{color:var(--accent)}
  .sub{color:var(--muted);max-width:880px;margin:0}
  .meta{color:var(--dim);font-size:12px;margin-top:10px}
  .eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
  .back{color:var(--accent);text-decoration:none;font-size:13px;display:inline-block;margin-bottom:10px}
  .back:hover{text-decoration:underline}

  /* FILTER BAR */
  .filterbar{margin:22px 0 8px;padding:16px;background:var(--panel);border:1px solid var(--hair);border-radius:12px;
    display:grid;grid-template-columns:1.7fr 1fr auto;gap:16px;align-items:start}
  @media (max-width:900px){.filterbar{grid-template-columns:1fr}}
  .filter h4{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin:0 0 6px;font-weight:500}
  .chips{display:flex;flex-wrap:wrap;gap:6px;max-height:116px;overflow-y:auto;padding:2px}
  .chip{padding:5px 10px;font-size:12px;font-weight:500;border-radius:14px;background:var(--panel2);
    color:var(--muted);border:1px solid var(--hair);cursor:pointer;transition:all .12s;user-select:none;
    white-space:nowrap}
  .chip:hover{border-color:var(--accent);color:var(--ink)}
  .chip.active{background:var(--accent);color:#0b0d10;border-color:var(--accent);font-weight:600}
  .chip.pos{color:var(--ink)}
  .actions{display:flex;flex-direction:column;gap:6px;align-items:stretch}
  .btn{padding:7px 12px;font-size:12px;font-weight:600;border-radius:6px;background:var(--panel2);
    color:var(--muted);border:1px solid var(--hair);cursor:pointer}
  .btn:hover{border-color:var(--accent);color:var(--ink)}
  .btn.primary{background:var(--accent);color:#0b0d10;border-color:var(--accent)}
  .scope{color:var(--dim);font-size:11px;margin-top:6px;text-align:right}
  .scope strong{color:var(--ink);font-variant-numeric:tabular-nums}

  /* KPI ROW */
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:14px 0}
  .kpi{background:var(--panel);border:1px solid var(--hair);border-radius:10px;padding:13px 14px}
  .kpi .v{font-size:22px;font-weight:700;letter-spacing:-0.02em;line-height:1.1;display:block;font-variant-numeric:tabular-nums}
  .kpi .v.pos{color:var(--pos)} .kpi .v.neu{color:var(--accent)}
  .kpi .v.warn{color:var(--warn)} .kpi .v.neg{color:var(--neg)}
  .kpi .k{color:var(--dim);font-size:11px;margin-top:3px;display:block}
  .kpi .n{color:var(--dim);font-size:10.5px;margin-top:4px;display:block;font-variant-numeric:tabular-nums}

  /* CHART GRID */
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
  @media (max-width:900px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--hair);border-radius:10px;padding:16px}
  .card h3{margin:0 0 8px;font-size:14px;font-weight:600;color:var(--ink);letter-spacing:-0.01em}
  .card p.desc{color:var(--dim);font-size:12px;margin:0 0 8px;line-height:1.45}
  .chart-wrap{position:relative;width:100%;height:260px}
  .chart-wrap.tall{height:340px}

  /* TEAM BREAKDOWN TABLE */
  table.breakdown{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:4px}
  table.breakdown th,table.breakdown td{padding:6px 8px;border-bottom:1px solid var(--hair);text-align:left}
  table.breakdown th{color:var(--dim);font-weight:500;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;position:sticky;top:0;background:var(--panel)}
  table.breakdown td.num{font-variant-numeric:tabular-nums;text-align:right}
  table.breakdown td.team{color:var(--ink);font-weight:500}
  table.breakdown tr:hover{background:var(--panel2)}

  /* EMPTY STATE */
  .empty{padding:40px 20px;text-align:center;color:var(--dim);font-size:13px}
  .empty strong{color:var(--warn)}

  .footer{margin-top:36px;color:var(--dim);font-size:11px;border-top:1px solid var(--hair);padding-top:12px}
  code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;
    background:rgba(255,255,255,.05);padding:1px 5px;border-radius:4px}
</style>
</head>
<body>
<div class="wrap">

  <a class="back" href="index.html">&larr; back to dashboard index</a>
  <div class="eyebrow" style="color:#3ccf8e">
    <span style="display:inline-block;width:8px;height:8px;background:#3ccf8e;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
    Track A &middot; why home wins
  </div>
  <h1>Does home-court advantage live in <span class="lead">certain teams or certain seasons?</span></h1>
  <p class="sub">The league-level +3.88 HCA (Track A) is an average. This tool lets you slice it.
    Pick any combination of teams and seasons -- every KPI and chart below recomputes in the
    browser over the filtered slice. Use it to answer questions the static dashboards can't:
    <em>is a given team's home edge driven by a particular era? Did a specific season swing the league HCA?
    Does the COVID dip appear for every team?</em></p>
  <div class="meta">__N_GAMES__ games &middot; 10 seasons (2015-16 &rarr; 2024-25) &middot;
    36 teams &middot; data: <a href="reports/team_explorer.json" style="color:var(--accent)">team_explorer.json</a></div>

  <!-- FILTER BAR -->
  <div class="filterbar">
    <div class="filter" id="filter-team">
      <h4>Teams (click to toggle; empty = all 36) &middot; <span id="team-count" style="color:var(--accent)">0 selected</span></h4>
      <div class="chips" id="team-chips"></div>
    </div>
    <div class="filter" id="filter-season">
      <h4>Seasons (click to toggle; empty = all 10) &middot; <span id="season-count" style="color:var(--accent)">0 selected</span></h4>
      <div class="chips" id="season-chips"></div>
    </div>
    <div class="actions">
      <button class="btn" id="btn-clear">Clear all</button>
      <button class="btn" id="btn-top8">Top-8 teams</button>
      <button class="btn" id="btn-last3">Last 3 seasons</button>
      <button class="btn" id="btn-covid">COVID slice (2019+2020)</button>
      <div class="scope"><strong id="scope-games">0</strong> games in scope &middot;
        <strong id="scope-teams">36</strong> teams &middot;
        <strong id="scope-seasons">10</strong> seasons</div>
    </div>
  </div>

  <!-- KPI STRIP -->
  <div class="kpis" id="kpi-strip"></div>

  <!-- CHARTS -->
  <div id="main-content">
    <div class="grid">
      <div class="card">
        <h3>HCA per season in the selected slice</h3>
        <p class="desc">Mean home margin per season, restricted to the selected teams. Bars show 0 when no games match in that season.</p>
        <div class="chart-wrap"><canvas id="c-hca-season"></canvas></div>
      </div>
      <div class="card">
        <h3>Home vs away win rate (selected slice)</h3>
        <p class="desc">Share of selected-team games won on home floor vs away floor, across all selected seasons.</p>
        <div class="chart-wrap"><canvas id="c-ha-winp"></canvas></div>
      </div>
      <div class="card">
        <h3>Per-team home and away record</h3>
        <p class="desc">One row per selected team. Sorted by home-margin edge. Scroll if many teams selected.</p>
        <div style="max-height:320px;overflow-y:auto">
          <table class="breakdown" id="tbl-teams">
            <thead><tr>
              <th>Team</th>
              <th class="num">Games</th>
              <th class="num">Home W-L</th>
              <th class="num">Away W-L</th>
              <th class="num">Home margin</th>
              <th class="num">Road margin</th>
              <th class="num">HCA (H-R)</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <h3>Shooting profile: home vs away</h3>
        <p class="desc">Aggregated shooting rates across the selected slice -- eFG%, 3PT%, FT% -- broken out by home and away possessions.</p>
        <div class="chart-wrap"><canvas id="c-shooting"></canvas></div>
      </div>
    </div>
  </div>

  <div class="footer">
    Explorer aggregates are computed client-side from per-(team, season, is_home)
    rows; every rate uses raw sums (not means-of-means) so filter combinations are
    arithmetically correct. Missing-team &times; missing-season cells are treated as
    zero-weight, not zero-rate.
    <br/>Build <code>__SHA__</code>
  </div>
</div>

<script>
const DATA = __JSON__;
const STATE = {teams: new Set(), seasons: new Set()};

// ============================================================================
// FILTER UI
// ============================================================================
function renderTeamChips() {
  const el = document.getElementById('team-chips');
  el.innerHTML = DATA.meta.teams.map(t => {
    const active = STATE.teams.has(t.team_id) ? 'active' : '';
    return `<span class="chip ${active}" data-team="${t.team_id}" title="${t.name} (${t.n_games} games)">${t.team_id}</span>`;
  }).join('');
  document.getElementById('team-count').textContent = STATE.teams.size ? `${STATE.teams.size} selected` : 'all 36';
}
function renderSeasonChips() {
  const el = document.getElementById('season-chips');
  el.innerHTML = DATA.meta.seasons.map(s => {
    const active = STATE.seasons.has(s) ? 'active' : '';
    return `<span class="chip ${active}" data-season="${s}">${s}-${String(s+1).slice(2)}</span>`;
  }).join('');
  document.getElementById('season-count').textContent = STATE.seasons.size ? `${STATE.seasons.size} selected` : 'all 10';
}
document.getElementById('team-chips').addEventListener('click', (e) => {
  const c = e.target.closest('.chip'); if (!c) return;
  const t = c.dataset.team;
  STATE.teams.has(t) ? STATE.teams.delete(t) : STATE.teams.add(t);
  renderTeamChips(); update();
});
document.getElementById('season-chips').addEventListener('click', (e) => {
  const c = e.target.closest('.chip'); if (!c) return;
  const s = parseInt(c.dataset.season);
  STATE.seasons.has(s) ? STATE.seasons.delete(s) : STATE.seasons.add(s);
  renderSeasonChips(); update();
});
document.getElementById('btn-clear').addEventListener('click', () => {
  STATE.teams.clear(); STATE.seasons.clear();
  renderTeamChips(); renderSeasonChips(); update();
});
document.getElementById('btn-top8').addEventListener('click', () => {
  STATE.teams = new Set(DATA.meta.teams.slice(0, 8).map(t => t.team_id));
  renderTeamChips(); update();
});
document.getElementById('btn-last3').addEventListener('click', () => {
  STATE.seasons = new Set(DATA.meta.seasons.slice(-3));
  renderSeasonChips(); update();
});
document.getElementById('btn-covid').addEventListener('click', () => {
  STATE.seasons = new Set([2019, 2020]);
  renderSeasonChips(); update();
});

// ============================================================================
// FILTER + AGGREGATE
// ============================================================================
function filteredRows() {
  const teamsSet = STATE.teams.size ? STATE.teams : null;
  const seasonsSet = STATE.seasons.size ? STATE.seasons : null;
  return DATA.team_season.filter(r =>
    (!teamsSet || teamsSet.has(r.team_id)) &&
    (!seasonsSet || seasonsSet.has(r.season))
  );
}

function aggregate(rows) {
  // Sum across all rows; pts/opp_pts/n are additive.
  const sum = (k) => rows.reduce((a,r)=>a+(r[k]||0), 0);
  const n_home = rows.filter(r=>r.is_home===1).reduce((a,r)=>a+r.n, 0);
  const n_away = rows.filter(r=>r.is_home===0).reduce((a,r)=>a+r.n, 0);
  const wins_home = rows.filter(r=>r.is_home===1).reduce((a,r)=>a+r.wins, 0);
  const wins_away = rows.filter(r=>r.is_home===0).reduce((a,r)=>a+r.wins, 0);
  const pts_h = rows.filter(r=>r.is_home===1).reduce((a,r)=>a+r.pts, 0);
  const pts_a = rows.filter(r=>r.is_home===0).reduce((a,r)=>a+r.pts, 0);
  const opp_h = rows.filter(r=>r.is_home===1).reduce((a,r)=>a+r.opp_pts, 0);
  const opp_a = rows.filter(r=>r.is_home===0).reduce((a,r)=>a+r.opp_pts, 0);
  const fgm_h = sumWhere(rows,r=>r.is_home===1,'fgm'), fga_h = sumWhere(rows,r=>r.is_home===1,'fga');
  const fgm_a = sumWhere(rows,r=>r.is_home===0,'fgm'), fga_a = sumWhere(rows,r=>r.is_home===0,'fga');
  const fgm3_h = sumWhere(rows,r=>r.is_home===1,'fgm3'), fga3_h = sumWhere(rows,r=>r.is_home===1,'fga3');
  const fgm3_a = sumWhere(rows,r=>r.is_home===0,'fgm3'), fga3_a = sumWhere(rows,r=>r.is_home===0,'fga3');
  const ftm_h = sumWhere(rows,r=>r.is_home===1,'ftm'), fta_h = sumWhere(rows,r=>r.is_home===1,'fta');
  const ftm_a = sumWhere(rows,r=>r.is_home===0,'ftm'), fta_a = sumWhere(rows,r=>r.is_home===0,'fta');
  // eFG% = (FGM + 0.5 * FGM3) / FGA
  const efg = (fgm, fgm3, fga) => fga ? ((fgm + 0.5*fgm3) / fga) : 0;
  return {
    n_home, n_away, n_total: n_home+n_away,
    home_win_p: n_home ? wins_home/n_home : 0,
    away_win_p: n_away ? wins_away/n_away : 0,
    margin_home: n_home ? (pts_h - opp_h)/n_home : 0,
    margin_away: n_away ? (pts_a - opp_a)/n_away : 0,
    pts_home_mean: n_home ? pts_h/n_home : 0,
    pts_away_mean: n_away ? pts_a/n_away : 0,
    efg_home: efg(fgm_h, fgm3_h, fga_h),
    efg_away: efg(fgm_a, fgm3_a, fga_a),
    fg3_home: fga3_h ? fgm3_h/fga3_h : 0,
    fg3_away: fga3_a ? fgm3_a/fga3_a : 0,
    ft_home: fta_h ? ftm_h/fta_h : 0,
    ft_away: fta_a ? ftm_a/fta_a : 0,
  };
}
function sumWhere(rows, pred, key) { return rows.filter(pred).reduce((a,r)=>a+(r[key]||0), 0); }

function perSeasonAgg(rows) {
  const by = {};
  for (const r of rows) {
    by[r.season] = by[r.season] || {n_home:0,n_away:0,pt_diff_home:0,pt_diff_away:0};
    const bucket = by[r.season];
    if (r.is_home === 1) {
      bucket.n_home += r.n;
      bucket.pt_diff_home += (r.pts - r.opp_pts);
    } else {
      bucket.n_away += r.n;
      bucket.pt_diff_away += (r.pts - r.opp_pts);
    }
  }
  return DATA.meta.seasons.map(s => {
    const b = by[s];
    return {
      season: s,
      n: b ? b.n_home + b.n_away : 0,
      margin_home: b && b.n_home ? b.pt_diff_home / b.n_home : null,
      margin_away: b && b.n_away ? b.pt_diff_away / b.n_away : null,
    };
  });
}

function perTeamAgg(rows) {
  const by = {};
  for (const r of rows) {
    by[r.team_id] = by[r.team_id] || {n_home:0,n_away:0,w_home:0,w_away:0,diff_home:0,diff_away:0};
    const b = by[r.team_id];
    if (r.is_home === 1) {
      b.n_home += r.n; b.w_home += r.wins; b.diff_home += (r.pts - r.opp_pts);
    } else {
      b.n_away += r.n; b.w_away += r.wins; b.diff_away += (r.pts - r.opp_pts);
    }
  }
  const out = Object.entries(by).map(([tid, b]) => ({
    team_id: tid,
    n: b.n_home + b.n_away,
    w_home: b.w_home, l_home: b.n_home - b.w_home,
    w_away: b.w_away, l_away: b.n_away - b.w_away,
    margin_home: b.n_home ? b.diff_home / b.n_home : 0,
    margin_away: b.n_away ? b.diff_away / b.n_away : 0,
  }));
  out.forEach(o => o.hca = o.margin_home - o.margin_away);
  out.sort((a,b) => b.hca - a.hca);
  return out;
}

// ============================================================================
// CHARTS
// ============================================================================
let charts = {};
const COLORS = {pos:'rgba(60,207,142,0.85)', neg:'rgba(239,90,90,0.85)',
  neu:'rgba(110,176,255,0.85)', warn:'rgba(245,183,58,0.85)', dim:'rgba(122,133,149,0.6)'};

Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";
Chart.defaults.color = '#b6bfcc';

function baseOpts(yLabel, extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {legend: {display: extra.legend !== false, position: 'bottom',
      labels: {color: '#b6bfcc', font: {size: 11}, boxWidth: 10}}},
    scales: {
      y: {grid: {color: 'rgba(255,255,255,0.05)'}, ticks: {color: '#7a8595'},
          title: {display: !!yLabel, text: yLabel, color: '#b6bfcc'}},
      x: {grid: {display: false}, ticks: {color: '#b6bfcc'}},
    },
    ...extra.rest,
  };
}

function upsertChart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id).getContext('2d'), cfg);
}

function fmtPct(p) { return p == null ? '--' : (p * 100).toFixed(1) + '%'; }
function fmtSigned(v, digits=2) { return v == null ? '--' : (v >= 0 ? '+' : '') + v.toFixed(digits); }

// ============================================================================
// UPDATE
// ============================================================================
function update() {
  const rows = filteredRows();

  // Scope readout
  const agg = aggregate(rows);
  document.getElementById('scope-games').textContent = agg.n_total.toLocaleString('en-US');
  document.getElementById('scope-teams').textContent =
    STATE.teams.size || 36;
  document.getElementById('scope-seasons').textContent =
    STATE.seasons.size || 10;

  // Empty state
  const mainEl = document.getElementById('main-content');
  const kpiEl = document.getElementById('kpi-strip');
  if (agg.n_total === 0) {
    kpiEl.innerHTML = '';
    mainEl.innerHTML = '<div class="empty"><strong>No games match.</strong><br/>This can happen if the selected teams never played in the selected seasons (e.g. Khimki in 2022-24). Try clearing filters or choosing a different combination.</div>';
    return;
  }
  // Rebuild main-content if it was cleared
  if (!document.getElementById('c-hca-season')) {
    mainEl.innerHTML = `
      <div class="grid">
        <div class="card"><h3>HCA per season in the selected slice</h3><p class="desc">Mean home margin per season, restricted to the selected teams.</p><div class="chart-wrap"><canvas id="c-hca-season"></canvas></div></div>
        <div class="card"><h3>Home vs away win rate</h3><p class="desc">Share of selected-team games won at home vs on the road.</p><div class="chart-wrap"><canvas id="c-ha-winp"></canvas></div></div>
        <div class="card"><h3>Per-team home and away record</h3><p class="desc">One row per selected team. Sorted by HCA.</p><div style="max-height:320px;overflow-y:auto"><table class="breakdown" id="tbl-teams"><thead><tr><th>Team</th><th class="num">Games</th><th class="num">Home W-L</th><th class="num">Away W-L</th><th class="num">Home margin</th><th class="num">Road margin</th><th class="num">HCA (H-R)</th></tr></thead><tbody></tbody></table></div></div>
        <div class="card"><h3>Shooting profile: home vs away</h3><p class="desc">eFG%, 3PT%, FT% aggregated across the slice.</p><div class="chart-wrap"><canvas id="c-shooting"></canvas></div></div>
      </div>`;
  }

  // KPIs
  kpiEl.innerHTML = `
    <div class="kpi"><span class="v neu">${agg.n_total.toLocaleString('en-US')}</span><span class="k">games in selection</span><span class="n">${agg.n_home} home / ${agg.n_away} away</span></div>
    <div class="kpi"><span class="v pos">${fmtSigned(agg.margin_home - agg.margin_away)}</span><span class="k">HCA (pts, home margin − away margin)</span><span class="n">from raw sums</span></div>
    <div class="kpi"><span class="v pos">${fmtPct(agg.home_win_p)}</span><span class="k">Home win rate</span><span class="n">${Math.round(agg.home_win_p*agg.n_home)}-${agg.n_home - Math.round(agg.home_win_p*agg.n_home)}</span></div>
    <div class="kpi"><span class="v neg">${fmtPct(agg.away_win_p)}</span><span class="k">Road win rate</span><span class="n">${Math.round(agg.away_win_p*agg.n_away)}-${agg.n_away - Math.round(agg.away_win_p*agg.n_away)}</span></div>
    <div class="kpi"><span class="v warn">${fmtSigned(agg.pts_home_mean - agg.pts_away_mean)}</span><span class="k">Scoring gap (H − A pts/g)</span><span class="n">${agg.pts_home_mean.toFixed(1)} vs ${agg.pts_away_mean.toFixed(1)}</span></div>
  `;

  // HCA per season chart
  const ps = perSeasonAgg(rows);
  const leagueBaseline = DATA.per_season_league.map(r => r.mean_home_margin);
  upsertChart('c-hca-season', {
    type:'bar',
    data:{
      labels: ps.map(r => `${r.season}-${String(r.season+1).slice(2)}`),
      datasets:[
        {label:'Selected slice -- home margin', data: ps.map(r => r.margin_home), backgroundColor: COLORS.pos, borderRadius:4},
        {label:'Selected slice -- away margin', data: ps.map(r => r.margin_away), backgroundColor: COLORS.neg, borderRadius:4},
        {label:'League baseline (all teams)', type:'line', data: leagueBaseline, borderColor: COLORS.neu,
         backgroundColor:'transparent', borderWidth:2, borderDash:[5,5], pointRadius:3, pointBackgroundColor:COLORS.neu},
      ],
    },
    options: {...baseOpts('Mean margin (pts/game)')},
  });

  // Home/away win rate chart
  upsertChart('c-ha-winp', {
    type:'bar',
    data:{labels:['Home games', 'Away games'], datasets:[{
      label:'Win %', data:[agg.home_win_p*100, agg.away_win_p*100],
      backgroundColor:[COLORS.pos, COLORS.neg], borderRadius:4,
    }]},
    options:{...baseOpts('Win %', {legend:false,
      rest:{scales:{y:{min:0,max:100,ticks:{callback:(v)=>v+'%'},title:{display:true, text:'Win %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
                    x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}}}})},
  });

  // Per-team table
  const pt = perTeamAgg(rows);
  const tbody = document.querySelector('#tbl-teams tbody');
  tbody.innerHTML = pt.map(r => `<tr>
    <td class="team">${r.team_id}</td>
    <td class="num">${r.n}</td>
    <td class="num">${r.w_home}-${r.l_home}</td>
    <td class="num">${r.w_away}-${r.l_away}</td>
    <td class="num" style="color:${r.margin_home>=0?'var(--pos)':'var(--neg)'}">${fmtSigned(r.margin_home)}</td>
    <td class="num" style="color:${r.margin_away>=0?'var(--pos)':'var(--neg)'}">${fmtSigned(r.margin_away)}</td>
    <td class="num" style="color:var(--warn);font-weight:600">${fmtSigned(r.hca)}</td>
  </tr>`).join('');

  // Shooting profile
  upsertChart('c-shooting', {
    type:'bar',
    data:{
      labels:['eFG%', '3PT%', 'FT%'],
      datasets:[
        {label:'Home', data:[agg.efg_home*100, agg.fg3_home*100, agg.ft_home*100], backgroundColor: COLORS.pos, borderRadius:4},
        {label:'Away', data:[agg.efg_away*100, agg.fg3_away*100, agg.ft_away*100], backgroundColor: COLORS.neg, borderRadius:4},
      ],
    },
    options:{...baseOpts('Rate (%)', {rest:{scales:{y:{ticks:{callback:(v)=>v+'%'}, title:{display:true, text:'Rate (%)', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
                                                    x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}}}})},
  });
}

renderTeamChips();
renderSeasonChips();
update();
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
    html = (HTML
            .replace("__JSON__", json.dumps(data))
            .replace("__N_GAMES__", f"{data['meta']['n_games']:,}")
            .replace("__SHA__", _git_sha()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    log.info("wrote %s (%.1f KB)", OUT, OUT.stat().st_size / 1024)


if __name__ == "__main__":
    main()
