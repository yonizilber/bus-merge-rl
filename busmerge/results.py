"""Measured results and every place they are published.

Each measurement in `results/` is a `scripts/verify_brain.py` run:
- `<name>.rows.json.gz`: one row per seed, as written by the script;
- `<name>.json`: where it came from (brain, seeds, traffic, code version, date) and its summary.

The summary is always computed from the rows (`summarize`). The README, SPECS and the case study
carry marked blocks generated from the summaries (`scripts/publish_results.py`), and the app renders
the same tables at run time. `tests/test_published_numbers.py` fails if any of them drifts from the
measurements.
"""
from __future__ import annotations

import gzip
import json
import statistics
from pathlib import Path

from busmerge.paths import REPO_ROOT

RESULTS_DIR = REPO_ROOT / "results"


def summarize(rows: list[dict]) -> dict:
    """Rates (% of runs) and times from verify_brain rows."""
    n = len(rows)

    def pct(k: int) -> float:
        return round(100.0 * k / n, 1)

    times = sorted(r["merge_total_s"] for r in rows if r.get("merge_total_s") is not None)
    near = [r["traffic"]["cars_near_bus_at_merge_start"] for r in rows if "traffic" in r]
    flow = [r["traffic"]["flow_veh_per_min"] for r in rows if "traffic" in r]
    near = [x for x in near if x == x]   # drop NaN
    flow = [x for x in flow if x == x]
    return {
        "n": n,
        "merged_pct": pct(sum(r["merge_outcome"] == "merged" for r in rows)),
        "contact_pct": pct(sum(r["merge_outcome"] == "collision" for r in rows)),
        "stuck_pct": pct(sum(r["merge_outcome"] == "stuck_waiting" for r in rows)),
        "strict_pct": pct(sum(r["strict_outcome"] == "merged" and not r["other_violations"] for r in rows)),
        "over_centre_pct": pct(sum(bool(r["over_centre_stage"]) for r in rows)),
        "off_road_pct": pct(sum(bool(r["off_road_stage"]) for r in rows)),
        "time_mean_s": round(statistics.mean(times), 1) if times else None,
        "time_p95_s": round(times[int(0.95 * (len(times) - 1))], 1) if times else None,
        "cars_near_bus": round(statistics.mean(near), 2) if near else None,
        "flow_per_min": round(statistics.mean(flow), 1) if flow else None,
    }


def save(name: str, rows: list[dict], meta: dict) -> Path:
    """Store a measurement: its rows and its provenance with the summary computed from them."""
    RESULTS_DIR.mkdir(exist_ok=True)
    with gzip.open(RESULTS_DIR / f"{name}.rows.json.gz", "wt") as f:
        json.dump(rows, f)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps({**meta, "name": name, "summary": summarize(rows)}, indent=1) + "\n")
    return path


def load(name: str) -> dict:
    return json.loads((RESULTS_DIR / f"{name}.json").read_text())


def load_rows(name: str) -> list[dict]:
    with gzip.open(RESULTS_DIR / f"{name}.rows.json.gz", "rt") as f:
        return json.load(f)


# ── What is published where ────────────────────────────────────────────────────────────────────

DEFAULT = "v13"
BRAINS = ["v13", "v11", "v10", "v9"]
STRESS = ["v13_rate0.2", "v13_rate0.4", "v13_rate0.6", "v13_rate0.8"]
CASE_STUDY = {"v11_old_steering": "v11, old steering", "v11": "v11, honest steering", "v13": "**v13**, honest steering"}


def _pct(x) -> str:
    return f"{x:.1f}%"


def _time(s: dict) -> str:
    return f"{s['time_mean_s']:.1f} / {s['time_p95_s']:.1f} s" if s["time_mean_s"] is not None else "–"


def brain_table(lang: str = "en") -> str:
    if lang == "he":
        head = ("| מוח | Seeds | השתלב | מגע | תקוע | הצלחה מחמירה | חצה קו אמצע | ירד מהכביש | זמן ממוצע / p95 |", " (ברירת מחדל)")
    else:
        head = ("| Brain | Seeds | Merged | Contact | Stuck | Strict | Over centre line | Off road | Mean / p95 time |",
                " (default)")
    lines = [head[0], "|---|---|---|---|---|---|---|---|---|"]
    for name in BRAINS:
        m = load(name)
        s = m["summary"]
        label = m["label"] + (head[1] if name == DEFAULT else "")
        time = _time(s).replace(" s", " שנ׳") if lang == "he" else _time(s)
        lines.append(f"| {label} | {m['seeds'][0]}-{m['seeds'][1]} | {_pct(s['merged_pct'])} | {_pct(s['contact_pct'])} | "
                     f"{_pct(s['stuck_pct'])} | {_pct(s['strict_pct'])} | {_pct(s['over_centre_pct'])} | "
                     f"{_pct(s['off_road_pct'])} | {time} |")
    return "\n".join(lines)


