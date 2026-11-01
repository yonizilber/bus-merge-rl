#!/usr/bin/env python3
"""Build the standalone Hebrew report that compares the simulation with published field data.

    python scripts/build_real_data_report.py

Reads scripts/real_data_report_template.html and results/experiments/stop_design_v1/real_data_comparison.json (the
simulation's side, written by scripts/compare_with_real_data.py) and writes docs/reports/REAL_DATA_COMPARISON.he.html:
one self-contained page (fonts come from Google Fonts when online) that opens in any browser. The field numbers and the
verdicts are written in the template by hand, each with its source; the simulation's numbers and the charts come from the
JSON. The page is not linked from the documentation sites.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "scripts" / "real_data_report_template.html"
DATA = REPO / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
OUT = REPO / "docs" / "reports" / "REAL_DATA_COMPARISON.he.html"
HEAD = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')


def main() -> None:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    used = {k: d[k] for k in ("lane_queue", "entry_flow", "verdict_by_occupancy", "lane_minus_bay_s_per_car")}
    used["merge_time"] = {"all_bay_runs": d["merge_time"]["all_bay_runs"]}
    page = TEMPLATE.read_text(encoding="utf-8")
    assert "/*DATA*/null" in page
    page = page.replace("/*DATA*/null", json.dumps(used, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEAD + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"written {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
