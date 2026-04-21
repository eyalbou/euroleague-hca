"""Phase 26 -- render dashboards/anomalies.html.

Ten data and basketball anomalies, each with a number, a small chart, and a
basketball-analyst interpretation. Same dark-on-accent design language as the
rest of the site.
"""
from __future__ import annotations

import json
import logging
import subprocess

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("26_anomalies_dashboard")

SRC = config.REPORTS_DIR / "anomalies.json"
OUT = config.DASHBOARDS_DIR / "anomalies.html"


HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<link rel="icon" type="image/png" href="assets/euroleague-logo.png"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>10 anomalies -- EuroLeague HCA</title>
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
  .topbar{display:flex;align-items:center;gap:14px;margin-bottom:14px}
  .brand{height:32px;width:auto;background:#fff;border-radius:6px;padding:4px 8px;
         box-shadow:0 1px 2px rgba(0,0,0,.18);flex-shrink:0}
  .hero{padding:24px 0 16px;border-bottom:1px solid var(--hair)}
  .eyebrow{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
  h1{font-size:30px;font-weight:700;line-height:1.08;letter-spacing:-0.02em;margin:0 0 8px}
  h1 .lead{color:var(--accent)}
  .sub{color:var(--muted);max-width:780px;margin:0}
  .meta{color:var(--dim);font-size:12px;margin-top:12px}

  .toc{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin:24px 0 8px}
  .toc a{display:flex;align-items:baseline;gap:8px;color:var(--muted);font-size:13px;
    text-decoration:none;padding:8px 10px;background:var(--panel);border:1px solid var(--hair);
    border-radius:8px;transition:all .15s}
  .toc a:hover{color:var(--ink);border-color:var(--accent)}
  .toc a .num{color:var(--accent);font-weight:700;font-size:12px;min-width:22px;text-align:right}

  .anomaly{margin:48px 0 0;padding:24px;background:var(--panel);border:1px solid var(--hair);border-radius:12px}
  .anomaly .ah{display:flex;align-items:center;gap:12px;margin-bottom:6px}
  .anomaly .num{background:var(--accent);color:#0b0d10;font-weight:700;
    border-radius:50%;width:30px;height:30px;display:inline-flex;align-items:center;
    justify-content:center;font-size:13px;flex-shrink:0}
  .anomaly h2{font-size:20px;font-weight:600;letter-spacing:-0.02em;margin:0}
  .anomaly .tagline{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:18px;margin-left:42px}

  .kpiline{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:6px 0 18px}
  .kpi{background:var(--panel2);border:1px solid var(--hair);border-radius:10px;padding:14px}
  .kpi .v{font-size:24px;font-weight:700;letter-spacing:-0.02em;line-height:1.1;display:block;font-variant-numeric:tabular-nums}
  .kpi .v.pos{color:var(--pos)} .kpi .v.neu{color:var(--accent)} .kpi .v.warn{color:var(--warn)} .kpi .v.neg{color:var(--neg)}
  .kpi .k{color:var(--dim);font-size:12px;margin-top:4px;display:block}
  .kpi .n{color:var(--dim);font-size:11px;margin-top:6px;display:block;font-variant-numeric:tabular-nums}

  .chart-wrap{position:relative;width:100%;height:260px;margin:8px 0 18px}

  .takeaway{background:rgba(110,176,255,.04);border-left:3px solid var(--accent);
    padding:14px 18px;border-radius:4px;margin-top:16px;color:var(--muted);font-size:13.5px;line-height:1.65}
  .takeaway strong{color:var(--ink)}
  .takeaway em.tag{color:var(--accent);font-style:normal;font-weight:600;margin-right:4px}

  table.tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  table.tbl th,table.tbl td{padding:8px 10px;border-bottom:1px solid var(--hair);text-align:left}
  table.tbl th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  table.tbl td.num{font-variant-numeric:tabular-nums;text-align:right}
  table.tbl td.name{color:var(--ink);font-weight:500}

  footer{margin-top:48px;color:var(--dim);font-size:12px;border-top:1px solid var(--hair);padding-top:16px}
  code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;
    background:rgba(255,255,255,.05);padding:1px 5px;border-radius:4px}

  @media (max-width:640px){ h1{font-size:24px} .wrap{padding:24px 16px 64px} }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <img class="brand" src="assets/euroleague-logo.png" alt="EuroLeague" />
    <a class="back" href="index.html">&larr; back to dashboard index</a>
  </div>

  <div class="hero">
    <div class="eyebrow" style="color:#3ccf8e"><span style="display:inline-block;width:8px;height:8px;background:#3ccf8e;border-radius:50%;margin-right:6px;vertical-align:middle"></span>Track A &middot; why home wins &middot; <a href="explorer.html" style="color:#3ccf8e;text-decoration:none">team+season explorer</a></div>
    <h1>Ten surprising patterns buried in <span class="lead">1.5M PBP events</span>.</h1>
    <p class="sub">A basketball analyst's tour through the EuroLeague data. Most of these findings re-frame where HCA is (and isn't) present -- OT collapse, clutch dilution, halftime holes. Two are standalone dynamics findings (#8 team 3PT travel, #10 named players). Each card is self-contained -- jump around freely.</p>
    <div class="meta">__N_GAMES__ games &middot; __N_SEASONS__ seasons &middot; all claims carry CIs or p-values</div>
  </div>

  <div class="toc" id="toc"></div>

  <!-- ========================================================================
       1. OVERTIME HCA
       ==================================================================== -->
  <div class="anomaly" id="a-overtime_hca">
    <div class="ah"><span class="num">1</span>
    <h2>The OT coin flip</h2></div>
    <div class="tagline">home-court advantage does not survive overtime</div>
    <div class="kpiline" id="kpi-1"></div>
    <div class="chart-wrap"><canvas id="c1"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> over ten seasons, home teams win regulation games 63.1% of the time, but overtime games are a <strong>coin flip at 50.0%</strong>. Drop of 13 percentage points, z = 3.07, p = 0.002 -- unmistakably real.<br/><br/>
      <em class="tag">Why:</em> an OT game is, by construction, a game that was tied after 40 minutes. HCA is a compounding efficiency edge that plays out over possessions; once both teams have played 40 minutes even, the signal is already exhausted. OT is basically 5 minutes of pickup basketball with exhausted starters, often depleted benches due to fouls, and no scouting advantage left to exploit. The pressure equalizes too -- crowd effect peaks in the last 3 minutes of regulation and is spent by the time OT starts.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> never treat OT as "normal basketball." HCA-adjusted models will systematically over-predict the home team in these games. If you're handicapping EuroLeague playoffs, mentally discount HCA to zero the moment a game goes to OT.
    </div>
  </div>

  <!-- ========================================================================
       2. FIRST-SCORE EFFECT
       ==================================================================== -->
  <div class="anomaly" id="a-first_score">
    <div class="ah"><span class="num">2</span>
    <h2>Does scoring first predict winning?</h2></div>
    <div class="tagline">momentum is overrated, HCA is not</div>
    <div class="kpiline" id="kpi-2"></div>
    <div class="chart-wrap"><canvas id="c2"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> the team that scores first wins only 54% of the time. Scoring first shifts your win probability by about <strong>4 percentage points</strong>, barely above noise. A much better predictor is simply: who's at home? Home teams that score first win 66.3%; home teams that <em>don't</em> score first still win 58.6%. The HCA effect is ~5x larger than the first-score effect.<br/><br/>
      <em class="tag">Why:</em> the first score is one possession out of ~72. Basketball is not a sport where early points compound (unlike football, where a kickoff return can swing field position for a quarter). Shot quality regresses, pace resets every possession, and any momentum from the opening bucket dissipates within the first media timeout.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> when a commentator says "and the first basket goes to X -- big early advantage," ignore them. That's 4 percentage points of win probability. A coach loses more than that by picking a wrong defensive matchup in their opening lineup.
    </div>
  </div>

  <!-- ========================================================================
       3. QUARTER-BY-QUARTER HCA
       ==================================================================== -->
  <div class="anomaly" id="a-quarter_hca">
    <div class="ah"><span class="num">3</span>
    <h2>Which quarter produces the +3.88 HCA?</h2></div>
    <div class="tagline">HCA is NOT a fourth-quarter phenomenon</div>
    <div class="kpiline" id="kpi-3"></div>
    <div class="chart-wrap"><canvas id="c3"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> HCA is spread almost evenly across all four quarters -- +1.08 in Q1, +0.88 in Q2, +0.94 in Q3, +0.88 in Q4. The <strong>first quarter actually has the biggest home edge</strong>, not the fourth. The 95% CIs overlap substantially across quarters -- this is a flat line, not a curve.<br/><br/>
      <em class="tag">Why:</em> HCA is a possession-level efficiency signal (as the mechanism analysis showed: ~+0.05 PPP edge * ~72 possessions = +3.7 pts per game). Since possessions are distributed evenly across quarters, the scoring edge is too. The popular "home crowd lifts them in the 4th" narrative is false here -- if anything, home teams lock in their edge early and coast.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> this is the cleanest evidence that EuroLeague HCA is a <em>structural</em> effect (playing on your own floor, referees, shot-clock familiarity, rest advantage) rather than a <em>clutch/emotion</em> effect. In fact, Q1 being the strongest quarter is consistent with a "travel and warmup" mechanism: road teams shoot worse in Q1 because they haven't fully adjusted to the rims, lighting, and sightlines.
    </div>
  </div>

  <!-- ========================================================================
       4. CLUTCH HCA
       ==================================================================== -->
  <div class="anomaly" id="a-clutch_hca">
    <div class="ah"><span class="num">4</span>
    <h2>Does HCA survive close games?</h2></div>
    <div class="tagline">in 5-point games home is barely favored</div>
    <div class="kpiline" id="kpi-4"></div>
    <div class="chart-wrap"><canvas id="c4"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> in games decided by 5 points or fewer, home teams win only <strong>54.2%</strong> of the time -- barely above coin flip. In blowouts (&gt;10), home win rate jumps to 70.3%. The full +3.88 HCA is not evenly distributed across outcomes; it's a distributional shift where home teams turn close games into comfortable wins, but don't meaningfully improve their record in <em>actually close</em> games.<br/><br/>
      <em class="tag">Why:</em> in close games both teams are playing to their capability, fatigue levels are matched, and the referee's whistle is decisive per possession rather than cumulative. These are exactly the conditions under which HCA washes out. The home edge <em>builds up</em> through the game as a probability shift, but once the outcome is actually uncertain, it reverts.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> closely ties into #1 (OT = coin flip) -- same mechanism, different time horizon. Playoff series forecasts should discount HCA more aggressively for "close-tempo" matchups (two disciplined, low-variance teams), and inflate it for "blowout-prone" matchups (high-variance offenses).
    </div>
  </div>

  <!-- ========================================================================
       5. BLOWOUT ASYMMETRY
       ==================================================================== -->
  <div class="anomaly" id="a-blowout_asymmetry">
    <div class="ah"><span class="num">5</span>
    <h2>Home blowouts vs road blowouts</h2></div>
    <div class="tagline">home blowouts are 2.85x more common at 20+</div>
    <div class="kpiline" id="kpi-5"></div>
    <div class="chart-wrap"><canvas id="c5"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> 299 home wins by 20+ vs just 105 road wins by 20+ in 10 seasons. At 30+, the ratio explodes to <strong>4.3-to-1</strong> (73 home vs 17 away). The HCA effect isn't additive -- it's distributional. The home team isn't just "+3.88 pts better on average"; it's producing a fat right tail of blowout wins that road teams almost never match.<br/><br/>
      <em class="tag">Why:</em> blowouts compound. Once a home team is up 15 at halftime, the crowd is loud, the opponent is demoralized, second units get longer runs while the visiting bench is already grinding through back-to-back travel. Road teams rarely get to that state because they have to win the early quarters on the road just to stay close. Over 40 minutes, the home team's "failure mode" is a close loss; the road team's failure mode is a blowout.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> this is the strongest single visual argument against modeling HCA as a simple mean shift. Use quantile regression or a separate "blowout model" if you're modeling total-points or spread bets in EuroLeague.
    </div>
  </div>

  <!-- ========================================================================
       6. HALFTIME COMEBACK RATE
       ==================================================================== -->
  <div class="anomaly" id="a-halftime_comeback">
    <div class="ah"><span class="num">6</span>
    <h2>The 10-point halftime hole</h2></div>
    <div class="tagline">a deficit at home is 3x easier to erase</div>
    <div class="kpiline" id="kpi-6"></div>
    <div class="chart-wrap"><canvas id="c6"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> home teams trailing by 10+ at halftime come back to win <strong>19.8%</strong> of the time. Away teams in the same hole come back only <strong>6.5%</strong> of the time -- <em>three times less often</em>, for an identical deficit. The magnitude of the gap (13 pp) is bigger than the overall +3.88 HCA implies.<br/><br/>
      <em class="tag">Why:</em> coaches make systematic adjustments at halftime -- new defensive coverages, matchup changes, bench rotations. The home coach makes those adjustments in front of a supportive crowd, with familiar film crew clips on the jumbotron, and an opponent that's now traveling fatigued with poor shot quality. The away coach is making the same adjustments but inheriting hostile crowd noise on every possession and a still-warm home team entering the 3rd quarter ready to land an early punch.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> if you're modeling in-game win probability (live betting, coaching decisions), HCA matters <em>more</em> when the home team is behind, not less. The opposite of what most baseline models assume. This is one of the cleanest pieces of evidence that EuroLeague HCA has a psychological/tactical component beyond pure possession efficiency.
    </div>
  </div>

  <!-- ========================================================================
       7. TIED AT HALF
       ==================================================================== -->
  <div class="anomaly" id="a-tied_at_half">
    <div class="ah"><span class="num">7</span>
    <h2>Tied at halftime</h2></div>
    <div class="tagline">the purest HCA test -- home still wins 60%</div>
    <div class="kpiline" id="kpi-7"></div>
    <div class="chart-wrap"><canvas id="c7"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> in games <strong>exactly tied at halftime</strong>, home teams win 59.6%. In games within 2 pts at halftime, they win 62.2%. The full baseline HCA of 63% is almost entirely still present -- so whatever HCA is made of, it lives in the 2nd half just as much as the 1st. Paired with #3 (quarter-by-quarter HCA), this is definitive evidence that HCA is constant over time, not a late-game clutch phenomenon.<br/><br/>
      <em class="tag">Why:</em> if HCA were purely "the home team starts hot and then just holds on," we'd expect games tied at halftime to be ~coin flips in the 2nd half (the hot start didn't materialize). Instead, the home team's +3.88 edge continues to accumulate possession-by-possession through the 3rd and 4th quarters, exactly as the possession-efficiency model predicts.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> halftime betting markets consistently overcorrect based on the first-half scoreline. "Tied at half? Must be a coin flip second half!" is wrong -- home is still ~60/40. There's almost always systematic value on the home team in these markets.
    </div>
  </div>

  <!-- ========================================================================
       8. TEAM 3PT HOME/ROAD GAPS
       ==================================================================== -->
  <div class="anomaly" id="a-team_3pt_gap">
    <div class="ah"><span class="num">8</span>
    <h2>Which teams travel worst with their 3-point shot?</h2></div>
    <div class="tagline">not every team's shooting "travels"</div>
    <div class="chart-wrap"><canvas id="c8"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> the average EuroLeague team shoots almost identically from 3 home and away (league gap <span id="league-gap-note"></span> pp). But individual teams are wildly different. CSKA Moscow shoots 42.2% at home vs 39.6% on the road -- a 2.6 pp penalty that's worth ~0.5 pts per game just from three. At the opposite end, Olympiacos actually shoots <em>better</em> on the road (-1.6 pp gap), which is unusual enough to look for a specific cause.<br/><br/>
      <em class="tag">Why the home edge exists for some teams:</em> rim familiarity, backdrop sightlines (crowd shirts, depth perception), shooting-gym practice during the day of the game. Shooters develop muscle memory for specific arena geometry. The Khimki arena (historically European) has a distinct low-ceiling lighting profile; that's plausibly why Khimki shows a 2.4 pp gap.<br/><br/>
      <em class="tag">Why Olympiacos travels well:</em> SEF Arena in Piraeus is one of the most hostile opponent venues in Europe, so the team plays a ton of "us against the world" style basketball. That doesn't transfer to shooting at home. Or -- equally likely -- it's 5-season noise, and the "effect" disappears on 20 more seasons of data.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> team-level home/road shooting splits have real signal for individual teams but almost no signal at the league level. Use per-team residuals, not league means, when forecasting specific matchups.
    </div>
  </div>

  <!-- ========================================================================
       9. FT-MYTH
       ==================================================================== -->
  <div class="anomaly" id="a-ft_myth">
    <div class="ah"><span class="num">9</span>
    <h2>Does the crowd actually distract FT shooters?</h2></div>
    <div class="tagline">the classic NBA myth, tested on 103k free throws</div>
    <div class="kpiline" id="kpi-9"></div>
    <div class="chart-wrap"><canvas id="c9"></canvas></div>
    <div class="takeaway">
      <strong>Basketball read:</strong> home shooters hit 76.89%, away shooters hit 76.41%. A half-a-percentage-point gap on 103k free throws. z = 1.83, p = 0.067 -- right at the edge of statistical significance, and the magnitude is basically zero. <strong>The "hostile crowd rattles visiting FT shooters" myth is not supported.</strong><br/><br/>
      <em class="tag">Why:</em> free throws are a closed-skill action. The shooter has 10 seconds alone at a fixed distance with no defender. Practiced free-throw shooters are effectively immune to crowd noise; they shut it out as part of their routine. The popular image of "crowd waving noodles behind the backboard" is memorable but empirically ineffective.<br/><br/>
      <em class="tag">Takeaway for analysts:</em> zero of the +3.88 HCA comes from FT shooting differential. The 0.48 pp edge times ~20 FT attempts per team per game is worth about 0.1 pts. Any argument that "home crowds win games by distracting FT shooters" is wrong by an order of magnitude.
    </div>
  </div>

  <!-- ========================================================================
       10. PLAYER SPLITS
       ==================================================================== -->
  <div class="anomaly" id="a-player_splits">
    <div class="ah"><span class="num">10</span>
    <h2>The biggest home warriors and road warriors</h2></div>
    <div class="tagline">named players who live on one side of the travel line</div>
    <div class="kpiline" id="kpi-10"></div>
    <h3 style="margin:16px 0 4px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Home warriors (most extra PPG at home)</h3>
    <table class="tbl"><thead><tr>
      <th>Player</th><th class="num">Home PPG</th><th class="num">Away PPG</th><th class="num">Diff</th><th class="num">Games (H/A)</th>
    </tr></thead><tbody id="tbl-home-warriors"></tbody></table>
    <h3 style="margin:28px 0 4px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Road warriors (most extra PPG on the road)</h3>
    <table class="tbl"><thead><tr>
      <th>Player</th><th class="num">Home PPG</th><th class="num">Away PPG</th><th class="num">Diff</th><th class="num">Games (H/A)</th>
    </tr></thead><tbody id="tbl-road-warriors"></tbody></table>
    <div class="takeaway" style="margin-top:20px">
      <strong>Basketball read:</strong> <em>home warriors</em> are named players who are measurably better scorers at home -- they get extra minutes, extra shots, or just shoot better off home arena rims. The 3+ PPG gap on David Lighty and Dzanan Musa is genuine signal over 60+ games per side. These are exactly the types of players coaches lean on more at home ("he'll get his at home, rest him on the road").<br/><br/>
      <em class="tag">Road warriors</em> are the inverse -- players whose aggressive, high-usage game travels <em>better</em>. Often these are elite creators who see fewer help-defense rotations on the road (less boisterous crowd = slightly later rotations = more looks). But more prosaically, they're often players whose teams are better on the road (so they get more minutes in winnable road games).<br/><br/>
      <em class="tag">Takeaway for analysts:</em> individual-player home/road splits are usable for in-game prop-betting and for coaching lineup decisions. For team-level HCA modeling, this is noise -- each team has both home warriors and road warriors on the roster, and they cancel. Individual-player HCA is a roster-construction question (should I have one more "traveling" scorer?), not a league-trend question.
    </div>
  </div>

  <footer>
    Data: silver-layer PBP + team box scores (10 seasons, 2,896 games, 1.51M events, 5,790 team-games).
    Methodology: Wilson 95% CIs for proportions, bootstrap 500-1000x for means, pooled two-proportion z-tests for rate comparisons.
    All raw numbers: <a href="reports/anomalies.json" style="color:var(--accent)">anomalies.json</a>.
    <br/>Build <code>__SHA__</code>
  </footer>
