# The next documentation version (draft for review)

This folder holds the next version of the project's documentation, built to be read by someone who has never seen
the project. It is kept for reference: the newer, third version is in `docs/current/`, and the technical reference documents are in
`docs/reference/`.

## Two sets, never mixed

| Set | Sources | Built site |
|---|---|---|
| English | `next/en/*.md` | `next/site/en/index.html` |
| Hebrew | `next/he/*.md` | `next/site/he/index.html` |

Each set has the same pages and is complete by itself: its navigation, notes, glossary and test report are all in
one language, and no page links to the other set. `tests/test_next_docs.py` checks this (no Hebrew in the English
pages, right-to-left Hebrew pages, no link across, no broken link). This file is not part of either set.

```bash
python scripts/build_next_docs.py              # both sites (next/site/ is not committed)
python scripts/build_next_docs.py --lang he    # one language
python scripts/build_test_report.py            # runs the suite and refreshes both test reports
```

## What each page is

| Page | Purpose |
|---|---|
| `README.md` | The overview, results (generated), the story in one paragraph, testing and limitations at a glance |
| `HOW_IT_WORKS.md` | The system from the road to the agent, with every term explained, the full list of the agent's 11 inputs and every reward term |
| `CASE_STUDY.md` | The reward-hacking case study (the English text is the one in `docs/`, with terms marked) |
| `HISTORY.md` | The other problems, from the first prototype to now, taken from the notes of the original repository and from `docs/reference/BUGS.md` |
| `TESTING.md` | What is tested and how, the layers, the known-limitation tests |
| `LIMITATIONS.md` | Every open issue in plain words, with the test that tracks it |
| `GLOSSARY.md` | The terms. The tooltips and the notes at the bottom of each page come from this file |
| (generated) `TEST_REPORT.html` | Every test case with its result, from one real run |

## How terms work

A source writes `[[idm]]` or `[[idm|the IDM model]]`.

- **Hover or focus** shows a popup with a one-line explanation. **Click** pins it. A technical term also has an
  **Expand** button in the popup: the equations (set as MathML at build time, so nothing is loaded when the page
  opens) and how this project implements the model. The popup also has a **Note** link.
- **The notes** at the bottom of each page have the same text. The title of a note leads back to the exact place in the
  text; after you came through a popup's Note link it leads back to *that* place, and each use also has its own arrow.
- **A term used twice.** Only the first use in each `##` section is linked (a paragraph full of underlines is hard to
  read); a repeat in the same section is plain text. A term linked again in a later section gets its own anchor, `↩1`,
  `↩2`, and so on, in the note.
- **The entries** are in `GLOSSARY.md`: `## Title {#key}`, a one-line `> tooltip`, a paragraph (the note), and
  optionally `<!-- details -->` followed by Markdown with `$...$` and `$$...$$` math. An unknown key fails the build.
- **Common terms** (reinforcement learning, reward, seed, and so on) are deliberately not defined.

## What is generated, not typed

- The results table and headline (from `results/`, by `scripts/publish_results.py`; a test fails if they differ).
- The table of the agent's inputs (`{{features_table}}`; a test checks every range and scale against
  `encode_features`).
- The test counts (`{{test_totals}}`, from the last recorded run) and both test reports.

## What is still missing

The documents `SPECS`, `TRAINING`, `BUGS`, `JOURNAL`, `ROADMAP`, `TEST_STRATEGY` and `QA_TEST_SUMMARY` in `docs/reference/` are not
in either set yet. They would be added to both languages once this structure is approved.
