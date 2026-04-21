"""Self-contained HTML dashboard renderer.

Every dashboard is a single .html file with JSON data embedded in a <script> tag, so the file
can be double-clicked to open in any browser offline. Chart.js + dependencies are loaded from
CDN.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from euroleague_hca.config import DASHBOARDS_DIR, SAMPLE_MODE


def _json_safe(obj: Any) -> Any:
    """Recursively coerce numpy / pandas / datetime values to JSON-friendly types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


@dataclass
class Dashboard:
    title: str
    slug: str
    subtitle: str = ""
    kpis: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)  # each {id, title, description, charts: [...]}

    def add_section(self, id_: str, title: str, description: str = "", charts: list[dict] | None = None) -> None:
        self.sections.append({"id": id_, "title": title, "description": description, "charts": charts or []})

    def write(self) -> Path:
        path = DASHBOARDS_DIR / f"{self.slug}.html"
        payload = _json_safe({
            "title": self.title,
            "subtitle": self.subtitle,
            "kpis": self.kpis,
            "sections": self.sections,
            "sample_mode": SAMPLE_MODE,
        })
        html = _render_html(payload)
        path.write_text(html, encoding="utf-8")
        return path


def _render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <title>{payload['title']}</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link href=\"https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap\" rel=\"stylesheet\">
  <link rel=\"stylesheet\" href=\"assets/styles.css\">
</head>
<body>
  <div id=\"root\"></div>
  <script id=\"payload\" type=\"application/json\">{data_json}</script>
  <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.js\"></script>
  <script src=\"https://cdn.jsdelivr.net/npm/chartjs-chart-matrix@2.0.1/dist/chartjs-chart-matrix.min.js\"></script>
  <script src=\"assets/fmt.js\"></script>
  <script src=\"assets/chart-theme.js\"></script>
  <script src=\"assets/chart-helpers.js\"></script>
  <script src=\"assets/filters.js\"></script>
  <script src=\"assets/dashboard.js\"></script>
</body>
</html>
"""