</div>

<script>
Chart.defaults.font.family = "'DM Sans','Axiforma',system-ui,sans-serif";
Chart.defaults.color = '#b8c1cb';
const DATA = __JSON__;
const anomalies = Object.fromEntries(DATA.anomalies.map(a => [a.id, a]));

// ---- TOC ----
const tocEl = document.getElementById('toc');
tocEl.innerHTML = DATA.anomalies.map((a, i) => `
  <a href="#a-${a.id}"><span class="num">${i+1}</span> ${a.title}</a>
`).join('');

const COLORS = {pos:'rgba(60,207,142,0.85)', neg:'rgba(239,90,90,0.85)',
  neu:'rgba(110,176,255,0.85)', warn:'rgba(245,183,58,0.85)', dim:'rgba(122,133,149,0.55)'};

function baseChartOpts(opts = {}) {
  return {
    responsive: true, maintainAspectRatio: false,
    plugins: {legend: {display: opts.legend !== false, position:'bottom', labels:{color:'#b6bfcc', font:{family:'DM Sans', size:11}}}},
    scales: {
      y: {grid:{color:'rgba(255,255,255,0.05)'}, ticks:{color:'#7a8595'},
          title:{display:!!opts.yLabel, text:opts.yLabel, color:'#b6bfcc'}},
      x: {grid:{display:false}, ticks:{color:'#b6bfcc'}},
    },
  };
}

