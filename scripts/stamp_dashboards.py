"""Stamp a build-provenance footer (commit SHA + UTC timestamp) into every
dashboard HTML file. Runs as a post-build step so the generator scripts don't
need to be aware of git.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from euroleague_hca import config

DASHBOARDS = config.PROJECT_ROOT / "dashboards"
MARKER = "<!-- build-footer -->"


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=config.PROJECT_ROOT, text=True,
        ).strip()
    except Exception:
        return "dev"


def stamp(path: Path, sha: str, stamp_ts: str) -> bool:
    html = path.read_text()
    footer = (
        f'{MARKER}<div style="position:fixed;bottom:0;left:0;right:0;'
        f'background:rgba(11,13,16,0.92);color:#7a8595;'
        f'font:400 11px/1.4 \'DM Sans\',system-ui,sans-serif;'
        f'padding:6px 12px;text-align:right;border-top:1px solid rgba(255,255,255,0.07);'
        f'z-index:9999;pointer-events:none">'
        f'Build <code style="color:#b6bfcc">{sha}</code> &middot; '
        f'rebuilt {stamp_ts} UTC &middot; '
        f'<a href="https://github.com/eyalbou/euroleague-hca" '
        f'style="color:#6eb0ff;text-decoration:none;pointer-events:auto">source</a>'
        f'</div>'
    )
    if MARKER in html:
        # Already stamped -- replace the existing footer block.
        import re
        html = re.sub(
            re.escape(MARKER) + r'<div[^<]*?(?:<[^/][^>]*>[^<]*?</[^>]+>[^<]*?)*?</div>',
            footer, html, flags=re.DOTALL,
        )
    else:
        html = html.replace("</body>", footer + "</body>", 1)
    path.write_text(html)
    return True


def main() -> None:
    sha = _sha()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    targets = [p for p in DASHBOARDS.glob("*.html") if "archive" not in str(p)]
    for p in targets:
        stamp(p, sha, ts)
        print(f"stamped {p.name}  (build {sha}, {ts})")


if __name__ == "__main__":
    main()
