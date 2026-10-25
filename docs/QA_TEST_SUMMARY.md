# Testing and QA summary · סיכום בדיקות ו-QA

English first, Hebrew below each section. Status on 2026-10-13: default agent v13.

---

## 1. Principles

- **One harness for every number.** The Streamlit app, the test suite, `scripts/verify_brain.py` and
  the nightly gates all run the same episode code (`busmerge/evaluation.py`) and judge it the same way.
  A difference between a test and the app counts as a bug.
- **No hidden corrections.** Speed and position only follow from acceleration. Every run is checked for
  physically impossible moments instead of having them clamped away. A model that fails visibly is
  preferred to one that invents.
- **Measure on unseen seeds.** Training, selection and publication use separate seed ranges.
- **Every published number is generated.** The README, SPECS and case-study tables are rendered from
  stored measurements, and a test fails if they drift.

<div dir="rtl">

## 1. עקרונות

- **רתמה אחת לכל מספר.** אפליקציית Streamlit, חבילת הבדיקות, `scripts/verify_brain.py` והבדיקות הליליות מריצים את אותו קוד אפיזודה (`busmerge/evaluation.py`) ושופטים אותו באותה דרך. הבדל בין בדיקה לאפליקציה נחשב באג.
- **אין תיקונים נסתרים.** מהירות ומיקום נגזרים רק מהתאוצה. כל הרצה נבדקת לרגעים בלתי אפשריים פיזיקלית במקום "לחתוך" אותם. עדיף מודל שנכשל בגלוי על פני מודל שממציא.
- **מדידה על seeds שלא נראו.** אימון, בחירה ופרסום משתמשים בטווחי seeds נפרדים.
- **כל מספר שמתפרסם נוצר אוטומטית.** הטבלאות ב-README, ב-SPECS ובחקר המקרה נוצרות ממדידות שמורות, ובדיקה נכשלת אם הן סוטות מהן.

</div>

---

## 2. Scope of the automated tests

