# ADR -- dashboard stack

## Status
Accepted.

## Context
We need visualizations that (a) are easy to commit to git, (b) open without a server, (c) support
interactive filtering for the HCA-over-time graph, and (d) render the same in sample and full
mode.

## Decision
Self-contained HTML dashboards rendered from Python via Jinja2 + Chart.js (via CDN).

- One template: `dashboard/templates/base.html.j2`.
- One Python helper: `dashboard/render.py` builds a JSON payload and injects it as
  `<script type="application/json" id="payload">...`.
- One JS helper: `dashboards/assets/dashboard.js` reads the payload and renders all charts.

## Alternatives considered
- **Jupyter.** Rejected for diff hygiene and hidden state (see technical-note-03).
- **Streamlit/Dash.** Rejected because they require a running server. We want static output.
- **Plotly HTML export.** Rejected because the per-file size balloons past 3 MB and it inlines a
  full Plotly bundle per chart.
- **D3 from scratch.** Rejected because Chart.js gives us 90% of what we need in 10% of the code.

## Consequences
- Dashboards are 50-150 KB HTML files with zero dependencies beyond a CDN.
- Chart customization is cheap (shared helpers in `chart-helpers.js`).
- Adding a new chart type means adding a render function in `chart-helpers.js` plus a branch in
  `dashboard.js`.

## When to revisit
If we want live updates (websockets, incremental refresh), Streamlit becomes attractive again.
