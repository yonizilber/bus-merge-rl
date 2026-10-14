#!/usr/bin/env python3
"""Bilingual (English / Hebrew) HTML report of the whole test suite, built from a real pytest run.

    python scripts/build_test_report.py               # runs pytest (about 2 minutes), then writes the report
    python scripts/build_test_report.py --no-run      # rebuild the page from the last recorded run

The run is recorded in outputs/test_results.xml (JUnit) and outputs/test_run.json (when, on which commit
and environment, how long). The page is docs/html/TEST_REPORT.html, in the same site as the HTML docs
(scripts/build_docs_html.py). Every number on it comes from the recorded run; the per-file descriptions
below are the only hand-written part.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "outputs"
JUNIT = OUT_DIR / "test_results.xml"
RUN_META = OUT_DIR / "test_run.json"
NIGHTLY_DIR = OUT_DIR / "nightly"

# Category key -> (English, Hebrew), in display order.
CATEGORIES = {
    "physics": ("Physics and physical limits", "פיזיקה ומגבלות פיזיקליות"),
    "geometry": ("Geometry and single source of truth", "גיאומטריה ומקור אמת יחיד"),
    "traffic": ("Traffic and bus rules", "כללי התנועה והאוטובוס"),
    "agent": ("Agent behaviour", "התנהגות הסוכן"),
    "rl": ("RL pipeline and training", "צינור ה-RL והאימון"),
    "safety": ("Governor and safety shield", "ה-Governor ושכבת הבטיחות"),
    "harness": ("Measurement harness and published numbers", "רתמת המדידה והמספרים המפורסמים"),
    "app": ("App and documentation", "האפליקציה והתיעוד"),
    "nightly": ("Nightly gates", "בדיקות ליליות"),
    "legacy": ("Legacy tests from the original project", "בדיקות ישנות מהפרויקט המקורי"),
}

# Test file -> (category, what it guards in English, in Hebrew).
FILES = {
    "test_invariants.py": ("physics",
        "The physics checker catches every kind of impossible moment it claims to (braking, backward motion, "
        "position jumps, overlap, leaving the road, the centre line, heading), and real runs keep the "
        "properties they already have.",
        "בודק הפיזיקה מזהה כל סוג של רגע בלתי אפשרי שהוא מתיימר לזהות (בלימה, תנועה לאחור, קפיצת מיקום, "
        "חפיפה, יציאה מהכביש, הקו האמצעי, זווית כיוון), והרצות אמיתיות שומרות על התכונות שכבר יש להן."),
    "test_physics_limits.py": ("physics",
        "Every steering update in a real run respects the bicycle model and its limits; speed never jumps. "
        "Strict xfail: no vehicle mass (O17) and no brake actuation lag (O18).",
        "כל עדכון היגוי בהרצה אמיתית מכבד את מודל האופניים ואת מגבלותיו; המהירות אף פעם לא קופצת. "
        "xfail קשיח: אין מסה לרכב (O17) ואין השהיית בלמים (O18)."),
    "test_physics_any_policy.py": ("physics",
        "Physics stays possible whatever the merging policy does: random and full-extreme drivers produce "
        "no impossible moment.",
        "הפיזיקה נשארת אפשרית יהיה מה שיהיה המדיניות: נהג אקראי או קיצוני לא מייצר רגע בלתי אפשרי."),
    "test_safe_speed.py": ("physics",
        "Unit tests of the safe-speed law every follower obeys.",
        "בדיקות יחידה של חוק המהירות הבטוחה שכל רכב עוקב מציית לו."),
    "test_safe_speed_properties.py": ("physics",
        "Property-based tests of the safe-speed law over thousands of random cases (hypothesis). "
        "Strict xfail: a follower can get into its own minimum gap (O19).",
        "בדיקות מבוססות תכונות של חוק המהירות הבטוחה על אלפי מקרים אקראיים (hypothesis). "
        "xfail קשיח: רכב עוקב יכול לחדור למרווח המינימלי שלו (O19)."),
    "test_traffic_density.py": ("physics",
        "No impossible moment at any inflow (0.2-0.8 cars/s). Strict xfail: the car generator loses "
        "arrivals and delivers less than requested (O20).",
        "אין רגע בלתי אפשרי בשום צפיפות (0.2-0.8 מכוניות לשנייה). xfail קשיח: מחולל המכוניות מאבד "
        "הגעות ומספק פחות מהמבוקש (O20)."),
    "test_no_state_assignment.py": ("physics",
        "Speed and pose change only through the physics. Strict xfail documents the leftovers (O5, O7); a "
        "companion test pins them so a new one fails CI.",
        "מהירות ותנוחה משתנות רק דרך הפיזיקה. xfail קשיח מתעד את השאריות (O5, O7); בדיקה משלימה מקבעת "
        "אותן כך שחדשה תכשיל את ה-CI."),
    "test_bus_physics.py": ("physics",
        "The bus pulls into the bay along the drawn kerb and stops in it by physics alone: on the road, at "
        "its target, parallel.",
        "האוטובוס נכנס למפרץ לאורך השפה המצוירת ועוצר בו בכוח הפיזיקה בלבד: על הכביש, ביעד, במקביל."),
    "test_steering_controller.py": ("physics",
        "The steering reaches its target line without overshooting; the old overshooting law fails the "
        "same check.",
        "ההיגוי מגיע לקו היעד בלי לחרוג ממנו; החוק הישן, שחרג מהיעד, נכשל באותה בדיקה."),
    "test_trajectory_kinematics.py": ("physics",
        "No car teleports, no bus jitter, no backward snaps around the merging bus.",
        "אין שיגור (teleport) של מכוניות, אין רעידות של האוטובוס ואין קפיצות לאחור סביב האוטובוס המשתלב."),
    "test_road_edge_reference.py": ("geometry",
        "The road-edge check agrees with a brute-force 1 cm walk around the vehicle outline on 3,000 poses.",
        "בדיקת קצה הכביש מסכימה עם בדיקת כוח-גס שעוברת על קו המתאר בצעדים של 1 ס\"מ, על 3,000 תנוחות."),
    "test_single_source.py": ("geometry",
        "The bay coordinates and the merge threshold are defined in one place; a copied constant fails.",
        "קואורדינטות המפרץ וסף ההשתלבות מוגדרים במקום אחד בלבד; קבוע מועתק מכשיל את הבדיקה."),
    "test_idm_merge_yield.py": ("traffic",
        "Cars yield to a merging bus continuously and safely (IDM yield blend, queues, leaders).",
        "מכוניות מפנות מקום לאוטובוס המשתלב באופן רציף ובטוח (שילוב ה-yield ב-IDM, תורים, מובילים)."),
    "test_blinker_presence.py": ("traffic",
        "The bus's virtual blinker makes cars bleed off speed before it pulls out, without emergency "
        "braking.",
        "\"הוינקר\" הווירטואלי של האוטובוס גורם למכוניות להאט לפני היציאה, בלי בלימת חירום."),
    "test_yield_surprise_filter.py": ("traffic",
        "The yield factor changes at a bounded rate, so the switch to merging never causes a cliff brake.",
        "גורם ה-yield משתנה בקצב מוגבל, כך שהמעבר להשתלבות לא גורם לבלימה חדה."),
    "test_squeeze_hysteresis.py": ("traffic",
        "Cars do not flutter between reacting and squeezing at borderline urgency.",
        "מכוניות לא מהבהבות בין תגובה ל\"היצמדות\" כשהדחיפות על הגבול."),
    "test_bus_queue_follow.py": ("traffic",
        "Back in the lane, the bus follows the queue with the same IDM as cars and never overtakes.",
        "אחרי שחזר לנתיב, האוטובוס נוסע בתור עם אותו IDM של המכוניות ולעולם לא עוקף."),
    "test_queue_analytics.py": ("traffic",
        "The overtake and queue analytics shown in the app count correctly.",
        "ניתוח העקיפות והתורים שמוצג באפליקציה סופר נכון."),
    "test_follower_telemetry.py": ("traffic",
        "The car-behind-the-bus telemetry classifies braking from the real acceleration.",
        "הטלמטריה של המכונית שמאחורי האוטובוס מסווגת בלימה לפי התאוצה האמיתית."),
    "test_scenario_a_exit.py": ("traffic",
        "Scenario A (in-lane stop): the bus resumes after boarding and everyone leaves the road.",
        "תרחיש A (עצירה בנתיב): האוטובוס ממשיך אחרי העלאת נוסעים וכל הרכבים יוצאים מהכביש."),
    "test_brain_behaviour.py": ("agent",
        "The default brain in forced situations: merges within 15 s from every stop point and never stalls "
        "half way (v11's reward hack is caught). Strict xfail: contact with a car alongside (O2), exit kerb "
        "from the far end (O12).",
        "המוח ברירת המחדל במצבים כפויים: משתלב תוך 15 שניות מכל נקודת עצירה ולא נתקע באמצע הדרך "
        "(ה-reward hacking של v11 נתפס). xfail קשיח: מגע עם מכונית לצד המפרץ (O2), שפת היציאה מקצה "
        "המפרץ (O12)."),
    "test_policy_sanity.py": ("agent",
        "The shipped brains answer unusual and wildly out-of-range inputs with finite, deterministic, "
        "in-range actions.",
        "המוחות המצורפים עונים על קלטים חריגים ורחוקים מהטווח בפעולות סופיות, דטרמיניסטיות ובתוך הטווח."),
    "test_env_engine_parity.py": ("rl",
        "The training environment moves the world bit for bit like the app engine; a 1e-9 m/s drift is "
        "caught.",
        "סביבת האימון מזיזה את העולם ביט לביט כמו מנוע האפליקציה; סטייה של 1e-9 מ'/ש נתפסת."),
    "test_ppo_ratio.py": ("rl",
        "The PPO ratio is exactly 1 before the first update, even for actions beyond the limit (BUGS P17).",
        "יחס ה-PPO שווה בדיוק 1 לפני העדכון הראשון, גם לפעולות שמעבר לגבול (BUGS P17)."),
    "test_training_rollback.py": ("rl",
        "Training never resets itself to weights that were never better (BUGS P18).",
        "האימון לעולם לא מאפס את עצמו למשקלים שמעולם לא היו טובים יותר (BUGS P18)."),
    "test_training_smoke.py": ("rl",
        "Two training epochs run end to end, change the weights, and the app engine drives the result.",
        "שני epochs של אימון רצים מקצה לקצה, משנים את המשקלים, ומנוע האפליקציה נוהג עם התוצאה."),
    "test_training_consistency.py": ("rl",
        "Training starts from poses the app can produce, and PPO stores each action with its own "
        "probability.",
        "האימון מתחיל מתנוחות שהאפליקציה יכולה לייצר, ו-PPO שומר כל פעולה עם ההסתברות שלה."),
    "test_reward_terms.py": ("rl",
        "Each term of the training reward matches its formula.",
        "כל רכיב בתגמול האימון תואם את הנוסחה שלו."),
    "test_reward_ranking.py": ("rl",
        "The reward pays most for merging all the way and least for staying in the bay.",
        "התגמול משלם הכי הרבה על השתלבות מלאה והכי מעט על הישארות במפרץ."),
    "test_checkpoints.py": ("rl",
        "Checkpoints round-trip exactly; a wrong shape or a missing file is refused.",
        "checkpoints נשמרים ונטענים בדיוק; צורה שגויה או קובץ חסר נדחים."),
    "test_observation.py": ("rl",
        "One observation builder, with a pinned contract (sentinels, width, noise).",
        "בונה תצפיות יחיד, עם חוזה מקובע (ערכי ברירת מחדל, רוחב, רעש)."),
    "test_sensor_noise.py": ("rl",
        "The human perception noise model: distance-dependent, steady, unbiased on the bus's own state.",
        "מודל רעש התפיסה האנושי: תלוי מרחק, יציב, ואינו מעוות את המצב של האוטובוס עצמו."),
    "test_crash_judge.py": ("rl",
        "The training env's crash judge agrees with the acceptance gate.",
        "שופט ההתנגשות של סביבת האימון מסכים עם שער הקבלה."),
    "test_shield_penalty_scale_wired.py": ("rl",
        "The shield-penalty curriculum actually changes the training reward.",
        "תוכנית הלימוד של קנס ה-shield אכן משנה את תגמול האימון."),
    "test_governor_clear_road.py": ("safety",
        "The governor never vetoes a merge on a clear road.",
        "ה-governor לעולם לא מטיל וטו על השתלבות בכביש פנוי."),
    "test_governor_hold_shield_conflict.py": ("safety",
        "The safety shield never overrides a governor hold with a forward lunge.",
        "שכבת הבטיחות לעולם לא דורסת \"החזקה\" של ה-governor בזינוק קדימה."),
    "test_governor_shield_telemetry.py": ("safety",
        "Every governor and shield decision is visible in the telemetry.",
        "כל החלטה של ה-governor ושל שכבת הבטיחות נראית בטלמטריה."),
    "test_evaluation.py": ("harness",
        "The app, the smoke test and the validation demo judge an episode identically.",
        "האפליקציה, בדיקת העשן והדגמת האימות שופטות אפיזודה באופן זהה."),
    "test_published_numbers.py": ("harness",
        "Every published number is generated from a stored measurement, and a changed number is caught.",
        "כל מספר שמתפרסם נוצר ממדידה שמורה, ומספר ששונה נתפס."),
    "test_determinism.py": ("harness",
        "The same seed gives the same run, with perception noise on.",
        "אותו seed נותן אותה הרצה, גם עם רעש תפיסה."),
    "test_golden_run.py": ("harness",
        "Fixed-seed engine runs reproduce their stored fingerprints: any behaviour change is caught.",
        "הרצות מנוע ב-seed קבוע משחזרות את טביעות האצבע השמורות: כל שינוי התנהגות נתפס."),
    "test_env_golden.py": ("harness",
        "The training env reproduces its stored fingerprints.",
        "סביבת האימון משחזרת את טביעות האצבע השמורות שלה."),
    "test_app_headless.py": ("app",
        "The Streamlit app, run headlessly: loads, offers the existing brains, shows the published table and "
        "the outcome the harness measured for a fixed seed.",
        "אפליקציית Streamlit, בהרצה ללא ממשק: נטענת, מציעה את המוחות הקיימים, מציגה את הטבלה המפורסמת ואת "
        "התוצאה שהרתמה מדדה עבור seed קבוע."),
    "test_docs_html.py": ("app",
        "The HTML docs build, cover every document, and have no broken links.",
        "מסמכי ה-HTML נבנים, מכסים כל מסמך, ואין בהם קישורים שבורים."),
    "test_nightly.py": ("nightly",
        "The default brain on 400 seeds used nowhere else; runs only with --nightly (GitHub Actions, "
        "nightly).",
        "המוח ברירת המחדל על 400 seeds שלא משמשים בשום מקום אחר; רץ רק עם ‎--nightly (GitHub Actions, "
        "בכל לילה)."),
    "test_behavior.py": ("legacy", "Written against the original API; kept as strict xfail until rewritten.",
                         "נכתבה מול ה-API המקורי; נשמרת כ-xfail קשיח עד שתיכתב מחדש."),
    "test_merge.py": ("legacy", "Written against the original API; kept as strict xfail until rewritten.",
                      "נכתבה מול ה-API המקורי; נשמרת כ-xfail קשיח עד שתיכתב מחדש."),
    "test_physics.py": ("legacy", "Written against the original API; kept as strict xfail until rewritten.",
                        "נכתבה מול ה-API המקורי; נשמרת כ-xfail קשיח עד שתיכתב מחדש."),
    "test_safety.py": ("legacy", "Written against the original API; kept as strict xfail until rewritten.",
                       "נכתבה מול ה-API המקורי; נשמרת כ-xfail קשיח עד שתיכתב מחדש."),
    "test_deadlock.py": ("legacy", "An early regression test from the original project.",
                         "בדיקת רגרסיה מוקדמת מהפרויקט המקורי."),
}

# Known limitations behind the strict xfails: BUGS id -> Hebrew summary (the English reason comes from the test).
LIMITATIONS_HE = {
    "O2": "הסוכן לפעמים יוצא כשמכונית לצד המפרץ, ונוגע בה.",
    "O5": "מהירות האוטובוס העומד מוצבת ל-0 בהגעה ובזמן העלאת נוסעים.",
    "O7": "תרחיש A מאפס את תנוחת האוטובוס.",
    "O12": "מקצה המפרץ הרחוק, אחרי שמכונית עוברת, הסוכן יוצא לאט מדי ופינת שפת היציאה חודרת לצידו.",
    "O17": "אין מסה לרכב: אוטובוס בולם בעוצמה של מכונית קטנה.",
    "O18": "אין השהיית בלמים: התאוצה יכולה לעבור משיוט לבלימה מלאה בצעד אחד.",
    "O19": "חוק המהירות הבטוחה יכול להכניס רכב עוקב עד כ-0.55 מ' לתוך המרווח המינימלי שלו (לא עד מגע).",
    "O20": "מחולל המכוניות מאבד הגעות כשהכניסה חסומה, ולכן מספק פחות מהזרימה המבוקשת.",
    "legacy": "בדיקה ישנה שנכתבה מול API קודם; ממתינה לכתיבה מחדש.",
}

STATUS = {  # key -> (English, Hebrew, colour token)
    "passed": ("Passed", "עברה", "ok"),
    "xfailed": ("Expected failure", "כישלון צפוי", "warn"),
    "skipped": ("Skipped", "דולגה", "muted"),
    "failed": ("Failed", "נכשלה", "bad"),
}

EXTRA_CSS = """
.report-head { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; align-items: baseline; }
.meta { color: var(--muted); font-size: 14px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 18px 0 8px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  box-shadow: var(--shadow); }
.tile .num { font-size: 28px; font-weight: 700; line-height: 1.1; }
.tile .lbl { color: var(--muted); font-size: 13px; margin-top: 4px; }
.tile .lbl span[dir="rtl"] { display: block; }
.verdict { margin: 14px 0 6px; padding: 12px 16px; border-radius: 12px; font-weight: 600; }
.verdict.ok { background: color-mix(in srgb, var(--ok) 14%, transparent); border: 1px solid var(--ok); }
.verdict.bad { background: color-mix(in srgb, var(--bad) 14%, transparent); border: 1px solid var(--bad); }
.badge { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
  white-space: nowrap; border: 1px solid currentColor; }
