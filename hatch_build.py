"""Hatchling build hook: download vendor CSS/JS assets before packaging.

Assets are fetched from their respective CDNs and written into
``py_experimenter_db/dashboard/static/vendor/`` so they are bundled
into the wheel without being checked in to source control.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface as _BuildHookBase
except ModuleNotFoundError:
    _BuildHookBase = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Asset manifest  (local-relative-path -> CDN URL)
# ---------------------------------------------------------------------------

VENDOR_ASSETS: dict[str, str] = {
    # DaisyUI
    "daisyui/full.min.css": "https://cdn.jsdelivr.net/npm/daisyui@4.12.10/dist/full.min.css",
    # Tailwind CSS Play CDN (self-contained JIT engine)
    "tailwind/tailwind.min.js": "https://cdn.tailwindcss.com",
    # HTMX
    "htmx/htmx.min.js": "https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js",
    # Alpine.js
    "alpinejs/cdn.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js",
    # CodeMirror - core
    "codemirror/codemirror.min.css": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/lib/codemirror.min.css",
    "codemirror/codemirror.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/lib/codemirror.min.js",
    # CodeMirror - theme
    "codemirror/dracula.css": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/theme/dracula.css",
    # CodeMirror - modes
    "codemirror/python.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/mode/python/python.min.js",
    "codemirror/sql.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/mode/sql/sql.min.js",
    "codemirror/yaml.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/mode/yaml/yaml.min.js",
    # CodeMirror - hint addon
    "codemirror/show-hint.min.css": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/hint/show-hint.min.css",
    "codemirror/show-hint.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/hint/show-hint.min.js",
    "codemirror/sql-hint.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/hint/sql-hint.min.js",
    # CodeMirror - fold addon
    "codemirror/foldgutter.min.css": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/fold/foldgutter.min.css",
    "codemirror/foldcode.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/fold/foldcode.min.js",
    "codemirror/foldgutter.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/fold/foldgutter.min.js",
    "codemirror/indent-fold.min.js": "https://cdn.jsdelivr.net/npm/codemirror@5.65.16/addon/fold/indent-fold.min.js",
    # Plotly (shared by experiment_detail and carbon pages)
    "plotly/plotly.min.js": "https://cdn.plot.ly/plotly-2.35.2.min.js",
}

_VENDOR_DIR = Path(__file__).parent / "py_experimenter_db" / "dashboard" / "static" / "vendor"


def _fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        dest.write_bytes(resp.read())


def download_all(force: bool = False) -> None:
    """Download all vendor assets to the local static/vendor directory."""
    for rel_path, url in VENDOR_ASSETS.items():
        dest = _VENDOR_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or force:
            print(f"  Downloading {url}")
            _fetch(url, dest)
        else:
            print(f"  Already present: {rel_path}")


# ---------------------------------------------------------------------------
# Hatchling build hook
# ---------------------------------------------------------------------------


class CustomBuildHook(_BuildHookBase):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:  # type: ignore[override]
        print("Fetching vendor CSS/JS assets …")
        download_all()
        print("Vendor assets ready.")
