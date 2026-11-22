# Documentation version 3 (draft for review)

The third and newest version of the project's documentation, and the one to read. Version 1 is the technical reference in
`docs/reference/` (still the home of `BUGS.md`, `SPECS.md` and the rest), version 2 is kept in `docs/archive/v2-next/`; both are
unchanged. `docs/README.md` maps all of it.

## What is here

| Path | What it is |
|---|---|
| `en/*.md`, `he/*.md` | The sources, one set per language. Terms are written `[[key|text]]` |
| `site.json` | The pages and the navigation of this version |
| `github/en/`, `github/he/` | The same pages as GitHub-flavoured Markdown, ready to be read on GitHub: terms become footnotes, math stays as `$…$`. Generated, committed, and checked by a test |
| `site/en/`, `site/he/` | The HTML sites (generated, not committed) |
| `test_counts.json`, `test_report.{en,he}.html` | The last full test run, as the pages show it; the website is built from them (GitHub Pages builds without running the tests) |

```bash
python scripts/build_next_docs.py --root docs/current --github     # both HTML sites and the GitHub Markdown
python scripts/build_next_docs.py --root docs/current --website _site   # the website, as GitHub Pages builds it
```

## What changed from version 2

- **Versions** follow semantic versioning: the simulation is 1.0.1 (the `busmerge` package version is set to match),
  brains are 0.N.0 (v13 is 0.13.0). The scheme, and why the brains stay at major version 0, is in the changelog.
- **Overview**: a hook right after the quick start (the research question, two GIFs: a bay stop and an in-lane stop),
  the results told as the test of realism, which brain works and which do not, and why the numbers can be trusted.
- **Research question**: a new page; motivation, measures, factors and the experiment.
- **Results**: three tabs. *Measurements and research* is the interactive explorer, with both experiments (19,500
  runs) told below it in chapters (what the bay costs, what it buys, who wins, what if the bay stop is longer, how
  sure). *Conclusions* gives our conclusion, the assumption it rests on and its sources. *Field data* compares the
  simulation with published measurements. The numbers are generated from `results/experiments/stop_design/combined.json`,
  and tests check the text against them; the figures are in `docs/media/` in both languages.
- **How it works** split into **World model** and **Agent**, in standard terminology (observation space, action
  space, reward function; the input table's columns are Index and Meaning).
- **Case study**: retitled; the whole story (problem, how it was found, cause, fix, result) at the top, with links to
  the detailed sections below.
- **History of problems** became a **Changelog** in the Keep a Changelog format, every fix with its commit.
- **Testing**: the status line first (passed, expected failures, skipped, failed, and what each means), the
  development rule (protected `main`, merge only on green CI), and "nightly" renamed to the scheduled job it is.

## Open decisions

- Where the published files go: for example the English GitHub Markdown as the root `README.md` and `docs/`, the
  Hebrew set under `docs/he/`.
- Release tags: the existing tag `v1.0-stable` (at `fb2b067`) could be complemented by `v1.0.0` and `v1.0.1` (at
  `d1bfad5`) in the SemVer form.
- GitHub settings when the repository is published: branch protection for `main` with the CI check required, the
  repository description and topics.
