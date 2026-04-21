"""Phase 16 -- build dashboards/index.html one-pager.

A tight summary landing page that links into the deep dashboards. Designed
for mobile-first viewing (follows eyal-visualization defaults: DM Sans, 4-pt
grid, subtle shadows, K/M formatting).
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("16_summary_onepager")


def _read(name: str) -> dict:
    p = config.REPORTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else {}


def _sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=config.PROJECT_ROOT, text=True).strip()
    except Exception:
        return "dev"


HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>EuroLeague HCA -- Home Court Advantage Analysis</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
  :root{
    --bg:#0b0d10; --panel:#13171d; --ink:#e7ecf1; --muted:#b6bfcc; --dim:#7a8595;
    --accent:#6eb0ff; --pos:#3ccf8e; --neg:#ef5a5a; --hair:rgba(255,255,255,.07);
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:var(--bg);color:var(--ink);
    font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.45;
    letter-spacing:-0.01em;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1080px;margin:0 auto;padding:32px 24px 96px}
  .hero{padding:32px 0 24px;border-bottom:1px solid var(--hair)}
  .eyebrow{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
  h1{font-size:36px;font-weight:700;line-height:1.08;margin:0 0 12px;letter-spacing:-0.03em}
  h1 .lead{color:var(--pos)}
  .sub{color:var(--muted);max-width:720px;margin:0 0 8px}
  .meta{color:var(--dim);font-size:12px;margin-top:12px}

  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:32px 0}
  .kpi{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:16px 16px 14px;
    box-shadow:0 1px 3px rgba(0,0,0,.4)}
  .kpi .v{font-size:28px;font-weight:700;letter-spacing:-0.02em;line-height:1.1;display:block}
  .kpi .v.pos{color:var(--pos)} .kpi .v.neu{color:var(--accent)}
  .kpi .k{color:var(--dim);font-size:12px;margin-top:4px;display:block}
  .kpi .n{color:var(--dim);font-size:11px;margin-top:8px;display:block;font-variant-numeric:tabular-nums}

  h2{font-size:22px;font-weight:600;letter-spacing:-0.02em;margin:40px 0 16px}
  h3{font-size:16px;font-weight:600;margin:24px 0 8px}

  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin:16px 0}
  .card{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:20px;
    text-decoration:none;color:inherit;display:block;transition:border-color .15s}
  .card:hover{border-color:#2a3440}
  .card .title{font-size:16px;font-weight:600;margin-bottom:8px}
  .card .desc{color:var(--muted);font-size:13px}
  .card .arrow{color:var(--accent);font-size:13px;margin-top:12px;display:inline-block}

  ul.facts{padding:0;margin:0;list-style:none}
  ul.facts li{padding:10px 0;border-bottom:1px solid var(--hair);color:var(--muted)}
  ul.facts li:last-child{border-bottom:0}
  ul.facts li strong{color:var(--ink)}

  table.tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  table.tbl th,table.tbl td{padding:8px 10px;border-bottom:1px solid var(--hair);text-align:left}
  table.tbl th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  table.tbl td.num{font-variant-numeric:tabular-nums;text-align:right}

  footer{margin-top:48px;color:var(--dim);font-size:12px;border-top:1px solid var(--hair);padding-top:16px}
  code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;
    background:rgba(255,255,255,.05);padding:1px 5px;border-radius:4px}

  @media (max-width:640px){
    h1{font-size:28px}
    .wrap{padding:24px 16px 64px}
  }
</style>
</head>
<body>
<div class="wrap">

<div class="hero">
  <div class="eyebrow">EuroLeague Basketball · 10 seasons · 2015-16 → 2024-25</div>
  <h1>Home teams win <span class="lead">__ODDS__x</span> more often.<br/>
     <span style="color:var(--muted);font-weight:500">Here's why -- and what it means possession by possession.</span></h1>
  <p class="sub">
    A self-built analysis pipeline -- direct Swagger API pulls, bronze/silver/gold parquet lake,
    SQLite warehouse, 1.13M play-by-play events, mixed-effects models, and a COVID natural experiment --
    all running locally in Cursor. Built as a learning exercise in ML engineering and LLM-assisted analysis.
  </p>
  <div class="meta">Build <code>__SHA__</code> · rebuilt __DATE__ UTC · <a href="https://github.com/__REPO__" style="color:var(--accent)">source on GitHub</a></div>
</div>

<div style="margin:24px 0 0;padding:20px;background:var(--panel);border:1px solid var(--hair);border-radius:12px;display:flex;gap:20px;align-items:center;flex-wrap:wrap">
  <div style="flex:1;min-width:240px">
    <div style="color:var(--pos);font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:4px">▶ 3-minute walkthrough</div>
    <div style="color:var(--ink);font-size:15px;font-weight:500;line-height:1.4">The whole story in under three minutes: headline, referee null result, possession mechanism, COVID experiment, and what it all means.</div>
  </div>
  <a href="walkthrough.mp4" style="background:var(--accent);color:#0b0d10;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600;font-size:13px;white-space:nowrap">Watch video →</a>
</div>

<div class="kpis">
  <div class="kpi">
    <span class="v pos">+__HCA_PTS__</span>
    <span class="k">pts / game home advantage</span>
    <span class="n">mixed-effects LM intercept, 95% CI</span>
  </div>
  <div class="kpi">
    <span class="v neu">__ODDS__x</span>
    <span class="k">home-win odds ratio</span>
    <span class="n">logistic regression on __N_GAMES__ games</span>
  </div>
  <div class="kpi">
    <span class="v pos">__SHARE__%</span>
    <span class="k">of HCA explained by possession efficiency</span>
    <span class="n">from play-by-play Δ PPP</span>
  </div>
  <div class="kpi">
    <span class="v pos">+__DELTA__</span>
    <span class="k">Δ pts / possession (home - road)</span>
    <span class="n">volume-weighted across 19 source actions</span>
  </div>
  <div class="kpi">
    <span class="v neu">__POS__%</span>
    <span class="k">of actions show home > road</span>
    <span class="n">every source is positive -- 19 of 19</span>
  </div>
</div>

<h2>Explore the dashboards</h2>
<div class="cards">
  <a class="card" href="dashboard.html">
    <div class="title">1. Analyst dashboard</div>
    <div class="desc">League-wide HCA, per-team variation, attendance dose-response, COVID natural experiment, ML models, mechanism decomposition. Seven tabs.</div>
    <span class="arrow">Open →</span>
  </a>
  <a class="card" href="transitions.html">
    <div class="title">2. Play-by-play transitions</div>
    <div class="desc">For any source action (3-pt make, turnover, block, foul...), see what happens next -- on the other team's next play, or on your own next possession. Includes an HCA lens and Storylines (second-order chains).</div>
    <span class="arrow">Open →</span>
  </a>
  <a class="card" href="referees.html">
    <div class="title">3. Referee-bias audit</div>
    <div class="desc">Per-referee home-vs-away call asymmetry on __N_ELIGIBLE__ EuroLeague officials. Funnel plot + Holm correction. Null result, honestly reported: zero biased refs after correction.</div>
    <span class="arrow">Open →</span>
  </a>
  <a class="card" href="final_report.html">
    <div class="title">4. Written report</div>
    <div class="desc">The full narrative + all numbers traced back to JSON outputs. ~6 KB of text, ~10 min read.</div>
    <span class="arrow">Open →</span>
  </a>
</div>

<h2>Learning notes (Phase E)</h2>
<div class="cards">
  <a class="card" href="concepts-learned.html">
    <div class="title">Concepts learned</div>
    <div class="desc">18 statistical, ML, and data methods used in the project -- paired analysis, cluster bootstrap, mixed-effects LM, DiD, Markov chains, KL divergence, calibration -- each with a concrete worked example from our data.</div>
    <span class="arrow">Read →</span>
  </a>
  <a class="card" href="llm-engineering-lessons.html">
    <div class="title">LLM engineering lessons</div>
    <div class="desc">16 workflow lessons about using an LLM as a coding and analysis partner. Plan-before-prompt, sample-first, code review &gt; code generation, the silent-collapse bug, and a revised scorecard.</div>
    <span class="arrow">Read →</span>
  </a>
</div>

<h2>What each chart says</h2>
<div class="cards">
  <div class="card">
    <div class="title">Where HCA comes from</div>
    <ul class="facts">
      <li><strong>+3.4 pts per 100 possessions</strong> efficiency gap at home</li>
      <li><strong>+1.6 pp</strong> higher free-throw rate at home</li>
      <li><strong>-1.0</strong> fewer turnovers per 100 possessions</li>
      <li><strong>+0.9 pp</strong> eFG% at home (shooting quality)</li>
      <li>Pace and offensive rebounding are <em>not</em> meaningfully different</li>
    </ul>
  </div>
  <div class="card">
    <div class="title">Possession-level HCA</div>
    <ul class="facts">
      <li><strong>Every source action</strong> shows home > road on next-possession PPP</li>
      <li>Top gaps: <code>CMU</code>, <code>AG</code>, <code>FTA</code>, <code>TO</code>, <code>OF</code></li>
      <li>Volume-weighted: <strong>+0.049 PPP</strong> → ~<strong>3.6 pts / game</strong></li>
      <li>94% of the 3.86-pt LM intercept is "explained" by possession efficiency</li>
    </ul>
  </div>
  <div class="card">
    <div class="title">Modeling</div>
    <ul class="facts">
      <li>Elo + <code>is_home</code> logistic → <strong>64.5%</strong> test accuracy</li>
      <li>Full logistic (+ attendance + rest + interactions) → <strong>65.7%</strong></li>
      <li>Mixed-effects LM for per-team slopes; Ridge on team fixed effects</li>
      <li>All bootstraps <strong>clustered at game level</strong></li>
    </ul>
  </div>
  <div class="card">
    <div class="title">COVID natural experiment</div>
    <ul class="facts">
      <li>Closed-doors 2019-20 / 2020-21 as a natural experiment</li>
      <li>Difference-in-differences on <code>home_pts - away_pts</code></li>
      <li>post − pre = <strong>__DID__ pts/game</strong> (CIs overlap zero)</li>
      <li>HCA effectively recovered post-pandemic</li>
    </ul>
  </div>
</div>

<h2>Data pipeline</h2>
<table class="tbl">
  <thead><tr><th>Layer</th><th>Content</th><th>Confidence</th></tr></thead>
  <tbody>
    <tr><td><code>raw/</code></td><td>Swagger JSON + live PBP JSON, gzipped</td><td>Official API -- high</td></tr>
    <tr><td><code>bronze/</code></td><td>Flat parquet -- header, boxscore, PBP events</td><td>Idempotent; partitioned by season</td></tr>
    <tr><td><code>silver/</code></td><td>Dim + fact tables, derived attendance_ratio, closed_doors flag, action_group</td><td>QA: event count monotonicity, attendance sanity</td></tr>
    <tr><td><code>gold/</code></td><td>Analysis-ready aggregates per team/season/phase</td><td>Used by models</td></tr>
    <tr><td><code>warehouse.db</code></td><td>SQLite mirror for ad-hoc SQL during EDA</td><td>Rebuildable from silver</td></tr>
  </tbody>
</table>

<footer>
  Built with Python 3.14, pandas/pyarrow, statsmodels, scikit-learn, LightGBM, Chart.js.
  Cursor-native <code># %%</code> scripts -- no notebooks. All code and intermediate artifacts in the GitHub repo.
</footer>

</div>
</body></html>
"""


