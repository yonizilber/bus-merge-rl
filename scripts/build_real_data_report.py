#!/usr/bin/env python3
"""Build the standalone Hebrew report that compares the simulation with published field data.

    python scripts/build_real_data_report.py

Reads scripts/real_data_report_template.html and results/experiments/stop_design_v1/real_data_comparison.json (the
simulation's side, written by scripts/compare_with_real_data.py) and writes docs/reports/REAL_DATA_COMPARISON.he.html:
one self-contained page (fonts come from Google Fonts when online) that opens in any browser. The field numbers and the
verdicts are written in the template by hand, each with its source; the simulation's numbers and the charts come from the
JSON. The documentation site copies it next to the results page.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "scripts" / "real_data_report_template.html"
DATA = REPO / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
OUT = REPO / "docs" / "reports" / "REAL_DATA_COMPARISON.he.html"
HEAD = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')


GEOMETRY = REPO / "results" / "experiments" / "stop_design_v2" / "stop_geometry.json"


def tokens(d: dict) -> dict:
    """The simulation's numbers quoted in the page's text, from the stored comparison and the measured geometry."""
    g = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    mt, bay, queue = d["merge_time"]["all_bay_runs"], d["bay_cost_s"], d["lane_queue"]["mean_max_queue_cars"]
    q = [v for row in queue.values() for v in row.values()]
    entry = g["arrival_time_from_braking_s"]["bay_minus_lane_mean"]
    runs = json.loads((REPO / "results" / "experiments" / "stop_design" / "combined.json").read_text(encoding="utf-8"))["runs"]
    return {"[[runs]]": f"{runs:,}", "[[mt_n30]]": str(mt["n_over_30s"]), "[[a_min]]": f"{bay['min']:.1f}", "[[a_max]]": f"{bay['max']:.1f}", "[[a_mean]]": f"{bay['mean']:.1f}",
            "[[mt_mean]]": f"{mt['mean']:.1f}", "[[mt_median]]": f"{mt['median']:.1f}", "[[mt_p90]]": f"{mt['p90']:.1f}",
            "[[mt_p99]]": f"{mt['p99']:.1f}", "[[mt_max]]": f"{mt['max']:.1f}", "[[mt_max_int]]": str(int(mt["max"])),
            "[[mt_over20]]": f"{100 * mt['share_over_20s']:.1f}%", "[[mt_n]]": f"{mt['n']:,}",
            "[[queue_min]]": f"{min(q):.1f}", "[[queue_max]]": f"{max(q):.0f}", "[[cells]]": str(5 * len(d["dwells_s"])),
            "[[entry_sim]]": f"{entry:.2f}".replace("-", "−"), "[[geom_seeds]]": str(g["seeds"]),
            "[[dev_lane]]": f"{g['distance_from_stop_pole_m']['lane_mean']:.1f}", "[[dev_bay]]": f"{g['distance_from_stop_pole_m']['bay_mean']:.1f}",
            "[[gap_lane]]": f"{g['gap_between_bus_side_and_pavement_edge_m']['lane_mean']:.2f}",
            "[[gap_bay]]": f"{g['gap_between_bus_side_and_pavement_edge_m']['bay_mean']:.2f}"}


def main() -> None:
    d = json.loads(DATA.read_text(encoding="utf-8"))
    used = {k: d[k] for k in ("lane_queue", "entry_flow", "verdict_by_occupancy", "lane_minus_bay_s_per_car")}
    used["merge_time"] = {"all_bay_runs": d["merge_time"]["all_bay_runs"]}
    used["dwells_s"] = d["dwells_s"]
    page = TEMPLATE.read_text(encoding="utf-8")
    assert "/*DATA*/null" in page
    for token, text in tokens(d).items():
        assert token in page, token
        page = page.replace(token, text)
    assert not re.search(r"\[\[[a-z_0-9]+\]\]", page), "a token was not filled"
    page = page.replace("/*DATA*/null", json.dumps(used, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEAD + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"written {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
