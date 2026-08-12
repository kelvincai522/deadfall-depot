"""Generate usd/modules/80_fx.usda -- DEADFALL DEPOT atmosphere, volumetrics and decals.

Owned by the FX agent. Run from tools/:  uv run gen_fx.py

What this authors
-----------------
1. RTX analytic fog per RenderProduct (aerial perspective). Measured live on this
   build: `omni:rtx:fog:*` on the RenderProduct is honoured by ovrtx 0.4.0 in both
   RealTimePathTracing and PathTracing. distanceDensity is the dominant control;
   endDist past ~400 barely matters.
2. Light-scattering geometry: sun bars through the open west roller doors, roof
   monitor curtains, the hero-gate wedge, and a glow cone under every practical
   whose position was read out of 60_lighting.usda. RTX has no participating
   medium without a VDB (the library ships none), so scattering is authored as
   thin emissive fractional-cutout geometry - the same trick a shipped game uses.
3. Ground mist, steam off the wet apron and drizzle veils.
4. Decals: tyre scuff, forklift arcs, oil, wet fans, rust bleed, water staining,
   algae, efflorescence, soot, bird mess, and drip lines.

Everything soft-edged is masked with an alpha texture (T_dot_falloff / smoke_wisp)
so no decal has the hard rectangular silhouette a critic spots instantly. Every
instance gets its own UV crop, so nothing repeats.
"""

import math
import random
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "usd" / "modules" / "80_fx.usda"

S3 = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
TEX_DOT = S3 + "Assets/Particles/textures/T_dot_falloff.png"
TEX_WISP = S3 + "Assets/Particles/textures/smoke_wisp.png"
TEX_MIST = S3 + "Assets/Particles/textures/T_Mist_6X6_basecolor.png"

rng = random.Random(80808)

# --- the sun, straight out of 60_lighting.usda -------------------------------
# DistantLight KeySun rotateXYZ (83.0, 0, 290) -> emission direction:
SUN = (0.93270, 0.33940, -0.12187)          # unit, travelling ENE and dropping
SUN_WARM = (1.0, 0.62, 0.30)
SKY_COOL = (0.50, 0.64, 0.95)
SODIUM = (1.0, 0.55, 0.22)
MERCURY = (0.74, 0.89, 1.0)

# --- global gain knobs -------------------------------------------------------
# Calibrated by rendering, not guessed. A cutout-emissive slab adds roughly
# `opacity * emissive_intensity` of radiance to a ray and removes `opacity` of
# what is behind it. The first pass used 0.085 x 900 = 77 and every cone read as
# a GREY FILTER darkening the ceiling instead of a glow, because 77 sits below
# the scene's own background level. Keeping the product an order of magnitude
# higher while dropping opacity by 3x is what flips it from a veil to a glow.
E_SHAFT_SUN = 6000.0
E_SHAFT_SKY = 3400.0
E_GATE = 7000.0
E_GLOW_HI = 4600.0
E_GLOW_LO = 1200.0
E_MIST = 3.2
OP_SHAFT = 0.022      # halved: every medium surface is now authored twice
OP_SHAFT_SKY = 0.0062
OP_GLOW = 0.015
OP_MIST = 1.0        # masked by texture

# --- REVISION 3: THE ATMOSPHERE ---------------------------------------------
# Three stacked height-graded haze tiers replace the old flat-topped scrim
# boxes. Every plane's density is masked by a VERTICAL GRADIENT (see
# haze_plane), so a tier has no top edge to see - it decays to exactly zero at
# its own ceiling. Three tiers with ceilings 6 / 17 / 34 m sum to a smooth
# monotone profile, which is what "thins with altitude, continuously" means.
# Thickening with distance comes from the plane SPACING: a horizontal ray
# crosses one every few metres, so accumulated airlight is proportional to
# path length. That is the correct behaviour and it is why this is authored as
# a grid of planes rather than as a single slab.
#
# `emissive x opacity` is the radiance a ray picks up per crossing; the sodium
# halos at ~69 are the calibration reference. Per-plane pickup is deliberately
# single-digit, because it is the SUM over 5-25 crossings that has to read.
E_HAZE = 90.0
HAZE_COOL = (0.42, 0.58, 1.00)
# THE HAZE IS COLD, AND NOT BY TASTE. Measured on this frame: making the
# sunward half of the haze warm moved the DARK half of the histogram from
# R-B = -0.049 to +0.024 - it painted the shadows the same colour as the key,
# which is the exact failure BRIEF section 6 names for cool_pixel_frac, and
# warm_cool_split collapsed from 0.057 to 0.010. Haze at this hour is lit by
# the whole storm dome, so it is the COOL half of the frame; the amber belongs
# to the sun, and the sun in this layer means the god rays. The colour is a
# saturated storm blue rather than a neutral grey for the same reason - per
# unit of brightness added to a silhouette it buys the most R-B separation.
OP_HAZE_A = 0.0068      # ground tier,  ceiling  6 m,  6.0 m plane pitch
OP_HAZE_B = 0.0055      # mid tier,     ceiling 17 m,  9.0 m plane pitch
OP_HAZE_C = 0.0045      # upper tier,   ceiling 44 m, 13.0 m plane pitch
HAZE_TOP_A, HAZE_TOP_B, HAZE_TOP_C = 6.0, 17.0, 34.0
HAZE_PITCH_A, HAZE_PITCH_B, HAZE_PITCH_C = 9.6, 14.4, 20.8

# God rays. Authored as CROSS-SECTION cards stacked along the sun vector, not
# as a tube: a camera looking down the beam crosses all of them and the beam
# reads bright, a camera looking across it crosses one or two and it stays
# faint. That anisotropy is exactly what a real participating medium does
# (pickup is proportional to path length inside the lit volume), and it is the
# only way to get a shaft that survives being looked at end-on.
# THIS LADDER IS A MEASURED OPTIMUM, NOT A GUESS. Three settings were rendered
# at 2048 spp on SILHOUETTE_WEST and analysed:
#     0.62x  p01 0.053  warm_cool_split 0.000
#     1.00x  p01 0.053  warm_cool_split 0.047   <- authored
#     1.60x  p01 0.070  warm_cool_split 0.007
# Both directions are worse. Above 1.0x the beams start painting the SHADOWS
# amber, which is the exact failure BRIEF section 6 names, and p01 leaves gate;
# below it there is not enough warm left in the bright half to separate from
# the blue sky at all. The previous owner's note implies mesh-light power
# tracks emissive and ignores opacity, so raising opacity ought to be free -
# it is not, as the 1.6x row shows. Re-measure p01 and warm_cool_split before
# believing any change to these numbers.
E_GODRAY = 700.0
OP_GODRAY = 0.0078
OP_GODRAY_SOFT = 0.0034
GODRAY_WARM = (1.0, 0.66, 0.34)


# --- texture atlases ---------------------------------------------------------
# smoke_wisp.png is NOT a single wisp: it is an 8x8 FLIPBOOK, and sampling the
# whole image as a mask paints a grid of 64 little puffs across whatever it is
# bound to. (That is exactly what the first render did to the warehouse wall.)
# Rows 0-1 are dense, rows 5-7 are almost gone, so the row doubles as a density
# control. T_Mist_6X6_basecolor.png is a 6x6 flipbook of the same kind.
def wisp(row=None, col=None, inset=0.006):
    """UV crop of one cell of the 8x8 smoke_wisp flipbook."""
    r = rng.randrange(2, 7) if row is None else row
    c = rng.randrange(8) if col is None else col
    h = 0.125 * 0.5 - inset
    return (0.125 * (c + 0.5), 0.125 * (r + 0.5), h, h)


# =============================================================================
# tiny mesh accumulator - one USD Mesh per (material, group), many faces inside
# =============================================================================
class M:
    """`two_sided` duplicates every face with reversed winding.

    `doubleSided = 1` makes USD *draw* the back of a face, but OmniPBR's emission
    only comes off the FRONT. The first calibrated render showed this beautifully:
    a glow cone seen from outside was a glow, and the same cone seen from inside -
    which is what a camera standing under a high bay sees - was a solid dark
    triangle hanging off the roof. Authoring both windings makes the medium emit
    whichever way you are looking through it. Opacity per surface is halved to
    keep the total the same.
    """

    def __init__(self, name, mat, two_sided=False):
        self.name = name
        self.mat = mat
        self.two = two_sided
        self.pts = []
        self.counts = []
        self.idx = []
        self.st = []

    def face(self, pts, uvs):
        self._face(pts, uvs)
        if self.two:
            self._face(list(reversed(pts)), list(reversed(uvs)))

    def _face(self, pts, uvs):
        b = len(self.pts)
        self.pts.extend(pts)
        self.counts.append(len(pts))
        self.idx.extend(range(b, b + len(pts)))
        self.st.extend(uvs)

    def quad(self, p0, p1, p2, p3, uv=None):
        self.face([p0, p1, p2, p3], uv or [(0, 0), (1, 0), (1, 1), (0, 1)])

    def tri(self, p0, p1, p2, uv=None):
        self.face([p0, p1, p2], uv or [(0.5, 0.06), (0.94, 0.94), (0.06, 0.94)])

    # a soft-masked quad: uv crop centred on `cu,cv` with half-extent `hu,hv`
    def blob(self, p0, p1, p2, p3, cu=0.5, cv=0.5, hu=0.5, hv=0.5, rot=0.0):
        c, s = math.cos(rot), math.sin(rot)
        def r(du, dv):
            return (cu + (du * c - dv * s), cv + (du * s + dv * c))
        self.face([p0, p1, p2, p3],
                  [r(-hu, -hv), r(hu, -hv), r(hu, hv), r(-hu, hv)])

    @property
    def empty(self):
        return not self.counts

    def usda(self, indent):
        i = " " * indent
        mn = [min(p[k] for p in self.pts) for k in range(3)]
        mx = [max(p[k] for p in self.pts) for k in range(3)]
        f3 = lambda p: "(%.4f, %.4f, %.4f)" % p
        f2 = lambda p: "(%.5f, %.5f)" % p
        return (
            f'{i}def Mesh "{self.name}" (\n'
            f'{i}    prepend apiSchemas = ["MaterialBindingAPI"]\n'
            f'{i})\n'
            f'{i}{{\n'
            f'{i}    uniform bool doubleSided = 1\n'
            f'{i}    bool primvars:doNotCastShadows = 1\n'
            f'{i}    float3[] extent = [({mn[0]:.4f}, {mn[1]:.4f}, {mn[2]:.4f}), '
            f'({mx[0]:.4f}, {mx[1]:.4f}, {mx[2]:.4f})]\n'
            f'{i}    int[] faceVertexCounts = [{", ".join(str(c) for c in self.counts)}]\n'
            f'{i}    int[] faceVertexIndices = [{", ".join(str(v) for v in self.idx)}]\n'
            f'{i}    rel material:binding = </World/FX/Looks/{self.mat}>\n'
            f'{i}    point3f[] points = [{", ".join(f3(p) for p in self.pts)}]\n'
            f'{i}    texCoord2f[] primvars:st = [{", ".join(f2(p) for p in self.st)}] (\n'
            f'{i}        interpolation = "faceVarying"\n'
            f'{i}    )\n'
            f'{i}    uniform token subdivisionScheme = "none"\n'
            f'{i}}}\n'
        )


def add(v, w, s=1.0):
    return (v[0] + w[0] * s, v[1] + w[1] * s, v[2] + w[2] * s)


def lerp(a, b, t):
    return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))