def stress_table() -> str:
    lines = ["| Inflow (cars/s) | Cars within 60 m when boarding ends | Flow past the stop (cars/min) | Merged | "
             "Contact | Stuck | Strict | Off road | Mean / p95 time |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name in STRESS:
        m = load(name)
        s = m["summary"]
        lines.append(f"| {m['traffic_rate']} | {s['cars_near_bus']} | {s['flow_per_min']} | {_pct(s['merged_pct'])} | "
                     f"{_pct(s['contact_pct'])} | {_pct(s['stuck_pct'])} | {_pct(s['strict_pct'])} | "
                     f"{_pct(s['off_road_pct'])} | {_time(s)} |")
    return "\n".join(lines)


def case_study_table() -> str:
    cols = [load(n) for n in CASE_STUDY]
    head = "| | " + " | ".join(CASE_STUDY.values()) + " |"
    rows = [("Merged (judged on traffic)", "merged_pct"), ("Contact with a car", "contact_pct"),
            ("Stuck", "stuck_pct"), ("Bus over the centre line", "over_centre_pct"),
            ("Bus off the road", "off_road_pct"), ("**Strict success**", "strict_pct")]
    lines = [head, "|---" * (len(cols) + 1) + "|"]
    for title, key in rows:
        lines.append(f"| {title} | " + " | ".join(_pct(m["summary"][key]) for m in cols) + " |")
    lines.append("| Mean / p95 time from end of boarding to merged | " + " | ".join(_time(m["summary"]) for m in cols) + " |")
    return "\n".join(lines)


def headline(lang: str = "en") -> str:
    m = load(DEFAULT)
    s = m["summary"]
    if lang == "he":
        centre = ("בלי לחצות אף פעם את קו האמצע" if s["over_centre_pct"] == 0
                  else f"וחוצה את קו האמצע ב-{_pct(s['over_centre_pct'])} מהן")
        return (f"הסוכן ברירת המחדל ({m['label']}) משתלב ב-{_pct(s['merged_pct'])} מתוך {s['n']:,} הרצות שלא נראו "
                f"באימון, {centre}; {_pct(s['strict_pct'])} מהן נקיות בכל בדיקה פיזיקלית "
                f"({_pct(s['contact_pct'])} מגע עם רכב, {_pct(s['off_road_pct'])} יציאה מהכביש).")
    centre = ("without ever crossing the centre line" if s["over_centre_pct"] == 0
              else f"crossing the centre line in {_pct(s['over_centre_pct'])} of them")
    return (f"The default agent ({m['label']}) merges in {_pct(s['merged_pct'])} of {s['n']:,} unseen runs "
            f"{centre}; {_pct(s['strict_pct'])} are clean by every physical check "
            f"({_pct(s['contact_pct'])} contact with a car, {_pct(s['off_road_pct'])} off the road).")


RENDERERS = {"headline": headline, "brain_table": brain_table, "stress_table": stress_table,
             "case_study_table": case_study_table,
             "headline_he": lambda: headline("he"), "brain_table_he": lambda: brain_table("he")}
PUBLISHED = {"README.md": ["headline", "brain_table"],
             "README.he.md": ["headline_he", "brain_table_he"],
             "docs/SPECS.md": ["brain_table", "stress_table"],
             "docs/CASE_STUDY_REWARD_HACKING.md": ["case_study_table"]}


def _block(name: str) -> str:
    return f"<!-- results:{name} (generated by scripts/publish_results.py; do not edit) -->\n{RENDERERS[name]()}\n<!-- /results:{name} -->"


def refresh(check: bool = False) -> list[str]:
    """Rewrite every published block from the measurements; with ``check`` only report stale ones."""
    stale = []
    for rel, names in PUBLISHED.items():
        path = REPO_ROOT / rel
        text = path.read_text()
        for name in names:
            start = text.find(f"<!-- results:{name} ")
            end = text.find(f"<!-- /results:{name} -->")
            if start < 0 or end < 0:
                stale.append(f"{rel}: block '{name}' missing")
                continue
            end += len(f"<!-- /results:{name} -->")
            new = _block(name)
            if text[start:end] != new:
                stale.append(f"{rel}: block '{name}' differs from the measurements")
                text = text[:start] + new + text[end:]
        if not check:
            path.write_text(text)
    return stale
