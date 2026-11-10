#!/usr/bin/env python3
"""Draw the figures of the field-data page (docs/current/*/FIELD_DATA.md), in English and Hebrew.

    python scripts/plot_field_comparison.py

The simulation's side comes from results/experiments/stop_design_v1/real_data_comparison.json (committed, written by
scripts/compare_with_real_data.py), so no raw runs are needed. The field values are quoted here by hand, each with its
source, as on the page. Every figure carries its own caption.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
FIELD = REPO / "results" / "experiments" / "stop_design_v1" / "real_data_comparison.json"
MEDIA = REPO / "docs" / "media"

# San Francisco: TCRP Web Document 19, appendix C, table C-6 (mean and maximum wait until the bus starts to move, s).
SF = [("site 2 (near the junction), off-peak", "אתר 2 (ליד הצומת), שעות רגילות", 7, 52),
      ("site 3 (after the junction), off-peak", "אתר 3 (אחרי הצומת), שעות רגילות", 4, 9),
      ("site 2, peak", "אתר 2, שעות עומס", 13, 29),
      ("site 3, peak", "אתר 3, שעות עומס", 4, 12)]
# Florida: Lin et al. (2013), from turning on the signal until the bus finishes accelerating (a different definition).
FL = [("a car made way", "מכונית פינתה דרך", 29), ("all merges", "כל ההשתלבויות", 36), ("waited for a gap", "חיכה לפער", 39)]
COLOURS = {"sim": "#3a4fb6", "field": "#0c7a69", "bay": "#2b6cb0", "lane": "#c2571a", "tie": "#7b8791"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["font.family"] = "DejaVu Sans"      # has Hebrew; matplotlib 3.11 orders right-to-left text itself
    return plt


def _caption(fig, text: str, lang: str, width: int = 112) -> None:
    lines = "\n".join(textwrap.wrap(text, width=width))
    if lang == "he":
        fig.text(0.99, 0.01, lines, ha="right", va="bottom", fontsize=8.5)
    else:
        fig.text(0.01, 0.01, lines, ha="left", va="bottom", fontsize=8.5)


def merge_figure(d: dict, lang: str) -> Path:
    plt, he = _plt(), lang == "he"
    m = d["merge_time"]["all_bay_runs"]
    rows = [((f"הסימולציה ({m['n']:,} הרצות מפרץ)" if he else f"simulation ({m['n']:,} bay runs)"), "sim", m["mean"], m["max"], m)]
    rows += [((f"סן פרנסיסקו, {h}" if he else f"San Francisco, {e}"), "field", mean, mx, None) for e, h, mean, mx in SF]
    rows += [((f"פלורידה, {h} (הגדרה אחרת)" if he else f"Florida, {e} (other definition)"), "diamond", mean, None, None) for e, h, mean in FL]
    fig, ax = plt.subplots(figsize=(9, 6.4))
    fig.subplots_adjust(left=0.36, right=0.97, bottom=0.27, top=0.93)
    for i, (name, kind, mean, mx, stats) in enumerate(rows):
        y = len(rows) - 1 - i
        col = COLOURS["sim" if kind == "sim" else "field"]
        if mx is not None:
            ax.plot([0, mx], [y, y], color=col, lw=1.3, alpha=0.7)
            ax.plot([mx, mx], [y - 0.15, y + 0.15], color=col, lw=1.3)
        if stats:
            ax.plot([stats["median"], stats["p90"]], [y, y], color=col, lw=7, solid_capstyle="round", alpha=0.85)
        ax.plot([mean], [y], marker="D" if kind == "diamond" else "o", ms=8, color=col, mec="white")
        ax.text(mean, y + 0.28, f"{mean:g}", ha="center", fontsize=8, color="#55646f")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=9)
    ax.set_xlim(0, 60)
    ax.set_xlabel("שניות" if he else "seconds")
    ax.set_title("כמה זמן לוקח לאוטובוס לצאת מהמפרץ" if he else "How long the bus takes to leave the bay")
    ax.grid(axis="x", alpha=0.3)
    cap = ("זמן ההשתלבות בשניות, מקור אחד בכל שורה. עיגול: ממוצע. בסימולציה הפס העבה הוא מהחציון עד אחוזון 90. קו דק: עד המקסימום "
           "שנצפה. בסימולציה הזמן נמדד מסוף העלייה עד השתלבות מלאה; בסן פרנסיסקו עד שהאוטובוס מתחיל לנוע, כך שאצלנו הוא כולל "
           "יותר. מעוין: פלורידה, שם נמדד מהפעלת האיתות עד סוף ההאצה, ולכן רק סדר גודל. בשטח יש המתנות ארוכות שכמעט אין בסימולציה."
           if he else
           "Merge time in seconds, one source per row. Dot: mean. For the simulation the thick bar runs from the median to the "
           "90th percentile. Thin line: up to the longest observed. The simulation times from the end of boarding to a complete "
           "merge; San Francisco until the bus starts to move, so ours includes more. Diamond: Florida, timed from the turn "
           "signal to the end of acceleration, so an order of magnitude only. The field has long waits that the simulation "
           "almost never produces.")
    _caption(fig, cap, lang)
    out = MEDIA / f"field_merge_time.{lang}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def queue_figure(d: dict, lang: str) -> Path:
    plt, he = _plt(), lang == "he"
    q, dwells = d["lane_queue"]["mean_max_queue_cars"], d["dwells_s"]
    fig, ax = plt.subplots(figsize=(8.5, 5.8))
    fig.subplots_adjust(bottom=0.30, top=0.92)
    ax.axhspan(1, 3, color=COLOURS["field"], alpha=0.18, label="סן פרנסיסקו: ממוצע 1 עד 3" if he else "San Francisco: mean 1 to 3")
    ax.axhline(6, color=COLOURS["field"], ls="--", lw=1.3, label="סן פרנסיסקו: מקסימום 6" if he else "San Francisco: maximum 6")
    for rate, alpha in (("0.1", 0.45), ("0.3", 0.7), ("0.5", 1.0)):
        ax.plot(dwells, [q[str(dw)][rate] for dw in dwells], marker="o", color=COLOURS["sim"], alpha=alpha,
                label=(f"הסימולציה, {rate} מכוניות לשנייה" if he else f"simulation, {rate} cars/s"))
    ax.set_xlabel("זמן העצירה בשניות" if he else "stop time (s)")
    ax.set_ylabel("מכוניות בתור" if he else "cars in the queue")
    ax.set_title("התור מאחורי אוטובוס שעוצר בנתיב" if he else "The queue behind a bus stopped in the lane")
    ax.set_xlim(0, max(dwells))
    ax.set_ylim(0, 24)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    cap = ("מספר המכוניות שעומדות מאחורי האוטובוס בשיא העצירה, לפי זמן העצירה. הקווים: ממוצע על זוגות הרצות בסימולציה, בשלוש "
           "עוצמות תנועה. הרצועה הירוקה: התור הממוצע שנצפה בסן פרנסיסקו בשעות העומס, והקו המקווקו: המקסימום שנצפה שם. בסן "
           "פרנסיסקו ארבעה נתיבים והנהגים עוקפים; בסימולציה נתיב אחד בלי עקיפות. כל נקודה מעל הקו המקווקו היא תור ארוך מכל מה שנצפה שם."
           if he else
           "The number of cars standing behind the bus at the peak of its stop, by stop time. Lines: means over paired runs in "
           "the simulation, at three traffic inflows. Green band: the mean queue observed in San Francisco at peak hours; dashed "
           "line: the longest observed there. San Francisco has four lanes and drivers overtake; the simulation has one lane and "
           "no overtaking. Every point above the dashed line is a queue longer than any observed there.")
    _caption(fig, cap, lang, width=108)
    out = MEDIA / f"field_queue.{lang}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def verdict_figure(d: dict, lang: str) -> Path:
    from busmerge.stop_results import OCCUPANCY_LABELS
    plt, he = _plt(), lang == "he"
    from matplotlib.colors import ListedColormap
    rates, dwells = ["0.1", "0.2", "0.3", "0.4", "0.5"], [str(x) for x in d["dwells_s"]]
    keys = list(OCCUPANCY_LABELS)
    code = {"bay": 0, "lane": 1, "tie": 2}
    cmap = ListedColormap([COLOURS["bay"], COLOURS["lane"], COLOURS["tie"]])
    fig, axes = plt.subplots(1, len(keys), figsize=(13, 5.4))
    fig.subplots_adjust(left=0.05, right=0.99, bottom=0.33, top=0.80, wspace=0.25)
    word = {"bay": "מפרץ", "lane": "נתיב", "tie": "שווה"} if he else {"bay": "bay", "lane": "lane", "tie": "tie"}
    for ax, k in zip(axes, keys):
        grid = d["verdict_by_occupancy"][k]["grid"]
        z = [[code[grid[dw][r]] for r in rates] for dw in reversed(dwells)]
        ax.imshow(z, cmap=cmap, vmin=0, vmax=2, aspect="auto")
        for i, dw in enumerate(reversed(dwells)):
            for j, r in enumerate(rates):
                ax.text(j, i, word[grid[dw][r]], ha="center", va="center", fontsize=6.5, color="white")
        ax.set_xticks(range(len(rates)))
        ax.set_xticklabels(rates, fontsize=8)
        ax.set_yticks(range(len(dwells)))
        ax.set_yticklabels(list(reversed(dwells)), fontsize=8)
        label = OCCUPANCY_LABELS[k][1 if he else 0]
        ax.set_title("\n".join(textwrap.wrap(label, 24)), fontsize=8.5)
        v = d["verdict_by_occupancy"][k]
        ax.set_xlabel(f"{word['bay']} {v['bay']} · {word['lane']} {v['lane']} · {word['tie']} {v['tie']}", fontsize=8.5)
    fig.suptitle("מי מנצח בכל תא, לפי התפוסות" if he else "Who wins in each cell, by occupancy", fontsize=12)
    cap = ("כל לוח הוא צירוף אחד של אנשים במכונית ונוסעים באוטובוס. שורות: זמן העצירה בשניות, זהה בשני התכנונים ובלי עונשי דיוק "
           "(45 למעלה, 0 למטה). עמודות: תנועה במכוניות לשנייה. כחול: המפרץ מנצח; כתום: הנתיב מנצח; אפור: אין הכרעה, כי רווח הסמך "
           "של 95% לממוצע כולל אפס. מתחת לכל לוח: ספירת התאים. ככל שבאוטובוס פחות נוסעים, המפרץ מנצח ביותר תאים; הטווח הישראלי של "
           "אנשים במכונית כמעט לא משנה."
           if he else
           "Each panel is one pair of people per car and passengers on the bus. Rows: stop time in seconds, the same in both "
           "designs and without accuracy penalties (45 at the top, 0 at the bottom). Columns: traffic inflow in cars per second. "
           "Blue: the bay wins; orange: the lane wins; grey: undecided, because the 95% interval of the mean includes zero. Under "
           "each panel: the count of cells. The fewer passengers on the bus, the more cells the bay wins; the Israeli range of "
           "people per car hardly matters.")
    _caption(fig, cap, lang, width=170)
    out = MEDIA / f"field_verdicts.{lang}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def main() -> None:
    sys.path.insert(0, str(REPO))
    d = json.loads(FIELD.read_text(encoding="utf-8"))
    for lang in ("en", "he"):
        for fn in (merge_figure, queue_figure, verdict_figure):
            print("written", fn(d, lang).relative_to(REPO))


if __name__ == "__main__":
    main()
