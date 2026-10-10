"""Planar geometry shared by the training env, the physical checks and the plots.

Convention used by the physics (``Vehicle.position``): the **front bumper**. A vehicle of length L
occupies [position - L, position] along the road. ``rect_corners`` takes a *centre*; use
``vehicle_corners`` when starting from a physics position.
"""
from __future__ import annotations

import numpy as np

from busmerge.rl.merge_constants import (
    BAY_ENTRY_TAPER_M, BAY_EXIT_TAPER_M, BAY_FLAT_END_X, BAY_FLAT_START_X, BUS_EXIT_ROOM_M,
    BUS_STOP_MARGIN_M, LANE_WIDTH,
)

ROAD_EDGE_Y = LANE_WIDTH / 2.0             # the dashed centre line; beyond it is the opposing lane
KERB_Y = -LANE_WIDTH / 2.0                 # kerb between the lane and the pavement / bay
BAY_WALL_Y = KERB_Y - LANE_WIDTH           # back wall of the bay (one lane width deep)
# Where a taper meets the plain kerb, the kerb has a corner pointing into the road. A body side can pass
# over such a corner with all four of its own corners still on the road, so these points are checked
# against the body as well (busmerge.invariants).
KERB_CORNERS = np.array([[BAY_FLAT_START_X - BAY_ENTRY_TAPER_M, KERB_Y],
                         [BAY_FLAT_END_X + BAY_EXIT_TAPER_M, KERB_Y]])


def _cross(u, v) -> float:
    """z-component of the cross product of two 2-D vectors (np.cross on 2-D input is deprecated)."""
    return float(u[0] * v[1] - u[1] * v[0])


def rect_corners(cx: float, cy: float, half_l: float, half_w: float,
                  angle_rad: float) -> np.ndarray:
    """Return (4,2) array of rectangle corners rotated by angle_rad."""
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    dx = np.array([ half_l,  half_l, -half_l, -half_l], dtype=np.float64)
    dy = np.array([ half_w, -half_w, -half_w,  half_w], dtype=np.float64)
    xs = cx + dx * c - dy * s
    ys = cy + dx * s + dy * c
    return np.stack([xs, ys], axis=1)


