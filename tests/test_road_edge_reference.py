"""The road-edge check agrees with a brute-force reference (#14).

`geometry.road_edge_excess` decides whether a body is off the road from its four corners plus the
kerb corners (the kerb corners that point into the road). The reference ignores that reasoning: it
walks the body outline in 1 cm steps and asks how far any point lies beyond an edge. Random poses
are drawn where the edge is hardest: around the entry and exit tapers and the bay, at bay depth or in
the lane, turned up to ±20°. A small band around the 2 cm tolerance is left unjudged, because the two
measure depth differently (vertical distance versus distance inside the body).
"""
import numpy as np
import pytest

from busmerge.geometry import ROAD_EDGE_Y, body_corners_xy, road_edge_excess, road_lower_edge
from busmerge.invariants import OFF_ROAD_TOLERANCE_M

BAND_M = 0.03        # judged only when the reference is this far from the tolerance


def _reference(front_x, lateral, length, width, heading):
    """Deepest point of the body outline below the kerb / bay wall, and above the centre line."""
    xs, ys = body_corners_xy(front_x, lateral, length, width, heading)
    corners = np.stack([xs[0], ys[0]], axis=1)
    points = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        n = int(np.ceil(np.hypot(*(b - a)) / 0.01)) + 1
        t = np.linspace(0.0, 1.0, n)[:, None]
        points.append(a + t * (b - a))
    p = np.concatenate(points)
    return float((road_lower_edge(p[:, 0]) - p[:, 1]).max()), float((p[:, 1] - ROAD_EDGE_Y).max())


@pytest.mark.parametrize("length,width", [(11.0, 2.5), (4.5, 1.8)], ids=["bus", "car"])
def test_road_edge_check_agrees_with_a_dense_outline_reference(length, width):
    rng = np.random.default_rng(14)
    judged = corners_only_would_miss = 0
    for _ in range(1500):
        front_x = rng.uniform(255.0, 345.0)
        lateral = rng.uniform(-5.0, 1.0)
        heading = np.radians(rng.uniform(-20.0, 20.0))
        below, above = road_edge_excess(front_x, lateral, length, width, heading)
        ref_below, ref_above = _reference(front_x, lateral, length, width, heading)
        xs, ys = body_corners_xy(front_x, lateral, length, width, heading)
        if ref_below > OFF_ROAD_TOLERANCE_M + BAND_M and (road_lower_edge(xs) - ys).max() <= OFF_ROAD_TOLERANCE_M:
            corners_only_would_miss += 1
        for checker, ref in ((below[0], ref_below), (above[0], ref_above)):
            if ref > OFF_ROAD_TOLERANCE_M + BAND_M:
                assert checker > OFF_ROAD_TOLERANCE_M, (front_x, lateral, np.degrees(heading), checker, ref)
                judged += 1
            elif ref < OFF_ROAD_TOLERANCE_M - BAND_M:
                assert checker <= OFF_ROAD_TOLERANCE_M, (front_x, lateral, np.degrees(heading), checker, ref)
                judged += 1
    assert judged > 2500
    if length > 10.0:   # the sample contains cases a four-corner check misses (BUGS P14)
        assert corners_only_would_miss > 0


def test_the_reference_sees_the_kerb_corner_that_four_corners_miss():
    # The case that motivated the kerb corners (BUGS P14): nose down 5° across the start of the entry
    # taper. All four corners are on the road, but the outline crosses the kerb corner.
    ref_below, _ = _reference(270.5, -0.8, 11.0, 2.5, np.radians(-5.0))
    xs, ys = body_corners_xy(270.5, -0.8, 11.0, 2.5, np.radians(-5.0))
    assert (ys >= road_lower_edge(xs)).all() and ref_below > 0.2