def box(m, lo, hi, uv_scale=1.0):
    """Six-sided axis-aligned box, faceVarying st in metres/uv_scale."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    dx, dy, dz = (x1 - x0) / uv_scale, (y1 - y0) / uv_scale, (z1 - z0) / uv_scale
    uvs = [[(0, 0), (dx, 0), (dx, dy), (0, dy)], [(0, 0), (dx, 0), (dx, dy), (0, dy)],
           [(0, 0), (dx, 0), (dx, dz), (0, dz)], [(0, 0), (dx, 0), (dx, dz), (0, dz)],
           [(0, 0), (dy, 0), (dy, dz), (0, dz)], [(0, 0), (dy, 0), (dy, dz), (0, dz)]]
    for f, uv in zip(faces, uvs):
        m.face([P[k] for k in f], uv)


def prism(m, quad_a, quad_b):
    """Hexahedron between two 4-point rings (same winding)."""
    m.face(list(quad_a), [(0, 0), (1, 0), (1, 1), (0, 1)])
    m.face(list(reversed(quad_b)), [(0, 0), (1, 0), (1, 1), (0, 1)])
    for k in range(4):
        a0, a1 = quad_a[k], quad_a[(k + 1) % 4]
        b0, b1 = quad_b[k], quad_b[(k + 1) % 4]
        m.face([a0, a1, b1, b0], [(0, 0), (1, 0), (1, 1), (0, 1)])


def cone(m, apex, apex_r, base_c, base_r, seg=18, uv_v0=0.0, uv_v1=1.0):
    """Open truncated cone (no caps) - a light shaft under a fitting."""
    ax = (0.0, 0.0, 1.0)
    d = (base_c[0] - apex[0], base_c[1] - apex[1], base_c[2] - apex[2])
    L = math.sqrt(sum(c * c for c in d)) or 1.0
    d = tuple(c / L for c in d)
    # build an orthonormal frame around d
    up = (0.0, 1.0, 0.0) if abs(d[2]) > 0.9 else (0.0, 0.0, 1.0)
    e0 = (d[1] * up[2] - d[2] * up[1], d[2] * up[0] - d[0] * up[2], d[0] * up[1] - d[1] * up[0])
    n = math.sqrt(sum(c * c for c in e0)) or 1.0
    e0 = tuple(c / n for c in e0)
    e1 = (d[1] * e0[2] - d[2] * e0[1], d[2] * e0[0] - d[0] * e0[2], d[0] * e0[1] - d[1] * e0[0])
    del ax

    def ring(c, r):
        out = []
        for k in range(seg):
            a = 2 * math.pi * k / seg
            out.append((c[0] + r * (e0[0] * math.cos(a) + e1[0] * math.sin(a)),
                        c[1] + r * (e0[1] * math.cos(a) + e1[1] * math.sin(a)),
                        c[2] + r * (e0[2] * math.cos(a) + e1[2] * math.sin(a))))
        return out

    ra, rb = ring(apex, apex_r), ring(base_c, base_r)
    for k in range(seg):
        j = (k + 1) % seg
        u0, u1 = k / seg, (k + 1) / seg
        m.face([ra[k], ra[j], rb[j], rb[k]],
               [(u0, uv_v0), (u1, uv_v0), (u1, uv_v1), (u0, uv_v1)])


def sphere(m, c, r, seg=16, rings=8):
    for i in range(rings):
        t0, t1 = math.pi * i / rings, math.pi * (i + 1) / rings
        for k in range(seg):
            a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
            def P(t, a):
                return (c[0] + r * math.sin(t) * math.cos(a),
                        c[1] + r * math.sin(t) * math.sin(a),
                        c[2] + r * math.cos(t))
            m.face([P(t0, a0), P(t0, a1), P(t1, a1), P(t1, a0)],
                   [(k / seg, i / rings), ((k + 1) / seg, i / rings),
                    ((k + 1) / seg, (i + 1) / rings), (k / seg, (i + 1) / rings)])


def _taper_u(s, amp, hold):
    """u offset from the mask centre at normalised arc position `s`.

    Flat (full opacity) across the middle `hold` fraction of the run, then ramps
    out to +/-`amp` at each end. With the radial T_dot_falloff mask an offset of
    0.44 lands on the transparent rim, so a run authored with amp=0.44 DIES OUT
    at both ends instead of stopping at a hard chopped edge. That is the whole
    difference between "a mark a wheel left" and "a decal somebody stamped".
    """
    e = max(1e-6, (1.0 - hold) * 0.5)
    if s < e:
        return -amp * (1.0 - s / e)
    if s > 1.0 - e:
        return amp * (1.0 - (1.0 - s) / e)
    return 0.0


def _streak_u(s, ph):
    """Smooth 1-D wobble in [-1, +1] used to break a track up along its length.

    A tyre does not lay a mark of constant density: rubber comes off in patches
    as load transfers, so the mark thins, almost disappears, and comes back. The
    round-3 critique named this exactly - "one dot stretched along a 10 m x 0.2 m
    strip yields a long soft ellipse". Offsetting u along the run walks the
    sample off the centre of the radial mask and back, which drops alpha AND
    narrows the effective mark at the same time, i.e. it behaves like a real
    streak rather than like a fade. Two incommensurate harmonics so the pattern
    never repeats over a run.
    """
    return 0.62 * math.sin(s * 13.1 + ph) + 0.38 * math.sin(s * 29.7 + ph * 1.71)


def ribbon(m, pts, width, z, cu=0.5, span=0.16, taper=None, hold=0.58, vh=0.44,
           width_end=None, streak=0.0, phase=0.0):
    """Continuous soft-edged ground ribbon through a polyline of (x, y).

    UV trick: u is held inside a narrow band across the mask's centre so the
    texture only fades ACROSS the ribbon, never along it - that is what stops a
    tyre track reading as a row of blobs.

    `taper` switches u to an arc-length-parameterised ramp instead (see
    _taper_u): full strength through the middle, dissolving at both ends. Used
    for every vehicle track, because a real tyre mark has no ends - it just gets
    fainter until the rubber has all been laid down. `width_end` linearly grows
    or shrinks the track width along the run (a wheel that is scrubbing sideways
    lays a wider mark than one that is rolling).
    """
    n = len(pts)
    # arc-length parameterisation - index parameterisation biases the fade
    # toward whichever end has the denser vertices, which on a straight-into-arc
    # path is always the arc.
    cum = [0.0]
    for k in range(n - 1):
        cum.append(cum[-1] + math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]))
    total = cum[-1] or 1.0
    for k in range(n - 1):
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1.0
        s0, s1 = cum[k] / total, cum[k + 1] / total
        if width_end is None:
            w0 = w1 = width
        else:
            w0 = width + (width_end - width) * s0
            w1 = width + (width_end - width) * s1
        n0x, n0y = -dy / L * w0 * 0.5, dx / L * w0 * 0.5
        n1x, n1y = -dy / L * w1 * 0.5, dx / L * w1 * 0.5
        if taper is None:
            u0 = cu - span * 0.5 + span * s0
            u1 = cu - span * 0.5 + span * s1
            v0, v1 = 0.06, 0.94
        else:
            u0 = 0.5 + _taper_u(s0, taper, hold)
            u1 = 0.5 + _taper_u(s1, taper, hold)
            v0, v1 = 0.5 - vh, 0.5 + vh
        if streak:
            u0 = min(0.94, max(0.06, u0 + streak * _streak_u(s0, phase)))
            u1 = min(0.94, max(0.06, u1 + streak * _streak_u(s1, phase)))
        m.face([(x0 - n0x, y0 - n0y, z), (x1 - n1x, y1 - n1y, z),
                (x1 + n1x, y1 + n1y, z), (x0 + n0x, y0 + n0y, z)],
               [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])


def arc(cx, cy, r, a0, a1, steps=14):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps)))
            for i in range(steps + 1)]


# --- vehicle paths -----------------------------------------------------------
# Every tyre mark in this map is generated from a DRIVEN PATH, not drawn as a
# shape. A path is a sequence of straights and constant-radius arcs; the two
# wheel tracks are then offset from the centreline by half the axle track, which
# is what makes the inner track tighter than the outer one - the single cue that
# separates a real turning mark from a stamped ring.
#
# Heading convention here is the maths one: 0 deg = +X (east), 90 deg = +Y
# (north), positive sweep = left turn (counter-clockwise).

def path_run(x, y, hdg_deg, segs, step=1.6):
    """('s', length) | ('a', radius, sweep_deg)  ->  centreline polyline."""
    pts = [(x, y)]
    h = math.radians(hdg_deg)
    cx, cy = x, y
    for seg in segs:
        if seg[0] == "s":
            L = seg[1]
            n = max(2, int(L / step))
            for i in range(1, n + 1):
                t = L * i / n
                pts.append((cx + math.cos(h) * t, cy + math.sin(h) * t))
        else:
            _, R, sweep = seg
            sgn = 1.0 if sweep >= 0 else -1.0
            ox = cx - sgn * math.sin(h) * R
            oy = cy + sgn * math.cos(h) * R
            a0 = math.atan2(cy - oy, cx - ox)
            n = max(4, int(abs(sweep) / 5.0))
            for i in range(1, n + 1):
                a = a0 + sgn * math.radians(abs(sweep)) * i / n
                pts.append((ox + R * math.cos(a), oy + R * math.sin(a)))
            h += math.radians(sweep)
        cx, cy = pts[-1]
    return pts


def offset_path(pts, d):
    """Parallel offset of a polyline by `d` (positive = to the left of travel)."""
    out = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        elif i == n - 1:
            dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
        else:
            dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        L = math.hypot(dx, dy) or 1.0
        out.append((pts[i][0] - dy / L * d, pts[i][1] + dx / L * d))
    return out


def wheel_pair(mats, pts, z, track=2.30, width=0.29, taper=0.36, hold=0.62,
               dual=False, vh=0.22):
    """Lay the two wheel tracks of one vehicle down a centreline.

    `track` is the axle track: 2.30 m for a rigid truck / tractor unit, 1.15 m
    for a counterbalance forklift. `dual` doubles the outer wheel into the twin
    tyres of a drive axle, offset 0.34 m - visible at HERO's scale and the kind
    of detail nobody fakes.
    """
    for side in (+1.0, -1.0):
        w = width * rng.uniform(0.88, 1.12)
        ribbon(rng.choice(mats), offset_path(pts, side * track * 0.5), w, z,
               taper=taper * rng.uniform(0.92, 1.0), hold=hold * rng.uniform(0.9, 1.05),
               vh=vh, streak=rng.uniform(0.05, 0.11), phase=rng.uniform(0, 6.28))
        if dual:
            ribbon(rng.choice(mats), offset_path(pts, side * (track * 0.5 + 0.34)),
                   w * 0.8, z, taper=taper * rng.uniform(0.9, 1.0), hold=hold * 0.9,
                   vh=min(0.34, vh * 1.15), streak=rng.uniform(0.06, 0.13),
                   phase=rng.uniform(0, 6.28))


def dot(spread=0.10, h=0.46):
    """UV crop of T_dot_falloff (a single clean radial blob), jittered."""
    return (0.5 + rng.uniform(-spread, spread), 0.5 + rng.uniform(-spread, spread), h, h)


def splat(m, x, y, z, rx, ry, rot=0.0, uv=None):
    """Soft-edged ground splat: one quad, mask cropped from its own part of the
    falloff so no two splats share a silhouette."""
    c, s = math.cos(rot), math.sin(rot)
    def P(dx, dy):
        return (x + dx * c - dy * s, y + dx * s + dy * c, z)
    cu, cv, hu, hv = uv or dot(0.08, 0.46)
    m.blob(P(-rx, -ry), P(rx, -ry), P(rx, ry), P(-rx, ry),
           cu, cv, hu, hv, rng.uniform(0, 6.28))


def wall_streak(m, plane, axis, u0, u1, ztop, zbot, uv=None, hu=None, hv=None, run=True):
    """Vertical streak on a plane. axis 'y': plane is Y=const, u is X.
    axis 'x': plane is X=const, u is Y.

    `run=True` is the default and is what makes these read as RUNS rather than as
    lozenges. It holds U inside a narrow band through the middle of the radial
    mask, so the decal is at full strength right across its width, and puts V from
    the mask centre out to its edge, so it is solid where it starts and dissolves
    where it ends. The first pass sampled the whole blob in both axes and every
    rust streak came back as a soft orange pill floating on the cladding.

    `uv` overrides with a whole crop (use wisp() for an irregular flipbook cell);
    `hu`/`hv` give just the half-extents of a jittered radial crop."""
    if uv is not None:
        cu, cv, hu, hv = uv
    elif run:
        cu, hu = 0.5 + rng.uniform(-0.05, 0.05), 0.055
        cv, hv = 0.5 + rng.uniform(-0.03, 0.03), 0.44
    else:
        cu = 0.5 + rng.uniform(-0.07, 0.07)
        cv = 0.5 + rng.uniform(-0.07, 0.07)
        hu = 0.46 if hu is None else hu
        hv = 0.46 if hv is None else hv
    if axis == "y":
        P = [(u0, plane, zbot), (u1, plane, zbot), (u1, plane, ztop), (u0, plane, ztop)]
    else:
        P = [(plane, u0, zbot), (plane, u1, zbot), (plane, u1, ztop), (plane, u0, ztop)]
    m.blob(*P, cu=cu, cv=cv, hu=hu, hv=hv)


HAZE_LADDER = [0.01512, 0.01206, 0.00954, 0.00756, 0.00598, 0.00475,
               0.00374, 0.00295, 0.00223, 0.00158, 0.00101, 0.00050]
GODRAY_LADDER = [0.01570, 0.01128, 0.00806, 0.00564,
                 0.00393, 0.00272, 0.00185, 0.00121]


def pick(ladder, value):
    """Index of the ladder step nearest `value` in the LOG domain, or None if
    the value has fallen below the bottom rung and the surface should simply
    not be authored. Log domain because these are multiplicative densities: a
    linear nearest-match biases every choice toward the coarse top of the
    ladder."""
    if value < ladder[-1] * 0.72:
        return None
    return min(range(len(ladder)),
               key=lambda i: abs(math.log(ladder[i]) - math.log(max(value, 1e-9))))


def haze_bands(ztop, nb, ramp=1.35, shape=1.55, zbase=0.0, base_ramp=0.0):
    """Horizontal bands of one haze tier: (z0, z1, weight).

    Band thickness grows with height (`ramp`) because the density profile is
    steepest near the ground and that is where the quantisation needs to be
    finest. `weight` is the profile at the band's midpoint, normalised to 1 at
    the tier's own base and reaching 0 exactly at the tier ceiling - so the top
    band is almost transparent and the tier has no visible lid.

    `zbase`/`base_ramp` give a tier a soft BOTTOM as well: weight ramps in with
    a smoothstep from `zbase` to `zbase + base_ramp`. Three tiers with different
    base heights is what turns a stack of lids into a continuous profile - but
    only if the base is soft, because a hard bottom edge is exactly as visible
    as a hard top one."""
    out = []
    for k in range(nb):
        z0 = ztop * (k / nb) ** ramp
        z1 = ztop * ((k + 1) / nb) ** ramp
        zm = 0.5 * (z0 + z1)
        w = max(0.0, 1.0 - zm / ztop) ** shape
        if base_ramp > 0.0:
            u = min(1.0, max(0.0, (zm - zbase) / base_ramp))
            w *= u * u * (3.0 - 2.0 * u)
        out.append((z0, z1, w))
    return out


def beam_rings(meshes, mid, e0, e1, hw, hh, level, roll):
    """One cross-section of a god ray: three nested rings at descending density.

    A constant-opacity quad has a hard rectangular silhouette, and a beam made
    of hard rectangles is a stack of cards. Three nested rings, each rolled to
    its own random angle about the beam axis, and twenty overlapping
    cross-sections along the run, leave no straight edge anywhere."""
    # TWO rings, not three. Mesh-light power scales with AREA x EMISSIVE and
    # is completely indifferent to how transparent the surface is, so a big
    # faint outer ring costs full illumination for almost no visible beam. The
    # 2.05x ring was measured doing exactly that: ablating the god rays alone
    # moved p01_luma 0.079 -> 0.023 and dead_area_frac 0.353 -> 0.284, i.e.
    # they were lighting the whole yard from the middle of the frame.
    for (scale, frac) in ((1.00, 1.00), (1.32, 0.42)):
        idx = pick(GODRAY_LADDER, level * frac)
        if idx is None:
            continue
        r = roll + scale * 1.7
        cr, sr = math.cos(r), math.sin(r)
        a = tuple(e0[k] * cr + e1[k] * sr for k in range(3))
        b = tuple(e1[k] * cr - e0[k] * sr for k in range(3))
        w, h = hw * scale, hh * scale

        def P(sw, sh):
            return (mid[0] + a[0] * sw * w + b[0] * sh * h,
                    mid[1] + a[1] * sw * w + b[1] * sh * h,
                    mid[2] + a[2] * sw * w + b[2] * sh * h)
        meshes[idx].quad(P(-1, -1), P(1, -1), P(1, 1), P(-1, 1))


def beam(meshes, origin, half_w, z_bot, z_top, length, step=1.60, stop=None,
         hw_grow=1.35, gain=1.0):
    """A god ray: cross-section cards stacked along the SUN vector.

    `origin` is the centre of the beam's mouth - an aperture that is actually
    open in 20_architecture: a clear bay between the conveyor bridge's portal
    legs, a missing panel in its skin, a hole in the dock canopy roof. The
    cross-section is carried along SUN, so it descends 0.1219 m per metre
    exactly as the light does, and its lower edge is clamped to the ground: a
    7 deg beam does not go underground, it grazes out along it.

    Cards, not a tube. A ray looking down the beam crosses all twenty of them
    and the shaft reads bright; a ray crossing it sideways crosses one and it
    stays faint. Pickup proportional to path length inside the lit volume is
    what a participating medium does, and it is the only construction that
    survives being looked at end-on - which is exactly how SILHOUETTE_WEST
    looks at these.

    `stop` is a (point, radius) lens keep-out: the run ends before it.
    """
    e0 = (SUN[1], -SUN[0], 0.0)
    n = math.hypot(e0[0], e0[1]) or 1.0
    e0 = (e0[0] / n, e0[1] / n, 0.0)
    e1 = (e0[1] * SUN[2] - e0[2] * SUN[1],
          e0[2] * SUN[0] - e0[0] * SUN[2],
          e0[0] * SUN[1] - e0[1] * SUN[0])
    steps = max(2, int(length / step))
    for i in range(steps + 1):
        s = i / steps
        t = length * s
        c = add(origin, SUN, t)
        if stop is not None and math.dist(c, stop[0]) < stop[1]:
            break
        zb = max(0.015, z_bot + SUN[2] * t)
        zt = z_top + SUN[2] * t
        if zt - zb < 0.25:
            break
        # fade in over the first 18 % of the run and out over the last 32 %,
        # so the beam has neither a chopped mouth nor a chopped tail
        if s < 0.18:
            a = 0.35 + 0.65 * (s / 0.18)
        elif s > 0.68:
            a = 1.0 - 0.88 * ((s - 0.68) / 0.32)
        else:
            a = 1.0
        beam_rings(meshes, (c[0], c[1], (zb + zt) * 0.5), e0, e1,
                   half_w * (1.0 + (hw_grow - 1.0) * s), (zt - zb) * 0.5,
                   GODRAY_LADDER[0] * a * gain, rng.uniform(0, 6.28))


def card(m, x, y, z0, z1, half_w, axis="x", uv=None, rot=0.0):
    """Vertical mist card. axis 'x' -> normal along X (faces east/west)."""
    cu, cv, hu, hv = uv or wisp()
    c, s = math.cos(rot), math.sin(rot)
    dx, dy = (0.0, 1.0) if axis == "x" else (1.0, 0.0)
    ex, ey = dx * c - dy * s, dx * s + dy * c
    P = [(x - ex * half_w, y - ey * half_w, z0), (x + ex * half_w, y + ey * half_w, z0),
         (x + ex * half_w, y + ey * half_w, z1), (x - ex * half_w, y - ey * half_w, z1)]
    m.blob(*P, cu=cu, cv=cv, hu=hu, hv=hv, rot=rng.choice([0.0, 1.5708, 3.1416, 4.7124]))


# =============================================================================
# MATERIALS
# =============================================================================
def tint(luma, ratio):
    """An RGB albedo with a given hue ratio and a given Rec.709 LUMINANCE.

    Every decal albedo in this file was solved from a measured luminance, so it
    has to be authored as a luminance and a hue independently - writing the
    numbers straight into an RGB triple hides the one quantity that matters and
    makes the next person's hue tweak silently change the exposure too.
    """
    k = 0.2126 * ratio[0] + 0.7152 * ratio[1] + 0.0722 * ratio[2]
    s = luma / k
    return (ratio[0] * s, ratio[1] * s, ratio[2] * s)


def mat(name, diff, rough, *, emis=None, e_int=0.0, opacity=None, tex=None,
        mono=1, metallic=0.0, spec=0.5, scale=(1.0, 1.0), doc=""):
    L = []
    a = L.append
    a(f'        def Material "{name}" (')
    a(f'            doc = "{doc}"' if doc else '            doc = ""')
    a('        )')
    a('        {')
    a(f'            token outputs:mdl:surface.connect = </World/FX/Looks/{name}/Shader.outputs:out>')
    a(f'            token outputs:surface.connect = </World/FX/Looks/{name}/Preview.outputs:surface>')
    a('')
    a('            def Shader "Shader"')
    a('            {')
    a('                uniform token info:implementationSource = "sourceAsset"')
    a('                uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@')
    a('                uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"')
    a(f'                color3f inputs:diffuse_color_constant = ({diff[0]:.4f}, {diff[1]:.4f}, {diff[2]:.4f})')
    a(f'                float inputs:reflection_roughness_constant = {rough:.3f}')
    a(f'                float inputs:metallic_constant = {metallic:.3f}')
    a(f'                float inputs:specular_level = {spec:.3f}')
    if emis is not None:
        a('                bool inputs:enable_emission = 1')
        a(f'                color3f inputs:emissive_color = ({emis[0]:.4f}, {emis[1]:.4f}, {emis[2]:.4f})')
        a(f'                float inputs:emissive_intensity = {e_int:.2f}')
    if opacity is not None or tex is not None:
        a('                bool inputs:enable_opacity = 1')
        a(f'                float inputs:opacity_constant = {(opacity if opacity is not None else 1.0):.4f}')
        a('                float inputs:opacity_threshold = 0.0')
    if tex is not None:
        a('                bool inputs:enable_opacity_texture = 1')
        a(f'                asset inputs:opacity_texture = @{tex}@')
        a(f'                int inputs:opacity_mode = {mono}')
        a(f'                float2 inputs:texture_scale = ({scale[0]:.4f}, {scale[1]:.4f})')
    a('                token outputs:out')
    a('            }')
    a('')
    a('            def Shader "Preview"')
    a('            {')
    a('                uniform token info:id = "UsdPreviewSurface"')
    a(f'                color3f inputs:diffuseColor = ({diff[0]:.4f}, {diff[1]:.4f}, {diff[2]:.4f})')
    a(f'                float inputs:roughness = {rough:.3f}')
    a('                float inputs:metallic = 0')
    a(f'                float inputs:opacity = {(opacity if opacity is not None else 1.0):.3f}')
    if emis is not None:
        a(f'                color3f inputs:emissiveColor = ({emis[0]:.4f}, {emis[1]:.4f}, {emis[2]:.4f})')
    a('                token outputs:surface')
    a('            }')
    a('        }')
    return "\n".join(L)


MATERIALS = [
    # ---- scattering media ---------------------------------------------------
    mat("FX_ShaftSun", (0.0, 0.0, 0.0), 1.0, emis=SUN_WARM, e_int=E_SHAFT_SUN,
        opacity=OP_SHAFT, doc="Sunlit air. Fractional-cutout emissive slab - RTX has no VDB medium here."),
    mat("FX_ShaftSunSoft", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.66, 0.38), e_int=E_SHAFT_SUN * 0.55,
        opacity=OP_SHAFT * 0.55, doc="Outer penumbra of a sun shaft."),
    mat("FX_ShaftSky", (0.0, 0.0, 0.0), 1.0, emis=SKY_COOL, e_int=E_SHAFT_SKY,
        opacity=OP_SHAFT_SKY, doc="Storm daylight falling through the roof monitor."),
    mat("FX_ShaftSkySoft", (0.0, 0.0, 0.0), 1.0, emis=(0.56, 0.68, 0.96), e_int=E_SHAFT_SKY * 0.5,
        opacity=OP_SHAFT_SKY * 0.6, doc="Roof-monitor spill, outer."),
    mat("FX_GateBeam", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.58, 0.26), e_int=E_GATE,
        opacity=0.07, doc="The hero gate blowing low sun into the shed."),
    mat("FX_GlowSodium", (0.0, 0.0, 0.0), 1.0, emis=SODIUM, e_int=E_GLOW_HI, opacity=OP_GLOW,
        doc="Sodium halo. Also hides a bare light gizmo behind a believable fitting glow."),
    mat("FX_GlowSodiumDim", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.45, 0.15), e_int=E_GLOW_LO,
        opacity=OP_GLOW * 0.6, doc="Dying sodium tube."),
    mat("FX_GlowMercury", (0.0, 0.0, 0.0), 1.0, emis=MERCURY, e_int=E_GLOW_HI * 0.75,
        opacity=OP_GLOW * 0.85, doc="The three cold mercury swaps."),
    mat("FX_GlowFlood", (0.0, 0.0, 0.0), 1.0, emis=(0.88, 0.94, 1.0), e_int=E_GLOW_HI * 1.1,
        opacity=OP_GLOW * 0.8, doc="Metal-halide mast/gantry flood halo."),
    # ---- particulate --------------------------------------------------------
    # Diffuse deliberately mid-grey, not white: a white lambertian card facing a
    # 4000-intensity sun blows out and the yard fills with cotton wool. Ask me
    # how I know.
    mat("FX_MistCool", (0.155, 0.175, 0.210), 1.0, emis=(0.42, 0.52, 0.70), e_int=E_MIST,
        tex=TEX_WISP, mono=0, doc="Damp ground mist, sky-lit side. One flipbook cell per card."),
    mat("FX_MistWarm", (0.190, 0.155, 0.125), 1.0, emis=(1.0, 0.62, 0.32), e_int=E_MIST * 2.4,
        tex=TEX_WISP, mono=0, doc="Ground mist where the low sun rakes through it."),
    mat("FX_Steam", (0.205, 0.210, 0.220), 1.0, emis=(0.66, 0.68, 0.74), e_int=E_MIST * 1.6,
        tex=TEX_WISP, mono=0, doc="Steam lifting off warm wet asphalt."),
    mat("FX_InteriorAir", (0.0, 0.0, 0.0), 1.0, emis=(0.70, 0.70, 0.74), e_int=4000.0,
        opacity=0.0016, doc="One uniform body of air over the whole shed, so the shaped volumes "
                            "never show their own boundary against the roof."),
    mat("FX_DustMote", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.74, 0.44), e_int=26000.0,
        opacity=0.85, doc="Dust in the beam. Sub-pixel quads; they read as sparkle."),
    # ---- REVISION 3: height-graded atmosphere -------------------------------
    # AN OMNIPBR FACT THAT COST A RENDER: `enable_opacity_texture` REPLACES
    # `opacity_constant`, it does not multiply it. Authoring a 0.0042 constant
    # alongside a mask gives you the mask - i.e. alpha up to 1.0 - and the
    # first attempt at this section rendered SILHOUETTE_WEST as a completely
    # uniform grey-blue rectangle, because the nearest haze plane 6 m from the
    # lens was opaque. Every low-density medium in this file is therefore
    # CONSTANT-opacity and untextured, and any gradient has to come from
    # geometry. That is what the ladder below is for.
    #
    # THE LADDER. Twelve density steps, ratio ~1.27 between neighbours. A haze
    # tier is cut into horizontal bands, each band takes the ladder entry
    # nearest its own point on the tier's falloff curve, and the band edges are
    # JITTERED PER PLANE by +/-0.22 m so a step is never a continuous
    # horizontal line across the frame. Quantisation error is under 13 % and
    # the edges dither out; the profile reads as smooth.
    mat("FX_Haze00", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.01512, doc="Atmosphere density step 0 of 12 (pickup 1.36 per crossing)."),
    mat("FX_Haze01", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.01206, doc="Atmosphere density step 1 of 12 (pickup 1.09 per crossing)."),
    mat("FX_Haze02", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00954, doc="Atmosphere density step 2 of 12 (pickup 0.86 per crossing)."),
    mat("FX_Haze03", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00756, doc="Atmosphere density step 3 of 12 (pickup 0.68 per crossing)."),
    mat("FX_Haze04", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00598, doc="Atmosphere density step 4 of 12 (pickup 0.54 per crossing)."),
    mat("FX_Haze05", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00475, doc="Atmosphere density step 5 of 12 (pickup 0.43 per crossing)."),
    mat("FX_Haze06", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00374, doc="Atmosphere density step 6 of 12 (pickup 0.34 per crossing)."),
    mat("FX_Haze07", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00295, doc="Atmosphere density step 7 of 12 (pickup 0.27 per crossing)."),
    mat("FX_Haze08", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00223, doc="Atmosphere density step 8 of 12 (pickup 0.20 per crossing)."),
    mat("FX_Haze09", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00158, doc="Atmosphere density step 9 of 12 (pickup 0.14 per crossing)."),
    mat("FX_Haze10", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00101, doc="Atmosphere density step 10 of 12 (pickup 0.09 per crossing)."),
    mat("FX_Haze11", (0.0, 0.0, 0.0), 1.0, emis=HAZE_COOL, e_int=E_HAZE,
        opacity=0.00050, doc="Atmosphere density step 11 of 12 (pickup 0.04 per crossing)."),
    # ---- REVISION 3: god rays ----------------------------------------------
    # Same constraint: constant opacity, no mask. A beam's soft edge is
    # therefore built out of THREE NESTED RINGS per cross-section card (core,
    # 1.5x at 45 %, 2.0x at 18 %), each at its own random roll about the beam
    # axis. Twenty overlapping cards of three rings each, all rolled
    # differently, have no straight edge left anywhere.
    mat("FX_GodRay0", (0.0, 0.0, 0.0), 1.0, emis=GODRAY_WARM, e_int=E_GODRAY,
        opacity=0.01570, doc="Sunlit air, beam density step 0 of 8 (pickup 10.99)."),
    mat("FX_GodRay1", (0.0, 0.0, 0.0), 1.0, emis=GODRAY_WARM, e_int=E_GODRAY,
        opacity=0.01128, doc="Sunlit air, beam density step 1 of 8 (pickup 7.90)."),
    mat("FX_GodRay2", (0.0, 0.0, 0.0), 1.0, emis=GODRAY_WARM, e_int=E_GODRAY,
        opacity=0.00806, doc="Sunlit air, beam density step 2 of 8 (pickup 5.64)."),
    mat("FX_GodRay3", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.72, 0.46), e_int=E_GODRAY,
        opacity=0.00564, doc="Sunlit air, beam density step 3 of 8 (pickup 3.95)."),
    mat("FX_GodRay4", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.72, 0.46), e_int=E_GODRAY,
        opacity=0.00393, doc="Sunlit air, beam density step 4 of 8 (pickup 2.75)."),
    mat("FX_GodRay5", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.72, 0.46), e_int=E_GODRAY,
        opacity=0.00272, doc="Sunlit air, beam density step 5 of 8 (pickup 1.90)."),
    mat("FX_GodRay6", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.72, 0.46), e_int=E_GODRAY,
        opacity=0.00185, doc="Sunlit air, beam density step 6 of 8 (pickup 1.30)."),
    mat("FX_GodRay7", (0.0, 0.0, 0.0), 1.0, emis=(1.0, 0.72, 0.46), e_int=E_GODRAY,
        opacity=0.00121, doc="Sunlit air, beam density step 7 of 8 (pickup 0.85)."),
    # ---- decals -------------------------------------------------------------
    # ==========================================================================
    # REVISION 4 - THE DECAL PHOTOMETRY WAS MEASURED, NOT REASONED ABOUT.
    # ==========================================================================
    # Round-4 blocker: the tyre scuff read as "white plastic tubing scattered
    # over a maquette" - luma 0.312 against asphalt at 0.10-0.15. Round 3 had
    # already tried to fix that by lowering the albedo, and the note below this
    # one records that reasoning. It was wrong about the MECHANISM, so it could
    # not work. Here is the measurement that settles it.
    #
    # Four renders of HERO_ESTABLISH and DETAIL_WET_APRON at --final, identical
    # except for the decal materials:
    #     nodecal  every decal group ablated (FX_SKIP)            -> host surface
    #     probeK   every decal diffuse forced to (0,0,0)          -> "black" decal
    #     probeM   diffuse (0,0,0) AND specular_level 0, rough 1  -> matte black
    #     probeW   every decal diffuse forced to (0.5,0.5,0.5)
    # Measured at the decal pixels (mask = the meshes projected through the real
    # camera transform), linear luminance:
    #
    #     HERO       host    probeM   probeK   ->  probeK/host
    #     Scuff      0.119   0.039    0.155        1.30
    #     Soot       0.075   0.022    0.135        1.79
    #     WetFan     0.208   0.059    0.336        1.61
    #     Rust_south 0.360   0.142    0.352        0.98
    #     CanopyCol  0.041   0.001    0.224        5.48
    #     DETAIL     host    probeM   probeK
    #     Scuff      0.088   0.012    0.504        5.76
    #     DockFace   0.125   0.006    0.490        3.93
    #
    # READ probeK: a decal with ZERO ALBEDO was still up to 5.8x BRIGHTER than
    # the surface under it. No albedo can fix that, which is why round 3's
    # albedo cut did not. THE MECHANISM IS SPECULAR. A decal is a perfectly flat
    # card; these cameras see the ground at 78-87 deg from its normal, and at
    # grazing incidence the Schlick term is (1-cos)^5 -> ~0.6 whatever F0 is, so
    # the card mirrors the bright storm dome straight into the lens. The host
    # asphalt escapes it because it has aggregate relief and a normal map to
    # scatter that lobe; a flat card has neither. probeM - the same black card
    # with specular_level 0 and roughness 1 - drops to 0.012-0.039, i.e. WELL
    # BELOW the host, which is what a stain is supposed to do.
    #
    # SO: EVERY DECAL IN THIS FILE IS NOW MATTE. specular_level = 0.0 and
    # roughness = 1.0, ground and wall alike. A stain is pigment sitting in the
    # host surface; it has no gloss coat of its own. The only exceptions are the
    # two water elements (FX_WetFan, FX_DripLine) and even they are pulled right
    # down, because "wet ground is shiny" is 10_terrain's job to say - it owns
    # the puddles and the wet asphalt material, and a second mirror laid on top
    # of that one is exactly the milky patch the review kept seeing.
    #
    # WITH THE SPECULAR GONE THE RESPONSE IS EXACTLY LINEAR IN ALBEDO:
    #     out(a) = probeM + a * gain,   gain = 2 * (probeW - probeK)
    # (gain = alpha*E, the diffuse response; it is independent of the specular
    # setting because probeW and probeK share it.) So every albedo below is
    # SOLVED, not guessed: a = (target_ratio * host - probeM) / gain, with
    # target_ratio the luminance the decal should read as a fraction of its
    # host. Measured gains: 0.94 (yard at HERO), 0.15-0.21 (dock at DETAIL),
    # 0.81-1.14 (walls at HERO). The yard and the dock differ by 6x because they
    # genuinely receive 6x different irradiance - the dock is in shadow - so one
    # albedo lands at 0.50 of host in the sunlit yard and 0.19 in the dock
    # shade. Both are darker than the host, which is the requirement; a mark
    # that is darker in shadow than in sun is correct, not a bug.
    #
    # Target ratios (decal luminance / host luminance) used to solve these:
    #   soot 0.30, fresh oil 0.35, tyre scuff 0.50, old scuff 0.65, old oil 0.60,
    #   damp 0.80, algae 0.72, water stain 0.80, rust 0.85, dilute rust 0.95,
    #   efflorescence 1.30 (salt bloom is the one thing that IS paler), bird mess
    #   1.60. Nothing else in this file is allowed above 1.0.
    #
    # AND THE WALL MATERIALS ARE NOW SPLIT PER HOST SURFACE. One FX_RustBleed was
    # shared by the sunlit warehouse cladding (host 0.360), the dock canopy steel
    # in shadow (host 0.041), the dock face (0.178) and the conveyor bridge
    # (0.517). A single albedo across a 9x range of host brightness cannot be
    # right anywhere: it measured 0.98x on the cladding and 5.5-11x on the canopy
    # columns, which is why the canopy read as if the rust were glowing. Four
    # hosts, four materials, four solved albedos.
    #
    # ---- the round-3 note, kept because its DATA is still good even though its
    # ---- conclusion was wrong (it blamed albedo; the cause was specular) ------
    # Round-3 blocker: the tyre scuff delivered at sRGB 0.53 against surrounding
    # asphalt at 0.377 in HERO_ESTABLISH - 1.41x BRIGHTER than the surface it is
    # supposed to be staining. "White plastic tubing scattered over a maquette".
    #
    # I measured the mechanism instead of guessing at it. Two extra renders:
    #   SCUFFRG  - FX_TyreScuff forced to (1,0,0) and FX_TyreScuffOld to (0,1,0).
    #              The marks came back SATURATED red and green, and the channel
    #              whose albedo was 0 came back at linear 0.0134. So (a) the MDL
    #              binds and diffuse_color_constant is honoured, and (b) the
    #              albedo-independent additive term (haze in front of the ground)
    #              is only 0.013 linear. There is no big specular offset.
    #   SCUFFA   - spec 0.35 -> 0.0, roughness 0.62 -> 1.0, albedo 0.042 -> 0.030.
    #              Scuff fell 0.530 -> 0.429 sRGB. Real, but only 40 % of the gap.
    #
    # Solving out:  linear_out = 0.0134 + irradiance * albedo, and the SCUFFRG /
    # SCUFFA pair pins the yard's irradiance at HERO to (4.25, 5.4, 8.2) linear
    # render units. The same equation run backwards on the ablated ground
    # (NOSCUFF core, linear 0.099 / 0.098 / 0.120) gives the ASPHALT an effective
    # albedo of about (0.020, 0.016, 0.013) - WARM and far darker than anyone
    # writing these decals assumed. 0.042 "near-black" is in fact TWICE the
    # albedo of the asphalt, and neutral grey against a warm surface under a
    # blue-dominant dome, which is why the marks came out pale AND cold.
    #
    # So every flat ground decal below is now authored in the 0.005-0.020 band
    # and TINTED WARM, against a measured asphalt of (0.020, 0.016, 0.013):
    #   soot < fresh oil < tyre scuff < old oil < old scuff < ASPHALT < damp
    # That ordering is the whole point. Wall decals are NOT in this band - a
    # vertical surface is not seen at 84 deg incidence and is lit by a different
    # part of the dome, so FX_RustBleed/WaterStain/Efflor/GrungeWash keep their
    # values and are deliberately left alone.
    #
    # specular_level 0.0 on the matte ones is not decoration either. A flat card
    # is a perfect plane, so at HERO's 84 deg grazing incidence its Schlick term
    # is (1-cos)^5 = 0.59 whatever F0 is; the asphalt escapes that only because
    # it has aggregate relief to scatter the lobe. Weakening specular_level does
    # not help, deleting the layer does.
    # ---- ground decals. All matte: spec 0.0, roughness 1.0. -----------------
    mat("FX_TyreScuffFresh", tint(0.0015, (1.00, 0.92, 0.86)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Fresh rubber off a locked or scrubbing wheel - the blackest mark on the yard. "
            "Solved to 0.32x host luminance at HERO."),
    mat("FX_TyreScuff", tint(0.0025, (1.00, 0.90, 0.82)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rubber laid down by a turning truck. Solved to 0.50x host luminance at HERO "
            "(0.19x in the dock shade, where there is 6x less light on it)."),
    mat("FX_TyreScuffOld", tint(0.0040, (1.00, 0.92, 0.86)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Older scuff, most of the rubber walked off. Solved to 0.65x host."),
    mat("FX_OilStain", tint(0.0004, (1.00, 0.94, 0.88)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Fresh oil, 0.35x host. Matte: the sheen a real oil film has is a mirror at "
            "grazing incidence and that mirror is what turned these pale."),
    mat("FX_OilOld", tint(0.0028, (1.00, 0.92, 0.85)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Old oil soaked into the aggregate, 0.55x host."),
    # WATER. The cool half of a Hackney-Yard frame is genuinely water mirroring a
    # blue-grey dome - but 10_terrain owns the puddles and the wet asphalt look,
    # and it already does that. A second specular sheet laid on top of it is what
    # the review kept reading as a milky patch: measured, this material at spec
    # 0.68 rendered its own footprint 1.61x BRIGHTER than the ground it lies on.
    # It is now a matte DARKENING, which is the other true half of "wet": water
    # fills the pores and drops the diffuse albedo.
    mat("FX_WetFan", tint(0.0072, (0.95, 1.00, 1.12)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rain blown in through a gate, and damp patches across the yard: a matte "
            "darkening at 0.75x host, tinted cool. Gloss is 10_terrain's to author."),
    mat("FX_Soot", tint(0.0004, (1.00, 0.98, 0.96)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Scorch, 0.30x host - the blackest ground look in the map."),
    mat("FX_BirdMess", tint(0.0500, (1.00, 0.99, 0.92)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Pigeons live under the canopy. The only ground decal deliberately ABOVE its "
            "host, at about 1.6x - and 1.6x, not the 5x that made the deck read as snow."),
    # ---- wall decals, split per host surface --------------------------------
    # One shared rust material could not serve a host range of 0.041 (canopy
    # steel in shadow) to 0.517 (bridge skin against the sky). Measured
    # host luminance and solved albedo are quoted on each.
    mat("FX_RustWall", tint(0.0300, (1.00, 0.44, 0.17)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rust bleed on the warehouse south cladding (host 0.360 -> 0.84x)."),
    mat("FX_RustWallPale", tint(0.0300, (1.00, 0.53, 0.27)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Dilute rust wash on the cladding (host 0.211 -> 0.94x)."),
    mat("FX_RustCanopy", tint(0.0015, (1.00, 0.44, 0.17)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rust on the dock canopy columns and fascia. Host measured 0.041 - the darkest "
            "surface any decal in this file sits on, and where the old shared material "
            "measured 5.5-11x too bright."),
    mat("FX_RustDock", tint(0.0550, (1.00, 0.44, 0.17)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rust off the dock levellers and bumpers, and on the office blockwork "
            "(host 0.178 -> 0.46x, read close in DETAIL_WET_APRON)."),
    mat("FX_RustBridge", tint(0.0061, (1.00, 0.44, 0.17)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Rust on the conveyor bridge skin (host 0.517 -> 0.85x)."),
    mat("FX_WaterWall", tint(0.0080, (0.96, 1.00, 0.98)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Gutter staining on the cladding (host 0.351 -> 0.80x)."),
    mat("FX_WaterCanopy", tint(0.0012, (0.96, 1.00, 0.98)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Water staining down the canopy columns (host 0.044 -> 0.81x)."),
    mat("FX_WaterDock", tint(0.0200, (0.96, 1.00, 0.98)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Water staining on the dock face and office (host 0.125 -> 0.45x)."),
    mat("FX_WaterBridge", tint(0.0047, (0.96, 1.00, 0.98)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Water staining on the bridge skin. Host 0.643, but the OCCLUSION floor alone "
            "is 0.518 there (the bridge is 22 m out through haze), so almost all of the "
            "0.81x comes from covering the surface, not from pigment."),
    mat("FX_GrungeWall", tint(0.0041, (1.00, 0.97, 0.90)), 1.0, tex=TEX_WISP, mono=0, spec=0.0,
        doc="Broad dirt wash on the cladding (host 0.433 -> 0.80x). Flipbook cell, "
            "stretched, for an irregular edge a radial blob cannot give."),
    mat("FX_GrungeBridge", tint(0.0041, (1.00, 0.97, 0.90)), 1.0, tex=TEX_WISP, mono=0, spec=0.0,
        doc="Dirt wash on the bridge skin."),
    mat("FX_Algae", tint(0.0200, (0.70, 1.00, 0.55)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Permanently wet concrete grows this (host 0.069 -> 0.42x)."),
    mat("FX_Efflor", tint(0.0700, (1.00, 0.99, 0.95)), 1.0, tex=TEX_DOT, mono=1, spec=0.0,
        doc="Salt bloom out of a blockwork joint - the one wall decal that is legitimately "
            "PALER than its host, at 1.11x. It was 5.0x."),
    mat("FX_DripLine", tint(0.0150, (0.92, 0.98, 1.00)), 0.20, opacity=0.30, spec=0.25,
        doc="A filament of water still coming off the gutter. The only element in this "
            "file that keeps a real specular lobe, because a 12 mm wide falling drip line "
            "IS a highlight - but at spec 0.25 rather than 0.9, which measured 1.40x its "
            "host."),
]


# =============================================================================
# BUILD
# =============================================================================
groups = []          # (scope_name, doc, [M...])


SKIP = set(filter(None, __import__("os").environ.get("FX_SKIP", "").split(",")))


def G(name, doc, meshes):
    if name in SKIP:
        print("  (skipping group " + name + ")")
        return
    ms = [m for m in meshes if not m.empty]
    if ms:
        groups.append((name, doc, ms))


# -----------------------------------------------------------------------------
# 1. INTERIOR - sun bars in through the open west roller doors
# -----------------------------------------------------------------------------
# WestDoor2 (Y 48.27..52.88) is 9 slats short of shut: the opening is the bottom
# ~1.9 m and it sits square on aisle A3 (clear band Y 46.53..52.47). Light that
# comes through it travels along SUN, dropping 0.1307 m per metre east, so the
# wedge dies on the slab about 14 m in. That is the shaft INTERIOR_AISLE needs.
core = M("Bars_core", "FX_ShaftSun", two_sided=True)
soft = M("Bars_penumbra", "FX_ShaftSunSoft", two_sided=True)
for i, (y0, y1) in enumerate([(48.55, 49.30), (49.55, 50.35), (50.60, 51.30), (51.55, 52.25)]):
    ztop = 1.86 - 0.05 * i
    x0 = -37.80
    for seg in range(6):
        t0, t1 = seg * 1.9, (seg + 1) * 1.9
        a = [(x0 + SUN[0] * t0, y0 + SUN[1] * t0, 0.002 + max(0.0, 0.0)),
             (x0 + SUN[0] * t0, y1 + SUN[1] * t0, 0.002),
             (x0 + SUN[0] * t0, y1 + SUN[1] * t0, ztop + SUN[2] * t0),
             (x0 + SUN[0] * t0, y0 + SUN[1] * t0, ztop + SUN[2] * t0)]
        b = [(x0 + SUN[0] * t1, y0 + SUN[1] * t1, 0.002),
             (x0 + SUN[0] * t1, y1 + SUN[1] * t1, 0.002),
             (x0 + SUN[0] * t1, y1 + SUN[1] * t1, ztop + SUN[2] * t1),
             (x0 + SUN[0] * t1, y0 + SUN[1] * t1, ztop + SUN[2] * t1)]
        if ztop + SUN[2] * t1 < 0.05:
            break
        prism(core if seg < 4 else soft, a, b)
# the penumbra: one fat soft wedge over the whole doorway
for t in (0,):
    y0, y1, ztop, x0 = 48.20, 52.60, 2.15, -37.85
    a = [(x0, y0, 0.0), (x0, y1, 0.0), (x0, y1, ztop), (x0, y0, ztop)]
    L = 15.5
    b = [(x0 + SUN[0] * L, y0 + SUN[1] * L, 0.0), (x0 + SUN[0] * L, y1 + SUN[1] * L, 0.0),
         (x0 + SUN[0] * L, y1 + SUN[1] * L, max(0.06, ztop + SUN[2] * L)),
         (x0 + SUN[0] * L, y0 + SUN[1] * L, max(0.06, ztop + SUN[2] * L))]
    prism(soft, a, b)

# WestDoor1 is wide open (Y 38.16..42.76, full 3.8 m) - that wedge lands in A2 and
# rakes the flank of rack run S1. Seen through the rack gaps from A3.
for i, (y0, y1) in enumerate([(38.40, 39.40), (39.70, 40.80), (41.10, 42.10), (42.30, 42.70)]):
    ztop = 3.72
    x0 = -37.80
    L = 22.0
    a = [(x0, y0, 0.0), (x0, y1, 0.0), (x0, y1, ztop), (x0, y0, ztop)]
    b = [(x0 + SUN[0] * L, y0 + SUN[1] * L, 0.0), (x0 + SUN[0] * L, y1 + SUN[1] * L, 0.0),
         (x0 + SUN[0] * L, y1 + SUN[1] * L, max(0.05, ztop + SUN[2] * L)),
         (x0 + SUN[0] * L, y0 + SUN[1] * L, max(0.05, ztop + SUN[2] * L))]
    prism(soft, a, b)
G("SunBars_West", "Sun through the two open west roller doors, traced along the real KeySun vector.",
  [core, soft])

# -----------------------------------------------------------------------------
# 2. INTERIOR - roof monitor curtains
# -----------------------------------------------------------------------------
# Clerestory_South (0,38.2,15.3) / Clerestory_North (0,52.8,15.3) / RoofMonitor_Down
# (0,45.5,16.6) pour cool daylight straight down the length of the shed. The roof
# trusses chop it into bars, so it is authored as curtains ACROSS X - which is
# also the only orientation INTERIOR_AISLE (looking due east) sees face-on.
cur = M("Curtains", "FX_ShaftSky", two_sided=True)
cur_s = M("Curtains_spill", "FX_ShaftSkySoft", two_sided=True)
# One uniform body of air over the whole hall, above the racking. Without it the
# curtains' own Y and X limits become visible: the first calibrated render had
# cone-shaped POCKETS of un-hazed dark ceiling in the top corners of
# INTERIOR_AISLE, which is the boundary of the hazed volume, not a shadow.
# 3.15 m clears the 3.011 m racking; 13.6 stays under the 14.33 m truss.
air = M("InteriorAir", "FX_InteriorAir", two_sided=True)
box(air, (-37.2, 16.0, 3.15), (37.2, 76.0, 13.60), uv_scale=10.0)
# A curtain's bottom edge is a hard horizontal line, so it is parked at Z 3.15 -
# 0.14 m clear of the 3.011 m racking - where it reads as "the light stops at the
# top of the racks" instead of as a floating edge. The soft tier below the main
# one turns the single step into two.
#
# REVISION 3 - THE CURTAINS NOW REACH THE FLOOR, IN THE AISLES ONLY.
# Stopping every curtain at Z 3.15 was a compromise made to avoid intersecting
# the 3.011 m racking, and it cost the interior the thing that makes a
# warehouse interior read: a column of daylight standing ON the slab. The
# racking is not continuous - LAYOUT 5.16 puts six E-W rack runs on an 8.00 m
# pitch, each 2.067 m deep, which leaves 5.94 m aisles between them and 13.5 m
# of open loading floor south of RR-S3. Over an AISLE there is nothing at all
# to intersect between Z 0 and Z 3.15, so the drop is authored there and only
# there. The result down INTERIOR_AISLE is a receding series of cool vertical
# bars crossing the aisle and landing on the wet slab - the shafts the lighting
# owner's Clerestory / RoofMonitor RectLights are pooling on the floor from
# their side, finally given air to be visible in.
#
# AISLE_BANDS are the Y ranges with no racking in them, taken off LAYOUT 5.16
# (run centres 29.5 / 37.5 / 45.5 / 53.5 / 61.5 / 69.5, each +/- 1.033) with a
# 0.13 m margin so a drop never touches a rack upright.
AISLE_BANDS = [(16.20, 28.34), (30.66, 36.34), (38.66, 44.34), (46.66, 52.34),
               (54.66, 60.34), (62.66, 68.34), (70.66, 75.90)]
# INTERIOR_AISLE stands at (-35.5, 49.4, 2.40). A full-height drop closer than
# this flares the lens; the first curtain at X = -33 is 2.5 m away and would
# have filled the frame with a white wall.
INT_LENS_X, INT_LENS_KEEPOUT = -35.5, 9.0

for k, x in enumerate(range(-33, 37, 8)):
    w = 1.10 + 0.22 * math.sin(k * 1.7)
    y0 = 33.0 + 0.9 * math.sin(k * 0.9)
    y1 = 62.0 + 1.1 * math.cos(k * 1.3)
    ztop, zmid = 12.40, 5.20 + 0.30 * ((k * 7) % 5)
    box(cur, (x - w * 0.5, y0, zmid), (x + w * 0.5, y1, ztop), uv_scale=4.0)
    box(cur_s, (x - w * 0.5, y0, 3.15), (x + w * 0.5, y1, zmid), uv_scale=4.0)
    if x - INT_LENS_X < INT_LENS_KEEPOUT:
        continue
    for (ay0, ay1) in AISLE_BANDS:
        b0, b1 = max(y0, ay0), min(y1, ay1)
        if b1 - b0 < 0.6:
            continue
        # narrower than the curtain above it: a shaft converges slightly as it
        # comes down, and the taper is what stops the drop reading as a box
        dw = w * 0.78
        box(cur_s, (x - dw * 0.5, b0 + 0.25, 0.03), (x + dw * 0.5, b1 - 0.25, 3.15),
            uv_scale=4.0)
# and the same for the south loading floor, where the monitor is over open slab -
# 13.5 m of bare concrete with no racking on it at all, so these run all the way
# down without needing to be cut
for k, x in enumerate(range(-26, 22, 11)):
    box(cur_s, (x - 1.3, 17.6, 4.6), (x + 1.3, 30.0, 12.2), uv_scale=6.0)
    box(cur_s, (x - 1.0, 18.2, 0.03), (x + 1.0, 28.2, 4.6), uv_scale=6.0)
G("RoofMonitor", "Storm daylight through the roof monitor, chopped into bars by the trusses, over "
                 "one uniform body of interior air. The bars drop to the slab wherever they cross "
                 "an aisle (no racking to intersect there), so the interior gets shafts that land "
                 "on the floor instead of stopping in mid-air at rack height.",
  [air, cur, cur_s])

# -----------------------------------------------------------------------------
# 3. HERO GATE - the map's focal point, blowing low sun both ways
# -----------------------------------------------------------------------------
gb = M("GateBeam", "FX_GateBeam", two_sided=True)
gs = M("GateSpill", "FX_ShaftSunSoft", two_sided=True)
# inside: a widening wedge from the 7.39 m gate, running along SUN
a = [(-3.10, 15.02, 0.02), (3.12, 15.02, 0.02), (3.12, 15.02, 4.40), (-3.10, 15.02, 4.40)]
L = 13.0
b = [(-4.30 + SUN[0] * L, 15.02 + SUN[1] * L, 0.02), (4.55 + SUN[0] * L, 15.02 + SUN[1] * L, 0.02),
     (4.55 + SUN[0] * L, 15.02 + SUN[1] * L, max(0.1, 4.40 + SUN[2] * L)),
     (-4.30 + SUN[0] * L, 15.02 + SUN[1] * L, max(0.1, 4.40 + SUN[2] * L))]
prism(gb, a, b)
# outside: the gate mouth glowing back at the yard (this is what HERO_ESTABLISH reads)
a = [(-3.60, 14.96, 0.02), (3.62, 14.96, 0.02), (3.62, 14.96, 5.10), (-3.60, 14.96, 5.10)]
b = [(-5.60, 8.60, 0.02), (5.80, 8.60, 0.02), (5.80, 8.60, 4.30), (-5.60, 8.60, 4.30)]
prism(gs, a, b)
# personnel-door slot, X -1.74..1.73 Z 1.90..2.57 - a thin bright bar
a = [(-1.70, 15.00, 1.94), (1.69, 15.00, 1.94), (1.69, 15.00, 2.53), (-1.70, 15.00, 2.53)]
b = [(-2.40 + SUN[0] * 7, 15.0 + SUN[1] * 7, 1.10), (2.40 + SUN[0] * 7, 15.0 + SUN[1] * 7, 1.10),
     (2.40 + SUN[0] * 7, 15.0 + SUN[1] * 7, 1.72), (-2.40 + SUN[0] * 7, 15.0 + SUN[1] * 7, 1.72)]
prism(gb, a, b)
G("HeroGate", "The 7.39 m gate as a light source: wedge in, spill out.", [gb, gs])

# -----------------------------------------------------------------------------
# 4. PRACTICAL GLOWS - one per fitting, positions read out of 60_lighting.usda
# -----------------------------------------------------------------------------
HIGHBAY = [
    (-26.85, 18.05, 8.31, "hi"), (-13.16, 18.05, 8.31, "hi"), (-6.85, 18.05, 8.31, "hg"),
    (0.0, 18.05, 8.31, "dim"), (6.84, 18.05, 8.31, "dim"), (13.15, 18.05, 8.31, "dim"),
    (-6.85, 32.98, 10.57, "hi"), (6.84, 32.98, 10.57, "hi"), (-20.0, 32.99, 10.57, "hi"),
    (-26.85, 45.52, 9.51, "hi"), (-20.0, 45.52, 9.51, "hi"), (-13.16, 45.52, 9.51, "hg"),
    (-6.85, 45.52, 9.51, "dim"), (6.84, 45.52, 9.51, "hi"), (13.15, 45.52, 9.51, "hi"),
    (20.0, 45.52, 9.51, "dim"), (26.84, 45.52, 9.51, "hg"),
    (-26.85, 58.09, 10.56, "hi"), (-20.0, 58.09, 10.56, "hi"), (-6.85, 58.09, 10.56, "hi"),
    (6.84, 58.09, 10.56, "hi"), (13.15, 58.09, 10.56, "hi"), (20.0, 58.09, 10.56, "hi"),
    (-26.85, 73.0, 8.26, "hi"), (-6.85, 73.0, 8.26, "hi"), (6.84, 73.0, 8.26, "hi"),
    (26.84, 73.0, 8.26, "hi"),
]
MATBY = {"hi": "FX_GlowSodium", "hg": "FX_GlowMercury", "dim": "FX_GlowSodiumDim"}
hb = {k: M("HighBay_" + k, v, two_sided=True) for k, v in MATBY.items()}
for x, y, z, kind in HIGHBAY:
    m = hb[kind]
    r = 0.34
    # stop the cone above the 3.011 m racking so no haze ever clips solid geometry
    cone(m, (x, y, z - 0.08), r, (x, y, 3.45), 2.35 if kind != "dim" else 1.35, seg=16)
    sphere(m, (x, y, z - 0.05), 0.52 if kind != "dim" else 0.34, seg=12, rings=6)
G("HighBayGlow", "27 measured high-bay fittings, each with its own scatter cone. Cones stop at "
                 "Z 3.45 so they never intersect the 3.011 m racking.", list(hb.values()))

WALLPACK = [(-34.0, "hi"), (-10.0, "hg"), (2.0, "hi"), (14.0, "dim"), (26.0, "hi")]
wp = {k: M("WallPack_" + k, v, two_sided=True) for k, v in MATBY.items()}
for x, kind in WALLPACK:
    m = wp[kind]
    cone(m, (x, 14.55, 5.14), 0.28, (x + 0.2, 12.4, 0.35), 2.35 if kind != "dim" else 1.4, seg=16)
    sphere(m, (x, 14.58, 5.18), 0.48 if kind != "dim" else 0.30, seg=12, rings=6)
G("WallPackGlow", "South-wall sodium packs. These are what put the specular on the wet yard in "
                  "LANE_EYE_YARD.", list(wp.values()))

DOCKC = [(-44.0, "hi"), (-30.0, "hi"), (-16.0, "hi"), (-6.0, "hi"), (2.0, "hi"), (26.0, "dim")]
dc = {k: M("DockCanopy_" + k, v, two_sided=True) for k, v in MATBY.items()}
for x, kind in DOCKC:
    m = dc[kind]
    cone(m, (x, -21.5, 5.12), 0.30, (x, -21.5, 0.55), 2.45 if kind != "dim" else 1.5, seg=16)
    sphere(m, (x, -21.5, 5.16), 0.42 if kind != "dim" else 0.26, seg=14, rings=7)
# the bay lamp on the dock face, the one that has to be reflected in P4
cone(dc["hi"], (-6.6, -22.10, 1.22), 0.18, (-6.6, -23.9, 0.10), 0.95, seg=14)
sphere(dc["hi"], (-6.6, -22.10, 1.25), 0.30, seg=12, rings=6)
G("DockCanopyGlow", "Canopy fascia sodiums. The halo also gives the bare emitter a fitting to sit "
                    "in instead of floating as a white disc.", list(dc.values()))

fl = M("Floods", "FX_GlowFlood", two_sided=True)
flw = M("Floods_warm", "FX_GlowSodium", two_sided=True)
# Halo only, and a small one. The first calibrated pass gave every flood a 2.1x
# outer shell plus a 3.6 m-base cone; at 22 m the Bridge_East cone filled a
# quarter of SILHOUETTE_WEST and read unmistakably as a lampshade made of
# polygons. Outdoors the RTX fog is already doing the glow - the geometry only
# has to give the bare emitter something to sit inside.
for (x, y, z, r, warm) in [(-60.0, -2.0, 8.0, 0.62, False), (44.0, 26.0, 9.0, 0.52, False),
                           (64.0, 26.0, 9.0, 0.52, False), (-54.0, 8.0, 4.5, 0.40, True),
                           (-30.0, 3.5, 5.05, 0.34, True), (25.9, -3.5, 5.75, 0.40, True),
                           (45.0, 8.0, 4.2, 0.36, True)]:
    sphere(flw if warm else fl, (x, y, z), r, seg=14, rings=7)
# only the fuel-bay mast keeps a beam, and only because it is 30 m from any lens
cone(fl, (-60.0, -2.0, 7.9), 0.5, (-58.6, -5.6, 1.6), 2.4, seg=16)
# the broken flickering unit over the dock-office stair reads green-sick
brk = M("Floods_broken", "FX_GlowMercury", two_sided=True)
sphere(brk, (47.0, -27.0, 4.2), 0.34, seg=12, rings=6)
G("FloodGlow", "Mast, gantry, trestle, bridge and platform floods - halos, not cones.",
  [fl, flw, brk])

# -----------------------------------------------------------------------------
# 5. GROUND MIST over the wet yard
# -----------------------------------------------------------------------------
mc = M("Mist_cool", "FX_MistCool")
mw = M("Mist_warm", "FX_MistWarm")
st = M("Steam", "FX_Steam")
# Ground-hugging only. The first pass put 90 waist-to-head-height cards across
# the yard and LANE_EYE_YARD came back looking like a dry-ice party. Mist here is
# a 0.35-0.9 m film that breaks up the reflection of the wet slab, nothing more.
CLEAR = [(-44.0, 2.0, 11.0), (48.0, -8.0, 9.0), (-12.0, -10.5, 6.0),
         (-54.0, -38.0, 9.0), (-35.5, 49.4, 5.0)]        # camera keep-out spheres
def clear_of_lens(x, y):
    return all(math.hypot(x - cx, y - cy) > r for (cx, cy, r) in CLEAR)

for i in range(34):
    x, y = rng.uniform(-52, 52), rng.uniform(-16.5, 13.5)
    if not clear_of_lens(x, y):
        continue
    m = mw if (x < -4 or rng.random() < 0.3) else mc
    card(m, x, y, 0.015, rng.uniform(0.35, 0.95), rng.uniform(2.2, 6.0) * 0.5,
         axis="x", uv=wisp(row=rng.randrange(4, 8)))
for i in range(16):
    x, y = rng.uniform(-50, 46), rng.uniform(-20.0, 13.0)
    if not clear_of_lens(x, y):
        continue
    card(rng.choice([mc, mw]), x, y, 0.015, rng.uniform(0.3, 0.8),
         rng.uniform(2.0, 5.0) * 0.5, axis="y", uv=wisp(row=rng.randrange(4, 8)))
# steam off the six authored puddles and off the wet dock apron
PUDDLE = [(-30, -3, 9.0, 5.0), (2, -9, 12.0, 6.0), (26, 6, 5.0, 4.0),
          (-8.5, -17.5, 7.0, 4.5), (44, -6, 6.0, 3.5), (-48, 9, 4.0, 3.0)]
for (px, py, sx, sy) in PUDDLE:
    for i in range(4):
        x = px + rng.uniform(-sx * 0.55, sx * 0.55)
        y = py + rng.uniform(-sy * 0.55, sy * 0.55)
        if not clear_of_lens(x, y):
            continue
        card(st, x, y, 0.01, rng.uniform(0.4, 1.1), rng.uniform(0.7, 1.6),
             axis="x", uv=wisp(row=rng.randrange(4, 8)))
for i in range(14):     # the algae strip at the dock foot steams too
    card(st, rng.uniform(-45, 29), rng.uniform(-21.6, -20.4), 0.01,
         rng.uniform(0.35, 0.95), rng.uniform(0.7, 1.6), axis="x",
         uv=wisp(row=rng.randrange(4, 8)))
# interior: damp air lifting off the slab where the rain blows in through the gates
for i in range(12):
    x, y = rng.uniform(-36, 2), rng.uniform(15.4, 22.5)
    card(st, x, y, 0.01, rng.uniform(0.3, 0.9), rng.uniform(0.8, 1.9), axis="x",
         uv=wisp(row=rng.randrange(4, 8)))
G("GroundMist", "A 0.35-0.9 m film only, cards normal to X (the axis three of the five shots look "
                "down), each one a single faint cell of the 8x8 smoke_wisp flipbook. Camera "
                "keep-out spheres stop any of it landing on the lens.", [mc, mw, st])

# -----------------------------------------------------------------------------
# 5b. THE ATMOSPHERE - three stacked height-graded haze tiers
# -----------------------------------------------------------------------------
# WHAT WAS WRONG. The previous build had two sets of flat-topped scrim boxes:
# a low set capped at ~1.6 m and nine tall ones running Z 2.55 to a ragged
# 6.5-9.5 m. Both are SLABS OF CONSTANT DENSITY, so both have a hard top edge,
# and SILHOUETTE_WEST - which pitches 6 deg up and therefore climbs 0.1055 m of
# Z per metre of range - crosses that edge at a well-defined distance. The
# result reads exactly as the review put it: a milky plate with a visible upper
# boundary and no gradient toward the horizon. A constant-density slab cannot
# produce a gradient; that is not a tuning problem.
#
# WHAT IS HERE NOW. Three tiers, ceilings 6 / 17 / 34 m, each built from
# parallel vertical planes whose alpha is a VERTICAL GRADIENT off the radial
# mask (see haze_plane). Two consequences, and they are the two the review
# asked for:
#
#   ALTITUDE. Each tier's density decays smoothly to exactly zero at its own
#   ceiling, so no tier has an edge. The three summed give a monotone profile
#   - roughly 1.0 / 0.55 / 0.28 / 0.12 / 0.04 of peak at Z 0 / 5 / 12 / 22 / 36
#   - which is a three-term fit to an exponential atmosphere, and is what
#   "thins with altitude, continuously" actually requires.
#
#   DISTANCE. The planes are on a fixed pitch (6 / 9 / 13 m), so the number a
#   ray crosses is proportional to how far it travels: airlight accumulates
#   with range, automatically, without anybody authoring a distance ramp. A
#   ray leaving the frame upward crosses fewer and fewer as it climbs out of
#   each tier in turn, so the sky stays clean.
#
# Both an X-normal and a Y-normal set are authored, at the same pitch, so the
# accumulation rate varies by at most sqrt(2) with view heading. Three shots
# look along X (SILHOUETTE west, LANE_EYE and INTERIOR east) and two along Y
# (HERO north-east, DETAIL south).
#
# The tiers are CUT AROUND THE WAREHOUSE. Inside the shed the air is authored
# separately (FX_InteriorAir, section 2) at a fifth of this density, because a
# closed building at dusk is not as hazy as the open yard and INTERIOR_AISLE's
# fog is deliberately thin. Above the ridge the planes resume, reading V off
# the same global ramp so the two pieces agree about density and the join is
# invisible.
hz = [M("Haze_%02d" % i, "FX_Haze%02d" % i, two_sided=True)
      for i in range(len(HAZE_LADDER))]

# the warehouse solid, in world coordinates, plus a small margin
WH_X0, WH_X1, WH_Y0, WH_Y1, WH_Z = -38.4, 38.4, 14.6, 76.6, 18.4
SITE_X0, SITE_X1 = -82.0, 74.0
SITE_Y0, SITE_Y1 = -60.0, 96.0
# ceiling / plane pitch / opacity / band count / base height / base ramp
# Three tiers, three different base heights and three different densities, each
# fading to zero at its own ceiling AND (for B and C) ramping in above its own
# base, so the sum is a smooth monotone profile with no lid and no floor:
#   Z  0     2     5    10    17    26    34
#   A  1.00  0.62  0.20  0.00  -     -     -
#   B  0.00  0.19  0.42  0.29  0.00  -     -
#   C  0.00  0.00  0.05  0.15  0.13  0.05  0.00
TIERS = ((HAZE_TOP_A, HAZE_PITCH_A, OP_HAZE_A, 9, 0.0, 0.0),
         (HAZE_TOP_B, HAZE_PITCH_B, OP_HAZE_B, 11, 0.0, 4.5),
         (HAZE_TOP_C, HAZE_PITCH_C, OP_HAZE_C, 12, 1.5, 11.0))

# --- LENS KEEP-OUT, AND WHY THE ATMOSPHERE NEEDED ONE ------------------------
# THIS IS THE "FLAT MILKY PLATE WITH A HARD UPPER BOUNDARY". The tiers are grids
# of parallel planes on a fixed pitch across the whole site, and nothing stopped
# one landing right on top of a camera. Measured for SILHOUETTE_WEST at
# (56, -8, 1.65): the tier-A X-normal grid puts a plane at X = 55.86 - fourteen
# CENTIMETRES in front of the lens - and tier C puts another at X = 56.84. A
# plane that close is face-on to the view direction and covers the ENTIRE frame
# with one uniform wash of its own density; that is the plate. Its band edges,
# which are 0.5-3 m apart in Z, subtend tens of degrees from 0.14 m away; that
# is the hard upper boundary. Neither is a density problem and no amount of
# retuning the ladder could have touched it.
#
# So a plane is culled if it passes within NEAR metres of ANY of the five camera
# eyes. That is a read of 90_cameras.usda, not an edit of it, and it is not a
# per-shot hack: the cull is the same geometry for every render, and the same
# would be needed for any camera placed anywhere in the site. What it costs is
# 2-3 crossings out of the 25-45 a horizontal ray makes on its way across the
# map, i.e. under 8 % of the accumulated airlight - and it costs that only in
# the first few metres, where a real atmosphere contributes nothing you can see
# either.
R_KEEP = 0.0
# Whole-plane cull distance: a plane whose position passes within NEAR metres of
# any camera eye is not authored at all. 3.0 m removes only the planes that are
# literally at a lens - the SILHOUETTE_WEST eye had one 0.14 m in front of it -
# and leaves everything past 3 m intact.
NEAR = 3.0


def _camera_eyes():
    p = Path(__file__).resolve().parent.parent / "usd" / "modules" / "90_cameras.usda"
    if not p.exists():
        print("  WARNING: 90_cameras.usda not found - no haze lens keep-out")
        return []
    txt = p.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in re.finditer(r'def Camera "(\w+)"\s*\{(.*?)\n        \}', txt, re.S):
        t = re.search(r'double3 xformOp:translate = \(([^)]*)\)', m.group(2))
        if t:
            v = [float(x) for x in t.group(1).split(",")]
            out.append((m.group(1), v[0], v[1], v[2]))
    return out


EYES = _camera_eyes()
print("  haze lens keep-out: %.1f m at each of %d camera eyes (%s)"
      % (NEAR, len(EYES), ", ".join(e[0] for e in EYES)))


def plane_clear(axis, pos):
    for (_n, ex, ey, _ez) in EYES:
        if not (SITE_X0 <= ex <= SITE_X1 and SITE_Y0 <= ey <= SITE_Y1):
            continue
        if abs(pos - (ex if axis == "x" else ey)) < NEAR:
            return False
    return True


def _holes(axis, pos):
    """DISABLED, and the measurement that killed it is worth keeping.

    The first version of this cut a 6.5 m keep-out DISC in each plane around each
    camera eye, on the sound-looking argument that culling a whole plane throws
    away the work it does 90 m away on the far side of the map. It works
    visually and it is a noise disaster: the disc has to be tessellated, so it
    leaves a rim of small emissive quads a couple of metres from the lens, and
    every one of those edges is a high-variance silhouette against a mesh light.
    Measured on SILHOUETTE_WEST at --final --warmup 120:

        no atmosphere at all          speckle 0.018   firefly 0.028
        atmosphere, no keep-out       speckle 0.018   firefly 0.027
        atmosphere, 6.5 m DISCS       speckle 0.029   firefly 0.074   <- rejected
        atmosphere, 3.0 m plane cull  see below

    The whole-plane cull costs about a tenth of the accumulated airlight and
    adds no geometry at all, so that is what is authored. Kept as a stub rather
    than deleted so the next person does not re-invent the disc."""
    return []


def _ragged(m, axis, pos, a0, a1, z0, z1, amp, holes=()):
    """One band of one plane, cut along its length into chunks whose top and
    bottom edges step by a random amount at every chunk boundary.

    THIS IS THE FIX FOR "A HARD UPPER BOUNDARY". A band is a horizontal strip,
    and a horizontal strip 156 m long has two perfectly straight horizontal
    edges. Displacing the WHOLE band by a per-plane offset - which is what
    revision 3 did, +/-0.22 m - does not help at all: it moves the straight line,
    it does not stop it being a straight line. Cutting the band into 7-14 m
    chunks and giving every chunk boundary its own vertical offset turns each
    edge into a ragged polyline whose steps are 1-3 deg apart at the distances
    these cameras work at, which is below what reads as an edge. The chunks
    share their boundary heights with their neighbours, so there is no gap and
    no overlap - the strip is continuous, just not straight."""
    L = a1 - a0
    if L <= 0.0:
        return
    # Chunk boundaries: coarse everywhere, fine only across a keep-out disc, so
    # cutting a 6.5 m hole costs a handful of extra faces instead of
    # re-tessellating 156 m of plane.
    zones = [(hu - hr - 2.0, hu + hr + 2.0) for (hu, _hz, hr) in holes]
    bnd, u = [a0], a0
    while u < a1 - 1e-6:
        fine = any(lo - 2.0 < u < hi for (lo, hi) in zones)
        u = min(a1, u + (2.0 if fine else rng.uniform(17.0, 32.0)))
        bnd.append(u)
    n = len(bnd) - 1
    e0 = [0.0] + [rng.uniform(-amp, amp) for _ in range(n - 1)] + [0.0]
    e1 = [0.0] + [rng.uniform(-amp, amp) for _ in range(n - 1)] + [0.0]
    for k in range(n):
        u0, u1 = bnd[k], bnd[k + 1]
        if holes:
            um, zm = 0.5 * (u0 + u1), 0.5 * (z0 + z1)
            if any((um - hu) ** 2 + (zm - hz_) ** 2 < hr * hr for (hu, hz_, hr) in holes):
                continue
        b0, b1 = max(0.015, z0 + e0[k]), max(0.02, z0 + e0[k + 1])
        t0, t1 = z1 + e1[k], z1 + e1[k + 1]
        if axis == "x":
            m.quad((pos, u0, b0), (pos, u1, b1), (pos, u1, t1), (pos, u0, t0))
        else:
            m.quad((u0, pos, b0), (u1, pos, b1), (u1, pos, t1), (u0, pos, t0))


def haze_span(axis, pos, z0, z1, idx, amp, holes=()):
    """One band of one plane, cut around the warehouse solid and rejoined above
    its ridge. Both pieces read their density off the same tier profile, so the
    join carries no step."""
    m = hz[idx]
    if axis == "x":
        if WH_X0 <= pos <= WH_X1:
            segs = [(SITE_Y0, WH_Y0), (WH_Y1, SITE_Y1)]
            if z0 >= WH_Z:
                segs.append((WH_Y0, WH_Y1))
        else:
            segs = [(SITE_Y0, SITE_Y1)]
    else:
        if WH_Y0 <= pos <= WH_Y1:
            segs = [(SITE_X0, WH_X0), (WH_X1, SITE_X1)]
            if z0 >= WH_Z:
                segs.append((WH_X0, WH_X1))
        else:
            segs = [(SITE_X0, SITE_X1)]
    for (a0, a1) in segs:
        _ragged(m, axis, pos, a0, a1, z0, z1, amp, holes)


_nplane, _ncull = 0, 0
for (ztop, pitch, op, nb, zbase, bramp) in TIERS:
    bands = haze_bands(ztop, nb, zbase=zbase, base_ramp=bramp)
    for axis, (lo, hi) in (("x", (SITE_X0, SITE_X1)), ("y", (SITE_Y0, SITE_Y1))):
        # a per-tier phase offset so the three tiers' planes never coincide
        phase = pitch * (0.31 if axis == "x" else 0.17) * (ztop / 6.0) % pitch
        k = 0
        while True:
            pos = lo + phase + pitch * k
            k += 1
            if pos > hi:
                break
            if not plane_clear(axis, pos):
                _ncull += 1
                continue
            holes = _holes(axis, pos)
            _nplane += 1
            # JITTER: every band edge on this plane is displaced, and by a
            # different amount on the next plane, so a density step never lines
            # up between neighbouring planes. On its own that is not enough -
            # see _ragged, which is what stops a single band's own edge being a
            # straight line - but the two together are what turn a 12-step
            # staircase back into a smooth profile.
            j = [rng.uniform(-0.30, 0.30) for _ in range(nb + 1)]
            j[0] = 0.0
            for bi, (z0, z1, w) in enumerate(bands):
                idx = pick(HAZE_LADDER, op * w)
                if idx is None:
                    continue
                # ragged-edge amplitude scales with band thickness: a thin band
                # near the ground gets a small wobble, a 6 m band up top a big
                # one, so the relative softening is the same all the way up.
                amp = min(1.5, 0.32 * (z1 - z0) + 0.10)
                haze_span(axis, pos, max(0.02, z0 + j[bi]), z1 + j[bi + 1], idx, amp,
                          holes)
print("  atmosphere: %d planes (%d culled at a lens), %d density steps"
      % (_nplane, _ncull, len(HAZE_LADDER)))
G("Atmosphere", "Three height-graded haze tiers (ceilings 6 / 17 / 34 m) on a 6 / 9 / 13 m plane "
                "pitch, X-normal and Y-normal, cut around the warehouse. Each tier is banded on a "
                "12-step density ladder with per-plane jittered band edges, so the vertical "
                "profile is a smooth monotone decay to zero at the ceiling and no tier has a "
                "visible top. Airlight accumulates with range because the crossing count does.",
  hz)

# -----------------------------------------------------------------------------
# 5c. GOD RAYS - the low sun through the conveyor bridge and the canopy breaks
# -----------------------------------------------------------------------------
# KeySun (rotateXYZ 83, 0, 290) travels along (0.9327, 0.3395, -0.1219): 7.0 deg
# above the horizon on compass bearing 250, dropping 0.1219 m for every metre it
# travels ENE. SILHOUETTE_WEST stands at (56, -8, 1.65) looking along bearing
# 265, so the sun is 15 deg to frame-left and the light is coming almost
# straight down the lens axis - the one geometry in which shafts read as shafts
# and not as slabs. Everything between the conveyor bridge and that lens is
# backlit air, and that is where the beams are.
#
# The apertures are measured off 20_architecture, not invented:
#   * the bridge occupies X 24.51..27.29 with portal legs at Y = +10, 0, -10,
#     -18.6 and a soffit at Z 5.48, so the clear bays between those legs are
#     under-deck beams;
#   * six skin panels are missing from the enclosed truss (LAYOUT 5.6); three
#     are in this camera's half and give beams ABOVE the deck at Z 6.1-8.1,
#     which is what finally puts light INSIDE the bridge aperture the review
#     was looking through;
#   * the dock canopy is missing three roof panels at X = -30, -4, +19
#     (LAYOUT 5.4); two of them drop bars that leave the canopy at its Y = -20
#     gutter and rake across the east yard straight at this lens.
grm = [M("GodRay_%d" % i, "FX_GodRay%d" % i, two_sided=True)
       for i in range(len(GODRAY_LADDER))]
SIL_LENS = ((56.0, -8.0, 1.65), 16.0)

# UNDER-DECK BARS. Not one flood per bay: a 9.65 m clear bay behind a 0.35 m
# leg is 96 % lit, and 96 % lit is a wash, not a shaft - the first calibrated
# pass authored it that way and the whole yard simply went warm. What actually
# chops the light under this structure is the cross-bracing and the purlin run,
# so the beams are FIVE narrow 1.5-1.8 m bars with 4-6 m of real dark between
# them. The dark is the effect. The light is only what makes the dark visible.
# They start at Z 1.5, not at the slab. Below that the bars are behind the
# yard dressing anyway, and the emissive area down there was buying nothing but
# a warm wash on the foreground.
for (by, bhw) in [(-17.4, 0.78), (-12.0, 0.72), (-6.4, 0.80), (-1.2, 0.74)]:
    beam(grm, (27.35, by, 1.50), bhw, 1.50, 5.32, rng.uniform(24.0, 27.0),
         stop=SIL_LENS, hw_grow=1.45, gain=rng.uniform(0.88, 1.0))
# missing skin panels, above the deck - the ones inside the aperture
for (by, bhw) in [(-16.0, 0.95), (-3.0, 1.00), (9.0, 0.90)]:
    beam(grm, (27.35, by, 0.0), bhw, 6.15, 8.05, 30.0, stop=SIL_LENS, hw_grow=1.6)
# dock-canopy roof breaks, raking across the east yard
for (bx, by) in [(-4.0, -27.5), (19.0, -27.5)]:
    beam(grm, (bx, by, 5.42), 1.55, 0.0, 1.35, 34.0, stop=SIL_LENS, hw_grow=1.9,
         gain=0.8)
G("GodRays", "The 7 deg sun through the four clear bays and three missing skin panels of the "
             "conveyor bridge, and through two holes in the dock canopy roof. Cross-section cards "
             "on the measured KeySun vector, clamped to the ground, stopped 10 m short of the "
             "SILHOUETTE_WEST lens. Cards rather than tubes: pickup is proportional to path "
             "length inside the beam, so a camera looking down one sees a shaft and a camera "
             "crossing one sees almost nothing.", grm)

# dust in the beams
dm = M("Motes", "FX_DustMote", two_sided=True)
for i in range(190):
    if i % 2:                                    # inside the west-door wedge
        t = rng.uniform(0.5, 14.0)
        x = -37.6 + SUN[0] * t + rng.uniform(-0.3, 0.3)
        y = rng.uniform(48.3, 52.5) + SUN[1] * t
        z = rng.uniform(0.15, 1.85) + SUN[2] * t
        if z < 0.05:
            continue
    else:                                        # under the roof monitor
        x = rng.uniform(-30, 32)
        y = rng.uniform(40, 56)
        z = rng.uniform(4.2, 12.5)
    s = rng.uniform(0.012, 0.035)
    dm.quad((x - s, y, z - s), (x + s, y, z - s), (x + s, y, z + s), (x - s, y, z + s))
G("DustMotes", "Sub-pixel emissive quads in the beams. They read as sparkle, not geometry.", [dm])

# -----------------------------------------------------------------------------
# 6. GROUND DECALS
# -----------------------------------------------------------------------------
# DECAL HEIGHTS. These were 0.014 / 1.214 / 0.016, i.e. 2 mm of clearance over
# 10_terrain's own surface paint (its TyrePolish mesh tops out at Z = 0.0123) and
# well INSIDE the aggregate relief that module now lays down (its LooseAggregate
# and EmbeddedAggregate meshes reach Z = 0.30). At 2 mm the cards were dipping
# through their host surface and z-fighting its paint at distance. 0.028 buys
# 16 mm of clearance over the paint layer, which is still under a millimetre of
# parallax error at the closest camera (DETAIL_WET_APRON, 8.8 m) and invisible at
# HERO's 80 m.
ZY = 0.028          # yard decal height (terrain paint tops out at 0.0123)
ZD = 1.228          # dock deck decal height (deck top 1.20)
ZI = 0.028          # interior slab

tsf = M("Scuff_fresh", "FX_TyreScuffFresh")
ts = M("Scuff", "FX_TyreScuff")
tsp = M("Scuff_old", "FX_TyreScuffOld")
TSM = [ts, tsp]
TSM_HOT = [tsf, tsf, ts]          # braking / scrubbing: mostly fresh black rubber
TSM_COLD = [tsp, tsp, ts]         # walked-off, old

# =============================================================================
# REVISION 4 - THE MARKS ARE NOW SHORT, SITED, LAYERED AND PROP-CLIPPED.
# =============================================================================
# Round-4 blocker, verbatim: "long, smooth, gently curving pale ribbons in
# parallel pairs with 60-100 degree arcs cross the whole of HERO_ESTABLISH and
# LANE_EYE_YARD, pass through props, and run off into the distance."
#
# All three of those are true of revision 2's construction and all three are
# structural. Revision 2 authored EIGHT manoeuvres of 41-52 m driven length,
# each a single 66-104 deg arc, plus four bay exits 13-16 m long, plus a 104 m
# service-road rut and a 74 m interior aisle line. A vehicle that lays a
# continuous visible mark for 45 m is not braking, turning or spinning - it is
# rolling, and a rolling tyre lays nothing. Rubber comes off a tyre only where
# the contact patch is SLIDING: under braking, under a hard steering input, and
# when a drive axle spins up. All three are events, and an event leaves a mark
# a few metres long.
#
# So the whole thing is rebuilt around SITES rather than journeys. Every mark in
# the yard now belongs to one of: a dock bay reverse, the dock drive-through
# mouth, the hero gate line, a roller-door reverse, the painted truck turning
# circle at (0, +2) that LAYOUT 4/Z2 puts there, the fuel-bay approach, or the
# east apron. No run exceeds 9 m of driven length and no arc exceeds 40 deg of
# sweep. At each site two to four passes are laid over each other at 2-9 deg of
# heading difference and 0.15-0.6 m of lateral offset, with different widths,
# different materials and different mask softness, because a bay that has been
# reversed into a thousand times carries a smear of near-parallel marks, not one
# clean pair.
#
# AND NOTHING PASSES THROUGH A PROP ANY MORE. 30_props.usda is parsed at
# generation time for the world XY of all 977 prop instances; a path is cut the
# moment it comes within 0.85 m of one, and the same test rejects the hard
# architecture (bridge legs, trestle legs, canopy columns, jersey barriers,
# bund wall). That is a read of another module, not an edit of one.

def _load_prop_keepout():
    """World XY of every prop instance in 30_props.usda.

    Parsed out of the text rather than composed with pxr because the props
    reference remote assets that pxr cannot resolve; the transforms themselves
    are local and authored in world space (there is no translate on any of the
    group Xforms - verified: zero matches at that indent level)."""
    p = Path(__file__).resolve().parent.parent / "usd" / "modules" / "30_props.usda"
    if not p.exists():
        print("  WARNING: 30_props.usda not found - tyre marks are NOT prop-clipped")
        return []
    txt = p.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in re.finditer(r'^ {16,}double3 xformOp:translate = \(([^)]*)\)', txt, re.M):
        v = m.group(1).split(",")
        out.append((float(v[0]), float(v[1])))
    return out


# hard architecture a truck cannot drive through, as (x, y, radius)
ARCH_KEEPOUT = (
    [(24.62, y, 1.1) for y in (10.0, 0.0, -12.0, -19.0)] +          # bridge legs
    [(27.18, y, 1.1) for y in (10.0, 0.0, -12.0, -19.0)] +
    [(-30.0, y, 1.4) for y in (12.0, 4.0, -6.0)] +                  # trestle legs
    [(cx, -21.0, 0.9) for cx in (-44, -36.8, -29.6, -22.4, -15.2,   # canopy columns
                                 -8, -0.8, 6.4, 13.6, 20.8, 28)] +
    [(-58.0, 8.0, 1.0), (-50.0, 8.0, 1.0)] +                        # tanker gantry
    [(41.0, 8.0, 0.6), (49.0, 8.0, 0.6)]                            # east bollards
)

_PROPS = _load_prop_keepout()
_CELL = 4.0
_GRID = {}
for _px, _py in _PROPS:
    _GRID.setdefault((int(_px // _CELL), int(_py // _CELL)), []).append((_px, _py, 0.85))
for _px, _py, _pr in ARCH_KEEPOUT:
    _GRID.setdefault((int(_px // _CELL), int(_py // _CELL)), []).append((_px, _py, _pr))
print(f"  prop keep-out: {len(_PROPS)} prop instances + {len(ARCH_KEEPOUT)} structures")


def prop_clear(x, y):
    gx, gy = int(x // _CELL), int(y // _CELL)
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for (px, py, pr) in _GRID.get((gx + i, gy + j), ()):
                if (px - x) ** 2 + (py - y) ** 2 < pr * pr:
                    return False
    return True


def drivable(x, y):
    """Where a truck can physically be. Nothing may lay rubber through a wall."""
    if -68.0 <= x <= 64.0 and -21.9 <= y <= 14.6:
        pass                                         # the yard and the dock apron
    elif -70.0 <= x <= -38.5 and -22.0 <= y <= 33.0:
        pass                                         # west fuel-bay approach
    elif 38.5 <= x <= 66.0 and -22.0 <= y <= 34.0:
        pass                                         # east rail-spur approach
    elif abs(x) <= 3.05 and 14.6 < y <= 24.0:
        pass                                         # the 7.39 m hero gate mouth
    else:
        return False
    return prop_clear(x, y)


def clip_path(pts):
    """Longest prefix that stays on drivable ground and clear of every prop."""
    out = []
    for (x, y) in pts:
        if not drivable(x, y):
            break
        out.append((x, y))
    return out


def event(x, y, hdg, segs, *, passes=3, track=2.30, width=0.28, dual=False,
          mats=None, spread=0.45, wobble=6.0, z=ZY, tag=""):
    """Lay one SLIDING EVENT: a short manoeuvre, several overlapping passes.

    Each pass is the same manoeuvre driven fractionally differently - a couple
    of degrees of heading, a few tens of centimetres of line, a different tyre
    width and a different mask softness. That is what a working yard looks like:
    the same movement repeated by different drivers, never once by one.
    """
    mats = mats or TSM
    nominal = sum(s[1] if s[0] == "s" else abs(s[1] * math.radians(s[2])) for s in segs)
    laid, n_ok = 0.0, 0
    for k in range(passes):
        f = 0.0 if passes == 1 else (k / (passes - 1.0) - 0.5) * 2.0
        best = None
        # The yard is dressed to a cover cadence of one piece of hard cover every
        # 8-12 m (LAYOUT 6), so a site chosen off a coordinate in the layout very
        # often has a drum or a pallet sitting on it. Rather than hand-nudge each
        # one until it fits - which would silently rot the next time 30_props
        # moves - each pass hunts for a start that gives it a clear run, and a
        # site that cannot find one anywhere within 2.5 m says so and lays
        # nothing. An honest empty site beats a mark through a crate.
        for _try in range(14):
            j = 0.0 if _try == 0 else 1.0
            px = x + rng.uniform(-0.25, 0.25) + f * spread * rng.uniform(0.6, 1.0) \
                + j * rng.uniform(-2.5, 2.5)
            py = y + rng.uniform(-0.25, 0.25) + f * spread * rng.uniform(0.6, 1.0) \
                + j * rng.uniform(-2.5, 2.5)
            ph = hdg + f * wobble * rng.uniform(0.5, 1.0) + rng.uniform(-1.5, 1.5) \
                + j * rng.uniform(-12.0, 12.0)
            segs_k = [(s[0], s[1] * rng.uniform(0.82, 1.12)) if s[0] == "s"
                      else (s[0], s[1] * rng.uniform(0.88, 1.15), s[2] * rng.uniform(0.85, 1.1))
                      for s in segs]
            p = clip_path(path_run(px, py, ph, segs_k, step=0.55))
            if len(p) < 4:
                continue
            L = sum(math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
                    for i in range(len(p) - 1))
            if best is None or L > best[0]:
                best = (L, p)
            if L >= nominal * 0.80:
                break
        if best is None or best[0] < max(1.6, nominal * 0.45):
            continue
        laid += best[0]
        n_ok += 1
        wheel_pair(mats, best[1], z, track=track * rng.uniform(0.96, 1.05),
                   width=width * rng.uniform(0.78, 1.22), dual=dual and k == 0,
                   vh=rng.uniform(0.15, 0.27))
    if tag:
        flag = "   <- BLOCKED by props, nothing laid" if n_ok == 0 else ""
        print(f"  {tag:34s} {n_ok}/{passes} passes, {laid:5.1f} m laid{flag}")
    return laid


# --- THE SITES ---------------------------------------------------------------
# 1. DOCK BAY REVERSING. A tractor backs a trailer onto a dock bay: it comes in
#    across the apron, stops, cuts the wheel hard and reverses in almost square.
#    The mark is the SCRUB while the steer axle is turned and the vehicle is
#    barely moving - a metre or two of arc - plus the straight-in reverse. Bays
#    are at X -38, -22, -6, +10 with the dock face at Y = -22 (LAYOUT 5.3).
for bx in (-38.0, -22.0, -6.0, 10.0):
    event(bx + rng.uniform(-0.5, 0.5), -13.6, 270,
          [("s", 5.6)], passes=3, width=0.30, dual=True, mats=TSM,
          spread=0.55, wobble=3.0, tag=f"dock bay reverse X{bx:+.0f}")
    event(bx + rng.uniform(-3.4, -2.0), -12.4, 254,
          [("s", 1.8), ("a", 6.5, 34), ("s", 2.2)], passes=2, width=0.26,
          mats=TSM_HOT, spread=0.35, wobble=8.0, tag=f"dock bay cut-in X{bx:+.0f}")

# 2. DOCK DRIVE-THROUGH MOUTH (X +2..+8, LAYOUT 5.3 bay gap). Everything leaving
#    the service road turns west here, and turning under load is where the
#    outside front tyre scrubs.
event(5.0, -20.4, 88, [("s", 2.4), ("a", 8.5, 28), ("s", 2.6)], passes=3,
      width=0.29, dual=True, mats=TSM, spread=0.5, tag="drive-through mouth")

# 3. THE HERO GATE LINE (X -3.15..+3.16 at Y = 15, LAYOUT 3.1). A truck noses
#    into a 7.39 m opening with 0.6 m of clearance either side; it goes in dead
#    straight and slowly, and it scrubs on the way back out.
event(1.5, 17.2, 270, [("s", 6.4)], passes=3, width=0.27, dual=True,
      mats=TSM, spread=0.35, wobble=2.0, tag="hero gate straight-in")
event(-1.5, 11.4, 92, [("s", 3.0), ("a", 11.0, 22), ("s", 2.4)], passes=2,
      width=0.25, mats=TSM_COLD, spread=0.4, tag="hero gate peel-off")

# 4. ROLLER-DOOR REVERSING, Y = 15, X -37.9..+2.6 (LAYOUT 3.1). Forty metres of
#    openable wall: trucks back up to it square, four places along its length.
for dx in (-34.0, -27.5, -19.0, -12.0):
    event(dx + rng.uniform(-0.6, 0.6), 13.4, 270, [("s", 4.6)], passes=2,
          width=0.28, dual=True, mats=TSM_COLD, spread=0.5, wobble=3.0,
          tag=f"roller-door reverse X{dx:+.0f}")

# 5. THE PAINTED TURNING CIRCLE, radius 9 centred (0, +2) - LAYOUT 4/Z2 puts it
#    there and the terrain paints it. A truck using it is at full lock, which is
#    the single hardest-scrubbing thing that happens in a yard. These are SHORT
#    ARCS ON that circle - 26-38 deg, 4-6 m of track - at four different radii
#    and four different places round it. Four short arcs at different radii and
#    different bearings do NOT read as a ring; four concentric 180 deg arcs did,
#    which is what revision 1 got wrong and revision 2 over-corrected by
#    deleting the circle altogether.
for (ang, rad, sweep) in ((206.0, 8.4, 32.0), (256.0, 9.5, -27.0),
                          (318.0, 9.0, 30.0), (16.0, 8.7, -34.0)):
    a = math.radians(ang)
    event(0.0 + rad * math.cos(a), 2.0 + rad * math.sin(a), ang + 90.0,
          [("s", 1.2), ("a", rad, sweep), ("s", 1.2)], passes=2, width=0.30,
          mats=TSM_HOT, spread=0.4, wobble=4.0,
          tag=f"turning circle @{ang:.0f} deg")

# 6. WEST FUEL BAY (LAYOUT 5.11/5.12). A tanker swings in off the west approach
#    and stops under the gantry; the bund wall gives it nowhere to go.
event(-52.5, 1.6, 104, [("s", 2.6), ("a", 9.0, 30), ("s", 2.4)], passes=2,
      width=0.31, dual=True, mats=TSM, spread=0.5, tag="fuel bay swing-in")
event(-58.5, -0.8, 88, [("s", 3.8)], passes=2, width=0.29, mats=TSM_HOT,
      spread=0.4, wobble=2.5, tag="fuel bay stop")

# 7. EAST APRON / RAIL SPUR (LAYOUT 5.15). SILHOUETTE_WEST's near ground.
event(45.0, -9.0, 176, [("s", 2.2), ("a", 10.0, -26), ("s", 2.8)], passes=3,
      width=0.28, dual=True, mats=TSM, spread=0.55, tag="east apron turn")
event(41.5, -3.0, 262, [("s", 4.2)], passes=2, width=0.26, mats=TSM_COLD,
      spread=0.45, wobble=3.0, tag="east apron reverse")
event(52.0, -16.5, 92, [("s", 2.0), ("a", 8.0, 33), ("s", 2.0)], passes=2,
      width=0.27, mats=TSM_HOT, spread=0.4, tag="rail spur cut")

# 8. BRAKING SMEARS. Short, straight, and WIDENING along their length - a locked
#    wheel scrubs flat and lays a wider, blacker mark the further it slides.
#    Always in pairs on the 2.30 m axle track, always where a driver actually
#    stands on it: the apron in front of the dock bays, the mouth of the
#    drive-through, and the two approaches to the gate line.
for (sx, sy, sh, L) in [(-37.4, -18.6, 92, 3.4), (-21.0, -17.9, 86, 2.6),
                        (-6.4, -18.8, 94, 3.9), (9.6, -18.2, 88, 3.0),
                        (4.2, -14.0, 268, 2.4), (25.0, -15.6, 176, 3.2),
                        (-29.5, -13.0, 262, 2.8), (17.5, -19.4, 8, 2.2),
                        (-8.5, 9.6, 274, 2.9), (12.0, 7.4, 96, 2.4),
                        (-44.0, 4.5, 88, 3.1)]:
    p = clip_path(path_run(sx, sy, sh, [("s", L)], step=0.4))
    if len(p) < 4:
        continue
    for side in (+1.0, -1.0):
        ribbon(rng.choice(TSM_HOT), offset_path(p, side * 1.15), 0.20, ZY,
               taper=0.32, hold=0.42, vh=rng.uniform(0.13, 0.21),
               width_end=0.36, streak=0.10, phase=rng.uniform(0, 6.28))

# 9. STRAIGHT DRAG SCUFFS. Not tyres - a skip, a rack frame or a pallet stack
#    being dragged. Dead straight, thin, short, and paired at odd spacings so
#    they never look like an axle. Count held at 10 (round 3 cut it from 22
#    because the criss-cross was reading as hatching) and the maximum length cut
#    from 6.0 to 3.6 m for the same reason.
for i in range(10):
    x0 = rng.uniform(-50, 48)
    y0 = rng.uniform(-20.6, 12.0)
    a = rng.uniform(0, 360)
    L = rng.uniform(1.4, 3.6)
    p = clip_path(path_run(x0, y0, a, [("s", L)], step=0.45))
    if len(p) < 3:
        continue
    ribbon(rng.choice(TSM), p, rng.uniform(0.06, 0.13), ZY, taper=0.44, hold=0.5,
           vh=rng.uniform(0.17, 0.28), streak=0.08, phase=rng.uniform(0, 6.28))
    if rng.random() < 0.45:
        ribbon(rng.choice(TSM), offset_path(p, rng.uniform(0.22, 0.70)),
               rng.uniform(0.05, 0.11), ZY, taper=0.44, hold=0.5,
               vh=rng.uniform(0.19, 0.30), streak=0.08, phase=rng.uniform(0, 6.28))

# 10. SERVICE-ROAD RUTS (Y = -37, LAYOUT Z3: "compacted mud with two deep wheel
#     ruts holding water"). These are the one long mark that is honest, because
#     a rut is a groove worn by rolling traffic and not a rubber deposit - but a
#     104 m unbroken ribbon still reads as a drawn line, so it is broken into
#     five segments of 11-19 m with 3-8 m of unworn ground between them and a
#     lateral wander of 0.4 m, which is what a mud track actually does.
_rx = -52.0
while _rx < 50.0:
    seg = rng.uniform(11.0, 19.0)
    x1 = min(52.0, _rx + seg)
    for off in (-1.15, 1.15):
        wob = rng.uniform(-0.4, 0.4)
        pts = [(x, -37.0 + off + wob + math.sin(x * 0.09 + off) * 0.28)
               for x in (_rx, (_rx + x1) * 0.5, x1)]
        ribbon(tsp, pts, rng.uniform(0.34, 0.48), ZY, taper=0.44, hold=0.66,
               vh=rng.uniform(0.22, 0.33), streak=0.10, phase=rng.uniform(0, 6.28))
    _rx = x1 + rng.uniform(3.0, 8.0)

# 11. FORKLIFT SCRUB at every rack-run gap. A counterbalance truck steers on the
#     REAR axle with a 1.15 m track, so it pivots almost on the spot - a tight,
#     short arc is exactly right for it, and unlike a truck it really does leave
#     one every time it turns. Sweep capped at 95 deg (was 128) and the entry and
#     exit straights cut to 1.2-2.2 m, so no interior mark is longer than 6 m.
GAPS = [(-18, 29.5), (14, 29.5), (-30, 37.5), (2, 37.5), (-10, 45.5), (26, 45.5),
        (-26, 53.5), (10, 53.5), (-2, 61.5), (22, 61.5), (-34, 69.5), (16, 69.5)]
for (gx, gy) in GAPS:
    for k in range(2):
        h0 = rng.choice([0, 180]) + rng.uniform(-14, 14)
        sw = rng.choice([1, -1]) * rng.uniform(55, 95)
        p = path_run(gx - math.cos(math.radians(h0)) * 2.2 + rng.uniform(-0.5, 0.5),
                     gy - math.sin(math.radians(h0)) * 2.2 + rng.uniform(-0.5, 0.5), h0,
                     [("s", rng.uniform(1.2, 2.2)), ("a", rng.uniform(2.0, 3.2), sw),
                      ("s", rng.uniform(1.2, 2.2))], step=0.5)
        wheel_pair(TSM if k == 0 else TSM_COLD, p, ZI, track=1.15,
                   width=rng.uniform(0.15, 0.21), taper=0.36,
                   vh=rng.uniform(0.16, 0.28))

# 12. THE MAIN THROUGH-LANE, A3 at Y = 49.5. This used to be a single 74 m
#     ribbon per wheel running the whole length of the shed, which is the same
#     "long smooth ribbon" failure indoors. It is now eleven worn PATCHES of
#     2.5-5.5 m with 2.5-7 m of clean slab between them, each one wandering by
#     up to 0.3 m, because what actually wears is where a wheel scuffs as it
#     starts, stops or corrects - not the whole run.
_ax = -36.0
while _ax < 34.0:
    seg = rng.uniform(2.5, 5.5)
    x1 = min(36.0, _ax + seg)
    for off in (-1.15, 1.15):
        wob = rng.uniform(-0.3, 0.3)
        ribbon(rng.choice(TSM_COLD), [(_ax, 49.5 + off + wob), (x1, 49.5 + off + wob * 0.4)],
               rng.uniform(0.22, 0.34), ZI, taper=0.44, hold=0.5,
               vh=rng.uniform(0.20, 0.31), streak=0.10, phase=rng.uniform(0, 6.28))
    _ax = x1 + rng.uniform(2.5, 7.0)
G("TyreScuff", "Rubber, authored as SLIDING EVENTS rather than as journeys: dock-bay reverses, "
               "the drive-through mouth, the hero gate line, roller-door reverses, four short "
               "scrub arcs on the painted turning circle at (0,+2), the fuel bay and the east "
               "apron. No run exceeds 9 m of driven length, no arc exceeds 40 deg of sweep, and "
               "every site carries 2-4 overlapping passes at 2-9 deg of heading difference so it "
               "reads as repeated use rather than as one drawn line. Every path is cut against "
               "the world XY of all 977 prop instances in 30_props.usda plus the hard "
               "architecture, so no mark passes through anything. Albedo is SOLVED from measured "
               "probe renders (see the decal block in MATERIALS) and every mark is matte, so it "
               "sits at 0.19-0.65x the luminance of the surface it lies on.",
  [tsf, ts, tsp])

oil = M("Oil_fresh", "FX_OilStain")
oild = M("Oil_old", "FX_OilOld")
# the 14x10 oil-black pad under the tanker gantry: individual drips, not one rectangle
for i in range(34):
    splat(oil if rng.random() < 0.45 else oild,
          -56 + rng.gauss(0, 3.6), 6 + rng.gauss(0, 2.6), ZY,
          rng.uniform(0.25, 1.35), rng.uniform(0.20, 1.10), rng.uniform(0, 3.14))
# inside the fuel bund and around the drum stacks
for i in range(22):
    splat(oil if rng.random() < 0.5 else oild,
          rng.uniform(-63, -49), rng.uniform(-13.4, -4.6), 0.006,
          rng.uniform(0.2, 0.9), rng.uniform(0.18, 0.8), rng.uniform(0, 3.14))
# under the dock bays and along the apron
for i in range(26):
    splat(oild, rng.uniform(-45, 29), rng.uniform(-21.0, -16.5), ZY,
          rng.uniform(0.3, 1.5), rng.uniform(0.25, 1.0), rng.uniform(0, 3.14))
# the oil drip trail running east down aisle A3 - a dashed line, gaps included
x = -34.0
while x < 35.0:
    splat(oil if rng.random() < 0.35 else oild, x, 49.5 + rng.gauss(0, 0.55), ZI,
          rng.uniform(0.10, 0.42), rng.uniform(0.09, 0.34), rng.uniform(0, 3.14))
    x += rng.uniform(1.1, 3.4)
# and a heavier patch where something stood and leaked for a year
for i in range(14):
    splat(oil, -22 + rng.gauss(0, 1.4), 45.5 + rng.gauss(0, 0.9), ZI,
          rng.uniform(0.2, 0.8), rng.uniform(0.18, 0.7), rng.uniform(0, 3.14))
for i in range(12):
    splat(oild, 4 + rng.gauss(0, 2.2), -1 + rng.gauss(0, 2.0), ZY,
          rng.uniform(0.25, 1.0), rng.uniform(0.22, 0.85), rng.uniform(0, 3.14))
G("OilStains", "Oil as a scatter of drips at three ages, never a rectangle.", [oil, oild])

wf = M("WetFan", "FX_WetFan")
# 6 m slick fanning in from the hero gate - the thing that makes the interior shot
for i in range(30):
    t = rng.random()
    y = 15.2 + t * 6.2
    spread = 1.4 + t * 3.4
    splat(wf, rng.gauss(0, spread * 0.55), y + rng.uniform(-0.4, 0.4), ZI,
          rng.uniform(0.5, 1.9) * (1.15 - t * 0.5), rng.uniform(0.4, 1.5) * (1.15 - t * 0.5),
          rng.uniform(0, 3.14))
# 2-3 m wet fans inside every open south roller-door bay
for bx in (-36.0, -30.5, -24.0, -18.5, -12.0, -6.5):
    for i in range(7):
        splat(wf, bx + rng.gauss(0, 1.5), 15.4 + rng.uniform(0, 2.9), ZI,
              rng.uniform(0.4, 1.3), rng.uniform(0.35, 1.0), rng.uniform(0, 3.14))
# and inside the two open west doors
for by in (40.5, 50.5):
    for i in range(6):
        splat(wf, -37.4 + rng.uniform(0, 2.8), by + rng.gauss(0, 1.6), ZI,
              rng.uniform(0.35, 1.2), rng.uniform(0.3, 1.0), rng.uniform(0, 3.14))
G("WaterIngress", "Rain blown in through every open gate. Gloss, not colour, is what sells it.", [wf])

soot = M("Soot", "FX_Soot")
for (cx, cy, n, rad) in [(10.5, -6.0, 16, 2.4), (-24.0, -9.0, 11, 1.8), (37.0, -30.5, 9, 1.5),
                         (-58.0, -9.5, 8, 1.3)]:
    for i in range(n):
        splat(soot, cx + rng.gauss(0, rad * 0.6), cy + rng.gauss(0, rad * 0.6),
              ZY if cy > -20 else ZY, rng.uniform(0.3, rad * 0.8), rng.uniform(0.25, rad * 0.7),
              rng.uniform(0, 3.14))
G("Scorch", "Somebody burned pallets in the yard.", [soot])

# A general wear layer so no square metre of the map is a clean untouched plane.
# analyze_shot reports dead_area_frac against a 0.160 ceiling and the bare
# asphalt in the lower third of LANE_EYE_YARD and SILHOUETTE_WEST is where that
# number comes from. Density is highest in the east apron (X +20..+52), which is
# the SILHOUETTE_WEST foreground and had almost nothing on it.
gw_d = M("GeneralWear_dark", "FX_OilOld")
gw_s = M("GeneralWear_scuff", "FX_TyreScuffOld")
gw_w = M("GeneralWear_damp", "FX_WetFan")
ZONES = [(-52, 52, -16, 14, 150), (20, 54, -20, 10, 90), (-52, 30, -21, -16, 55),
         (-70, -40, -18, 30, 60), (38, 68, -20, 24, 55), (-46, 30, -33.6, -22.4, 70)]
for (x0, x1, y0, y1, n) in ZONES:
    for i in range(n):
        x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
        z = ZD if y < -22.0 else ZY
        # MIX SHIFTED TOWARD DAMP IN ROUND 3. Was 42 % oil-dark / 35 % scuff /
        # 23 % damp. The concept is "the rain has just stopped", so damp should
        # be the DOMINANT ground state, and now that the damp look is a dark
        # glossy mirror rather than a pale patch there is no reason to ration it:
        # it is the honest source of the frame's cool half. 30 / 32 / 38.
        m = gw_d if rng.random() < 0.32 else (gw_s if rng.random() < 0.48 else gw_w)
        r = rng.uniform(0.18, 1.5)
        splat(m, x, y, z, r, r * rng.uniform(0.45, 1.0), rng.uniform(0, 3.14))
# and a few dozen long, thin drag scars where something heavy was pulled
for i in range(26):
    x0, y0 = rng.uniform(-50, 50), rng.uniform(-20, 13)
    a = rng.uniform(0, 6.28)
    L = rng.uniform(2.5, 9.0)
    ribbon(rng.choice([gw_s, gw_d]),
           [(x0, y0), (x0 + math.cos(a) * L * 0.5, y0 + math.sin(a) * L * 0.5),
            (x0 + math.cos(a) * L, y0 + math.sin(a) * L)],
           rng.uniform(0.08, 0.22), ZY, cu=rng.uniform(0.42, 0.58))
G("GeneralWear", "The layer that stops any patch of ground reading as a clean plane: 480 wear "
                 "splats and 26 drag scars, weighted toward the two lane-level camera "
                 "foregrounds.", [gw_d, gw_s, gw_w])

bm = M("BirdMess", "FX_BirdMess")
for i in range(46):
    if i % 2:
        x, y, z = rng.uniform(-45, 29), rng.uniform(-33.5, -22.4), ZD
    else:
        x, y, z = rng.uniform(-44, 28), rng.uniform(-21.4, -20.6), ZY
    splat(bm, x, y, z, rng.uniform(0.05, 0.22), rng.uniform(0.05, 0.20), rng.uniform(0, 3.14))
for i in range(18):     # under the warehouse eaves
    splat(bm, rng.uniform(-37, 37), rng.uniform(13.7, 14.6), ZY,
          rng.uniform(0.05, 0.19), rng.uniform(0.05, 0.17), rng.uniform(0, 3.14))
G("BirdMess", "Pigeons roost under the canopy and the eaves.", [bm])

# -----------------------------------------------------------------------------
# 7. WALL DECALS
# -----------------------------------------------------------------------------
WALL_Y = 14.92      # 0.08 m proud of the warehouse south wall plane at Y = 15.00
rb = M("Rust_south", "FX_RustWall")
rbp = M("RustPale_south", "FX_RustWallPale")
ws = M("Water_south", "FX_WaterWall")
wsh = M("Wash_south", "FX_GrungeWall")
# Streak tops are capped at 10.6 m: the cladding runs out below the eaves line and
# a streak authored at 12.9 hangs in the sky above the roof edge, which the first
# render showed very clearly.
for i in range(56):
    x = rng.uniform(-37.4, 37.4)
    w = rng.uniform(0.10, 0.46)
    top = rng.choice([10.55, 10.55, 8.60, 5.35, 4.05, 3.92])
    ln = rng.uniform(1.1, 4.6) * (1.25 if top > 8 else 1.0)
    wall_streak(rng.choice([rb, rb, rbp]), WALL_Y, "y", x, x + w, top, max(0.15, top - ln))
for i in range(18):     # broad dilute washes under the gutter
    x = rng.uniform(-36, 36)
    w = rng.uniform(1.4, 4.2)
    wall_streak(rng.choice([ws, wsh]), WALL_Y - 0.005, "y", x, x + w, 10.5,
                rng.uniform(5.2, 8.4), uv=wisp(row=rng.randrange(1, 5)))
for i in range(16):     # splash-back and road dirt at the base of the wall
    x = rng.uniform(-37, 37)
    wall_streak(rng.choice([rbp, wsh]), WALL_Y, "y", x, x + rng.uniform(1.0, 3.4),
                rng.uniform(0.9, 1.8), 0.03, uv=wisp(row=rng.randrange(1, 5)))
G("WarehouseSouthWall", "Rust bleed, gutter wash and splash-back on the 76 m south wall - the "
                        "surface HERO_ESTABLISH is built on. 0.08 m proud of Y=15.00.",
  [rb, rbp, ws, wsh])

dk = M("DockFace_stain", "FX_WaterDock")
dka = M("DockFace_algae", "FX_Algae")
dkr = M("DockFace_rust", "FX_RustDock")
dke = M("DockFace_efflor", "FX_Efflor")
FY = -21.96         # dock north face is Y = -22.00, deck top 1.20
# DETAIL_WET_APRON closes on this face from 14.6 m, so these are authored small
# and dense. Wide soft crops that were fine at 60 m read as blurry rectangles at
# 14 m - that is exactly what the first calibrated pass showed on this wall.
for i in range(78):
    x = rng.uniform(-45.6, 29.6)
    wall_streak(dk, FY, "y", x, x + rng.uniform(0.07, 0.42), rng.uniform(1.02, 1.19),
                rng.uniform(0.12, 0.62))
for i in range(96):     # the permanently wet 0.35 m algae band at the dock foot
    x = rng.uniform(-45.8, 29.8)
    wall_streak(dka, FY, "y", x, x + rng.uniform(0.35, 1.35), rng.uniform(0.22, 0.46), 0.0,
                uv=wisp(row=rng.randrange(1, 6)))
for i in range(38):     # rust off the leveller plates and bay bumpers
    bx = rng.choice([-38, -22, -6, 10]) + rng.uniform(-2.2, 2.2)
    wall_streak(dkr, FY, "y", bx, bx + rng.uniform(0.08, 0.30), rng.uniform(0.95, 1.18),
                rng.uniform(0.05, 0.45))
for i in range(34):
    x = rng.uniform(-45, 29)
    wall_streak(dke, FY, "y", x, x + rng.uniform(0.18, 0.75), rng.uniform(0.7, 1.05),
                rng.uniform(0.1, 0.45), uv=wisp(row=rng.randrange(2, 7)))
G("DockFace", "The dock face closes DETAIL_WET_APRON 14.6 m out: algae band, water staining, "
              "rust off the levellers, salt bloom.", [dk, dka, dkr, dke])

col = M("CanopyColumns", "FX_RustCanopy")
colw = M("CanopyColumns_water", "FX_WaterCanopy")
for cx in (-44, -36.8, -29.6, -22.4, -15.2, -8, -0.8, 6.4, 13.6, 20.8, 28):
    for i in range(3):
        y = -21.13 + rng.uniform(0.0, 0.02)
        wall_streak(col, y, "x", cx - 0.09, cx + 0.09, rng.uniform(2.2, 5.1),
                    rng.uniform(0.0, 1.4), hu=0.30, hv=0.5)
    wall_streak(colw, -21.14, "x", cx - 0.09, cx + 0.09, 5.35, rng.uniform(2.4, 4.2), hu=0.34)
# gutter run along the canopy fascia at Y = -19.67
gut = M("CanopyFascia", "FX_RustCanopy")
for i in range(30):
    x = rng.uniform(-45.8, 29.8)
    wall_streak(gut, -19.60, "y", x, x + rng.uniform(0.10, 0.55), 6.12, rng.uniform(5.35, 5.9),
                hu=0.36, hv=0.46)
G("DockCanopyStreaks", "Eleven columns and 76 m of gutter, all of it running rust.",
  [col, colw, gut])

off_w = M("DockOffice_west", "FX_WaterDock")
off_r = M("DockOffice_rust", "FX_RustDock")
off_e = M("DockOffice_efflor", "FX_Efflor")
for i in range(24):     # west elevation X = 29.95, seen from the whole yard
    y = rng.uniform(-33.6, -20.4)
    wall_streak(off_w, 29.88, "x", y, y + rng.uniform(0.3, 1.8), rng.uniform(6.4, 7.45),
                rng.uniform(1.2, 4.6), hu=0.42, hv=0.5)
for i in range(14):
    y = rng.uniform(-33.6, -20.4)
    wall_streak(off_r, 29.88, "x", y, y + rng.uniform(0.09, 0.34), rng.uniform(4.2, 7.4),
                rng.uniform(0.6, 3.4), hu=0.32)
for i in range(16):
    y = rng.uniform(-33.4, -20.6)
    wall_streak(off_e, 29.88, "x", y, y + rng.uniform(0.4, 1.5), rng.uniform(1.4, 3.2),
                rng.uniform(0.05, 1.0), hu=0.44, hv=0.42)
for i in range(20):     # north elevation Y = -19.95, faces the yard
    x = rng.uniform(30.4, 45.6)
    wall_streak(rng.choice([off_w, off_r, off_e]), -19.88, "y", x, x + rng.uniform(0.15, 1.6),
                rng.uniform(3.0, 7.4), rng.uniform(0.3, 3.0), hu=0.4, hv=0.48)
G("DockOfficeStreaks", "Two-storey blockwork, water-stained. It is a legal power position, so it "
                       "gets read closely.", [off_w, off_r, off_e])

br = M("Bridge_rust", "FX_RustBridge")
brw = M("Bridge_water", "FX_WaterBridge")
brg = M("Bridge_grunge", "FX_GrungeBridge")
# No broad washes on the bridge: its skin is already the darkest surface in
# SILHOUETTE_WEST, and a pale wash on it reads as cloud stuck to the building.
# SILHOUETTE_WEST crosses the conveyor bridge at frame centre, 22 m out: east face
for i in range(34):
    y = rng.uniform(-19.4, 14.8)
    wall_streak(br, 27.25, "x", y, y + rng.uniform(0.06, 0.26), rng.uniform(8.2, 8.95),
                rng.uniform(5.95, 7.9))
for i in range(12):
    y = rng.uniform(-19.4, 14.8)
    wall_streak(brw, 27.24, "x", y, y + rng.uniform(0.12, 0.5), 8.95, rng.uniform(6.6, 8.4))
for i in range(22):     # west face, the one LANE_EYE_YARD sees at 70 m
    y = rng.uniform(-19.4, 14.8)
    wall_streak(rng.choice([br, brw]), 24.55, "x", y, y + rng.uniform(0.1, 0.5),
                rng.uniform(8.2, 8.95), rng.uniform(5.95, 7.8))
# the legs
for ly in (10.0, 0.0, -12.0, -19.0):
    for lx in (24.62, 27.18):
        wall_streak(br, lx, "x", ly - 0.2, ly + 0.2, rng.uniform(3.0, 5.6), rng.uniform(0.0, 1.6),
                    hu=0.3, hv=0.5)
G("ConveyorBridgeStreaks", "The bridge is the map's silhouette. Rust running off every panel lap.",
  [br, brw, brg])

# NOTE: there are deliberately NO streaks on the pipe trestle. It is an OPEN
# lattice, and the first calibrated render made that painfully obvious - two
# dozen rust streaks authored on its bounding planes hung in mid-air across the
# whole upper third of LANE_EYE_YARD like orange flames. Weathering decals only
# go on surfaces that are actually solid: the warehouse cladding, the dock face,
# the canopy columns and fascia, the office blockwork, the bund wall and the
# enclosed conveyor bridge skin.
bd = M("Bund_stain", "FX_Algae")
bde = M("Bund_efflor", "FX_Efflor")
for i in range(26):
    x = rng.uniform(-63.6, -46.2)
    wall_streak(bd, -14.06, "y", x, x + rng.uniform(0.3, 1.9), rng.uniform(0.3, 0.62), 0.0,
                hu=0.44, hv=0.4)
for i in range(18):
    x = rng.uniform(-63.6, -46.2)
    wall_streak(bde, -14.06, "y", x, x + rng.uniform(0.25, 1.2), rng.uniform(0.55, 0.88),
                rng.uniform(0.05, 0.4), hu=0.42, hv=0.42)
G("WestSideStreaks", "The fuel bund wall (the trestle gets none - see above).", [bd, bde])

# -----------------------------------------------------------------------------
# 8. DRIP LINES - the rain stopped a minute ago
# -----------------------------------------------------------------------------
dr = M("Drips", "FX_DripLine")
for i in range(70):     # off the dock canopy gutter, straight through HERO's foreground
    x = rng.uniform(-45.6, 29.6)
    z0 = rng.uniform(3.1, 5.30)
    dr.quad((x - 0.012, -19.62, z0), (x + 0.012, -19.62, z0),
            (x + 0.012, -19.62, 5.36), (x - 0.012, -19.62, 5.36))
for i in range(46):     # off the dock nosing - DETAIL_WET_APRON foreground
    x = rng.uniform(-45.6, 29.6)
    z0 = rng.uniform(0.35, 1.05)
    dr.quad((x - 0.010, -21.99, z0), (x + 0.010, -21.99, z0),
            (x + 0.010, -21.99, 1.19), (x - 0.010, -21.99, 1.19))
for i in range(40):     # off the warehouse eaves
    x = rng.uniform(-37, 37)
    z0 = rng.uniform(10.6, 12.6)
    dr.quad((x - 0.012, 14.90, z0), (x + 0.012, 14.90, z0),
            (x + 0.012, 14.90, 12.85), (x - 0.012, 14.90, 12.85))
G("DripLines", "Water still coming off the gutter, the nosing and the eaves.", [dr])


# -----------------------------------------------------------------------------
# 9. THE STORM BREAK - DELETED IN REVISION 3, ON PURPOSE
# -----------------------------------------------------------------------------
# This section used to author a sun disc, two halos and a lit cloud band as
# camera-facing backdrop cards on the SILHOUETTE_WEST sun bearing at 108-157 m.
# It is gone, and it is not coming back.
#
# 90_cameras measured it and was right: projected into the CURRENT shot-5 frame
# (the camera moved to (56, -8) after these cards were authored) Break_outer and
# Break_sky are an 80 x 93 m and a 55 x 204 m emissive quad standing across the
# whole western sky, spanning u -1.21..+3.63 and v -0.47..+2.66. THEY ARE the
# "flat milky-grey plate with a visible hard upper boundary" the review flagged,
# and the boundary is literally Break_outer's top edge at Z 44.26. They also
# occluded the dome's own sun disc, which is the only photographable sun on this
# stage. 90_cameras hid them with an `over` and asked the owner of this module to
# decide; the decision is delete.
#
# The lesson is worth keeping even though the code is not: a matte-painting card
# is authored for ONE camera transform, and a camera transform is not this
# module's to depend on. The warmth those cards were carrying is now authored as
# god rays (section 5c), which are built on the KeySun VECTOR rather than on a
# camera position and are therefore still correct when the camera moves.
#
# 90_cameras' `over "FX" { over "StormBreak" }` now targets a prim that does not
# exist. An `over` on a missing prim composes to nothing, so the override is
# inert and harmless; the camera owner can drop those lines at their leisure.


# =============================================================================
# EMIT
# =============================================================================
FOG = {
    # shot: (density, colour, colourIntensity, startDist, endDist, hDensity, hFalloff, hStart)
    #
    # Haze colour follows the SUN, because forward-scattered haze does. The sun
    # sits at bearing 200 deg. SILHOUETTE_WEST (heading 90 -> looking due west)
    # and DETAIL_WET_APRON (heading 218) are looking within ~20 deg of it, so
    # their haze is golden; HERO_ESTABLISH and LANE_EYE_YARD look away from it,
    # so theirs is the cold storm-sky blue. Authoring one neutral grey for all
    # five put SILHOUETTE_WEST's warm_cool_split at 0.005 against a 0.020 floor -
    # the haze was cancelling the amber/teal split the whole level is built on.
    "HERO_ESTABLISH":   (0.265, (0.335, 0.395, 0.520), 0.26, 14.0, 700.0, 0.55, 11.0, 0.0),
    "INTERIOR_AISLE":   (0.026, (0.470, 0.440, 0.450), 0.28, 6.0, 240.0, 0.22, 8.0, 0.0),
    "LANE_EYE_YARD":    (0.290, (0.330, 0.390, 0.515), 0.27, 9.0, 700.0, 0.60, 8.0, 0.0),
    "DETAIL_WET_APRON": (0.110, (0.580, 0.400, 0.300), 0.34, 2.0, 90.0, 0.45, 5.0, 0.0),
    # SILHOUETTE_WEST - THIS BLOCK IS INERT AND IS KEPT IN SYNC ON PURPOSE.
    # 90_cameras.usda is a stronger sublayer and now authors the full fog block
    # on this RenderProduct itself, retuning it to cold, low-density values. The
    # numbers below are a verbatim copy of theirs (0.085 density, (0.42, 0.47,
    # 0.56) at 0.22, from 25 m, height density 0.35 / falloff 11.0). Copying
    # rather than deleting means that if the camera owner ever drops their block
    # this shot does not silently fall back to whatever the previous product in
    # the same render.py invocation left in renderer-global state.
    # DO NOT "improve" these without talking to 90_cameras: they will not take
    # effect, and the next person to read the file will believe they did.
    "SILHOUETTE_WEST":  (0.085, (0.420, 0.470, 0.560), 0.22, 25.0, 520.0, 0.35, 11.0, 0.0),
}

HEAD = '''#usda 1.0
(
    doc = """DEADFALL DEPOT module: fx. Owned by one specialist agent - do not edit from another module.