def clip_polygon_by_half_plane(poly: np.ndarray,
                                a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Sutherland-Hodgman clip — keeps vertices on the right side of directed edge a→b.
    Our rectangles use clockwise winding, so interior = right of each edge (cross <= 0)."""
    if len(poly) == 0:
        return poly
    out = []
    n = len(poly)
    edge = b - a
    for i in range(n):
        cur = poly[i]
        nxt = poly[(i + 1) % n]
        # CW winding: inside = right of edge = cross product <= 0
        cur_inside = _cross(edge, cur - a) <= 0.0
        nxt_inside = _cross(edge, nxt - a) <= 0.0
        if cur_inside:
            out.append(cur)
        if cur_inside != nxt_inside:
            denom = _cross(edge, nxt - cur)
            if abs(denom) > 1e-12:
                t = _cross(edge, a - cur) / denom
                out.append(cur + t * (nxt - cur))
    return np.array(out, dtype=np.float64) if out else np.empty((0, 2))


def polygon_area(poly: np.ndarray) -> float:
    """Shoelace formula for a convex polygon (4+ vertices)."""
    if len(poly) < 3:
        return 0.0
    n = len(poly)
    xs, ys = poly[:, 0], poly[:, 1]
    return 0.5 * abs(
        float(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)))
    )


def compute_sat_overlap_area(bus_corners: np.ndarray,
                             car_corners: np.ndarray) -> float:
    """
    Area (m²) of the intersection of two convex rectangles.
    Returns 0.0 when they do not overlap.
    Uses Sutherland-Hodgman clipping of bus polygon against each edge of car.
    """
    clip = bus_corners.copy()
    n = len(car_corners)
    for i in range(n):
        if len(clip) == 0:
            return 0.0
        a = car_corners[i]
        b = car_corners[(i + 1) % n]
        clip = clip_polygon_by_half_plane(clip, a, b)
    return polygon_area(clip)


def vehicle_corners(front_x: float, lateral: float, length: float, width: float,
                    heading_rad: float) -> np.ndarray:
    """Corners of a vehicle given its front-bumper position (the physics convention)."""
    return rect_corners(front_x - length / 2.0, lateral, length / 2.0, width / 2.0, heading_rad)


def road_lower_edge(x):
    """Lowest drivable y at road position ``x``: the kerb, or the bay wall where the bay is (numpy-aware)."""
    x = np.asarray(x, dtype=float)
    entry_start = BAY_FLAT_START_X - BAY_ENTRY_TAPER_M
    exit_end = BAY_FLAT_END_X + BAY_EXIT_TAPER_M
    depth = KERB_Y - BAY_WALL_Y
    edge = np.full_like(x, KERB_Y)
    entering = (x > entry_start) & (x < BAY_FLAT_START_X)
    edge = np.where(entering, KERB_Y - depth * (x - entry_start) / BAY_ENTRY_TAPER_M, edge)
    edge = np.where((x >= BAY_FLAT_START_X) & (x <= BAY_FLAT_END_X), BAY_WALL_Y, edge)
    leaving = (x > BAY_FLAT_END_X) & (x < exit_end)
    edge = np.where(leaving, BAY_WALL_Y + depth * (x - BAY_FLAT_END_X) / BAY_EXIT_TAPER_M, edge)
    return edge


def body_corners_xy(front_x, lateral, length, width, heading_rad):
    """(n, 4) corner x and y of n bodies (numpy-aware; front-bumper convention, rotated by the heading)."""
    front_x, lateral, length, width, heading_rad = np.broadcast_arrays(
        *(np.atleast_1d(np.asarray(a, dtype=float)) for a in (front_x, lateral, length, width, heading_rad)))
    half_l, half_w = length / 2.0, width / 2.0
    cx, cy = front_x - half_l, lateral
    c, s = np.cos(heading_rad)[:, None], np.sin(heading_rad)[:, None]
    dx = np.array([1, 1, -1, -1])[None, :] * half_l[:, None]
    dy = np.array([1, -1, -1, 1])[None, :] * half_w[:, None]
    return cx[:, None] + dx * c - dy * s, cy[:, None] + dx * s + dy * c


def kerb_corner_depth(front_x, lateral, length, width, heading_rad) -> np.ndarray:
    """How far the deepest kerb corner (KERB_CORNERS) lies inside each body; negative = outside."""
    front_x, lateral, length, width, heading_rad = np.broadcast_arrays(
        *(np.atleast_1d(np.asarray(a, dtype=float)) for a in (front_x, lateral, length, width, heading_rad)))
    half_l, half_w = length / 2.0, width / 2.0
    cx, cy = front_x - half_l, lateral
    c, s = np.cos(heading_rad), np.sin(heading_rad)
    depth = np.full(len(cx), -np.inf)
    for px, py in KERB_CORNERS:
        u = (px - cx) * c + (py - cy) * s          # the corner in the body frame
        w = -(px - cx) * s + (py - cy) * c
        depth = np.maximum(depth, np.minimum(half_l - np.abs(u), half_w - np.abs(w)))
    return depth


def road_edge_excess(front_x, lateral, length, width, heading_rad) -> tuple[np.ndarray, np.ndarray]:
    """How far each body reaches past the road edges (numpy-aware; > 0 = past the edge).

    ``below``: a corner below the kerb or the bay wall, or a kerb corner inside the body.
    ``above``: a corner over the centre line. The physics checks and the training start poses both
    use this, so "on the road" means one thing everywhere.
    """
    xs, ys = body_corners_xy(front_x, lateral, length, width, heading_rad)
    below = np.maximum((road_lower_edge(xs) - ys).max(axis=1),
                       kerb_corner_depth(front_x, lateral, length, width, heading_rad))
    above = (ys - ROAD_EDGE_Y).max(axis=1)
    return below, above


def bus_stop_range(bus_length: float) -> tuple[float, float]:
    """Front-bumper positions where a stopped bus is wholly in the flat part of the bay with room
    ahead to steer out (the app's stop targets and the training start poses)."""
    return (BAY_FLAT_START_X + bus_length + BUS_STOP_MARGIN_M, BAY_FLAT_END_X - BUS_EXIT_ROOM_M)


def bay_outline() -> np.ndarray:
    """The bay as drawn and as checked: the road edge from the start of the entry taper, along the bay
    wall, to the end of the exit taper (the polyline ``road_lower_edge`` follows). Closing it along
    the kerb gives the bay's area."""
    return np.array([[BAY_FLAT_START_X - BAY_ENTRY_TAPER_M, KERB_Y], [BAY_FLAT_START_X, BAY_WALL_Y],
                     [BAY_FLAT_END_X, BAY_WALL_Y], [BAY_FLAT_END_X + BAY_EXIT_TAPER_M, KERB_Y]])


def bay_pull_in_target(front_x: float) -> float:
    """Lateral target of a bus pulling into the bay, read off the drawn road edge.

    The lane centre shifted down by as much as the road edge has dropped under the bus's front
    bumper: like a driver tracking the kerb with the front corner, the bus keeps the clearance to the
    edge it had in the lane, turns in along the entry taper and ends at the bay centre (BAY_DEPTH).
    """
    return float(road_lower_edge(front_x)) - KERB_Y
