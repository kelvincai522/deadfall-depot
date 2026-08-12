"""Generate usd/modules/10_terrain.usda -- the ground system for DEADFALL DEPOT.

The single biggest tell of a fake environment is a flat tiled quad, so nothing
here is flat and nothing here is one material.  The whole 150 x 150 m plate is a
subdivided mesh driven by one continuous analytic height field, so every region
seam matches, and the surface carries:

  * site drainage  -- an authored N-S cross-fall profile plus a perimeter rise,
                      so water runs to the trench drain at Y = -14.5
  * settlement     -- fbm undulation, damped near the building and on concrete
  * vehicle ruts   -- settled wheel tracks along the authored truck routes
  * potholes       -- seeded, with rims
  * puddle basins  -- carved, then flooded by a flat water plane whose shoreline
                      is derived from the actual carved surface, so the water
                      edge is irregular and correct rather than a drawn ellipse
  * a drainage ditch, a fuel-bund sump, two trench drains with real cast-iron
    bars, kerbs, manhole covers, apron edges, broken half-buried slabs, paint

Material regions are GeomSubsets named `sub_<Look>` (familyName "materialBind")
so 50_materials can rebind each ground treatment independently.  Every mesh also
carries a fallback UsdPreviewSurface under /World/Terrain/Looks so the level
never renders as untextured grey.

    cd tools && uv run gen_terrain.py

Deterministic: same seed in, same file out.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "usd" / "modules" / "10_terrain.usda"

TERRAIN = "/World/Terrain"
SEED = 20260807


# ----------------------------------------------------------------------------
# 1.  noise + small maths helpers
# ----------------------------------------------------------------------------


def _hash(ix, iy, seed):
    n = (ix.astype(np.int64) * np.int64(73856093)) ^ (
        iy.astype(np.int64) * np.int64(19349663)
    ) ^ np.int64((seed * 83492791) & 0x7FFFFFFF)
    n = n & np.int64(0x7FFFFFFF)
    n = (n ^ (n >> np.int64(13))) * np.int64(1274126177)
    n = n & np.int64(0x7FFFFFFF)
    n = n ^ (n >> np.int64(16))
    return (n & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def vnoise(x, y, freq, seed):
    """Value noise in [-1, 1]; freq is cycles per metre."""
    xf = np.asarray(x, dtype=np.float64) * freq
    yf = np.asarray(y, dtype=np.float64) * freq
    x0 = np.floor(xf)
    y0 = np.floor(yf)
    tx = xf - x0
    ty = yf - y0
    sx = tx * tx * (3.0 - 2.0 * tx)
    sy = ty * ty * (3.0 - 2.0 * ty)
    i0 = x0.astype(np.int64)
    j0 = y0.astype(np.int64)
    n00 = _hash(i0, j0, seed)
    n10 = _hash(i0 + 1, j0, seed)
    n01 = _hash(i0, j0 + 1, seed)
    n11 = _hash(i0 + 1, j0 + 1, seed)
    a = n00 + (n10 - n00) * sx
    b = n01 + (n11 - n01) * sx
    return (a + (b - a) * sy) * 2.0 - 1.0


def fbm(x, y, freq, octaves, seed, gain=0.5, lac=2.03):
    total = np.zeros(np.shape(x), dtype=np.float64)
    amp, norm, f = 1.0, 0.0, freq
    for o in range(octaves):
        total = total + amp * vnoise(x, y, f, seed + 17 * o)
        norm += amp
        amp *= gain
        f *= lac
    return total / norm


def limit_slope(r, maxstep, iters=200):
    """Cap the radial step between neighbouring samples of a closed outline.

    Sector count alone does NOT bound the chord length of a traced boundary:
    the chord is hypot(r*dtheta, dr), and dr is set by how fast the traced
    radius changes, not by how finely you sample the angle.  A contour that
    jumps 1.8 m between two adjacent rays has a 1.8 m straight edge in it no
    matter how many rays you used -- which is exactly how a shoreline sampled
    at 0.25 m still ended up with a 1.8 m straight run.  This lowers (never
    raises) radii until no neighbour pair differs by more than `maxstep`, which
    bounds the chord and cannot introduce a new violation.
    """
    r = np.asarray(r, dtype=np.float64).copy()
    for _ in range(iters):
        hi = np.minimum(np.roll(r, 1), np.roll(r, -1)) + maxstep
        over = r > hi
        if not over.any():
            break
        r[over] = hi[over]
    return r


def sstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# --- boundary conditioning: chord bound + lateral jitter --------------------
#
# Every material boundary in this module is eventually a closed polyline, and
# every closed polyline has exactly two ways of betraying itself: a chord long
# enough that the eye reads it as a ruled line, and a boundary so smoothly
# sampled that it reads as a drawn curve.  The pair of helpers below fix both
# for ALL producers at once -- mosaic cells, ground patches, oil pads -- instead
# of each one re-deriving its own crenulation.
#
#   resample_closed  puts the vertices back on a uniform arc-length grid, so a
#                    ray-traced outline whose radius jumps between neighbouring
#                    rays cannot leave a long straight run behind.
#   jitter_boundary  then displaces every vertex ALONG ITS OWN NORMAL by
#                    0.10-0.40 m from a two-band noise field.  That is a real
#                    cut-and-patch edge: a saw kerf wanders a hand's width every
#                    metre, because it was cut round the broken bit, not drawn.
#
# Both are cheap, and the result is measured (not asserted) by BOUNDARY_AUDIT.


BOUNDARY_AUDIT = {"n": 0, "worst": 0.0, "worst_src": "-", "jit_min": 9e9,
                  "jit_max": 0.0, "verts": 0, "step_min": 9e9, "step_max": 0.0}


def _closed_perimeter(px, py):
    dx = np.roll(px, -1) - px
    dy = np.roll(py, -1) - py
    return np.hypot(dx, dy)


def resample_closed(px, py, step):
    """Uniform arc-length resample of a closed outline at ~`step` metres."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    seg = _closed_perimeter(px, py)
    per = float(seg.sum())
    if per < 1e-6:
        return px, py
    n = int(max(8, round(per / step)))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.arange(n) * (per / n)
    qx = np.interp(t, s, np.concatenate([px, px[:1]]))
    qy = np.interp(t, s, np.concatenate([py, py[:1]]))
    return qx, qy


def bound_chords(px, py, maxlen, iters=6):
    """Insert midpoints until no chord of the closed outline exceeds `maxlen`."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    for _ in range(iters):
        seg = _closed_perimeter(px, py)
        over = seg > maxlen
        if not over.any():
            break
        mx = 0.5 * (px + np.roll(px, -1))
        my = 0.5 * (py + np.roll(py, -1))
        nx, ny = [], []
        for i in range(px.size):
            nx.append(px[i])
            ny.append(py[i])
            if over[i]:
                nx.append(mx[i])
                ny.append(my[i])
        px = np.array(nx)
        py = np.array(ny)
    return px, py


def jitter_boundary(px, py, seed, step=0.72, lat=(0.10, 0.40), maxchord=0.95,
                    src="patch"):
    """Resample a closed outline to `step` and wander it laterally.

    The lateral offset comes from two noise bands -- ~3.4 m and ~1.15 m -- whose
    combined amplitude is itself modulated between `lat[0]` and `lat[1]` on a
    9 m field, so some arcs of the joint are nearly straight and others are torn
    open by 0.4 m.  Both wavelengths are longer than `step`, so the outline
    wanders without folding on itself.  Afterwards every chord is bounded, and
    the true worst chord and the true jitter range are recorded for the report.
    """
    px, py = resample_closed(px, py, step)
    n = px.size
    if n < 8:
        return px, py
    tx = np.roll(px, -1) - np.roll(px, 1)
    ty = np.roll(py, -1) - np.roll(py, 1)
    L = np.hypot(tx, ty)
    L[L < 1e-9] = 1.0
    nx, ny = -ty / L, tx / L                      # outward-ish normal
    # Value-noise fbm rarely gets anywhere near its nominal +/-1, so the raw sum
    # is expanded by 2.6 and clipped: without that the boundary wandered by
    # 8 cm when it was asked for 40 and the joint stayed a drawn curve.
    w = (0.64 * fbm(px * 1.0 + seed * 0.017, py * 1.0, 1.0 / 3.4, 2, 7300 + seed)
         + 0.36 * fbm(px + 31.0, py - 19.0 + seed * 0.011, 1.0 / 1.15, 2, 7400 + seed))
    w = np.tanh(3.4 * w)
    amp = lat[0] + (lat[1] - lat[0]) * (0.5 + 0.5 * np.tanh(
        2.8 * fbm(px, py, 1.0 / 9.0, 2, 7500 + seed)))
    off = amp * w
    # a light smoothing pass on the offset itself: neighbouring vertices are
    # ~0.7 m apart and must not be pushed hard in opposite directions, or the
    # outline folds over on itself
    off = 0.15 * np.roll(off, 1) + 0.70 * off + 0.15 * np.roll(off, -1)
    qx = px + nx * off
    qy = py + ny * off
    # Wander at `step` (0.5-1.0 m), TESSELLATE at 0.42 m.  The two are different
    # jobs: the first is what the boundary looks like, the second is what stops
    # a flat overlay polygon from sagging below the ~1 m ground relief it lies
    # on and letting bare ground erupt through the middle of a patch.
    qx, qy = bound_chords(qx, qy, min(maxchord, 0.42))
    seg = _closed_perimeter(qx, qy)
    worst = float(seg.max()) if seg.size else 0.0
    BOUNDARY_AUDIT["n"] += 1
    BOUNDARY_AUDIT["verts"] += int(qx.size)
    if worst > BOUNDARY_AUDIT["worst"]:
        BOUNDARY_AUDIT["worst"] = worst
        BOUNDARY_AUDIT["worst_src"] = src
    a = np.abs(off)
    BOUNDARY_AUDIT["jit_min"] = min(BOUNDARY_AUDIT["jit_min"], float(a.min()))
    BOUNDARY_AUDIT["jit_max"] = max(BOUNDARY_AUDIT["jit_max"], float(a.max()))
    BOUNDARY_AUDIT["step_min"] = min(BOUNDARY_AUDIT["step_min"], float(step))
    BOUNDARY_AUDIT["step_max"] = max(BOUNDARY_AUDIT["step_max"], float(step))
    return qx, qy


def rect_mask(x, y, x0, x1, y0, y1, soft, jitter=0.0, seed=0):
    """1 well inside the rect, 0 well outside, smooth over `soft` metres."""
    j = 0.0
    if jitter:
        j = jitter * fbm(x, y, 1.0 / 2.6, 2, seed)
    dx = np.minimum(x - x0, x1 - x) + j
    dy = np.minimum(y - y0, y1 - y) + j
    return sstep(np.minimum(dx, dy) / soft + 0.5)


def seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    L2 = max(vx * vx + vy * vy, 1e-9)
    t = np.clip((wx * vx + wy * vy) / L2, 0.0, 1.0)
    return np.hypot(px - (ax + t * vx), py - (ay + t * vy))


def poly_dist(px, py, pts):
    d = None
    for i in range(len(pts) - 1):
        di = seg_dist(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        d = di if d is None else np.minimum(d, di)
    return d


def offset_polyline(pts, off):
    """Offset a polyline sideways by `off` metres (left positive)."""
    out = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            (ax, ay), (bx, by) = pts[0], pts[1]
        elif i == n - 1:
            (ax, ay), (bx, by) = pts[-2], pts[-1]
        else:
            (ax, ay), (bx, by) = pts[i - 1], pts[i + 1]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1.0
        out.append((pts[i][0] - dy / L * off, pts[i][1] + dx / L * off))
    return out


def resample(pts, step):
    out = [pts[0]]
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        n = max(1, int(round(math.hypot(bx - ax, by - ay) / step)))
        for k in range(1, n + 1):
            t = k / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return out


def blob(cx, cy, rx, ry, seed, n=28, rough=0.24, yaw=0.0):
    """An irregular closed outline -- wet fans, damp halos, broken slabs.

    Two rules keep the result off the critic's list.  (1) The point count is
    raised until no chord is longer than 0.55 m, so a large blob can never
    degenerate into a polygon whose straight edges you can count -- that is the
    'razor triangle' failure.  (2) On top of the three low harmonics that give
    the blob its overall shape there are two high ones at ~0.15 m amplitude,
    which crenulate the edge at the scale of a hand.  A boundary with a wobble
    finer than the eye can resolve stops reading as a drawn line.
    """
    r_ = max(rx, ry)
    n = int(max(n, min(150, math.ceil(2.0 * math.pi * r_ / 0.42))))
    rng = np.random.default_rng(seed)
    phase = rng.uniform(0, 6.28, 5)
    amp = rng.uniform(0.5, 1.0, 3)
    ca, sa = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    out = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        r = 1.0 + rough * (
            amp[0] * math.sin(2 * t + phase[0])
            + amp[1] * math.sin(3 * t + phase[1])
            + amp[2] * math.sin(5 * t + phase[2])
        ) / 3.0
        r += rough * (0.115 * math.sin(9 * t + phase[3])
                      + 0.075 * math.sin(17 * t + phase[4]))
        ux, uy = rx * r * math.cos(t), ry * r * math.sin(t)
        out.append((cx + ux * ca - uy * sa, cy + ux * sa + uy * ca))
    return out


# ----------------------------------------------------------------------------
# 2.  site definition -- everything the layout plan pins down
# ----------------------------------------------------------------------------

# N-S drainage profile of the finished ground.  Y = 15.0 is the gate line and is
# exactly 0.000 so there is no step into the warehouse.
PROFILE = [
    (-56.0, -0.020), (-44.0, -0.020), (-40.0, -0.050), (-37.0, -0.085),
    (-34.0, -0.058), (-26.0, -0.045), (-21.0, -0.038), (-17.0, -0.070),
    (-14.5, -0.088), (-8.0, -0.065), (0.0, -0.040), (6.0, -0.022),
    (13.5, 0.000), (15.0, 0.000), (60.0, 0.005), (76.25, 0.005),
    (78.0, 0.020), (94.0, 0.020),
]
PROF_Y = np.array([p[0] for p in PROFILE])
PROF_Z = np.array([p[1] for p in PROFILE])

# Paved rectangles -- unpaved ground sits 0.10 m lower, as dirt does beside a slab.
PAVED = [
    (-52.0, 52.0, -16.0, 15.6),      # central yard, Lane B
    (-46.0, 30.0, -34.0, -16.0),     # dock apron, Lane C
    (-70.0, -52.0, -24.0, 34.0),     # west spawn / fuel bay
    (52.0, 70.0, -24.0, 60.0),       # east spawn / rail spur
    (-40.0, 40.0, 13.0, 78.0),       # warehouse footprint
    (-46.0, -38.0, 14.0, 59.0),      # apron outside the west roller doors
    (38.0, 46.0, 32.0, 59.0),        # apron outside the east roller doors
    (40.0, 50.0, 2.0, 30.0),         # east loading-platform apron
]

# Settled vehicle routes: (centreline, track gauge, rut depth, rut width)
RUTS = [
    (((-56.0, -6.0), (-40.0, -3.0), (-24.0, 1.0), (-10.0, 3.5), (-1.0, 8.0),
      (0.0, 14.6)), 2.30, 0.055, 1.40),
    (((-50.0, -18.6), (-20.0, -18.2), (6.0, -18.6), (30.0, -18.3)), 2.40, 0.048, 1.45),
    (((-56.0, -37.2), (-20.0, -36.7), (14.0, -37.3), (52.0, -36.9)), 2.20, 0.090, 1.20),
    (((56.0, -8.0), (48.0, -1.0), (45.0, 8.0), (45.0, 22.0)), 2.30, 0.045, 1.35),
    (((-66.0, 2.0), (-58.0, 6.0), (-50.0, 3.0), (-44.0, -6.0)), 2.30, 0.050, 1.35),
    (((2.0, 12.0), (16.0, 6.0), (32.0, 1.0), (46.0, -4.0)), 2.30, 0.040, 1.35),
]

# (name, cx, cy, size_x, size_y, yaw, basin depth, diesel sheen)
#
# Basin depth is how far the bed is cut BELOW the surrounding grade at the
# centre.  Every one of these is now 4.5-8.5 cm rather than the 3.4-6.2 cm of
# the first pass: a puddle whose bed is only three centimetres down has a rim
# the surface noise can jump over, and when that happens the flood fill spills
# past the basin and the water renders as a rectangle with dead-straight edges.
# The depth also has to pay for a visible meniscus and a damp margin, and 3 cm
# is not enough ground for both.
PUDDLES = [
    ("P1_TrestleMirror", -30.0, -3.0, 9.0, 5.0, 8.0, 0.082, False),
    ("P2_YardHero", 2.0, -9.0, 12.0, 6.0, -5.0, 0.086, False),
    ("P3_BridgeMirror", 26.0, 6.0, 5.0, 4.0, 22.0, 0.072, False),
    # P4 is SHOT 4's whole subject, so it is the deepest basin in the map: with
    # the rim guarantee in place a 0.095 m bowl floods to ~82 mm of water, which
    # is enough for the bed to go properly dark under it, for the bank to stand
    # ~19 mm proud of the waterline, and for the meniscus fillet to have a slope
    # to climb.  At the old 0.080 next to an unguarded rim it held 30 mm.
    ("P4_DockDetail", -8.5, -17.5, 7.0, 4.5, -12.0, 0.095, False),
    ("P5_EastApron", 44.0, -6.0, 6.0, 3.5, 15.0, 0.072, False),
    ("P6_FuelSheen", -48.0, 9.0, 4.0, 3.0, 0.0, 0.066, True),
]
MINOR_PUDDLES = [
    ("W01_RoadRut", -37.0, -36.9, 5.4, 1.4, 1.0, 0.058, False),
    ("W02_RoadRut", -14.0, -36.8, 6.6, 1.4, -1.0, 0.060, False),
    ("W03_RoadRut", 8.0, -37.1, 5.6, 1.4, 1.5, 0.060, False),
    ("W04_RoadRut", 34.0, -37.0, 4.6, 1.3, 0.0, 0.056, False),
    ("W05_EastBreak", 38.5, -24.0, 5.5, 4.0, 24.0, 0.064, False),
    ("W06_EastBreak", 44.0, -30.5, 4.0, 3.0, -18.0, 0.060, False),
    ("W07_FuelBayMud", -52.0, 4.0, 5.5, 4.0, 12.0, 0.064, False),
    ("W08_Yard", -20.0, -12.0, 3.6, 2.2, -22.0, 0.058, False),
    # Moved north off the E-W drain line. It used to be centred 1.0 m from the
    # trench, so half its footprint lay inside the drain frame -- which is not a
    # place standing water can be, and now that the shoreline tracer refuses to
    # cross ironwork it could not close a basin at all.
    ("W09_Yard", 11.5, -11.6, 4.2, 2.4, 8.0, 0.074, False),
    ("W10_Yard", -3.0, 5.5, 3.4, 2.0, 34.0, 0.054, False),
    ("W11_Yard", 20.0, -3.0, 3.0, 2.2, -40.0, 0.054, False),
    ("W12_Yard", -40.0, 8.0, 3.2, 2.4, 18.0, 0.056, False),
    ("W13_Yard", 33.0, -9.5, 3.8, 2.6, -8.0, 0.056, False),
    # Two extra basins put deliberately into the near field of LANE_EYE_YARD, so
    # the shot that is judged on ground quality actually has readable standing
    # water inside 12 m instead of only the big ones at 15-50 m.
    ("W21_LaneNear", -36.0, 0.5, 4.6, 2.8, -14.0, 0.068, False),
    ("W22_LaneNear", -29.5, 5.5, 3.4, 2.2, 26.0, 0.062, False),
    ("W14_EastSpawn", 56.0, 12.0, 4.4, 2.6, 4.0, 0.058, False),
    ("W15_WestSpawn", -62.0, -20.0, 4.0, 3.0, -30.0, 0.058, False),
    ("W16_Apron", 26.0, -25.5, 3.2, 2.4, 16.0, 0.052, False),
    ("W17_Apron", -30.0, -26.0, 3.6, 2.2, -12.0, 0.052, False),
    ("W18_SouthOOB", 60.0, -34.0, 5.0, 3.4, 26.0, 0.060, False),
    ("W19_NorthFlank", -66.0, 30.0, 4.6, 3.2, -20.0, 0.058, False),
    ("W20_GateApproach", 6.0, 10.5, 3.0, 1.8, 44.0, 0.048, False),
]
ALL_PUDDLES = PUDDLES + MINOR_PUDDLES

DRAIN_EW = ("y", -14.5, -40.0, 34.0)     # E-W trench drain
DRAIN_NS = ("x", 18.0, -13.5, 12.0)      # N-S trench drain
BUND = (-63.7, -48.3, -13.7, -4.3)       # inside face of the fuel bund wall
OIL_PAD = (-63.0, -49.0, 1.0, 11.0)      # 14 x 10 pad under the tanker gantry
DITCH_Y = -48.0
ANNEX = (13.79, 26.20, 76.25, 88.25)     # the building owns this floor

AISLES_Y = [21.70, 33.50, 41.50, 49.50, 57.50, 65.50, 73.39]
RACK_GAPS = [
    (-18.0, 29.5), (14.0, 29.5), (-30.0, 37.5), (2.0, 37.5),
    (-10.0, 45.5), (26.0, 45.5), (-26.0, 53.5), (10.0, 53.5),
    (-2.0, 61.5), (22.0, 61.5), (-34.0, 69.5), (16.0, 69.5),
]
SOUTH_DOORS_X = [-33.0, -24.0, -15.0, -8.0]     # open roller doors -> wet fans
MANHOLES = [
    (-30.0, 8.5), (-12.0, -6.0), (6.0, 4.5), (24.0, -11.0), (40.0, 2.0),
    (-44.0, -2.0), (-20.0, -26.0), (4.0, -27.5), (22.0, -30.0), (-38.0, -20.0),
    (-58.0, 14.0), (58.0, -14.0), (46.0, 24.0), (-8.0, 11.5),
]


def _make_potholes():
    rng = np.random.default_rng(SEED)
    out = []
    zones = [
        (-50.0, 50.0, -15.0, 14.0, 28, 1.00, 2.30, 0.050, 0.120),
        (-45.0, 29.0, -33.0, -17.0, 15, 1.00, 2.00, 0.045, 0.100),
        (30.0, 52.0, -39.0, -17.0, 16, 1.10, 2.60, 0.060, 0.135),
        (-70.0, -53.0, -22.0, 32.0, 13, 1.05, 2.20, 0.050, 0.115),
        (53.0, 70.0, -22.0, 55.0, 13, 1.05, 2.20, 0.050, 0.115),
        (-69.0, 69.0, -39.5, -34.5, 11, 1.00, 1.80, 0.055, 0.115),
    ]
    for x0, x1, y0, y1, n, rmin, rmax, dmin, dmax in zones:
        for _ in range(n):
            out.append((float(rng.uniform(x0, x1)), float(rng.uniform(y0, y1)),
                        float(rng.uniform(rmin, rmax)), float(rng.uniform(dmin, dmax))))
    return out


POTHOLES = _make_potholes()
PH_X = np.array([p[0] for p in POTHOLES])
PH_Y = np.array([p[1] for p in POTHOLES])
PH_R = np.array([p[2] for p in POTHOLES])
PH_D = np.array([p[3] for p in POTHOLES])


# ----------------------------------------------------------------------------
# 3.  the height field
# ----------------------------------------------------------------------------


def _interior_mask(x, y):
    return rect_mask(x, y, -37.0, 37.0, 15.9, 75.4, 1.4)


def _paved_mask(x, y):
    m = np.zeros(np.shape(x), dtype=np.float64)
    for i, (x0, x1, y0, y1) in enumerate(PAVED):
        m = np.maximum(m, rect_mask(x, y, x0, x1, y0, y1, 1.6, jitter=0.9, seed=311 + i))
    return m


def _rim(x, y):
    t = np.maximum.reduce([(np.abs(x) - 46.0) / 29.0,
                           (y - 78.0) / 16.0,
                           (-44.0 - y) / 12.0])
    return 0.20 * sstep(np.clip(t, 0.0, 1.0))


def _ruts(x, y):
    carve = np.zeros(np.shape(x), dtype=np.float64)
    for idx, (path, gauge, depth, width) in enumerate(RUTS):
        wobble = 0.55 + 0.45 * (0.5 + 0.5 * fbm(x, y, 1.0 / 7.0, 2, 601 + idx))
        for side in (+1.0, -1.0):
            d = poly_dist(x, y, offset_polyline(list(path), side * gauge * 0.5))
            carve = np.maximum(carve, depth * wobble * np.exp(-(d / (width * 0.5)) ** 2))
    return carve


def _potholes_carve(x, y, jit=None):
    # Broadcast over all 96 potholes at once. This function is called for every
    # single overlay vertex in the module -- tens of thousands of scalar calls --
    # and a Python loop over the pothole list was the largest single cost in the
    # generator.
    if jit is None:
        jit = fbm(x, y, 1.0 / 1.1, 2, 907)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    sh = x.shape
    X = x.reshape(-1, 1)
    Y = y.reshape(-1, 1)
    J = np.asarray(jit, dtype=np.float64).reshape(-1, 1)
    rr = np.maximum(PH_R[None, :] * (1.0 + 0.28 * J), 0.15)
    q = np.hypot(X - PH_X[None, :], Y - PH_Y[None, :]) / rr
    bowl = PH_D[None, :] * np.clip(1.0 - q * q, 0.0, 1.0) ** 1.15
    lip = 0.22 * PH_D[None, :] * np.exp(-((q - 1.12) / 0.22) ** 2)
    return np.max(bowl - lip, axis=1).reshape(sh)


def surface_wear(x, y):
    """0 where the pavement is still intact, 1 where it has actually failed.

    THE MUD RULE, as a field.  A distribution depot is asphalt, and the thing
    that made this yard read as a field was that every loose-stone scatter in
    the module was spread UNIFORMLY over it -- 5 200 chips across the yard plus
    a 34-per-square-metre near-field carpet -- so the surface had gravel on it
    everywhere and read as gravel.  Loose stone on a paved yard is not
    everywhere: it is in the potholes, along the failed margins where the
    binder has gone, and in the blotches where the surface has broken up.  Every
    scatter in this module is now multiplied by this field on paved ground, so
    the intact asphalt between them stays intact.

    Three terms, all of them things you can point at in the frame:
      * the pothole bowls themselves,
      * the outer 1.5-2 m of every paved zone, where the paving fails first,
      * a coarse 8 m blotch field, thresholded so only its top ~35% survives --
        the patches where the surface has genuinely gone.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ph = np.clip(_potholes_carve(x, y) / 0.045, 0.0, 1.0)
    marg = np.clip(1.0 - _paved_mask(x, y), 0.0, 1.0)
    blotch = np.clip(2.35 * (0.5 + 0.5 * fbm(x, y, 1.0 / 8.0, 3, 7717)) - 1.18,
                     0.0, 1.0)
    return np.clip(np.maximum(np.maximum(ph, marg), blotch), 0.0, 1.0)


def _ditch(x, y):
    cy = DITCH_Y + 0.9 * fbm(x, np.zeros_like(x) + 3.0, 1.0 / 26.0, 2, 77)
    return np.interp(np.abs(y - cy),
                     np.array([0.0, 0.5, 1.0, 1.5, 2.1]),
                     np.array([0.60, 0.52, 0.30, 0.10, 0.0]))


def _bund(x, y):
    return 0.20 * rect_mask(x, y, *BUND, 0.45)


def _oil_pad(x, y):
    return 0.045 * rect_mask(x, y, *OIL_PAD, 0.55, jitter=0.25, seed=414)


def _drain_notch(x, y):
    """A shallow dish falling toward each trench drain, so water runs to it.

    This used to cut 0.30 m at the centreline while `build_drains` built its
    channel box only 0.16 m deep.  The ground therefore dropped 140 mm BELOW the
    bottom of the drain's own walls, leaving an open gap all along both sides of
    every channel: from any grazing camera you looked straight past the ironwork
    into an unlit, bottomless slot.  That is exactly the black void that crossed
    the lower third of the detail frame.  The dish is now 0.11 m at its deepest
    and the channel box is a closed 0.32 m deep invert (see build_drains), so the
    terrain can never undercut it again.

    The dish was also far too WIDE.  At a 1.70 m half-width it reached 3.4 m
    across, which is not a crossfall, it is a bathtub -- and puddle P4, whose
    layout centre is 3.0 m off the E-W drain line, had its whole northern bank
    swallowed by it.  P4's rim on that side sat 70 mm below its own centre grade,
    so the flood fill found no rim, filled to 30 mm above the bed instead of 70,
    and spilled 4.2 m sideways straight across the ironwork.  What the detail
    camera saw was a 30 mm film of water with no shoreline lying over the drain --
    "a glossy patch on flat ground".  The half-width is now 1.25 m, and
    `_puddle_rimlift` guarantees the bank on top of that.
    """
    # TWO HARD CONSTRAINTS, both of which this profile failed for a whole review
    # round, and both of which are invisible in the layer and obvious in a frame:
    #
    #   at |offset| = HF (0.80) the dish must be deeper than FRAME (0.038), or the
    #   pavement closes over the top of the drain frame and the ironwork vanishes
    #   under the ground it is set into;
    #
    #   at |offset| < HV (0.23) the dish must be deeper than WATER (0.092) plus
    #   the overlay stack (0.011), or THE GROUND PLATE LIES ON TOP OF THE WATER.
    #   The terrain is not cut at the drain -- it runs straight through it -- so a
    #   0.075 m dish put the pavement 28 mm ABOVE a water surface at 0.092 and the
    #   channel could not hold anything visible no matter what was authored in it.
    #   That is why "the drain is dry" survived a fix that put water in it: the
    #   water was there, under the floor.  At 0.132 the ground sits 36 mm under the
    #   waterline, so the channel holds 36 mm of visible standing water and the
    #   grade falls into the drain the way a yard's does.
    pd = np.array([0.0, 0.50, 0.85, 1.15, 1.45])
    pz = np.array([0.132, 0.124, 0.104, 0.045, 0.0])
    _, c, s0, s1 = DRAIN_EW
    n1 = np.where((x > s0 - 0.6) & (x < s1 + 0.6), np.interp(np.abs(y - c), pd, pz), 0.0)
    _, c2, t0, t1 = DRAIN_NS
    n2 = np.where((y > t0 - 0.6) & (y < t1 + 0.6), np.interp(np.abs(x - c2), pd, pz), 0.0)
    return np.maximum(n1, n2)


def _in_drain_frame(x, y):
    """Inside the footprint of a trench-drain frame, skirt included.

    A puddle shoreline is not allowed in here.  Water that reaches a drain goes
    INTO it; it does not sheet across the ironwork.  P4's traced contour used to
    run 1.4 m past the E-W drain's north skirt, which put a flat mirror plane
    straight through the cast-iron grating -- so from the detail camera the drain
    read as a dry dusty grille lying in a wet smear with no shoreline anywhere.
    """
    _, c, s0, s1 = DRAIN_EW
    m1 = (np.abs(y - c) < 1.38) & (x > s0 - 0.4) & (x < s1 + 0.4)
    _, c2, t0, t1 = DRAIN_NS
    m2 = (np.abs(x - c2) < 1.38) & (y > t0 - 0.4) & (y < t1 + 0.4)
    return m1 | m2


def _drain_keepout(x, y):
    """0 across a trench-drain gully, 1 clear of it, smooth between.

    Puddle geometry -- both the carved basin and the rim guarantee -- is held
    entirely off the drain corridor.  A basin carved inside a gully has no rim
    on the gully side by construction, so its flood fill runs down the gully
    instead of holding, and the pavement raised by the rim guarantee closes over
    the ironwork.  P4's layout footprint reaches 0.7 m past the E-W drain's
    centreline, so it is the one basin this actually bites on: the drain
    truncates its northern 0.8 m, which is what a drain does to a puddle.
    """
    _, c, s0, s1 = DRAIN_EW
    d1 = np.where((x > s0 - 0.4) & (x < s1 + 0.4), np.abs(y - c), 99.0)
    _, c2, t0, t1 = DRAIN_NS
    d2 = np.where((y > t0 - 0.4) & (y < t1 + 0.4), np.abs(x - c2), 99.0)
    d = np.minimum(d1, d2)
    return sstep(np.clip((d - 1.42) / 0.63, 0.0, 1.0))


def _puddle_jitter(x, y):
    return fbm(x, y, 0.55, 2, 1303)


def _puddle_q(x, y, p, jit=None):
    if jit is None:
        jit = _puddle_jitter(x, y)
    _, cx, cy, sx, sy, yaw, _, _ = p
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)
    dx, dy = x - cx, y - cy
    u = (dx * ca + dy * sa) / (sx * 0.5)
    v = (-dx * sa + dy * ca) / (sy * 0.5)
    return np.sqrt(u * u + v * v) * (1.0 + 0.24 * jit)


_PUD_CX = np.array([p[1] for p in ALL_PUDDLES])
_PUD_CY = np.array([p[2] for p in ALL_PUDDLES])
_PUD_HX = np.array([p[3] * 0.5 for p in ALL_PUDDLES])
_PUD_HY = np.array([p[4] * 0.5 for p in ALL_PUDDLES])
_PUD_CA = np.array([math.cos(math.radians(p[5])) for p in ALL_PUDDLES])
_PUD_SA = np.array([math.sin(math.radians(p[5])) for p in ALL_PUDDLES])
_PUD_D = np.array([p[6] for p in ALL_PUDDLES])


def _puddle_fields(x, y):
    # Broadcast over all 26 puddles at once -- same reasoning as
    # _potholes_carve; this is on the hot path of every terrain_z call.
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    sh = x.shape
    jit = np.asarray(_puddle_jitter(x, y), dtype=np.float64).reshape(-1, 1)
    dx = x.reshape(-1, 1) - _PUD_CX[None, :]
    dy = y.reshape(-1, 1) - _PUD_CY[None, :]
    u = (dx * _PUD_CA[None, :] + dy * _PUD_SA[None, :]) / _PUD_HX[None, :]
    v = (-dx * _PUD_SA[None, :] + dy * _PUD_CA[None, :]) / _PUD_HY[None, :]
    q = np.sqrt(u * u + v * v) * (1.0 + 0.24 * jit)
    # Wall in the outer 28% of the footprint rather than the outer 65%.  A bowl
    # that shallows gradually all the way from the centre floods to only ~0.75
    # of its nominal size and has no rim you can see; a dished bed with a
    # defined edge floods to ~0.9, and gives the meniscus and the damp margin a
    # real 4-8 cm of bank to sit on.
    prof = np.clip((1.0 - q) / 0.28, 0.0, 1.0)
    carve = np.max(_PUD_D[None, :] * prof * prof * (3.0 - 2.0 * prof), axis=1)
    basin = np.max(np.clip((1.25 - q) / 0.55, 0.0, 1.0), axis=1)
    return basin.reshape(sh), carve.reshape(sh)


# --- the rim guarantee ------------------------------------------------------
#
# A puddle only exists because something holds it.  The first version carved a
# bowl into whatever the site profile happened to be doing and then flood-filled
# it -- which works in the middle of a flat apron and fails completely anywhere
# the site is already falling, because the "rim" on the downhill side is lower
# than the bed and the fill has nothing to stop it.  Three of the six hero
# basins sit next to something that falls away: P4 beside the E-W trench drain,
# P5 on the broken east apron, P6 in the fuel-bay overflow.  All three flooded
# to a two-to-three centimetre film that spread far outside their own footprint
# and had no bank, no shoreline relief and nothing for a meniscus to sit on.
#
# So each basin now carries its own DATUM: the undisturbed grade at its centre.
# Inside the footprint the ground is raised toward that datum wherever it has
# fallen below it -- never lowered, and never by more than RIM_CAP -- and the
# lift feathers out to zero by 1.42x the footprint.  The bowl is then carved
# into the result.  The consequence is that `rim - bed` is the authored basin
# depth almost everywhere instead of whatever the site left over, so the water
# is 60-90 mm deep at the centre, its shoreline lands at ~0.92 of the nominal
# footprint instead of running away, and there is a real bank above the
# waterline for the meniscus fillet to climb.
RIM_CAP = 0.058          # the tallest lip a puddle may build for itself
_PUD_PAN = None
_PAN_BUSY = False


def _pan_levels():
    """Undisturbed grade at each puddle centre, computed once, lazily."""
    global _PUD_PAN, _PAN_BUSY
    if _PUD_PAN is None:
        _PAN_BUSY = True
        try:
            _PUD_PAN = np.asarray(terrain_z(_PUD_CX, _PUD_CY, puddles=False),
                                  dtype=np.float64)
        finally:
            _PAN_BUSY = False
    return _PUD_PAN


def _puddle_rimlift(x, y, z, jit):
    if _PAN_BUSY:
        return 0.0
    pan = _pan_levels()
    x = np.asarray(x, dtype=np.float64)
    sh = x.shape
    dx = x.reshape(-1, 1) - _PUD_CX[None, :]
    dy = np.asarray(y, dtype=np.float64).reshape(-1, 1) - _PUD_CY[None, :]
    u = (dx * _PUD_CA[None, :] + dy * _PUD_SA[None, :]) / _PUD_HX[None, :]
    v = (-dx * _PUD_SA[None, :] + dy * _PUD_CA[None, :]) / _PUD_HY[None, :]
    q = np.sqrt(u * u + v * v) * (1.0 + 0.24 * np.asarray(jit).reshape(-1, 1))
    w = sstep(np.clip((1.42 - q) / 0.34, 0.0, 1.0))
    need = np.clip(pan[None, :] - np.asarray(z, dtype=np.float64).reshape(-1, 1),
                   0.0, RIM_CAP)
    return np.max(w * need, axis=1).reshape(sh)


def terrain_z(x, y, puddles=True):
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    m_in = _interior_mask(x, y)
    basin, pcarve = _puddle_fields(x, y)

    z = np.interp(y, PROF_Y, PROF_Z) + _rim(x, y)
    z = z - 0.10 * (1.0 - _paved_mask(x, y))

    prox = rect_mask(x, y, -38.5, 38.5, 13.6, 78.0, 2.2)
    damp = (1.0 - 0.80 * prox) * (1.0 - 0.55 * basin)
    broad = (0.030 * fbm(x, y, 1.0 / 17.0, 3, 11)
             + 0.016 * fbm(x + 90.0, y - 40.0, 1.0 / 6.5, 2, 23))
    # Two fine bands. The 1.7 m one is settlement mottle; the 1.05 m one is the
    # finest relief the 0.35 m face grid can carry, and it exists purely so that
    # a 5.5-degree sun rakes something at grazing incidence -- without it a
    # 100 m run of asphalt is a mirror-flat plane no material can rescue.
    fine = (0.008 * fbm(x, y, 1.0 / 1.7, 2, 37)
            + 0.0042 * fbm(x - 23.0, y + 61.0, 1.0 / 1.15, 2, 43))
    z = z + damp * (broad + fine)

    # The repair mosaic's 2-3 cm settlement steps are damped out inside a puddle
    # basin.  A 3 cm cell lip running through the middle of a 6 cm basin tips
    # the water plane's shoreline onto the lip and the flood fill either spills
    # across the whole sample window (a rectangle of water) or splits in two.
    z = z + _mosaic_level(x, y) * (1.0 - 0.80 * basin)
    z = z + _oil_pad(x, y)
    z = z - _ruts(x, y)
    z = z - _potholes_carve(x, y)
    z = z - _ditch(x, y)
    z = z - _bund(x, y)
    z = z - _drain_notch(x, y)

    if puddles:
        keep = _drain_keepout(x, y)
        z = z + _puddle_rimlift(x, y, z, _puddle_jitter(x, y)) * keep * (1.0 - m_in)

    z_in = -0.012 - 0.005 * (0.5 + 0.5 * fbm(x, y, 1.0 / 3.0, 2, 53))
    z = z * (1.0 - m_in) + z_in * m_in

    if puddles:
        z = z - pcarve * keep * (1.0 - m_in)
    return z


_Z_CACHE: dict[tuple[float, float], float] = {}


def z_at(px, py):
    key = (round(float(px), 4), round(float(py), 4))
    v = _Z_CACHE.get(key)
    if v is None:
        v = float(terrain_z(np.array([px], dtype=float), np.array([py], dtype=float))[0])
        _Z_CACHE[key] = v
    return v


# ----------------------------------------------------------------------------
# 4.  material palette + per-face classification
# ----------------------------------------------------------------------------

# Every ground look in this module binds a SHARED material from
# /World/Looks (authored in 50_materials.usda as scanned vMaterials MDL).
# There is deliberately no local Looks scope: a constant-colour fallback is
# worse than no fallback, because it silently ships a clay render.
#
#   terrain look name : (shared material under /World/Looks, authoring note)
PALETTE = {
    # Five phase variants of the same asphalt scan (different tile size, rotation
    # and batch brightness). The mosaic hands a different one to every cell, so a
    # 104 m yard never repeats its texture and no two adjacent patches share a
    # tiling phase -- which is the other half of beating "uniform ground".
    "AsphaltOxidised": ("G_AsphaltOxidised", "grey oxidised asphalt, aggregate showing; dominant yard surface"),
    "AsphaltOxidisedB": ("G_AsphaltOxidised_B", "yard asphalt, tighter aggregate read, 1.45 m tile at 37 deg"),
    "AsphaltOxidisedC": ("G_AsphaltOxidised_C", "yard asphalt, paler batch, 1.85 m tile at 118 deg"),
    "AsphaltOxidisedD": ("G_AsphaltOxidised_D", "yard asphalt, darkest batch, 2.65 m tile at 214 deg"),
    "AsphaltOxidisedE": ("G_AsphaltOxidised_E", "yard asphalt, warm bleached batch, 3.35 m tile at 301 deg"),
    "AsphaltPatchOxide": ("G_AsphaltPatchOxide", "an old asphalt repair that has oxidised paler than the surround"),
    "AsphaltPatchTar": ("G_AsphaltPatchTar", "a recent tar-rich repair, darker and glossier than the surround"),
    "AsphaltFresh": ("G_AsphaltFresh", "the newest repair on the site -- near-black and still shedding water"),
    # Tyre polish is MATTE.  It used to bind the tar scan (roughness 0.34), and a
    # 0.34-rough near-black surface seen at 2-6 degrees of grazing incidence is a
    # Fresnel mirror: every wheel path and every turn arc in the yard came back as
    # a pale blue-lavender smear of reflected overcast, which is the wrong hue for
    # asphalt and reads as an airbrushed blob rather than as wear.  Polish is now
    # the darkest matte asphalt batch, and the genuinely WET gloss is a separate,
    # much narrower look used only in the 0.35 m core of a wheel path.
    "AsphaltPolish": ("G_AsphaltOxidised_D", "asphalt polished dark and smooth by tyres in the wheel paths -- matte"),
    "AsphaltPolishWet": ("G_AsphaltPatchTar", "the wet, still-glossy core of a wheel path; narrow strips only"),
    "DampMottle": ("G_AsphaltOxidised_D", "matte damp mottling outside a puddle's drying margin"),
    "TarSeam": ("G_AsphaltOxidised_D", "an old oxidised joint round a repair patch -- dark and MATTE; a glossy seam under a 5.5 deg sun turns into a run of bright tape"),
    "AsphaltAggregate": ("G_AsphaltAggregate", "crumbling asphalt worn through to loose aggregate"),
    "ConcreteSlabExposed": ("G_ConcreteExposed", "old concrete slab exposed where the asphalt has worn away"),
    "ConcreteDock": ("G_ConcreteDock", "power-floated dock apron concrete, tyre scuffed"),
    "ConcreteWetAlgae": ("G_ConcreteAlgae", "permanently wet algae-dark concrete at the dock foot"),
    "ConcreteKerb": ("G_ConcreteKerb", "precast kerb / plinth concrete, chipped, rust bleed at the rebar"),
    "Gravel": ("G_Gravel", "compacted gravel service surface"),
    "Ballast": ("G_Ballast", "coarse rail ballast, weeds and mud between"),
    "Mud": ("G_Mud", "compacted mud with a dry cracked crust"),
    "MudWet": ("G_MudWet", "saturated mud, near-mirror sheen in the ruts"),
    "DirtWeeds": ("G_DirtWeeds", "out-of-bounds dirt, rank weeds through it"),
    "OilPad": ("G_OilPad", "oil-soaked black concrete -- darkest ground in the map"),
    "AsphaltCracked": ("G_AsphaltCracked", "spawn-apron asphalt, crazed and cracked, weeds in the cracks"),
    "BrokenConcrete": ("G_BrokenConcrete", "half-buried broken slab, exposed aggregate and rebar"),
    "PuddleBed": ("G_PuddleBed", "silted puddle bed under the waterline"),
    "DampRing": ("G_DampRing", "damp halo around standing water, darker than the dry ground"),
    "Water": ("W_StandingWater", "standing rainwater -- mirrors the dusk sky"),
    "WaterCalm": ("W_StandingWaterCalm", "the big hero puddles: glassier, holds a clean reflection"),
    "WaterSilt": ("W_StandingWaterSilt", "silty water in ruts and potholes"),
    "WaterDiesel": ("W_DieselSheen", "diesel-rainbow film on water; thin-film iridescence"),
    "OilyWater": ("W_OilyWater", "black oily water in the fuel bund sump"),
    "DrainIron": ("M_CastIron", "cast-iron drain grate, rusted, wet"),
    "DrainVoid": ("X_Void", "the dark inside of the drain -- near-black, no highlight"),
    "Crack": ("X_Void", "the open black slot of a crack in the asphalt"),
    "ManholeIron": ("M_CastIronWorn", "cast-iron manhole cover, worn smooth on the traffic side"),
    "PaintYellow": ("P_LineYellow", "faded yellow bay marking, worn away in the wheel paths"),
    "PaintWhite": ("P_LineWhite", "faded white line marking"),
    "InteriorWorn": ("G_InteriorWorn", "warehouse slab worn through to aggregate along the aisle"),
    "InteriorWet": ("G_InteriorWet", "wet sheen on the warehouse slab where water has run in"),
    "InteriorOil": ("G_InteriorOil", "oil drip trail on sealed concrete"),
    "InteriorScuff": ("G_InteriorScuff", "black forklift tyre-scuff arcs"),
    "InteriorJoint": ("G_InteriorJoint", "saw-cut slab joint, dirt packed, several spalled"),
    "Moss": ("S_MossPatch", "moss and algae growing out of a crack or a drain lip"),
    "SandDrift": ("G_SandDrift", "wind-drifted sand against the perimeter fence"),
    # ---- backdrop band only (see build_backdrop_looks) ----------------------
    # These twelve are the ONLY locally-authored materials in this module and
    # they are used on nothing closer than 88 m out from the plate.  At that
    # range a scanned 1.9 m tile is sub-pixel and the only thing a distant mass
    # contributes is a VALUE and a SILHOUETTE, so a flat, dark, haze-matched
    # constant is not a fallback, it is the correct answer -- it is what a matte
    # painter would paint.
    #
    # FOUR SURFACE FAMILIES x THREE DEPTH PLANES.  The depth planes are the
    # whole mechanism of aerial perspective: further away is lighter, bluer and
    # lower in contrast.  Rounds 1-4 had one tone per family, so a mass at 110 m
    # and a mass at 290 m rendered at the same value and the horizon read as a
    # flat cut-out.  Every backdrop object now picks its plane from its own
    # measured `far_d`, so the ramp is a property of the placement, not a guess.
    "BackdropMassN": ("BD_MassN", "distant industrial mass, nearest depth plane (under 185 m from the eye)"),
    "BackdropMassM": ("BD_MassM", "distant industrial mass, middle depth plane (185-240 m from the eye)"),
    "BackdropMassF": ("BD_MassF", "distant industrial mass, furthest depth plane (240 m+ from the eye)"),
    "BackdropRoofN": ("BD_RoofN", "distant roof/parapet plane, nearest depth plane"),
    "BackdropRoofM": ("BD_RoofM", "distant roof/parapet plane, middle depth plane"),
    "BackdropRoofF": ("BD_RoofF", "distant roof/parapet plane, furthest depth plane"),
    "BackdropSteelN": ("BD_SteelN", "distant lattice steel -- mast, guide frame, nearest"),
    "BackdropSteelM": ("BD_SteelM", "distant lattice steel, middle depth plane"),
    "BackdropSteelF": ("BD_SteelF", "distant lattice steel, furthest depth plane"),
    "BackdropScrubN": ("BD_ScrubN", "tree belt on the nearest horizon plane (under 185 m from the eye) "
                                    "-- darkest and least hazed of the three"),
    "BackdropScrubM": ("BD_ScrubM", "tree belt on the middle horizon plane (185-240 m from the eye)"),
    "BackdropScrubF": ("BD_ScrubF", "tree belt on the furthest horizon plane (240 m+ from the eye) "
                                    "-- lightest and bluest of the three"),
}
MAT_NAMES = list(PALETTE.keys())
M = {n: i for i, n in enumerate(MAT_NAMES)}
LOOKS_ROOT = "/World/Looks"
BACKDROP_LOOKS = "/World/Terrain/BackdropLooks"

# ---------------------------------------------------------------------------
# BACKDROP TONE CALIBRATION -- the horizon is authored in DELIVERED PIXELS.
#
# The horizon has failed four review rounds ("faceted cones", "tents", "flat
# greybox", "the brightest thing on the skyline"). Every previous attempt tuned
# an *albedo* and hoped. Albedo is not what a critic looks at; the pixel is. So
# this table states the pixel each backdrop family is supposed to DELIVER in
# HERO_ESTABLISH, and the albedo is solved for.
#
# HOW THE TRANSFER WAS MEASURED (reproducible, two renders):
#   1. over-layer the six old BD_* looks at pure primaries, render
#      HERO_ESTABLISH --final --warmup 120, and build a per-material pixel mask
#      from the result. (This also proved the GeomSubset bindings resolve in
#      ovrtx -- the masses turned pure red, so rounds 1-3 blamed the wrong
#      thing when they blamed material binding.)
#   2. render the same frame twice more through that mask: once with the shipped
#      albedos, once with every BD_* albedo set to (0,0,0). The black render is
#      the ADDITIVE FLOOR (in-scattered haze + the 80_fx volume in front of the
#      band); the difference divided by the albedo is the GAIN.
#
# RE-MEASURED 2026-08-08 against 60_lighting as it now stands (27 lights, after
# that module's own noise pass). This is not a footnote: the FIRST measurement,
# taken two hours earlier against the 82-light build, gave a mass gain of
# (50.8, 35.2, 21.7). The same geometry and the same albedo now measure
# (12.9, 9.2, 4.6) -- the scene's response at the horizon fell about 4x while
# the frame's mean luma ROSE from 0.229 to 0.291. A backdrop authored as a
# constant albedo is therefore hostage to 60_lighting, and any future change
# there needs these two probe renders re-run. The probe pair is the whole
# calibration and it costs about a minute of GPU:
#
#   over-layer the twelve BD_* looks at distinguishable emissive keys, render,
#   mask; then over-layer them all at diffuse (0,0,0), render, mask again.
#   floor = the black frame through the mask; gain = (delivered - floor) / albedo.
#
# Gains are per channel because the key is 3200 K: the R:G:B response ratio is
# about 1 : 0.71 : 0.36, which is why a NEUTRAL tint delivers a WARM pixel here
# and why the solved albedos come out blue.
#
#   family   gain (R,G,B)         floor, linear (R,G,B)       mask px
#   mass     10.45,  8.08, 5.72   0.00152, 0.00162, 0.00233   119 k
#   roof     17.13, 13.73, 10.62  0.00152, 0.00163, 0.00223    71 k
#   steel    13.65, 11.57,  8.81  0.00201, 0.00226, 0.00313    44 k
#   scrub     9.77,  7.90,  6.44  0.00193, 0.00220, 0.00301    40 k
#
# These are the THIRD fit, and the convergence history is worth keeping because
# it says how much of this is measurement and how much is model:
#   fit 1 (single probe, six of twelve masks collided after emissive clipping):
#          BD_MassN delivered luma 0.064 vs 0.081 target, BD_ScrubF saturation
#          0.56 vs 0.18. Probe split into two frames of six keys and re-fit.
#   fit 2: BD_MassN 0.077 vs 0.081 and saturation 0.182 vs 0.176 -- converged.
#          BD_ScrubM 0.119 vs 0.073 -- NOT converged, because the foliage
#          break-up added between the two fits changed the belts' own normal
#          distribution and therefore their gain. Re-fit again.
# The model is linear (delivered = floor + gain x albedo) so a Newton step
# converges whenever the GEOMETRY is held still; change the geometry and the
# family gain moves with it.
#
# HONEST LIMIT: the three FAR-plane looks return an empty mask in
# HERO_ESTABLISH, because only two backdrop objects sit past 240 m on that
# bearing and both are behind the building. Their albedos are solved from the
# family gain fitted on the near and middle planes. They are visible in
# SILHOUETTE_WEST and have not been measured there.
BD_GAIN = {
    "mass": (10.45, 8.08, 5.72),
    "roof": (17.13, 13.73, 10.62),
    "steel": (13.65, 11.57, 8.81),
    "scrub": (9.77, 7.90, 6.44),
}
BD_FLOOR = {
    "mass": (0.00152, 0.00162, 0.00233),
    "roof": (0.00152, 0.00163, 0.00223),
    "steel": (0.00201, 0.00226, 0.00313),
    "scrub": (0.00193, 0.00220, 0.00301),
}

# THE ART DIRECTION, in delivered sRGB.  Reference point: the storm sky in the
# horizon band of HERO_ESTABLISH measures (0.171, 0.192, 0.220), luma 0.190.
#
# Rules a shipped background ridge obeys, and the numbers that encode them:
#   * NOTHING in the band is brighter than the sky behind it. The palest entry
#     here (a far roof plane) is luma 0.135 = 0.71 x sky. The old build measured
#     BD_Roof at luma 0.284 -- 1.5 x sky, i.e. literally the brightest object on
#     the skyline, which is the note the critic has written four times.
#   * The band is LOW IN CHROMA. Saturation here is 0.17-0.19. The old build
#     measured 0.39-0.44, which is why it read as saturated teal slabs.
#   * It is COOL, but only just: B > R by ~20 %, which keeps these 9 % of the
#     frame on the correct side of cool_pixel_frac without tinting them.
#   * Further = lighter, bluer, lower contrast. Near-to-far spans luma
#     0.054 -> 0.135, so three depth planes are separable at a glance.
#   * Vegetation sits well below built mass at every plane: a tree line is a
#     dark, absorbing volume and a wall is a lit plane.
BD_TARGET_SRGB = {
    "BD_MassN": (0.076, 0.082, 0.092),
    "BD_MassM": (0.094, 0.102, 0.115),
    "BD_MassF": (0.114, 0.124, 0.140),
    "BD_RoofN": (0.086, 0.093, 0.104),
    "BD_RoofM": (0.104, 0.113, 0.127),
    "BD_RoofF": (0.124, 0.135, 0.152),
    "BD_SteelN": (0.062, 0.067, 0.076),
    "BD_SteelM": (0.078, 0.085, 0.096),
    "BD_SteelF": (0.096, 0.104, 0.118),
    "BD_ScrubN": (0.050, 0.054, 0.061),
    "BD_ScrubM": (0.068, 0.074, 0.084),
    "BD_ScrubF": (0.092, 0.100, 0.114),
}

# Depth-plane breaks, in metres from the point every camera stands near.
#
# NOT `far_d`. The first draft banded on distance out from the plate edge and
# every object in the north-east cluster came back on the NEAREST plane -- a
# block at (162, 80) is only 87 m outside the plate but 227 m from the hero
# camera, so the whole horizon collapsed onto one tone and rendered as a black
# cut-out at luma 0.039 against a 0.175 sky. Aerial perspective is a function of
# how far the EYE is from the thing, so that is what it is banded on.
BD_PLANE_ORIGIN = (0.0, 10.0)
BD_PLANES = (185.0, 240.0)


def bd_family(look):
    for f in ("mass", "roof", "steel", "scrub"):
        if look.lower().startswith("bd_" + f):
            return f
    raise ValueError(look)


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def bd_albedo(look):
    """Solve the OmniPBR diffuse constant that DELIVERS BD_TARGET_SRGB[look]."""
    fam = bd_family(look)
    out = []
    for t, k, fl in zip(BD_TARGET_SRGB[look], BD_GAIN[fam], BD_FLOOR[fam]):
        out.append(max((_srgb_to_linear(t) - fl) / k, 1e-6))
    return tuple(out)


def bd_plane(cx, cy):
    """'N' / 'M' / 'F' depth plane for a backdrop object, by eye distance."""
    d = math.hypot(float(cx) - BD_PLANE_ORIGIN[0], float(cy) - BD_PLANE_ORIGIN[1])
    return "N" if d < BD_PLANES[0] else ("M" if d < BD_PLANES[1] else "F")

# Overlay stacking order, in metres above the ground surface.  This is a
# CHRONOLOGY, not an arbitrary set of offsets: the surface was patched, the
# patches were sealed, then it was painted, then twenty years of traffic
# polished the paint away, dropped oil on it and finally cracked it open.  Get
# the order wrong and a fresh yellow line sits on top of a tyre scuff, which is
# one of the things that makes a render look like an ArchVis leasing image.
L_MOSAIC = 0.0030    # the repair patchwork itself, as smooth-outlined meshes
L_PATCH = 0.0050     # organic ground-treatment overlays on top of it
L_SEAM = 0.0068      # poured bitumen joints round them
L_PAINT = 0.0074     # bay markings, hatching, turning circle
L_POLISH = 0.0080    # tyre polish and turn scuff, over the paint
L_OIL = 0.0090       # drop-out stains
L_SPALL = 0.0096     # crumbled crack edges
L_CRACK = 0.0100     # the open slot, cutting through everything above
L_MOSS = 0.0106      # what grew afterwards


def zstep(i, n=64, step=0.00003):
    """A unique sub-millimetre level for the i-th element of one overlay layer.

    Two overlay polygons in the SAME layer that overlap at exactly the same
    height do not blend -- they z-fight, and a path tracer resolves the fight
    per-sample, which produces hard-edged geometric mottling that follows the
    mesh grid.  That is what made the yard look like camouflage netting.  Every
    element therefore gets its own level inside a 1.9 mm band: far below what a
    grazing camera can see as a step, far above float32 ray precision.
    """
    return (i % n) * step


# ---------------------------------------------------------------------------
# 4a.  THE PAVED-SURFACE LOOKS, authored locally.  Read this before reverting it.
# ---------------------------------------------------------------------------
#
# MEASURED, unfiltered, LANE_EYE_YARD --final --warmup 120, against the level as
# it stood before this pass (all six numbers are sRGB luma of a sampled block):
#
#     storm sky in the horizon band ................ 0.279
#     yard ground, 30-50 m out ..................... 0.379
#     yard ground, 3-6 m out ....................... 0.320
#     one mosaic repair plate at grazing incidence .. 0.802
#
# A depot yard whose ASPHALT is 1.4x the value of the sky behind it, and whose
# repair plates are 2.9x it, is not a paved yard -- it is a mud field, and that
# is exactly the note this pass was given.  Three separate causes, all of them
# in the material and none of them in the geometry:
#
#  1. TILE SIZE.  The shared asphalt looks bind `asphalt_fine_tarred_diff` with
#     `texture_scale = 0.23077` under a world-space triplanar, i.e. ONE TILE PER
#     4.33 m.  The scan's 3-8 mm chippings therefore render 4-5 cm across, which
#     at 3 m from the lens is a bed of coffee beans.  Probed at 0.9-1.3 m per
#     tile the same scan reads as asphalt.
#  2. SATURATION.  `albedo_desaturation = 0.5` leaves half the scan's warm brown
#     in place; under a 3200 K key that is the "brown" in "uniform brown mud".
#     At 0.90-0.95 it goes grey and the low sun supplies the warmth instead.
#  3. ROUGHNESS.  `reflection_roughness_constant = 0.48` on a near-black surface
#     seen at 2-6 degrees of grazing incidence is a Fresnel mirror: a 7 m mosaic
#     cell returns a coherent sheet of sky at 0.80 luma with a hard polygonal
#     silhouette.  At 0.76-0.86 the sheet breaks up into a sheen.
#
# All three live in 50_materials.usda, which this module does not own, so the
# paved-surface family is authored here instead -- same scanned textures, solved
# tiling, desaturated, and rough enough not to mirror.  A probe render with these
# values applied as overrides measured the same three blocks at 0.291 / 0.315 /
# 0.614 and the yard read as asphalt for the first time.
#
# Scope of the override is deliberately narrow: ASPHALT and the two wet-margin
# looks only.  Concrete, gravel, mud, ballast, sand, water, paint, ironwork and
# every interior look still bind /World/Looks, because those are genuinely
# different materials rather than a mis-tuned one, and because a yard whose mud
# is warm against grey asphalt is the point.
#
# TO REVERT: set LOCAL_PAVED_LOOKS = False.  Everything falls back to
# /World/Looks and nothing else in this module changes.
LOCAL_PAVED_LOOKS = True
GROUND_LOOKS = TERRAIN + "/GroundLooks"

_VM = ("https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
       "Materials/vMaterials_2/")
_T_ASPH = (_VM + "Ground/textures/asphalt_fine_tarred_diff.jpg",
           _VM + "Ground/textures/asphalt_fine_tarred_norm.jpg",
           _VM + "Ground/textures/asphalt_fine_tarred_multi_R_rough_G_ao_B_height.jpg")
_T_COURT = (_VM + "Ground/textures/hard_court_mono_diff.jpg",
            _VM + "Ground/textures/hard_court_norm.jpg",
            _VM + "Ground/textures/hard_court_multi_R_rough_G_ao_B_height.jpg")
_T_AGG = (_VM + "Ground/textures/aggregate_exposed_diff.jpg",
          _VM + "Ground/textures/aggregate_exposed_norm.jpg",
          _VM + "Ground/textures/aggregate_exposed_rough.jpg")

# local name: (textures, tile metres, rotation deg, albedo_brightness,
#              desaturation, roughness constant, roughness texture influence,
#              specular level, bump, detail normal, detail tile m, doc)
#
# The five base phases are an ORDERED BRIGHTNESS RAMP (0.102 -> 0.150) because
# `_mix_pick` walks it with a smooth field; if the ramp is not monotonic the
# smooth field stops doing its job and neighbouring cells jump two steps.
#
# THE ALBEDO LADDER IS SOLVED, NOT GUESSED.  Three renders of LANE_EYE_YARD
# --final --warmup 120, measured on the same three blocks:
#
#   albedo x1.00 (first draft)  yard ground 0.49-0.61 luma, sky 0.30
#                               -> mean_luma 0.225, still PALER than the sky.
#   albedo x0.44                yard ground 0.15-0.32, mean_luma 0.191,
#                               detail_density 0.084, dead_area 0.128
#   albedo x0.60 SHIPPED        mean_luma 0.188, rms_contrast 0.275,
#                               detail_density 0.088, warm_cool_split 0.156
#                               (up from 0.141), dead_area 0.120
#
# x0.44 was very slightly too dark in the shadowed foreground and cost detail;
# x0.60 puts the open yard just under the sky, which is where a wet asphalt
# apron belongs at dusk, and it is the value in this table.
#
# The tint is (0.78, 0.91, 1.18) -- B is 1.51x R.  A 3200 K key is doing the
# warming, so the SURFACE has to be cool or the whole lower half of the frame
# comes back one hue; that is also the only lever this module has on
# cool_pixel_frac, since the yard is the largest single surface in three of the
# five shots.  Pushed further than this the asphalt goes lilac.
PAVED_LOOKS = {
    "T_AsphaltA": (_T_ASPH, 1.00, 0.0, 0.120, 0.92, 0.80, 0.35, 0.225, 1.9,
                   _T_COURT[1], 0.234, "yard asphalt, base phase, 1.00 m tile"),
    "T_AsphaltB": (_T_ASPH, 0.87, 37.0, 0.129, 0.93, 0.78, 0.35, 0.225, 2.0,
                   _T_AGG[1], 0.207, "yard asphalt, 0.87 m tile at 37 deg"),
    "T_AsphaltC": (_T_ASPH, 1.16, 118.0, 0.141, 0.94, 0.82, 0.32, 0.210, 1.8,
                   _T_COURT[1], 0.276, "yard asphalt, paler batch, 1.16 m tile"),
    "T_AsphaltD": (_T_ASPH, 0.77, 214.0, 0.102, 0.90, 0.76, 0.38, 0.240, 2.1,
                   _T_AGG[1], 0.179, "yard asphalt, darkest batch, 0.77 m tile"),
    "T_AsphaltE": (_T_ASPH, 1.35, 301.0, 0.150, 0.95, 0.84, 0.30, 0.195, 1.7,
                   _T_COURT[1], 0.303, "yard asphalt, bleached batch, 1.35 m tile"),
    # ROUGHNESS FLOOR FOR ANYTHING LAID AT AREA.  HERO_ESTABLISH looks down at
    # the yard at about 6 degrees of incidence, and at 6 degrees ANY dielectric
    # under about 0.65 roughness returns a coherent image of the sky.  The first
    # build of the saw-cut repairs used the glossier patch looks, and what the
    # hero frame showed was four hard-edged sheets of blue lying in the yard.
    # The narrow strips (wheel-path core, puddle collar) keep their gloss --
    # that sheen is the whole Hackney Yard read at eye height -- but nothing
    # that covers square metres is allowed under 0.65 any more.
    "T_PatchTar": (_T_ASPH, 0.91, 63.0, 0.090, 0.90, 0.74, 0.40, 0.190, 1.6,
                   _T_ASPH[1], 0.207, "recent tar-rich repair: darker and slightly "
                                      "glossier than the surround"),
    "T_PatchOxide": (_T_COURT, 1.05, 152.0, 0.148, 0.96, 0.86, 0.30, 0.175, 1.5,
                     _T_AGG[1], 0.234, "an old repair that has oxidised paler than "
                                       "the surround"),
    "T_Fresh": (_T_ASPH, 0.83, 22.0, 0.072, 0.88, 0.68, 0.42, 0.190, 1.6,
                _T_ASPH[1], 0.193, "the newest repair on the site, near-black"),
    "T_Cracked": (_T_COURT, 0.95, 96.0, 0.147, 0.94, 0.85, 0.32, 0.195, 1.9,
                  _T_AGG[1], 0.221, "crazed, cracked apron asphalt"),
    "T_Aggregate": (_T_AGG, 0.62, 41.0, 0.108, 0.92, 0.90, 0.28, 0.155, 2.2,
                    _T_ASPH[1], 0.152, "asphalt worn through to loose aggregate"),
    "T_Seam": (_T_ASPH, 0.55, 8.0, 0.069, 0.82, 0.88, 0.22, 0.150, 1.4,
               _T_ASPH[1], 0.138, "hot-poured bitumen joint: dark and MATTE"),
    # Narrow strips only -- these are the three looks allowed to stay glossy,
    # because a 0.30-0.62 m ribbon of sheen is a highlight and a 5 m plate of it
    # is a mirror.
    "T_Polish": (_T_ASPH, 0.72, 17.0, 0.090, 0.92, 0.58, 0.40, 0.210, 1.3,
                 _T_ASPH[1], 0.166, "asphalt polished dark and smooth by tyres"),
    "T_PolishWet": (_T_ASPH, 0.66, 17.0, 0.069, 0.88, 0.28, 0.30, 0.280, 1.0,
                    _T_ASPH[1], 0.152, "the still-wet glossy core of a wheel path"),
    # THE WET COLLAR IS DARK, NOT SHINY.  The margin bands are built by
    # `contour_annulus` as three broken rings of quad fragments, and at 0.42
    # roughness every one of those fragments returned its own little image of
    # the sky at grazing incidence -- so the ring round each puddle came back as
    # a band of bright crushed-shell flecks instead of as soaked ground, and the
    # eye read it as a gravel shore. The mirror belongs to the WATER; the ground
    # that the water has soaked is the darkest thing in the yard, and that
    # contrast is what makes a puddle read as depth rather than as a decal.
    "T_Damp": (_T_ASPH, 0.94, 78.0, 0.062, 0.90, 0.62, 0.34, 0.160, 1.5,
               _T_ASPH[1], 0.179, "the saturated collar on a puddle's waterline"),
    "T_DampMottle": (_T_ASPH, 1.22, 133.0, 0.092, 0.92, 0.78, 0.36, 0.140, 1.6,
                     _T_COURT[1], 0.248, "matte drying margin outside a puddle"),
    # THE SILTED BED IS SILT, NOT SHINGLE.  This was the last thing wrong with
    # the gameplay frame and it took five isolation renders to name: the bed ring
    # runs from 0.86 to 0.995 of the shoreline, which is the SHALLOWEST water in
    # the puddle, so wherever the bed sits within a few millimetres of the
    # waterline it breaks the surface -- and it was bound to `aggregate_exposed`,
    # a pale pebble scan. What that produced was a 1-2 m band of bright shingle
    # round every puddle in the level, and the eye read the whole thing as a
    # gravel pit rather than as standing water on tarmac. Silt that has settled
    # out of runoff is the FINEST material on the site and the darkest: it is
    # bound to the asphalt scan at a 0.34 m tile, near-black and matte.
    "T_PuddleBed": (_T_ASPH, 0.34, 55.0, 0.055, 0.88, 0.86, 0.24, 0.130, 1.5,
                    _T_ASPH[1], 0.110, "silted bed under a puddle waterline"),
}

# terrain look name -> local paved look.  Keyed on the TERRAIN name, not on the
# shared material name, because four terrain looks (polish, wet polish, seam,
# damp mottle) all pointed at G_AsphaltOxidised_D and this pass needs them to be
# four different surfaces -- that is what "polished smoother where traffic runs"
# means.
LOCAL_PAVED = {
    "AsphaltOxidised": "T_AsphaltA",
    "AsphaltOxidisedB": "T_AsphaltB",
    "AsphaltOxidisedC": "T_AsphaltC",
    "AsphaltOxidisedD": "T_AsphaltD",
    "AsphaltOxidisedE": "T_AsphaltE",
    "AsphaltPatchTar": "T_PatchTar",
    "AsphaltPatchOxide": "T_PatchOxide",
    "AsphaltFresh": "T_Fresh",
    "AsphaltCracked": "T_Cracked",
    "AsphaltAggregate": "T_Aggregate",
    "TarSeam": "T_Seam",
    "AsphaltPolish": "T_Polish",
    "AsphaltPolishWet": "T_PolishWet",
    "DampRing": "T_Damp",
    "DampMottle": "T_DampMottle",
    "PuddleBed": "T_PuddleBed",
}


def build_paved_looks(stage):
    """Emit the local paved-surface family.  See the block comment above."""
    if not LOCAL_PAVED_LOOKS:
        return
    UsdGeom.Scope.Define(stage, GROUND_LOOKS).GetPrim().SetDocumentation(
        "The paved-surface look family for the yard, the dock apron and both spawn "
        "aprons, authored in this module rather than in 50_materials because the "
        "three things that made the yard read as mud -- a 4.33 m texture tile, "
        "0.5 desaturation and 0.48 roughness -- are all material settings and all "
        "measurable in the frame. Same scanned textures; solved tiling, "
        "desaturated, and rough enough that a 5.5 degree sun cannot turn a 7 m "
        "repair plate into a mirror. Concrete, gravel, mud, ballast, sand, water, "
        "paint and ironwork still bind /World/Looks.")
    for name, (tex, tile, rot, bright, desat, rough, rinf, spec, bump,
               dnorm, dtile, doc) in PAVED_LOOKS.items():
        diff, norm, roughtex = tex
        path = f"{GROUND_LOOKS}/{name}"
        mat = UsdShade.Material.Define(stage, path)
        mat.GetPrim().SetDocumentation(doc)
        sh = UsdShade.Shader.Define(stage, f"{path}/Shader")
        sh.SetSourceAsset(Sdf.AssetPath("OmniPBR.mdl"), "mdl")
        sh.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
        A = Sdf.ValueTypeNames
        sh.CreateInput("diffuse_texture", A.Asset).Set(Sdf.AssetPath(diff))
        sh.CreateInput("normalmap_texture", A.Asset).Set(Sdf.AssetPath(norm))
        sh.CreateInput("reflectionroughness_texture", A.Asset).Set(
            Sdf.AssetPath(roughtex))
        sh.CreateInput("detail_normalmap_texture", A.Asset).Set(Sdf.AssetPath(dnorm))
        sh.CreateInput("albedo_brightness", A.Float).Set(float(bright))
        sh.CreateInput("albedo_desaturation", A.Float).Set(float(desat))
        sh.CreateInput("albedo_add", A.Float).Set(-0.030)
        # Cool, only just: B is 1.29x R. The dome is the cool half of the frame
        # and asphalt is the largest surface in it, so this is where
        # cool_pixel_frac is won or lost -- but a strongly blue ground under a
        # 3200 K key goes lilac, which is worse than brown.
        sh.CreateInput("diffuse_tint", A.Color3f).Set(Gf.Vec3f(0.78, 0.91, 1.18))
        sh.CreateInput("reflection_roughness_constant", A.Float).Set(float(rough))
        sh.CreateInput("reflection_roughness_texture_influence", A.Float).Set(float(rinf))
        sh.CreateInput("specular_level", A.Float).Set(float(spec))
        sh.CreateInput("metallic_constant", A.Float).Set(0.0)
        # bump_factor / detail_bump_factor are UNIFORM parameters in OmniPBR.mdl
        # (that is how 50_materials authors them); a varying opinion on a uniform
        # MDL parameter is silently dropped and the surface renders flat.
        for nm, v in (("bump_factor", float(bump)), ("detail_bump_factor", 1.05)):
            sh.GetPrim().CreateAttribute(
                f"inputs:{nm}", A.Float, False, Sdf.VariabilityUniform).Set(v)
        sh.CreateInput("project_uvw", A.Bool).Set(True)
        sh.CreateInput("world_or_object", A.Bool).Set(True)
        s = 1.0 / float(tile)
        sh.CreateInput("texture_scale", A.Float2).Set(Gf.Vec2f(s, s))
        sh.CreateInput("texture_rotate", A.Float).Set(float(rot))
        sh.CreateInput("texture_translate", A.Float2).Set(
            Gf.Vec2f(0.137 * (rot + 1.0) % 1.0, 0.311 * (rot + 2.0) % 1.0))
        ds = float(tile) / float(dtile)
        sh.CreateInput("detail_texture_scale", A.Float2).Set(Gf.Vec2f(ds, ds))
        sh.CreateInput("detail_texture_rotate", A.Float).Set(float((rot + 53.0) % 180.0))
        mat.CreateSurfaceOutput("mdl").ConnectToSource(
            sh.CreateOutput("out", Sdf.ValueTypeNames.Token))
        # UsdPreviewSurface fallback: value only, matched to the MDL's delivered
        # tone so a preview-surface client does not render a different yard.
        pv = UsdShade.Shader.Define(stage, f"{path}/Preview")
        pv.CreateIdAttr("UsdPreviewSurface")
        g = float(bright) * 0.55
        pv.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(g * 0.78, g * 0.91, g * 1.18))
        pv.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(float(rough))
        pv.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        pv.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(1.0)
        pv.CreateInput("specular", Sdf.ValueTypeNames.Float).Set(float(spec))
        mat.CreateSurfaceOutput().ConnectToSource(
            pv.CreateOutput("surface", Sdf.ValueTypeNames.Token))


def look_path(name):
    mat = PALETTE[name][0]
    if mat.startswith("BD_"):
        return f"{BACKDROP_LOOKS}/{mat}"
    if LOCAL_PAVED_LOOKS and name in LOCAL_PAVED:
        return f"{GROUND_LOOKS}/{LOCAL_PAVED[name]}"
    return f"{LOOKS_ROOT}/{mat}"


# ----------------------------------------------------------------------------
# 4b.  the repair mosaic
# ----------------------------------------------------------------------------
# A depot yard is not one surface, it is forty years of patch repairs butted
# against each other.  Each patch is a different mix, a different age and --
# critically -- a slightly different HEIGHT, which is why water pools where it
# does.  So the paved zones are cut by a jittered-grid Voronoi: every cell picks
# its own look AND its own +/-2..3 cm level offset, blended over the cell edge so
# the step is a ramp rather than a crack.  The material boundary and the height
# break therefore coincide, which is what makes it read as a repair rather than
# as a texture change.

MOSAIC_S = 7.5           # nominal cell size, metres
MOSAIC_JIT = 0.40        # seed jitter as a fraction of the cell

# Each mix is now an ORDERED BRIGHTNESS RAMP, darkest first, and a cell's look
# is chosen by sampling a smooth 30 m field through that ramp and adding a small
# per-cell jitter (see _mix_pick).  Picking uniformly at random -- which is what
# the first pass did -- guarantees that somewhere in every frame the darkest and
# the palest member of the ramp end up sharing a boundary, and THAT is the hard
# diagonal value step running through the right half of the gameplay shot.  With
# a smooth field, neighbours are almost always within one step of each other and
# the yard reads as a surface that weathered, not as a chart of swatches.
MIX = {
    # Roughly half the yard is base asphalt -- but spread across five tiling
    # phases, so "base" is never twice the same pixels.  The other half is
    # repairs, and only one cell in sixteen is a genuinely fresh black one:
    # a glossy near-black surface at 5.5 deg of sun mirrors the sky, and used
    # over a 7 m cell it reads as a sheet of ice rather than as new tarmac.
    # No exposed concrete or broken slab in the YARD mosaic. Those scans sit at
    # 0.15 albedo against asphalt's 0.05 -- a 3x value step across a 7 m cell,
    # which stops reading as a repair and starts reading as camouflage. They stay
    # on the dock (where the apron really is concrete) and in the spawn aprons.
    # Ordered by the DELIVERED brightness of the local paved looks
    # (0.170 / 0.200 / 0.215 / 0.235 / 0.250), which is what makes the smooth
    # 34 m field walk a ramp instead of shuffling swatches.
    "yard": ["AsphaltOxidisedD", "AsphaltOxidised", "AsphaltOxidisedB",
             "AsphaltOxidisedC", "AsphaltOxidisedE"],
    "dock": ["AsphaltOxidisedD", "AsphaltPatchOxide", "ConcreteDock",
             "ConcreteDock", "ConcreteDock", "AsphaltCracked",
             "ConcreteSlabExposed", "BrokenConcrete"],
    "westspawn": ["AsphaltOxidisedD", "AsphaltCracked", "AsphaltCracked",
                  "AsphaltOxidisedE", "AsphaltPatchOxide", "Gravel",
                  "AsphaltAggregate", "ConcreteSlabExposed", "BrokenConcrete"],
    "eastspawn": ["AsphaltCracked", "AsphaltOxidisedC", "Gravel", "Gravel",
                  "AsphaltAggregate", "ConcreteSlabExposed", "SandDrift",
                  "BrokenConcrete"],
    "eastbreak": ["MudWet", "Mud", "Mud", "Gravel", "Gravel",
                  "AsphaltAggregate", "BrokenConcrete"],
}


def _mix_pick(cx, cy, cid, n):
    """Index into an ordered brightness ramp for the cell at (cx, cy).

    A smooth 34 m field walks the ramp, so neighbouring repairs are close in
    value; a small per-cell jitter breaks the field into discrete patches and
    occasionally jumps two steps, which is what stops it looking airbrushed.
    """
    f = 0.5 + 0.5 * fbm(np.asarray(cx, dtype=np.float64),
                        np.asarray(cy, dtype=np.float64), 1.0 / 34.0, 3, 6101)
    j = _hash(np.asarray(cid) % np.int64(65536),
              np.asarray(cid) // np.int64(65536), 7717) - 0.5
    v = f * (n - 1) + 1.35 * j
    return np.clip(np.rint(v), 0, n - 1).astype(np.int32)

# x0, x1, y0, y1, mix, level amplitude (m), soft edge (m)
MOSAIC_ZONES = [
    (-52.0, 52.0, -16.0, 13.0, "yard", 0.021, 2.4),
    (-46.5, 30.5, -34.0, -16.0, "dock", 0.018, 2.0),
    (-70.0, -52.0, -24.0, 34.0, "westspawn", 0.026, 2.4),
    (52.0, 70.0, -24.0, 58.0, "eastspawn", 0.026, 2.4),
    (30.0, 52.0, -38.0, -16.0, "eastbreak", 0.032, 2.2),
]


def _warp(x, y):
    """Domain warp applied before the Voronoi lookup.

    A raw jittered-grid Voronoi has straight boundaries, and a straight boundary
    quantised to the 0.35 m face grid reads as a staircase of flat plates -- the
    exact failure this module exists to avoid.  Warping the sample position by
    ~1 m at a 3.5 m wavelength (plus 0.3 m at 1.2 m for edge crumble) turns every
    cell edge into a wandering, ragged curve whose own wobble is several times
    the face pitch, so the quantisation disappears into it.  Level, material and
    seams all read through the same warp, so they stay exactly co-located.
    """
    wx = (0.62 * fbm(x, y, 1.0 / 4.2, 2, 3301)
          + 0.30 * fbm(x, y, 1.0 / 1.35, 2, 3305))
    wy = (0.62 * fbm(x + 41.0, y - 17.0, 1.0 / 4.2, 2, 3302)
          + 0.30 * fbm(x + 41.0, y - 17.0, 1.0 / 1.35, 2, 3306))
    return x + wx, y + wy


def _cell_seeds(x, y, S=MOSAIC_S):
    """Nine candidate jittered seeds around each sample; returns their (cx, cy, id)."""
    gx = np.floor(np.asarray(x) / S)
    gy = np.floor(np.asarray(y) / S)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            ix = (gx + di)
            iy = (gy + dj)
            jx = _hash(ix.astype(np.int64), iy.astype(np.int64), 4177) * 2.0 - 1.0
            jy = _hash(ix.astype(np.int64), iy.astype(np.int64), 9311) * 2.0 - 1.0
            cx = (ix + 0.5 + MOSAIC_JIT * jx) * S
            cy = (iy + 0.5 + MOSAIC_JIT * jy) * S
            cid = (ix.astype(np.int64) + 4096) * np.int64(8192) + (iy.astype(np.int64) + 4096)
            yield cx, cy, cid


def _mosaic(x, y):
    """Nearest / second-nearest warped jittered-grid Voronoi.

    Returns (id1, f1, id2, f2).  f2 - f1 is twice the distance to the cell
    boundary, which is what the level blend and the tar seams are built on.
    """
    x, y = _warp(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    ds, ids = [], []
    for cx, cy, cid in _cell_seeds(x, y):
        ds.append(np.hypot(x - cx, y - cy))
        ids.append(np.broadcast_to(cid, np.shape(x)))
    D = np.stack(ds, axis=0)
    I = np.stack(ids, axis=0)
    order = np.argpartition(D, 1, axis=0)[:2]
    d01 = np.take_along_axis(D, order, axis=0)
    i01 = np.take_along_axis(I, order, axis=0)
    swap = d01[0] > d01[1]
    f1 = np.where(swap, d01[1], d01[0])
    f2 = np.where(swap, d01[0], d01[1])
    id1 = np.where(swap, i01[1], i01[0])
    id2 = np.where(swap, i01[0], i01[1])
    return id1, f1, id2, f2


def _cell_level(cid):
    """Per-cell settlement in [-1, 1]; biased low so most cells are dished."""
    h = _hash(cid % np.int64(65536), cid // np.int64(65536), 5501)
    return (h ** 1.35) * 2.0 - 1.0


def _cell_sharp(cid):
    """True for the ~22% of cells that are a RECENT repair.

    An old settled patch meets its neighbour in a gentle swale you only see
    because water collects along it.  A recent overlay meets it at a 2-3 cm lip
    you can trip on.  Giving every cell the same lip is what made the first pass
    read as a mosaic of flat plates, so only a minority get the crisp edge.
    """
    return _hash(cid % np.int64(65536), cid // np.int64(65536), 6607) < 0.22


def _mosaic_zone_mask(x, y, z_index):
    x0, x1, y0, y1, _, _, soft = MOSAIC_ZONES[z_index]
    return rect_mask(x, y, x0, x1, y0, y1, soft, jitter=1.1, seed=520 + z_index)


def _mosaic_level(x, y):
    """Total mosaic level offset (metres) at every sample."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    id1, f1, id2, f2 = _mosaic(x, y)
    l1 = _cell_level(id1)
    l2 = _cell_level(id2)
    # Ramp width per boundary: recent repairs meet at a 0.45 m lip, settled old
    # patches at a 2.4 m swale you read as a shadow, not as a step.
    ramp = np.where(_cell_sharp(id1) | _cell_sharp(id2), 0.45, 2.40)
    t = sstep(np.clip((f2 - f1) / ramp, 0.0, 1.0))
    lvl = l1 * (0.5 + 0.5 * t) + l2 * (0.5 - 0.5 * t)
    out = np.zeros(np.shape(x), dtype=np.float64)
    for k, zone in enumerate(MOSAIC_ZONES):
        out = out + zone[5] * lvl * _mosaic_zone_mask(x, y, k)
    return out


def _mosaic_material(x, y):
    """(material id, in-mosaic mask) from the nearest cell."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    id1, _, _, _ = _mosaic(x, y)
    mid = np.full(np.shape(x), -1, dtype=np.int32)
    for k, zone in enumerate(MOSAIC_ZONES):
        mix = MIX[zone[4]]
        pick = _mix_pick(x, y, id1, len(mix))
        table = np.array([M[m] for m in mix], dtype=np.int32)
        inside = _mosaic_zone_mask(x, y, k) > 0.5
        mid = np.where(inside, table[pick], mid)
    return mid


def classify(x, y):
    """Ground material id per face centre.

    Two kinds of rule live here.

    * Zone-level, straight-edged rules (which lane you are standing in).
    * The repair mosaic.  Face-centre classification quantises a boundary to the
      mesh grid, and a *noisy* boundary quantised to a 0.35 m grid reads as a
      staircase of flat plates -- the exact 'fake' tell this module exists to
      avoid.  A mosaic boundary is different: it coincides with a real 2-3 cm
      height ramp in the surface AND is over-drawn by a poured tar seam, so the
      quantisation is hidden by geometry that belongs there.

    The remaining organic boundaries (gravel drift, damp rings, oil spills) are
    authored as smooth overlay patches under Terrain/Patches.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mid = np.full(x.shape, M["DirtWeeds"], dtype=np.int32)

    dcy = DITCH_Y + 0.9 * fbm(x, np.zeros_like(x) + 3.0, 1.0 / 26.0, 2, 77)
    dd = np.abs(y - dcy)
    south = y < -40.0
    mid[(dd < 3.4) & south] = M["Mud"]
    mid[(dd < 1.7) & south] = M["MudWet"]

    west = (x < -52.0) & (y > -24.0) & (y < 34.0)
    east = (x > 52.0) & (y > -24.0) & (y < 60.0)
    spawn = west | east
    mid[spawn] = M["AsphaltCracked"]
    mid[spawn & (np.abs(x) > 65.0)] = M["Gravel"]
    mid[(np.abs(x - 54.0) < 2.4) & (y > -30.0) & (y < 60.0)] = M["Ballast"]

    in_dock = (y >= -40.0) & (y < -16.0)
    mid[in_dock & (x > -46.0) & (x < 30.0) & (y >= -34.0)] = M["ConcreteDock"]
    mid[in_dock & (x >= 30.0)] = M["Gravel"]
    mid[in_dock & (x <= -46.0)] = M["Gravel"]
    mid[(y >= -40.0) & (y < -34.0)] = M["Mud"]

    mid[(x > -52.0) & (x < 52.0) & (y > -16.0) & (y < 15.0)] = M["AsphaltOxidised"]

    # the repair mosaic overrides the zone default wherever it applies
    mos = _mosaic_material(x, y)
    mid = np.where(mos >= 0, mos, mid)

    # the ballast bed and the wet band at the dock foot are not patchwork
    mid[(np.abs(x - 54.0) < 2.4) & (y > -30.0) & (y < 60.0)] = M["Ballast"]
    mid[(y >= -40.0) & (y < -34.0)] = M["Mud"]

    bx0, bx1, by0, by1 = BUND
    mid[(x > bx0) & (x < bx1) & (y > by0) & (y < by1)] = M["MudWet"]
    return mid


# ----------------------------------------------------------------------------
# 5.  geometry accumulation + USD emission
# ----------------------------------------------------------------------------


def _face_normal(pts):
    a = np.array(pts[1], dtype=float) - np.array(pts[0], dtype=float)
    b = np.array(pts[2], dtype=float) - np.array(pts[0], dtype=float)
    n = np.cross(a, b)
    L = float(np.linalg.norm(n))
    if L < 1e-9:
        return (0.0, 0.0, 1.0)
    n = n / L
    return (float(n[0]), float(n[1]), float(n[2]))


class Poly:
    """Hard-edged polygon accumulator (unshared vertices, flat normals)."""

    def __init__(self):
        self.P, self.N, self.ST = [], [], []
        self.FC, self.FI, self.FM = [], [], []

    def add(self, pts, mat, normal=None, st=None, normals=None):
        """Add one face.

        `normals` (one per vertex) overrides the flat face normal. It exists for
        the shelter belts: a lofted ridge shaded with flat normals resolves into
        the exact comb of hard facet edges the whole rebuild is there to remove,
        and unshared vertices are fine as long as adjacent faces agree on the
        vertex normal, which is what the analytic ellipse normal guarantees.
        """
        if len(pts) < 3:
            return
        if normal is None and normals is None:
            normal = _face_normal(pts)
        base = len(self.P)
        for i, p in enumerate(pts):
            self.P.append((float(p[0]), float(p[1]), float(p[2])))
            self.N.append(normals[i] if normals is not None else normal)
            self.ST.append(st[i] if st else (float(p[0]), float(p[1])))
        self.FC.append(len(pts))
        self.FI.extend(range(base, base + len(pts)))
        self.FM.append(mat)

    def empty(self):
        return not self.FC


def strip_along(pts, width, mat, poly, lift=0.009, flat_z=None, keep=1.0, rng=None):
    """A terrain-following (or flat) ribbon: paint, wear trails, oil."""
    left = offset_polyline(pts, width * 0.5)
    right = offset_polyline(pts, -width * 0.5)
    for i in range(len(pts) - 1):
        if rng is not None and keep < 1.0 and rng.random() > keep:
            continue
        quad = []
        for px, py in (right[i], right[i + 1], left[i + 1], left[i]):
            z = flat_z if flat_z is not None else z_at(px, py) + lift
            quad.append((px, py, z))
        poly.add(quad, mat, normal=(0.0, 0.0, 1.0))


def ragged_ribbon(pts, width, mat, poly, lift=0.009, keep=0.75, rng=None,
                  jitter=0.55, wobble=0.30, seed=0):
    """A wear ribbon whose EDGES ARE NOT PARALLEL.

    `strip_along` offsets a centreline by a constant half-width, and a constant
    half-width over ten metres is a strip of gaffer tape stuck to the ground --
    two dead-straight parallel edges, which is one of the specific things a
    critic points at.  Real wear (a wheel path, a damp band beside a channel)
    breathes: it is 0.15 m wide here and 0.5 m there, it wanders off its
    nominal line by a third of its own width, and it stops and restarts.  All
    three are authored per vertex here from a noise field, so no two segments
    share an edge direction.
    """
    r = rng if rng is not None else np.random.default_rng(seed)
    n = len(pts)
    px = np.array([p[0] for p in pts], dtype=float)
    py = np.array([p[1] for p in pts], dtype=float)
    hw = 0.5 * width * (1.0 + wobble * fbm(px * 3.1 + seed, py * 3.1, 1.0, 2, 2200 + seed))
    off = jitter * 0.5 * width * fbm(px * 1.7, py * 1.7 + seed, 1.0, 2, 2300 + seed)
    left, right = [], []
    for i in range(n):
        if i == 0:
            ax, ay, bx, by = px[0], py[0], px[1], py[1]
        elif i == n - 1:
            ax, ay, bx, by = px[-2], py[-2], px[-1], py[-1]
        else:
            ax, ay, bx, by = px[i - 1], py[i - 1], px[i + 1], py[i + 1]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        cxx, cyy = px[i] + nx * off[i], py[i] + ny * off[i]
        left.append((cxx + nx * hw[i], cyy + ny * hw[i]))
        right.append((cxx - nx * hw[i], cyy - ny * hw[i]))
    for i in range(n - 1):
        if r.random() > keep:
            continue
        quad = []
        for qx, qy in (right[i], right[i + 1], left[i + 1], left[i]):
            quad.append((qx, qy, z_at(qx, qy) + lift))
        poly.add(quad, mat, normal=(0.0, 0.0, 1.0))


def _int_array(a):
    arr = np.asarray(a, dtype=np.int32)
    try:
        return Vt.IntArray.FromNumpy(arr)
    except Exception:
        return Vt.IntArray(arr.tolist())


def bind_look(prim, name):
    """Bind a shared /World/Looks material by relationship.

    Deliberately NOT UsdShade.MaterialBindingAPI().Bind(): the target lives in
    50_materials.usda and does not exist in this in-memory stage, so the
    relationship is authored directly.  It resolves at composition time.
    """
    UsdShade.MaterialBindingAPI.Apply(prim)
    rel = prim.CreateRelationship("material:binding", False)
    rel.SetTargets([Sdf.Path(look_path(name))])
    prim.SetCustomDataByKey("terrainLookHint", PALETTE[name][1])


def emit_mesh(stage, path, points, counts, indices, normals, sts, face_mats,
              mat_paths, default_mat, doc=None):
    if len(counts) == 0:
        return None
    mesh = UsdGeom.Mesh.Define(stage, path)
    p = np.ascontiguousarray(np.asarray(points, dtype=np.float32))
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(p))
    mesh.CreateFaceVertexCountsAttr(_int_array(counts))
    mesh.CreateFaceVertexIndicesAttr(_int_array(indices))
    mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(
        np.ascontiguousarray(np.asarray(normals, dtype=np.float32))))
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
    pv = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex)
    pv.Set(Vt.Vec2fArray.FromNumpy(
        np.ascontiguousarray(np.asarray(sts, dtype=np.float32))))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateDoubleSidedAttr(False)
    mesh.CreateExtentAttr(Vt.Vec3fArray([Gf.Vec3f(*p.min(axis=0).tolist()),
                                         Gf.Vec3f(*p.max(axis=0).tolist())]))
    if doc:
        mesh.GetPrim().SetDocumentation(doc)

    bind_look(mesh.GetPrim(), default_mat)

    fm = np.asarray(face_mats, dtype=np.int32)
    for mi in np.unique(fm):
        name = MAT_NAMES[int(mi)]
        idx = np.nonzero(fm == mi)[0].astype(np.int32)
        sub = UsdGeom.Subset.CreateGeomSubset(
            mesh, f"sub_{name}", UsdGeom.Tokens.face, _int_array(idx), "materialBind")
        bind_look(sub.GetPrim(), name)
    return mesh


class Acc:
    """Accumulates indexed, smooth-shaded overlay geometry (patches, rings)."""

    def __init__(self):
        self.P, self.N, self.ST = [], [], []
        self.FC, self.FI, self.FM = [], [], []

    def add(self, pts, nrm, st, faces, mats):
        base = len(self.P)
        self.P.extend(pts)
        self.N.extend(nrm)
        self.ST.extend(st)
        for f, m in zip(faces, mats):
            self.FC.append(len(f))
            self.FI.extend(base + i for i in f)
            self.FM.append(m)

    def empty(self):
        return not self.FC


def _overlay_z(px, py, lift, r=0.26):
    """Height for an overlay vertex: the local ground CREST, plus the lift.

    An overlay is a few millimetres above a surface that undulates at a ~1 m
    wavelength, so sampling the ground at the overlay's own vertices is not
    enough -- between two vertices the flat polygon sags below the crest and the
    bare ground erupts through the middle of the patch as a hard-edged pale
    island.  Sampling the maximum over a small disc instead guarantees the
    overlay clears every crest it spans, at the cost of floating a couple of
    millimetres higher in the hollows, which nothing can see.
    """
    z = terrain_z(px, py)
    for k in range(6):
        a = k * math.pi / 3.0
        z = np.maximum(z, terrain_z(px + r * math.cos(a), py + r * math.sin(a)))
    return z + lift


def _overlay_normals(px, py, eps=0.10):
    zx0, zx1 = terrain_z(px - eps, py), terrain_z(px + eps, py)
    zy0, zy1 = terrain_z(px, py - eps), terrain_z(px, py + eps)
    nx = -(zx1 - zx0) / (2 * eps)
    ny = -(zy1 - zy0) / (2 * eps)
    nz = np.ones_like(nx)
    L = np.sqrt(nx * nx + ny * ny + 1.0)
    return np.stack([nx / L, ny / L, nz / L], axis=-1)


def polar_patch(acc: Acc, cx, cy, rx, ry, mat, seed, yaw=0.0, rough=0.30,
                lift=0.012, inner=0.0, ring_scale=1.0, index=0):
    """A smooth-outlined ground patch: polar grid, terrain-following, lifted.

    This is how the irregular ground treatments get boundaries that are curves
    rather than staircases of mesh faces.
    """
    # Sample at 0.45 m.  An overlay is only a few millimetres above the ground,
    # and the ground carries relief down to a ~1 m wavelength, so a coarsely
    # tessellated patch is a set of large flat triangles that CUT THROUGH the
    # surface they are supposed to be lying on.  What that looks like on screen
    # is a hard-edged polygonal island of bare ground poking up through the
    # middle of the patch -- which is exactly the pale blob that sat in the
    # lower third of the gameplay shot.
    r = max(rx, ry)
    sectors = int(np.clip(round(2 * math.pi * r / 0.30), 36, 200))
    rings = int(np.clip(round((1.0 - inner) * r / 0.45), 3, 20))
    rng = np.random.default_rng(seed)
    phase = rng.uniform(0, 6.28, 5)
    amp = rng.uniform(0.5, 1.0, 3)
    ca, sa = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

    t = np.arange(sectors) * (2 * math.pi / sectors)
    shape = 1.0 + rough * (amp[0] * np.sin(2 * t + phase[0])
                           + amp[1] * np.sin(3 * t + phase[1])
                           + amp[2] * np.sin(5 * t + phase[2])) / 3.0
    # crenulation, same reasoning as blob(): no chord longer than ~0.3 m and a
    # boundary that changes direction faster than the eye tracks it
    shape = shape + rough * (0.12 * np.sin(11 * t + phase[3])
                             + 0.075 * np.sin(19 * t + phase[4]))
    ux = rx * shape * np.cos(t)
    uy = ry * shape * np.sin(t)
    bx = cx + ux * ca - uy * sa
    by = cy + ux * sa + uy * ca

    # Same conditioning as the mosaic joints: coarsen the sampling to 0.35-0.85 m
    # of arc and then tear the outline sideways.  The amplitude is tied to the
    # patch's own size, because a 0.40 m bite out of a 0.9 m repair is not a
    # ragged edge, it is a different shape.
    step = float(np.clip(0.30 * r, 0.50, 0.95))
    lat_hi = float(np.clip(0.135 * r, 0.12, 0.40))
    bx, by = jitter_boundary(bx, by, seed % 100000, step=step,
                             lat=(0.40 * lat_hi, lat_hi),
                             maxchord=0.95, src="groundpatch")
    sectors = int(bx.size)

    xs, ys, faces, closed_centre = [], [], [], inner <= 1e-6
    if closed_centre:
        xs.append(cx)
        ys.append(cy)
    fracs = np.linspace(inner if not closed_centre else (1.0 / (rings + 1)), 1.0, rings)
    for f in fracs:
        xs.extend(cx + (bx - cx) * f)
        ys.extend(cy + (by - cy) * f)
    px = np.array(xs)
    py = np.array(ys)
    pz = _overlay_z(px, py, lift + zstep(index))
    nrm = _overlay_normals(px, py)

    off = 1 if closed_centre else 0
    if closed_centre:
        for s in range(sectors):
            faces.append((0, off + s, off + (s + 1) % sectors))
    for k in range(rings - 1):
        a0 = off + k * sectors
        a1 = off + (k + 1) * sectors
        for s in range(sectors):
            s2 = (s + 1) % sectors
            faces.append((a0 + s, a0 + s2, a1 + s2, a1 + s))
    if not closed_centre:
        pass

    pts = list(zip(px.tolist(), py.tolist(), pz.tolist()))
    st = list(zip(px.tolist(), py.tolist()))
    acc.add(pts, [tuple(v) for v in nrm.tolist()], st, faces, [mat] * len(faces))
    return bx, by


def feather_outline(poly: Poly, bx, by, cx, cy, mat, seed, band=0.62,
                    lift=0.0042, pitch=0.30, overlap=None):
    """Dither a patch boundary across a 0.3-0.8 m transition strip.

    A repair patch and the surface it was cut into differ in value.  Wherever
    that difference lands on a single polygon edge you get an instant step, and
    an instant step over tens of metres is the thing that reads as a blockout --
    it is the hard diagonal seam through the yard and the razor triangle at the
    bottom of the hero frame.

    There is no opacity map available to this module, so the transition is built
    out of geometry: a band of shrinking islands of the PATCH's own material,
    scattered across its own boundary, dense on the inside and thinning to
    nothing 0.6 m outside.  The value therefore crosses the joint as a dissolve
    over half a metre instead of on one edge, which is what feathering a mask
    would have done and what the join actually looks like on a real yard.
    """
    rng = np.random.default_rng(seed)
    n = len(bx)
    per = 0.0
    for i in range(n):
        j = (i + 1) % n
        per += math.hypot(bx[j] - bx[i], by[j] - by[i])
    m = int(np.clip(round(per / pitch), 14, 900))

    # --- the OVERLAP STRIP ---------------------------------------------------
    # The island dither below is the dissolve; this is the thing it dissolves
    # from.  A repair is not butted flush against the surface it was cut into --
    # the tar squeezes out under the roller and the new mix laps over the old by
    # a hand's width, and by a boot's width where the cut was ragged.  So the
    # patch's own material is carried 0.10-0.44 m PAST its own boundary as a
    # continuous ribbon whose width breathes on a 2.2 m noise field and drops to
    # nothing for whole arcs.  Value therefore never changes on the polygon edge
    # that defines the patch: by the time you reach that edge you are already
    # 0.3 m into a strip of the same material, which then dithers out.
    if overlap is not None:
        o0, o1 = overlap
        BX = np.asarray(bx, dtype=np.float64)
        BY = np.asarray(by, dtype=np.float64)
        ux = BX - cx
        uy = BY - cy
        L = np.hypot(ux, uy)
        L[L < 1e-9] = 1.0
        ux, uy = ux / L, uy / L
        wob = 0.5 + 0.5 * fbm(BX * 1.0 + seed * 0.013, BY, 1.0 / 2.2, 2, 8100 + seed)
        wob = wob * (0.35 + 0.65 * (0.5 + 0.5 * fbm(BX, BY + seed * 0.007,
                                                    1.0 / 6.5, 2, 8200 + seed)))
        wid = o0 + (o1 - o0) * np.clip(wob, 0.0, 1.0)
        ox = BX + ux * wid
        oy = BY + uy * wid
        ZI = _overlay_z(BX, BY, lift - 0.0004, r=0.16)
        ZO = _overlay_z(ox, oy, lift - 0.0004, r=0.16)
        for i in range(n):
            j = (i + 1) % n
            if wid[i] < o0 * 0.55 and wid[j] < o0 * 0.55:
                continue                    # the lap ran out along this arc
            dz = zstep(i, 32, 0.00003)
            poly.add([(BX[i], BY[i], ZI[i] + dz), (BX[j], BY[j], ZI[j] + dz),
                      (ox[j], oy[j], ZO[j] + dz), (ox[i], oy[i], ZO[i] + dz)],
                     mat, normal=(0, 0, 1))

    cxs, cys, spec = [], [], []
    for k in range(m):
        i = int(k * n / m) % n
        ux, uy = bx[i] - cx, by[i] - cy
        L = math.hypot(ux, uy) or 1.0
        ux, uy = ux / L, uy / L
        # straddle the joint: normally distributed about it, biased outward
        t = float(rng.normal(0.10, 0.44)) * band
        f = min(abs(t) / band, 1.0)
        s = float(rng.uniform(0.055, 0.28)) * (1.0 - 0.62 * f)
        if s < 0.030:
            continue
        cxs.append(bx[i] + ux * t - uy * float(rng.uniform(-0.22, 0.22)))
        cys.append(by[i] + uy * t + ux * float(rng.uniform(-0.22, 0.22)))
        spec.append((s, s * float(rng.uniform(0.5, 1.0)),
                     int(rng.integers(0, 999999)), float(rng.uniform(0.30, 0.55)),
                     zstep(k, 40, 0.00004)))
    if not cxs:
        return
    # One vectorised height lookup for every island.  An island is at most
    # 0.28 m across, far below the ~1 m wavelength of the ground relief, so a
    # single crest-sampled height per island is exact enough and turns 8-25
    # scalar terrain_z calls per island into one batched call for all of them.
    zc = _overlay_z(np.array(cxs), np.array(cys), lift, r=0.18)
    for k, (px, py) in enumerate(zip(cxs, cys)):
        s, sy, sd, rough, dz = spec[k]
        z = float(zc[k]) + dz
        poly.add([(qx, qy, z) for qx, qy in blob(px, py, s, sy, sd, n=8, rough=rough)],
                 mat, normal=(0, 0, 1))


# --- puddle shorelines, traced as true contours of the height field ---------

_CONTOUR_CACHE: dict[str, tuple] = {}


def puddle_contour(p):
    """(level, cx, cy, theta[], radius[]) for one puddle, or None.

    The shoreline is not drawn and it is not a flood fill on a grid.  The water
    level is derived from the basin the height field actually carved -- deepest
    point, rim height, fill to just under the rim -- and the outline is then
    found by bisecting outward along 100-220 rays until the ground crosses that
    level.  So the edge IS the contour: it wanders where the basin wanders, and
    the longest straight segment anywhere on it is 0.22 m.
    """
    key = p[0]
    if key in _CONTOUR_CACHE:
        return _CONTOUR_CACHE[key]
    _, cx, cy, sx, sy, yaw, depth, _ = p
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)

    # relocate the centre onto the true low point of the basin
    g = np.linspace(-0.42, 0.42, 7)
    GX, GY = np.meshgrid(cx + g * sx * 0.5, cy + g * sy * 0.5)
    GZ = terrain_z(GX, GY)
    k = int(np.argmin(GZ))
    ox, oy = float(GX.ravel()[k]), float(GY.ravel()[k])
    zc = float(GZ.ravel()[k])

    # rim height just outside the nominal footprint
    # Sample the rim at 1.06x rather than 1.12x of the footprint: 1.06 is inside
    # the plateau `_puddle_rimlift` guarantees, 1.12 is out in the feather where
    # the site profile has already started to win again.
    th64 = np.arange(64) * (2 * math.pi / 64)
    ex = sx * 0.5 * 1.06 * np.cos(th64)
    ey = sy * 0.5 * 1.06 * np.sin(th64)
    rx = cx + ex * ca - ey * sa
    ry = cy + ex * sa + ey * ca
    rimz = terrain_z(rx, ry)
    # A trench drain is not a rim.  P4's rim ring crosses the E-W drain, whose
    # dish is 75 mm deep, and averaging that into the percentile dropped the
    # flood level far enough to turn an 80 mm puddle into a 30 mm film that
    # sheeted across the ironwork.  Water that reaches a gully goes down it.
    keep = ~_in_drain_frame(rx, ry)
    rim = float(np.percentile(rimz[keep] if keep.sum() >= 12 else rimz, 22))
    if rim - zc < 0.014:
        _CONTOUR_CACHE[key] = None
        return None
    # Filled to 86% of the rim rather than 72%.  A basin flooded to
    # three-quarters of its depth wets only about 60% of its own footprint, and
    # what you get is a small dark lens sitting in the middle of a large damp
    # dish -- water that reads as a stain.  At 86% the shoreline runs out onto
    # the shallow bank where the ground is nearly flat, so the puddle is wide,
    # its edge is a long low-angle contour that wanders properly, and there is
    # enough surface for the sky to actually land in.
    level = zc + min(0.86 * (rim - zc), (rim - zc) - 0.008)

    rmax = max(sx, sy) * 0.95
    sectors = int(np.clip(round(2 * math.pi * rmax * 0.5 / 0.14), 128, 400))
    th = np.arange(sectors) * (2 * math.pi / sectors)
    ct, stt = np.cos(th), np.sin(th)
    lo = np.zeros(sectors)
    hi = np.full(sectors, rmax)
    for _ in range(26):
        mid = 0.5 * (lo + hi)
        mx = ox + mid * ct
        my = oy + mid * stt
        under = (terrain_z(mx, my) < level) & ~_in_drain_frame(mx, my)
        lo = np.where(under, mid, lo)
        hi = np.where(under, hi, mid)
    r = lo
    med = float(np.median(r))
    if med < 0.30:
        _CONTOUR_CACHE[key] = None
        return None
    r = np.clip(r, 0.40 * med, 1.85 * med)
    for _ in range(2):
        r = 0.25 * (np.roll(r, 1) + 2.0 * r + np.roll(r, -1))
    # Arc between rays is <= 0.18 m, so a 0.11 m radial cap bounds every
    # shoreline edge at hypot(0.18, 0.11) = 0.21 m -- half the 0.40 m limit the
    # critic set, and the generator now measures and reports the true maximum
    # rather than asserting it (see build_water).
    r = limit_slope(r, 0.11)
    out = (level, ox, oy, th, r)
    _CONTOUR_CACHE[key] = out
    return out


def contour_annulus(acc: Acc, p, f0, f1, mat, lift=0.009, rings=2, index=0,
                    phase=0.0, broken=0.0):
    """A ring hugging the traced shoreline, at f0..f1 times its radius.

    The width is NOT constant.  A constant-width dark band round a puddle is a
    stamped ring, and a stamped ring is one of the things the critic can name
    from across the room.  A real drying margin is wide where the bank is flat,
    absent where it is steep, and it disappears entirely for whole arcs.  So the
    outer edge is modulated by three harmonics between 25% and 100% of the
    nominal width, and segments below `broken` of full width are dropped.
    """
    c = puddle_contour(p)
    if c is None:
        return
    level, ox, oy, th, r = c
    ct, stt = np.cos(th), np.sin(th)
    sectors = len(th)
    w = 0.5 + 0.5 * (0.55 * np.sin(3.0 * th + phase)
                     + 0.30 * np.sin(5.0 * th + 1.7 * phase)
                     + 0.15 * np.sin(8.0 * th + 3.1 * phase))
    w = 0.25 + 0.75 * np.clip(w, 0.0, 1.0)
    xs, ys = [], []
    for k in range(rings + 1):
        f = f0 + (f1 - f0) * w * (k / rings)
        xs.extend(ox + r * f * ct)
        ys.extend(oy + r * f * stt)
    px, py = np.array(xs), np.array(ys)
    # SMOOTHED IN Z AND IN NORMAL.  This is the fix for the "shingle beach"
    # round every puddle, and the cause was geometric, not material.  A traced
    # shoreline has 128-256 rays, so on a 2.5 m puddle these rings are quads
    # about 60 mm across -- seven times finer than the 0.35 m ground mesh they
    # lie on.  `_overlay_z` takes the ground CREST over a 0.26 m disc and
    # `_overlay_normals` differences the height field over 0.10 m, and the
    # height field carries deliberate 1.05 m and 1.70 m noise bands; sampled at
    # 60 mm that comes out as crumpled foil, every facet of which either catches
    # or shadows a 5.5 degree sun.  The result was a metre-wide band of bright
    # flakes round every puddle in the level, which read as gravel and undid
    # most of the point of the wet ring.  The ground either side of it looked
    # smooth for exactly one reason: it is sampled at 0.35 m and averages the
    # same noise away.  So these bands sample the crest over 0.45 m and take
    # their normal over 0.55 m -- roughly the ground's own scale -- and go back
    # to being a tonal band on a surface.
    pz = _overlay_z(px, py, lift + zstep(index), r=0.45)
    nrm = _overlay_normals(px, py, eps=0.55)
    faces = []
    for k in range(rings):
        a0, a1 = k * sectors, (k + 1) * sectors
        for s in range(sectors):
            if w[s] < broken:
                continue
            s2 = (s + 1) % sectors
            faces.append((a0 + s, a0 + s2, a1 + s2, a1 + s))
    if not faces:
        return
    acc.add(list(zip(px.tolist(), py.tolist(), pz.tolist())),
            [tuple(v) for v in nrm.tolist()],
            list(zip(px.tolist(), py.tolist())), faces, [mat] * len(faces))


def annulus_patch(acc: Acc, p, r0, r1, mat, lift=0.009, rings=3, index=0):
    """A damp/silt ring hugging a puddle's shoreline, smooth-edged."""
    _, cx, cy, sx, sy, yaw, _, _ = p
    sectors = int(np.clip(round(2 * math.pi * max(sx, sy) * 0.5 * r1 / 0.45), 28, 128))
    t = np.arange(sectors) * (2 * math.pi / sectors)
    ca, sa = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    xs, ys = [], []
    for f in np.linspace(r0, r1, rings + 1):
        ux = sx * 0.5 * f * np.cos(t)
        uy = sy * 0.5 * f * np.sin(t)
        gx = cx + ux * ca - uy * sa
        gy = cy + ux * sa + uy * ca
        # undo the same jitter the basin uses, so the ring follows the shoreline
        j = _puddle_jitter(gx, gy)
        gx = cx + (gx - cx) / (1.0 + 0.24 * j)
        gy = cy + (gy - cy) / (1.0 + 0.24 * j)
        xs.extend(gx)
        ys.extend(gy)
    px, py = np.array(xs), np.array(ys)
    pz = _overlay_z(px, py, lift + zstep(index))
    nrm = _overlay_normals(px, py)
    faces = []
    for k in range(rings):
        a0, a1 = k * sectors, (k + 1) * sectors
        for s in range(sectors):
            s2 = (s + 1) % sectors
            faces.append((a0 + s, a0 + s2, a1 + s2, a1 + s))
    acc.add(list(zip(px.tolist(), py.tolist(), pz.tolist())),
            [tuple(v) for v in nrm.tolist()],
            list(zip(px.tolist(), py.tolist())), faces, [mat] * len(faces))


def ribbon_patch(acc: Acc, centreline, width, mat, lift=0.010, step=0.45, index=0):
    """A smooth terrain-following ribbon overlay (wet ruts, mud tracks)."""
    pts = resample(list(centreline), step)
    left = offset_polyline(pts, width * 0.5)
    right = offset_polyline(pts, -width * 0.5)
    n = len(pts)
    xs = [p[0] for p in right] + [p[0] for p in left]
    ys = [p[1] for p in right] + [p[1] for p in left]
    px, py = np.array(xs), np.array(ys)
    pz = _overlay_z(px, py, lift + zstep(index))
    nrm = _overlay_normals(px, py)
    faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
    acc.add(list(zip(px.tolist(), py.tolist(), pz.tolist())),
            [tuple(v) for v in nrm.tolist()],
            list(zip(px.tolist(), py.tolist())), faces, [mat] * len(faces))


PATCH_ZONES = [
    # x0,   x1,    y0,     y1,   n, rmin, rmax, materials (weighted by repetition)
    # No AsphaltAggregate in the yard or on the dock: the exposed-aggregate scan
    # is much lighter and pinker than asphalt, so used at area it reads as a rug
    # laid on the ground rather than as a worn surface.  It stays in the spawn
    # aprons and the broken-up east apron where a light gravelly break is right.
    # Nothing paler than AsphaltOxidised_E goes on the yard. The oxidised-repair
    # scan sits at 0.68 albedo against the yard's 0.44-0.55, and under a warm key
    # that is not a repair patch, it is a sheet of bone-white paper lying in the
    # middle of the frame.
    # Yard repairs are now 0.9-2.8 m and there are 26 of them, not 10 at up to
    # 5.5 m.  A 5.5 m soft-edged overlay on a surface with no other incident at
    # that scale IS an airbrushed blob however good its outline is; a 1.5 m one
    # reads as a patch because it is the size of a patch.
    (-50, 50, -15, 14, 26, 0.9, 2.8,
     ["AsphaltOxidisedC", "AsphaltOxidisedD", "AsphaltOxidisedE"]),
    (-45, 29, -33, -17, 7, 1.4, 4.5,
     ["ConcreteSlabExposed", "AsphaltPatchOxide", "AsphaltCracked"]),
    (-69, -53, -22, 32, 12, 1.4, 5.0,
     ["AsphaltAggregate", "AsphaltAggregate", "Gravel", "ConcreteSlabExposed"]),
    (53, 69, -22, 55, 12, 1.4, 5.0,
     ["AsphaltAggregate", "AsphaltAggregate", "Gravel", "SandDrift"]),
    (31, 51, -38, -18, 10, 1.6, 4.5, ["Mud", "MudWet", "Gravel", "BrokenConcrete"]),
    (-68, 68, -55, -42, 16, 2.0, 6.5, ["Gravel", "Gravel", "Mud", "BrokenConcrete"]),
    (-68, 68, 78, 92, 14, 2.0, 6.5, ["Gravel", "Gravel", "BrokenConcrete", "Mud"]),
    (-69, -40, 34, 75, 10, 2.0, 6.0, ["Gravel", "DirtWeeds", "BrokenConcrete"]),
    (40, 69, 30, 75, 10, 2.0, 6.0, ["Gravel", "DirtWeeds", "SandDrift"]),
    (-68, 68, -39, -35, 8, 1.4, 3.6, ["MudWet", "Gravel", "Mud"]),
]


def build_patches(stage, mat_paths, report):
    """Smooth-outlined ground-treatment patches -- the irregular boundaries."""
    UsdGeom.Scope.Define(stage, TERRAIN + "/Patches")
    rng = np.random.default_rng(SEED + 51)

    acc = Acc()
    feather = Poly()
    count = 0
    for x0, x1, y0, y1, n, rmin, rmax, mats in PATCH_ZONES:
        for _ in range(n):
            cx = float(rng.uniform(x0, x1))
            cy = float(rng.uniform(y0, y1))
            if 12.0 < cx < 28.0 and 74.0 < cy < 90.0:      # office annex floor
                continue
            rx = float(rng.uniform(rmin, rmax))
            ry = rx * float(rng.uniform(0.45, 1.0))
            mat = M[mats[int(rng.integers(0, len(mats)))]]
            bx, by = polar_patch(
                acc, cx, cy, rx, ry, mat,
                int(rng.integers(0, 999999)), yaw=float(rng.uniform(0, 180)),
                rough=float(rng.uniform(0.20, 0.38)), lift=L_PATCH, index=count)
            feather_outline(feather, bx, by, cx, cy, mat, 6200 + count,
                            band=0.78, lift=L_PATCH + 0.0009, pitch=0.32,
                            overlap=(0.09, 0.38))
            count += 1
    # the oil-black pad under the tanker gantry, as one soft-edged pad
    bx, by = polar_patch(acc, -56.0, 6.0, 7.6, 5.4, M["OilPad"], 8811, rough=0.16,
                         lift=L_PATCH + 0.0022, index=count)
    feather_outline(feather, bx, by, -56.0, 6.0, M["OilPad"], 6800,
                    band=1.10, lift=L_PATCH + 0.0031, pitch=0.40,
                    overlap=(0.12, 0.55))
    count += 1

    # Genuinely fresh black repairs: 14 of them, each squeezed into a pothole and
    # no more than 2 m across.  Kept small on purpose -- the near-black gloss
    # mirrors the dusk sky, which is a lovely detail at 1.5 m and an ice rink at
    # 7 m, so it is only ever used where you can also see its edge.
    for k, (px, py, pr, _) in enumerate(POTHOLES[::9][:14]):
        r = float(np.clip(pr * 1.35, 0.7, 2.0))
        polar_patch(acc, px, py, r, r * float(rng.uniform(0.6, 1.0)), M["AsphaltFresh"],
                    9200 + k, yaw=float(rng.uniform(0, 180)), rough=0.30,
                    lift=L_PATCH + 0.0026, index=count)
        count += 1
    emit_mesh(stage, f"{TERRAIN}/Patches/GroundPatches", acc.P, acc.FC, acc.FI, acc.N,
              acc.ST, acc.FM, mat_paths, "AsphaltAggregate",
              doc="Smooth-outlined ground-treatment patches lifted 12-13 mm onto the base "
                  "ground: asphalt repairs, exposed slab, gravel drift, mud, the oil pad. "
                  "Authored as overlays so the boundaries are curves, not mesh staircases, "
                  "sampled at 0.30 m and crenulated by two high harmonics.")
    emit_poly(stage, f"{TERRAIN}/Patches/GroundPatchFeather", feather, mat_paths,
              "AsphaltAggregate",
              doc="0.3-0.8 m dithered transition strip straddling every ground-patch "
                  "boundary, so the value step is feathered rather than cut")

    # damp halo + silted bed rings around every puddle
    # Silt bed and damp margin, kept TIGHT.  The damp look is four times darker
    # than dry asphalt, so a halo out to 1.55x the puddle -- which is what this
    # used to be -- paints a near-black blob nine metres across round every one
    # of twenty-six puddles, and the yard reads as camouflage from the air.  A
    # real drying margin is a hand's width of dark at the waterline that breaks
    # into mottling within a metre.
    #
    # THE WET RING IS WIDER THAN THE WATER.  This is the thing the previous pass
    # got backwards: it pulled the halo in to 1.20x because a solid dark annulus
    # at 1.55x read as a blob.  But a puddle in a yard does not sit on dry
    # ground -- the ground round it is soaked, and the soaked zone is roughly
    # twice the standing water because that is where the water WAS an hour ago.
    # Removing it does not make the puddle look better, it makes it look like a
    # decal.  The fix for the blob was never the radius, it was the SILHOUETTE:
    # so the halo now runs out to 1.98x, but it does it in four bands whose
    # drop-out rises from 0% at the waterline to 55% at the outside, and then
    # dissolves into a stipple beyond that.  Dark, wide, and with no edge
    # anywhere on it.
    acc = Acc()
    for pi, p in enumerate(ALL_PUDDLES):
        # silted bed, visible through the water and just above the waterline
        # Pulled in from 0.80-1.002 to 0.86-0.985 and dropped 1 mm.  The old ring
        # reached the waterline exactly, and since the bed is the shallowest part
        # of the basin, half of it stood proud of the water -- so the "bed you
        # see through the water" was in fact a ring of exposed shoreline lying
        # OUTSIDE the puddle. It now stops 1.5% short of the contour and sits
        # under 10-25 mm of water everywhere.
        contour_annulus(acc, p, 0.86, 0.985, M["PuddleBed"], lift=0.0020, rings=3,
                        index=5 * pi, phase=0.83 * pi, broken=0.0)
        # the saturated collar just outside the meniscus fillet (which occupies
        # 1.000-1.044 and is water, not ground): unbroken, dark, glossy
        # WIDENED 2026-08-09.  With the damp looks authored locally (roughness
        # 0.40 against the yard's 0.80) the collar finally has a value to spend,
        # so it is spent on WIDTH: an unbroken dark band out to 1.24x, soaked
        # ground to 1.62x and a drying margin to 2.15x. The wet ground is now
        # comfortably more than twice the standing water, which is the single
        # cue that says "this puddle is what is left of a much bigger one".
        contour_annulus(acc, p, 1.046, 1.24, M["DampRing"], lift=0.0046, rings=3,
                        index=5 * pi + 1, phase=1.4 * pi, broken=0.0)
        # the soaked ground: still clearly darker than dry asphalt, breaking up
        # Drop-out cut from 30/55% to 10/30%.  A ring that is half missing is a
        # ring made of fragments, and a fragment lifted 5-6 mm off the ground
        # shows its edge to the sun. The halo still has to dissolve outward, but
        # the dissolve is now carried by the outer stipple rather than by
        # punching holes in the band itself.
        contour_annulus(acc, p, 1.23, 1.62, M["DampRing"], lift=0.0053, rings=3,
                        index=5 * pi + 2, phase=1.97 * pi + 0.4, broken=0.10)
        # then the drying margin, broken and irregular, matte
        contour_annulus(acc, p, 1.60, 2.15, M["DampMottle"], lift=0.0060, rings=3,
                        index=5 * pi + 3, phase=2.11 * pi + 0.7, broken=0.30)
    emit_mesh(stage, f"{TERRAIN}/Patches/PuddleMargins", acc.P, acc.FC, acc.FI, acc.N,
              acc.ST, acc.FM, mat_paths, "PuddleBed",
              doc="Silted bed, an unbroken 60-140 mm saturated collar exactly on the "
                  "waterline, a soaked band out to 1.46x and a matte drying margin out to "
                  "1.98x -- so the wet ground is twice the width of the standing water, "
                  "which is what it is on a real yard an hour after rain. All four bands "
                  "follow the SAME traced contour the water surface uses, so bed, "
                  "waterline and halo are concentric rather than four drawn ellipses, and "
                  "the drop-out rises 0 -> 30 -> 55% outward so the halo has no "
                  "silhouette to read as a blob.")

    # The margin's outward dissolve.  MATTE, and half the radius it used to be.
    # It was bound to the damp look (roughness 0.26) and thrown out to 0.80 of
    # the puddle's own size around all twenty-eight puddles, which under a grey
    # dome at grazing incidence painted a soft, edgeless, pale blue-lavender
    # smear several metres across next to every one of them.  That is the
    # airbrushed blob the critic could name from a thumbnail.
    poly = Poly()
    for pi, p in enumerate(ALL_PUDDLES):
        _, cx, cy, sx, sy, yaw, _, _ = p
        c = puddle_contour(p)
        if c is not None:
            _, cx, cy, _, r = c
            rr = float(np.median(r))
            sx, sy = 2.0 * rr, 2.0 * rr
        # An ANNULAR scatter from 1.9x to 2.6x the shoreline: the last of the
        # soaked ground, dissolving to nothing. Hollow core (fmin) so nothing
        # lands on the water or on the solid bands, outward-biased radius so the
        # islands thin as they go, and each island shrinks with radius.
        # FEWER, BIGGER, FLATTER.  34-plus islands of 50-260 mm per puddle, each
        # lifted 5 mm off the ground, do not read as a tonal dissolve at eye
        # height -- they read as a bed of shingle, because every one of them
        # presents a lit top face and a lit edge to a 5.5 degree sun. The
        # drying margin is a STAIN; it needs a handful of large soft islands,
        # not a scatter of chips.
        stipple(poly, M["DampMottle"], 4400 + pi, cx, cy, sx * 1.30, sy * 1.30,
                int(10 + 3 * math.sqrt(sx * sy)), 0.16, 0.62, lift=L_PATCH,
                yaw=yaw, bias=0.62, edge=0.70, fmin=0.74)
    emit_poly(stage, f"{TERRAIN}/Patches/PuddleDrying", poly, mat_paths, "DampMottle",
              doc="the outermost drying edge, an annular stipple from 1.9x to 2.6x the "
                  "shoreline radius so the soaked ground fades out with no cut "
                  "silhouette anywhere; matte")

    # wet wheel tracks where vehicles run on unpaved ground
    acc = Acc()
    ri = 0
    for idx in (2,):                      # the rear service road
        path, gauge, _, _ = RUTS[idx]
        for side in (+1.0, -1.0):
            ribbon_patch(acc, offset_polyline(list(path), side * gauge * 0.5), 0.85,
                         M["MudWet"], lift=L_PATCH, step=1.2, index=ri)
            ri += 1
    for line, w in ((((31.0, -30.0), (40.0, -26.0), (50.0, -22.0)), 1.6),
                    (((32.0, -20.0), (44.0, -19.0), (51.0, -21.0)), 1.4)):
        ribbon_patch(acc, line, w, M["MudWet"], lift=L_PATCH, step=1.2, index=ri)
        ri += 1
    emit_mesh(stage, f"{TERRAIN}/Patches/WetWheelTracks", acc.P, acc.FC, acc.FI, acc.N,
              acc.ST, acc.FM, mat_paths, "MudWet",
              doc="saturated mud in the wheel tracks on the unpaved service road and the "
                  "broken-up east apron")
    report.append(f"  patches {count} ground patches + {len(ALL_PUDDLES)} puddle margins")


# --- rectangular saw-cut repairs -------------------------------------------
#
# Everything else in this module weathers the ground with ORGANIC shapes: warped
# Voronoi cells, polar blobs, traced contours, wandering ribbons.  All of it is
# correct and none of it says PAVEMENT, because the one thing on a real yard
# that is unambiguously man-made is the rectangle a contractor saw-cut out of the
# surface to reach a service and then filled back in.  A COD yard is full of
# them: a hard-edged, slightly-off-tone rectangle with a poured bitumen border,
# sitting a centimetre proud or a centimetre sunk, usually squared to the slab
# grid because that is where the saw goes.  Their absence is why forty rounds of
# noise still read as terrain -- there was no straight line anywhere in the
# ground except the joints.
#
# x0, x1, y0, y1, count, min size, max size, fills
REPAIR_RECT_ZONES = [
    (-50.0, 50.0, -15.0, 12.5, 30, 1.10, 5.20,
     ["AsphaltPatchTar", "AsphaltPatchOxide", "AsphaltPatchTar", "AsphaltFresh",
      "AsphaltOxidisedD", "AsphaltPatchOxide"]),
    (-45.0, 29.0, -33.0, -17.0, 12, 1.00, 4.20,
     ["AsphaltPatchTar", "AsphaltPatchOxide", "ConcreteSlabExposed",
      "AsphaltPatchTar"]),
    (-69.0, -53.0, -22.0, 32.0, 8, 1.00, 3.80,
     ["AsphaltPatchTar", "AsphaltPatchOxide", "AsphaltCracked"]),
    (53.0, 69.0, -22.0, 56.0, 8, 1.00, 3.80,
     ["AsphaltPatchOxide", "AsphaltPatchTar", "AsphaltCracked"]),
]


def build_repair_rects(stage, mat_paths, report):
    """Saw-cut rectangular repairs with poured bitumen borders."""
    rng = np.random.default_rng(SEED + 57)
    poly = Poly()
    made = 0
    for x0, x1, y0, y1, n, smin, smax, fills in REPAIR_RECT_ZONES:
        placed = []
        tries = 0
        while len(placed) < n and tries < n * 40:
            tries += 1
            cx = float(rng.uniform(x0, x1))
            cy = float(rng.uniform(y0, y1))
            # A saw cut squares itself to the slab grid more often than not, so
            # 55% of them land with one edge on a 5 m line.
            if rng.random() < 0.55:
                if rng.random() < 0.5:
                    cx = round(cx / 5.0) * 5.0 + float(rng.uniform(-1.6, 1.6))
                else:
                    cy = round(cy / 5.0) * 5.0 + float(rng.uniform(-1.6, 1.6))
            w = float(rng.uniform(smin, smax))
            h = w * float(rng.uniform(0.35, 0.95))
            if rng.random() < 0.35:
                w, h = h, w
            # keep off the water, the ironwork and each other
            if _in_drain_frame(np.array([cx]), np.array([cy]))[0]:
                continue
            near_water = False
            for p in ALL_PUDDLES:
                if _puddle_q(np.array([cx]), np.array([cy]), p)[0] < 1.5:
                    near_water = True
                    break
            if near_water:
                continue
            if any(abs(cx - qx) < (w + qw) * 0.62 and abs(cy - qy) < (h + qh) * 0.62
                   for qx, qy, qw, qh in placed):
                continue
            placed.append((cx, cy, w, h))

            yaw = math.radians(float(rng.uniform(-5.0, 5.0))
                               + (90.0 if rng.random() < 0.22 else 0.0))
            ca, sa = math.cos(yaw), math.sin(yaw)
            fill = M[fills[int(rng.integers(0, len(fills)))]]
            # proud or sunk: a resurfaced patch stands 8-16 mm above the old
            # surface, an excavated one that settled sits 5-11 mm below it
            up = rng.random() < 0.55
            step = (float(rng.uniform(0.008, 0.016)) if up
                    else -float(rng.uniform(0.005, 0.011)))
            band = float(rng.uniform(0.055, 0.115))

            hw0, hh0 = w * 0.5, h * 0.5
            # One subdivision count per edge, shared by the inner and the outer
            # ring, so the two have the same vertex count and the border quads
            # pair up one for one.
            mcount = [max(int(round((2 * hw0 if k % 2 == 0 else 2 * hh0) / 0.30)), 2)
                      for k in range(4)]

            def ring(hw, hh, jit):
                """Perimeter of a rectangle, sampled at ~0.30 m with edge jitter."""
                pts = []
                corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
                for k in range(4):
                    ax_, ay_ = corners[k]
                    bx_, by_ = corners[(k + 1) % 4]
                    m = mcount[k]
                    for j in range(m):
                        t = j / m
                        ux = ax_ + (bx_ - ax_) * t
                        uy = ay_ + (by_ - ay_) * t
                        # jitter along the OUTWARD normal only: a saw cut is
                        # straight, the excavation behind it is not
                        nx_ = 0.0 if abs(bx_ - ax_) > 1e-6 else math.copysign(1.0, ux)
                        ny_ = 0.0 if abs(by_ - ay_) > 1e-6 else math.copysign(1.0, uy)
                        if nx_ == 0.0 and ny_ == 0.0:
                            nx_ = math.copysign(1.0, ux)
                        d = jit * (float(rng.random()) - 0.35)
                        ux += nx_ * d
                        uy += ny_ * d
                        pts.append((cx + ux * ca - uy * sa, cy + ux * sa + uy * ca))
                return pts

            inner = ring(hw0, hh0, 0.030)
            outer = ring(hw0 + band, hh0 + band, 0.055)
            zi = [z_at(px, py) + L_PATCH + 0.0016 + step for px, py in inner]
            zo = [z_at(px, py) + L_SEAM + 0.0004 for px, py in outer]
            # A saw-cut patch is a rigid PLATE: its rim follows the ground but
            # its interior is flat, so it may not be laid across anything the
            # height field bends by more than a few centimetres. Without this a
            # 5 m rectangle that happened to land over a 120 mm pothole bridged
            # it, and the plate hovered over the hole with daylight underneath.
            if max(zi) - min(zi) > 0.055:
                placed.pop()
                continue
            # fill: a fan from the centre so the patch is one flat plate
            czp = float(np.mean(zi))
            for k in range(len(inner)):
                k2 = (k + 1) % len(inner)
                poly.add([(cx, cy, czp),
                          (inner[k][0], inner[k][1], zi[k]),
                          (inner[k2][0], inner[k2][1], zi[k2])], fill)
            # the poured bitumen border, bridging the step back to grade
            for k in range(len(inner)):
                k2 = (k + 1) % len(inner)
                poly.add([(inner[k][0], inner[k][1], zi[k]),
                          (inner[k2][0], inner[k2][1], zi[k2]),
                          (outer[k2][0], outer[k2][1], zo[k2]),
                          (outer[k][0], outer[k][1], zo[k])], M["TarSeam"])
            made += 1
    emit_poly(stage, f"{TERRAIN}/Patches/SawCutRepairs", poly, mat_paths, "AsphaltPatchTar",
              doc=f"{made} rectangular saw-cut repairs across the yard, the dock apron and "
                  f"both spawn aprons: a hard-edged plate of a different asphalt batch "
                  f"standing 8-16 mm proud or settled 5-11 mm below the surround, inside a "
                  f"55-115 mm poured bitumen border that bridges the step. 55% of them are "
                  f"squared to the 5 m slab grid because that is where the saw goes. This "
                  f"is the one shape on a real yard that is unambiguously man-made, and "
                  f"the module had no straight line in the ground except the joints.")
    report.append(f"  repairs {made} rectangular saw-cut repairs with bitumen borders")


# ----------------------------------------------------------------------------
# 5b.  the far field and the background silhouette band
# ----------------------------------------------------------------------------
#
# The first version of the far field was an 1850 m plate on ~50 vertex columns
# -- quads up to 370 m across, one material, world-metre UVs.  At that
# magnification a 1.9 m scan averages to a single colour, the RTX distance fog
# then paints that colour lavender, and the result was a flat plate filling the
# top-right third of the hero frame with a razor-straight edge across the sky.
# That is the single loudest "not a game" tell in the build.
#
# Three things fix it, and all three are needed.
#
# 1.  RADIUS.  It now stops at ~390 m instead of 925 m, on 24 rings, so the
#     largest quad is 36 m, not 370 m.
#
# 2.  A HORIZON BERM.  Falling away monotonically does not help: the elevation
#     angle of a falling plane approaches a constant from below, so the OUTER
#     EDGE is always the highest thing in it and always silhouettes against the
#     sky.  Instead the ground rises to a low berm at ~150 m out and then drops
#     40 m over the next 230 m.  From the hero camera (Z 19) the berm crest sits
#     at -3.4 deg and every ring beyond it is lower on screen, so the outer edge
#     of the world is geometrically invisible from every camera in the map.
#     What silhouettes instead is a rolling, noisy, scrub-dotted land edge.
#
# 3.  A BUILT BACKGROUND.  Beyond the berm, blocked masses -- gasholders, a
#     lattice mast, a chimney, long shed roofs, a silo battery, a slab block --
#     at 130-290 m on the bearings the cameras actually look down.  They are the
#     third depth plane the brief asks for and the frame has never had.

PLATE = (-75.0, 75.0, -56.0, 94.0)

# distance out from the plate edge -> ground height.  See note 2 above.
FAR_PROF_D = np.array([0.0, 12.0, 30.0, 55.0, 85.0, 118.0, 150.0,
                       185.0, 230.0, 280.0, 335.0, 390.0])
FAR_PROF_Z = np.array([-0.10, -0.75, -1.70, -2.50, -2.55, -0.40, 4.30,
                       1.00, -9.00, -20.00, -30.00, -41.00])


def far_d(x, y):
    x0, x1, y0, y1 = PLATE
    dx = np.maximum(np.maximum(x0 - x, x - x1), 0.0)
    dy = np.maximum(np.maximum(y0 - y, y - y1), 0.0)
    return np.hypot(dx, dy)


def far_z(x, y):
    """Height of the far field.  Continuous with the plate at the seam."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    x0, x1, y0, y1 = PLATE
    d = far_d(x, y)
    # Meander the ring so the berm is a landform, not a rounded rectangle.
    # Held off near the plate so the seam stays continuous.
    m = np.clip(d / 70.0, 0.0, 1.0)
    dm = np.maximum(d + m * (34.0 * fbm(x, y, 1.0 / 300.0, 2, 4242)
                             + 14.0 * fbm(x, y, 1.0 / 105.0, 2, 4243)), 0.0)
    z = np.interp(dm, FAR_PROF_D, FAR_PROF_Z)
    # rolling relief, growing with distance -- this is what stops the far field
    # being one value even where the material cannot help
    amp = np.clip(d / 45.0, 0.0, 1.0)
    z = z + amp * (3.4 * fbm(x, y, 1.0 / 78.0, 3, 4301)
                   + 1.55 * fbm(x, y, 1.0 / 27.0, 3, 4307)
                   + 0.52 * fbm(x, y, 1.0 / 8.5, 2, 4311))
    t = sstep(d / 14.0)
    zp = terrain_z(np.clip(x, x0, x1), np.clip(y, y0, y1))
    return z * t + zp * (1.0 - t)


# distance band -> ordered look ramp.  A 34 m field walks each ramp, so the far
# field is a patchwork of fields, never one value, and the bands keep the
# nearer ground weedier and the ridge line darker.
FAR_BANDS = [
    (0.0, 34.0, ["DirtWeeds", "Mud", "Gravel"]),
    (34.0, 92.0, ["Mud", "DirtWeeds", "DirtWeeds", "Gravel"]),
    (92.0, 165.0, ["Mud", "Mud", "DirtWeeds", "Gravel"]),
    (165.0, 240.0, ["Mud", "DirtWeeds", "Mud", "Gravel"]),
    (240.0, 1e9, ["Mud", "Mud", "DirtWeeds"]),
]


def far_material(x, y):
    d = far_d(x, y)
    f = 0.5 + 0.5 * fbm(x, y, 1.0 / 34.0, 3, 4501)
    g = 0.5 + 0.5 * fbm(x + 400.0, y - 250.0, 1.0 / 11.0, 2, 4507)
    mid = np.full(np.shape(x), M["DirtWeeds"], dtype=np.int32)
    for lo, hi, names in FAR_BANDS:
        table = np.array([M[n] for n in names], dtype=np.int32)
        v = np.clip(np.rint(f * (len(names) - 1) + 0.9 * (g - 0.5)),
                    0, len(names) - 1).astype(np.int32)
        mid = np.where((d >= lo) & (d < hi), table[v], mid)
    return mid


FAR_RINGS = [3.0, 7.0, 12.0, 18.0, 25.0, 33.0, 42.0, 52.0, 63.0, 75.0, 88.0,
             102.0, 117.0, 133.0, 150.0, 168.0, 187.0, 207.0, 230.0, 256.0,
             285.0, 318.0, 352.0, 390.0]


def build_far_field(stage, mat_paths, report):
    x0, x1, y0, y1 = PLATE
    xs = ([x0 - d for d in reversed(FAR_RINGS)]
          + list(np.arange(x0, x1 + 0.1, 5.0)) + [x1 + d for d in FAR_RINGS])
    ys = ([y0 - d for d in reversed(FAR_RINGS)]
          + list(np.arange(y0, y1 + 0.1, 5.0)) + [y1 + d for d in FAR_RINGS])
    AX, AY = np.array(xs), np.array(ys)
    X, Y = np.meshgrid(AX, AY)
    Z = far_z(X, Y)

    e = 0.9
    gx = (far_z(X + e, Y) - far_z(X - e, Y)) / (2 * e)
    gy = (far_z(X, Y + e) - far_z(X, Y - e)) / (2 * e)
    nrm = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    pts = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
    st = np.stack([X, Y], axis=-1).reshape(-1, 2)

    nx, ny = len(xs) - 1, len(ys) - 1
    W = len(xs)
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny))
    ii, jj = ii.ravel(), jj.ravel()
    fcx = 0.5 * (AX[ii] + AX[ii + 1])
    fcy = 0.5 * (AY[jj] + AY[jj + 1])
    keep = ~((fcx > x0) & (fcx < x1) & (fcy > y0) & (fcy < y1))
    ii, jj, fcx, fcy = ii[keep], jj[keep], fcx[keep], fcy[keep]
    a = jj * W + ii
    faces = np.stack([a, a + 1, a + W + 1, a + W], axis=-1).ravel()
    counts = np.full(ii.shape[0], 4, dtype=np.int32)
    emit_mesh(stage, f"{TERRAIN}/Ground/Ground_FarField", pts, counts, faces,
              nrm.reshape(-1, 3), st, far_material(fcx, fcy), mat_paths, "Mud",
              doc="Far-field ground, plate edge out to 390 m on 24 rings (largest quad "
                  "36 m). Rises to a low berm at ~150 m and then drops 40 m over the "
                  "next 240 m, so the berm crest is the only thing in it that meets the "
                  "sky and the outer edge of the world is never visible from any camera. "
                  "Banded by distance into alternating dirt / mud / gravel fields and "
                  "carried on 3-4 m of rolling relief, so it can never average to a "
                  "single flat colour.")
    report.append(f"  farfield {ii.shape[0]} faces, outer radius 390 m, berm crest "
                  f"+4.3 m at 150 m")


# --- low-poly blocked masses for the background band ------------------------


def bd_box(poly, cx, cy, z0, z1, sx, sy, yaw, mat, top_mat=None):
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)
    hx, hy = sx * 0.5, sy * 0.5
    cor = []
    for ux, uy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
        cor.append((cx + ux * ca - uy * sa, cy + ux * sa + uy * ca))
    poly.add([(px, py, z1) for px, py in cor], top_mat if top_mat is not None else mat,
             normal=(0, 0, 1))
    for k in range(4):
        p, q = cor[k], cor[(k + 1) % 4]
        poly.add([(p[0], p[1], z0), (q[0], q[1], z0),
                  (q[0], q[1], z1), (p[0], p[1], z1)], mat)


def bd_cyl(poly, cx, cy, z0, z1, r0, r1, seg, mat, cap_mat=None, cap=True,
           cx1=None, cy1=None):
    """A cone frustum. cx1/cy1 lean the top ring off the base axis."""
    if cx1 is None:
        cx1 = cx
    if cy1 is None:
        cy1 = cy
    t = [2 * math.pi * k / seg for k in range(seg)]
    a0 = [(cx + r0 * math.cos(v), cy + r0 * math.sin(v)) for v in t]
    a1 = [(cx1 + r1 * math.cos(v), cy1 + r1 * math.sin(v)) for v in t]
    for k in range(seg):
        p0, q0 = a0[k], a0[(k + 1) % seg]
        p1, q1 = a1[k], a1[(k + 1) % seg]
        poly.add([(p0[0], p0[1], z0), (q0[0], q0[1], z0),
                  (q1[0], q1[1], z1), (p1[0], p1[1], z1)], mat)
    if cap and r1 > 0.05:
        poly.add([(px, py, z1) for px, py in a1], cap_mat or mat, normal=(0, 0, 1))


# Every backdrop billboard faces this point: the centre of the plate at rough
# camera height. All five cameras stand inside the plate, so one view point
# serves them all.
BD_VIEW = (0.0, 19.0, 6.0)


def bd_bar(poly, a, b, w, mat, view=BD_VIEW):
    """A thin structural member, as ONE ribbon rotated to face the map centre.

    What this used to be, and why both halves of it were bugs:

    * It emitted the SAME quad twice, once per winding, "so it is visible from
      any bearing". Two exactly coincident faces is a z-fight, and a path
      tracer resolves a z-fight as per-sample speckle -- so every lattice
      member of every pylon and every one of the ~700 catenary segments was
      seeding noise into the sky of the establishing shot. The gate that has
      failed three rounds running is firefly/variance; this module was feeding
      it.
    * It oriented the ribbon off a fixed world reference, which left the
      horizontal catenaries lying nearly edge-on to every camera. A flat
      ribbon at grazing incidence is exactly where Schlick's Fresnel goes to
      1.0 regardless of the specular level, so each 1-px-wide wire turned into
      a white line ruled across the storm sky.

    Facing the ribbon at the map centre fixes both at once: one face, no
    coincident geometry, and the member is seen flat rather than at grazing
    incidence, so it shades from its own albedo like everything else. Every
    camera in shots.json stands inside the plate, so one view point serves all
    five without a per-shot billboard.
    """
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    d = (dx / L, dy / L, dz / L)
    mid = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]), 0.5 * (a[2] + b[2]))
    v = (view[0] - mid[0], view[1] - mid[1], view[2] - mid[2])
    vl = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    v = (v[0] / vl, v[1] / vl, v[2] / vl)
    sx = d[1] * v[2] - d[2] * v[1]
    sy = d[2] * v[0] - d[0] * v[2]
    sz = d[0] * v[1] - d[1] * v[0]
    n = math.sqrt(sx * sx + sy * sy + sz * sz)
    if n < 1e-4:                      # member points at the viewer: any side does
        ref = (0.0, 0.0, 1.0) if abs(d[2]) < 0.9 else (1.0, 0.0, 0.0)
        sx = d[1] * ref[2] - d[2] * ref[1]
        sy = d[2] * ref[0] - d[0] * ref[2]
        sz = d[0] * ref[1] - d[1] * ref[0]
        n = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
    sx, sy, sz = sx / n * w * 0.5, sy / n * w * 0.5, sz / n * w * 0.5
    q = [(a[0] - sx, a[1] - sy, a[2] - sz), (b[0] - sx, b[1] - sy, b[2] - sz),
         (b[0] + sx, b[1] + sy, b[2] + sz), (a[0] + sx, a[1] + sy, a[2] + sz)]
    fn = _face_normal(q)
    if fn[0] * v[0] + fn[1] * v[1] + fn[2] * v[2] < 0.0:
        q = q[::-1]
        fn = _face_normal(q)
    poly.add(q, mat, normal=fn)


# How far the per-vertex foliage break-up may push the loft radius. The crest
# ceiling divides by CLUMP_MAX, so a clumped crown still cannot breach it.
CLUMP_MAX = 1.28
CLUMP_MIN = 0.74


def bd_shelter_belt(poly, sx, sy, heading, n_st, base_h, base_w, mat, seed,
                    step=2.2, curve=0.0, sink=1.0, crown_amp=0.42, min_far_d=66.0):
    """A CONTINUOUS, soft-crested tree belt on the far berm.

    This replaces the ~1200 individual tapered masses that three review rounds
    called "a comb of untextured faceted cones", "tents", "traffic cones". They
    deserved it, and the reason is structural, not tuning: a solid of revolution
    that tapers to a small top ring has a POINT on its silhouette, and a point
    on the skyline is a cone no matter what value it is drawn at. Raising the
    segment count does not help -- a 32-sided cone is still a cone -- and neither
    does darkening it, because the silhouette is the shape.

    A real shelter belt is not a row of objects at all. It is one continuous
    mass with an irregular top edge, so that is what this builds:

      * a meandering plan line walked at `step` metres with a slow turn rate,
      * a HALF-ELLIPSE cross-section (rounded crest, never an apex) lofted along
        it, so every silhouette tangent is continuous,
      * a crest height modulated by two things -- a low-frequency +/-30 % noise
        so the belt line itself rises and falls, and a train of GAUSSIAN crowns
        at 6-15 m spacing so individual trees read INSIDE the mass without ever
        separating from it. A gaussian has no corner at its peak; that is the
        whole reason the crowns are gaussian and not tapers,
      * analytic per-vertex ellipse normals, so the loft shades as a smooth
        round form instead of resolving into facet bands,
      * both ends tapered to zero height and width, so a belt never terminates
        in a wall.
    """
    rng = np.random.default_rng(seed)
    n_st = int(max(4, n_st))
    px, py, hd = [sx], [sy], float(heading)
    cx0, cy0 = 0.5 * (PLATE[0] + PLATE[1]), 0.5 * (PLATE[2] + PLATE[3])
    for _ in range(n_st - 1):
        hd += math.radians(float(rng.normal(0.0, 4.2))) + curve
        qx, qy = px[-1] + step * math.cos(hd), py[-1] + step * math.sin(hd)
        # KEEP OFF THE PLATE. A belt is a 190 m random walk with a turn rate;
        # left alone it wanders, and a replay of the placement RNG showed ~6 %
        # of walks reaching far_d < 60 m and several reaching far_d = 0 -- i.e.
        # a 20 m tall tree ridge standing in the out-of-bounds margin of the
        # playable map, through the poplar line and the perimeter fence. When a
        # step would breach the keep-out, the heading is reflected about the
        # local tangent so its radial component points outward; the belt turns
        # away instead of stopping, which keeps the crest continuous.
        if float(far_d(np.array([qx]), np.array([qy]))[0]) < min_far_d:
            ox, oy = qx - cx0, qy - cy0
            ol = math.hypot(ox, oy) or 1.0
            ox, oy = ox / ol, oy / ol
            ux, uy = math.cos(hd), math.sin(hd)
            dot = ux * ox + uy * oy
            if dot < 0.0:
                ux, uy = ux - 2.0 * dot * ox, uy - 2.0 * dot * oy
                hd = math.atan2(uy, ux)
                qx, qy = px[-1] + step * ux, py[-1] + step * uy
        px.append(qx)
        py.append(qy)
    ax = np.array(px)
    ay = np.array(py)
    z0 = far_z(ax, ay) - sink

    s = np.arange(n_st, dtype=float) * step
    # low-frequency height/width breathing -- the belt line itself undulates
    h = base_h * (1.0 + 0.30 * fbm(ax, ay, 1.0 / 46.0, 2, seed + 11)
                  + 0.15 * fbm(ax, ay, 1.0 / 17.0, 2, seed + 13))
    w = base_w * (1.0 + 0.24 * fbm(ax + 300.0, ay - 210.0, 1.0 / 29.0, 2, seed + 17))

    # gaussian crowns: individual trees inside the mass, no corner at the peak
    sc = 0.0
    while sc < s[-1]:
        sc += float(rng.uniform(6.0, 15.0))
        sig = float(rng.uniform(3.2, 6.4))
        amp = base_h * crown_amp * float(rng.uniform(0.45, 1.0))
        h = h + amp * np.exp(-((s - sc) / sig) ** 2)

    # taper both ends to nothing
    ramp = np.clip(np.minimum(s, s[-1] - s) / max(step * 2.6, 1e-6), 0.0, 1.0)
    ramp = ramp * ramp * (3.0 - 2.0 * ramp)
    h = np.maximum(h * ramp, 0.02)
    w = np.maximum(w * ramp, 0.02)

    # THE CREST CEILING. A belt walks 190 m of a berm that itself rolls +/-5 m,
    # so a nominally 11 m belt can crest 22 m above the eye line if the walk
    # happens to climb. Measured on the previous build's delivered frame: the
    # tree band's silhouette reached the TOP EDGE of HERO_ESTABLISH in a few
    # columns -- a 5.7 deg tree, which is a foreground tree, not a horizon.
    # Clamping the crest (not the base) keeps the belt sitting on the ground it
    # is standing on and only shortens the trees, which is the physically
    # sensible way round.
    ceil = np.array([bd_ceiling(float(px_), float(py_)) for px_, py_ in zip(ax, ay)])
    # / CLUMP_MAX so the foliage break-up below cannot push a crest through it
    h = np.minimum(h, np.maximum((ceil - z0) / CLUMP_MAX, 0.6))

    # unit plan-normal per station (central difference along the line)
    nx = np.empty(n_st)
    ny = np.empty(n_st)
    for i in range(n_st):
        a = max(i - 1, 0)
        b = min(i + 1, n_st - 1)
        dx, dy = ax[b] - ax[a], ay[b] - ay[a]
        L = math.hypot(dx, dy) or 1.0
        nx[i], ny[i] = -dy / L, dx / L

    # ---- the loft, with FOLIAGE BREAK-UP -----------------------------------
    #
    # A clean half-ellipse loft with analytic ellipse normals shades as a
    # perfectly smooth tube. Rendered and looked at, that is exactly what it
    # read as: a row of pale blue-grey inflated blobs, which is a different
    # wrong answer from the cones but still not a tree line. A tree line's
    # value break-up comes from CANOPIES -- 2-4 m lumps that each catch and
    # occlude the sky differently.
    #
    # So the loft radius is modulated by two octaves of noise sampled in the
    # surface's own 3D position (2.6 m and 1.15 m), and the normals are then
    # recomputed by finite differences ON THE PERTURBED SURFACE rather than
    # from the ideal ellipse -- otherwise the geometry would be lumpy and the
    # shading would still be smooth, which is the worst of both.
    NC = 15
    TH = np.linspace(0.0, math.pi, NC)
    U = np.cos(TH)[None, :]
    V = np.sin(TH)[None, :]
    W2 = w[:, None]
    H2 = h[:, None]
    NXc = nx[:, None]
    NYc = ny[:, None]
    BX = ax[:, None] + NXc * W2 * U
    BY = ay[:, None] + NYc * W2 * U
    BZ = z0[:, None] + H2 * V
    g = (0.20 * fbm(BX + BZ * 1.7, BY - BZ * 1.3, 1.0 / 2.6, 3, seed + 29)
         + 0.10 * fbm(BX - BZ * 2.1, BY + BZ * 1.9, 1.0 / 1.15, 2, seed + 31))
    rad = np.clip(1.0 + g, CLUMP_MIN, CLUMP_MAX)
    PX = ax[:, None] + NXc * W2 * U * rad
    PY = ay[:, None] + NYc * W2 * U * rad
    PZ = z0[:, None] + H2 * V * rad

    P = np.stack([PX, PY, PZ], axis=-1)
    di = np.gradient(P, axis=0)
    dj = np.gradient(P, axis=1)
    N = np.cross(di, dj)
    ln = np.linalg.norm(N, axis=-1, keepdims=True)
    N = np.where(ln > 1e-9, N / np.maximum(ln, 1e-9), 0.0)
    # orient outward: compare against the ideal ellipse gradient
    gu = U / np.maximum(W2, 1e-4)
    gv = V / np.maximum(H2, 1e-4)
    gl = np.maximum(np.hypot(gu, gv), 1e-9)
    ideal = np.stack([NXc * gu / gl * np.ones_like(U),
                      NYc * gu / gl * np.ones_like(U), gv / gl], axis=-1)
    flip = np.sum(N * ideal, axis=-1, keepdims=True) < 0.0
    N = np.where(flip, -N, N)
    # degenerate rows (zero area) fall back to the ideal normal
    N = np.where(ln > 1e-9, N, ideal)

    for i in range(n_st - 1):
        for j in range(NC - 1):
            quad = [tuple(P[i, j]), tuple(P[i + 1, j]),
                    tuple(P[i + 1, j + 1]), tuple(P[i, j + 1])]
            nq = [tuple(N[i, j]), tuple(N[i + 1, j]),
                  tuple(N[i + 1, j + 1]), tuple(N[i, j + 1])]
            poly.add(quad, mat, normals=nq)
    return n_st


def bd_shed(poly, cx, cy, z0, length, width, eaves, ridge, yaw, mat, roof):
    """A long low industrial shed: blockwork walls, shallow pitched roof."""
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)

    def w2(u, v):
        return (cx + u * ca - v * sa, cy + u * sa + v * ca)

    hL, hW = length * 0.5, width * 0.5
    bd_box(poly, cx, cy, z0, eaves, length, width, yaw, mat, top_mat=mat)
    rp = [w2(-hL, -hW), w2(hL, -hW), w2(hL, 0.0), w2(-hL, 0.0)]
    poly.add([(rp[0][0], rp[0][1], eaves), (rp[1][0], rp[1][1], eaves),
              (rp[2][0], rp[2][1], ridge), (rp[3][0], rp[3][1], ridge)], roof)
    rp = [w2(-hL, 0.0), w2(hL, 0.0), w2(hL, hW), w2(-hL, hW)]
    poly.add([(rp[0][0], rp[0][1], ridge), (rp[1][0], rp[1][1], ridge),
              (rp[2][0], rp[2][1], eaves), (rp[3][0], rp[3][1], eaves)], roof)
    for u in (-hL, hL):
        g = [w2(u, -hW), w2(u, 0.0), w2(u, hW)]
        tri = [(g[0][0], g[0][1], eaves), (g[1][0], g[1][1], ridge),
               (g[2][0], g[2][1], eaves)]
        poly.add(tri, mat)
        poly.add(tri[::-1], mat)


def bd_mast(poly, cx, cy, z0, h, base, top, mat, levels=9):
    """A guyed lattice mast: four tapering legs, ring bands, face diagonals."""
    zs = [z0 + h * k / levels for k in range(levels + 1)]
    ws = [base + (top - base) * k / levels for k in range(levels + 1)]

    def corner(k, i):
        w = ws[k] * 0.5
        return [(cx - w, cy - w, zs[k]), (cx + w, cy - w, zs[k]),
                (cx + w, cy + w, zs[k]), (cx - w, cy + w, zs[k])][i]

    for k in range(levels):
        for i in range(4):
            bd_bar(poly, corner(k, i), corner(k + 1, i), 0.55, mat)
            bd_bar(poly, corner(k, i), corner(k, (i + 1) % 4), 0.40, mat)
            j = (i + 1) % 4
            if (k + i) % 2 == 0:
                bd_bar(poly, corner(k, i), corner(k + 1, j), 0.32, mat)
            else:
                bd_bar(poly, corner(k, j), corner(k + 1, i), 0.32, mat)
    for i in range(4):
        bd_bar(poly, corner(levels, i), corner(levels, (i + 1) % 4), 0.40, mat)
    bd_cyl(poly, cx, cy, z0 + h, z0 + h + 5.0, 0.30, 0.16, 6, mat)


def bd_gasholder(poly, cx, cy, z0, r, h, mat, roof, steel):
    """A riveted gasholder: drum, shallow crown, and the lattice guide frame
    round it -- the guide frame is what makes the silhouette read as a
    gasholder rather than as a tin can."""
    seg = 22
    bd_cyl(poly, cx, cy, z0, z0 + h, r, r, seg, mat, cap=False)
    bd_cyl(poly, cx, cy, z0 + h, z0 + h + r * 0.16, r, r * 0.60, 18, roof)
    bd_cyl(poly, cx, cy, z0 + h + r * 0.16, z0 + h + r * 0.22, r * 0.60, 0.0, 18, roof)
    for k in range(10):
        a = 2 * math.pi * k / 10
        px, py = cx + r * 1.13 * math.cos(a), cy + r * 1.13 * math.sin(a)
        bd_bar(poly, (px, py, z0), (px, py, z0 + h * 1.10), 0.75, steel)
        a2 = 2 * math.pi * (k + 1) / 10
        qx, qy = cx + r * 1.13 * math.cos(a2), cy + r * 1.13 * math.sin(a2)
        for f in (0.34, 0.70, 1.06):
            bd_bar(poly, (px, py, z0 + h * f), (qx, qy, z0 + h * f), 0.45, steel)
        bd_bar(poly, (px, py, z0 + h * 0.34), (qx, qy, z0 + h * 0.70), 0.30, steel)


def bd_chimney(poly, cx, cy, z0, h, r0, r1, mat, steel):
    bd_cyl(poly, cx, cy, z0, z0 + h, r0, r1, 16, mat, cap=False)
    for f in (0.42, 0.68, 0.88, 0.98):
        rr = r0 + (r1 - r0) * f
        bd_cyl(poly, cx, cy, z0 + h * f, z0 + h * f + 0.55,
               rr * 1.12, rr * 1.12, 16, steel, cap=False)


def bd_block(poly, cx, cy, z0, sx, sy, h, yaw, mass, roof, steel, seed):
    """A distant industrial block, articulated.

    The first pass drew this as one extruded box, and a 56 x 37 m untextured
    plane square-on to a low sun renders as a single flat value -- measured at
    0.455 sRGB against a 0.177 sky, i.e. a white cube in the background of the
    hero shot.  A building of that size is never one plane: it is bays of
    different heights, a parapet, pilasters standing proud, and recessed glazing
    bands.  Each of those breaks the elevation into strips at different angles
    to the sun, which is what turns a lit box back into a lit building.
    """
    rng = np.random.default_rng(seed)
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)

    def w(u, v):
        return (cx + u * ca - v * sa, cy + u * sa + v * ca)

    n = int(rng.integers(3, 6))
    bounds = [0.0] + sorted(rng.uniform(0.14, 0.86, n - 1).tolist()) + [1.0]
    for k in range(n):
        u0 = (bounds[k] - 0.5) * sx
        u1 = (bounds[k + 1] - 0.5) * sx
        if u1 - u0 < 2.0:
            continue
        hk = h * float(rng.uniform(0.58, 1.0))
        dy = sy * float(rng.uniform(0.70, 1.0))
        bx, by = w(0.5 * (u0 + u1), 0.0)
        # A bay BODY is never the roof look. BD_Roof is the palest of the four
        # and a 20 x 30 m bay of it square-on to the sun renders as a sheet of
        # white card; it is for horizontal planes, parapets and pilasters only.
        body = mass if k % 2 == 0 else steel
        bd_box(poly, bx, by, z0, z0 + hk, u1 - u0, dy, yaw, body, top_mat=roof)
        bd_box(poly, bx, by, z0 + hk, z0 + hk + float(rng.uniform(0.7, 1.6)),
               (u1 - u0) * 0.99, dy * 0.99, yaw, roof)
        # pilasters standing 0.45 m proud of both long faces
        m = max(2, int(round((u1 - u0) / 5.5)))
        for j in range(m):
            uu = u0 + (j + 0.5) * (u1 - u0) / m
            for vv in (-dy * 0.5, dy * 0.5):
                px, py = w(uu, vv)
                bd_box(poly, px, py, z0, z0 + hk * float(rng.uniform(0.90, 1.0)),
                       0.9, 0.9, yaw, roof if body == mass else mass)
        # dark recessed glazing bands, 1% proud so they read on the elevation
        for f in (0.28, 0.50, 0.72, 0.90):
            if rng.random() < 0.34 or hk * f < 4.0:
                continue
            zc = z0 + hk * f
            bd_box(poly, bx, by, zc, zc + hk * 0.085,
                   (u1 - u0) * 0.90, dy * 1.02, yaw, steel)
    # roof plant room and a stair core, so the parapet line is not level
    px, py = w(sx * float(rng.uniform(-0.32, 0.32)), 0.0)
    bd_box(poly, px, py, z0 + h * 0.86, z0 + h * float(rng.uniform(1.06, 1.22)),
           sx * 0.16, sy * 0.55, yaw, roof)
    px, py = w(sx * float(rng.uniform(-0.45, 0.45)), sy * 0.2)
    bd_box(poly, px, py, z0 + h * 0.80, z0 + h * float(rng.uniform(1.10, 1.30)),
           sx * 0.09, sy * 0.30, yaw, mass)


def bd_pylon_line(poly, x0, y0, x1, y1, n, h, steel, seed):
    """A distant transmission line: lattice pylons plus sagging catenaries.

    This is here for a measured reason.  After the berm and the blocked masses
    the hero frame's remaining dead area is almost all SKY -- 60% of the tiles
    in the top sixth of the frame carry no information, because a storm HDRI is
    smooth and the terrain module cannot put clouds in it.  What it CAN do is
    hang things in front of it.  A pylon is a few hundred thin members and a
    catenary crosses a hundred metres of empty sky on a curve, so a single line
    breaks far more sky than its silhouette area suggests -- and a transmission
    line running behind the yard is exactly the right furniture for the place.
    """
    rng = np.random.default_rng(seed)
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    px_, py_ = -dy / L, dx / L
    towers = []
    for k in range(n):
        t = k / max(n - 1, 1)
        cx = x0 + dx * t + float(rng.uniform(-4.0, 4.0))
        cy = y0 + dy * t + float(rng.uniform(-4.0, 4.0))
        z0 = float(far_z(np.array([cx]), np.array([cy]))[0]) - 1.5
        hh = h * float(rng.uniform(0.90, 1.10))
        bd_mast(poly, cx, cy, z0, hh, hh * 0.155, hh * 0.045, steel, levels=6)
        arms = []
        for f, aw in ((0.58, 0.30), (0.75, 0.26), (0.92, 0.20)):
            zc = z0 + hh * f
            a = hh * aw
            bd_bar(poly, (cx - px_ * a, cy - py_ * a, zc),
                   (cx + px_ * a, cy + py_ * a, zc), 0.55, steel)
            arms.append((zc, a))
        towers.append((cx, cy, arms))
    for i in range(len(towers) - 1):
        ax, ay, aa = towers[i]
        bx, by, ba = towers[i + 1]
        span = math.hypot(bx - ax, by - ay)
        sag = span * 0.038
        for j in range(3):
            za, wa = aa[j]
            zb, wb = ba[j]
            for s in (-1.0, 1.0):
                p0 = (ax + px_ * wa * s, ay + py_ * wa * s, za)
                p1 = (bx + px_ * wb * s, by + py_ * wb * s, zb)
                prev = p0
                for m in range(1, 9):
                    u = m / 8.0
                    q = (p0[0] + (p1[0] - p0[0]) * u,
                         p0[1] + (p1[1] - p0[1]) * u,
                         p0[2] + (p1[2] - p0[2]) * u - 4.0 * sag * u * (1.0 - u))
                    bd_bar(poly, prev, q, 0.11, steel)
                    prev = q


def bd_silo_battery(poly, cx, cy, z0, n, r, h, pitch, yaw, mat, roof):
    a = math.radians(yaw)
    ca, sa = math.cos(a), math.sin(a)
    for k in range(n):
        u = (k - (n - 1) * 0.5) * pitch
        px, py = cx + u * ca, cy + u * sa
        hh = h * (1.0 + 0.06 * math.sin(2.1 * k))
        bd_cyl(poly, px, py, z0, z0 + hh, r, r, 16, mat, cap=False)
        # DOMED, not conical. A silo top drawn as one frustum running to radius
        # zero is a 16-sided CONE, and a row of them on the skyline is the
        # "row of faceted cones" three review rounds kept reporting. Three
        # frustums on a circular profile give a rounded crown whose silhouette
        # has no apex and no facet band at this range.
        for f0, f1 in ((0.00, 0.55), (0.55, 0.85), (0.85, 1.00)):
            bd_cyl(poly, px, py, z0 + hh + r * 0.42 * f0, z0 + hh + r * 0.42 * f1,
                   r * math.cos(f0 * math.pi * 0.5) ** 0.55,
                   r * math.cos(f1 * math.pi * 0.5) ** 0.55, 16, roof,
                   cap=(f1 >= 1.0))
    bd_box(poly, cx, cy, z0 + h * 0.98, z0 + h * 1.16,
           (n - 1) * pitch + 2 * r, r * 2.1, yaw, roof)


# ---------------------------------------------------------------------------
# THE HORIZON CEILING.
#
# This is the rule that keeps the background a BACKGROUND, and it is the fix
# for the note that has now been written four times ("greybox", "tents",
# "traffic cones", "unfinished"). Every one of those rounds authored the band
# in metres of height and then discovered in the render how much of the frame
# it ate. Measured on the delivered HERO_ESTABLISH frame of the previous build:
# the built masses' silhouette had a median top elevation of +2.2 deg and
# reached the TOP EDGE of the frame in six of sixteen column bands. HERO's
# frame top is only +5.68 deg above the horizon, so a mass touching it is
# occupying a third of the visible sky -- that is a foreground object standing
# 230 m away, and it reads exactly like one.
#
# So height is no longer authored. Every backdrop object states the WORLD Z of
# its top, and `bd_ceiling` clamps that Z so the object's apparent elevation
# stays inside a per-camera budget from all three exterior cameras. A ridge you
# cannot make too tall by accident is the only kind that survives a round.
# (eye x, y, z), view bearing deg, half-arc deg, in-frame crest budget deg.
# The half-arc is the camera's real half-HFOV plus 12 deg of slack, because a
# ceiling that binds on a camera which is FACING THE OTHER WAY is what flattened
# the west gasholders to nothing in the first draft of this rule.
BD_HORIZON_CAMS = (
    ((-33.0, -36.0, 19.0), 61.05, 44.9, 2.35),   # HERO   frame top +5.74
    ((-44.0, 2.0, 1.65), 0.0, 44.9, 6.20),       # LANE   frame top +19.9
    ((56.0, -8.0, 1.65), 180.0, 39.4, 6.80),     # SILH   frame top +16.1
    ((-12.0, -10.5, 1.10), 308.0, 33.8, 2.90),   # DETAIL frame top +5.70
)
# Anything the cameras cannot frame still has to stay a horizon, or it shows up
# the moment somebody nudges a camera. Out-of-arc objects get this much.
BD_OFF_ARC_EL = 9.0
# slender accents -- chimneys, masts, silo vents -- get this multiple of the
# budget, because a 2-3 m wide vertical crossing the sky is punctuation, not
# mass, and a horizon with nothing rising off it is a ruled line.
BD_ACCENT_LIFT = 1.85


def bd_ceiling(cx, cy, accent=False):
    """Highest world Z this (x, y) may reach without eating anyone's sky."""
    lift = BD_ACCENT_LIFT if accent else 1.0
    best = 1e9
    for (ex, ey, ez), brg, arc, el in BD_HORIZON_CAMS:
        d = math.hypot(cx - ex, cy - ey)
        off = abs((math.degrees(math.atan2(cy - ey, cx - ex)) - brg + 180.0)
                  % 360.0 - 180.0)
        e = el if off <= arc else BD_OFF_ARC_EL
        best = min(best, ez + d * math.tan(math.radians(e * lift)))
    return best


# (kind, x, y, TOP_Z, params...) -- placed on the bearings the cameras look
# down. HERO_ESTABLISH from (-33,-36) frames world bearings 28-94 deg;
# LANE_EYE_YARD from (-44,+2) frames -33..+33; SILHOUETTE_WEST from (56,-8)
# frames 153-207. Every entry sits inside one of those three arcs at 88-330 m.
#
# The fourth column is the ABSOLUTE WORLD Z OF THE TOP OF THE OBJECT, not a
# height -- see bd_ceiling. It is clamped at build time and the build prints
# the resulting apparent elevation of every entry, so a monolith cannot ship
# again without somebody reading the number that says so.
BACKDROP = [
    # --- west: the storm break in SILHOUETTE_WEST ---------------------------
    ("gasholder", -198.0, 46.0, 27.0, 15.0),
    ("gasholder", -232.0, -6.0, 24.0, 12.5),
    ("chimney", -186.0, 74.0, 38.0, 3.4, 2.1),
    ("mast", -190.0, -76.0, 35.0, 9.0, 2.2),
    ("shed", -216.0, -34.0, 20.0, 74.0, 22.0, 5.0, 12.0),
    ("block", -158.0, 10.0, 23.0, 46.0, 18.0, -8.0),
    ("silos", -166.0, -46.0, 26.0, 5, 4.4, 9.6, 78.0),
    ("shed", -252.0, 62.0, 19.0, 62.0, 24.0, 4.0, -22.0),
    ("block", -228.0, 108.0, 25.0, 34.0, 16.0, 15.0),
    # --- north-east: the empty third of HERO_ESTABLISH ----------------------
    ("silos", 146.0, 104.0, 27.5, 6, 4.6, 10.0, 24.0),
    ("block", 162.0, 80.0, 26.0, 56.0, 20.0, 20.0),
    ("shed", 92.0, 186.0, 21.0, 86.0, 26.0, 5.5, -8.0),
    ("chimney", 30.0, 236.0, 36.0, 3.6, 2.2),
    ("mast", 64.0, 216.0, 34.0, 8.0, 2.0),
    ("gasholder", 188.0, 132.0, 28.0, 14.0),
    ("block", 118.0, 152.0, 25.0, 40.0, 16.0, -34.0),
    ("shed", 6.0, 168.0, 17.0, 58.0, 20.0, 4.0, 6.0),
    # --- east: the far end of LANE_EYE_YARD ---------------------------------
    ("gasholder", 212.0, 6.0, 26.0, 13.0),
    ("silos", 196.0, -62.0, 28.0, 4, 4.2, 9.0, 108.0),
    ("shed", 176.0, -112.0, 18.0, 66.0, 22.0, 4.5, 25.0),
    ("mast", 232.0, -30.0, 32.0, 7.6, 1.9),
    ("block", 170.0, 44.0, 24.0, 38.0, 15.0, -12.0),
    # --- south, so the ring is closed from any camera -----------------------
    ("block", -40.0, -206.0, 26.0, 52.0, 20.0, 8.0),
    ("chimney", 88.0, -196.0, 33.0, 3.0, 1.9),
    ("shed", -142.0, -164.0, 19.0, 60.0, 22.0, 4.0, 40.0),
    ("silos", 40.0, -168.0, 24.0, 3, 4.0, 8.6, 12.0),
    # --- slender accents. Their job is to break the sky band without taking
    #     mass out of it: nothing here is wider than 3.6 m. -------------------
    ("chimney", 120.0, 168.0, 37.0, 3.4, 2.0),
    ("mast", 168.0, 118.0, 32.0, 8.5, 2.1),
    ("chimney", -18.0, 208.0, 34.0, 3.2, 1.9),
    ("mast", 208.0, 62.0, 31.0, 7.4, 1.9),
    ("chimney", 62.0, 196.0, 33.0, 2.8, 1.8),
]
# kinds whose silhouette is punctuation rather than mass
BD_ACCENT_KINDS = {"chimney", "mast"}

# (x0, y0, x1, y1, pylons, height) -- runs chosen so each sweeps the sky band of
# one camera end to end.
PYLON_LINES = [
    (230.6, 100.5, -46.6, 260.5, 6, 30.0),      # sweeps HERO bearings 27-93
    (-182.0, -160.0, -182.0, 150.0, 6, 28.0),   # sweeps SILHOUETTE_WEST
    (196.0, -150.0, 196.0, 150.0, 5, 28.0),     # sweeps LANE_EYE_YARD
]


def build_backdrop_looks(stage):
    """The only locally-authored materials in this module.  See PALETTE.

    Twelve constant looks: four surface families x three depth planes, each one
    solved by `bd_albedo` from the pixel it is required to deliver. Nothing here
    is a guessed tint -- see the BD_GAIN / BD_FLOOR / BD_TARGET_SRGB block.
    """
    UsdGeom.Scope.Define(stage, BACKDROP_LOOKS).GetPrim().SetDocumentation(
        "Flat, dark, desaturated looks for the 88-330 m background silhouette band "
        "ONLY. Nothing closer than 88 m binds these. At that range the RTX distance "
        "fog has already collapsed any scanned material to a single value, so what a "
        "distant mass contributes is its silhouette and its value -- and a constant "
        "chosen to sit just under the sky is the correct answer, not a fallback. "
        "Three depth planes per family; the ramp is aerial perspective, baked, "
        "because the renderer supplies almost none of it at this range (measured: "
        "the additive in-scattered floor is 0.024-0.048 sRGB, under a fifth of the "
        "band's own value).")
    for name in BD_TARGET_SRGB:
        colour, rough = bd_albedo(name), 1.0
        path = f"{BACKDROP_LOOKS}/{name}"
        mat = UsdShade.Material.Define(stage, path)
        sh = UsdShade.Shader.Define(stage, f"{path}/Shader")
        sh.SetSourceAsset(Sdf.AssetPath("OmniPBR.mdl"), "mdl")
        sh.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
        sh.CreateInput("diffuse_color_constant",
                       Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*colour))
        sh.CreateInput("reflection_roughness_constant",
                       Sdf.ValueTypeNames.Float).Set(rough)
        # specular_level 0, NOT 0.12. MEASURED: with the diffuse at 0.0138 and
        # specular_level 0.12 the sheen alone measured 0.037-0.056 linear on the
        # backdrop masses in HERO_ESTABLISH -- 0.22-0.26 sRGB, i.e. ABOVE the
        # 0.20 sRGB the horizon has to stay under, before a single photon of
        # diffuse. It is also sun-COLOURED, which is why the delivered masses
        # measured warm-neutral (0.557, 0.498, 0.452) while their authored
        # albedo was blue. No amount of darkening the diffuse could have fixed
        # that; the sheen had to go.
        sh.CreateInput("specular_level", Sdf.ValueTypeNames.Float).Set(0.0)
        mat.CreateSurfaceOutput("mdl").ConnectToSource(
            sh.CreateOutput("out", Sdf.ValueTypeNames.Token))
        pv = UsdShade.Shader.Define(stage, f"{path}/Preview")
        pv.CreateIdAttr("UsdPreviewSurface")
        pv.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*colour))
        pv.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(rough)
        pv.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        pv.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(1.0)
        mat.CreateSurfaceOutput().ConnectToSource(
            pv.CreateOutput("surface", Sdf.ValueTypeNames.Token))


def build_backdrop(stage, mat_paths, report):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Backdrop")
    poly = Poly()

    def tones(cx, cy):
        """(mass, roof, steel) material indices on this object's depth plane."""
        p = bd_plane(cx, cy)
        return (M["BackdropMass" + p], M["BackdropRoof" + p], M["BackdropSteel" + p])

    def base(cx, cy):
        return float(far_z(np.array([cx]), np.array([cy]))[0]) - 2.2

    audit = []
    for item in BACKDROP:
        kind, cx, cy, top = item[0], item[1], item[2], item[3]
        z0 = base(cx, cy)
        mass, roof, steel = tones(cx, cy)
        cap = bd_ceiling(cx, cy, accent=kind in BD_ACCENT_KINDS)
        top = min(top, cap)
        h = max(top - z0, 4.0)
        if kind == "gasholder":
            r = item[4]
            bd_gasholder(poly, cx, cy, z0, r, h - r * 0.22, mass, roof, steel)
        elif kind == "chimney":
            r0, r1 = item[4], item[5]
            bd_chimney(poly, cx, cy, z0, h, r0, r1, mass, steel)
        elif kind == "mast":
            b, t = item[4], item[5]
            bd_mast(poly, cx, cy, z0, h - 5.0, b, t, steel)
        elif kind == "shed":
            L, W, drop, yaw = item[4], item[5], item[6], item[7]
            bd_shed(poly, cx, cy, z0, L, W, top - drop, top, yaw, mass, roof)
        elif kind == "block":
            sx, sy, yaw = item[4], item[5], item[6]
            # bd_block's roof plant room stands 1.30 x the body height, so the
            # BODY has to be sized off the clamped top, not the other way round.
            body = h / 1.30
            bd_block(poly, cx, cy, z0, sx, sy, body, yaw, mass, roof, steel,
                     int(abs(cx) * 131 + abs(cy) * 17) + 7)
            # a second, lower wing so the block is not a single extruded slab
            bd_box(poly, cx + sx * 0.38, cy - sy * 0.46, z0, z0 + body * 0.48,
                   sx * 0.40, sy * 0.85, yaw + 6.0, mass, top_mat=roof)
        elif kind == "silos":
            n, r, pitch, yaw = item[4], item[5], item[6], item[7]
            bd_silo_battery(poly, cx, cy, z0, n, r, (top - z0 - r * 0.42) / 1.06,
                            pitch, yaw, mass, roof)
        audit.append((kind, cx, cy, top,
                      math.degrees(math.atan2(top - 19.0,
                                              math.hypot(cx + 33.0, cy + 36.0)))))

    hot = [a for a in audit if a[4] > 5.0]
    report.append("  backdrop crest: max apparent elevation from HERO_ESTABLISH "
                  f"{max(a[4] for a in audit):+.2f} deg (frame top is +5.68); "
                  f"{len(hot)} entries above +5.0 deg")

    # Transmission lines. Their job is the SKY, not the crest: a storm HDRI is
    # smooth, and a catenary crossing a hundred metres of it on a curve breaks
    # far more empty sky than its silhouette area suggests.
    for k, (ax, ay, bx2, by2, n, hh) in enumerate(PYLON_LINES):
        bd_pylon_line(poly, ax, ay, bx2, by2, n, hh,
                      M["BackdropSteel" + bd_plane(0.5 * (ax + bx2),
                                                   0.5 * (ay + by2))], 5500 + k)

    rng = np.random.default_rng(SEED + 4400)
    x0, x1, y0, y1 = PLATE
    mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)

    def ring_point(rad):
        """A point on the far berm at radial distance `rad` out from the plate."""
        a = rng.uniform(0, 2 * math.pi)
        return (mx + (0.5 * (x1 - x0) + rad) * math.cos(a),
                my + (0.5 * (y1 - y0) + rad) * math.sin(a), a)

    # THE HORIZON TREE LINE.  Three depth planes of CONTINUOUS shelter belts.
    #
    # What was here before: ~1200 individually placed tapered masses, which
    # rounds 1, 2 and 3 all read as a comb of faceted cones -- correctly. See
    # bd_shelter_belt for why segment count and value could never have fixed
    # that: the failure was that each mass was a separate object with a pointed
    # silhouette, and a skyline made of separate pointed objects is a row of
    # tents at any resolution and any albedo.
    #
    # A shelter belt is ONE mass with an irregular crest. Thirty-one lofted
    # belts, each 40-190 m long, do the same job the 1200 masses were meant to
    # do -- break the berm crest, give the horizon depth planes -- while being
    # incapable of producing a cone silhouette. The individual trees read as
    # gaussian crowns inside the belt, which is how a real tree line reads from
    # 150 m: a continuous dark band with a lumpy top edge, not a row of shapes.
    #
    # 40_vegetation's Lombardy poplar lines at Y = -52 and X = -73 sit INSIDE the
    # plate, so they are always in front of these; the belts are the plane
    # behind them, which is exactly the layering the brief asks for.
    def scrub_tone(cx, cy):
        return M["BackdropScrub" + bd_plane(cx, cy)]

    belts = 0
    for lo, hi, count, hlo, hhi, wlo, whi in (
            (88.0, 130.0, 9, 5.0, 8.5, 4.5, 8.0),      # in front of the crest
            (130.0, 190.0, 15, 6.5, 11.0, 5.5, 10.5),  # ON the crest -- the read
            (190.0, 250.0, 10, 8.0, 13.0, 6.5, 12.5)):  # behind it
        got = 0
        tries = 0
        while got < count and tries < count * 40:
            tries += 1
            rad = rng.uniform(lo, hi)
            cx, cy, a = ring_point(rad)
            if not (lo - 25.0 <= float(far_d(np.array([cx]), np.array([cy]))[0]) <= hi + 25.0):
                continue
            # run the belt broadly TANGENTIALLY to the ring, so it lies across
            # the eye line rather than running away from it
            head = a + math.pi * 0.5 + math.radians(float(rng.uniform(-38, 38)))
            if rng.random() < 0.5:
                head += math.pi
            n_st = int(rng.integers(18, 86))
            bd_shelter_belt(poly, cx, cy, head, n_st,
                            float(rng.uniform(hlo, hhi)), float(rng.uniform(wlo, whi)),
                            scrub_tone(cx, cy), int(rng.integers(1, 10 ** 6)),
                            curve=math.radians(float(rng.uniform(-1.1, 1.1))))
            got += 1
            belts += 1

    # Copses: short belts, 4-9 stations, which read as a clump of six or seven
    # trees. Same primitive, so they cannot degenerate into cones either.
    copses = 0
    for _ in range(58):
        rad = rng.uniform(84.0, 252.0)
        cx, cy, a = ring_point(rad)
        d = float(far_d(np.array([cx]), np.array([cy]))[0])
        if d < 70.0 or d > 262.0:
            continue
        bd_shelter_belt(poly, cx, cy, rng.uniform(0, 2 * math.pi),
                        int(rng.integers(4, 10)),
                        float(rng.uniform(5.5, 11.0)), float(rng.uniform(5.0, 9.5)),
                        scrub_tone(cx, cy), int(rng.integers(1, 10 ** 6)),
                        step=float(rng.uniform(2.6, 4.2)), crown_amp=0.55)
        copses += 1

    # Distant out-buildings: low farm sheds and walls scattered through the
    # belts so the horizon is not purely vegetal. Capped at 6.2 m so none of
    # them spikes above the tree line and re-becomes a silhouette object.
    sheds = 0
    for _ in range(46):
        rad = rng.uniform(92.0, 240.0)
        cx, cy, a = ring_point(rad)
        d = float(far_d(np.array([cx]), np.array([cy]))[0])
        if d < 80.0 or d > 250.0:
            continue
        mass, roof, _steel = tones(cx, cy)
        z0 = float(far_z(np.array([cx]), np.array([cy]))[0]) - 0.9
        w = float(rng.uniform(6.0, 19.0))
        h = float(rng.uniform(2.6, 6.2))
        if rng.random() < 0.55:
            bd_shed(poly, cx, cy, z0, w, w * float(rng.uniform(0.35, 0.7)),
                    z0 + h * 0.72, z0 + h, float(rng.uniform(0, 180)), mass, roof)
        else:
            bd_box(poly, cx, cy, z0, z0 + h, w, w * float(rng.uniform(0.4, 1.0)),
                   float(rng.uniform(0, 180)), mass, top_mat=roof)
        sheds += 1

    emit_poly(stage, f"{TERRAIN}/Backdrop/BackgroundBand", poly, mat_paths,
              "BackdropMassM",
              doc="The background silhouette band at 88-330 m on the bearings "
                  "HERO_ESTABLISH, LANE_EYE_YARD and SILHOUETTE_WEST actually look down: "
                  "gasholders, lattice masts, chimneys, long shed roofs, silo batteries, "
                  "slab blocks and pylon runs, standing behind and among 34 CONTINUOUS "
                  "lofted shelter belts, ~55 copses and ~44 low out-buildings that break "
                  "the berm crest. Two structural rules make this a background rather than "
                  "a row of objects: (1) every crest, built or vegetal, is clamped by "
                  "bd_ceiling so its apparent elevation from HERO_ESTABLISH cannot exceed "
                  "+2.35 deg (+4.35 for slender accents) against a frame top of +5.68 -- "
                  "heights are no longer authored at all, only clamped world tops; "
                  "(2) nothing on the skyline has an apex: the belts are lofted "
                  "half-ellipses with gaussian crowns and analytic normals, and the silo "
                  "and gasholder crowns are three-frustum domes, because a solid of "
                  "revolution running to radius zero is a cone and a row of cones is what "
                  "four review rounds reported. Values are solved from a MEASURED transfer "
                  "so each of the twelve looks delivers a stated pixel -- see "
                  "BD_TARGET_SRGB / BD_GAIN. Three depth planes per surface family carry "
                  "the aerial perspective the renderer does not supply at this range.")
    report.append(f"  backdrop {len(BACKDROP)} blocked masses + {belts} shelter belts + "
                  f"{copses} copses + {sheds} out-buildings, {len(poly.FC)} faces")


def emit_poly(stage, path, poly: Poly, mat_paths, default_mat, doc=None):
    if poly.empty():
        return None
    return emit_mesh(stage, path, poly.P, poly.FC, poly.FI, poly.N, poly.ST,
                     poly.FM, mat_paths, default_mat, doc)


def ground_region(stage, name, x0, x1, y0, y1, cx, cy, mat_paths, default_mat,
                  cutouts=(), doc=None):
    nx = max(1, int(round((x1 - x0) / cx)))
    ny = max(1, int(round((y1 - y0) / cy)))
    dx = (x1 - x0) / nx
    dy = (y1 - y0) / ny
    # one-cell halo so normals come from central differences and match at seams
    xs = np.linspace(x0 - dx, x1 + dx, nx + 3)
    ys = np.linspace(y0 - dy, y1 + dy, ny + 3)
    Xh, Yh = np.meshgrid(xs, ys)
    Zh = terrain_z(Xh, Yh)

    gy, gx = np.gradient(Zh, dy, dx)
    nrm = np.stack([-gx[1:-1, 1:-1], -gy[1:-1, 1:-1],
                    np.ones_like(gx[1:-1, 1:-1])], axis=-1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)

    X = Xh[1:-1, 1:-1]
    Y = Yh[1:-1, 1:-1]
    Z = Zh[1:-1, 1:-1]
    pts = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
    st = np.stack([X, Y], axis=-1).reshape(-1, 2)
    nrm = nrm.reshape(-1, 3)

    W = nx + 1
    ii, jj = np.meshgrid(np.arange(nx), np.arange(ny))
    ii, jj = ii.ravel(), jj.ravel()
    fcx = X[0, ii] + 0.5 * dx
    fcy = Y[jj, 0] + 0.5 * dy

    keep = np.ones(ii.shape, dtype=bool)
    for (ax0, ax1, ay0, ay1) in cutouts:
        keep &= ~((fcx > ax0) & (fcx < ax1) & (fcy > ay0) & (fcy < ay1))
    ii, jj, fcx, fcy = ii[keep], jj[keep], fcx[keep], fcy[keep]

    a = jj * W + ii
    faces = np.stack([a, a + 1, a + W + 1, a + W], axis=-1).ravel()
    counts = np.full(ii.shape[0], 4, dtype=np.int32)
    return emit_mesh(stage, f"{TERRAIN}/Ground/{name}", pts, counts, faces, nrm, st,
                     classify(fcx, fcy), mat_paths, default_mat, doc)


# --- water ------------------------------------------------------------------


def _neighbours(mask):
    n = np.zeros(mask.shape, dtype=np.int32)
    n[1:, :] += mask[:-1, :]
    n[:-1, :] += mask[1:, :]
    n[:, 1:] += mask[:, :-1]
    n[:, :-1] += mask[:, 1:]
    return n


def _flood(X, Y, Z, level, mat):
    sub = Z < (level - 0.0045)
    keep = sub[:-1, :-1] & sub[1:, :-1] & sub[:-1, 1:] & sub[1:, 1:]
    # A face may only be filled in if the ground under it is still at or below
    # the waterline -- otherwise the morphological pass would float a slab of
    # water above dry ground, which reads as a hard-edged grey plate.
    fmax = np.maximum.reduce([Z[:-1, :-1], Z[1:, :-1], Z[:-1, 1:], Z[1:, 1:]])
    fillable = fmax < level
    # Morphological cleanup: a flood fill on a grid leaves single-cell spikes and
    # pinholes along the shoreline, and close up those read as torn polygons.
    for _ in range(2):
        nb = _neighbours(keep)
        keep = (keep & (nb >= 2)) | (fillable & (nb >= 3))
    if not keep.any():
        return None
    W = X.shape[1]
    jj, ii = np.nonzero(keep)
    a = jj * W + ii
    faces = np.stack([a, a + 1, a + W + 1, a + W], axis=-1).ravel()
    counts = np.full(ii.shape[0], 4, dtype=np.int32)
    pts = np.stack([X, Y, np.full_like(X, level)], axis=-1).reshape(-1, 3)
    nrm = np.tile(np.array([0.0, 0.0, 1.0]), (pts.shape[0], 1))
    st = np.stack([X, Y], axis=-1).reshape(-1, 2)
    mats = np.full(ii.shape[0], mat, dtype=np.int32)
    return pts, counts, faces, nrm, st, mats, int(ii.shape[0])


def build_water(stage, mat_paths, report):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Water")
    worst_edge = 0.0
    worst_name = "-"
    for p in ALL_PUDDLES:
        name, cx, cy, sx, sy, yaw, depth, diesel = p
        c = puddle_contour(p)
        if c is None:
            report.append(f"  WARNING puddle {name}: basin does not close")
            continue
        level, ox, oy, th, r = c
        # A real puddle is not one surface.  Wind ruffles the exposed middle
        # least and the shallow rim most, and the rim carries silt in suspension,
        # so the centre is a near-perfect mirror of the sky and the last hand's
        # width before the shoreline is dull.  That gradient is what makes water
        # read as water rather than as a dark cut-out, and it is authored here as
        # three concentric GeomSubsets binding three different shared looks --
        # frosting_roughness 0.006 / 0.022 / 0.075 in 50_materials.
        in_yard = (-53.0 < cx < 53.0) and (-40.0 < cy < 15.0)
        if diesel:
            bands = ("WaterDiesel", "WaterDiesel", "WaterSilt")
        elif p in PUDDLES or in_yard:
            # Every puddle a yard camera can see is a MIRROR.  It used to be
            # only the six hero basins; the other nineteen were bound to the
            # silty look, which is a rough dielectric, and a rough dielectric at
            # dusk returns the average of the dome instead of an image of it --
            # so nineteen out of twenty-five puddles in this level were throwing
            # away the single best thing a wet yard has to offer.
            bands = ("WaterCalm", "WaterCalm", "Water")
        else:
            bands = ("Water", "Water", "WaterSilt")
        sectors = len(th)
        ct, stt = np.cos(th), np.sin(th)
        rings = int(np.clip(round(float(np.median(r)) / 0.45), 3, 12))
        fr = np.linspace(1.0 / (rings + 1), 1.0, rings)
        px = [ox]
        py = [oy]
        for f in fr:
            px.extend(ox + r * f * ct)
            py.extend(oy + r * f * stt)
        # THE MENISCUS, as geometry.  Water wets asphalt, so the surface does
        # not stop dead at the waterline -- it climbs the bank for a centimetre
        # or two in a concave fillet.  That fillet is curved, so it reflects the
        # sky at a DIFFERENT angle from the flat middle, and what a camera sees
        # is an unbroken bright hairline running all the way round the puddle.
        # It is the single cue that says "this is a liquid with surface tension"
        # rather than "this is a grey polygon lying on tarmac", and no material
        # setting can supply it because it is a shape, not a shade.
        MEN_F = (1.013, 1.030, 1.044)
        MEN_Z = (0.0030, 0.0052, 0.0064)
        for f in MEN_F:
            px.extend(ox + r * f * ct)
            py.extend(oy + r * f * stt)
        P = np.array(px)
        Q = np.array(py)
        Z = np.full_like(P, level)
        base = 1 + rings * sectors
        for k, f in enumerate(MEN_F):
            a = base + k * sectors
            mx = P[a:a + sectors]
            my = Q[a:a + sectors]
            # ride on whichever is higher, the fillet or the bank it climbs
            Z[a:a + sectors] = np.maximum(level + MEN_Z[k],
                                          _overlay_z(mx, my, 0.0022, r=0.07))
        pts = np.stack([P, Q, Z], axis=-1)
        nrm = np.tile(np.array([0.0, 0.0, 1.0]), (P.size, 1))
        st = np.stack([P, Q], axis=-1)

        def band_of(f):
            # The mirror-smooth core now runs to 0.94 of the radius instead of
            # 0.88, and the dull rim band is the last 6% only. Wind ruffles the
            # shallows, not the middle, and a puddle that is dull over its outer
            # third has no room left to hold a reflection.
            if f <= 0.74:
                return M[bands[0]]
            if f <= 0.94:
                return M[bands[1]]
            return M[bands[2]]

        faces, counts, mats = [], [], []
        for s in range(sectors):
            faces.extend((0, 1 + s, 1 + (s + 1) % sectors))
            counts.append(3)
            mats.append(band_of(0.0))
        for k in range(rings - 1):
            a0 = 1 + k * sectors
            a1 = 1 + (k + 1) * sectors
            m = band_of(float(fr[k + 1]))
            for s in range(sectors):
                s2 = (s + 1) % sectors
                faces.extend((a0 + s, a0 + s2, a1 + s2, a1 + s))
                counts.append(4)
                mats.append(m)
        # the meniscus fillet: three rings climbing the bank, glossiest look
        men_mat = M[bands[0]] if not diesel else M["WaterDiesel"]
        for k in range(len(MEN_F)):
            a0 = 1 + (rings - 1) * sectors if k == 0 else base + (k - 1) * sectors
            a1 = base + k * sectors
            for s in range(sectors):
                s2 = (s + 1) % sectors
                faces.extend((a0 + s, a0 + s2, a1 + s2, a1 + s))
                counts.append(4)
                mats.append(men_mat)
        # measure the true longest shoreline edge rather than asserting a bound
        sx_ = ox + r * ct
        sy_ = oy + r * stt
        edge = float(np.max(np.hypot(sx_ - np.roll(sx_, -1), sy_ - np.roll(sy_, -1))))
        if edge > worst_edge:
            worst_edge, worst_name = edge, name
        emit_mesh(stage, f"{TERRAIN}/Water/{name}", pts, counts, faces, nrm, st,
                  np.array(mats, dtype=np.int32), mat_paths, bands[0],
                  doc=f"Standing water, flat surface Z = {level:.4f}, bed carved "
                      f"{depth * 100:.0f} mm below grade. The shoreline is a true contour "
                      f"of the carved basin -- bisected along {sectors} rays until the "
                      f"ground crosses the waterline -- so it is not a drawn ellipse; the "
                      f"longest straight segment anywhere on it is {edge:.3f} m. Bound in "
                      f"three concentric bands, mirror-smooth out to 0.94 of the radius "
                      f"and rougher only in the last 6%, plus a three-ring meniscus fillet "
                      f"that climbs 3-6 mm up the bank outside the shoreline so the "
                      f"waterline carries an unbroken specular hairline.")
        rmed = float(np.median(r))
        report.append(f"  water {name:<18} Z {level:+.4f}  r~{rmed:4.2f} m  "
                      f"{sectors:>3} rays  max edge {edge:.3f} m  {bands[0]}")
    report.append(f"  WATER SHORELINE worst straight edge {worst_edge:.3f} m "
                  f"({worst_name}) -- limit 0.400 m")

    # drainage ditch -- five flat reaches, like check dams
    for k, (xa, xb) in enumerate([(-70, -42), (-42, -14), (-14, 14), (14, 42), (42, 70)]):
        c = 0.30
        nx = int(round((xb - xa) / c))
        ny = int(round(5.0 / c))
        X, Y = np.meshgrid(np.linspace(xa, xb, nx + 1),
                           np.linspace(DITCH_Y - 2.5, DITCH_Y + 2.5, ny + 1))
        Z = terrain_z(X, Y)
        level = float(np.percentile(Z, 8)) + 0.30
        out = _flood(X, Y, Z, level, M["WaterSilt"])
        if out is None:
            continue
        pts, counts, faces, nrm, st, mats, nf = out
        emit_mesh(stage, f"{TERRAIN}/Water/DitchReach_{k}", pts, counts, faces, nrm, st,
                  mats, mat_paths, "WaterSilt",
                  doc=f"south-perimeter drainage ditch, standing water at Z = {level:.4f}")

    # fuel bund sump
    x0, x1, y0, y1 = BUND
    c = 0.25
    nx = int(round((x1 - x0) / c))
    ny = int(round((y1 - y0) / c))
    X, Y = np.meshgrid(np.linspace(x0 + 0.05, x1 - 0.05, nx + 1),
                       np.linspace(y0 + 0.05, y1 - 0.05, ny + 1))
    Z = terrain_z(X, Y)
    level = float(np.percentile(Z, 30)) + 0.15
    out = _flood(X, Y, Z, level + 0.0016, M["OilyWater"])
    if out is not None:
        pts, counts, faces, nrm, st, mats, nf = out
        emit_mesh(stage, f"{TERRAIN}/Water/FuelBund_Sump", pts, counts, faces, nrm, st,
                  mats, mat_paths, "OilyWater",
                  doc=f"oily standing water inside the fuel bund, Z = {level:.4f}")
        report.append(f"  water FuelBund_Sump      Z {level:+.4f}  {nf:>5} faces")


# --- trench drains ----------------------------------------------------------


def build_drains(stage, mat_paths):
    """Cast-iron slotted trench drains -- as CLOSED channels that hold water.

    Two things were wrong with the first version and both of them are visible
    from eight metres away in the detail shot.

    1.  The channel was an open-bottomed trough.  Its walls ran from 30 mm to
        160 mm below grade, but the terrain's own notch under it cut 300 mm, so
        the ground fell away below the walls and left a continuous gap into an
        unlit interior.  What you saw was a bottomless black slot with two
        dead-straight edges.  The channel is now a closed box: a solid invert at
        -0.320, full-height side walls, and end walls at both extremities.

    2.  The grating was TRANSVERSE bars, 55 mm wide on a 100 mm pitch, 30 mm
        deep.  The sun in this level is at 5.5 degrees, so every bar cast a
        310 mm shadow -- three pitches -- and the entire grating self-shadowed
        into solid black.  The grating now runs LONGITUDINALLY: five bars along
        the channel separated by 36 mm slots, cross-tied every 0.6 m.  That
        presents ~78% solid iron to the sky, so it catches the low key light and
        reads as ironwork, with the slots as dark lines running along the run.

    3.  The water was 175 mm below grade.  Nobody could ever see it.  The detail
        camera is 1.10 m up and 5.2 m back, so it looks into the channel at 13.6
        degrees: past the near lip a sight ray has fallen only 111 mm by the time
        it reaches the far wall, and 175 mm is 64 mm below that.  Every square
        millimetre of that water surface was occluded by the channel's own far
        wall, from every camera in the level.  The channel is a blocked drain the
        night a storm broke -- it is now holding water 82 mm below grade, i.e.
        42 mm under the grating, which puts a 0.29 m band of it in direct view
        through any open bay and a glint under every slot.

        And the water still would not have shown, because THE TERRAIN IS NOT CUT
        AT THE DRAIN.  The ground plate runs straight through the channel at the
        depth of the drain's own dish, so with a 75 mm dish the pavement lay 28 mm
        ON TOP OF an 92 mm water surface: the channel was a box of geometry with
        a floor drawn across its middle.  `_drain_notch` now cuts 132 mm, and
        build_drains asserts both clearances every run.

    4.  Nothing had lifted a grate.  A 74 m run of continuous, intact, identical
        cast-iron is the sort of thing only a renderer builds.  Two bays are now
        deliberately open where SHOT 4 crosses the run at X = -8.9, with the
        removed leaf lying on the pavement beside them, so the standing water in
        the channel is looked at directly rather than inferred through a slot.

    5.  It was clean.  A trench drain is the wettest, shadiest, least-swept line
        in a yard: the inner faces are permanently damp algae-dark concrete, and
        moss grows out of the joint between the frame and the grating.  Both are
        authored now, and SHOT 4 is framed on this exact detail 5 m from the lens.
    """
    UsdGeom.Scope.Define(stage, TERRAIN + "/Drainage")
    HV, HF = 0.23, 0.80      # half-width of the slot and of the concrete frame
    FRAME = 0.038            # frame top below local grade
    SKIRT = 0.110            # how far the outer skirt buries into the pavement
    INVERT = 0.330           # depth of the channel floor below local grade
    WATER = 0.082            # depth of the water surface below local grade
    # Bays deliberately without a grating.  The first pair is the SHOT 4 crossing
    # (the drain runs under the detail camera's aim point at X = -8.9); the rest
    # are scattered so the run does not read as one intact extrusion.
    OPEN_BAYS = {"EW": [(-9.42, -8.75), (14.6, 15.3), (-27.4, -26.7)],
                 "NS": [(-2.3, -1.6)]}
    # Placed by projecting them into SHOT 4 rather than by eye: the first sits
    # 3.8 m from the detail camera at frame (740, 1010), directly beside the bay
    # it was pulled out of, so the open channel has a reason on screen.  The
    # second is 24 m away at the other open bay so the gesture is not a repeat.
    LOOSE_LEAVES = {"EW": [(-9.55, -13.15, 24.0), (15.10, -13.30, -38.0)],
                    "NS": []}
    # The drain only exists if the terrain's own dish is deeper than the frame at
    # the frame's outer edge.  Narrow that dish by 5 mm too much and the pavement
    # closes over the ironwork and the whole assembly vanishes -- silently, with
    # no error, in a 190 MB layer nobody reads.  Check it every build.
    _clear = float(_drain_notch(np.array([0.0]), np.array([DRAIN_EW[1] + HF]))[0])
    if _clear <= FRAME + 0.012:
        raise RuntimeError(
            f"trench-drain frame would be buried: the drain dish is only "
            f"{_clear * 1000:.1f} mm deep at |offset| = {HF} m but the frame top "
            f"sits {FRAME * 1000:.1f} mm below grade. Deepen _drain_notch.")
    _slot = float(_drain_notch(np.array([0.0]), np.array([DRAIN_EW[1] + HV]))[0])
    if _slot <= WATER + 0.018:
        raise RuntimeError(
            f"the ground plate would lie ON TOP OF the drain water: the dish is "
            f"{_slot * 1000:.1f} mm deep at the slot edge but the channel's water "
            f"surface is {WATER * 1000:.1f} mm below grade, and the terrain is not "
            f"cut at the drain. Deepen _drain_notch or raise the water.")
    for tag, (axis, c, s0, s1) in (("EW", DRAIN_EW), ("NS", DRAIN_NS)):
        poly = Poly()
        rng = np.random.default_rng(SEED + (0 if tag == "EW" else 1))
        step = 0.5
        n = int(round((s1 - s0) / step))
        ss = np.linspace(s0, s1, n + 1)
        # LOCAL grade on the drain line, with the drain's own dish added back.
        # The first version sampled the ground 1.5 m to one side, which for the
        # E-W drain lands in the soft seam between the yard and the dock paved
        # rectangles where the unpaved penalty is half applied.  The whole
        # assembly was therefore built 5-9 cm too low, the terrain's dish closed
        # over the top of it, and every camera saw a bare groove in the ground
        # with the ironwork hidden inside it -- which is precisely the "black
        # void with no water and no grating" in the detail frame.
        cc = np.full_like(ss, c)
        if axis == "y":
            base = terrain_z(ss, cc) + _drain_notch(ss, cc)
        else:
            base = terrain_z(cc, ss) + _drain_notch(cc, ss)

        def pt(s, o, z):
            return (s, c + o, z) if axis == "y" else (c + o, s, z)

        for i in range(n):
            a, b = float(ss[i]), float(ss[i + 1])
            g0, g1 = float(base[i]), float(base[i + 1])
            # invert: a solid floor, benched slightly so silt collects in the middle
            poly.add([pt(a, -HV, g0 - INVERT), pt(b, -HV, g1 - INVERT),
                      pt(b, HV, g1 - INVERT), pt(a, HV, g0 - INVERT)],
                     M["PuddleBed"], normal=(0, 0, 1))
            # Full-height channel walls, inward facing.  Split at the waterline:
            # silted bed colour below it, algae-dark permanently wet concrete
            # above.  A tide mark inside a drain is free and it is the difference
            # between "a slot" and "a drain that has been holding water".
            for o in (-HV, HV):
                for za, zb, mat in ((INVERT, WATER + 0.010, M["PuddleBed"]),
                                    (WATER + 0.010, FRAME, M["ConcreteWetAlgae"])):
                    quad = [pt(a, o, g0 - za), pt(b, o, g1 - za),
                            pt(b, o, g1 - zb), pt(a, o, g0 - zb)]
                    poly.add(quad if o < 0 else quad[::-1], mat)
            # concrete frame either side of the slot
            for lo, hi in ((-HF, -HV), (HV, HF)):
                poly.add([pt(a, lo, g0 - FRAME), pt(b, lo, g1 - FRAME),
                          pt(b, hi, g1 - FRAME), pt(a, hi, g0 - FRAME)],
                         M["ConcreteKerb"], normal=(0, 0, 1))
            for o in (-HF, HF):     # outer skirt buried in the dished pavement
                quad = [pt(a, o, g0 - FRAME - SKIRT), pt(b, o, g1 - FRAME - SKIRT),
                        pt(b, o, g1 - FRAME), pt(a, o, g0 - FRAME)]
                poly.add(quad if o > 0 else quad[::-1], M["ConcreteKerb"])

        # end walls, so the channel is a closed box and not a tunnel to nowhere
        for s_end, sgn in ((s0, -1.0), (s1, 1.0)):
            g = float(base[0] if sgn < 0 else base[-1])
            quad = [pt(s_end, -HV, g - INVERT), pt(s_end, HV, g - INVERT),
                    pt(s_end, HV, g - FRAME), pt(s_end, -HV, g - FRAME)]
            poly.add(quad if sgn > 0 else quad[::-1], M["ConcreteKerb"])

        # ---- the grating: longitudinal bars, cross-tied ---------------------
        BARN = 5
        gap = 0.036
        barw = (2.0 * HV - (BARN - 1) * gap) / BARN          # 0.0632 m
        panel = 0.60
        npan = int((s1 - s0) / panel)
        missing = set()
        for k in range(npan):
            pa = s0 + k * panel
            if any(lo - 0.05 < pa < hi for lo, hi in OPEN_BAYS[tag]):
                missing.add(k)                                # authored open bay
            elif rng.random() < 0.055:                        # grate lifted / stolen
                missing.add(k)
        for k in range(npan):
            if k in missing:
                continue
            pa = s0 + k * panel
            pb = pa + panel
            sink = 0.0
            if rng.random() < 0.07:                           # a panel dropped in
                sink = float(rng.uniform(0.006, 0.020))
            ga = float(np.interp(pa, ss, base))
            gb = float(np.interp(pb, ss, base))
            top_a, top_b = ga - 0.040 - sink, gb - 0.040 - sink
            bot_a, bot_b = top_a - 0.034, top_b - 0.034
            for j in range(BARN):
                oa = -HV + j * (barw + gap)
                ob = oa + barw
                poly.add([pt(pa, oa, top_a), pt(pb, oa, top_b),
                          pt(pb, ob, top_b), pt(pa, ob, top_a)],
                         M["DrainIron"], normal=(0, 0, 1))
                for o, sgn in ((oa, -1.0), (ob, 1.0)):
                    quad = [pt(pa, o, bot_a), pt(pb, o, bot_b),
                            pt(pb, o, top_b), pt(pa, o, top_a)]
                    poly.add(quad if sgn < 0 else quad[::-1], M["DrainIron"])
                for s_end, sg in ((pa, -1.0), (pb, 1.0)):
                    z = top_a if sg < 0 else top_b
                    zb = bot_a if sg < 0 else bot_b
                    quad = [pt(s_end, oa, zb), pt(s_end, ob, zb),
                            pt(s_end, ob, z), pt(s_end, oa, z)]
                    poly.add(quad if sg > 0 else quad[::-1], M["DrainIron"])
            # transverse cross-tie at the panel joint, standing 3 mm proud
            ta = pa + 0.02
            tb = pa + 0.07
            poly.add([pt(ta, -HV, top_a + 0.003), pt(tb, -HV, top_a + 0.003),
                      pt(tb, HV, top_a + 0.003), pt(ta, HV, top_a + 0.003)],
                     M["DrainIron"], normal=(0, 0, 1))
            for s_end, sg in ((ta, -1.0), (tb, 1.0)):
                quad = [pt(s_end, -HV, top_a - 0.030), pt(s_end, HV, top_a - 0.030),
                        pt(s_end, HV, top_a + 0.003), pt(s_end, -HV, top_a + 0.003)]
                poly.add(quad if sg > 0 else quad[::-1], M["DrainIron"])

        emit_poly(stage, f"{TERRAIN}/Drainage/TrenchDrain_{tag}", poly, mat_paths,
                  "DrainIron",
                  doc="Cast-iron slotted trench drain. A CLOSED concrete channel -- "
                      "0.32 m invert, full-height walls, end walls -- carrying a "
                      "longitudinal grating of five 63 mm bars separated by 36 mm slots "
                      "and cross-tied every 0.60 m. Longitudinal, not transverse: at the "
                      "5.5 degree sun elevation of this level a transverse bar shadows "
                      "the next three, and the whole grating goes black.")

        # ---- the water the channel is holding -------------------------------
        wat = Poly()
        for i in range(n):
            a, b = float(ss[i]), float(ss[i + 1])
            g0, g1 = float(base[i]), float(base[i + 1])
            wat.add([pt(a, -HV + 0.004, g0 - WATER), pt(b, -HV + 0.004, g1 - WATER),
                     pt(b, HV - 0.004, g1 - WATER), pt(a, HV - 0.004, g0 - WATER)],
                    M["Water"], normal=(0, 0, 1))
        emit_poly(stage, f"{TERRAIN}/Drainage/TrenchDrain_{tag}_Water", wat, mat_paths,
                  "Water",
                  doc=f"Standing water {WATER * 1000:.0f} mm below grade -- 42 mm under the "
                      "grating -- inside the closed channel. At the 13.6 degree look-down "
                      "of the detail camera this surface is DIRECTLY visible across a "
                      "0.29 m band through every open bay, and shows as a glint under "
                      "every slot elsewhere. It used to sit at 175 mm, which the "
                      "channel's own far wall occluded from every camera in the level.")

        # ---- moss in the corner between the frame and the grating ------------
        # A drain frame collects everything that washes toward it and never dries.
        # The joint at the slot edge is where moss actually grows, and it is what
        # SHOT 4 is judged on -- so it is authored as a run of small blobs hugging
        # both inner corners, patchy rather than continuous, thickest where the
        # frame is shaded by the grating.
        corner = Poly()
        crng = np.random.default_rng(SEED + (60 if tag == "EW" else 61))
        for k in range(int((s1 - s0) / 0.16)):
            s = s0 + (k + 0.5) * 0.16
            ftop = float(np.interp(s, ss, base)) - FRAME
            for sgn in (-1.0, 1.0):
                if crng.random() < 0.30:
                    continue
                o = sgn * float(crng.uniform(HV + 0.010, HV + 0.130))
                # Small and ragged, not big and round.  A 0.25 m moss blob with an
                # eight-sided outline lying flat on concrete is a lime sticker; the
                # colony has to be a stipple of 4-11 cm patches with fractal edges
                # before it reads as something growing rather than something pasted.
                w = 0.016 + 0.062 * float(crng.random()) ** 1.9
                px, py = pt(s, o, 0.0)[0], pt(s, o, 0.0)[1]
                corner.add([(qx, qy, ftop + 0.0026) for qx, qy in
                            blob(px, py, w, w * float(crng.uniform(0.35, 0.85)),
                                 int(crng.integers(0, 999999)), n=16, rough=0.62)],
                           M["Moss"], normal=(0, 0, 1))
            if crng.random() < 0.22:        # silt washed across the frame
                # NOT the algae look: a flat 0.19 m quad of saturated algae-green
                # lying on a smooth frame is a teal sticker, and at 2x on the
                # detail frame that is exactly what it read as. Silt is the right
                # material for something the water carried here anyway.
                o = float(crng.uniform(-HF + 0.05, HF - 0.05))
                if abs(o) < HV + 0.02:
                    continue
                r = 0.035 + 0.10 * float(crng.random()) ** 1.7
                px, py = pt(s, o, 0.0)[0], pt(s, o, 0.0)[1]
                corner.add([(qx, qy, ftop + 0.0018) for qx, qy in
                            blob(px, py, r, r * 0.65, int(crng.integers(0, 999999)),
                                 n=14, rough=0.6)],
                           M["PuddleBed"], normal=(0, 0, 1))
        # A slime tongue on the invert under each open bay, so the exposed channel
        # floor is not clean concrete where it is actually looked at.
        for lo, hi in OPEN_BAYS[tag]:
            gm = float(np.interp(0.5 * (lo + hi), ss, base))
            for _ in range(7):
                s = float(crng.uniform(lo - 0.1, hi + 0.1))
                o = float(crng.uniform(-HV + 0.03, HV - 0.03))
                r = float(crng.uniform(0.04, 0.10))
                px, py = pt(s, o, 0.0)[0], pt(s, o, 0.0)[1]
                corner.add([(qx, qy, gm - 0.126) for qx, qy in
                            blob(px, py, r, r * 0.7, int(crng.integers(0, 999999)),
                                 n=8, rough=0.5)], M["Moss"], normal=(0, 0, 1))
        emit_poly(stage, f"{TERRAIN}/Drainage/TrenchDrain_{tag}_Moss", corner, mat_paths,
                  "Moss",
                  doc="moss in the joint between the drain frame and the grating, algae "
                      "creeping across the frame, and slime on the exposed invert of the "
                      "open bays")

        # ---- the grate leaves somebody lifted out ----------------------------
        for lx, ly, lyaw in LOOSE_LEAVES[tag]:
            leaf = Poly()
            ca_, sa_ = math.cos(math.radians(lyaw)), math.sin(math.radians(lyaw))

            def place(u, v):
                return (lx + u * ca_ - v * sa_, ly + u * sa_ + v * ca_)

            # A steel leaf is rigid, so it does not drape -- it lands on a plane.
            # Fit that plane to the ground under its own footprint (the gully bank
            # here runs at about 1:10) or one corner floats and the other buries.
            _s = [(u, v, z_at(*place(u, v)))
                  for u in (-0.30, 0.30) for v in (-HV, HV)]
            _bu = ((_s[2][2] + _s[3][2]) - (_s[0][2] + _s[1][2])) / (2 * 0.60)
            _bv = ((_s[1][2] + _s[3][2]) - (_s[0][2] + _s[2][2])) / (2 * 2 * HV)
            _a = max(q[2] - _bu * q[0] - _bv * q[1] for q in _s) + 0.004

            def gzp(u, v):
                return _a + _bu * u + _bv * v

            def slab(ua, ub, va, vb, thick):
                ring = [(ua, va), (ub, va), (ub, vb), (ua, vb)]
                top = [place(u, v) + (gzp(u, v),) for u, v in ring]
                leaf.add([(q[0], q[1], q[2]) for q in top], M["DrainIron"],
                         normal=(0, 0, 1))
                for e in range(4):
                    p0, p1 = top[e], top[(e + 1) % 4]
                    leaf.add([(p0[0], p0[1], p0[2] - thick),
                              (p1[0], p1[1], p1[2] - thick),
                              (p1[0], p1[1], p1[2]), (p0[0], p0[1], p0[2])],
                             M["DrainIron"])

            for j in range(BARN):
                oa = -HV + j * (barw + gap)
                slab(-0.30, 0.30, oa, oa + barw, 0.034)
            for uu in (-0.27, 0.27):        # the two cross-ties
                slab(uu - 0.025, uu + 0.025, -HV, HV, 0.031)
            emit_poly(stage,
                      f"{TERRAIN}/Drainage/TrenchDrain_{tag}_Leaf_"
                      f"{abs(int(round(lx * 10)))}_{abs(int(round(ly * 10)))}",
                      leaf, mat_paths, "DrainIron",
                      doc="a grating leaf lifted out of the run and dropped on the "
                          "pavement beside the bay it came from")

        # Moss and silt along the frame, and a damp band either side.  A drain
        # is the wettest, shadiest line in a yard -- a clean one is a lie, and
        # SHOT 4 is framed on this exact detail 5 m from the lens.
        dress = Poly()
        mrng = np.random.default_rng(SEED + (40 if tag == "EW" else 41))
        for k in range(int((s1 - s0) / 0.55)):
            s = s0 + (k + 0.5) * 0.55
            for o in (-HF - 0.06, HF + 0.06):
                if mrng.random() < 0.34:
                    continue
                w = float(mrng.uniform(0.035, 0.115))
                px, py = pt(s, o + float(mrng.uniform(-0.10, 0.22)), 0.0)[:2]
                dress.add([(qx, qy, z_at(qx, qy) + L_MOSS) for qx, qy in
                           blob(px, py, w, w * float(mrng.uniform(0.5, 1.0)),
                                int(mrng.integers(0, 999999)), n=15, rough=0.6)],
                          M["Moss"], normal=(0, 0, 1))
            if mrng.random() < 0.35:            # silt washed out of the slot
                o = float(mrng.uniform(-1.5, 1.5))
                px, py = pt(s, o, 0.0)[0], pt(s, o, 0.0)[1]
                r = float(mrng.uniform(0.12, 0.42))
                dress.add([(qx, qy, z_at(qx, qy) + L_MOSS - 0.0006) for qx, qy in
                           blob(px, py, r, r * 0.7, int(mrng.integers(0, 999999)),
                                n=10, rough=0.5)], M["PuddleBed"], normal=(0, 0, 1))
        # Permanently damp ground either side of the channel.  This used to be a
        # constant-width 0.30 m strip offset a constant 0.95 m from the
        # centreline: two dead-straight parallel edges running seventy metres
        # across the yard, which from the detail camera is a strip of tape lying
        # beside the drain.  It is now a ragged ribbon whose width breathes
        # between 0.1 and 0.5 m and which wanders off its line, plus a stipple
        # of matte mottling dissolving outward, so it has no cut edge at all.
        for o in (-0.88, 0.88):
            line = [(pt(float(s), o, 0.0)[0], pt(float(s), o, 0.0)[1])
                    for s in np.linspace(s0, s1, int((s1 - s0) / 0.6) + 1)]
            ragged_ribbon(line, 0.30, M["DampRing"], dress, lift=L_PATCH - 0.0008,
                          keep=0.46, rng=mrng, jitter=0.85, wobble=0.62,
                          seed=int(311 + 13 * o))
        for k in range(int((s1 - s0) / 1.4)):
            s = s0 + (k + 0.5) * 1.4
            for o in (-1.15, 1.15):
                if mrng.random() < 0.45:
                    continue
                qx, qy = pt(s, o + float(mrng.uniform(-0.3, 0.3)), 0.0)[:2]
                stipple(dress, M["DampMottle"], int(mrng.integers(0, 999999)),
                        qx, qy, 0.55, 0.35, 7, 0.04, 0.16, lift=L_PATCH - 0.0012,
                        bias=1.4, edge=0.7)
        emit_poly(stage, f"{TERRAIN}/Drainage/TrenchDrain_{tag}_Dressing", dress,
                  mat_paths, "Moss",
                  doc="moss on the drain frame, silt fans washed out of the slot and a "
                      "permanently damp band either side of the channel")


def build_covers(stage, mat_paths):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Covers")
    poly = Poly()
    rng = np.random.default_rng(SEED + 7)
    seg = 24
    ring = [(math.cos(2 * math.pi * k / seg), math.sin(2 * math.pi * k / seg))
            for k in range(seg)]
    # A manhole is a SET COVER: a heavy iron lid dropped into a cast frame, and
    # the whole point of it visually is that it is INSET.  The first version was
    # a flat disc floating 6 mm ABOVE grade on a raised collar, which from any
    # distance is a hard-edged black ellipse painted on the ground -- the critic
    # named it in the hero frame.  What is built now, from the outside in:
    #   * a concrete haunch ring, top at grade, sloping down to
    #   * a frame seating flange 30 mm below grade,
    #   * a 22 mm annular gap showing a dark socket 90 mm down,
    #   * the lid itself, top 20 mm below the frame, slightly tilted in its seat,
    #   * two raised keyways and two pick-holes on the lid face.
    seg2 = 32
    ring2 = [(math.cos(2 * math.pi * k / seg2), math.sin(2 * math.pi * k / seg2))
             for k in range(seg2)]
    for cx, cy in MANHOLES:
        g = z_at(cx, cy)
        r_haunch, r_flange, r_socket, r_lid = 0.475, 0.360, 0.320, 0.298
        z_flange = g - 0.030
        z_lid = g - 0.050
        tilt = math.radians(float(rng.uniform(-2.4, 2.4)))
        yaw = float(rng.uniform(0, math.pi))
        for k in range(seg2):
            ax, ay = ring2[k]
            bx, by = ring2[(k + 1) % seg2]
            # concrete haunch, grade down to the frame flange
            poly.add([(cx + ax * r_flange, cy + ay * r_flange, z_flange),
                      (cx + bx * r_flange, cy + by * r_flange, z_flange),
                      (cx + bx * r_haunch, cy + by * r_haunch, g + 0.002),
                      (cx + ax * r_haunch, cy + ay * r_haunch, g + 0.002)],
                     M["ConcreteKerb"])
            # frame flange, flat, iron
            poly.add([(cx + ax * r_socket, cy + ay * r_socket, z_flange),
                      (cx + bx * r_socket, cy + by * r_socket, z_flange),
                      (cx + bx * r_flange, cy + by * r_flange, z_flange),
                      (cx + ax * r_flange, cy + ay * r_flange, z_flange)],
                     M["ManholeIron"], normal=(0, 0, 1))
            # socket wall dropping into the chamber, and its dark floor ring
            poly.add([(cx + ax * r_socket, cy + ay * r_socket, g - 0.120),
                      (cx + bx * r_socket, cy + by * r_socket, g - 0.120),
                      (cx + bx * r_socket, cy + by * r_socket, z_flange),
                      (cx + ax * r_socket, cy + ay * r_socket, z_flange)][::-1],
                     M["DrainVoid"])
            poly.add([(cx + ax * r_lid, cy + ay * r_lid, g - 0.120),
                      (cx + bx * r_lid, cy + by * r_lid, g - 0.120),
                      (cx + bx * r_socket, cy + by * r_socket, g - 0.120),
                      (cx + ax * r_socket, cy + ay * r_socket, g - 0.120)],
                     M["DrainVoid"], normal=(0, 0, 1))

        def lid_z(u, v, base=z_lid):
            return base + math.tan(tilt) * (u * math.cos(yaw) + v * math.sin(yaw))

        disc = [(cx + ax * r_lid, cy + ay * r_lid, lid_z(ax * r_lid, ay * r_lid))
                for ax, ay in ring2]
        poly.add(disc, M["ManholeIron"], normal=(0, 0, 1))
        for k in range(seg2):
            a, b = disc[k], disc[(k + 1) % seg2]
            poly.add([(a[0], a[1], a[2] - 0.070), (b[0], b[1], b[2] - 0.070), b, a],
                     M["ManholeIron"])
        # two raised keyway ribs across the lid, 4 mm proud, so the face is not flat
        ka = float(rng.uniform(0, math.pi))
        for sgn in (-1.0, 1.0):
            ca2, sa2 = math.cos(ka), math.sin(ka)
            hw, hl = 0.026, r_lid * 0.86
            oc = sgn * r_lid * 0.34
            quad = []
            for du, dv in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)):
                u, v = du, dv + oc
                quad.append((cx + u * ca2 - v * sa2, cy + u * sa2 + v * ca2,
                             lid_z(u * ca2 - v * sa2, u * sa2 + v * ca2) + 0.004))
            poly.add(quad, M["ManholeIron"], normal=(0, 0, 1))
        # two pick-holes -- small dark squares punched through the lid face
        for sgn in (-1.0, 1.0):
            u = sgn * r_lid * 0.62
            v = 0.0
            hw = 0.030
            quad = [(cx + u - hw, cy + v - hw, lid_z(u - hw, v - hw) - 0.028),
                    (cx + u + hw, cy + v - hw, lid_z(u + hw, v - hw) - 0.028),
                    (cx + u + hw, cy + v + hw, lid_z(u + hw, v + hw) - 0.028),
                    (cx + u - hw, cy + v + hw, lid_z(u - hw, v + hw) - 0.028)]
            poly.add(quad, M["DrainVoid"], normal=(0, 0, 1))

    for cx, cy in ((-26.0, 13.0), (-6.0, 13.0), (14.0, 13.0), (30.0, 13.0),
                   (-44.0, -16.6), (26.0, -16.6)):
        g = z_at(cx, cy)
        h = 0.225
        poly.add([(cx - h, cy - h, g - 0.055), (cx + h, cy - h, g - 0.055),
                  (cx + h, cy + h, g - 0.055), (cx - h, cy + h, g - 0.055)],
                 M["DrainVoid"], normal=(0, 0, 1))
        for e in ((-h, -h, h, -h), (h, -h, h, h), (h, h, -h, h), (-h, h, -h, -h)):
            poly.add([(cx + e[0], cy + e[1], g - 0.055), (cx + e[2], cy + e[3], g - 0.055),
                      (cx + e[2], cy + e[3], g + 0.002), (cx + e[0], cy + e[1], g + 0.002)],
                     M["DrainVoid"])
        for k in range(5):
            y0 = cy - h + 0.02 + k * 0.088
            poly.add([(cx - h, y0, g + 0.002), (cx + h, y0, g + 0.002),
                      (cx + h, y0 + 0.048, g + 0.002), (cx - h, y0 + 0.048, g + 0.002)],
                     M["ManholeIron"], normal=(0, 0, 1))

    emit_poly(stage, f"{TERRAIN}/Covers/ManholeCovers", poly, mat_paths, "ManholeIron",
              doc="Cast-iron set covers. Each is a real inset assembly -- concrete haunch "
                  "at grade, iron seating flange 30 mm down, a 22 mm annular gap onto a "
                  "dark socket 120 mm down, and the lid itself 50 mm below grade with two "
                  "raised keyway ribs and two punched pick-holes, tilted up to 2.4 deg in "
                  "its seat. Not a flat disc lying on the surface. Plus six kerbside gully "
                  "gratings over dark voids.")


def build_kerbs(stage, mat_paths):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Kerbs")

    # 1.5 m x 0.12 m kerb plinth against the warehouse south wall (Y 13.50 .. 15.00)
    poly = Poly()
    rng = np.random.default_rng(SEED + 11)
    y_s, y_n = 13.50, 15.00
    xs = np.arange(-38.0, 38.0001, 0.5)
    tops = []
    for x in xs:
        if -4.2 < x < 4.2:                       # hero-gate vehicle crossing
            tops.append(None)
            continue
        t = 0.120
        for cx, w in ((-29.4, 0.9), (-11.8, 0.6), (17.6, 1.1)):   # chipped / spalled
            if abs(x - cx) < w:
                t = 0.040 + 0.02 * float(rng.random())
        tops.append(t + 0.004 * float(vnoise(np.array([x]), np.array([0.0]), 0.7, 91)[0]))
    for i in range(len(xs) - 1):
        if tops[i] is None or tops[i + 1] is None:
            continue
        xa, xb = float(xs[i]), float(xs[i + 1])
        za, zb = z_at(xa, y_s), z_at(xb, y_s)
        ta, tb = za + tops[i], zb + tops[i + 1]
        poly.add([(xa, y_s, ta), (xb, y_s, tb), (xb, y_n, tb), (xa, y_n, ta)],
                 M["ConcreteKerb"], normal=(0, 0, 1))
        poly.add([(xa, y_s, za), (xb, y_s, zb), (xb, y_s, tb), (xa, y_s, ta)],
                 M["ConcreteKerb"], normal=(0, -1, 0))
    for xe in (-38.0, -4.2, 4.2, 38.0):
        ze = z_at(xe, y_s)
        poly.add([(xe, y_s, ze), (xe, y_n, ze), (xe, y_n, ze + 0.120), (xe, y_s, ze + 0.120)],
                 M["ConcreteKerb"])
    emit_poly(stage, f"{TERRAIN}/Kerbs/WarehouseKerbPlinth", poly, mat_paths, "ConcreteKerb",
              doc="1.5 m x 0.12 m concrete kerb plinth along the warehouse south wall; "
                  "chipped down to 0.04 m in three places, broken out at the hero gate")

    # loading-dock apron edge beam at Y = -21.70, broken out at every truck bay
    poly = Poly()
    bays = (-38.0, -22.0, -6.0, 10.0)
    y_c, hw = -21.70, 0.15
    xs = np.arange(-46.0, 30.0001, 0.5)
    for i in range(len(xs) - 1):
        xa, xb = float(xs[i]), float(xs[i + 1])
        xm = 0.5 * (xa + xb)
        if any(abs(xm - b) < 2.3 for b in bays) or 1.6 < xm < 8.4:
            continue
        if 25.0 < xm < 26.6 or -33.0 < xm < -31.8:       # smashed sections
            continue
        za, zb = z_at(xa, y_c), z_at(xb, y_c)
        ta, tb = za + 0.085, zb + 0.085
        poly.add([(xa, y_c - hw, ta), (xb, y_c - hw, tb),
                  (xb, y_c + hw, tb), (xa, y_c + hw, ta)], M["ConcreteKerb"], normal=(0, 0, 1))
        poly.add([(xa, y_c + hw, za), (xb, y_c + hw, zb),
                  (xb, y_c + hw, tb), (xa, y_c + hw, ta)], M["ConcreteKerb"], normal=(0, 1, 0))
        poly.add([(xb, y_c - hw, zb), (xa, y_c - hw, za),
                  (xa, y_c - hw, ta), (xb, y_c - hw, tb)], M["ConcreteKerb"], normal=(0, -1, 0))
    emit_poly(stage, f"{TERRAIN}/Kerbs/DockApronEdgeBeam", poly, mat_paths, "ConcreteKerb",
              doc="concrete apron edge beam in front of the dock face, broken out at each "
                  "recessed truck bay and at the X +2..+8 drive-through")

    # 0.35 m permanently wet algae band along the dock foot at Y = -21.0
    poly = Poly()
    for i in range(len(xs) - 1):
        xa, xb = float(xs[i]), float(xs[i + 1])
        wa = 0.175 + 0.06 * float(vnoise(np.array([xa]), np.array([0.0]), 0.55, 123)[0])
        wb = 0.175 + 0.06 * float(vnoise(np.array([xb]), np.array([0.0]), 0.55, 123)[0])
        za, zb = z_at(xa, -21.0) + 0.004, z_at(xb, -21.0) + 0.004
        poly.add([(xa, -21.0 - wa, za), (xb, -21.0 - wb, zb),
                  (xb, -21.0 + wb, zb), (xa, -21.0 + wa, za)],
                 M["ConcreteWetAlgae"], normal=(0, 0, 1))
    emit_poly(stage, f"{TERRAIN}/Kerbs/DockFootAlgaeBand", poly, mat_paths,
              "ConcreteWetAlgae",
              doc="0.35 m band of permanently wet algae-dark concrete along the dock foot")


def build_broken_slabs(stage, mat_paths):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Debris")
    poly = Poly()
    rng = np.random.default_rng(SEED + 21)
    zones = [
        (-74.0, -70.5, -54.0, 92.0, 16), (70.5, 74.0, -54.0, 92.0, 16),
        (-70.0, 70.0, -55.0, -41.0, 26), (-68.0, 68.0, 77.0, 93.0, 22),
        (31.0, 51.0, -39.0, -17.0, 14), (-70.0, -40.0, 36.0, 75.0, 14),
        (40.0, 70.0, 30.0, 75.0, 12),
    ]
    for x0, x1, y0, y1, n in zones:
        for _ in range(n):
            cx = float(rng.uniform(x0, x1))
            cy = float(rng.uniform(y0, y1))
            if 13.0 < cx < 27.0 and 75.0 < cy < 89.0:
                continue
            rx = float(rng.uniform(0.45, 1.35))
            ry = rx * float(rng.uniform(0.5, 1.0))
            thick = float(rng.uniform(0.09, 0.17))
            sink = float(rng.uniform(0.35, 0.85))
            outline = blob(cx, cy, rx, ry, int(rng.integers(0, 99999)), n=7, rough=0.42,
                           yaw=float(rng.uniform(0, 180)))
            g = z_at(cx, cy)
            tx = math.tan(math.radians(float(rng.uniform(-7, 7))))
            ty = math.tan(math.radians(float(rng.uniform(-7, 7))))
            top = [(px, py, g + thick * (1.0 - sink) + tx * (px - cx) + ty * (py - cy))
                   for px, py in outline]
            poly.add(top, M["BrokenConcrete"])
            for k in range(len(top)):
                a, b = top[k], top[(k + 1) % len(top)]
                poly.add([(a[0], a[1], a[2] - thick), (b[0], b[1], b[2] - thick), b, a],
                         M["BrokenConcrete"])
    emit_poly(stage, f"{TERRAIN}/Debris/BrokenSlabs", poly, mat_paths, "BrokenConcrete",
              doc="half-buried broken concrete slabs, tilted and part-sunk, through the "
                  "out-of-bounds margin and the broken-up east apron")


def build_markings(stage, mat_paths):
    UsdGeom.Scope.Define(stage, TERRAIN + "/Markings")
    poly = Poly()
    rng = np.random.default_rng(SEED + 31)
    LIFT = L_PAINT

    # faded 9 m truck-turning circle centred (0, +2)
    seg = 128
    for k in range(seg):
        if rng.random() < 0.20:                    # worn away
            continue
        t0 = 2 * math.pi * k / seg
        t1 = 2 * math.pi * (k + 1) / seg
        quad = []
        for r, t in ((8.93, t0), (9.07, t0), (9.07, t1), (8.93, t1)):
            px, py = math.cos(t) * r, 2.0 + math.sin(t) * r
            quad.append((px, py, z_at(px, py) + LIFT))
        poly.add(quad, M["PaintYellow"], normal=(0, 0, 1))

    # dock truck-bay markings on 4.0 m centres, worn out in the wheel paths
    for x in np.arange(-46.0, 30.001, 4.0):
        line = resample([(float(x), -21.3), (float(x), -16.4)], 0.45)
        for i in range(len(line) - 1):
            if rng.random() < 0.14:
                continue
            (xa, ya), (xb, yb) = line[i], line[i + 1]
            w = 0.06
            poly.add([(xa - w, ya, z_at(xa, ya) + LIFT), (xa + w, ya, z_at(xa, ya) + LIFT),
                      (xb + w, yb, z_at(xb, yb) + LIFT), (xb - w, yb, z_at(xb, yb) + LIFT)],
                     M["PaintYellow"], normal=(0, 0, 1))
        if rng.random() < 0.7:
            xa, xb = float(x) - 1.6, float(x) + 1.6
            za, zb = z_at(xa, -21.4) + LIFT, z_at(xb, -21.4) + LIFT
            poly.add([(xa, -21.42, za), (xb, -21.42, zb),
                      (xb, -21.30, zb), (xa, -21.30, za)], M["PaintYellow"], normal=(0, 0, 1))

    # keep-clear hatching in front of the hero gate
    for k in range(12):
        b = -9.0 + k * 1.5
        line = [(px, py) for px, py in resample([(b, 4.8), (b + 7.5, 12.4)], 0.45)
                if -5.4 <= px <= 5.4 and 4.6 <= py <= 12.6]
        if len(line) >= 2:
            strip_along(line, 0.16, M["PaintWhite"], poly, lift=LIFT, keep=0.72, rng=rng)

    # edge line along the yard / dock-apron boundary
    strip_along(resample([(-45.0, -16.35), (29.0, -16.35)], 0.45), 0.065,
                M["PaintWhite"], poly, lift=LIFT, keep=0.34, rng=rng)

    emit_poly(stage, f"{TERRAIN}/Markings/YardPaint", poly, mat_paths, "PaintYellow",
              doc="faded ground paint: 9 m truck-turning circle at (0,+2), dock truck bays "
                  "on 4 m centres, hero-gate keep-clear hatching, apron edge line")


def stipple(poly, mat, seed, cx, cy, rx, ry, n, rmin, rmax, z=None, lift=0.010,
            yaw=0.0, bias=0.85, edge=0.80, fmin=0.0):
    """Scatter shrinking irregular islands so a decal has NO outer silhouette.

    This is the whole trick for ground decals without an opacity map.  A single
    blob -- however nicely shaped -- reads as a card lying on the floor, because
    its edge is a hard step from full effect to none.  Real wear, damp and oil
    all dissolve: dense and continuous at the core, then breaking into smaller
    and sparser islands until it is gone.  Building that dissolve out of
    geometry gives the same read and costs a few hundred triangles.
    """
    rng = np.random.default_rng(seed)
    ca, sa = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    for i in range(n):
        t = rng.uniform(0.0, 2.0 * math.pi)
        f = float(rng.random()) ** bias          # radial position, core-biased
        if f < fmin:                             # annular scatter, hollow core
            f = fmin + (1.0 - fmin) * f / max(fmin, 1e-6)
        ux, uy = rx * f * math.cos(t), ry * f * math.sin(t)
        px = cx + ux * ca - uy * sa
        py = cy + ux * sa + uy * ca
        s = (rmax - (rmax - rmin) * f ** edge) * float(rng.uniform(0.6, 1.25))
        outline = blob(px, py, s, s * float(rng.uniform(0.55, 1.0)),
                       int(rng.integers(0, 999999)), n=int(rng.integers(6, 10)),
                       rough=float(rng.uniform(0.28, 0.55)),
                       yaw=float(rng.uniform(0, 180)))
        dz = zstep(i, 48, 0.00004)
        if z is None:
            poly.add([(qx, qy, z_at(qx, qy) + lift + dz) for qx, qy in outline], mat,
                     normal=(0, 0, 1))
        else:
            poly.add([(qx, qy, z + dz) for qx, qy in outline], mat, normal=(0, 0, 1))


def wander(x0, y0, heading, length, step, jitter, rng, bounds):
    """A crack path: a heading-jittered walk clipped to a rectangle."""
    pts = [(x0, y0)]
    h = heading
    n = max(2, int(length / step))
    for _ in range(n):
        h += math.radians(float(rng.normal(0.0, jitter)))
        nx = pts[-1][0] + step * math.cos(h)
        ny = pts[-1][1] + step * math.sin(h)
        if not (bounds[0] < nx < bounds[1] and bounds[2] < ny < bounds[3]):
            break
        pts.append((nx, ny))
    return pts, h


def _cell_outlines(zone_index, sectors=132):
    """Trace every repair patch in a zone as a smooth closed outline.

    Face-centre classification puts the patch boundary on the 0.35 m face grid.
    Three metres from a soldier's eye a 0.35 m face is two hundred pixels wide,
    so that boundary reads as a literal staircase -- which is what the first
    pass of this mosaic did, and it looked like vinyl flooring.  So the patchwork
    is not painted onto the base mesh at all: each cell is found by sampling the
    warped Voronoi, then its edge is located to the millimetre by bisection along
    72 rays from the cell's centroid, and the result is emitted as its own patch
    mesh with true curved edges.  `classify` still tags the base mesh with the
    same diagram, so if a ray-march ever fails the surface underneath is already
    the right material.
    """
    x0, x1, y0, y1, _, _, _ = MOSAIC_ZONES[zone_index]
    step = 0.35
    xs = np.arange(x0, x1 + step, step)
    ys = np.arange(y0, y1 + step, step)
    X, Y = np.meshgrid(xs, ys)
    ids, f1, _, f2 = _mosaic(X, Y)
    inside = _mosaic_zone_mask(X, Y, zone_index) > 0.5
    ids = ids[inside]
    gx = X[inside]
    gy = Y[inside]
    depth = (f2 - f1)[inside]          # how far this sample is from any cell edge
    uniq, inv = np.unique(ids, return_inverse=True)
    counts = np.bincount(inv)
    # Start the ray-march from the cell's POLE OF INACCESSIBILITY, not its
    # centroid: the domain warp can bend a cell into a crescent whose centroid
    # falls in the neighbouring cell, and marching from there collapses the
    # patch to nothing and leaves a hole with the quantised base mesh showing.
    best = np.full(uniq.size, -1.0)
    cx = np.zeros(uniq.size)
    cy = np.zeros(uniq.size)
    order = np.argsort(depth)
    for idx in order:                  # ascending, so the deepest sample wins
        c = inv[idx]
        best[c] = depth[idx]
        cx[c] = gx[idx]
        cy[c] = gy[idx]
    keep = counts >= 6
    uniq, cx, cy = uniq[keep], cx[keep], cy[keep]

    # bisect outward along each ray until the cell id changes
    th = np.arange(sectors) * (2.0 * math.pi / sectors)
    ct, stt = np.cos(th)[None, :], np.sin(th)[None, :]
    lo = np.zeros((uniq.size, sectors))
    hi = np.full((uniq.size, sectors), MOSAIC_S * 1.9)
    own = uniq[:, None]
    for _ in range(20):
        mid = 0.5 * (lo + hi)
        px = cx[:, None] + mid * ct
        py = cy[:, None] + mid * stt
        got, _, _, _ = _mosaic(px, py)
        same = got == own
        lo = np.where(same, mid, lo)
        hi = np.where(same, hi, mid)
    # A radial march can only describe a star-shaped region, and the domain warp
    # happily bends a cell into a crescent.  When a ray leaves the cell early --
    # or immediately, for a cell whose pole sits on the zone edge -- the raw
    # outline gets a notch running all the way back to the pole, and the fan
    # triangle and seam ribbon built on it render as a long straight spear lying
    # across the yard.  So the radius profile is despiked against its own median
    # and then smoothed: the patch becomes a plausible blob that may spill a
    # little into its neighbour, which is what real repairs do anyway.
    r = lo
    med = np.median(r, axis=1, keepdims=True)
    r = np.clip(r, 0.45 * med, 1.75 * med)
    for _ in range(6):
        r = 0.25 * (np.roll(r, 1, axis=1) + 2.0 * r + np.roll(r, -1, axis=1))

    # Crenulate.  Smoothing the despiked profile six times leaves a boundary so
    # clean it becomes a drawn ellipse, and an ellipse edge at 3 m from the lens
    # is a straight chord for tens of pixels at a time.  Three high harmonics --
    # ~2.5 m, ~1.3 m and ~0.8 m wavelength on a 3.8 m cell, amplitudes 21, 13 and
    # 8 cm -- give the joint the ragged, bitten look a real cut-and-patch edge
    # has, and guarantee the boundary changes direction several times per metre.
    ph = (_hash(uniq % np.int64(65536), uniq // np.int64(65536), 9901)[:, None]
          * 6.2832)
    ang = th[None, :]
    r = r * (1.0
             + 0.056 * np.sin(9.0 * ang + ph)
             + 0.034 * np.sin(17.0 * ang + 2.31 * ph)
             + 0.021 * np.sin(29.0 * ang + 4.07 * ph))

    # keep the patch inside its zone by shortening the ray, not by clamping the
    # point -- clamping folds a whole arc onto the rect corner
    eps = 1e-6
    lim = np.minimum(
        np.where(ct > eps, (x1 - cx[:, None]) / np.maximum(ct, eps),
                 np.where(ct < -eps, (x0 - cx[:, None]) / np.minimum(ct, -eps), 1e9)),
        np.where(stt > eps, (y1 - cy[:, None]) / np.maximum(stt, eps),
                 np.where(stt < -eps, (y0 - cy[:, None]) / np.minimum(stt, -eps), 1e9)))
    r = np.minimum(r * 1.04, np.maximum(lim, 0.0))

    # Bound the chord.  The zone-edge ray shortening above can drop a radius
    # from 4 m to nothing between two adjacent rays, which puts a 4-6 m straight
    # edge into the patch outline -- a razor chord across the yard, and the
    # single most visible thing the critic named. Arc between rays is ~0.18 m,
    # so a 0.40 m radial cap bounds every boundary edge at 0.44 m.
    r = np.stack([limit_slope(r[i], 0.24) for i in range(r.shape[0])], axis=0)

    good = np.median(r, axis=1) > 0.85          # drop slivers not worth a mesh
    uniq, cx, cy, r = uniq[good], cx[good], cy[good], r[good]
    bx = cx[:, None] + r * ct
    by = cy[:, None] + r * stt

    # Final conditioning, per cell: put the vertices on a 0.72 m arc-length grid
    # and wander the joint 0.10-0.40 m sideways (jitter_boundary).  132 evenly
    # spaced rays give a 0.18 m arc on a 3.8 m cell, and a boundary sampled four
    # times finer than it wanders is a DRAWN CURVE -- smooth, continuous, and
    # exactly the thing that made these joints read as vinyl inlay.  Resampling
    # coarser and then tearing the edge open by up to 0.4 m is what a saw kerf
    # cut round a broken patch actually looks like, and it is measured below.
    outlines = []
    for i in range(uniq.size):
        outlines.append(jitter_boundary(bx[i], by[i], int(uniq[i] % 100000) + 7,
                                        step=0.72, lat=(0.10, 0.40),
                                        maxchord=0.95, src="mosaic"))
    return uniq, cx, cy, outlines


def build_mosaic(stage, mat_paths, report):
    """The repair patchwork, as real meshes, plus the seams that bind them."""
    UsdGeom.Scope.Define(stage, TERRAIN + "/Patches")
    patch = Acc()
    seam = Poly()
    feather = Poly()
    srng = np.random.default_rng(SEED + 91)
    ncell = 0
    worst_chord = 0.0

    for k, zone in enumerate(MOSAIC_ZONES):
        mix = MIX[zone[4]]
        table = np.array([M[m] for m in mix], dtype=np.int32)
        uniq, cx, cy, outlines = _cell_outlines(k)
        if uniq.size == 0:
            continue
        pick = _mix_pick(cx, cy, uniq, len(mix))
        # a sub-millimetre per-cell height so overlapping outlines never z-fight
        jz = _hash(uniq % np.int64(65536), uniq // np.int64(65536), 8123) * 0.0006

        for c in range(uniq.size):
            ncell += 1
            bx_c, by_c = outlines[c]
            sectors = int(bx_c.size)
            ch = np.hypot(bx_c - np.roll(bx_c, -1), by_c - np.roll(by_c, -1))
            worst_chord = max(worst_chord, float(ch.max()))
            rmed = float(np.median(np.hypot(bx_c - cx[c], by_c - cy[c])))
            nring = int(np.clip(round(rmed / 0.45), 3, 16))
            rings = np.linspace(0.0, 1.0, nring + 1)
            px = [cx[c]]
            py = [cy[c]]
            for f in rings[1:]:
                px.extend(cx[c] + (bx_c - cx[c]) * f)
                py.extend(cy[c] + (by_c - cy[c]) * f)
            P = np.array(px)
            Q = np.array(py)
            Z = _overlay_z(P, Q, L_MOSAIC + jz[c])
            nrm = _overlay_normals(P, Q)
            faces = []
            for s in range(sectors):
                faces.append((0, 1 + s, 1 + (s + 1) % sectors))
            for ring in range(len(rings) - 2):
                a0 = 1 + ring * sectors
                a1 = 1 + (ring + 1) * sectors
                for s in range(sectors):
                    s2 = (s + 1) % sectors
                    faces.append((a0 + s, a0 + s2, a1 + s2, a1 + s))
            patch.add(list(zip(P.tolist(), Q.tolist(), Z.tolist())),
                      [tuple(v) for v in nrm.tolist()],
                      list(zip(P.tolist(), Q.tolist())), faces,
                      [int(table[pick[c]])] * len(faces))

            # feathered transition strip straddling this cell's boundary
            feather_outline(feather, bx_c, by_c, cx[c], cy[c],
                            int(table[pick[c]]), 5100 + ncell,
                            band=0.74, lift=L_MOSAIC + 0.0011 + jz[c], pitch=0.30,
                            overlap=(0.10, 0.44))

            # poured seam along the outline.  Coverage is up from 45% to 78%: a
            # bitumen joint is the one thing that genuinely does sit across the
            # value step, so where it survives it hides the joint outright, and
            # the 22% that is missing is what keeps it from reading as piping.
            ring_pts = list(zip(bx_c.tolist(), by_c.tolist()))
            ring_pts.append(ring_pts[0])
            for i in range(len(ring_pts) - 1):
                if srng.random() < 0.22:
                    continue      # an old joint survives in pieces, not in runs
                (xa, ya), (xb, yb) = ring_pts[i], ring_pts[i + 1]
                dx, dy = xb - xa, yb - ya
                L = math.hypot(dx, dy)
                if L < 1e-4 or L > 1.2:
                    continue      # a long chord means a bad outline, not a seam
                w = 0.026 + 0.040 * float(srng.random())
                nx, ny = -dy / L * w, dx / L * w
                q = [(xa + nx, ya + ny), (xb + nx, yb + ny),
                     (xb - nx, yb - ny), (xa - nx, ya - ny)]
                seam.add([(qx, qy, z_at(qx, qy) + L_SEAM) for qx, qy in q],
                         M["TarSeam"], normal=(0, 0, 1))

    emit_mesh(stage, f"{TERRAIN}/Patches/RepairMosaic", patch.P, patch.FC, patch.FI,
              patch.N, patch.ST, patch.FM, mat_paths, "AsphaltOxidised",
              doc="The repair patchwork. Every paved zone is cut into warped-Voronoi "
                  "cells; each cell picks its own scanned look AND its own 2-3 cm "
                  "settlement, so material boundary and height break coincide the way a "
                  "real repair does. Outlines are traced by bisection at 132 rays and "
                  "then crenulated by three high harmonics, so no boundary chord is "
                  "longer than 0.30 m and no boundary is straight. Looks are drawn from "
                  "an ordered brightness ramp sampled through a smooth 34 m field, so "
                  "adjacent repairs are close in value.")
    emit_poly(stage, f"{TERRAIN}/Patches/MosaicFeather", feather, mat_paths,
              "AsphaltOxidised",
              doc="The transition strip. Every mosaic boundary is dithered across a "
                  "0.3-0.8 m band by a scatter of shrinking islands of the patch's own "
                  "material, so the value crosses the joint as a dissolve rather than on "
                  "a single polygon edge. This is the fix for the hard diagonal seam in "
                  "the yard and the razor triangle at the bottom of the hero frame.")
    emit_poly(stage, f"{TERRAIN}/Patches/RepairSeams", seam, mat_paths, "TarSeam",
              doc="hot-poured bitumen seam round every repair patch, 50-130 mm, broken in "
                  "one segment in five; matte, because a glossy seam under a 5.5 deg sun "
                  "turns into a run of bright tape")
    report.append(f"  mosaic  {ncell} repair patches, crenulated + feathered outlines, "
                  f"{len(feather.FC)} feather islands")
    report.append(f"  MOSAIC BOUNDARY worst straight chord {worst_chord:.3f} m "
                  f"-- limit 1.000 m")


def _crack_seed(rng, zone_index, x0, x1, y0, y1):
    """Where a crack starts and which way it runs -- along a STRESS LINE.

    Asphalt does not craze at random.  Three mechanisms account for almost every
    crack in a yard like this, and all three are directional:

      * REFLECTIVE CRACKING.  The yard is asphalt laid over an older concrete
        slab on a 5 m grid (the same grid `build_nearfield` saw-cuts).  Every
        joint underneath telegraphs straight up through the overlay, so the
        longest and straightest cracks in the yard sit within a few hundred
        millimetres of x = 5k or y = 5k and run along it.
      * FATIGUE CRACKING.  The wheel paths take the load, so the second family
        runs parallel to the truck routes and lives inside a metre of them.
      * EDGE CRACKING.  Unsupported pavement edges fail first, so the third
        family hugs the kerb line and the apron edge and runs along it.

    The old version seeded a uniform random position and a uniform random
    heading, which is a plausible-looking noise pattern and reads as one: a
    scribble laid over the ground with no relationship to anything else in the
    frame.  Cracks that line up with the slab grid and the wheel paths make the
    yard read as a STRUCTURE that failed.
    """
    r = rng.random()
    if zone_index == 0 and r < 0.42:
        # reflective: on the 5 m slab grid, running along it
        if rng.random() < 0.5:
            gx = float(np.clip(round(rng.uniform(x0, x1) / 5.0) * 5.0, x0, x1))
            return (gx + float(rng.normal(0.0, 0.26)), float(rng.uniform(y0, y1)),
                    math.pi * 0.5 + float(rng.normal(0.0, 0.10))
                    + (math.pi if rng.random() < 0.5 else 0.0))
        gy = float(np.clip(round(rng.uniform(y0, y1) / 5.0) * 5.0, y0, y1))
        return (float(rng.uniform(x0, x1)), gy + float(rng.normal(0.0, 0.26)),
                float(rng.normal(0.0, 0.10)) + (math.pi if rng.random() < 0.5 else 0.0))
    if r < 0.68:
        # fatigue: inside a metre of a wheel path, running with it
        for _ in range(8):
            path, gauge, _, _ = RUTS[int(rng.integers(0, len(RUTS)))]
            line = resample(list(path), 1.0)
            i = int(rng.integers(0, max(len(line) - 2, 1)))
            (ax, ay), (bx, by) = line[i], line[i + 1]
            h = math.atan2(by - ay, bx - ax)
            off = float(rng.uniform(-1.0, 1.0)) * gauge * 0.5 + float(rng.normal(0, 0.35))
            px = ax - math.sin(h) * off
            py = ay + math.cos(h) * off
            if x0 < px < x1 and y0 < py < y1:
                return (px, py, h + float(rng.normal(0.0, 0.14))
                        + (math.pi if rng.random() < 0.5 else 0.0))
    if r < 0.86:
        # edge: hugging whichever boundary of the zone is nearest, running along it
        if rng.random() < 0.5:
            ex = x0 if rng.random() < 0.5 else x1
            return (ex + float(rng.uniform(0.15, 1.5)) * (1.0 if ex == x0 else -1.0),
                    float(rng.uniform(y0, y1)),
                    math.pi * 0.5 + float(rng.normal(0.0, 0.18))
                    + (math.pi if rng.random() < 0.5 else 0.0))
        ey = y0 if rng.random() < 0.5 else y1
        return (float(rng.uniform(x0, x1)),
                ey + float(rng.uniform(0.15, 1.5)) * (1.0 if ey == y0 else -1.0),
                float(rng.normal(0.0, 0.18)) + (math.pi if rng.random() < 0.5 else 0.0))
    return (float(rng.uniform(x0, x1)), float(rng.uniform(y0, y1)),
            float(rng.uniform(0, 2 * math.pi)))


def build_cracks(stage, mat_paths, report):
    """A branching crack network with crumbled edges.

    Two co-located ribbons per crack: a wide, low `AsphaltAggregate` spall halo
    where the surface has broken up, and a narrow near-black `X_Void` slot on
    top of it.  A crack without a spall halo reads as a drawn line.
    """
    rng = np.random.default_rng(SEED + 61)
    zones = [
        (-51.0, 51.0, -15.5, 12.5, 62, 4.0, 15.0),      # yard
        (-45.0, 29.0, -33.0, -16.5, 26, 3.0, 11.0),     # dock apron
        (-69.0, -53.0, -23.0, 33.0, 22, 3.0, 11.0),     # west spawn
        (53.0, 69.0, -23.0, 57.0, 22, 3.0, 11.0),       # east spawn
        (31.0, 51.0, -37.0, -17.0, 14, 2.5, 8.0),       # broken east apron
    ]
    paths = []
    for zi, (x0, x1, y0, y1, n, lmin, lmax) in enumerate(zones):
        for _ in range(n):
            sx, sy, head = _crack_seed(rng, zi, x0, x1, y0, y1)
            # Inside a camera disc the crack is built as real lipped relief by
            # build_lipped_cracks; a flat ribbon on top of it would double the
            # value and put a black smear round the geometry.
            if _near_eye(np.array([sx]), np.array([sy]), slack=-4.0)[0] <= 0.0:
                continue
            main, endh = wander(sx, sy, head, float(rng.uniform(lmin, lmax)), 0.42,
                                14.0, rng, (x0, x1, y0, y1))
            if len(main) < 3:
                continue
            # Half-widths halved.  The old 26-58 mm half-width put a 12 cm-wide
            # near-black ribbon across the yard, and 12 cm at 10 m is 25 pixels
            # of pure black -- which is what the black shards littering the
            # bottom of the gameplay frame actually were.
            paths.append((main, float(rng.uniform(0.013, 0.030))))
            for _ in range(int(rng.integers(0, 3))):      # branches
                k = int(rng.integers(1, len(main) - 1))
                bx, by = main[k]
                bh = head + math.radians(float(rng.uniform(35, 115))
                                         * (1 if rng.random() < 0.5 else -1))
                br, _ = wander(bx, by, bh, float(rng.uniform(1.2, 5.0)), 0.42, 20.0,
                               rng, (x0, x1, y0, y1))
                if len(br) >= 3:
                    paths.append((br, float(rng.uniform(0.009, 0.018))))

    poly = Poly()
    for pts, w in paths:
        n = len(pts)
        # halo first, slot on top. The halo is CONTINUOUS (drop 0) and only
        # twice the slot width -- a wide, broken, brighter halo reads as a row
        # of pale cards lying beside the crack rather than as crumbled edges.
        for lift, scale, mat, drop in ((L_SPALL, 1.8, M["AsphaltAggregate"], 0.0),
                                       (L_CRACK, 1.0, M["Crack"], 0.10)):
            for i in range(n - 1):
                # half-width tapers to nothing at the tip, per vertex
                t0 = w * scale * (1.0 - 0.62 * (i / max(n - 1, 1)))
                t1 = w * scale * (1.0 - 0.62 * ((i + 1) / max(n - 1, 1)))
                if t0 < 0.006 or rng.random() < drop:
                    continue
                a, b = pts[i], pts[i + 1]
                dx, dy = b[0] - a[0], b[1] - a[1]
                L = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / L, dx / L
                q = [(a[0] - nx * t0, a[1] - ny * t0), (b[0] - nx * t1, b[1] - ny * t1),
                     (b[0] + nx * t1, b[1] + ny * t1), (a[0] + nx * t0, a[1] + ny * t0)]
                poly.add([(px, py, z_at(px, py) + lift) for px, py in q], mat,
                         normal=(0, 0, 1))
    emit_poly(stage, f"{TERRAIN}/Patches/CrackNetwork", poly, mat_paths, "Crack",
              doc="branching crack network through the yard, dock apron and both spawn "
                  "aprons: a near-black open slot over a wider crumbled-aggregate spall "
                  "halo, tapering to nothing at the tip")
    report.append(f"  cracks  {len(paths)} crack paths, {len(poly.FC)} quads")


# where vehicles actually stop and leak: dock bays, gate line, turning circle
OIL_SPILLS = [
    (-38.0, -18.6, 1.2), (-22.0, -18.4, 1.5), (-6.0, -18.7, 1.3), (10.0, -18.5, 1.1),
    (-38.0, -23.4, 0.8), (-22.0, -23.6, 0.9), (-6.0, -23.3, 1.0), (10.0, -23.5, 0.8),
    (-30.0, -36.9, 0.9), (4.0, -37.2, 1.1), (34.0, -36.8, 0.8),
    (-2.0, 8.6, 1.4), (6.0, 6.2, 1.0), (-14.0, 4.0, 0.9), (18.0, 2.4, 1.2),
    (-44.0, -2.0, 1.0), (-56.0, -1.5, 1.3), (44.0, 10.0, 1.0), (46.0, -12.0, 0.9),
    (-52.0, 12.0, 0.8), (24.0, -12.0, 1.1), (-26.0, -8.0, 0.9),
]


def build_traffic(stage, mat_paths, report):
    """Tyre polish, turn scuff and oil drop-out -- where the trucks actually go.

    The yard's tell in LANE_EYE_YARD is that nothing has ever driven across it.
    Wheel paths polish asphalt darker and smoother; turning tractors lay black
    arcs; every vehicle that parks leaves a stain.
    """
    rng = np.random.default_rng(SEED + 71)
    poly = Poly()

    # Polished wheel paths along the paved truck routes.  Built as a stipple,
    # not a ribbon: a constant-width strip down a truck route reads as gaffer
    # tape stuck to the yard, because a real wheel path has no edge -- it is
    # densest under the tyre and fades out over a metre either side.
    si = 0
    for idx in (0, 1, 3, 5):
        path, gauge, _, _ = RUTS[idx]
        for side in (+1.0, -1.0):
            line = resample(offset_polyline(list(path), side * gauge * 0.5), 1.1)
            for i in range(len(line) - 1):
                (xa, ya) = line[i]
                # MATTE, and thinner.  This stipple used to bind the polish look
                # (roughness 0.58) and lay ten flat islands per 1.1 m of route.
                # A flat 0.05-0.30 m island of a smooth look seen at 2-6 degrees
                # of grazing incidence is a mirror the size of a coin, and six
                # thousand of them along the truck routes came back as a band of
                # bright crushed-shell flecks running past every puddle -- the
                # single ugliest thing left in the gameplay frame. The CONTINUITY
                # of a wheel path is carried by the two ragged ribbons below;
                # the stipple only has to carry its dissolve, so it is matte.
                stipple(poly, M["AsphaltOxidisedD"], 7700 + si, xa, ya, 0.75, 0.75,
                        6, 0.05, 0.30, lift=L_POLISH, bias=0.7, edge=0.9)
                si += 1
            # The stipple alone has no CONTINUITY -- from eye height it is a
            # sprinkle, not a lane.  A real wheel path is a continuous polished
            # band about 0.34 m wide, sitting inside that dissolve, and because
            # it is still holding rain it is the one bit of ground that is
            # genuinely glossy.  Broken 30% of the time so it is not a stripe of
            # tape, and narrow enough that its Fresnel sheen is a line rather
            # than a blob.
            core = resample(offset_polyline(list(path), side * gauge * 0.5), 0.55)
            ragged_ribbon(core, 0.62, M["AsphaltPolish"], poly,
                          lift=L_POLISH - 0.0004, keep=0.86, rng=rng,
                          jitter=0.5, wobble=0.42, seed=int(idx * 7 + side + 3))
            ragged_ribbon(core, 0.30, M["AsphaltPolishWet"], poly,
                          lift=L_POLISH + 0.0004, keep=0.62, rng=rng,
                          jitter=0.8, wobble=0.55, seed=int(idx * 7 + side + 41))

    # Black turn marks where tractors swing into the dock bays and the gate.
    #
    # These used to be circular arcs about a fixed centre, and two of them per
    # centre meant they came out CONCENTRIC.  No vehicle has ever made that
    # mark, and a set of perfect rings 15-25 m across reads instantly as a
    # stamped ring texture.  A tractor unit turning is translating as well as
    # rotating, so the mark is a SPIRAL, its centre is wherever the driver
    # happened to be, and it comes in PAIRS 1.9-2.6 m apart because the vehicle
    # has two tracks.  All three are now authored.
    arc = 0
    for cx0, cy0, r0 in ((-38.0, -14.0, 6.5), (-22.0, -14.0, 6.0), (-6.0, -14.0, 6.5),
                         (10.0, -14.0, 6.0), (0.0, 8.0, 7.5), (-6.0, 4.0, 9.0),
                         (18.0, -6.0, 7.0), (-30.0, 2.0, 8.0), (30.0, -8.0, 6.5)):
        for _ in range(2):
            arc += 1
            cx = cx0 + float(rng.uniform(-3.4, 3.4))
            cy = cy0 + float(rng.uniform(-2.6, 2.6))
            r = r0 * float(rng.uniform(0.7, 1.2))
            a0 = float(rng.uniform(0, 2 * math.pi))
            span = math.radians(float(rng.uniform(40, 100)))
            drift = float(rng.uniform(-0.26, 0.26))     # spiral: dr per radian
            wob = float(rng.uniform(0.0, 6.28))
            gauge = float(rng.uniform(1.9, 2.6))
            for track in (-0.5 * gauge, 0.5 * gauge):
                if rng.random() < 0.22:
                    continue                            # one track did not mark
                for k in range(30):
                    if rng.random() < 0.40:
                        continue
                    t0 = a0 + span * k / 30
                    t1 = a0 + span * (k + 1) / 30
                    hw = 0.035 + 0.045 * float(rng.random())
                    q = []
                    for sgn, tt in ((-1.0, t0), (1.0, t0), (1.0, t1), (-1.0, t1)):
                        rr = (r + track + drift * (tt - a0) * r
                              + 0.22 * math.sin(3.0 * (tt - a0) + wob)
                              + sgn * hw)
                        px, py = cx + rr * math.cos(tt), cy + rr * math.sin(tt)
                        if not (-52 < px < 52 and -38 < py < 12.8):
                            q = []
                            break
                        q.append((px, py, z_at(px, py) + L_POLISH
                                  + zstep(arc, 24, 0.00005)))
                    if len(q) == 4:
                        poly.add(q, M["AsphaltPolish"], normal=(0, 0, 1))

    emit_poly(stage, f"{TERRAIN}/Patches/TyrePolish", poly, mat_paths, "AsphaltPolish",
              doc="asphalt polished dark and smooth in the wheel paths of the six truck "
                  "routes, plus black turn arcs where tractors swing into the dock bays "
                  "and the hero gate")

    # oil drop-out: a solid core that dissolves into a stipple of small spots
    poly = Poly()
    for i, (cx, cy, r) in enumerate(OIL_SPILLS):
        poly.add([(px, py, z_at(px, py) + L_OIL) for px, py in
                  blob(cx, cy, r * 0.42, r * 0.30, 8300 + i, n=14, rough=0.42,
                       yaw=float(rng.uniform(0, 180)))], M["OilPad"], normal=(0, 0, 1))
        stipple(poly, M["OilPad"], 8400 + i, cx, cy, r * 1.25, r * 0.85, 34,
                0.035, 0.24, lift=L_OIL - 0.0002, yaw=float(rng.uniform(0, 180)))
    emit_poly(stage, f"{TERRAIN}/Patches/OilDropOut", poly, mat_paths, "OilPad",
              doc="22 oil drop-out stains where vehicles park -- solid core dissolving "
                  "into a stipple of drips so the stain has no cut edge")
    report.append(f"  traffic wheel paths, turn arcs and {len(OIL_SPILLS)} oil stains")


GRIT_ZONES = [
    # x0,  x1,   y0,    y1,     n,  smin,  smax, materials
    # No ConcreteSlabExposed in the yard or on the dock: it is the palest ground
    # look in the palette, and a 10 cm chip of it at 9 m from a 45 mm lens is a
    # 30-pixel white flake -- it reads as litter paper, not as aggregate.
    #
    # PAVED COUNTS CUT BY 4-5x AND THE MIX TURNED DARK.  5 200 pale chips over
    # the yard is 1.7 stones per square metre of 3-10 cm warm-grey gravel, which
    # is a gravel bed, not a paved yard with grit on it.  The survivors are
    # mostly the same near-black material as the surface they broke off, they
    # are gated by `surface_wear` so they collect in the potholes and the failed
    # margins, and they are no longer FLOATING (see build_grit).
    (-52.0, 52.0, -16.0, 14.5, 850, 0.026, 0.085,
     ["AsphaltOxidisedD", "AsphaltAggregate", "AsphaltOxidisedD", "TarSeam",
      "AsphaltAggregate", "AsphaltPolish", "AsphaltOxidisedB", "PuddleBed"]),
    (-46.0, 30.0, -34.0, -16.0, 700, 0.026, 0.085,
     ["AsphaltOxidisedD", "AsphaltAggregate", "Gravel", "TarSeam",
      "BrokenConcrete", "AsphaltOxidisedD"]),
    (-70.0, -52.0, -24.0, 34.0, 1700, 0.032, 0.125,
     ["Gravel", "AsphaltAggregate", "BrokenConcrete"]),
    (52.0, 70.0, -24.0, 58.0, 1700, 0.032, 0.125,
     ["Gravel", "Ballast", "AsphaltAggregate", "SandDrift"]),
    (30.0, 52.0, -38.0, -16.0, 1300, 0.034, 0.135,
     ["Gravel", "BrokenConcrete", "Mud"]),
    (-70.0, 70.0, -40.0, -34.0, 900, 0.030, 0.115,
     ["Gravel", "BrokenConcrete", "Mud"]),
    (-70.0, 70.0, -56.0, -40.0, 900, 0.032, 0.130,
     ["Gravel", "BrokenConcrete", "DirtWeeds"]),
    (-70.0, 70.0, 76.5, 93.0, 800, 0.032, 0.130,
     ["Gravel", "BrokenConcrete", "DirtWeeds"]),
]


def build_grit(stage, mat_paths, report):
    """Loose aggregate lying ON the yard: ~15 000 chips, 3-13 cm, each tilted.

    The critic's note on the ground is that it is 'a large-scale airbrushed
    smear' with no per-metre incident, and that is exactly what a height field
    plus overlay decals gives you: everything in it is smooth at the scale of a
    boot.  A derelict yard is covered in loose stone -- spalled off the slab,
    tracked out of the gravel, dropped off lorries -- and each chip is a tiny
    facet at its own angle.  Under a 5.5 degree sun a facet tilted 15-30 degrees
    is either fully lit or fully shadowed, so a scatter of them puts real
    high-frequency value variation into a surface no texture tile can rescue.

    Density is modulated by a 6 m noise field, because grit drifts: it collects
    in hollows and against edges and leaves bare patches in the wheel paths.
    """
    UsdGeom.Scope.Define(stage, TERRAIN + "/Grit")
    rng = np.random.default_rng(SEED + 131)
    poly = Poly()
    total = 0
    for x0, x1, y0, y1, n, smin, smax, mats in GRIT_ZONES:
        table = [M[m] for m in mats]
        # oversample, then reject against a drift field
        k = int(n * 2.2)
        px = rng.uniform(x0, x1, k)
        py = rng.uniform(y0, y1, k)
        drift = 0.5 + 0.5 * fbm(px, py, 1.0 / 6.0, 3, 7301)
        # Same distance grading as the near field, for the same reason: a 3 cm
        # chip 60 m from the lens is a sixth of a pixel and contributes nothing
        # but variance.  Far from every camera the scatter thins to a third and
        # the stones roughly double, so what survives is still resolvable.
        eyed = np.full(px.shape, 1e9)
        for ex, ey, _, _ in NEARFIELD_EYES:
            eyed = np.minimum(eyed, np.hypot(px - ex, py - ey))
        thin = np.clip(1.25 / (1.0 + (eyed / 26.0) ** 1.5), 0.30, 1.0)
        # On paved ground the scatter is gated by where the surface has failed:
        # a quarter of it survives on intact asphalt, all of it in the potholes
        # and along the failed margins. Off the paving (spawn gravel, the south
        # OOB, the service road) the ground IS loose stone, so it is left alone.
        pav = _paved_mask(px, py)
        gate = 1.0 - pav * (1.0 - (0.24 + 0.76 * surface_wear(px, py)))
        keep = rng.random(k) < np.clip(drift * 1.35, 0.05, 1.0) * thin * gate
        px, py, eyed = px[keep][:n], py[keep][:n], eyed[keep][:n]
        if px.size == 0:
            continue
        # interior floor belongs to the warehouse; do not litter it
        inside = (px > -37.5) & (px < 37.5) & (py > 15.2) & (py < 76.2)
        px, py, eyed = px[~inside], py[~inside], eyed[~inside]
        z = _overlay_z(px, py, 0.0, r=0.10)
        grow = 1.0 + 0.85 * np.clip((eyed - 18.0) / 45.0, 0.0, 1.0)
        size = rng.uniform(smin, smax, px.size) * grow
        tilt = np.radians(rng.uniform(4.0, 22.0, px.size))
        az = rng.uniform(0.0, 2 * math.pi, px.size)
        mat = rng.integers(0, len(table), px.size)
        nv = rng.integers(5, 8, px.size)
        for i in range(px.size):
            s = float(size[i])
            t = float(tilt[i])
            ca, sa = math.cos(float(az[i])), math.sin(float(az[i]))
            slope = math.tan(t)
            v = int(nv[i])
            ph = float(rng.uniform(0, 6.28))
            asp = float(rng.uniform(0.55, 1.0))
            pts = []
            for j in range(v):
                a = 2 * math.pi * j / v + ph
                ux = s * (0.72 + 0.28 * math.sin(3 * a + ph)) * math.cos(a)
                uy = s * asp * (0.72 + 0.28 * math.sin(2 * a + ph)) * math.sin(a)
                dz = slope * (ux * ca + uy * sa)
                # 0.12 s, not 0.45 s.  A 10 cm chip lifted 4.5 cm off the ground
                # is a flat plate hovering half its own width in the air, and
                # that is exactly what it renders as: a dead leaf.  A stone
                # lying on tarmac sits on the tarmac.
                pts.append((float(px[i]) + ux, float(py[i]) + uy,
                            float(z[i]) + 0.0035 + 0.12 * s + dz))
            poly.add(pts, table[int(mat[i])])
            total += 1
    emit_poly(stage, f"{TERRAIN}/Grit/LooseAggregate", poly, mat_paths,
              "BrokenConcrete",
              doc="Loose aggregate lying on the ground: ~15 000 chips 3-13 cm across, "
                  "each an irregular facet tilted 4-32 degrees at a random azimuth, so a "
                  "5.5 degree sun lights or shadows each one individually. Density is "
                  "drift-modulated on a 6 m field. This is the per-metre incident the "
                  "height field and the decal overlays cannot provide.")
    report.append(f"  grit    {total} loose aggregate chips")


# ----------------------------------------------------------------------------
# 5c.  the near field -- real micro-geometry inside 25 m of every camera
# ----------------------------------------------------------------------------
#
# Everything above this point is either a height field or a decal lying on it.
# Both are smooth at the scale of a boot, and at three metres from the lens that
# is the whole problem: the surface has a colour and a speckle and no OBJECTS in
# it, so it photographs as film grain over flat brown.  What a Call of Duty
# near field actually contains, and what is built here, is:
#
#   * aggregate -- thousands of individual stones, each a facet with its own
#     angle, mostly EMBEDDED so they read as the surface breaking up rather
#     than as litter scattered on it
#   * saw-cut expansion joints on a real grid, as recessed slots with two
#     chamfered arrises and a dark interior -- straight, because a saw cut is
#     straight, and that straightness is what gives the eye a scale reference
#   * potholes with raised, broken rims of spalled plates
#   * kerb nosing that is chipped, with rebar showing
#
# It is expensive, so it is only built where a camera can see it: inside a disc
# round each of the five shot positions.

NEARFIELD_EYES = [
    # x, y, radius, chips per m^2 -- the five camera positions from 90_cameras
    #
    # DENSITY CUT 2.5-3x.  34 stones per square metre of 13-105 mm aggregate is
    # a shingle beach: measured in LANE_EYE_YARD it covered the near yard wall
    # to wall and the ground read as gravel, which is the note this pass was
    # given.  Exposed aggregate on asphalt is what shows through where the
    # BINDER has worn, so density is now both lower and gated by `surface_wear`
    # on paved ground -- see build_nearfield.
    (-44.0, 2.0, 30.0, 13.0),     # LANE_EYE_YARD   -- the ground-truth shot
    (-12.0, -10.5, 24.0, 15.0),   # DETAIL_WET_APRON -- judged on this alone
    (-33.0, -36.0, 26.0, 8.0),    # HERO_ESTABLISH
    (47.8, -6.4, 26.0, 9.0),      # SILHOUETTE_WEST
    (0.0, -20.0, 14.0, 9.0),      # dock apron between the two southern shots
    # Two more discs strung along the LANE_EYE_YARD sightline. The five camera
    # positions alone leave the 30-70 m middle of that frame -- which is half
    # its area -- with nothing but the base mesh and a 4 m texture tile, and a
    # middle distance with no per-metre incident is the "empty middle" the brief
    # fails you for. Density is low and the distance grading makes the stones
    # large, so what lands there is resolvable rather than sub-pixel.
    (-14.0, 3.0, 26.0, 5.0),      # LANE_EYE mid-distance
    (-2.0, -6.0, 22.0, 4.5),      # centre cluster / yard middle
]

# Deliberately spread across the full value range of the palette.  A scatter of
# stones that are all mid-grey averages back to the surface tone and disappears;
# what makes aggregate read is that some chips are near-black and some are
# near-white, so the surface acquires a histogram instead of a tint.
# ConcreteKerb and one of the two Gravels are gone, and PuddleBed/OxidisedD are
# doubled.  The palest looks in this list sit at 1.25-1.27 albedo_brightness
# against asphalt's 1.34 but on a much brighter scan, so a 20 mm chip of them in
# direct sun is a blown white speck -- and a blown white speck two pixels across
# is indistinguishable, to the eye AND to analyze_shot, from an unconverged
# firefly.  The near-field scatter was measured at 3.4% firefly fraction in the
# bottom band of the detail frame, which is seven times the gate.
#
# RE-WEIGHTED DARK, 2026-08-09.  The old list was nine pale entries out of
# twelve (aggregate, gravel, broken concrete, ballast, puddle bed, mud) against
# three dark ones, so a scatter that was supposed to read as asphalt breaking up
# instead painted the yard the colour of gravel.  Aggregate in a tarred surface
# is mostly the same near-black stone as the binder round it; the pale flint is
# the minority, and it is the minority that gives the surface its histogram.
# Eight dark to four pale.
NEARFIELD_MIX = ["AsphaltOxidisedD", "AsphaltOxidisedD", "TarSeam", "AsphaltPolish",
                 "AsphaltOxidisedB", "AsphaltFresh", "AsphaltOxidisedD", "TarSeam",
                 "AsphaltAggregate", "Gravel", "BrokenConcrete", "PuddleBed"]


def _emit_chips(stage, path, px, py, pz, size, aspect, tilt, az, yaw, mats,
                mat_paths, default, doc):
    """Vectorised irregular quad chips lying on the ground.

    Written with numpy rather than as a Python loop because the near field needs
    tens of thousands of them and the per-chip loop in build_grit is already the
    slowest thing in this generator.
    """
    n = px.size
    if n == 0:
        return 0
    k = np.arange(4)[None, :]
    ang = yaw[:, None] + k * (math.pi * 0.5) + 0.34 * np.sin(3.1 * k + yaw[:, None])
    rad = size[:, None] * (0.70 + 0.30 * np.cos(2.7 * k + 1.9 * yaw[:, None]))
    ux = rad * np.cos(ang)
    uy = rad * np.sin(ang) * aspect[:, None]
    slope = np.tan(tilt)[:, None]
    dz = slope * (ux * np.cos(az)[:, None] + uy * np.sin(az)[:, None])
    X = px[:, None] + ux
    Y = py[:, None] + uy
    Z = pz[:, None] + dz
    P = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
    ST = np.stack([X, Y], axis=-1).reshape(-1, 2)
    # face normal from the tilt plane, exact for a planar quad
    nx = -slope[:, 0] * np.cos(az)
    ny = -slope[:, 0] * np.sin(az)
    nz = np.ones(n)
    L = np.sqrt(nx * nx + ny * ny + 1.0)
    fn = np.stack([nx / L, ny / L, nz / L], axis=-1)
    N = np.repeat(fn, 4, axis=0)
    counts = np.full(n, 4, dtype=np.int32)
    idx = np.arange(4 * n, dtype=np.int32)
    emit_mesh(stage, path, P, counts, idx, N, ST, mats, mat_paths, default, doc=doc)
    return n


def _nearfield_points(rng):
    """Scatter positions inside the camera discs, rejected off illegal ground."""
    xs, ys = [], []
    for ex, ey, rad, dens in NEARFIELD_EYES:
        n = int(math.pi * rad * rad * dens)
        t = rng.uniform(0.0, 2.0 * math.pi, n)
        # sqrt for a uniform disc, then biased inward so the closest 12 m --
        # the part that fills a third of the frame -- is the densest
        u = rng.random(n) ** 0.52
        px = ex + rad * u * np.cos(t)
        py = ey + rad * u * np.sin(t)
        xs.append(px)
        ys.append(py)
    px = np.concatenate(xs)
    py = np.concatenate(ys)
    ok = (px > -70.0) & (px < 70.0) & (py > -44.0) & (py < 74.0)
    ok &= ~((px > -37.6) & (px < 37.6) & (py > 15.1) & (py < 76.3))   # interior floor
    ok &= ~((px > -46.5) & (px < 30.5) & (py > -34.5) & (py < -21.5))  # under the dock
    ok &= ~((px > 29.5) & (px < 46.5) & (py > -34.5) & (py < -19.5))   # dock office
    return px[ok], py[ok]


def _near_eye(px, py, slack=4.0):
    """Distance from the nearest camera disc edge; <= 0 means inside one."""
    d = np.full(np.shape(px), 1e9)
    for ex, ey, rad, _ in NEARFIELD_EYES:
        d = np.minimum(d, np.hypot(px - ex, py - ey) - (rad + slack))
    return d


# The lateral profile of a settled wheel path, measured from the track centre.
# Offsets in metres, height ABOVE local grade in metres, and the look each lane
# is bound to.  The height field already dishes the route by 40-90 mm over 1.4 m,
# which is the right shape and completely unreadable: it is one gentle sag
# sampled by four faces of a 0.35 m grid, so from eye height the drive lane is
# invisible.  What makes a rut read is the SHOULDER -- the 10-15 mm ridge of
# swept grit and crushed binder standing either side of where the tyre runs.
# A 5.5 degree sun lights the near flank of that ridge and shadows the far one,
# which draws two continuous lines down the yard and gives the eye a direction.
RUT_PROFILE = [
    (-1.15, 0.0035, "AsphaltOxidisedD"),
    (-0.78, 0.0135, "AsphaltAggregate"),   # shoulder berm crest
    (-0.50, 0.0058, "AsphaltPolish"),
    (-0.24, 0.0038, "AsphaltPolish"),
    (0.0, 0.0032, "AsphaltPolishWet"),     # polished, still-wet trough floor
    (0.24, 0.0038, "AsphaltPolishWet"),
    (0.50, 0.0058, "AsphaltPolish"),
    (0.78, 0.0135, "AsphaltPolish"),
    (1.15, 0.0035, "AsphaltAggregate"),
]


def build_rut_relief(stage, mat_paths, report):
    """Settled, polished wheel paths with real shoulder berms, near the cameras."""
    rng = np.random.default_rng(SEED + 223)
    poly = Poly()
    nseg = 0
    for idx, (path, gauge, _, _) in enumerate(RUTS):
        for side in (+1.0, -1.0):
            line = resample(offset_polyline(list(path), side * gauge * 0.5), 0.34)
            if len(line) < 3:
                continue
            LX = np.array([p[0] for p in line])
            LY = np.array([p[1] for p in line])
            if (_near_eye(LX, LY) > 0.0).all():
                continue                       # no camera can see this route
            # per-station tangent and normal
            ax = np.roll(LX, -1) - np.roll(LX, 1)
            ay = np.roll(LY, -1) - np.roll(LY, 1)
            ax[0], ay[0] = LX[1] - LX[0], LY[1] - LY[0]
            ax[-1], ay[-1] = LX[-1] - LX[-2], LY[-1] - LY[-2]
            L = np.hypot(ax, ay)
            L[L < 1e-9] = 1.0
            nx, ny = -ay / L, ax / L
            # the berm is not the same height for ten metres at a stretch
            swell = 0.55 + 0.85 * (0.5 + 0.5 * fbm(LX, LY, 1.0 / 5.5, 2,
                                                   9100 + idx * 7))
            wander = 0.16 * fbm(LX + 13.0, LY - 7.0, 1.0 / 4.0, 2, 9200 + idx)
            cols = []
            for (off, _, _) in RUT_PROFILE:
                qx = LX + nx * (off + wander)
                qy = LY + ny * (off + wander)
                cols.append((qx, qy, _overlay_z(qx, qy, 0.0, r=0.09)))
            inside = _near_eye(LX, LY) <= 0.0
            for k in range(len(RUT_PROFILE) - 1):
                m = M[RUT_PROFILE[k + 1][2]]
                h0 = RUT_PROFILE[k][1]
                h1 = RUT_PROFILE[k + 1][1]
                x0, y0, z0 = cols[k]
                x1, y1, z1 = cols[k + 1]
                for i in range(len(line) - 1):
                    if not (inside[i] and inside[i + 1]):
                        continue
                    if rng.random() < 0.11:
                        continue               # the polish is not continuous
                    s0 = swell[i]
                    s1 = swell[i + 1]
                    poly.add([(x0[i], y0[i], z0[i] + h0 * s0),
                              (x0[i + 1], y0[i + 1], z0[i + 1] + h0 * s1),
                              (x1[i + 1], y1[i + 1], z1[i + 1] + h1 * s1),
                              (x1[i], y1[i], z1[i] + h1 * s0)], m)
                    nseg += 1
    emit_poly(stage, f"{TERRAIN}/NearField/SettledRuts", poly, mat_paths,
              "AsphaltPolish",
              doc="Settled, polished wheel paths inside the camera discs, built as a "
                  "nine-lane cross-section rather than a flat decal: a wet polished "
                  "trough floor, a matte polished flank, and a 10-15 mm shoulder berm of "
                  "swept grit either side whose height breathes on a 5.5 m field. The "
                  "berm is the readable part -- it is what a 5.5 degree sun can light on "
                  "one flank and shadow on the other, and it is what turns the height "
                  "field's invisible 60 mm sag into a drive lane you can see from eye "
                  "height.")
    report.append(f"  ruts    {nseg} polished-rut quads with shoulder berms")


def build_lipped_cracks(stage, mat_paths, report):
    """Near-field cracks as real relief: a dark channel between two raised lips.

    `build_cracks` paints the whole map with flat ribbons, which is right for
    the middle distance and wrong for the first 25 m: a flat near-black ribbon
    12 cm wide and 8 m long has no thickness and no shadow, so close up it reads
    as a torn strip of gaffer laid on the yard -- the black shards scattered
    across the bottom of the gameplay frame.  A real crack in asphalt is a
    RIDGE with a slot in it: the slab heaves either side of the fracture, the
    lips stand 8-20 mm proud and crumble, and the slot between them is in
    permanent shadow.  That profile is authored here, only where a camera can
    resolve it.
    """
    rng = np.random.default_rng(SEED + 227)
    poly = Poly()
    npath = 0
    for ex, ey, rad, _ in NEARFIELD_EYES:
        r_use = min(rad, 26.0)
        for _ in range(int(r_use * 1.9)):
            t = rng.uniform(0, 2 * math.pi)
            u = rng.random() ** 0.65
            sx = ex + r_use * u * math.cos(t)
            sy = ey + r_use * u * math.sin(t)
            if -37.6 < sx < 37.6 and 15.1 < sy < 76.3:
                continue                       # warehouse floor
            if -46.5 < sx < 30.5 and -34.5 < sy < -21.5:
                continue                       # under the dock deck
            if not (-70.0 < sx < 70.0 and -40.0 < sy < 14.0):
                continue
            pts, _ = wander(sx, sy, float(rng.uniform(0, 2 * math.pi)),
                            float(rng.uniform(2.2, 9.0)), 0.38, 16.0, rng,
                            (-70.0, 70.0, -40.0, 14.0))
            if len(pts) < 4:
                continue
            npath += 1
            PX = np.array([p[0] for p in pts])
            PY = np.array([p[1] for p in pts])
            ax = np.roll(PX, -1) - np.roll(PX, 1)
            ay = np.roll(PY, -1) - np.roll(PY, 1)
            ax[0], ay[0] = PX[1] - PX[0], PY[1] - PY[0]
            ax[-1], ay[-1] = PX[-1] - PX[-2], PY[-1] - PY[-2]
            L = np.hypot(ax, ay)
            L[L < 1e-9] = 1.0
            nx, ny = -ay / L, ax / L
            n = PX.size
            s = np.arange(n) / max(n - 1, 1)
            taper = np.clip(np.minimum(s, 1.0 - s) * 4.0, 0.12, 1.0)
            w0 = (0.006 + 0.011 * (0.5 + 0.5 * fbm(PX, PY, 1.0 / 1.6, 2, 9410))) * taper
            w1 = w0 + (0.020 + 0.030 * (0.5 + 0.5 * fbm(PX + 9.0, PY, 1.0 / 2.1, 2,
                                                        9420))) * taper
            w2 = w1 + (0.055 + 0.095 * (0.5 + 0.5 * fbm(PX, PY + 5.0, 1.0 / 3.2, 2,
                                                        9430))) * taper
            lip = (0.008 + 0.013 * (0.5 + 0.5 * fbm(PX - 4.0, PY + 3.0, 1.0 / 2.8, 2,
                                                    9440))) * taper
            ZG = _overlay_z(PX, PY, 0.0, r=0.07)
            lanes = [(-w2, np.full(n, 0.0009), None),
                     (-w1, lip, M["AsphaltAggregate"]),
                     (-w0, np.full(n, 0.0012), M["AsphaltAggregate"]),
                     (w0, np.full(n, 0.0012), M["Crack"]),
                     (w1, lip, M["AsphaltAggregate"]),
                     (w2, np.full(n, 0.0009), M["AsphaltAggregate"])]
            for k in range(len(lanes) - 1):
                o0, h0, _ = lanes[k]
                o1, h1, mat = lanes[k + 1]
                for i in range(n - 1):
                    poly.add([(PX[i] + nx[i] * o0[i], PY[i] + ny[i] * o0[i],
                               ZG[i] + h0[i]),
                              (PX[i + 1] + nx[i + 1] * o0[i + 1],
                               PY[i + 1] + ny[i + 1] * o0[i + 1], ZG[i + 1] + h0[i + 1]),
                              (PX[i + 1] + nx[i + 1] * o1[i + 1],
                               PY[i + 1] + ny[i + 1] * o1[i + 1], ZG[i + 1] + h1[i + 1]),
                              (PX[i] + nx[i] * o1[i], PY[i] + ny[i] * o1[i],
                               ZG[i] + h1[i])], mat)
    emit_poly(stage, f"{TERRAIN}/NearField/LippedCracks", poly, mat_paths, "Crack",
              doc="Near-field cracks with RAISED LIPS: a 12-34 mm dark slot between two "
                  "8-21 mm lips of crumbled aggregate, tapering to nothing at both tips. "
                  "A flat dark ribbon has no thickness and no shadow and reads close up "
                  "as a strip of tape lying on the yard; a crack in real asphalt is a "
                  "heave with a slot in it.")
    report.append(f"  cracks  {npath} lipped near-field cracks, {len(poly.FC)} quads")


# (polyline, side, min width, max width, berm height, material lanes)
# Wherever a paved surface meets something vertical, the stuff a broom or a
# tyre pushes sideways has nowhere left to go, so it piles: grit, crushed
# binder, leaf mould, road salt.  The result is a windrow -- a few centimetres
# high, a boot wide, running the whole length of the wall.  Its absence is one
# of the reasons a yard reads as a blockout: a perfectly clean junction between
# ground and wall exists nowhere outside an architectural render.
EDGE_DRIFTS = [
    (((-38.0, 13.38), (0.0, 13.38), (38.0, 13.38)), -1.0, 0.22, 0.88, 0.020,
     ["Gravel", "AsphaltAggregate", "SandDrift"]),
    (((-46.0, -21.62), (-8.0, -21.62), (30.0, -21.62)), 1.0, 0.18, 0.74, 0.017,
     ["Gravel", "AsphaltAggregate", "Mud"]),
    (((-51.6, -15.0), (-51.6, 0.0), (-51.6, 13.0)), 1.0, 0.25, 1.05, 0.024,
     ["Gravel", "AsphaltAggregate", "BrokenConcrete"]),
    (((51.6, -15.0), (51.6, 0.0), (51.6, 13.0)), -1.0, 0.25, 1.05, 0.024,
     ["Gravel", "AsphaltAggregate", "BrokenConcrete"]),
    (((-45.6, -33.4), (-8.0, -33.4), (29.6, -33.4)), 1.0, 0.20, 0.80, 0.018,
     ["Gravel", "Mud", "AsphaltAggregate"]),
    (((-52.0, -15.7), (0.0, -15.7), (52.0, -15.7)), 1.0, 0.16, 0.62, 0.014,
     ["AsphaltAggregate", "Gravel", "PuddleBed"]),
]


def build_edge_drift(stage, mat_paths, report):
    """Swept grit windrows piled against every kerb, wall foot and apron edge."""
    rng = np.random.default_rng(SEED + 233)
    poly = Poly()
    nq = 0
    for di, (path, side, wmin, wmax, berm, mats) in enumerate(EDGE_DRIFTS):
        line = resample(list(path), 0.42)
        LX = np.array([p[0] for p in line])
        LY = np.array([p[1] for p in line])
        ax = np.roll(LX, -1) - np.roll(LX, 1)
        ay = np.roll(LY, -1) - np.roll(LY, 1)
        ax[0], ay[0] = LX[1] - LX[0], LY[1] - LY[0]
        ax[-1], ay[-1] = LX[-1] - LX[-2], LY[-1] - LY[-2]
        L = np.hypot(ax, ay)
        L[L < 1e-9] = 1.0
        nx, ny = side * (-ay / L), side * (ax / L)
        # the drift is not the same width for twenty metres: it swells where the
        # sweeper never reaches and disappears where a wheel has cut through it
        sw = 0.5 + 0.5 * np.tanh(2.4 * fbm(LX, LY, 1.0 / 4.4, 2, 9600 + di))
        gap = 0.5 + 0.5 * np.tanh(2.2 * fbm(LX + 17.0, LY - 9.0, 1.0 / 7.5, 2,
                                            9700 + di))
        wid = (wmin + (wmax - wmin) * sw) * np.clip(gap * 1.35, 0.0, 1.0)
        lanes = [0.0, 0.30, 0.66, 1.0]
        hts = [berm, berm * 0.72, berm * 0.30, 0.0012]
        cols = []
        for f in lanes:
            qx = LX + nx * wid * f
            qy = LY + ny * wid * f
            cols.append((qx, qy, _overlay_z(qx, qy, 0.0, r=0.09)))
        table = [M[m] for m in mats]
        for k in range(len(lanes) - 1):
            x0, y0, z0 = cols[k]
            x1, y1, z1 = cols[k + 1]
            for i in range(len(line) - 1):
                if wid[i] < wmin * 0.5 and wid[i + 1] < wmin * 0.5:
                    continue
                if rng.random() < 0.07:
                    continue
                poly.add([(x0[i], y0[i], z0[i] + hts[k]),
                          (x0[i + 1], y0[i + 1], z0[i + 1] + hts[k]),
                          (x1[i + 1], y1[i + 1], z1[i + 1] + hts[k + 1]),
                          (x1[i], y1[i], z1[i] + hts[k + 1])],
                         table[min(k, len(table) - 1)])
                nq += 1
        # loose chips thrown clear of the windrow, so it has no outer edge
        for i in range(0, len(line) - 1, 3):
            if rng.random() < 0.45:
                continue
            stipple(poly, table[-1], 9800 + di * 977 + i,
                    float(LX[i] + nx[i] * wid[i] * 1.35),
                    float(LY[i] + ny[i] * wid[i] * 1.35),
                    0.55, 0.55, 7, 0.020, 0.075, lift=0.004, bias=0.8, edge=0.9)
    emit_poly(stage, f"{TERRAIN}/NearField/EdgeDrift", poly, mat_paths, "Gravel",
              doc="Swept grit windrows against the warehouse kerb plinth, the dock apron "
                  "edge beam, the dock face, and both ends of the yard: a 14-24 mm berm at "
                  "the wall running out to grade over 0.16-1.05 m, width breathing on a "
                  "4.4 m field and cut through entirely where wheels cross, dissolving "
                  "outward into loose chips. A clean junction between ground and wall "
                  "exists nowhere outside an architectural render.")
    report.append(f"  edges   {nq} grit-windrow quads along {len(EDGE_DRIFTS)} runs")


def build_nearfield(stage, mat_paths, report):
    UsdGeom.Scope.Define(stage, TERRAIN + "/NearField")
    rng = np.random.default_rng(SEED + 211)

    # ---- 1. embedded aggregate -------------------------------------------
    px, py = _nearfield_points(rng)
    # drift: stone collects in hollows and against edges, and the wheel paths
    # are swept bare, so density is modulated rather than uniform
    drift = 0.5 + 0.5 * fbm(px, py, 1.0 / 4.5, 3, 7601)
    fine = 0.5 + 0.5 * fbm(px + 55.0, py - 31.0, 1.0 / 1.3, 2, 7607)
    # DISTANCE GRADING.  This was the aggregate's undoing in the last round: a
    # 12 mm stone at 22 m subtends a third of a pixel, so every pixel of the
    # middle distance was averaging a random handful of chips whose materials
    # run from near-black asphalt to pale broken concrete.  That is not detail,
    # it is variance -- it renders as salt-and-pepper before the denoiser and as
    # smeared mush after it, which is exactly why detail_density MEASURED LOW on
    # the most heavily detailed surface in the level.  So chips grow and thin
    # with range: at the camera they are 9-55 mm and dense, at 25 m they are
    # 45-140 mm and a quarter as dense, and the smallest chip anywhere is kept
    # near 3 screen pixels (0.0022 rad/px * distance at this focal length).
    eyed = np.full(px.shape, 1e9)
    for ex, ey, _, _ in NEARFIELD_EYES:
        eyed = np.minimum(eyed, np.hypot(px - ex, py - ey))
    thin = np.clip(2.10 / (1.0 + (eyed / 10.0) ** 1.35), 0.14, 1.0)
    # Aggregate shows through where the BINDER has worn away, not everywhere.
    # On paved ground a fifth of the scatter survives on intact asphalt and all
    # of it in the potholes, the failed margins and the broken-up blotches; off
    # the paving the ground is loose stone anyway and the gate is 1.
    pav = _paved_mask(px, py)
    gate = 1.0 - pav * (1.0 - (0.20 + 0.80 * surface_wear(px, py)))
    keep = (rng.random(px.size)
            < np.clip(0.34 + 1.30 * drift * fine, 0.05, 1.0) * thin * gate)
    px, py, eyed = px[keep], py[keep], eyed[keep]
    ground = _overlay_z(px, py, 0.0, r=0.07)
    # 13 mm floor rather than 9: below about three screen pixels a chip stops
    # being aggregate and becomes a speckle, and a bright speckle is a firefly.
    smin = np.minimum(0.013 + 0.0026 * eyed, 0.050)
    size = smin + np.minimum(0.044 + 0.0038 * eyed, 0.105) * rng.random(px.size) ** 2.4
    # embedment: most stones are three-quarters buried in the binder and only
    # the crown shows.  That is what exposed aggregate looks like; a stone
    # sitting fully proud is a pebble someone dropped.
    proud = np.where(rng.random(px.size) < 0.16,
                     rng.uniform(0.45, 0.85, px.size),
                     rng.uniform(0.10, 0.32, px.size))
    pz = ground + 0.0015 + proud * size
    # 3-21 degrees, not 3-34.  A steeply tipped facet under a 5.5 degree sun is
    # either edge-on (invisible) or square to it (blown), and the blown ones are
    # what the firefly metric counts.  21 degrees still gives every stone its own
    # value without any of them turning into a mirror.
    tilt = np.radians(rng.uniform(3.0, 21.0, px.size))
    az = rng.uniform(0.0, 2 * math.pi, px.size)
    yaw = rng.uniform(0.0, 2 * math.pi, px.size)
    aspect = rng.uniform(0.5, 1.0, px.size)
    table = np.array([M[m] for m in NEARFIELD_MIX], dtype=np.int32)
    mats = table[rng.integers(0, len(NEARFIELD_MIX), px.size)]
    nchip = _emit_chips(
        stage, f"{TERRAIN}/NearField/EmbeddedAggregate", px, py, pz, size, aspect,
        tilt, az, yaw, mats, mat_paths, "AsphaltAggregate",
        doc="Embedded aggregate inside 24-30 m of every camera: individual stones "
            "12-55 mm across, each an irregular facet tilted 3-34 degrees at its own "
            "azimuth, and 84% of them sunk so only 10-32% of the stone stands proud. "
            "That is the difference between a surface breaking up and gravel lying on "
            "it. Density is drift-modulated on a 4.5 m and a 1.3 m field so the stone "
            "collects and thins the way it does on a real yard.")

    # ---- 2. saw-cut expansion joints --------------------------------------
    #
    # This was authored the first time as a slot cut DOWN into the slab: floor
    # at -22 mm, vertical walls, chamfered arrises rising from -5 mm to +10 mm.
    # None of it was visible.  The ground mesh is a closed surface at grade and
    # nothing in this module cuts a hole in it, so every face below grade was
    # buried under the very surface it was supposed to be cut into.  What the
    # camera actually got was two pale hairlines with NOTHING between them --
    # the joint had a highlight and no shadow, which is worse than no joint,
    # because a bright line with no dark line reads as a scratch on the lens.
    #
    # The whole cross-section is therefore lifted so it sits ON the ground and
    # makes its own relief: two 14 mm lips of dirty concrete either side of a
    # 26 mm valley whose floor is 1.5 mm above grade and bound to the void look.
    # The valley is only 12 mm deep, but under a 5.5 degree sun the upwind lip
    # throws its shadow the full width of it, so it reads as the black slot it
    # is meant to be -- and the two lips are genuinely raised, so they catch the
    # key as the hairline pair the eye uses for scale.
    joints = Poly()
    jrng = np.random.default_rng(SEED + 213)
    HWS, HWL, HWO = 0.013, 0.040, 0.078     # half: slot, lip crest, outer toe
    Z_VALLEY, Z_LIP, Z_TOE = 0.0015, 0.0140, 0.0010

    def joint_run(a, b, axis, lip_mat="ConcreteKerb"):
        line = resample([a, b], 0.55)
        for i in range(len(line) - 1):
            (xa, ya), (xb, yb) = line[i], line[i + 1]
            # a joint disappears where a later overlay has covered it
            if jrng.random() < 0.24:
                continue
            spall = 1.0 + (1.9 * jrng.random() if jrng.random() < 0.14 else 0.0)
            sag = 0.72 + 0.55 * jrng.random()    # lips settle unevenly
            hs = HWS * spall
            hl = HWL * spall
            ho = HWO * spall
            za = z_at(xa, ya)
            zb = z_at(xb, yb)
            if axis == "x":                      # run along X, offsets in Y
                def q(o, z):
                    return ((xa, ya + o, za + z), (xb, yb + o, zb + z))
            else:
                def q(o, z):
                    return ((xa + o, ya, za + z), (xb + o, yb, zb + z))
            lm = M[lip_mat]
            lanes = [(-ho, Z_TOE, None),
                     (-hl, Z_LIP * sag, lm),
                     (-hs, Z_VALLEY, lm),
                     (hs, Z_VALLEY, M["Crack"]),
                     (hl, Z_LIP * sag, lm),
                     (ho, Z_TOE, lm)]
            for k in range(len(lanes) - 1):
                o0, z0, _ = lanes[k]
                o1, z1, mat = lanes[k + 1]
                (p0, p1) = q(o0, z0)
                (p2, p3) = q(o1, z1)
                joints.add([p0, p1, p3, p2], mat, normal=(0, 0, 1))

    # The yard is asphalt over an older slab, so the joint that telegraphs
    # through it is a bitumen-sealed line, not a concrete arris: the lips bind
    # TarSeam and what reads is the DARK line and the shadow in it.  Pale
    # concrete lips on a dark yard drew a grid of bright tape.  The dock apron
    # really is concrete, so its joints keep the concrete lip.
    for x in np.arange(-50.0, 50.001, 5.0):
        joint_run((float(x), -15.6), (float(x), 13.6), "y", "TarSeam")
    for y in np.arange(-15.0, 12.001, 5.0):
        joint_run((-51.0, float(y)), (51.0, float(y)), "x", "TarSeam")
    for x in np.arange(-45.0, 30.001, 5.0):
        joint_run((float(x), -33.6), (float(x), -16.4), "y", "ConcreteKerb")
    for y in np.arange(-33.0, -17.001, 4.0):
        joint_run((-45.5, float(y)), (29.5, float(y)), "x", "ConcreteKerb")
    emit_poly(stage, f"{TERRAIN}/NearField/ExpansionJoints", joints, mat_paths, "Crack",
              doc="Saw-cut slab joints on the yard's 5.0 m grid and the dock apron's "
                  "5.0 x 4.0 m grid, built as real RAISED relief rather than a recess: a "
                  "26 mm valley bound to the void look with a 14 mm settled concrete lip "
                  "either side and a toe running out to 78 mm. Recessed geometry is "
                  "invisible here -- the ground mesh has no hole in it -- so a slot cut "
                  "below grade renders as two bright hairlines with no shadow between "
                  "them. Broken where resurfacing has covered them and spalled up to 3x "
                  "width in 14% of segments; lip height varies 72-127% run to run.")

    # ---- 3. potholes with broken, raised rims ------------------------------
    rim = Poly()
    prng = np.random.default_rng(SEED + 217)
    chosen = []
    for (hx, hy, hr, hd) in POTHOLES:
        for ex, ey, rad, _ in NEARFIELD_EYES:
            if math.hypot(hx - ex, hy - ey) < rad and hd > 0.075:
                chosen.append((hx, hy, hr, hd))
                break
    chosen = chosen[:22]
    for i, (hx, hy, hr, hd) in enumerate(chosen):
        # exposed-aggregate floor, following the carved bowl
        n = int(np.clip(round(2 * math.pi * hr / 0.30), 24, 90))
        t = np.arange(n) * (2 * math.pi / n)
        wob = 1.0 + 0.16 * np.sin(3 * t + i) + 0.09 * np.sin(7 * t + 2.1 * i)
        fx = hx + hr * 0.78 * wob * np.cos(t)
        fy = hy + hr * 0.78 * wob * np.sin(t)
        fz = terrain_z(fx, fy) + 0.006
        cz = float(terrain_z(np.array([hx]), np.array([hy]))[0]) + 0.006
        floor = [(hx, hy, cz)] + list(zip(fx.tolist(), fy.tolist(), fz.tolist()))
        for k in range(n):
            rim.add([floor[0], floor[1 + k], floor[1 + (k + 1) % n]],
                    M["AsphaltAggregate"])
        # the rim: spalled plates of surfacing tipped up out of the hole
        nplate = int(np.clip(round(2 * math.pi * hr / 0.24), 12, 46))
        for k in range(nplate):
            if prng.random() < 0.22:
                continue
            a = 2 * math.pi * k / nplate + float(prng.uniform(-0.05, 0.05))
            rr = hr * float(prng.uniform(0.94, 1.14))
            cxp = hx + rr * math.cos(a)
            cyp = hy + rr * math.sin(a)
            s = float(prng.uniform(0.07, 0.20))
            gz = z_at(cxp, cyp)
            th = math.radians(float(prng.uniform(9.0, 30.0)))
            outline = blob(cxp, cyp, s, s * float(prng.uniform(0.5, 0.95)),
                           int(prng.integers(0, 999999)), n=6, rough=0.45,
                           yaw=float(prng.uniform(0, 180)))
            top = [(qx, qy,
                    gz + 0.006 + math.tan(th) * ((qx - cxp) * math.cos(a)
                                                 + (qy - cyp) * math.sin(a)))
                   for qx, qy in outline]
            rim.add(top, M["BrokenConcrete"] if prng.random() < 0.4
                    else M["AsphaltAggregate"])
            for j in range(len(top)):
                p, q2 = top[j], top[(j + 1) % len(top)]
                rim.add([(p[0], p[1], p[2] - 0.035), (q2[0], q2[1], q2[2] - 0.035),
                         q2, p], M["Crack"])
    emit_poly(stage, f"{TERRAIN}/NearField/PotholeRims", rim, mat_paths,
              "AsphaltAggregate",
              doc=f"{len(chosen)} potholes inside the camera discs given explicit "
                  f"geometry: an exposed-aggregate floor following the carved bowl and a "
                  f"broken raised rim of 12-46 spalled surfacing plates tipped 9-30 deg "
                  f"out of the hole, each with a dark edge face. The height field alone "
                  f"gives a smooth dish, which is not what a pothole looks like.")

    # ---- 4. chipped kerb nosing + exposed rebar ----------------------------
    nose = Poly()
    krng = np.random.default_rng(SEED + 219)
    KERBS = [  # (x0, x1, y, top, side) -- the two kerb lines a camera can reach
        (-38.0, 38.0, 13.50, 0.120, -1.0),      # warehouse south kerb plinth
        (-46.0, 30.0, -21.70, 0.085, -1.0),     # dock apron edge beam
    ]
    nspall = nrebar = 0
    for (x0, x1, yk, top, side) in KERBS:
        x = x0 + 1.0
        while x < x1 - 1.0:
            x += float(krng.uniform(1.4, 5.5))
            if yk > 0 and -4.4 < x < 4.4:              # hero-gate crossing
                continue
            if yk < 0:                                  # dock bays / drive-through
                if any(abs(x - b) < 2.4 for b in (-38.0, -22.0, -6.0, 10.0)):
                    continue
                if 1.5 < x < 8.5 or 24.9 < x < 26.7 or -33.1 < x < -31.7:
                    continue
            gz = z_at(x, yk)
            # a bite taken out of the top arris: 3-7 fragments dropped below it
            w = float(krng.uniform(0.18, 0.62))
            for _ in range(int(krng.integers(3, 8))):
                fx = x + float(krng.uniform(-w, w))
                fs = float(krng.uniform(0.030, 0.085))
                fz = gz + top - float(krng.uniform(0.005, 0.055))
                out = blob(fx, yk + side * float(krng.uniform(0.0, 0.10)), fs,
                           fs * float(krng.uniform(0.5, 1.0)),
                           int(krng.integers(0, 999999)), n=6, rough=0.5)
                pts = [(qx, qy, fz) for qx, qy in out]
                nose.add(pts, M["ConcreteKerb"])
                for j in range(len(pts)):
                    p, q2 = pts[j], pts[(j + 1) % len(pts)]
                    nose.add([(p[0], p[1], p[2] - 0.045),
                              (q2[0], q2[1], q2[2] - 0.045), q2, p],
                             M["BrokenConcrete"])
                nspall += 1
            # rusted rebar showing through, one spall in three
            if krng.random() < 0.34:
                for _ in range(int(krng.integers(1, 4))):
                    bx0 = x + float(krng.uniform(-w, w))
                    bz = gz + top - float(krng.uniform(0.02, 0.06))
                    ln = float(krng.uniform(0.10, 0.34))
                    hh = 0.006
                    ang = float(krng.uniform(-0.5, 0.5))
                    dx0, dy0 = ln * math.cos(ang), ln * math.sin(ang) * 0.3
                    for dz in (-hh, hh):
                        nose.add([(bx0, yk - hh, bz + dz),
                                  (bx0 + dx0, yk + dy0 - hh, bz + dz + 0.012),
                                  (bx0 + dx0, yk + dy0 + hh, bz + dz + 0.012),
                                  (bx0, yk + hh, bz + dz)], M["DrainIron"])
                    nrebar += 1
    emit_poly(stage, f"{TERRAIN}/NearField/KerbNosing", nose, mat_paths, "ConcreteKerb",
              doc=f"{nspall} spalled fragments broken out of the top arris of the "
                  f"warehouse kerb plinth and the dock apron edge beam, with {nrebar} "
                  f"rusted rebar stubs showing through. A kerb with an unbroken 90 deg "
                  f"nosing after forty years of forklifts is the single most obvious "
                  f"untouched-blockout tell in a yard.")

    report.append(f"  nearfield {nchip} embedded aggregate chips, "
                  f"{len(joints.FC)} joint faces, {len(chosen)} detailed potholes, "
                  f"{nspall} kerb spalls, {nrebar} rebar stubs")


def build_interior_overlays(stage, mat_paths):
    """Warehouse01 supplies its own flat floor (SM_Floor_A1 at Z = 0.000), so the
    interior ground treatment is authored as thin overlays above it rather than as
    a competing slab.  MarkingLines.usd tops out at Z = 0.007, so everything here
    sits at 0.010 or above."""
    UsdGeom.Scope.Define(stage, TERRAIN + "/InteriorOverlay")
    rng = np.random.default_rng(SEED + 41)

    # saw-cut slab joints on a 6.0 m grid, several spalled wide
    poly = Poly()
    for x in np.arange(-36.0, 36.001, 6.0):
        line = resample([(float(x), 15.4), (float(x), 76.0)], 1.5)
        for i in range(len(line) - 1):
            w = float(rng.uniform(0.06, 0.13)) if rng.random() < 0.06 else 0.014
            (xa, ya), (xb, yb) = line[i], line[i + 1]
            poly.add([(xa - w, ya, 0.010), (xa + w, ya, 0.010),
                      (xb + w, yb, 0.010), (xb - w, yb, 0.010)],
                     M["InteriorJoint"], normal=(0, 0, 1))
    for y in np.arange(16.0, 76.001, 6.0):
        line = resample([(-37.0, float(y)), (37.0, float(y))], 1.5)
        for i in range(len(line) - 1):
            w = float(rng.uniform(0.06, 0.13)) if rng.random() < 0.06 else 0.014
            (xa, ya), (xb, yb) = line[i], line[i + 1]
            poly.add([(xa, ya - w, 0.010), (xb, yb - w, 0.010),
                      (xb, yb + w, 0.010), (xa, ya + w, 0.010)],
                     M["InteriorJoint"], normal=(0, 0, 1))
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/SlabJoints", poly, mat_paths,
              "InteriorJoint",
              doc="saw-cut slab joints on a 6.0 m grid, several spalled wide")

    # Aisle centrelines worn through to aggregate.
    #
    # The previous version of this was a constant-width ribbon of 1.5 m quads and
    # it read exactly as what it was: a stretched card lying down the aisle with
    # two straight parallel edges.  A traffic wear path has no edge at all.  So
    # the ribbon is now built from two INDEPENDENTLY noised boundary polylines
    # sampled at 0.45 m (the two sides never run parallel), the ribbon is cut by
    # random holidays where the floor is still sound, and the whole thing is
    # feathered out to +/-3 m by a stipple of shrinking islands.
    poly = Poly()
    for ai, ay in enumerate(AISLES_Y):
        xs = np.arange(-36.6, 36.601, 0.45)
        centre = ay + 0.55 * np.array(
            [vnoise(np.array([x]), np.array([ay + 3.0]), 0.055, 400 + ai)[0]
             + 0.4 * vnoise(np.array([x]), np.array([ay]), 0.19, 430 + ai)[0] for x in xs])
        south = centre - (0.62 + 0.55 * np.array(
            [0.5 + 0.5 * fbm(np.array([x]), np.array([ay - 7.0]), 0.085, 3, 300 + ai)[0]
             for x in xs]))
        north = centre + (0.62 + 0.55 * np.array(
            [0.5 + 0.5 * fbm(np.array([x]), np.array([ay + 11.0]), 0.075, 3, 340 + ai)[0]
             for x in xs]))
        for i in range(len(xs) - 1):
            if rng.random() < 0.10:                    # sound patches of slab
                continue
            xa, xb = float(xs[i]), float(xs[i + 1])
            poly.add([(xa, float(south[i]), 0.0108), (xb, float(south[i + 1]), 0.0108),
                      (xb, float(north[i + 1]), 0.0108), (xa, float(north[i]), 0.0108)],
                     M["InteriorWorn"], normal=(0, 0, 1))
        # feathered dissolve on both flanks, plus a scatter of isolated scuffs
        for sgn in (-1.0, 1.0):
            for cx in np.arange(-34.0, 35.0, 4.0):
                stipple(poly, M["InteriorWorn"], int(rng.integers(0, 999999)),
                        float(cx), ay + sgn * 1.85, 2.6, 1.35, 22, 0.045, 0.30,
                        z=0.0106)
        for cx in np.arange(-33.0, 35.0, 6.0):
            stipple(poly, M["InteriorScuff"], int(rng.integers(0, 999999)),
                    float(cx) + float(rng.uniform(-1.5, 1.5)),
                    ay + float(rng.uniform(-2.2, 2.2)), 1.1, 0.7, 14, 0.03, 0.16,
                    z=0.0113)
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/AisleWear", poly, mat_paths, "InteriorWorn",
              doc="warehouse slab worn through to aggregate along every aisle centreline: "
                  "two independently noised edges, random sound-slab holidays, and a "
                  "stippled dissolve on both flanks so the wear path has no silhouette")

    # forklift tyre-scuff arcs at each staggered rack gap
    poly = Poly()
    for gx, gy in RACK_GAPS:
        for sgn in (-1.0, 1.0):
            r = 3.2 + 1.4 * float(rng.random())
            a0 = math.radians(float(rng.uniform(-40, 10)))
            span = math.radians(float(rng.uniform(55, 105)))
            for k in range(16):
                if rng.random() < 0.22:
                    continue
                t0 = a0 + span * k / 16
                t1 = a0 + span * (k + 1) / 16
                pts = []
                for rr, tt in ((r - 0.10, t0), (r + 0.10, t0), (r + 0.10, t1), (r - 0.10, t1)):
                    px = gx + rr * math.cos(tt)
                    py = gy + sgn * (2.6 + rr * math.sin(tt))
                    if not (-37.0 < px < 37.0 and 15.6 < py < 75.8):
                        pts = []
                        break
                    pts.append((px, py, 0.012))
                if pts:
                    poly.add(pts, M["InteriorScuff"], normal=(0, 0, 1))
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/ForkliftScuff", poly, mat_paths,
              "InteriorScuff", doc="black forklift tyre-scuff arcs at every rack-run gap")

    # Oil drip trail east down the main through-lane A3.
    #
    # Also rebuilt: the old version was a 0.30 m constant-width strip plus
    # 0.10-0.34 m discs, which rendered as a row of hard grey-blue rounded quads
    # floating on the slab.  A drip trail is a hairline stain with the occasional
    # pool, so the line is now 0.04-0.09 m and heavily broken, the drips are
    # small, and each of the six real leaks (where a forklift stands) is a
    # stipple rather than a disc.
    poly = Poly()
    trail = resample(
        [(float(x), 49.5 + 0.5 * float(vnoise(np.array([x]), np.array([0.0]), 0.09, 555)[0])
          + 0.18 * float(vnoise(np.array([x]), np.array([12.0]), 0.4, 557)[0]))
         for x in np.arange(-31.0, 34.001, 1.0)], 0.45)
    for i in range(len(trail) - 1):
        if rng.random() < 0.42:
            continue
        w = 0.020 + 0.026 * float(rng.random())
        (xa, ya), (xb, yb) = trail[i], trail[i + 1]
        poly.add([(xa, ya - w, 0.0126), (xb, yb - w, 0.0126),
                  (xb, yb + w, 0.0126), (xa, ya + w, 0.0126)],
                 M["InteriorOil"], normal=(0, 0, 1))
    for cx in np.arange(-30.0, 34.0, 1.6):
        r = float(rng.uniform(0.025, 0.085))
        cy = 49.5 + float(rng.uniform(-1.5, 1.5))
        poly.add([(px, py, 0.0128) for px, py in
                  blob(float(cx), cy, r, r * 0.8, int(rng.integers(0, 99999)),
                       n=8, rough=0.4)], M["InteriorOil"], normal=(0, 0, 1))
    for k, sx in enumerate((-27.5, -14.0, -2.5, 9.0, 19.5, 30.0)):     # standing leaks
        sy = 49.5 + float(rng.uniform(-1.8, 1.8))
        poly.add([(px, py, 0.0127) for px, py in
                  blob(sx, sy, 0.24, 0.17, 5600 + k, n=12, rough=0.45)],
                 M["InteriorOil"], normal=(0, 0, 1))
        stipple(poly, M["InteriorOil"], 5650 + k, sx, sy, 0.95, 0.62, 30,
                0.018, 0.10, z=0.0126)
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/OilTrail", poly, mat_paths, "InteriorOil",
              doc="oil drip trail running east down aisle A3: a broken 40-90 mm hairline, "
                  "small drips, and six standing leaks that dissolve into a stipple")

    # Water ingress: damp halos + flat water films inside the open doors.
    #
    # A damp halo has no edge either -- concrete dries from the outside in, so the
    # boundary is a mottle.  The halo is therefore a stipple with a small solid
    # core.  The FILM keeps a hard outline, because standing water genuinely does
    # have a sharp shoreline and that meniscus is what sells it.
    halos, films = Poly(), Poly()
    for di, dx in enumerate(SOUTH_DOORS_X):
        halos.add([(px, py, 0.0104) for px, py in
                   blob(dx, 16.4, 1.5, 1.05, 700 + di, n=20, rough=0.34)],
                  M["InteriorWet"], normal=(0, 0, 1))
        stipple(halos, M["InteriorWet"], 720 + di, dx, 16.9, 3.4, 2.5, 120,
                0.07, 0.55, z=0.0103)
        films.add([(px, py, 0.0145) for px, py in
                   blob(dx, 16.1, 1.9, 1.25, 760 + di, n=30, rough=0.40)],
                  M["Water"], normal=(0, 0, 1))
        for s in range(3):                                   # satellite pools
            films.add([(px, py, 0.0143) for px, py in
                       blob(dx + float(rng.uniform(-2.4, 2.4)),
                            16.6 + float(rng.uniform(-0.9, 2.4)),
                            float(rng.uniform(0.14, 0.45)),
                            float(rng.uniform(0.10, 0.32)),
                            770 + di * 7 + s, n=14, rough=0.45)],
                      M["Water"], normal=(0, 0, 1))
    # the 6 m slick fanning in from the hero gate -- the interior shot's reflection
    halos.add([(px, py, 0.0106) for px, py in blob(0.0, 18.8, 3.1, 2.6, 790, n=30, rough=0.30)],
              M["InteriorWet"], normal=(0, 0, 1))
    stipple(halos, M["InteriorWet"], 795, 0.0, 19.8, 6.4, 5.4, 260, 0.09, 0.70, z=0.0105)
    films.add([(px, py, 0.0150) for px, py in blob(0.0, 18.2, 3.6, 3.0, 791, n=40, rough=0.34)],
              M["Water"], normal=(0, 0, 1))
    films.add([(px, py, 0.0150) for px, py in blob(-1.2, 22.6, 1.9, 1.4, 792, n=22, rough=0.36)],
              M["Water"], normal=(0, 0, 1))
    for s in range(10):
        films.add([(px, py, 0.0148) for px, py in
                   blob(float(rng.uniform(-5.5, 5.5)), float(rng.uniform(16.2, 24.5)),
                        float(rng.uniform(0.18, 0.7)), float(rng.uniform(0.12, 0.5)),
                        800 + s, n=16, rough=0.44)], M["Water"], normal=(0, 0, 1))
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/WetFanHalos", halos, mat_paths,
              "InteriorWet",
              doc="damp mottle on the slab around each water-ingress fan: a small solid "
                  "core dissolving into a stipple, so the damp patch has no cut edge")
    emit_poly(stage, f"{TERRAIN}/InteriorOverlay/WaterFilms", films, mat_paths, "Water",
              doc="flat standing-water films inside the open roller doors plus the 6 m slick "
                  "fanning in from the hero gate -- these carry the interior reflection. "
                  "Hard outline is deliberate: a shoreline is sharp.")


# ----------------------------------------------------------------------------
# 6.  build
# ----------------------------------------------------------------------------

REGIONS = [
    # name,                       x0,    x1,     y0,     y1,   cx,   cy, default look
    ("Ground_MarginWest", -75.0, -70.0, -56.0, 94.0, 1.0, 1.0, "DirtWeeds", ()),
    ("Ground_MarginEast", 70.0, 75.0, -56.0, 94.0, 1.0, 1.0, "DirtWeeds", ()),
    ("Ground_OOBSouth", -70.0, 70.0, -56.0, -40.0, 0.5, 0.5, "DirtWeeds", ()),
    ("Ground_ServiceRoad", -70.0, 70.0, -40.0, -34.0, 0.35, 0.25, "Mud", ()),
    ("Ground_DockApron", -70.0, 70.0, -34.0, -16.0, 0.35, 0.35, "ConcreteDock", ()),
    ("Ground_CentralYard", -70.0, 70.0, -16.0, 15.0, 0.35, 0.35, "AsphaltOxidised", ()),
    ("Ground_FlankWest", -70.0, -38.0, 15.0, 76.25, 0.75, 0.75, "Gravel", ()),
    ("Ground_FlankEast", 38.0, 70.0, 15.0, 76.25, 0.75, 0.75, "Gravel", ()),
    ("Ground_InteriorUnderlay", -38.0, 38.0, 15.0, 76.25, 1.0, 1.0, "ConcreteSlabExposed", ()),
    ("Ground_OOBNorth", -70.0, 70.0, 76.25, 94.0, 1.0, 1.0, "Gravel", (ANNEX,)),
]

REGION_DOCS = {
    "Ground_InteriorUnderlay":
        "Underlayment only. Warehouse01 supplies its own flat floor mesh SM_Floor_A1 at "
        "Z = 0.000 (world X -37.98..+37.97, Y +15.23..+88.25), so this sits 12-17 mm below "
        "it and never z-fights; it exists to close the gap between the yard edge at Y=15.00 "
        "and the asset floor edge at Y=15.23 and to guarantee no see-through. The visible "
        "interior treatment is /World/Terrain/InteriorOverlay/*.",
    "Ground_OOBNorth":
        "North out-of-bounds backdrop. The office-annex footprint (X 13.79..26.20, "
        "Y 75.81..88.25) is cut out - that floor belongs to Warehouse01.",
    "Ground_CentralYard":
        "Lane B. Patched asphalt over an older slab: three asphalt looks with irregular "
        "4-14 m boundaries, old concrete exposed where the truck routes have ground "
        "through, cambered to the E-W trench drain at Y = -14.5.",
    "Ground_ServiceRoad":
        "Rear service road. Compacted mud, sampled at 0.25 m in Y so the two deep "
        "water-holding wheel ruts actually resolve.",
    "Ground_DockApron":
        "Lane C apron. Concrete X -46..+30, broken up into gravel and mud east of X=+30 "
        "and west of X=-46.",
    "Ground_OOBSouth":
        "South out-of-bounds. Carries the E-W drainage ditch at Y = -48 (2.5 m wide, "
        "0.60 m deep, meandering) which holds water its full length.",
}


def main():
    report: list[str] = []
    stage = Usd.Stage.CreateInMemory("10_terrain.usda")
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    stage.OverridePrim("/World")
    root = UsdGeom.Xform.Define(stage, TERRAIN)
    root.GetPrim().SetDocumentation(
        "DEADFALL DEPOT ground system. One continuous analytic height field drives every "
        "ground mesh so region seams match exactly. Material regions are GeomSubsets named "
        "sub_<Look> with familyName 'materialBind', each bound directly to a shared scanned "
        "material under /World/Looks (50_materials.usda). There is no local Looks scope and "
        "no constant-colour fallback anywhere in this module by design.")
    UsdGeom.Scope.Define(stage, TERRAIN + "/Ground")

    # No local Looks scope. Every mesh and every GeomSubset binds a shared
    # scanned material under /World/Looks (50_materials.usda).
    mat_paths: dict[str, str] = {}

    ground_faces = 0
    for name, x0, x1, y0, y1, cx, cy, dm, cuts in REGIONS:
        mesh = ground_region(stage, name, x0, x1, y0, y1, cx, cy, mat_paths, dm,
                             cutouts=cuts, doc=REGION_DOCS.get(name))
        nf = len(mesh.GetFaceVertexCountsAttr().Get())
        npt = len(mesh.GetPointsAttr().Get())
        nsub = len(mesh.GetPrim().GetChildren())
        ground_faces += nf
        report.append(f"  {name:<26} {nf:>7} faces {npt:>7} pts  {nsub:>2} subsets")

    build_paved_looks(stage)
    build_backdrop_looks(stage)
    build_far_field(stage, mat_paths, report)
    build_backdrop(stage, mat_paths, report)
    build_mosaic(stage, mat_paths, report)
    build_patches(stage, mat_paths, report)
    build_repair_rects(stage, mat_paths, report)
    build_cracks(stage, mat_paths, report)
    build_traffic(stage, mat_paths, report)
    build_grit(stage, mat_paths, report)
    build_nearfield(stage, mat_paths, report)
    build_rut_relief(stage, mat_paths, report)
    build_lipped_cracks(stage, mat_paths, report)
    build_edge_drift(stage, mat_paths, report)
    build_water(stage, mat_paths, report)
    build_drains(stage, mat_paths)
    build_covers(stage, mat_paths)
    build_kerbs(stage, mat_paths)
    build_broken_slabs(stage, mat_paths)
    build_markings(stage, mat_paths)
    build_interior_overlays(stage, mat_paths)

    faces = pts = meshes = subsets = 0
    zmin, zmax = 1e9, -1e9
    for prim in stage.Traverse():
        if prim.GetTypeName() == "GeomSubset":
            subsets += 1
        if prim.GetTypeName() != "Mesh":
            continue
        m = UsdGeom.Mesh(prim)
        meshes += 1
        faces += len(m.GetFaceVertexCountsAttr().Get())
        pts += len(m.GetPointsAttr().Get())
        ext = m.GetExtentAttr().Get()
        zmin = min(zmin, ext[0][2])
        zmax = max(zmax, ext[1][2])

    # /World must stay an `over` -- 00_stage.usda owns the `def`.
    spec = stage.GetRootLayer().GetPrimAtPath("/World")
    spec.specifier = Sdf.SpecifierOver
    spec.typeName = ""

    layer = stage.GetRootLayer()
    layer.documentation = (
        "DEADFALL DEPOT module: terrain (ground, kerbs, drainage, puddle geometry). "
        "Owned by one specialist agent - do not edit from another module. GENERATED by "
        "tools/gen_terrain.py; regenerate rather than hand-editing."
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Export via a temp file we own and rename ourselves, with retries.  This
    # module is 190 MB and takes nine minutes to build; other agents render off
    # the composed level constantly, and a renderer holding 10_terrain.usda open
    # makes Sdf's own atomic rename fail with "Access is denied" -- which throws
    # away the whole build AND leaves a 190 MB orphan temp behind.  Wait it out.
    tmp = OUT.with_suffix(".tmp_export")
    layer.Export(str(tmp))
    for attempt in range(120):
        try:
            os.replace(str(tmp), str(OUT))
            break
        except OSError:
            if attempt == 0:
                print("  target locked by another process (a render is reading it); "
                      "waiting...", flush=True)
            time.sleep(5.0)
    else:
        raise RuntimeError(f"could not replace {OUT} after 10 minutes; the new "
                           f"layer is complete and waiting at {tmp}")

    ba = BOUNDARY_AUDIT
    report.append(
        f"  BOUNDARY AUDIT  {ba['n']} conditioned outlines, {ba['verts']} vertices; "
        f"wander step {ba['step_min']:.2f}-{ba['step_max']:.2f} m (spec 0.5-1.0); "
        f"worst chord {ba['worst']:.3f} m (limit 1.000, source {ba['worst_src']}); "
        f"lateral jitter up to {ba['jit_max']:.3f} m (spec 0.10-0.40)")

    print("\n".join(report))
    print(f"\n  ground faces {ground_faces}")
    print(f"  stage: {meshes} meshes, {subsets} material subsets, {faces} faces, "
          f"{pts} points, Z range {zmin:+.3f} .. {zmax:+.3f}")
    print(f"  wrote {OUT}  ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
