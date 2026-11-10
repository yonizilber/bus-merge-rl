#!/usr/bin/env python3
"""Build the interactive explorer, in Hebrew and English: which stop design is better under the conditions a visitor picks.

    python scripts/build_stop_design_explorer.py

Reads results/experiments/stop_design/combined.json (written by scripts/summarize_stop_experiments.py from both
stop-design experiments) and results/experiments/stop_design_v1/real_data_comparison.json, and writes
docs/tools/stop_design_explorer.{he,en}.html. For every traffic rate and every pairing of a lane dwell time with a bay
dwell time (the same seed gives the same cars in both designs) the page carries what is needed to rebuild the paired
person-time difference for ANY occupancies in the browser:

    ΔPT = pax_bus · a + pax_car · b,   a = ΔT_bus (bay − lane, s),   b = ΔT_cars (bay − lane, s, summed over cars)

with the means of a and b and their variances and covariance over the seeds (so the 95% interval is exact for the
mean, by the normal approximation, for any occupancy). Between the grid points the page interpolates linearly; it never
extrapolates. The sentences of the written summary are computed here from the same table (``summary_facts``) so that a
number in the text cannot drift from the data. The field reference values are written in the markup by hand, with
their sources.

The page is assembled from scripts/explorer/: style.css and the two scripts (model.js, the calculation; page.js, the
drawing) are shared, and <lang>.html holds the words.
"""
import json
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "scripts" / "explorer"
COMBINED = REPO / "results" / "experiments" / "stop_design" / "combined.json"
FIELD = REPO / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
OUT = {lang: REPO / "docs" / "tools" / f"stop_design_explorer.{lang}.html" for lang in ("he", "en")}
RATES = (0.1, 0.2, 0.3, 0.4, 0.5)
PC_START, PB_START = 1.35, 20.0       # the page's starting occupancies (the middle of the Israeli car range, a rough bus)


def head(lang: str) -> str:
    return (f'<!doctype html>\n<html lang="{lang}" dir="{"rtl" if lang == "he" else "ltr"}">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n')


def verdict(pc: float, pb: float, v: list) -> tuple[str, float]:
    n, a, b, va, vb, c = v
    mean = pb * a + pc * b
    se = 1.96 * math.sqrt(max(pb * pb * va + pc * pc * vb + 2 * pb * pc * c, 0.0) / n)
    return ("bay" if mean + se < 0 else "lane" if mean - se > 0 else "tie"), mean


def summary_facts(table: dict, dwells: list[int]) -> dict:
    """The numbers the written summary quotes, from the table alone (equal dwell times, no geometry penalties)."""
    eq = {(r, d): table[f"{r:g}"][str(d)][str(d)] for r in RATES for d in dwells}
    a_all = [v[1] for v in eq.values()]
    counts = {"bay": 0, "lane": 0, "tie": 0}
    for v in eq.values():
        counts[verdict(PC_START, PB_START, v)[0]] += 1

    def break_even(rate, dwell):
        n, a, b, *_ = eq[(rate, dwell)]
        return -PC_START * b / a if a * b < 0 else None
    return {"a_min": min(a_all), "a_max": max(a_all), "counts": counts, "cells": len(eq),
            "break_even": {f"{r:g}|{d}": break_even(r, d) for r in RATES for d in dwells},
            "b_big": eq[(0.5, dwells[-1])][2], "b_stop0": eq[(0.5, dwells[0])][2], "eq": eq,
            # the longest stop at which the bay costs both the bus and the cars at every inflow (the lane wins at any load)
            "lane_always_max": max(d for d in dwells if all(eq[(r, d)][1] > 0 and eq[(r, d)][2] > 0 for r in RATES))}