Regenerate with:  cd tools && uv run gen_fx.py

Three things live in this layer.

1. ATMOSPHERE. `omni:rtx:fog:*` on each RenderProduct. Verified live on this build
   (ovrtx 0.4.0.346409): the OmniRtxDebugSettingsAPI fog block is honoured, it
   fogs the dome background as well as geometry, and `distanceDensity` is the
   only control that really matters - `endDist` past ~400 m changes nothing.
   It works in PathTracing as well as RealTimePathTracing - both tiers verified.
   90_cameras.usda is a STRONGER sublayer than this one, so wherever it states
   an `omni:rtx:fog:*` opinion of its own theirs wins and this block goes dead -
   by design. As of revision 3 it does exactly that on two of the five
   products; see below.

   REVISION 3 - THE FOG IS NOW SHARED WITH 90_cameras, NOT FOUGHT OVER.
   90_cameras is a stronger sublayer and now authors the full fog block on
   SILHOUETTE_WEST (cold, thin: 0.085 density, (0.42, 0.47, 0.56) at 0.22,
   starting 25 m out, height density 0.35 / falloff 11) and disables it on
   DETAIL_WET_APRON. Those opinions win. The block below keeps a verbatim copy
   of the SILHOUETTE numbers so the shot cannot fall back to renderer-global
   leftovers if that override is ever removed, and authors the other three
   shots itself. Analytic fog is UNIFORM IN THE HORIZONTAL and its only shape
   control is an exponential height falloff, so it is the right instrument for
   bulk distance desaturation and the wrong one for anything with structure -
   which is why the atmosphere with structure is geometry (below).

