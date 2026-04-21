"""Phase 17 -- build docs/ folder for GitHub Pages.

Copies the three dashboards, the final report, selected JSON reports, and
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


def main() -> None:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)

    # Copy dashboards
    for name in ["index.html", "dashboard.html", "transitions.html", "final_report.html"]:
        src = DASHBOARDS / name
        if src.exists():
            shutil.copy2(src, DOCS / name)
            log.info("copied dashboards/%s", name)

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
        "hca_transitions.json",
        "final_report.md",
    ]
    for name in publishable:
        src = REPORTS / name
        if src.exists():
            shutil.copy2(src, DOCS_REPORTS / name)

    # Manifest
    manifest = {
        "built_at_utc": datetime.utcnow().isoformat() + "Z",
        "dashboards": [
            {"href": "index.html", "title": "Summary (start here)"},
            {"href": "dashboard.html", "title": "Analyst dashboard (7 tabs)"},
            {"href": "transitions.html", "title": "Play-by-play transitions"},
            {"href": "final_report.html", "title": "Written report"},
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
