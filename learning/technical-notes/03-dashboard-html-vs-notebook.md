# Technical note 03 -- HTML dashboards instead of notebooks

## Why we dropped Jupyter

- `.ipynb` diffs are unreadable in git. Every cell execution rewrites metadata, so "what changed"
  is lost in noise.
- Notebooks encourage hidden state (run cells out of order, forget a variable was redefined).
- Notebooks are tied to a kernel; opening one from a stranger's repo requires the right env.

## What we do instead

- **Python scripts with `# %%` cell markers.** Cursor and VS Code render these as runnable cells,
  but the file is a plain `.py` -- clean diffs, no metadata, no kernel required.
- **HTML dashboards** with Chart.js, rendered by `dashboard/render.py` from a Jinja template and a
  JSON payload. Each dashboard is self-contained: open the HTML, see charts. No server.

## Asset sharing

All dashboards share `dashboards/assets/styles.css`, `chart-theme.js`, `fmt.js`, `filters.js`,
`chart-helpers.js`, `dashboard.js`. Copy them into a new project in one directory and every
downstream dashboard looks consistent.

## One thing to watch

Chart.js does NOT inherit CSS `font-family`. You have to set `Chart.defaults.font.family`
explicitly in `chart-theme.js` to match the CSS font. This is documented in the
`eyal-visualization` skill and we followed it.

## When we'd use a notebook

- One-off exploration before committing to a pipeline step. Scratch space in `scripts/_scratch.py`
  (with `# %%` cells) works just as well and stays in git's ignore list.