.badge.ok { color: var(--ok); } .badge.warn { color: var(--warn); } .badge.muted { color: var(--muted); }
.badge.bad { color: var(--bad); }
.sbar { display: flex; height: 8px; border-radius: 999px; overflow: hidden; background: var(--border); min-width: 120px; }
.sbar i { display: block; height: 100%; }
.sbar i.ok { background: var(--ok); } .sbar i.warn { background: var(--warn); } .sbar i.muted { background: var(--muted); }
.sbar i.bad { background: var(--bad); }
details.file { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; margin: 10px 0;
  box-shadow: var(--shadow); }
details.file > summary { cursor: pointer; padding: 12px 16px; display: flex; gap: 12px; align-items: center;
  flex-wrap: wrap; list-style: none; }
details.file > summary::-webkit-details-marker { display: none; }
details.file > summary .name { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 600; }
details.file > summary .counts { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }
details.file .body { padding: 0 16px 14px; }
details.file .desc { margin: 4px 0 10px; }
details.file .desc[dir="rtl"] { border-right: 3px solid var(--accent); padding-right: 12px; }
details.file .table-wrap { margin: 8px 0 0; box-shadow: none; }
td.t { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; min-width: 15rem; }
td.time { text-align: right; color: var(--muted); white-space: nowrap; }
.he { direction: rtl; text-align: right; }
:root { --ok: #1a7f37; --warn: #9a6700; --bad: #cf222e; }
@media (prefers-color-scheme: dark) { :root { --ok: #3fb950; --warn: #d29922; --bad: #f85149; } }
"""


def run_tests() -> None:
    """Run the suite (as CI does) and record the results and the environment."""
    OUT_DIR.mkdir(exist_ok=True)
    start = time.time()
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           f"--junitxml={JUNIT}"], cwd=REPO)
    elapsed = time.time() - start
    versions = {}
    for module in ("torch", "numpy", "pandas", "streamlit"):
        try:
            versions[module] = __import__(module).__version__
        except ImportError:
            pass
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                           text=True, cwd=REPO).stdout.strip()
    RUN_META.write_text(json.dumps({
        "when": datetime.datetime.now().isoformat(timespec="minutes"), "wall_s": round(elapsed, 1),
        "exit_code": proc.returncode, "commit": commit + ("+uncommitted" if dirty else ""),
        "python": platform.python_version(), "platform": platform.platform(terse=True), **versions,
    }, indent=1))


def _cases() -> list[dict]:
    root = ET.parse(JUNIT).getroot()
    cases = []
    for tc in root.iter("testcase"):
        classname = tc.get("classname", "")
        module = classname.split(".")[1] if classname.startswith("tests.") else classname.split(".")[0]
        status, reason = "passed", ""
        for child in tc:
            if child.tag in ("failure", "error"):
                status, reason = "failed", child.get("message", "")
            elif child.tag == "skipped":
                kind = child.get("type", "")
                status = "xfailed" if "xfail" in kind else "skipped"
                reason = child.get("message", "")
        cases.append({"file": f"{module}.py", "name": tc.get("name", ""), "time": float(tc.get("time", 0)),
                      "status": status, "reason": reason})
    return cases


def _bilingual(en: str, he: str, tag: str = "span") -> str:
    return f'{html.escape(en)} · <{tag} dir="rtl">{html.escape(he)}</{tag}>'


def _bar(counts: dict) -> str:
    total = sum(counts.values()) or 1
    return '<div class="sbar">' + "".join(
        f'<i class="{STATUS[k][2]}" style="width:{100 * counts.get(k, 0) / total:.2f}%"></i>'
        for k in STATUS if counts.get(k)) + "</div>"


def _badges(counts: dict) -> str:
    return "".join(f'<span class="badge {STATUS[k][2]}">{counts[k]} {STATUS[k][0].lower()}</span>'
                   for k in STATUS if counts.get(k))


def _limitation_id(reason: str) -> str:
    m = re.search(r"BUGS (O\d+)", reason)
    return m.group(1) if m else ("legacy" if "legacy API" in reason else "")


def _nightly() -> str:
    files = sorted(NIGHTLY_DIR.glob("*.json")) if NIGHTLY_DIR.exists() else []
    if not files:
        return ("<p>No local nightly run recorded. On GitHub the gates run every night "
                "(<code>.github/workflows/nightly.yml</code>).</p>")
    when = datetime.datetime.fromtimestamp(max(f.stat().st_mtime for f in files)).strftime("%Y-%m-%d %H:%M")
    rows = []
    for f in files:
        s = json.loads(f.read_text())
        rows.append(f"<tr><td>{html.escape(f.stem)}</td><td>{s['n']}</td><td>{s['merged_pct']:.1f}%</td>"
                    f"<td>{s['contact_pct']:.1f}%</td><td>{s['stuck_pct']:.1f}%</td><td>{s['strict_pct']:.1f}%</td>"
                    f"<td>{s['over_centre_pct']:.1f}%</td><td>{s.get('other_violation_runs', 0)}</td>"
                    f"<td>{s['time_mean_s']:.1f} s</td></tr>")
    return (f'<p class="meta">Last local run of <code>pytest --nightly -m nightly</code>: {when} · '
            f'<span dir="rtl">ההרצה המקומית האחרונה</span></p>'
            '<div class="table-wrap"><table><thead><tr><th>Gate</th><th>Seeds</th><th>Merged</th><th>Contact</th>'
            '<th>Stuck</th><th>Strict</th><th>Centre line</th><th>Other violations</th><th>Mean time</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _report_body() -> tuple[str, str]:
    cases = _cases()
    meta = json.loads(RUN_META.read_text()) if RUN_META.exists() else {}
    totals = defaultdict(int)
    for c in cases:
        totals[c["status"]] += 1
    by_file = defaultdict(list)
    for c in cases:
        by_file[c["file"]].append(c)
    unknown = sorted(set(by_file) - set(FILES))

    green = totals["failed"] == 0
    verdict = (f'<div class="verdict {"ok" if green else "bad"}">'
               + (_bilingual("All green: every test passed or failed exactly as documented.",
                             "הכול ירוק: כל בדיקה עברה או נכשלה בדיוק כפי שתועד.") if green else
                  _bilingual(f"{totals['failed']} test(s) failed.", f"{totals['failed']} בדיקות נכשלו."))
               + "</div>")
    env = " · ".join(f"{k} {meta[k]}" for k in ("python", "torch", "numpy", "pandas", "streamlit") if k in meta)
    head = (f'<div class="report-head"><h1>Test report · <span dir="rtl">דוח בדיקות</span></h1></div>'
            f'<p class="meta">Run {html.escape(meta.get("when", "?"))} · commit <code>{html.escape(meta.get("commit", "?"))}</code>'
            f' · {html.escape(env)}</p>')
    intro = (
        "<p>Every result on this page comes from one real run of the whole suite (<code>pytest</code>, as CI runs "
        "it). <strong>Strict xfail</strong> marks a known limitation: the test keeps its honest assertion, must "
        "fail on that assertion, and turns red the day the behaviour changes.</p>"
        '<div dir="rtl"><p>כל תוצאה בעמוד הזה מגיעה מהרצה אמיתית אחת של כל החבילה (<code>pytest</code>, כפי '
        "שה-CI מריץ אותה). <strong>xfail קשיח</strong> מסמן מגבלה ידועה: הבדיקה שומרת על ההנחה הכנה שלה, חייבת "
        "להיכשל עליה, והופכת לאדומה ביום שההתנהגות משתנה.</p></div>")
    total = sum(totals.values())
    nightly_skips = sum(1 for c in cases if c["status"] == "skipped" and c["file"] == "test_nightly.py")
    tiles = [(total, "Test cases", "מקרי בדיקה"), (totals["passed"], "Passed", "עברו"),
             (totals["xfailed"], "Expected failures (strict xfail)", "כישלונות צפויים"),
             (totals["skipped"], f"Skipped ({nightly_skips} nightly, {totals['skipped'] - nightly_skips} other)",
              f"דולגו ({nightly_skips} ליליות, {totals['skipped'] - nightly_skips} אחרות)"),
             (totals["failed"], "Failed", "נכשלו"),
             (f"{meta['wall_s'] / 60:.1f} min" if "wall_s" in meta else "–", "Run time", "זמן ריצה")]
    tiles_html = '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="num">{v}</div><div class="lbl">{html.escape(en)}'
        f'<span dir="rtl">{html.escape(he)}</span></div></div>' for v, en, he in tiles) + "</div>"

    # Categories overview
    rows = []
    for key, (en, he) in CATEGORIES.items():
        files = [f for f in by_file if FILES.get(f, ("",))[0] == key]
        counts = defaultdict(int)
        for f in files:
            for c in by_file[f]:
                counts[c["status"]] += 1
        if not files:
            continue
        rows.append(f'<tr><td><a href="#{key}">{html.escape(en)}</a></td><td class="he">{html.escape(he)}</td>'
                    f"<td>{len(files)}</td><td>{sum(counts.values())}</td><td>{_bar(counts)}</td>"
                    f"<td>{_badges(counts)}</td></tr>")
    overview = ('<h2 id="overview">Overview by area · <span dir="rtl">סקירה לפי תחום</span></h2>'
                '<div class="table-wrap"><table><thead><tr><th>Area</th><th>תחום</th><th>Files</th><th>Cases</th>'
                f'<th>Status</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    # Known limitations (strict xfail)
    lim_rows = []
    for c in sorted((c for c in cases if c["status"] == "xfailed"), key=lambda c: (c["file"], c["name"])):
        lid = _limitation_id(c["reason"])
        reason = re.sub(r"^reason:\s*", "", c["reason"])
        lim_rows.append(f'<tr><td class="t">{html.escape(c["file"])}<br>{html.escape(c["name"])}</td>'
                        f'<td>{html.escape(lid) if lid != "legacy" else "legacy"}</td><td>{html.escape(reason)}</td>'
                        f'<td class="he">{html.escape(LIMITATIONS_HE.get(lid, ""))}</td></tr>')
    limitations = ('<h2 id="limitations">Known limitations (strict xfail) · <span dir="rtl">מגבלות ידועות</span></h2>'
                   '<div class="table-wrap"><table><thead><tr><th>Test</th><th>BUGS</th><th>Reason</th>'
                   f'<th>הסבר</th></tr></thead><tbody>{"".join(lim_rows)}</tbody></table></div>')

    nightly = f'<h2 id="nightly-results">Latest nightly results · <span dir="rtl">תוצאות ליליות אחרונות</span></h2>{_nightly()}'

    # Per area, per file
    sections, toc_items = [], ['<li><a href="#overview">Overview by area</a></li>',
                               '<li><a href="#limitations">Known limitations</a></li>',
                               '<li><a href="#nightly-results">Latest nightly results</a></li>']
    for key, (en, he) in CATEGORIES.items():
        files = sorted(f for f in by_file if FILES.get(f, ("",))[0] == key)
        if not files:
            continue
        toc_items.append(f'<li><a href="#{key}">{html.escape(en)}</a></li>')
        cards = []
        for f in files:
            _, desc_en, desc_he = FILES[f]
            counts = defaultdict(int)
            for c in by_file[f]:
                counts[c["status"]] += 1
            test_rows = "".join(
                f'<tr><td class="t">{html.escape(c["name"])}</td>'
                f'<td><span class="badge {STATUS[c["status"]][2]}">{STATUS[c["status"]][0]}</span></td>'
                f'<td class="time">{c["time"]:.2f} s</td></tr>' for c in sorted(by_file[f], key=lambda c: c["name"]))
            open_attr = " open" if counts.get("failed") else ""
            cards.append(
                f'<details class="file"{open_attr}><summary><span class="name">{html.escape(f)}</span>'
                f'<span class="counts">{_badges(counts)}</span></summary><div class="body">'
                f'<p class="desc">{html.escape(desc_en)}</p><p class="desc" dir="rtl">{html.escape(desc_he)}</p>'
                '<div class="table-wrap"><table><thead><tr><th>Test case</th><th>Result</th><th>Time</th></tr>'
                f'</thead><tbody>{test_rows}</tbody></table></div></div></details>')
        sections.append(f'<h2 id="{key}">{html.escape(en)} · <span dir="rtl">{html.escape(he)}</span></h2>'
                        + "".join(cards))
    if unknown:
        sections.append(f"<p>Files without a description: {', '.join(unknown)}</p>")
    toc = "<ul>" + "".join(toc_items) + "</ul>"
    body = head + intro + tiles_html + verdict + overview + limitations + nightly + "".join(sections)
    return body, toc


def write(out_dir: Path) -> Path:
    """Write TEST_REPORT.html from the last recorded run (or a page explaining how to record one)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_docs_html
    target = Path(out_dir) / "TEST_REPORT.html"
    if JUNIT.exists():
        body, toc = _report_body()
    else:
        body, toc = ("<h1>Test report · <span dir=\"rtl\">דוח בדיקות</span></h1><p>No test run recorded yet. Run "
                     "<code>python scripts/build_test_report.py</code>.</p>"), ""
    target.write_text(build_docs_html.shell("Test report", "TEST_REPORT.html", body, toc,
                                            "Generated by <code>scripts/build_test_report.py</code> from a recorded "
                                            "pytest run.", EXTRA_CSS), encoding="utf-8")
    return target


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-run", action="store_true", help="rebuild from the last recorded run")
    ap.add_argument("--out", type=Path, default=REPO / "docs" / "html")
    args = ap.parse_args()
    if not args.no_run:
        run_tests()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_docs_html
    build_docs_html.build(args.out)        # the whole site, including this report
    print(args.out / "TEST_REPORT.html")
