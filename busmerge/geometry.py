"""Planar geometry shared by the training env, the physical checks and the plots.

Convention used by the physics (``Vehicle.position``): the **front bumper**. A vehicle of length L
occupies [position - L, position] along the road. ``rect_corners`` takes a *centre*; use
``vehicle_corners`` when starting from a physics position.
"""
from __future__ import annotations

import numpy as np


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
        cur_inside = float(np.cross(edge, cur - a)) <= 0.0
        nxt_inside = float(np.cross(edge, nxt - a)) <= 0.0
        if cur_inside:
            out.append(cur)
        if cur_inside != nxt_inside:
            denom = float(np.cross(edge, nxt - cur))
            if abs(denom) > 1e-12:
                t = float(np.cross(edge, a - cur)) / denom
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
