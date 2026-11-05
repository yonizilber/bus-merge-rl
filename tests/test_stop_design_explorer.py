"""The interactive explorer (docs/tools/stop_design_explorer.he.html) says what the stored measurements say.

- Its embedded table reproduces the published summary of the first experiment (same cars in both designs).
- The numbers of its written summary are recomputed from the table, independently of the builder.
- The dwell model (passengers, doors, accuracy penalties) and the calculation that run in the browser agree with
  independent ones here, on and between grid points.
- Dwell time can be 0 (no passengers), the car-occupancy range of the page is the Israeli one (1.2 to 1.5), and the bay
  and lane stops are treated as the same in the simulation (no entry or alignment difference) with the field-based
  extras as visible, adjustable defaults.
"""
import json
import math
import re

import pytest

from busmerge.paths import REPO_ROOT

PAGE_PATH = REPO_ROOT / "docs" / "tools" / "stop_design_explorer.he.html"
PAGE = PAGE_PATH.read_text(encoding="utf-8")
DATA = json.loads(re.search(r"const DATA = (\{.*?\});\n", PAGE, re.S).group(1))
SUMMARY = json.loads((REPO_ROOT / "results" / "experiments" / "stop_design_v1" / "summary.json").read_text())
GEOM = json.loads((REPO_ROOT / "results" / "experiments" / "stop_design_v2" / "stop_geometry.json").read_text())
RATES, DWELLS = DATA["rates"], DATA["dwells"]


def pair(rate, lane, bay):
    return DATA["pairs"][f"{rate:g}"][str(lane)][str(bay)]


def verdict(pc, pb, v, extra=0.0):
    n, a, b, va, vb, c = v
    a += extra
    mean = pb * a + pc * b
    se = 1.96 * math.sqrt((pb * pb * va + pc * pc * vb + 2 * pb * pc * c) / n)
    return ("bay" if mean + se < 0 else "lane" if mean - se > 0 else "tie"), mean


def test_the_dwell_axis_starts_at_zero_and_covers_the_first_experiment():
    assert DWELLS[0] == 0 and DWELLS[-1] == 45 and 10 in DWELLS and 6 in DWELLS
    assert RATES == [0.1, 0.2, 0.3, 0.4, 0.5]


def test_every_pairing_is_stored_with_a_sensible_number_of_seeds():
    for r in RATES:
        for lane in DWELLS:
            for bay in DWELLS:
                n = pair(r, lane, bay)[0]
                assert n in (150, 300), (r, lane, bay, n)        # 150 pairs across the experiments, 300 within the first


def test_the_table_reproduces_the_published_summary_of_the_first_experiment():
    for cell in SUMMARY["cells"]:
        n, a, b, *_ = pair(cell["traffic_rate"], cell["dwell_s"], cell["dwell_s"])
        assert n == cell["pairs"] == 300
        assert a == pytest.approx(cell["delta_bus_time_s"], abs=0.01)
        assert b == pytest.approx(cell["delta_cars_time_s"], abs=0.051)       # the summary rounds to 0.1 s
        assert 50 * a + 1.2 * b == pytest.approx(cell["delta_pt_mean"], abs=0.1)


def test_a_stop_with_no_passengers_only_hurts_the_bay():
    """Dwell 0 and 3 s: nobody stands in the lane for long, so the bay saves the cars nothing (it slows them when the
    bus merges back, up to about 12 vehicle-minutes in a run at 0.5 cars/s) and still costs the bus its merge."""
    for dwell in (0, 3):
        for r in RATES:
            n, a, b, *_ = pair(r, dwell, dwell)
            assert a > 0 and b > 0, (dwell, r)
            for pc in (1.0, 1.35, 2.0):
                for pb in range(2, 81):
                    assert verdict(pc, pb, pair(r, dwell, dwell))[0] != "bay", (dwell, r, pc, pb)
    assert pair(0.5, 0, 0)[2] / 60 > 10                  # "about 12 vehicle-minutes": 738 s at 0.5 cars/s and no stop


def test_fewer_bus_passengers_never_make_the_lane_relatively_better():
    """ΔPT is linear in the bus load with slope a > 0: an emptier bus can only move the verdict toward the bay."""
    for r in RATES:
        for d in DWELLS:
            assert pair(r, d, d)[1] > 0
            means = [verdict(1.35, pb, pair(r, d, d))[1] for pb in (5, 20, 50, 80)]
            assert means == sorted(means)