2. SCATTERING GEOMETRY. RTX only integrates a real participating medium out of a
   UsdVolVolume, and there is not one OpenVDB file in the 9969-file library - I
   checked. So in-scatter is authored the way a shipped game authors it: thin
   emissive geometry with fractional cutout opacity. Every beam is traced along
   the actual KeySun vector (0.9327, 0.3394, -0.1219) from the actual door
   openings measured off 20_architecture (WestDoor1 is fully open, WestDoor2 is
   nine slats short of shut, so its opening is the bottom 1.9 m), and every glow
   cone sits on a light position read out of 60_lighting.usda. Cones stop at
   Z 3.45 - above the 3.011 m racking - so no haze ever clips solid geometry.

3. DECALS. Everything soft-edged is masked by an alpha texture
   (Particles/T_dot_falloff.png, Particles/smoke_wisp.png) and every instance
   samples its own crop of that mask, at its own rotation, so no two share a
   silhouette and nothing reads as a floating card. Ground ribbons (tyre tracks,
   forklift arcs) hold U inside a narrow band across the mask centre, so the
   fade is across the track and never along it.

   REVISION 2 - TYRE MARKS ARE NOW DRIVEN, NOT DRAWN. The old turning circle was
   four concentric arcs of radius 8.05-9.62 m about (0, +2). Concentric circles
   is what it looked like, because that is what it was, and it was one of the
   first things the eye found in HERO. Nothing gets erased by describing the arc
   as "open" - four nested 180 deg arcs read as rings. Every mark in the yard is
   now generated from a vehicle path (path_run / offset_path / wheel_pair):
   straight in, ONE arc of 62-104 deg, straight out, entered and left at a real
   yard entrance, clipped against drivable() so nothing lays rubber through a
   wall. The two wheel tracks are offset by half a 2.30 m axle track, which
   makes the inner radius genuinely tighter than the outer one; drive axles get
   a twin mark 0.34 m outboard; and every run is tapered by ARC LENGTH so it
   dissolves at both ends and no mark closes on itself. Forklifts inside the
   shed use a 1.15 m track. Braking smears are short, straight and WIDEN along
   their length, because a locked wheel scrubs flat.

