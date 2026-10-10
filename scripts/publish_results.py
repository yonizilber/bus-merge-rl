#!/usr/bin/env python3
"""Regenerate every published results block (README, SPECS, case study) from results/.

    python scripts/publish_results.py           # rewrite the blocks
    python scripts/publish_results.py --check   # exit 1 if any block differs from the measurements
"""
import argparse
import sys

from busmerge.results import refresh

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    stale = refresh(check=ap.parse_args().check)
    for line in stale:
        print(line)
    sys.exit(1 if stale and "--check" in sys.argv else 0)
