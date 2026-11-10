"""The numbers and tables of the results page (docs/current/*/RESULTS.md), from the committed measurements.

A page writes ``{{stop:key}}`` where a number or a table belongs; ``fill`` replaces it, so a sentence cannot drift from
the data. The sources are:

- results/experiments/stop_design/combined.json (scripts/summarize_stop_experiments.py): both experiments, paired.
- results/experiments/stop_design_v1/real_data_comparison.json (scripts/compare_with_real_data.py): what the
  simulation produces that field studies also measured.

Occupancies are not fixed anywhere. The simulation gives, per pair of runs with the same cars, a = how much longer the
bus's trip is with the bay (s) and b = how much longer all cars' trips together are (vehicle-s), so for any choice

    ΔPT = bus passengers · a + people per car · b      (below zero: the bay moves people faster)

Tables that need one car occupancy use ``PC`` (1.35, the middle of the Israeli range 1.2 to 1.5) and say so.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache

from busmerge.paths import REPO_ROOT

COMBINED = REPO_ROOT / "results" / "experiments" / "stop_design" / "combined.json"
FIELD = REPO_ROOT / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
PC = 1.35                      # people per car where the page needs one value (the middle of 1.2 to 1.5)
CAP = 100                      # tipping points above this many bus passengers are shown as ">100"
EXAMPLE_LOADS = (10, 20, 40, 60)
PAIRS = ((3, 6), (6, 10), (10, 15), (15, 20), (20, 30), (30, 45))
Z = 1.96

TEXT = {
    "en": {"s": "s", "dwell": "Dwell time", "inflow": "inflow (cars/s)", "lane_always": "lane always",
           "bay_always": "bay always", "bus": "Bus, bay − lane (s)", "cars": "All cars, bay − lane (vehicle-min)",
           "be": "Dwell time / inflow (cars/s)", "pair": "Stop in lane / in bay", "load": "Bus passengers",
           "bay": "bay wins", "lane": "lane wins", "tie": "undecided", "and": "and", "at": "at", "from": "from",
           "every": "at every inflow", "cars_s": "cars/s"},
    "he": {"s": "שנ'", "dwell": "זמן עצירה", "inflow": "תנועה (מכוניות/שנ')", "lane_always": "נתיב תמיד",
           "bay_always": "מפרץ תמיד", "bus": "האוטובוס, מפרץ − נתיב (שנ')", "cars": "כל המכוניות, מפרץ − נתיב (דקות-רכב)",
           "be": "זמן עצירה / תנועה (מכוניות/שנ')", "pair": "עצירה בנתיב / במפרץ", "load": "נוסעים באוטובוס",
           "bay": "המפרץ מנצח", "lane": "הנתיב מנצח", "tie": "ללא הכרעה", "and": "ו-", "at": "ב-", "from": "מ-",
           "every": "בכל עוצמת תנועה", "cars_s": "מכוניות/שנ'"},
}


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(COMBINED.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def field() -> dict:
    return json.loads(FIELD.read_text(encoding="utf-8"))


def pair(rate: float, lane: int, bay: int) -> list:
    """[n, mean a, mean b, var a, var b, cov ab] for a lane stop of ``lane`` s and a bay stop of ``bay`` s."""
    return data()["pairs"][f"{rate:g}"][str(lane)][str(bay)]


def verdict(pc: float, pb: float, v: list) -> str:
    """Who wins on mean ΔPT with its 95% interval (normal approximation): 'bay', 'lane' or 'tie'."""
    n, a, b, va, vb, c = v
    mean = pb * a + pc * b
    se = Z * math.sqrt(max(pb * pb * va + pc * pc * vb + 2 * pb * pc * c, 0.0) / n)
    return "bay" if mean + se < 0 else "lane" if mean - se > 0 else "tie"


def tipping_bus_load(v: list, pc: float = PC) -> float | str:
    """The number of bus passengers at which the two designs tie on mean person-time.

    With the bay costing the bus (a > 0) and saving the cars (b < 0) the bay wins below it. 'lane always': the bay
    costs both (a > 0, b >= 0). 'bay always': it saves both."""
    _, a, b, *_ = v
    if a > 0 and b < 0:
        return -pc * b / a
    if a > 0:
        return "lane_always"
    if b <= 0:
        return "bay_always"
    return pc * b / -a                              # the bay costs the cars and saves the bus: it wins ABOVE this


def _r(x: float) -> int:
    return int(math.floor(x + 0.5))


def _minus(s: str) -> str:
    return s.replace("-", "−")


def _show_load(v, t: dict) -> str:
    if isinstance(v, str):
        return t[v]
    return f">{CAP}" if v > CAP else str(_r(v))


def _grid(cell, head: str, lang: str) -> str:
    d, t = data(), TEXT[lang]
    lines = [f"| {head} | " + " | ".join(f"{r:g}" for r in d["rates"]) + " |", "|---|" + "---|" * len(d["rates"])]
    for dw in sorted(d["dwells"], reverse=True):
        lines.append(f"| **{dw} {t['s']}** | " + " | ".join(cell(r, dw) for r in d["rates"]) + " |")
    return "\n".join(lines)


def table_bus(lang: str) -> str:
    return _grid(lambda r, dw: _minus(f"{pair(r, dw, dw)[1]:+.1f}"), TEXT[lang]["bus"], lang)


def table_cars(lang: str) -> str:
    return _grid(lambda r, dw: _minus(f"{pair(r, dw, dw)[2] / 60:+.1f}"), TEXT[lang]["cars"], lang)


def table_tipping(lang: str) -> str:
    t = TEXT[lang]
    return _grid(lambda r, dw: _show_load(tipping_bus_load(pair(r, dw, dw)), t), t["be"], lang)


def table_pairs(lang: str) -> str:
    d, t = data(), TEXT[lang]
    lines = [f"| {t['pair']} | " + " | ".join(f"{r:g}" for r in d["rates"]) + " |", "|---|" + "---|" * len(d["rates"])]
    for lane, bay in PAIRS:
        cells = [_show_load(tipping_bus_load(pair(r, lane, bay)), t) for r in d["rates"]]
        lines.append(f"| **{lane} / {bay} {t['s']}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def example_counts(pb: float, pc: float = PC) -> dict:
    d = data()
    out = {"bay": 0, "lane": 0, "tie": 0}
    for r in d["rates"]:
        for dw in d["dwells"]:
            out[verdict(pc, pb, pair(r, dw, dw))] += 1
    return out


def table_examples(lang: str) -> str:
    t = TEXT[lang]
    lines = [f"| {t['load']} | {t['bay']} | {t['lane']} | {t['tie']} |", "|---|---|---|---|"]
    for pb in EXAMPLE_LOADS:
        c = example_counts(pb)
        lines.append(f"| **{pb}** | {c['bay']} | {c['lane']} | {c['tie']} |")
    return "\n".join(lines)


def _equal_cells() -> list[tuple[float, int, list]]:
    d = data()
    return [(r, dw, pair(r, dw, dw)) for r in d["rates"] for dw in d["dwells"]]


def lane_always_dwells() -> list[int]:
    """The dwell times at which the bay costs both the bus and the cars at every inflow."""
    d = data()
    return [dw for dw in d["dwells"] if all(tipping_bus_load(pair(r, dw, dw)) == "lane_always" for r in d["rates"])]


def _slower_cars_text(lang: str) -> str:
    """Where the bay makes the cars slower (b > 0), dwell by dwell, in words."""
    d, t = data(), TEXT[lang]
    parts = []
    for dw in d["dwells"]:
        rates = [r for r in d["rates"] if pair(r, dw, dw)[2] > 0]
        if not rates:
            continue
        if len(rates) == len(d["rates"]):
            where = t["every"]
        elif rates == d["rates"][-len(rates):]:
            where = f"{t['from']}{rates[0]:g} {t['cars_s']}" if lang == "he" else f"from {rates[0]:g} cars/s"
        else:
            where = ", ".join(f"{r:g}" for r in rates) + f" {t['cars_s']}"
        parts.append((dw, where))
    full = [dw for dw, w in parts if w == t["every"]]
    rest = [(dw, w) for dw, w in parts if w != t["every"]]
    if lang == "he":
        s = f"בעצירה של {max(full)} שניות ומטה {t['every']}" if full else ""
        s += "".join(f", ובעצירה של {dw} שניות {w}" for dw, w in rest)
    else:
        s = f"for stops of {max(full)} s or shorter {t['every']}" if full else ""
        s += "".join(f", and at {dw} s {w}" for dw, w in rest)
    return s


def facts(lang: str) -> dict[str, str]:
    d, f, t = data(), field(), TEXT[lang]
    eq = _equal_cells()
    a_all = [v[1] for _, _, v in eq]
    cells = [c for r in d["cells"].values() for c in r.values()]
    queues = [c["lane_queue_max_cars_mean"] for c in cells]
    bay_runs = sum(c["bay_runs"] for c in cells)
    da = max(abs(d["cells"][f"{r:g}"][str(dw)]["a_without_contact"] - v[1]) for r, dw, v in eq)
    db = max(abs(d["cells"][f"{r:g}"][str(dw)]["b_without_contact"] - v[2]) for r, dw, v in eq)
    la = lane_always_dwells()
    tip = {(r, dw): tipping_bus_load(v) for r, dw, v in eq}
    mt = f["merge_time"]["all_bay_runs"]
    per_car_15 = [f["lane_minus_bay_s_per_car"]["15"][k] for k in ("0.1", "0.3", "0.5")]
    pairs_n = sorted({v[0] for _, _, v in eq})
    prov = {p["experiment"]: p for p in d["provenance"]}
    fmt_list = (lambda xs: ", ".join(str(x) for x in xs[:-1]) + (" ו-" if lang == "he" else " and ") + str(xs[-1]))
    out = {
        "runs": f"{d['runs']:,}", "runs_v1": f"{prov['stop_design_v1']['runs_stored']:,}",
        "runs_v2": f"{prov['stop_design_v2']['runs_stored']:,}", "commit_v1": prov["stop_design_v1"]["commit"],
        "commit_v2": prov["stop_design_v2"]["commit"].split("+")[0],
        "date_v1": prov["stop_design_v1"]["date"][:10], "date_v2": prov["stop_design_v2"]["date"][:10],
        "cells": str(len(eq)), "dwells": fmt_list(d["dwells"]), "pairs_min": str(pairs_n[0]), "pairs_max": str(pairs_n[-1]),
        "a_min": f"{min(a_all):.1f}", "a_max": f"{max(a_all):.1f}", "a_mean": f"{sum(a_all) / len(a_all):.1f}",
        "q_min": f"{min(queues):.0f}", "q_max": f"{max(queues):.0f}",
        "q_max_single": str(max(c["lane_queue_max_cars_max"] for c in cells)),
        "entry_wait_max": f"{max(c['lane_entry_wait_max_s_mean'] for c in cells):.0f}",
        "b_big": f"{-pair(0.5, 45, 45)[2] / 60:.0f}", "b_stop0": f"{pair(0.5, 0, 0)[2] / 60:.0f}",
        "slower_cars": _slower_cars_text(lang),
        "lane_always_max": str(max(la)) if la else "–",
        "contact_pct": f"{100 * sum(c['bay_contact_runs'] for c in cells) / bay_runs:.1f}",
        "offroad_pct": f"{100 * sum(c['bay_off_road_runs'] for c in cells) / bay_runs:.1f}",
        "bay_runs": f"{bay_runs:,}", "da_max": f"{da:.1f}", "db_max": f"{db:.0f}",
        "censored": str(sum(c["censored_runs"] for c in cells)),
        "mt_mean": f"{mt['mean']:.1f}", "mt_max": f"{mt['max']:.1f}", "mt_n": f"{mt['n']:,}",
        "mt_n30": str(mt["n_over_30s"]), "mt_p99": f"{mt['p99']:.1f}",
        "flow_h": f"{f['entry_flow']['flow_veh_per_h']:,}", "flow_s": f"{f['entry_flow']['flow_cars_per_s']:.2f}",
        "per_car_15_lo": f"{min(per_car_15):.0f}", "per_car_15_hi": f"{max(per_car_15):.0f}",
        "entry_sim": _minus(f"{d['geometry']['entry_s']:.2f}"), "geom_seeds": str(d["geometry"]["seeds"]),
        "dev_lane": f"{d['geometry']['dev_lane_m']:.1f}", "dev_bay": f"{d['geometry']['dev_bay_m']:.1f}",
        "gap_lane": f"{d['geometry']['gap_lane_m']:.2f}", "gap_bay": f"{d['geometry']['gap_bay_m']:.2f}",
        "pc": f"{PC:g}",
        "table_bus": table_bus(lang), "table_cars": table_cars(lang), "table_tipping": table_tipping(lang),
        "table_pairs": table_pairs(lang), "table_examples": table_examples(lang),
    }
    for (r, dw), v in tip.items():
        out[f"tip_{r:g}_{dw}"] = _show_load(v, t)
    for lane, bay in PAIRS:
        for r in d["rates"]:
            out[f"tip_{r:g}_{lane}_{bay}"] = _show_load(tipping_bus_load(pair(r, lane, bay)), t)
    for pb in EXAMPLE_LOADS:
        for k, n in example_counts(pb).items():
            out[f"n{pb}_{k}"] = str(n)
    return out


_TOKEN = re.compile(r"\{\{stop:([a-z0-9_.]+)\}\}")


def fill(text: str, lang: str) -> str:
    """Replace every ``{{stop:key}}``; an unknown key is an error, not a blank."""
    if "{{stop:" not in text:
        return text
    values = facts(lang)

    def repl(m: re.Match) -> str:
        if m.group(1) not in values:
            raise KeyError(f"unknown results token {{{{stop:{m.group(1)}}}}}")
        return values[m.group(1)]
    return _TOKEN.sub(repl, text)
