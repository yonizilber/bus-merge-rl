# Documentation map · מפת התיעוד

**Newest first.** Everything about the project's documents is in this folder; each subfolder says what it is and how new it is.
**מהחדש לישן.** כל המסמכים נמצאים בתיקייה הזו, ולכל תיקיית משנה כתוב מה היא ועד כמה היא עדכנית.

| Folder · תיקייה | What it is · מה זה | Status · מצב | Open it · פתיחה |
|---|---|---|---|
| [`tools/`](tools/) | The interactive explorer: choose traffic, occupancies, stop times and penalties and see whether a bay or an in-lane stop is better (Hebrew and English; also the "Explorer" tab of `current/`). הכלי האינטראקטיבי: בוחרים תנאים ורואים מה עדיף (עברית ואנגלית; גם הלשונית "הכלי" ב-`current/`). | **Newest · חדש ביותר** | `tools/stop_design_explorer.he.html`, `tools/stop_design_explorer.en.html` |
| [`reports/`](reports/) | Standalone report: the simulation against published field data, with sources (Hebrew; the same comparison, in both languages, is the "Field data" tab of `current/`). דוח עצמאי: הסימולציה מול נתוני שטח, עם מקורות (אותה השוואה, בשתי השפות, היא הלשונית "נתוני שטח" ב-`current/`). | **Newest · חדש ביותר** | `reports/REAL_DATA_COMPARISON.he.html` |
| [`current/`](current/) | The third documentation version: an English and a Hebrew set (never mixed), industry style. Pages: overview, world, agent, case study, results, research, testing, limitations, changelog. הגרסה השלישית של התיעוד, באנגלית ובעברית בנפרד. | **Current · עדכנית.** The results are three tabs: Results (both experiments, 19,500 runs, and the conclusion with sources), Explorer and Field data. התוצאות הן שלוש לשוניות: תוצאות (שני הניסויים והמסקנה עם מקורות), הכלי ונתוני שטח. | `current/site/en/index.html`, `current/site/he/index.html` (built by `python scripts/build_next_docs.py --root docs/current --github`); GitHub-viewable Markdown in `current/github/` |
| [`reference/`](reference/) | The original technical documents, still the home of the bug list and the specification: `BUGS.md`, `SPECS.md`, `TRAINING.md`, `TEST_STRATEGY.md`, `JOURNAL.md`, `ROADMAP.md`, `QA_TEST_SUMMARY.md`, `CASE_STUDY_REWARD_HACKING.md`, `EXPERIMENT_STOP_DESIGN.md`, `REAL_DATA_COMPARISON.md` (English). מסמכי ה-Markdown הטכניים המקוריים. | Living reference. מסמכי עזר חיים. | `reference/html/index.html` (built by `python scripts/build_docs_html.py`) |
| [`archive/v2-next/`](archive/v2-next/) | The second documentation version (a draft that the third replaced). הגרסה השנייה של התיעוד, שהשלישית החליפה. | **Old, kept for reference · ישן, נשמר לעיון** | `archive/v2-next/site/en/index.html` (built by `python scripts/build_next_docs.py`) |
| [`media/`](media/) | GIFs and figures shared by the sets above. תמונות וגרפים משותפים. | Shared · משותף | |

The `site/` and `html/` folders are generated and not in git; build them with the commands above. תיקיות `site/` ו-`html/` נוצרות מהפקודות שלמעלה ואינן ב-git.

The standalone report and the explorer are built by `scripts/build_real_data_report.py` and `scripts/build_stop_design_explorer.py` from the stored measurements in `results/experiments/` (see `reference/EXPERIMENT_STOP_DESIGN.md`). `results/experiments/stop_design/combined.json`, the summary of both experiments that the Results page and the explorer read, is written by `scripts/summarize_stop_experiments.py` from the raw runs in `outputs/` (not in git).