def test_the_simulation_gives_the_two_designs_the_same_arrival_geometry():
    """Measured, not assumed: no extra time to enter the bay and no extra misalignment (hence the page's field-based extras)."""
    assert abs(GEOM["arrival_time_from_braking_s"]["bay_minus_lane_mean"]) < 0.1
    assert abs(GEOM["distance_from_stop_pole_m"]["bay_mean"] - GEOM["distance_from_stop_pole_m"]["lane_mean"]) < 0.1
    assert abs(GEOM["gap_between_bus_side_and_pavement_edge_m"]["bay_mean"] - GEOM["gap_between_bus_side_and_pavement_edge_m"]["lane_mean"]) < 0.1
    assert DATA["geometry"]["entry_s"] == GEOM["arrival_time_from_braking_s"]["bay_minus_lane_mean"]


# --- the dwell model, independently of the page's code -----------------------------------------------------------
ADV = dict(fixed=4, tpax=3.0, m2=0.7, m3=0.6, longPen=0.4, latPen=0.05)


def door_mult(doors):
    return {1: 1.0, 2: ADV["m2"], 3: ADV["m3"]}[doors]


def base_dwell(npax, doors):
    return 0.0 if npax <= 0 else ADV["fixed"] + npax * ADV["tpax"] * door_mult(doors)


def geometry_penalty(npax, doors, dev, gap):
    m = door_mult(doors)
    return ADV["longPen"] * dev * m + ADV["latPen"] * npax * m * (gap / 0.1)


@pytest.mark.parametrize("npax,doors", [(0, 2), (1, 1), (6, 2), (6, 1), (10, 3), (30, 1)])
def test_the_default_dwell_times_follow_the_stated_model(npax, doors):
    g = DATA["geometry"]
    base = base_dwell(npax, doors)
    lane = min(45, max(0, base + geometry_penalty(npax, doors, g["dev_lane_m"], g["gap_lane_m"])))
    bay = min(45, max(0, base + geometry_penalty(npax, doors, g["dev_bay_m"] + 1.0, g["gap_bay_m"] + 0.4)))
    assert bay >= lane                                   # the defaults make the bay stop no shorter than the lane stop
    if npax == 0:
        assert base == 0


def test_more_doors_shorten_the_stop():
    assert base_dwell(10, 1) > base_dwell(10, 2) > base_dwell(10, 3) > 0


def test_the_israeli_car_occupancy_range_is_on_the_page():
    assert 'id="pcar" min="1" max="2" step="0.05" value="1.35"' in PAGE         # the default is the middle of 1.2 to 1.5
    assert '$("pcar-band").style.left = "20%"; $("pcar-band").style.right = "50%"' in PAGE   # the band is 1.2 to 1.5 of 1 to 2
    assert 1.2 < 1.35 < 1.5 and (1.2 + 1.5) / 2 == pytest.approx(1.35)


def test_the_summary_sentences_are_the_recomputed_numbers():
    eq = {(r, d): pair(r, d, d) for r in RATES for d in DWELLS}
    a_all = [v[1] for v in eq.values()]
    assert f'<span class="num">{min(a_all):.1f}</span> עד <span class="num">{max(a_all):.1f}</span> שניות לנסיעה' in PAGE
    counts = {"bay": 0, "lane": 0, "tie": 0}
    for v in eq.values():
        counts[verdict(1.35, 20.0, v)[0]] += 1
    assert f'המפרץ עדיף ב-<span class="num">{counts["bay"]}</span>, הנתיב ב-<span class="num">{counts["lane"]}</span>' in PAGE
    assert f'<span class="num">{len(eq)}</span> הצירופים' in PAGE
    n, a, b, *_ = pair(0.3, 15, 15)
    assert f'<span class="num">0.3</span> מכוניות לשנייה המפרץ עדיף כשבאוטובוס פחות מכ-<span class="num">{-1.35 * b / a:.0f}</span> נוסעים' in PAGE
    assert f'עד כ-<span class="num">{pair(0.5, 0, 0)[2] / 60:.0f}</span> דקות רכב בהרצה אחת' in PAGE
    assert not re.search(r"\[\[[a-z_0-9]+\]\]", PAGE)      # no token was left unfilled


# --- the browser -------------------------------------------------------------------------------------------------
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
        page.goto(PAGE_PATH.as_uri())
        page.wait_for_function("window.Explorer !== undefined")
        yield page, errors
        browser.close()


def reference(pc, pb, rate, lane, bay, extra):
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
    return verdict(pc, pb, out, extra)