4. THE ATMOSPHERE (section 5b) AND THE GOD RAYS (section 5c) - REVISION 3.
   The review of SILHOUETTE_WEST said the air read as "a fogged pane rather
   than air": a flat milky-grey plate with a hard upper boundary and no
   gradient toward the horizon. Two separate causes, both fixed at the root.

   (a) THE PLATE was the StormBreak backdrop cards, and they are DELETED - see
       the note where section 9 used to be. They were camera-facing quads built
       for a shot-5 camera that has since moved, and from the new eye they were
       an 80 x 93 m emissive rectangle standing across the western sky with its
       top edge at Z 44.26. 90_cameras measured this independently and hid them
       with an `over`; this module has now removed them properly.

   (b) THE MISSING GRADIENT was structural, not a tuning error. Every haze
       volume in this layer used to be a CONSTANT-DENSITY SLAB - flat-topped
       boxes capped at 1.6 m, and nine tall ones running Z 2.55 to a ragged
       6.5-9.5 m. A constant-density slab has an edge by construction and
       cannot produce a gradient. It is replaced by three stacked height-graded
       tiers with ceilings 6 / 17 / 34 m, built from parallel vertical planes
       on a 6 / 9 / 13 m pitch. Each tier is cut into 8-10 horizontal BANDS and
       each band takes the step of a 12-entry density ladder nearest its own
       point on that tier falloff curve, so density decays to almost nothing at
       the ceiling and no tier has a top edge. The band edges are jittered by
       +/-0.22 m INDEPENDENTLY ON EVERY PLANE, so a density step is never a
       continuous horizontal line across the frame - that dither is what turns
       a 12-step staircase back into a smooth profile. The three tiers sum to a
       monotone decay that is a three-term fit to an exponential atmosphere.
       Thickening with distance is automatic: the number of planes a ray
       crosses is proportional to how far it travels. The tiers are cut around
       the warehouse solid and rejoin above the ridge.

       THE OBVIOUS IMPLEMENTATION DOES NOT WORK, AND IT COST A RENDER. The
       first attempt made the gradient continuous by binding T_dot_falloff as
       an opacity mask with U pinned to its centre and V ramped up the plane,
       with `opacity_constant = 0.0042` alongside it. In OmniPBR
       `enable_opacity_texture` REPLACES `opacity_constant`, it does not
       multiply it: alpha went to 1.0, the nearest haze plane 6 m from the lens
       was opaque, and SILHOUETTE_WEST rendered as a completely uniform
       grey-blue rectangle. Every low-density medium in this file is
       constant-opacity and untextured for that reason, and any gradient has to
       be built out of geometry.

   The god rays are the other half of the same job. KeySun is 7.0 deg up on
   compass bearing 250 and SILHOUETTE_WEST looks along bearing 265, so the
   light is coming almost down the lens axis and every clear bay in the
   conveyor bridge, every missing skin panel and two holes in the dock canopy
   roof is an aperture with a beam behind it. Each beam is a stack of
   CROSS-SECTION cards on a 1.6 m pitch rather than a tube, because a ray
   looking down the beam then crosses fifteen of them and a ray crossing it
   sideways crosses one - the pickup is proportional to the path length inside
   the lit volume, which is what a real medium does and what stops a shaft
   reading as a flat card from the other four cameras. The warmth the deleted
   StormBreak cards used to carry now comes from here, and unlike a backdrop
   card these are built on the sun VECTOR, so they stay correct when a camera
   moves.

   INTERIOR: the roof-monitor curtains now drop to the slab wherever they cross
   an aisle (LAYOUT 5.16 leaves 5.94 m of clear floor between rack runs, so
   there is nothing there to intersect). 60_lighting's Clerestory and
   RoofMonitor RectLights were already pooling daylight on the floor from their
   side; this is the air that makes the column between the roof and the pool
   visible. INTERIOR_AISLE gets a 9 m lens keep-out so the nearest curtain does
   not flare the frame.

