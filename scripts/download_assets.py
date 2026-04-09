"""Standalone helper: download vendor CSS/JS assets for local development.

Usage (from the project root):
    python scripts/download_assets.py          # skip already-present files
    python scripts/download_assets.py --force  # re-download everything
"""

import argparse
import sys
from pathlib import Path

# Allow importing from the project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from hatch_build import download_all

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download vendor CSS/JS assets.")
    parser.add_argument("--force", action="store_true", help="Re-download even if files already exist.")
    args = parser.parse_args()
    download_all(force=args.force)
