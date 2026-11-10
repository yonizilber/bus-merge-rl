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


def case_study_table(lang: str = "en") -> str:
    he = lang == "he"
    cols = [load(n) for n in CASE_STUDY]
    labels = ({"v11_old_steering": "v11, היגוי ישן", "v11": "v11, היגוי כנה", "v13": "**v13**, היגוי כנה"}
              if he else CASE_STUDY)
    head = "| | " + " | ".join(labels[n] for n in CASE_STUDY) + " |"
    rows = ([("השתלב (נשפט לפי התנועה)", "merged_pct"), ("מגע עם מכונית", "contact_pct"), ("תקוע", "stuck_pct"),
             ("האוטובוס חצה את קו האמצע", "over_centre_pct"), ("האוטובוס ירד מהכביש", "off_road_pct"),
             ("**הצלחה מחמירה**", "strict_pct")] if he else
            [("Merged (judged on traffic)", "merged_pct"), ("Contact with a car", "contact_pct"),
             ("Stuck", "stuck_pct"), ("Bus over the centre line", "over_centre_pct"),
             ("Bus off the road", "off_road_pct"), ("**Strict success**", "strict_pct")])
    lines = [head, "|---" * (len(cols) + 1) + "|"]
    for title, key in rows:
        lines.append(f"| {title} | " + " | ".join(_pct(m["summary"][key]) for m in cols) + " |")
    last = "זמן ממוצע / p95 מסוף העלאת הנוסעים עד השתלבות" if he else "Mean / p95 time from end of boarding to merged"
    unit = (lambda s: _time(s).replace(" s", " שנ׳")) if he else _time
    lines.append(f"| {last} | " + " | ".join(unit(m["summary"]) for m in cols) + " |")
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


# ── Semantic versions (docs version 3) ─────────────────────────────────────────────────────────
# Brains follow SemVer with major version 0 (no brain passes the acceptance gate yet): a new training
# run is a new minor version. The old "vN" names are kept on the files; see the changelog.
BRAIN_VERSION = {"v13": "0.13.0", "v11": "0.11.0", "v10": "0.10.0", "v9": "0.9.0", "v11_old_steering": "0.11.0"}


def _version_label(name: str, label: str, he: bool) -> str:
    version = BRAIN_VERSION[name]
    if label.endswith(" best"):
        version += " (הנקודה הטובה ביותר)" if he else " (best checkpoint)"
    return f"**{version}**" if name == DEFAULT else version


def brain_table_semver(lang: str = "en") -> str:
    he = lang == "he"
    head = ("| מוח | מצב | Seeds | השתלב | מגע | תקוע | הצלחה מחמירה | חצה קו אמצע | ירד מהכביש | זמן ממוצע / p95 |" if he else
            "| Brain | Status | Seeds | Merged | Contact | Stuck | Strict success | Over centre line | Off road | Mean / p95 time |")
    working = "✔ **עובד** (ברירת מחדל)" if he else "✔ **Working** (default)"
    superseded = "✘ הוחלף: נעצר באמצע הדרך" if he else "✘ Superseded: stops half way"
    lines = [head, "|---|---|---|---|---|---|---|---|---|---|"]
    for name in BRAINS:
        m = load(name)
        s = m["summary"]
        time = _time(s).replace(" s", " שנ'") if he else _time(s)
        lines.append(f"| {_version_label(name, m['label'], he)} | {working if name == DEFAULT else superseded} | "
                     f"{m['seeds'][0]}-{m['seeds'][1]} | {_pct(s['merged_pct'])} | {_pct(s['contact_pct'])} | "
                     f"{_pct(s['stuck_pct'])} | {_pct(s['strict_pct'])} | {_pct(s['over_centre_pct'])} | "
                     f"{_pct(s['off_road_pct'])} | {time} |")
    return "\n".join(lines)


def headline_semver(lang: str = "en") -> str:
    m = load(DEFAULT)
    s = m["summary"]
    v = BRAIN_VERSION[DEFAULT]
    if lang == "he":
        return (f"מוח {v}, ברירת המחדל והמוח היחיד שעובד, משתלב ב-{_pct(s['merged_pct'])} מתוך {s['n']:,} הרצות שלא נראו "
                f"באימון. הוא אף פעם לא נתקע ({_pct(s['stuck_pct'])}) ואף פעם לא חוצה את קו האמצע "
                f"({_pct(s['over_centre_pct'])}); {_pct(s['contact_pct'])} מההרצות מסתיימות במגע עם מכונית. "
                f"{_pct(s['strict_pct'])} מההרצות נקיות בכל בדיקה פיזיקלית.")
    return (f"Brain {v}, the default and the only working brain, merges in {_pct(s['merged_pct'])} of {s['n']:,} "
            f"unseen runs. It never gets stuck ({_pct(s['stuck_pct'])}) and never crosses the centre line "
            f"({_pct(s['over_centre_pct'])}); {_pct(s['contact_pct'])} of runs end in contact with a car. "
            f"{_pct(s['strict_pct'])} of runs are clean by every physical check.")


def case_study_table_semver(lang: str = "en") -> str:
    he = lang == "he"
    labels = ({"v11_old_steering": "0.11.0, היגוי ישן", "v11": "0.11.0, היגוי מתוקן", "v13": "**0.13.0**, היגוי מתוקן"} if he else
              {"v11_old_steering": "0.11.0, old steering", "v11": "0.11.0, corrected steering",
               "v13": "**0.13.0**, corrected steering"})
    table = case_study_table(lang).split("\n")
    table[0] = "| | " + " | ".join(labels[n] for n in CASE_STUDY) + " |"
    return "\n".join(table)


RENDERERS = {"headline": headline, "brain_table": brain_table, "stress_table": stress_table,
             "case_study_table": case_study_table,
             "headline_he": lambda: headline("he"), "brain_table_he": lambda: brain_table("he"),
             "case_study_table_he": lambda: case_study_table("he"),
             "brain_table_semver": brain_table_semver, "brain_table_semver_he": lambda: brain_table_semver("he"),
             "headline_semver": headline_semver, "headline_semver_he": lambda: headline_semver("he"),
             "case_study_table_semver": case_study_table_semver,
             "case_study_table_semver_he": lambda: case_study_table_semver("he")}
PUBLISHED = {"README.md": ["headline", "brain_table"],
             "README.he.md": ["headline_he", "brain_table_he"],
             "docs/archive/v2-next/en/README.md": ["headline", "brain_table"],
             "docs/archive/v2-next/en/CASE_STUDY.md": ["case_study_table"],
             "docs/archive/v2-next/he/README.md": ["headline_he", "brain_table_he"],
             "docs/archive/v2-next/he/CASE_STUDY.md": ["case_study_table_he"],
             "docs/current/en/README.md": ["headline_semver", "brain_table_semver"],
             "docs/current/en/CASE_STUDY.md": ["case_study_table_semver"],
             "docs/current/he/README.md": ["headline_semver_he", "brain_table_semver_he"],
             "docs/current/he/CASE_STUDY.md": ["case_study_table_semver_he"],
             "docs/reference/SPECS.md": ["brain_table", "stress_table"],
             "docs/reference/CASE_STUDY_REWARD_HACKING.md": ["case_study_table"]}


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