THE EMISSIVE BUDGET IS THE WHOLE GAME, and it is not obvious. `ris:meshLights`
is ON in both render tiers, so every emissive surface in here is also a REAL AREA
LIGHT. The first calibrated pass ran the high-bay cones at emissive 26000; they
lit the entire roof, and because a cone occludes its own emission you got hard
black cone-shaped patches painted across the trusses of INTERIOR_AISLE. The fix
was emissive 26000 -> 4600 with opacity 0.014 -> 0.015, which holds the visible
in-scatter (roughly opacity x emissive, ~70) while cutting the radiated power by
5-6x. If you raise any E_* constant in gen_fx.py, re-render INTERIOR_AISLE and
look at the roof before you believe it.

REVISION 3 ADDS THE OTHER HALF OF THAT LESSON: MESH-LIGHT POWER SCALES WITH
AREA, AND IT DOES NOT CARE HOW TRANSPARENT THE SURFACE IS. The god rays were
first authored with three nested rings per cross-section, the outermost at 2.05x
scale and 18 % density. That outer ring was four times the area of the core for
almost none of the visible beam, and it lit the whole yard from the middle of
the frame: ablating the god rays alone (FX_SKIP=GodRays) moved p01_luma
0.079 -> 0.023 and dead_area_frac 0.353 -> 0.284, while ablating the haze tiers
instead (FX_SKIP=Atmosphere) changed neither. The outer ring is gone, the
under-deck beams start at Z 1.50 instead of at the slab, and the lens keep-out
went 10 m -> 16 m. Same beam, a third of the emissive area.