def main() -> None:
    logistic = _read("logistic_output.json")
    mixedlm = _read("mixedlm_output.json")
    hca = _read("hca_transitions.json")
    mech = _read("mechanism_output.json")
    covid = _read("covid_output.json")

    sha = _sha()
    date = datetime.utcnow().strftime("%Y-%m-%d")
    repo = "eyalbou/euroleague-hca"
    referees = _read("referee_output.json")

    odds = logistic.get("is_home_odds", 0)
    mixed_int = (mixedlm.get("fixed_effects") or {}).get("Intercept", 0)
    n_games = mech.get("n_games", 2897)
    kpi = hca.get("kpi", {})
    share = kpi.get("share_of_hca_explained", 0)
    pos_share = kpi.get("pct_sources_positive_delta", 0)
    weighted_delta = kpi.get("weighted_delta_ppp", 0)
    did = ((covid.get("did") or {}).get("post - pre") or {}).get("mean", 0)
    ref_eligible = (referees.get("kpi") or {}).get("n_refs_eligible", 61)

    html = (
        HTML
        .replace("__ODDS__", f"{odds:.2f}")
        .replace("__HCA_PTS__", f"{mixed_int:.2f}")
        .replace("__N_GAMES__", f"{n_games:,}")
        .replace("__SHARE__", f"{share*100:.0f}")
        .replace("__DELTA__", f"{weighted_delta:.3f}")
        .replace("__POS__", f"{pos_share*100:.0f}")
        .replace("__DID__", f"{did:+.2f}")
        .replace("__N_ELIGIBLE__", str(ref_eligible))
        .replace("__SHA__", sha)
        .replace("__DATE__", date)
        .replace("__REPO__", repo)
    )

    out = config.PROJECT_ROOT / "dashboards" / "index.html"
    out.write_text(html)
    log.info("wrote %s (%.0f KB)", out, out.stat().st_size / 1024)


if __name__ == "__main__":
    main()