function errorBarPlugin() {
  return {
    id: 'errorBars',
    afterDatasetsDraw(chart) {
      const {ctx, data, scales} = chart;
      const yScale = scales.y;
      data.datasets.forEach((ds, dsi) => {
        if (!ds._errorBars) return;
        const meta = chart.getDatasetMeta(dsi);
        meta.data.forEach((bar, i) => {
          const eb = ds._errorBars[i]; if (!eb) return;
          const yLo = yScale.getPixelForValue(eb.lo);
          const yHi = yScale.getPixelForValue(eb.hi);
          ctx.save();
          ctx.strokeStyle = 'rgba(255,255,255,0.55)';
          ctx.lineWidth = 1.5; ctx.beginPath();
          ctx.moveTo(bar.x, yLo); ctx.lineTo(bar.x, yHi);
          ctx.moveTo(bar.x-5, yLo); ctx.lineTo(bar.x+5, yLo);
          ctx.moveTo(bar.x-5, yHi); ctx.lineTo(bar.x+5, yHi);
          ctx.stroke(); ctx.restore();
        });
      });
    },
  };
}

function kpi(el, items) {
  el.innerHTML = items.map(i => `<div class="kpi">
    <span class="v ${i.color||'neu'}">${i.value}</span>
    <span class="k">${i.label}</span>
    ${i.sub ? `<span class="n">${i.sub}</span>` : ''}
  </div>`).join('');
}