| Area | What is checked | Examples |
|---|---|---|
| **Physics constraints** | The invariants: braking ≤ 9 m/s², acceleration ≤ 5 m/s², no negative speed, no backward motion, no position jump, no overlap, the road edges (exact polygons, including kerb corners), the centre line, heading | Every steering update in a real run (more than 5,000) respects the bicycle model; speed never steps; a random or full-extreme driver produces no impossible moment; a sweep at 0.2-0.8 cars/s |
| **Property-based physics** | The safe-speed law over thousands of random cases (`hypothesis`) | Never brakes beyond the limit, never closes more than the gap in one step, never into contact |
| **Geometry** | The road-edge check against a brute-force 1 cm outline walk | 3,000 random poses at the tapers |
| **Steering** | Pure pursuit converges without overshoot | 56 cases; the old overshooting law is shown to fail |
| **RL pipeline** | The training env equals the app engine bit for bit. PPO ratio = 1 before the first update. Rollback never restores starting weights. Two-epoch training end to end. Each reward term by its formula. Reward ranking. Checkpoint round trip. Policy sanity on unusual inputs. Determinism with noise on. Valid training start poses | A 1e-9 m/s drift is caught; the old clipped-action buffer and the old rollback rule are shown to fail |
| **Behaviour** | The default agent in forced situations | Merges within 15 s from every metre of the stop range; never stalls half way (v11's reward hack is caught) |
| **App** | Headless Streamlit run | Loads, offers exactly the existing brains, shows the published table, and for a fixed seed shows the outcome the harness measured |
| **Published numbers** | Summaries recomputed from per-seed rows; every generated block checked | A one-point change is caught |
| **CI/CD** | GitHub Actions: `ruff` + `pytest` on every push; nightly gates on 250 unused seeds (400 runs) | The workflow was reproduced locally in a clean virtual environment |

Every guard is accompanied by a check that it **can fail**. For example, the overshoot test is run
against the old controller, the stall test against v11, the parity test against an injected drift, and
the single-source scan against a planted copy.

<div dir="rtl">

## 2. היקף הבדיקות האוטומטיות

| תחום | מה נבדק | דוגמאות |
|---|---|---|
| **אילוצי פיזיקה** | האינווריאנטים: בלימה ≤ 9 מ'/ש², האצה ≤ 5 מ'/ש², אין מהירות שלילית, אין תנועה לאחור, אין קפיצת מיקום, אין חפיפה, קצוות הכביש (פוליגונים מדויקים, כולל פינות שפה), הקו האמצעי, זווית כיוון | כל עדכון היגוי בהרצה אמיתית (יותר מ-5,000) מכבד את מודל האופניים; המהירות לעולם לא קופצת; נהג אקראי או קיצוני לא מייצר רגע בלתי אפשרי; סריקה בצפיפויות 0.2-0.8 מכוניות לשנייה |
| **פיזיקה מבוססת תכונות** | חוק המהירות הבטוחה על אלפי מקרים אקראיים (`hypothesis`) | לעולם לא בולם מעבר לגבול, לא סוגר יותר מהמרווח בצעד אחד, ולעולם לא מגיע למגע |
| **גיאומטריה** | בדיקת קצה הכביש מול בדיקת כוח-גס שעוברת על קו המתאר בצעדים של 1 ס"מ | 3,000 תנוחות אקראיות באזור ההרחבות |
| **היגוי** | Pure pursuit מתכנס בלי לחרוג מהיעד | 56 מקרים; מוכח שהחוק הישן, שחרג מהיעד, נכשל |
| **צינור ה-RL** | סביבת האימון זהה למנוע האפליקציה ביט לביט. יחס PPO שווה 1 לפני העדכון הראשון. rollback לעולם לא משחזר משקלי התחלה. אימון של שני epochs מקצה לקצה. כל רכיב בתגמול לפי הנוסחה שלו. דירוג תגמולים. שמירה וטעינה של checkpoint. שפיות המדיניות על קלטים חריגים. דטרמיניזם עם רעש. תנוחות פתיחה תקינות באימון | סטייה של 1e-9 מ'/ש נתפסת; מוכח שה-buffer הישן (פעולה חתוכה) וכלל ה-rollback הישן נכשלים |
| **התנהגות** | הסוכן ברירת המחדל במצבים כפויים | משתלב תוך 15 שניות מכל מטר בטווח העצירה; לעולם לא נתקע באמצע הדרך (ה-reward hacking של v11 נתפס) |
| **אפליקציה** | הרצת Streamlit ללא ממשק | נטענת, מציעה בדיוק את המוחות הקיימים, מציגה את הטבלה המפורסמת, ועבור seed קבוע מציגה את התוצאה שהרתמה מדדה |
| **מספרים מפורסמים** | הסיכומים מחושבים מחדש משורות ה-seed; כל בלוק שנוצר נבדק | שינוי של נקודה אחת נתפס |
| **CI/CD** | GitHub Actions: `ruff` ו-`pytest` בכל push; בדיקות ליליות על 250 seeds שאינם בשימוש (400 הרצות) | ה-workflow שוחזר מקומית בסביבה וירטואלית נקייה |

לכל שומר מצורפת בדיקה שמוכיחה שהוא **מסוגל להיכשל**. למשל, בדיקת החריגה מורצת מול הבקר הישן, בדיקת התקיעה מול v11, בדיקת הזהות מול סטייה מוזרקת, וסריקת "מקור יחיד" מול עותק שהושתל.

</div>

---

## 3. Strict `xfail`: known limitations kept visible

**Why.** A known limitation of the engine or the agent is still a failing assertion. Deleting the test
or loosening its threshold would hide it. Marking it `xfail(strict=True, raises=AssertionError)` keeps
the honest assertion in the suite and documents the limitation next to the code:
- the failure must be the assertion itself, not a crash;
- if the behaviour ever changes, the test turns red;
- every one cites its entry in [BUGS.md](BUGS.md);
- where a limitation is a list (state assignments outside the physics), a passing companion test pins
  the list exactly, so a new case fails CI.

| Limitation | Tracked by | BUGS |
|---|---|---|
| The agent sometimes pulls out while a car is alongside (about 2% of runs) | `test_brain_behaviour.py` | O2 |
| From the far end of the bay, the agent steers out too slowly and clips the exit kerb (about 9%) | `test_brain_behaviour.py` (2 placements) | O12 |
| The stopped bus's speed is set to 0; scenario A resets its pose | `test_no_state_assignment.py` | O5, O7 |
| **No vehicle mass**: a bus brakes as hard as a compact car | `test_physics_limits.py` | O17 |
| **No brake actuation lag**: jerk up to about 107 m/s³ | `test_physics_limits.py` | O18 |
| The safe-speed law can intrude up to 0.55 m into the 2 m minimum gap (never into contact) | `test_safe_speed_properties.py` | O19 |
| The car generator loses arrivals: about 71% of the requested inflow is delivered at the default | `test_traffic_density.py` (4 densities) | O20 |

There are 11 such cases. The other 9 `xfail` are tests inherited from the original project, written
against an older API and kept until they are rewritten.

**Documented, not yet pinned by a test** (2026-10-25): O21, the cars' steering law has no heading term and
overshoots (it explains most of the cars crossing the centre line), and O22, the IDM acceleration functions
change the vehicle's state. Both would be strict `xfail` tests (TEST_STRATEGY N1, N2); they are listed so that
the 11 above are not read as the full list of limitations.

<div dir="rtl">

## 3. ‏`xfail` קשיח: מגבלות ידועות נשארות גלויות

**למה.** מגבלה ידועה של המנוע או של הסוכן היא עדיין הנחה (assertion) שנכשלת. מחיקת הבדיקה או הרפיית הסף שלה היו מסתירות אותה. סימון ב-`xfail(strict=True, raises=AssertionError)` משאיר את ההנחה הכנה בחבילה ומתעד את המגבלה ליד הקוד:
- הכישלון חייב להיות ההנחה עצמה, לא קריסה;
- אם ההתנהגות תשתנה אי פעם, הבדיקה הופכת לאדומה;
- כל אחת מפנה לרשומה שלה ב-[BUGS.md](BUGS.md);
- כשהמגבלה היא רשימה (השמות של מצב מחוץ לפיזיקה), בדיקה משלימה עוברת מקבעת את הרשימה במדויק, כך שמקרה חדש מכשיל את ה-CI.

| מגבלה | נבדקת ב- | BUGS |
|---|---|---|
| הסוכן לפעמים יוצא כשמכונית לצידו (כ-2% מההרצות) | `test_brain_behaviour.py` | O2 |
| מקצה המפרץ הרחוק הסוכן יוצא לאט מדי ונוגע בשפת היציאה (כ-9%) | `test_brain_behaviour.py` (2 מיקומים) | O12 |
| מהירות האוטובוס העומד מוצבת ל-0; תרחיש A מאפס את התנוחה | `test_no_state_assignment.py` | O5, O7 |
| **אין מסה לרכב**: אוטובוס בולם בעוצמה של מכונית קטנה | `test_physics_limits.py` | O17 |
| **אין השהיית בלמים**: jerk עד כ-107 מ'/ש³ | `test_physics_limits.py` | O18 |
| חוק המהירות הבטוחה יכול לחדור עד 0.55 מ' לתוך המרווח המינימלי של 2 מ' (אף פעם לא עד מגע) | `test_safe_speed_properties.py` | O19 |
| מחולל המכוניות מאבד הגעות: בברירת המחדל מתקבל כ-71% מהזרימה המבוקשת | `test_traffic_density.py` (4 צפיפויות) | O20 |

יש 11 מקרים כאלה. 9 ה-`xfail` האחרים הם בדיקות שעברו בירושה מהפרויקט המקורי, נכתבו מול API ישן ונשמרות עד שייכתבו מחדש.

**מתועדות, ועדיין לא מקובעות בבדיקה** (25.10.2026): O21, חוק ההיגוי של המכוניות ללא איבר כיוון וחורג מהיעד (הוא מסביר את
רוב חציית קו האמצע של מכוניות), ו-O22, פונקציות התאוצה של ה-IDM משנות את מצב הרכב. שתיהן יהיו בדיקות xfail קשיחות
(TEST_STRATEGY, N1 ו-N2); הן מופיעות כאן כדי ש-11 המקרים שלמעלה לא ייקראו כרשימה המלאה של המגבלות.

</div>

---

## 4. Tests as a discovery tool

Writing the tests found real problems, each now fixed or documented:
- **O16:** the pull-in steering is unstable for sudden steps at speed.
- **O19:** the safe-speed law can intrude into its own minimum gap. `hypothesis` found the smallest
  case.
- **O20:** the car generator loses arrivals, which explained the flat stress results.
- **H15:** the app showed no outcome when the bus left the road.
- **P17 and P18:** a PPO buffer bias and a silent rollback. Both had blocked retraining.

**Manual visual QA in the app** then found and fixed four more:
- **H17:** the merge-zone view ran to the end of the traffic.
- **H18:** the governor panel listed "disabled" frames as decisions.
- **H19:** a fixed "PPO+Governor" label was shown with the governor off.
- **Layout:** the diagnostics panels were placed above the view.

<div dir="rtl">

## 4. בדיקות ככלי גילוי

כתיבת הבדיקות חשפה בעיות אמיתיות, וכל אחת מהן תוקנה או תועדה:
- **O16:** היגוי הכניסה למפרץ אינו יציב לקפיצות פתאומיות במהירות.
- **O19:** חוק המהירות הבטוחה יכול לחדור למרווח המינימלי שלו עצמו. `hypothesis` מצא את המקרה המינימלי.
- **O20:** מחולל המכוניות מאבד הגעות, וזה מה שהסביר את תוצאות העומס השטוחות.
- **H15:** האפליקציה לא הציגה תוצאה כשהאוטובוס יצא מהכביש.
- **P17 ו-P18:** הטיה ב-buffer של PPO ו-rollback שקט. שניהם חסמו את האימון מחדש.

**QA ויזואלי ידני באפליקציה** מצא ותיקן עוד ארבעה:
- **H17:** תצוגת אזור ההשתלבות נמשכה עד סוף התנועה.
- **H18:** לוח ה-governor הציג פריימים של "disabled" כהחלטות.
- **H19:** תווית קבועה "PPO+Governor" הוצגה כשה-governor כבוי.
- **פריסה:** לוחות האבחון הוצבו מעל התצוגה.

</div>

---

## 5. Stability achieved

- **Push CI:** 361 passed, 20 strict `xfail`, 6 skipped (the 5 nightly gates and 1 conditional skip), in
  about 2 minutes. The result is identical in a clean virtual environment installed exactly as the
  workflow installs it (current PyTorch and NumPy).
- **Nightly gates:** 5 of 5 pass on 250 seeds used nowhere else (400 runs). The default agent merges in 98.0% of
  runs and 89.5% are strict successes, in line with the published 89.4% on 1,000 other seeds.
- **Reproducibility:** re-running every published measurement on the current code gave identical
  results.

<div dir="rtl">

## 5. היציבות שהושגה

- **CI בכל push:** ‏361 עוברות, 20 ‏`xfail` קשיחות, 6 מדולגות (5 הבדיקות הליליות ודילוג מותנה אחד), בכ-2 דקות. התוצאה זהה בסביבה וירטואלית נקייה שהותקנה בדיוק כמו ב-workflow (גרסאות עדכניות של PyTorch ו-NumPy).
- **בדיקות ליליות:** 5 מתוך 5 עוברות על 250 seeds שלא משמשים בשום מקום אחר (400 הרצות). הסוכן ברירת המחדל משתלב ב-98.0% מההרצות ו-89.5% הן הצלחות קפדניות, בהתאמה ל-89.4% שפורסמו על 1,000 seeds אחרים.
- **שחזוריות:** הרצה מחדש של כל מדידה שפורסמה על הקוד הנוכחי נתנה תוצאות זהות.

</div>