@pytest.mark.parametrize("pc,pb,rate,lane,bay,extra", [
    (1.2, 50, 0.3, 15, 15, 0), (1.5, 20, 0.5, 45, 45, 0), (1.7, 10.7, 0.1, 0, 0, 0),         # grid points
    (1.35, 20, 0.33, 4, 9, 1.0), (1.2, 35, 0.47, 12, 38, 0), (1.5, 5, 0.15, 44, 2, -0.5)])  # between grid points
def test_the_browser_calculation_matches_an_independent_one(browser_page, pc, pb, rate, lane, bay, extra):
    page, errors = browser_page
    got = page.evaluate("([pc, pb, r, l, b, e]) => { const x = Explorer.evaluate(pc, pb, r, l, b, e); return [x.verdict, x.mean]; }",
                        [pc, pb, rate, lane, bay, extra])
    want_verdict, want_mean = reference(pc, pb, rate, lane, bay, extra)
    assert got[1] == pytest.approx(want_mean, rel=1e-9, abs=1e-6) and got[0] == want_verdict
    assert errors == []


@pytest.mark.parametrize("npax,doors", [(0, 2), (6, 2), (6, 1), (10, 3)])
def test_the_browser_dwell_model_matches_the_one_here(browser_page, npax, doors):
    page, _ = browser_page
    got = page.evaluate("([n, d]) => { const A = Explorer.DEFAULT_ADV; const S = {mode: 'pax', npax: n, doors: d};"
                        " return Explorer.dwells(S, A); }", [npax, doors])
    g = DATA["geometry"]
    base = base_dwell(npax, doors)
    assert got["base"] == pytest.approx(base)
    assert got["lane"] == pytest.approx(min(45, base + geometry_penalty(npax, doors, g["dev_lane_m"], g["gap_lane_m"])))
    assert got["bay"] == pytest.approx(min(45, base + geometry_penalty(npax, doors, g["dev_bay_m"] + 1.0, g["gap_bay_m"] + 0.4)))


@pytest.mark.parametrize("link", ["free", "same", "pen"])
def test_a_directly_chosen_dwell_time_follows_the_link_between_the_designs(browser_page, link):
    """Lane time as typed; bay time independent (free), equal (same), or the lane's plus the bay's extra accuracy penalty (pen)."""
    page, _ = browser_page
    got = page.evaluate("([link]) => Explorer.dwells({mode: 'direct', link, dLane: 8, dBay: 14, npax: 6, doors: 2}, Explorer.DEFAULT_ADV)", [link])
    g = DATA["geometry"]
    extra = (geometry_penalty(6, 2, g["dev_bay_m"] + 1.0, g["gap_bay_m"] + 0.4) - geometry_penalty(6, 2, g["dev_lane_m"], g["gap_lane_m"]))
    assert got["lane"] == pytest.approx(8)
    assert got["bay"] == pytest.approx({"free": 14, "same": 8, "pen": 8 + extra}[link])
    assert extra > 0                                    # with the default assumptions the bay stop is the less precise one


def test_the_dwell_controls_switch_between_passengers_and_seconds(browser_page):
    page, errors = browser_page
    page.click("#dmode button[data-m=direct]")
    assert page.is_visible("#dsecs") and page.is_disabled("#dbay")                 # default link: same + the bay's penalty
    page.click("#dlink button[data-l=free]")
    assert not page.is_disabled("#dbay")
    page.evaluate("() => { const a = document.getElementById('dlane'); a.value = 5; a.dispatchEvent(new Event('input'));"
                  " const b = document.getElementById('dbay'); b.value = 20; b.dispatchEvent(new Event('input')); }")
    assert "5.0" in page.inner_text("#dw-v") and "20.0" in page.inner_text("#dw-v")
    page.click("#dlink button[data-l=same]")
    assert page.is_disabled("#dbay") and page.input_value("#dbay") == "5"
    page.click("#dmode button[data-m=pax]")
    assert not page.is_visible("#dsecs")
    assert errors == []


def test_the_page_renders_and_reacts_to_the_controls(browser_page):
    page, errors = browser_page
    page.evaluate("() => { const s = document.getElementById('pbus'); s.value = 3; s.dispatchEvent(new Event('input')); }")
    light = page.inner_text("#verdict-title")
    assert light == "המפרץ עדיף"
    assert page.locator("#map .c").count() == 9 * len(DWELLS)
    assert page.locator("#advgrid input").count() == 11
    assert errors == []
