"""The interactive explorer (docs/tools/stop_design_explorer.he.html) says what the stored measurement says.

- Its embedded table reproduces the published summary (same cars in both designs, equal dwell times).
- Every number in its written summary is what the table gives.
- The calculation that runs in the browser agrees with an independent one here, on and between grid points.
"""
import json
import math
import re

import pytest

from busmerge.paths import REPO_ROOT

PAGE = (REPO_ROOT / "docs" / "tools" / "stop_design_explorer.he.html").read_text(encoding="utf-8")
DATA = json.loads(re.search(r"const DATA = (\{.*?\});\n", PAGE, re.S).group(1))
SUMMARY = json.loads((REPO_ROOT / "results" / "experiments" / "stop_design_v1" / "summary.json").read_text())
RATES, DWELLS = DATA["rates"], DATA["dwells"]


def pair(rate, lane, bay):
    return DATA["pairs"][f"{rate:g}"][str(lane)][str(bay)]


def verdict(pc, pb, v):
    n, a, b, va, vb, c = v
    mean = pb * a + pc * b
    se = 1.96 * math.sqrt((pb * pb * va + pc * pc * vb + 2 * pb * pc * c) / n)
    return ("bay" if mean + se < 0 else "lane" if mean - se > 0 else "tie"), mean


def counts(pc, pb):
    out = {"bay": 0, "lane": 0, "tie": 0}
    for r in RATES:
        for d in DWELLS:
            out[verdict(pc, pb, pair(r, d, d))[0]] += 1
    return out


def test_the_table_reproduces_the_published_summary():
    for cell in SUMMARY["cells"]:
        n, a, b, *_ = pair(cell["traffic_rate"], cell["dwell_s"], cell["dwell_s"])
        assert n == cell["pairs"] == 300
        assert a == pytest.approx(cell["delta_bus_time_s"], abs=0.01)
        assert b == pytest.approx(cell["delta_cars_time_s"], abs=0.051)   # the summary rounds to 0.1 s
        assert 50 * a + 1.2 * b == pytest.approx(cell["delta_pt_mean"], abs=0.1)


def test_the_normal_interval_gives_the_same_winners_as_the_bootstrap_one():
    """Winners by the page's interval equal the published winners (bootstrap) at the experiment's own occupancies."""
    for cell in SUMMARY["cells"]:
        published = "bay" if cell["delta_pt_ci_high"] < 0 else "lane" if cell["delta_pt_ci_low"] > 0 else "tie"
        assert verdict(1.2, 50, pair(cell["traffic_rate"], cell["dwell_s"], cell["dwell_s"]))[0] == published, cell


def test_the_summary_sentences():
    assert counts(1.2, 50) == {"bay": 10, "lane": 13, "tie": 2}            # "10 למפרץ, 13 לנתיב ו-2 ללא הכרעה"
    assert counts(1.5, 20) == {"bay": 17, "lane": 8, "tie": 0}             # "17 מתוך 25 ... והנתיב ב-8"
    delays = [pair(r, d, d)[1] for r in RATES for d in DWELLS]
    assert 5.2 < min(delays) < 5.4 and 10.4 < max(delays) < 10.6           # "5.3 עד 10.5 שניות"
    n, a, b, *_ = pair(0.5, 45, 45)
    assert -46 < b / 60 < -45                                                # "כ-45 דקות רכב"
    for rate, expected in ((0.3, 25), (0.5, 59)):                            # "פחות מכ-25 / כ-59 נוסעים" (15 s, 1.5 per car)
        n, a, b, *_ = pair(rate, 15, 15)
        assert -1.5 * b / a == pytest.approx(expected, abs=0.5)
    for rate in (0.3, 0.4, 0.5):                                             # "הנתיב לא מפסיד בשום תפוסה" at 10 s, dense traffic
        for pb in range(2, 81):
            for pc in (1.0, 1.5, 2.0, 2.5):
                assert verdict(pc, pb, pair(rate, 10, 10))[0] != "bay", (rate, pb, pc)


def test_fewer_bus_passengers_never_make_the_lane_relatively_better():
    """ΔPT is linear in the bus load with slope a > 0: an emptier bus can only move the verdict toward the bay."""
    for r in RATES:
        for d in DWELLS:
            assert pair(r, d, d)[1] > 0
            means = [verdict(1.5, pb, pair(r, d, d))[1] for pb in (5, 20, 50, 80)]
            assert means == sorted(means)


@pytest.fixture(scope="module")
def browser_page():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:                                              # no browser in this environment
            pytest.skip(f"no browser: {exc}")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((REPO_ROOT / "docs" / "tools" / "stop_design_explorer.he.html").as_uri())
        page.wait_for_function("window.Explorer !== undefined")
        yield page, errors
        browser.close()


def reference(pc, pb, rate, lane, bay):
    """Independent trilinear interpolation of the table."""
    def idx(axis, v):
        v = min(max(v, axis[0]), axis[-1])
        i = max(k for k in range(len(axis) - 1) if axis[k] <= v)
        return i, (v - axis[i]) / (axis[i + 1] - axis[i])
    (ri, wr), (li, wl), (bi, wb) = idx(RATES, rate), idx(DWELLS, lane), idx(DWELLS, bay)
    out = [0.0] * 6
    for r, w1 in ((ri, 1 - wr), (ri + 1, wr)):
        for lk, w2 in ((li, 1 - wl), (li + 1, wl)):
            for bk, w3 in ((bi, 1 - wb), (bi + 1, wb)):
                v = pair(RATES[r], DWELLS[lk], DWELLS[bk])
                out = [o + w1 * w2 * w3 * x for o, x in zip(out, v)]
    return verdict(pc, pb, out)


@pytest.mark.parametrize("pc,pb,rate,lane,bay", [
    (1.2, 50, 0.3, 15, 15), (1.5, 20, 0.5, 45, 45), (1.7, 10.7, 0.1, 10, 10),     # grid points
    (1.5, 20, 0.33, 17, 23), (1.2, 35, 0.47, 12, 38), (2.0, 5, 0.15, 44, 11)])   # between grid points, different dwells
def test_the_browser_calculation_matches_an_independent_one(browser_page, pc, pb, rate, lane, bay):
    page, errors = browser_page
    got = page.evaluate("([pc, pb, r, l, b]) => { const e = Explorer.evaluate(pc, pb, r, l, b); return [e.verdict, e.mean]; }",
                        [pc, pb, rate, lane, bay])
    want_verdict, want_mean = reference(pc, pb, rate, lane, bay)
    assert got[1] == pytest.approx(want_mean, rel=1e-9, abs=1e-6) and got[0] == want_verdict
    assert errors == []


def test_the_page_renders_a_verdict_and_reacts_to_the_controls(browser_page):
    page, _ = browser_page
    page.evaluate("() => { const s = document.getElementById('pbus'); s.value = 80; s.dispatchEvent(new Event('input')); }")
    heavy = page.inner_text("#verdict-title")
    page.evaluate("() => { const s = document.getElementById('pbus'); s.value = 3; s.dispatchEvent(new Event('input')); }")
    light = page.inner_text("#verdict-title")
    assert light == "המפרץ עדיף"
    assert page.locator("#map .c").count() == 72 and heavy != ""