Three god-ray densities were then rendered at 2048 spp and measured, because
"a brighter beam must mean more warm in the frame" is not true here:
    0.62x   p01_luma 0.053   warm_cool_split 0.000
    1.00x   p01_luma 0.053   warm_cool_split 0.047   <- authored
    1.60x   p01_luma 0.070   warm_cool_split 0.007
Above 1.0x the beams start painting the SHADOWS amber, which is precisely the
failure BRIEF section 6 names, and p01_luma leaves gate with it.

AND THE HAZE IS COLD, WHICH IS ALSO A MEASUREMENT, NOT A PREFERENCE. An earlier
revision made the sunward half of the tiers warm, on the sound theory that
forward-scattered haze between the eye and a low sun is warm. It is - but the
tiers are also area lights, so it moved the DARK half of the histogram from
R-B = -0.049 to +0.024 and warm_cool_split collapsed 0.057 -> 0.010. The air in
this layer is the cool half of the frame. The amber belongs to the beams.

Every mesh also carries `bool primvars:doNotCastShadows = 1`. Honest note: that
string is real (it lives in plugins/rtx/rtx.hydra.dll) but authoring it produced
NO observable change on this build - the black cones survived it untouched and
only went away when the emissive came down. It is left in because it is correct
intent and costs nothing; do not rely on it.