def render_summary(facts: dict, dwells: list[int], lang: str) -> str:
    be, c = facts["break_even"], facts["counts"]
    n = lambda x: f'<span class="num">{x}</span>'          # noqa: E731
    a_min, a_max = f"{facts['a_min']:.1f}", f"{facts['a_max']:.1f}"
    b_big, b_stop0 = f"{-facts['b_big'] / 60:.0f}", f"{facts['b_stop0'] / 60:.0f}"
    be_03, be_05, pb = f"{be['0.3|15']:.0f}", f"{be['0.5|15']:.0f}", f"{PB_START:.0f}"
    la = facts["lane_always_max"]
    if lang == "he":
        items = [
            f'<li><b>המחיר של המפרץ הוא כמה שניות של האוטובוס.</b> כשהאוטובוס יוצא ממפרץ הוא צריך למצוא רווח, ובניסוי זה הוסיף לו '
            f'{n(a_min)} עד {n(a_max)} שניות לנסיעה, בכל התנאים שנבדקו.</li>',
            f'<li><b>המחיר של העצירה בנתיב משלמות המכוניות שמאחור.</b> הוא גדל עם זמן העצירה ועם צפיפות התנועה, ובעצירה של '
            f'{n(dwells[-1])} שניות ב-{n("0.5")} מכוניות לשנייה הוא מגיע לכ-{n(b_big)} דקות רכב בהרצה אחת.</li>',
            f'<li><b>עצירה קצרה (0 עד {la} שניות): הנתיב, בכל מספר נוסעים.</b> התור שהמפרץ חוסך קצר או לא קיים, והמפרץ מאט את המכוניות כשהאוטובוס חוזר לנתיב: '
            f'עד כ-{n(b_stop0)} דקות רכב בהרצה אחת ב-{n("0.5")} מכוניות לשנייה, בלי עצירה בכלל.</li>',
            f'<li><b>ככל שהאוטובוס ריק יותר, המפרץ משתלם יותר.</b> ההפסד של האוטובוס נמדד באנשים, והחיסכון של המכוניות לא תלוי בכמה אנשים '
            f'נסעו באוטובוס. נקודת האיזון (עם {n(PC_START)} אנשים במכונית): בעצירה של {n(15)} שניות '
            f'ו-{n("0.3")} מכוניות לשנייה המפרץ עדיף כשבאוטובוס פחות מכ-{n(be_03)} נוסעים, ב-'
            f'{n("0.5")} פחות מכ-{n(be_05)}.</li>',
            f'<li><b>דוגמה, עם ערכי ההתחלה של הכלי</b> ({n(PC_START)} אנשים במכונית, {n(pb)} '
            f'באוטובוס, בלי עונשי דיוק, ובזמן עצירה זהה בשני התכנונים; אלה לא נתונים, ואפשר לשנות אותם למעלה): מתוך {n(facts["cells"])} הצירופים של תנועה וזמן עצירה '
            f'המפרץ עדיף ב-{n(c["bay"])}, הנתיב ב-{n(c["lane"])} ו-{n(c["tie"])} ללא הכרעה.</li>',
        ]
    else:
        items = [
            f'<li><b>The bay\'s price is a few seconds of the bus\'s time.</b> Leaving a bay, the bus has to find a gap, and in the experiment '
            f'that added {n(a_min)} to {n(a_max)} s to its trip, in every condition tested.</li>',
            f'<li><b>The cars behind pay the price of the in-lane stop.</b> It grows with the stop time and the traffic, and with a stop of '
            f'{n(dwells[-1])} s at {n("0.5")} cars per second it reaches about {n(b_big)} vehicle-minutes in a single run.</li>',
            f'<li><b>A short stop (0 to {la} s): the lane, at any number of passengers.</b> The queue the bay would save is short or none, and the bay slows '
            f'the cars when the bus pulls back into the lane: up to about {n(b_stop0)} vehicle-minutes in a run at {n("0.5")} cars per second, with no stop at all.</li>',
            f'<li><b>The emptier the bus, the better the bay.</b> The bus\'s loss is counted in people, and the cars\' saving does not depend on how many '
            f'people rode the bus. The tipping point (with {n(PC_START)} people per car): with a {n(15)} s stop and {n("0.3")} cars per second the '
            f'bay is better when the bus carries fewer than about {n(be_03)} passengers; at {n("0.5")}, fewer than about {n(be_05)}.</li>',
            f'<li><b>An example, with the tool\'s starting values</b> ({n(PC_START)} people per car, {n(pb)} on the bus, no '
            f'accuracy penalties and the same stop time in both designs; these are not data, and you can change them above): of the '
            f'{n(facts["cells"])} combinations of traffic and stop time, the bay is better in {n(c["bay"])}, the lane in {n(c["lane"])}, and '
            f'{n(c["tie"])} are undecided.</li>',
        ]
    return "\n      ".join(items)


def build(lang: str, data: dict, field: dict) -> Path:
    dwells = data["dwells"]
    facts = summary_facts(data["pairs"], dwells)
    geom, mt = data["geometry"], field["merge_time"]["all_bay_runs"]
    payload = {k: data[k] for k in ("rates", "dwells", "pairs", "provenance", "lane_queue_cars")}
    payload["geometry"] = {k: geom[k] for k in ("entry_s", "dev_lane_m", "dev_bay_m", "gap_lane_m", "gap_bay_m")}
    page = (SRC / f"{lang}.html").read_text(encoding="utf-8")
    parts = {"/*STYLE*/": (SRC / "style.css").read_text(encoding="utf-8"), "/*MODEL*/": (SRC / "model.js").read_text(encoding="utf-8"),
             "/*PAGE*/": (SRC / "page.js").read_text(encoding="utf-8")}
    for mark, text in parts.items():
        assert page.count(mark) == 1, (lang, mark)
        page = page.replace(mark, text)
    tokens = {"[[runs]]": f"{data['runs']:,}", "[[summary]]": render_summary(facts, dwells, lang),
              "[[bus_cost_range]]": f'{facts["a_min"]:.1f}–{facts["a_max"]:.1f}',
              "[[entry_sim]]": f'{geom["entry_s"]:.2f}'.replace("-", "−"), "[[geom_seeds]]": str(geom["seeds"]),
              "[[dev_bay]]": f'{geom["dev_bay_m"]:.1f}', "[[dev_lane]]": f'{geom["dev_lane_m"]:.1f}',
              "[[gap_bay]]": f'{geom["gap_bay_m"]:.2f}', "[[gap_lane]]": f'{geom["gap_lane_m"]:.2f}',
              "[[mt_max]]": f'{mt["max"]:.1f}', "[[mt_n30]]": str(mt["n_over_30s"]), "[[mt_n]]": f'{mt["n"]:,}'}
    for token, text in tokens.items():
        assert token in page, (lang, token)
        page = page.replace(token, text)
    assert not re.search(r"\[\[[a-z_0-9]+\]\]", page), f"{lang}: a token was not filled"
    assert page.count("/*DATA*/null") == 1
    page = page.replace("/*DATA*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    out = OUT[lang]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head(lang) + page.replace("<main>", "</head>\n<body>\n<main>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    return out


def main() -> None:
    data = json.loads(COMBINED.read_text(encoding="utf-8"))
    field = json.loads(FIELD.read_text(encoding="utf-8"))
    for lang in OUT:
        out = build(lang, data, field)
        print(f"written {out.relative_to(REPO)} ({out.stat().st_size // 1024} KB); dwell levels {data['dwells']}")


if __name__ == "__main__":
    main()
