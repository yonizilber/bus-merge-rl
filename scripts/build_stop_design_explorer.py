#!/usr/bin/env python3
"""Build the interactive explorer: which stop design is better under the conditions a visitor picks.

    python scripts/build_stop_design_explorer.py

Reads the stored runs of the stop-design experiments (outputs/experiments/stop_design_v1: dwell 10 to 45 s, 300 seeds;
stop_design_v2: dwell 0 to 6 s, 150 seeds) and the measured arrival geometry (results/experiments/stop_design_v2/
stop_geometry.json), and writes docs/tools/stop_design_explorer.he.html. For every traffic rate and every pairing of a
lane dwell time with a bay dwell time (the same seed gives the same cars in both designs) the page carries what is
needed to rebuild the paired person-time difference for ANY occupancies in the browser:

    ΔPT = pax_bus · a + pax_car · b,   a = ΔT_bus (bay − lane, s),   b = ΔT_cars (bay − lane, s, summed over cars)

with the means of a and b and their variances and covariance over the seeds (so the 95% interval is exact for the
mean, by the normal approximation, for any occupancy). Between the grid points the page interpolates linearly; it never
extrapolates. The sentences of the written summary are computed here from the same table (``summary_facts``) so that a
number in the text cannot drift from the data. The field reference values are written in the template by hand, with
their sources.
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import analyze_stop_experiment as an  # noqa: E402
from busmerge.experiments.stop_design import paired_difference  # noqa: E402

OUTPUTS = REPO / "outputs" / "experiments"
EXPERIMENTS = ("stop_design_v1", "stop_design_v2")
GEOMETRY = REPO / "results" / "experiments" / "stop_design_v2" / "stop_geometry.json"
TEMPLATE = REPO / "scripts" / "stop_design_explorer_template.html"
OUT = REPO / "docs" / "tools" / "stop_design_explorer.he.html"
HEAD = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')
RATES = (0.1, 0.2, 0.3, 0.4, 0.5)
PC_DEFAULT, PB_DEFAULT = 1.35, 20.0       # the page's default occupancies (the middle of the Israeli range, a rough bus)


def load_runs() -> tuple[pd.DataFrame, list[dict]]:
    runs, provenance = [], []
    for name in EXPERIMENTS:
        r, _ = an.load(OUTPUTS / name)
        runs.append(r)
        p = json.loads((OUTPUTS / name / "provenance.json").read_text(encoding="utf-8"))
        provenance.append({k: p[k] for k in ("experiment", "commit", "brain_version", "date", "runs_stored")})
    return pd.concat(runs, ignore_index=True), provenance


def pairing_table(runs: pd.DataFrame, dwells: list[int]) -> dict:
    """{rate: {dwell_lane: {dwell_bay: [n, mean a, mean b, var a, var b, cov ab]}}} over the common seeds."""
    table: dict = {}
    for lane in dwells:
        for bay in dwells:
            m = paired_difference(runs, 1.0, 1.0, dwell_lane=lane, dwell_bay=bay)
            m = m.assign(a=m["bus_travel_time_s_b"] - m["bus_travel_time_s_a"],
                         b=m["cars_travel_time_s_b"] - m["cars_travel_time_s_a"])
            for rate, g in m.groupby("traffic_rate"):
                cov = np.cov(g["a"], g["b"], ddof=1)
                table.setdefault(f"{rate:g}", {}).setdefault(str(lane), {})[str(bay)] = [
                    int(len(g)), round(float(g["a"].mean()), 4), round(float(g["b"].mean()), 4),
                    round(float(cov[0, 0]), 4), round(float(cov[1, 1]), 4), round(float(cov[0, 1]), 4)]
    return table


def verdict(pc: float, pb: float, v: list) -> tuple[str, float]:
    n, a, b, va, vb, c = v
    mean = pb * a + pc * b
    se = 1.96 * math.sqrt(max(pb * pb * va + pc * pc * vb + 2 * pb * pc * c, 0.0) / n)
    return ("bay" if mean + se < 0 else "lane" if mean - se > 0 else "tie"), mean


def geometry() -> dict:
    g = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    return {"entry_s": g["arrival_time_from_braking_s"]["bay_minus_lane_mean"], "seeds": g["seeds"],
            "dev_lane_m": g["distance_from_stop_pole_m"]["lane_mean"], "dev_bay_m": g["distance_from_stop_pole_m"]["bay_mean"],
            "gap_lane_m": g["gap_between_bus_side_and_pavement_edge_m"]["lane_mean"],
            "gap_bay_m": g["gap_between_bus_side_and_pavement_edge_m"]["bay_mean"]}


def summary_facts(table: dict, dwells: list[int]) -> dict:
    """The numbers the written summary quotes, from the table alone (equal dwell times, no geometry penalties)."""
    eq = {(r, d): table[f"{r:g}"][str(d)][str(d)] for r in RATES for d in dwells}
    a_all = [v[1] for v in eq.values()]
    counts = {"bay": 0, "lane": 0, "tie": 0}
    for v in eq.values():
        counts[verdict(PC_DEFAULT, PB_DEFAULT, v)[0]] += 1

    def break_even(rate, dwell):
        n, a, b, *_ = eq[(rate, dwell)]
        return -PC_DEFAULT * b / a if a * b < 0 else None
    lane_always = sorted((r, d) for (r, d), v in eq.items() if v[1] > 0 and v[2] > 0)
    return {"a_min": min(a_all), "a_max": max(a_all), "counts": counts, "cells": len(eq),
            "break_even": {f"{r:g}|{d}": break_even(r, d) for r in RATES for d in dwells}, "lane_always": lane_always,
            "b_big": eq[(0.5, dwells[-1])][2], "b_stop0": eq[(0.5, dwells[0])][2], "eq": eq}


def render_summary(facts: dict, dwells: list[int]) -> str:
    be = facts["break_even"]
    items = [
        f'<li><b>המחיר של המפרץ הוא כמה שניות של האוטובוס.</b> כשהאוטובוס יוצא ממפרץ הוא צריך למצוא רווח, ובניסוי זה הוסיף לו '
        f'<span class="num">{facts["a_min"]:.1f}</span> עד <span class="num">{facts["a_max"]:.1f}</span> שניות לנסיעה, בכל התנאים שנבדקו.</li>',
        f'<li><b>המחיר של העצירה בנתיב משלמות המכוניות שמאחור.</b> הוא גדל עם זמן העצירה ועם צפיפות התנועה, ובעצירה של '
        f'<span class="num">{dwells[-1]}</span> שניות ב-<span class="num">0.5</span> מכוניות לשנייה הוא מגיע לכ-'
        f'<span class="num">{-facts["b_big"] / 60:.0f}</span> דקות רכב בהרצה אחת.</li>',
        f'<li><b>עצירה קצרה מאוד (0 עד 3 שניות): הנתיב, בכל מספר נוסעים.</b> אין שם תור שהמפרץ חוסך, והוא רק מאט את המכוניות כשהאוטובוס חוזר לנתיב: '
        f'עד כ-<span class="num">{facts["b_stop0"] / 60:.0f}</span> דקות רכב בהרצה אחת ב-<span class="num">0.5</span> מכוניות לשנייה, בלי עצירה בכלל.</li>',
        f'<li><b>ככל שהאוטובוס ריק יותר, המפרץ משתלם יותר.</b> ההפסד של האוטובוס נמדד באנשים, והחיסכון של המכוניות לא תלוי בכמה אנשים '
        f'נסעו באוטובוס. נקודת האיזון (עם <span class="num">{PC_DEFAULT}</span> אנשים במכונית): בעצירה של <span class="num">15</span> שניות '
        f'ו-<span class="num">0.3</span> מכוניות לשנייה המפרץ עדיף כשבאוטובוס פחות מכ-<span class="num">{be["0.3|15"]:.0f}</span> נוסעים, ב-'
        f'<span class="num">0.5</span> פחות מכ-<span class="num">{be["0.5|15"]:.0f}</span>.</li>',
        f'<li><b>עם ההנחות הבסיסיות לישראל</b> (<span class="num">{PC_DEFAULT}</span> אנשים במכונית, <span class="num">{PB_DEFAULT:.0f}</span> '
        f'באוטובוס, בלי עונשי דיוק, ובזמן עצירה זהה בשני התכנונים), מתוך <span class="num">{facts["cells"]}</span> הצירופים של תנועה וזמן עצירה '
        f'המפרץ עדיף ב-<span class="num">{facts["counts"]["bay"]}</span>, הנתיב ב-<span class="num">{facts["counts"]["lane"]}</span> ו-'
        f'<span class="num">{facts["counts"]["tie"]}</span> ללא הכרעה.</li>',
    ]
    return "\n      ".join(items)


def main() -> None:
    runs, provenance = load_runs()
    dwells = sorted(int(d) for d in runs["dwell_s"].unique())
    table = pairing_table(runs, dwells)
    geom = geometry()
    facts = summary_facts(table, dwells)
    lane_q = runs[runs.scenario == "A"].groupby(["traffic_rate", "dwell_s"])["queue_max_cars"].mean()
    payload = {"rates": list(RATES), "dwells": dwells, "pairs": table, "provenance": provenance,
               "geometry": {"entry_s": geom["entry_s"], "dev_lane_m": geom["dev_lane_m"], "dev_bay_m": geom["dev_bay_m"],
                            "gap_lane_m": geom["gap_lane_m"], "gap_bay_m": geom["gap_bay_m"]},
               "lane_queue_cars": {f"{r:g}": {str(d): round(float(lane_q[(r, d)]), 1) for d in dwells} for r in RATES}}
    page = TEMPLATE.read_text(encoding="utf-8")
    assert "/*DATA*/null" in page
    tokens = {"[[runs]]": f"{int(runs.shape[0]):,}", "[[summary]]": render_summary(facts, dwells),
              "[[bus_cost_range]]": f'{facts["a_min"]:.1f}–{facts["a_max"]:.1f}', "[[entry_sim]]": f'{geom["entry_s"]:.1f}',
              "[[geom_seeds]]": str(geom["seeds"]), "[[dev_bay]]": f'{geom["dev_bay_m"]:.1f}', "[[dev_lane]]": f'{geom["dev_lane_m"]:.1f}',
              "[[gap_bay]]": f'{geom["gap_bay_m"]:.2f}', "[[gap_lane]]": f'{geom["gap_lane_m"]:.2f}'}
    for token, text in tokens.items():
        assert token in page, token
        page = page.replace(token, text)
    assert not re.search(r"\[\[[a-z_0-9]+\]\]", page), "a token was not filled"
    page = page.replace("/*DATA*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HEAD + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    print(f"written {OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB); dwell levels {dwells}")


if __name__ == "__main__":
    main()