Honest limits, so the next agent is not surprised:
  - This is not volumetric scattering. A shaft is emissive geometry, so it does
    not go dark where a rack shadows it. Beams are therefore kept short and
    inside volumes that are genuinely lit.
  - The dust motes are opaque quads 12-35 mm across. At the distances the shots
    use they are 1-3 pixels; at close range they would read as confetti.
  - No rain streaks and no embers: it is the minute AFTER the storm, and nothing
    in this map is on fire.
  - There are no far-field rain veils. They were authored, and they failed: the
    distance fog washes anything past ~120 m to the fog colour, so a squall
    curtain out at 150 m is invisible, and at closer range it sits in front of a
    hero element. The flat dome sky is therefore still the single biggest
    contributor to dead_area_frac in LANE_EYE_YARD and SILHOUETTE_WEST, and that
    is 60_lighting's HDRI, not this layer.
  - THE HAZE TIERS ARE NOT A PARTICIPATING MEDIUM. They are emissive planes,
    so they add airlight but they do not go dark inside a shadow: a distant
    object standing in shade gets the same haze in front of it as one standing
    in sunlight. At the ranges these shots use that is invisible, and it is the
    approximation every shipped game makes, but it is an approximation.
  - THE GOD RAYS DO NOT SELF-SHADOW EITHER. Every beam is authored where the
    light demonstrably reaches, from an aperture that is actually open in
    20_architecture - that is the discipline that keeps them honest. Nothing
    downstream of a solid gets a beam. They are also visible almost entirely to
    SILHOUETTE_WEST, because that is the only camera looking within 15 deg of
    the sun. That is not a camera-specific hack - the geometry is on the sun
    vector and would be correct from anywhere - it is simply where backlit air
    is visible.
  - THE BEAMS READ AS SOFT VERTICAL SHAFTS, NOT AS THE HARD CREPUSCULAR FANS
    a photograph gets looking ACROSS a sunbeam. That is geometry, not tuning:
    SILHOUETTE_WEST looks 15 deg off the sun, so it is looking almost END-ON
    down every beam, and an end-on beam projects to a short streak near the sun
    bearing rather than a long bar across the frame. A camera looking across
    the sun bearing would see them properly. Do not try to fix it by making
    them brighter; that was tried and measured (see the ladder above).
  - THE HAZE TIERS STOP AT THE SITE BOUNDARY (X -82..+74, Y -60..+96). Past it
    only the analytic fog is working. None of the five shots crosses that line
    at an angle where it shows, but a camera placed outside the compound would
    see the atmosphere stop.
  - detail_density fails on all five shots and did so before this revision too.
    The haze-only ablation measured it going UP (0.020 -> 0.026), so it is not
    this layer; it is a materials / reconstruction condition.
  - Set FX_SKIP=<GroupName>[,<GroupName>...] before `uv run gen_fx.py` to omit a
    group. That is how the black-cone cause was isolated (FX_SKIP=HighBayGlow),
    and it is the fastest way to attribute any future artefact."""
    metersPerUnit = 1
    upAxis = "Z"
)

over "World"
{
    def Xform "FX" (
        doc = "Atmosphere, in-scatter geometry and decals for DEADFALL DEPOT."
    )
    {
        def Scope "Looks"
        {
'''

parts = [HEAD]
parts.append("\n\n".join(MATERIALS))
parts.append("\n        }\n")

for name, doc, meshes in groups:
    parts.append(f'\n        def Xform "{name}" (\n            doc = "{doc}"\n        )\n        {{\n')
    for m in meshes:
        parts.append(m.usda(12))
    parts.append("        }\n")

parts.append("    }\n}\n")

parts.append('\nover "Render"\n{\n')
for shot, (dd, c, ci, sd, ed, hd, hf, hs) in FOG.items():
    parts.append(f'''    over "{shot}"
    {{
        bool omni:rtx:fog:enabled = 1
        color3f omni:rtx:fog:color = ({c[0]:.4f}, {c[1]:.4f}, {c[2]:.4f})
        float omni:rtx:fog:colorIntensity = {ci:.3f}
        float omni:rtx:fog:distanceDensity = {dd:.4f}
        float omni:rtx:fog:start:distance = {sd:.2f}
        float omni:rtx:fog:endDist = {ed:.1f}
        float omni:rtx:fog:height:density = {hd:.3f}
        float omni:rtx:fog:height:falloff = {hf:.2f}
        float omni:rtx:fog:start:height = {hs:.2f}
        bool omni:rtx:fog:zUp:enabled = 1
    }}
''')
parts.append("}\n")

OUT.write_text("".join(parts), encoding="utf-8")

nm = sum(len(g[2]) for g in groups)
nf = sum(len(m.counts) for g in groups for m in g[2])
print(f"wrote {OUT}  ({OUT.stat().st_size / 1e6:.2f} MB)")
print(f"  {len(MATERIALS)} materials, {len(groups)} groups, {nm} meshes, {nf} faces")