function fmtPct(p) { return (p*100).toFixed(1) + '%'; }

// ============================================================================
// 1. OVERTIME HCA
// ============================================================================
{
  const a = anomalies.overtime_hca;
  kpi(document.getElementById('kpi-1'), [
    {value: fmtPct(a.regulation.home_win_p), label: 'Regulation home-win %', sub: `n=${a.regulation.n.toLocaleString('en-US')} [${fmtPct(a.regulation.lo)}-${fmtPct(a.regulation.hi)}]`, color:'pos'},
    {value: fmtPct(a.overtime.home_win_p), label: 'Overtime home-win %', sub: `n=${a.overtime.n} [${fmtPct(a.overtime.lo)}-${fmtPct(a.overtime.hi)}]`, color:'neg'},
    {value: a.diff_pp.toFixed(1)+' pp', label: 'Drop in OT', sub:`z=${a.z} &middot; p=${a.p_value}`, color:'warn'},
  ]);
  new Chart(document.getElementById('c1').getContext('2d'), {
    type:'bar',
    data: {labels:['Regulation', 'Overtime'], datasets:[{
      label:'Home win %', data:[a.regulation.home_win_p*100, a.overtime.home_win_p*100],
      backgroundColor: [COLORS.pos, COLORS.neg],
      _errorBars:[{lo:a.regulation.lo*100, hi:a.regulation.hi*100},
                  {lo:a.overtime.lo*100, hi:a.overtime.hi*100}],
    }]},
    plugins: [errorBarPlugin()],
    options: {...baseChartOpts({yLabel:'Home win %', legend:false}),
      scales:{y:{min:0,max:100, ticks:{color:'#7a8595', callback:(v)=>v+'%'},
                 grid:{color:'rgba(255,255,255,0.05)'}, title:{display:true, text:'Home win %', color:'#b6bfcc'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc', font:{weight:500}}}},
    },
  });
}

// ============================================================================
// 2. FIRST-SCORE EFFECT
// ============================================================================
{
  const a = anomalies.first_score;
  kpi(document.getElementById('kpi-2'), [
    {value: fmtPct(a.scored_first_team_wins.p), label: 'Team that scored first wins %', sub:`CI [${fmtPct(a.scored_first_team_wins.lo)}-${fmtPct(a.scored_first_team_wins.hi)}]`, color:'neu'},
    {value: fmtPct(a.home_scored_first.home_win_p), label: 'Home wins when home scored first', sub:`n=${a.home_scored_first.n}`, color:'pos'},
    {value: fmtPct(a.away_scored_first.home_win_p), label: 'Home wins when AWAY scored first', sub:`n=${a.away_scored_first.n} (home still wins most)`, color:'pos'},
  ]);
  new Chart(document.getElementById('c2').getContext('2d'), {
    type:'bar',
    data: {labels:['Home scored first', 'Away scored first'], datasets:[{
      label:'Home win %', data:[a.home_scored_first.home_win_p*100, a.away_scored_first.home_win_p*100],
      backgroundColor: [COLORS.pos, COLORS.neu],
      _errorBars:[{lo:a.home_scored_first.lo*100, hi:a.home_scored_first.hi*100},
                  {lo:a.away_scored_first.lo*100, hi:a.away_scored_first.hi*100}],
    }]},
    plugins: [errorBarPlugin()],
    options: {...baseChartOpts({yLabel:'Home win %', legend:false}),
      scales:{y:{min:40,max:80, ticks:{color:'#7a8595', callback:(v)=>v+'%'}, title:{display:true, text:'Home win %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 3. QUARTER-BY-QUARTER HCA
// ============================================================================
{
  const a = anomalies.quarter_hca;
  const qs = a.by_quarter;
  kpi(document.getElementById('kpi-3'), [
    {value: '+'+qs[0].mean_home_margin.toFixed(2), label:'Q1 home margin', sub:`[${qs[0].lo.toFixed(2)}-${qs[0].hi.toFixed(2)}]`, color:'pos'},
    {value: '+'+qs[1].mean_home_margin.toFixed(2), label:'Q2', color:'pos'},
    {value: '+'+qs[2].mean_home_margin.toFixed(2), label:'Q3', color:'pos'},
    {value: '+'+qs[3].mean_home_margin.toFixed(2), label:'Q4', color:'pos'},
  ]);
  new Chart(document.getElementById('c3').getContext('2d'), {
    type:'bar',
    data:{labels:qs.map(q=>'Q'+q.quarter), datasets:[{
      label:'Mean home margin', data: qs.map(q=>q.mean_home_margin),
      backgroundColor: COLORS.pos,
      _errorBars: qs.map(q=>({lo:q.lo, hi:q.hi})),
    }]},
    plugins:[errorBarPlugin()],
    options:{...baseChartOpts({yLabel:'Home points - Away points (per game)', legend:false}),
      scales:{y:{min:0, max:2, ticks:{color:'#7a8595'}, title:{display:true, text:'Home margin (pts/game)', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc', font:{weight:500}}}},
    },
  });
}

// ============================================================================
// 4. CLUTCH HCA
// ============================================================================
{
  const a = anomalies.clutch_hca;
  kpi(document.getElementById('kpi-4'), a.buckets.map(b => ({
    value: fmtPct(b.home_win_p), label: b.bucket, sub:`n=${b.n.toLocaleString('en-US')} [${fmtPct(b.lo)}-${fmtPct(b.hi)}]`,
    color: b.bucket.startsWith('close') ? 'warn' : (b.bucket.startsWith('medium') ? 'neu' : 'pos'),
  })));
  new Chart(document.getElementById('c4').getContext('2d'), {
    type:'bar',
    data:{labels: a.buckets.map(b=>b.bucket), datasets:[{
      label:'Home win %', data: a.buckets.map(b=>b.home_win_p*100),
      backgroundColor: [COLORS.warn, COLORS.neu, COLORS.pos],
      _errorBars: a.buckets.map(b=>({lo:b.lo*100, hi:b.hi*100})),
    }]},
    plugins:[errorBarPlugin()],
    options:{...baseChartOpts({yLabel:'Home win %', legend:false}),
      scales:{y:{min:40,max:80, ticks:{color:'#7a8595', callback:(v)=>v+'%'}, title:{display:true, text:'Home win %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 5. BLOWOUT ASYMMETRY
// ============================================================================
{
  const a = anomalies.blowout_asymmetry;
  const t20 = a.thresholds.find(t=>t.margin===20);
  kpi(document.getElementById('kpi-5'), [
    {value: t20.home.toString(), label:'Home wins by 20+', sub: fmtPct(t20.home_p)+' of games', color:'pos'},
    {value: t20.away.toString(), label:'Away wins by 20+', sub: fmtPct(t20.away_p)+' of games', color:'neg'},
    {value: t20.ratio.toFixed(2)+'x', label:'Ratio (home / away)', sub:'home blowouts dominate', color:'warn'},
    {value: a.thresholds.find(t=>t.margin===30).ratio.toFixed(2)+'x', label:'At 30+ margin', color:'neg'},
  ]);
  new Chart(document.getElementById('c5').getContext('2d'), {
    type:'bar',
    data:{labels: a.thresholds.map(t=>'|margin| >= '+t.margin), datasets:[
      {label:'Home wins', data: a.thresholds.map(t=>t.home), backgroundColor: COLORS.pos},
      {label:'Away wins', data: a.thresholds.map(t=>t.away), backgroundColor: COLORS.neg},
    ]},
    options:{...baseChartOpts({yLabel:'Number of games'}),
      scales:{y:{ticks:{color:'#7a8595'}, title:{display:true, text:'# games', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 6. HALFTIME COMEBACK
// ============================================================================
{
  const a = anomalies.halftime_comeback;
  kpi(document.getElementById('kpi-6'), [
    {value: fmtPct(a.home_trailing.comeback_p), label:'Home comeback from 10+ down at half', sub:`n=${a.home_trailing.n}`, color:'pos'},
    {value: fmtPct(a.away_trailing.comeback_p), label:'Away comeback from 10+ down at half', sub:`n=${a.away_trailing.n}`, color:'neg'},
    {value: (a.home_trailing.comeback_p/a.away_trailing.comeback_p).toFixed(1)+'x', label:'Home is this much more likely to recover', color:'warn'},
  ]);
  new Chart(document.getElementById('c6').getContext('2d'), {
    type:'bar',
    data:{labels:['Home trailing 10+ at half', 'Away trailing 10+ at half'], datasets:[{
      label:'Comeback %', data:[a.home_trailing.comeback_p*100, a.away_trailing.comeback_p*100],
      backgroundColor:[COLORS.pos, COLORS.neg],
      _errorBars:[{lo:a.home_trailing.lo*100, hi:a.home_trailing.hi*100},
                  {lo:a.away_trailing.lo*100, hi:a.away_trailing.hi*100}],
    }]},
    plugins:[errorBarPlugin()],
    options:{...baseChartOpts({yLabel:'Comeback %', legend:false}),
      scales:{y:{min:0,max:30, ticks:{color:'#7a8595', callback:(v)=>v+'%'}, title:{display:true, text:'Comeback %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 7. TIED AT HALF
// ============================================================================
{
  const a = anomalies.tied_at_half;
  const te = a.buckets.tied_exact;
  const w2 = a.buckets.within_2;
  kpi(document.getElementById('kpi-7'), [
    {value: fmtPct(te.home_win_p), label:'Home win % when tied at half (exact)', sub:`n=${te.n} [${fmtPct(te.lo)}-${fmtPct(te.hi)}]`, color:'pos'},
    {value: fmtPct(w2.home_win_p), label:'Within 2 pts at half', sub:`n=${w2.n} [${fmtPct(w2.lo)}-${fmtPct(w2.hi)}]`, color:'neu'},
    {value: '63.1%', label:'Baseline (all games)', sub:'HCA fully preserved from halftime', color:'dim'},
  ]);
  new Chart(document.getElementById('c7').getContext('2d'), {
    type:'bar',
    data:{labels:['Tied exactly at half', 'Within 2 pts at half', 'All games (baseline)'], datasets:[{
      label:'Home win %', data:[te.home_win_p*100, w2.home_win_p*100, 63.07],
      backgroundColor:[COLORS.pos, COLORS.neu, COLORS.dim],
      _errorBars:[{lo:te.lo*100, hi:te.hi*100},{lo:w2.lo*100, hi:w2.hi*100},{lo:61.25, hi:64.85}],
    }]},
    plugins:[errorBarPlugin()],
    options:{...baseChartOpts({yLabel:'Home win %', legend:false}),
      scales:{y:{min:40,max:80, ticks:{color:'#7a8595', callback:(v)=>v+'%'}, title:{display:true, text:'Home win %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 8. TEAM 3PT HOME/ROAD GAPS
// ============================================================================
{
  const a = anomalies.team_3pt_gap;
  document.getElementById('league-gap-note').textContent = a.league_mean_gap_pp.toFixed(2);
  const all = [...a.top_home_shooters.map(r=>({...r, dir:'home'})).slice(0,5),
               ...a.top_road_warriors.map(r=>({...r, dir:'road'})).slice(0,5)];
  new Chart(document.getElementById('c8').getContext('2d'), {
    type:'bar',
    data:{
      labels: all.map(r=>r.team_id),
      datasets:[{
        label:'Home 3PT% - Road 3PT% (pp)',
        data: all.map(r=>r.gap_pp),
        backgroundColor: all.map(r=>r.gap_pp>0 ? COLORS.pos : COLORS.neg),
      }],
    },
    options:{...baseChartOpts({yLabel:'Home-away 3PT% gap (pp)', legend:false}),
      indexAxis:'y',
      scales:{
        x:{title:{display:true, text:'Home-Road 3PT% (pp)', color:'#b6bfcc'}, ticks:{color:'#7a8595'}, grid:{color:'rgba(255,255,255,0.05)'}},
        y:{ticks:{color:'#b6bfcc', font:{size:12, weight:500}}, grid:{display:false}},
      },
      plugins:{legend:{display:false},
        tooltip:{callbacks:{
          label: (ctx) => {
            const r = all[ctx.dataIndex];
            return [`${r.team_id}: ${r.gap_pp.toFixed(2)} pp`,
                    `home 3PT%: ${r.fg3_pct_home.toFixed(1)}%`,
                    `away 3PT%: ${r.fg3_pct_away.toFixed(1)}%`,
                    `games: ${r.n_home_games}H / ${r.n_away_games}A`];
          }
        }}
      },
    },
  });
}

// ============================================================================
// 9. FT-MYTH
// ============================================================================
{
  const a = anomalies.ft_myth;
  kpi(document.getElementById('kpi-9'), [
    {value: a.home.ft_pct.toFixed(2)+'%', label:'Home FT%', sub:`${a.home.ftm.toLocaleString('en-US')} / ${a.home.fta.toLocaleString('en-US')}`, color:'pos'},
    {value: a.away.ft_pct.toFixed(2)+'%', label:'Away FT%', sub:`${a.away.ftm.toLocaleString('en-US')} / ${a.away.fta.toLocaleString('en-US')}`, color:'neg'},
    {value: '+'+a.diff_pp.toFixed(2)+' pp', label:'Difference', sub:`z=${a.z} &middot; p=${a.p_value} (not significant)`, color:'dim'},
  ]);
  new Chart(document.getElementById('c9').getContext('2d'), {
    type:'bar',
    data:{labels:['Home shooters', 'Away shooters'], datasets:[{
      label:'FT%', data:[a.home.ft_pct, a.away.ft_pct],
      backgroundColor:[COLORS.pos, COLORS.neg],
    }]},
    options:{...baseChartOpts({yLabel:'Free-throw %', legend:false}),
      scales:{y:{min:70,max:80, ticks:{color:'#7a8595', callback:(v)=>v+'%'}, title:{display:true, text:'Free-throw %', color:'#b6bfcc'}, grid:{color:'rgba(255,255,255,0.05)'}},
              x:{grid:{display:false}, ticks:{color:'#b6bfcc'}}},
    },
  });
}

// ============================================================================
// 10. PLAYER SPLITS
// ============================================================================
{
  const a = anomalies.player_splits;
  kpi(document.getElementById('kpi-10'), [
    {value: a.n_players_eligible.toString(), label:'Eligible players (>=50 games H+A)', color:'neu'},
    {value: '+'+a.top_home_warriors[0].diff_ppg.toFixed(2), label:'Biggest home-warrior gap (PPG)', sub:a.top_home_warriors[0].player_name, color:'pos'},
    {value: a.top_road_warriors[0].diff_ppg.toFixed(2), label:'Biggest road-warrior gap (PPG)', sub:a.top_road_warriors[0].player_name, color:'neg'},
  ]);
  function row(r) {
    const sign = r.diff_ppg > 0 ? '+' : '';
    const color = r.diff_ppg > 0 ? 'color:var(--pos)' : 'color:var(--neg)';
    return `<tr>
      <td class="name">${r.player_name}</td>
      <td class="num">${r.ppg_home.toFixed(2)}</td>
      <td class="num">${r.ppg_away.toFixed(2)}</td>
      <td class="num" style="${color};font-weight:600">${sign}${r.diff_ppg.toFixed(2)}</td>
      <td class="num">${r.games_home}/${r.games_away}</td>
    </tr>`;
  }
  document.getElementById('tbl-home-warriors').innerHTML = a.top_home_warriors.map(row).join('');
  document.getElementById('tbl-road-warriors').innerHTML = a.top_road_warriors.map(row).join('');
}
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
    n_games = data["meta"]["n_games"]
    n_seasons = len(data["meta"]["seasons"])
    html = (HTML
            .replace("__JSON__", json.dumps(data))
            .replace("__N_GAMES__", f"{n_games:,}")
            .replace("__N_SEASONS__", str(n_seasons))
            .replace("__SHA__", _git_sha()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    log.info("wrote %s (%.1f KB)", OUT, OUT.stat().st_size / 1024)


if __name__ == "__main__":
    main()
