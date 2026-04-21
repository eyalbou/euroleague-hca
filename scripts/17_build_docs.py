"""Phase 17 -- build docs/ folder for GitHub Pages.

Copies the three dashboards, the final report, selected JSON reports, the
two Phase E learning notes (converted from markdown to styled HTML), and
a minimal manifest into docs/ at repo root. Pages is configured to serve
from main branch /docs/.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("17_build_docs")

DOCS = config.PROJECT_ROOT / "docs"
DASHBOARDS = config.PROJECT_ROOT / "dashboards"
REPORTS = config.REPORTS_DIR
LEARNING = config.PROJECT_ROOT / "learning"


LEARNING_HTML_WRAPPER = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} -- EuroLeague HCA</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
  :root{--bg:#0b0d10;--panel:#13171d;--ink:#e7ecf1;--muted:#b6bfcc;--dim:#7a8595;
    --accent:#6eb0ff;--pos:#3ccf8e;--hair:rgba(255,255,255,.07)}
  html,body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'DM Sans',system-ui,sans-serif;font-size:15px;line-height:1.6;letter-spacing:-0.01em}
  .wrap{max-width:780px;margin:0 auto;padding:40px 24px 96px}
  .back{color:var(--accent);font-size:13px;text-decoration:none}
  h1{font-size:32px;letter-spacing:-0.02em;margin:24px 0 8px;font-weight:700}
  h2{font-size:22px;letter-spacing:-0.02em;margin:40px 0 12px;
    border-bottom:1px solid var(--hair);padding-bottom:8px;font-weight:600}
  h3{font-size:17px;margin:28px 0 10px;font-weight:600}
  p,li{color:var(--muted)}
  li{margin:6px 0}
  strong{color:var(--ink);font-weight:600}
  em{color:var(--ink)}
  code{background:rgba(255,255,255,.06);padding:2px 6px;border-radius:4px;font-size:13px;
    font-family:'JetBrains Mono',ui-monospace,monospace;color:#e4b85c}
  pre{background:var(--panel);padding:16px;border-radius:8px;overflow:auto;font-size:13px;
    border:1px solid var(--hair)}
  pre code{background:transparent;padding:0;color:var(--ink)}
  blockquote{border-left:3px solid var(--accent);margin:16px 0;padding:4px 16px;
    color:var(--muted);background:rgba(110,176,255,.04)}
  table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
  th,td{padding:8px 12px;border-bottom:1px solid var(--hair);text-align:left;color:var(--muted)}
  th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  hr{border:0;border-top:1px solid var(--hair);margin:32px 0}
  a{color:var(--accent)}
  .eyebrow{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:24px}
</style>
</head>
<body><div class="wrap">
<a class="back" href="index.html">&larr; back to dashboard index</a>
<div class="eyebrow">Phase E -- learning artifact</div>
{body}
</div></body></html>"""


def _convert_learning_md(md_path: Path, title: str, out_path: Path) -> None:
    try:
        import markdown
    except ImportError:
        log.warning("markdown package not installed; skipping %s", md_path.name)
        return
    body = markdown.markdown(md_path.read_text(), extensions=["tables", "fenced_code"])
    html = LEARNING_HTML_WRAPPER.replace("{title}", title).replace("{body}", body)
    out_path.write_text(html)
    log.info("converted %s -> %s (%.0f KB)", md_path.name, out_path.name, out_path.stat().st_size / 1024)


def main() -> None:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)

    # Copy dashboards
    for name in ["index.html", "dashboard.html", "transitions.html",
                 "final_report.html", "referees.html", "rebound_rates.html",
                 "anomalies.html", "explorer.html"]:
        src = DASHBOARDS / name
        if src.exists():
            shutil.copy2(src, DOCS / name)
            log.info("copied dashboards/%s", name)

    # Copy walkthrough video if rendered
    video_src = config.PROJECT_ROOT / "video" / "out" / "walkthrough.mp4"
    if video_src.exists():
        shutil.copy2(video_src, DOCS / "walkthrough.mp4")
        log.info("copied walkthrough.mp4 (%.1f MB)", video_src.stat().st_size / 1024 / 1024)

    # Copy shared assets (if any)
    assets_src = DASHBOARDS / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, DOCS / "assets")

    # Copy selected report JSONs (traceability for reviewers)
    DOCS_REPORTS = DOCS / "reports"
    DOCS_REPORTS.mkdir()
    publishable = [
        "logistic_output.json",
        "trees_output.json",
        "mixedlm_output.json",
        "ridge_fe_output.json",
        "covid_output.json",
        "mechanism_output.json",
        "transitions_bars.json",
        "transitions_concentration.json",
        "transitions_qa.json",
        "transitions_team_rank.json",
        "transitions_bigrams.json",
        "hca_transitions.json",
        "referee_output.json",
        "referee_qa.json",
        "rebound_rates.json",
        "rebound_rates_qa.json",
        "rebound_slices.json",
        "anomalies.json",
        "team_explorer.json",
        "final_report.md",
    ]
    for name in publishable:
        src = REPORTS / name
        if src.exists():
            shutil.copy2(src, DOCS_REPORTS / name)

    # Phase E -- learning notes, converted from markdown to styled HTML
    learning_pages = [
        ("concepts-learned.md", "Concepts learned", "concepts-learned.html"),
        ("llm-engineering-lessons.md", "LLM engineering lessons", "llm-engineering-lessons.html"),
    ]
    for md_name, title, html_name in learning_pages:
        src = LEARNING / md_name
        if src.exists():
            _convert_learning_md(src, title, DOCS / html_name)
        else:
            log.warning("missing learning file %s", src)

    # Manifest
    manifest = {
        "built_at_utc": datetime.utcnow().isoformat() + "Z",
        "dashboards": [
            {"href": "index.html", "title": "Summary (start here)"},
            {"href": "dashboard.html", "title": "Analyst dashboard (7 tabs)"},
            {"href": "transitions.html", "title": "Play-by-play transitions"},
            {"href": "referees.html", "title": "Referee-bias audit (Phase F)"},
            {"href": "rebound_rates.html", "title": "Rebound rates by miss type (Phase H)"},
            {"href": "anomalies.html", "title": "Ten basketball anomalies (Phase I)"},
            {"href": "explorer.html", "title": "Team & Season Explorer (multi-select filters, Phase J)"},
            {"href": "walkthrough.mp4", "title": "3-minute walkthrough video (Phase G)"},
            {"href": "final_report.html", "title": "Written report"},
            {"href": "concepts-learned.html", "title": "Concepts learned (Phase E)"},
            {"href": "llm-engineering-lessons.html", "title": "LLM engineering lessons (Phase E)"},
        ],
        "reports_count": len(list(DOCS_REPORTS.glob("*"))),
    }
    (DOCS / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # .nojekyll -- prevent GH Pages from running Jekyll (respects underscores, etc.)
    (DOCS / ".nojekyll").write_text("")

    total_kb = sum(p.stat().st_size for p in DOCS.rglob("*") if p.is_file()) / 1024
    log.info("docs/ built: %.0f KB, %d files",
             total_kb, sum(1 for _ in DOCS.rglob("*") if _.is_file()))


if __name__ == "__main__":
    main()
