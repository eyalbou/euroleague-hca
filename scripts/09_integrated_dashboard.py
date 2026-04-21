"""Phase 9 -- Integrated dashboard.

Tabbed view that embeds each phase dashboard as an iframe so everything is
reachable from a single entry point.
"""
# %% imports
from __future__ import annotations

import json
from pathlib import Path

from euroleague_hca import config


PHASES = [
    ("phase-01-ingest",         "Phase 1 -- Ingest",                "Raw -> bronze coverage"),
    ("phase-02-coverage",       "Phase 2 -- Validate",              "Silver tables, warehouse coverage, integrity"),
    ("phase-04-descriptive",    "Phase 4 -- Descriptive HCA",       "League + per-team HCA, attendance dose-response, D04-1..D04-16"),
    ("phase-04b-descriptive-ext","Phase 4b -- Ext descriptive",      "PBP/shot/geo/referee placeholders + head-to-head"),
    ("phase-05-tests",          "Phase 5 -- Hypothesis tests",      "Permutation, paired t / Wilcoxon, Spearman"),
    ("phase-06-ml-logistic",    "Phase 6a -- Logistic",             "Baselines + logistic + attendance interaction"),
    ("phase-07-ml-trees",       "Phase 6b -- Trees + SHAP",         "RF + LightGBM, feature importance, PDP"),
    ("phase-07c-mixedlm",       "Phase 6b.5 -- Mixed effects",      "Per-team random intercept + slope"),
    ("phase-07b-hierarchical",  "Phase 6c -- Bayesian (optional)",  "PyMC partial pooling (skipped if PyMC missing)"),
    ("phase-08-covid",          "Phase 7 -- COVID experiment",      "DiD across pre / covid / post"),
]


def build_index() -> Path:
    tabs_html = "\n".join(
        f'<button class="tab" data-target="{slug}">{title}</button>'
        for slug, title, _ in PHASES
    )
    panels_html = "\n".join(
        f'<section class="panel" id="{slug}"><header class="panel-head"><h2>{title}</h2>'
        f'<p class="panel-sub">{sub}</p>'
        f'<a class="panel-open" href="{slug}.html" target="_blank">open full &#8599;</a></header>'
        f'<iframe src="{slug}.html" loading="lazy"></iframe></section>'
        for slug, title, sub in PHASES
    )
    first = PHASES[0][0]

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EuroLeague HCA -- integrated dashboard</title>
<link rel="stylesheet" href="assets/styles.css">
<style>
  body {{ margin: 0; background: var(--bg, #0f1218); }}
  .app-header {{ padding: 20px 32px; border-bottom: 1px solid var(--border, #2a2f3a); }}
  .app-header h1 {{ margin: 0 0 4px 0; font-size: 22px; }}
  .app-header p {{ margin: 0; color: var(--muted, #9aa4b2); font-size: 13px; }}
  .tabs {{ display: flex; gap: 8px; padding: 12px 32px; overflow-x: auto; border-bottom: 1px solid var(--border, #2a2f3a); background: rgba(255,255,255,0.02); }}
  .tab {{ background: transparent; border: 1px solid var(--border, #2a2f3a); color: var(--muted, #9aa4b2); padding: 8px 16px; border-radius: 999px; font-size: 13px; cursor: pointer; white-space: nowrap; }}
  .tab:hover {{ color: var(--fg, #e7ecf3); border-color: var(--accent, #4f8cff); }}
  .tab.active {{ background: var(--accent, #4f8cff); color: #fff; border-color: var(--accent, #4f8cff); }}
  .panels {{ position: relative; }}
  .panel {{ display: none; padding: 0; }}
  .panel.active {{ display: block; }}
  .panel-head {{ padding: 16px 32px 8px; display: flex; align-items: baseline; gap: 16px; }}
  .panel-head h2 {{ margin: 0; font-size: 18px; }}
  .panel-sub {{ margin: 0; color: var(--muted, #9aa4b2); font-size: 13px; flex: 1; }}
  .panel-open {{ color: var(--accent, #4f8cff); text-decoration: none; font-size: 12px; }}
  iframe {{ width: 100%; height: calc(100vh - 160px); border: 0; background: var(--bg, #0f1218); }}
</style>
</head>
<body>
<header class="app-header">
  <h1>EuroLeague Home-Court Advantage</h1>
  <p>Integrated dashboard -- 10 seasons, {'MOCK DATA' if config.USE_MOCK_DATA else 'LIVE DATA'} -- click any tab to open that phase</p>
</header>
<nav class="tabs">
  {tabs_html}
</nav>
<div class="panels">
  {panels_html}
</div>
<script>
  const tabs = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  function activate(id) {{
    tabs.forEach(t => t.classList.toggle('active', t.dataset.target === id));
    panels.forEach(p => p.classList.toggle('active', p.id === id));
    history.replaceState(null, '', '#' + id);
  }}
  tabs.forEach(t => t.addEventListener('click', () => activate(t.dataset.target)));
  const fromHash = location.hash.replace('#', '');
  activate(fromHash || '{first}');
</script>
</body>
</html>
"""
    out = config.DASHBOARDS_DIR / "dashboard.html"
    out.write_text(html)
    return out


if __name__ == "__main__":
    print(config.banner())
    out = build_index()
    print(f"integrated dashboard: {out}")
    print(f"open with: open {out}")
