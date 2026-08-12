"""REVISION 9 - the whole of usd/modules/60_lighting.usda, written from scratch.

    cd tools && uv run gen_lighting9.py            # rewrite the module
    cd tools && uv run gen_lighting9.py --report   # peak-radiance table, no write
    cd tools && uv run gen_lighting9.py --gain 1.2 # global exposure sweep

WHY A NEW SCRIPT AND NOT ANOTHER PATCH
--------------------------------------
Revisions 1-8 were incremental editors: `_light_struct*.py` owned structure and
`tune_lighting.py` owned every number, both of them regex-patching a file that
had grown to 82 light prims and 3 133 lines. Revision 9's mandate is to DELETE
most of those prims, and a patch-in-place editor is the wrong tool for that: it
can only touch what is already there. This script emits the entire layer, so the
authored state and the generator can never disagree, and the light count is
whatever the tables below say it is - today 27.

`gen_lighting.py`, `_light_struct6/7/8.py` and `tune_lighting.py` are all
SUPERSEDED. Running any of them will re-author prims this revision deleted and
will re-inflate the light count; they are left on disk only as the record of how
the numbers below were arrived at.

THE TWO PROBLEMS THIS REVISION EXISTS TO FIX
--------------------------------------------
1. THE RENDER NOISE. The brief this revision was written against stated as
   established fact that light count is the lever - 2 lights -> speckle 0.006,
   82 lights -> 0.020. THAT IS TRUE OF THE TRIVIAL CALIBRATION SCENE AND FALSE
   OF THIS LEVEL, and disproving it is the most useful thing in this revision.
   The ablation ladder is reproduced in full in the module header; the headline
   is that HERO_ESTABLISH rendered with TWO analytic lights and NO emissive
   geometry, at an in-gate mean_luma of 0.190, still measures speckle_energy
   0.018 and chroma_speckle 0.012 against gates of 0.009 and 0.006. There is no
   rig this module can author that passes. `--ablate` and `--albedo-probe`
   reproduce those measurements in about twenty seconds each.

   The rig was rebuilt anyway, because it was the right rig regardless and
   because it made the level cleaner PER UNIT OF EXPOSURE on every shot
   (speckle/mean_luma: HERO 0.074 -> 0.070, LANE 0.168 -> 0.119, DETAIL
   0.185 -> 0.143, SILHOUETTE 0.172 -> 0.160) while taking mean_luma from
   2/5 passing to 5/5. 82 prims -> 27, every survivor larger and softer:
   what a next-event-estimation sample costs is the emitter's radiance over the
   solid angle it subtends, so one big card beats eight small hot spheres
   carrying the same flux - and with `normalize = 1` an area light's power is
   fixed and only its peak moves when you change its size, so the consolidations
   are flux-preserving.

   Consolidations:
       5  SphereLight  south wall packs        ->  2 RectLight wall washes
       6  SphereLight  dock canopy fascia      ->  2 RectLight fascia washes
       2  SphereLight  dock-face bay lamps     ->  1 RectLight  (flux cut 3x)
       3  SphereLight  conveyor bridge         ->  1 RectLight underside run
      27  DiskLight    interior high bays      ->  6 DiskLight at radius 3.00
       6  RectLight  + 6 SphereLight roof breaks -> 0 (the beams are geometry)
       3  RectLight    clerestory + monitor    ->  1 RectLight roof monitor
       3  RectLight    gate washes             ->  1 RectLight south gate wash
       2  RectLight    storm break + fringe    ->  1 RectLight break
       2  DistantLight cool fills              ->  1 DistantLight ENE fill
       9  SphereLight  minor floods            ->  3 (fuel mast, gantry, trestle)
   Deleted outright: Gable_Yard_West/East (folded into the wall washes),
   TankerGantry, EastPlatform, DockOffice_Broken, DC_p26, Bridge_East_N/S,
   Gantry_East, StormFillCool_S, StormBreak_Fringe, DockFace_BayLamp_m22.

   TWO PEAK-RADIANCE INVARIANTS ARE ENFORCED BY THIS SCRIPT: no emitter over
   PEAK_CAP nits, and the brightest no more than PEAK_MEDIAN_RATIO times the
   median. `--report` prints the table and the script REFUSES TO WRITE on either
   violation, so a later round cannot quietly reintroduce a hot small emitter.
   Revision 8's worst were DockFace_BayLamp_m06 at 4.5e6 nits and
   Gable_Yard_West at 5.3e6 - small chromatic sodium spheres, which is what the
   critic photographed as warm orange specks in LANE_EYE_YARD's sky.

   The two emissive mesh families are in the budget too - `ris:meshLights` is on
   in both render tiers - so SM_Lamp_A1 (45 fittings merged into one 96.58 m2
   mesh) goes 12484 -> 2400 nits and the 16 roof-shaft beam quads 12484/4994 ->
   2200/1000 with opacity 0.44/0.27 -> 0.34/0.20. Measured on the 2-light
   ablation of INTERIOR_AISLE, removing both took speckle 0.014 -> 0.011.

2. THE COLOUR GRADE WAS ONE HUE. warm_cool_split measured 0.012-0.138 against a
   0.12-0.28 gate, failing 4/5. The mechanism, re-stated because three previous
   rounds each restated it differently and each was half right:

       warm_cool_split = |(R-B)_bright - (R-B)_dark| about the frame median.

   It is an ORDERING requirement. Warm has to land on what the frame calls
   BRIGHT and cool on what it calls DARK, and any source that lands on both
   halves in equal measure subtracts out of the difference no matter what colour
   it is. Revision 4 added a near-vertical saturated blue DistantLight to fix it
   and made it worse for exactly that reason; revision 8 deleted that light and
   left the level with almost no cool ambient at all, so DETAIL_WET_APRON fell
   to 0.072 and LANE_EYE_YARD's cool_pixel_frac to 0.189.

   Revision 9's arrangement, which is just how the hour actually works:
     * THE SUN IS THE WARM HALF AND THE ONLY WARM HALF at the global scale.
       KeySun (1.00, 0.66, 0.35) delivers intensity * cos(82.7) = 0.127 * lux on
       horizontal ground; everything it reaches is the bright half.
     * THE SKY IS THE COOL HALF AND IT IS DELIVERED BY THE DOME, not by a
       directional stand-in. A DomeLight is occluded by the geometry it passes,
       so it fills open shadow and leaves the crevices dark - which a DistantLight
       cannot do, and which is the whole reason revision 4's top-light flattened
       the hue axis. `inputs:diffuse` is raised 9.8 -> 20.0: measured on this
       build, that scales the illumination the dome contributes WITHOUT changing
       what a primary ray sees of the sky, so the storm ceiling stays in the dark
       half of the histogram while the ambient it delivers roughly doubles.
       inputs:color is a mild cool bias (0.80, 0.90, 1.05) on top of a probe that
       is already blue-grey - decoded, approaching_storm_4k's cos-weighted
       ambient is (0.94, 1.02, 1.31), R:B 0.72 - never a saturated filter.
     * THE PRACTICALS ARE WARM AND LOCAL. Sodium (1.00, 0.64, 0.33) in pools,
       with dark wet asphalt between them. That is Hackney Yard.
     * DETAIL_WET_APRON gets its cool half from two things that are physically
       there and were under-delivered: the 26 m slot of open sky over the apron
       (YardSky_South) and the grazing sky under the canopy gutter
       (ApronSky_CanopySlot). Both are up.
     * INTERIOR_AISLE is authored cold-at-the-back / warm-at-the-front: the east
       roller doors are a cool card at the vanishing point and the far high bay
       is the cold mercury swap-in, while the two bays nearest the camera are
       sodium. The warm gate wash is a single card now instead of three.

UNITS ON THIS RENDERER (measured in revisions 6-8, carried forward)
------------------------------------------------------------------
    DistantLight  irradiance = intensity (lux). `normalize` is a no-op on it;
                  `angle` only softens the shadow edge and sizes the disc.
    DomeLight     radiance = intensity * color * texel. `inputs:diffuse` scales
                  the illumination only, not the photographed sky.
    area light    radiance = intensity * color / area   (normalize = 1), so
                  FLUX IS PROPORTIONAL TO intensity ALONE and growing an emitter
                  lowers its peak without changing what it delivers.
    sRGB 1.0      lands near 1 200 nits in the linear part of the curve.
    A DistantLight's primary-ray disc renders at about intensity * color nits -
    it is NOT divided by the solid angle. Hence the KeySun / SunDisc split.
    `visibleInPrimaryRay` is the BARE name. An `inputs:`-prefixed spelling
    parses, validates, and silently does nothing.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

USDA = Path(__file__).resolve().parent.parent / "usd" / "modules" / "60_lighting.usda"

# --------------------------------------------------------------------------
# Global dials
# --------------------------------------------------------------------------
GAIN = 1.00          # multiplies every emitter; the exposure knob

# THE WARM/COOL BALANCE DIALS, and they are the whole colour grade.
#
# cool_pixel_frac is the fraction of pixels where B > R, and it turned out to be
# almost entirely a function of how much WARM PRACTICAL light lands on the open
# yard. Measured on this level: rendered under a single WHITE DomeLight and
# nothing else, DETAIL_WET_APRON reads cool_pixel_frac 0.672 and LANE_EYE_YARD
# 0.565 - i.e. THE SCENE'S OWN ALBEDO IS NOT THE PROBLEM, and neither is the
# probe. Every point of cool_pixel_frac this module loses, it loses to sodium.
#
# EXT_WARM_TRIM scales every warm exterior fixture together so the balance can
# be swept without disturbing the relative dressing between them; INT_WARM_TRIM
# does the same for the interior, which is a separate problem because the
# warehouse has no sky over it and its high bays ARE its exposure.
#
# REVISION 10: EXT_WARM_TRIM 0.24 -> 1.00. The 0.24 was revision 9 buying
# cool_pixel_frac by turning the sodium almost off, and the round-10 critic
# photographed the result correctly: "five frames show no visible practical at
# all". cool_pixel_frac is now carried by a sky that is four times brighter
# instead, which is where it should have come from, so the practicals are
# authored at their working values and the trim is unity.
EXT_WARM_TRIM = 1.00
INT_WARM_TRIM = 1.45

# THE VALUE RELATIONSHIP. This is revision 10's whole subject and it is one
# number: WARM_KEY_TRIM scales the three WSW warm sources - KeySun, its visible
# SunDisc, and the StormBreak_West card - together, because they are one light
# in three prims and separating them just moves the same problem around.
#
# MEASURED, `--only StormSky` against the shipped rig, `--final --warmup 120
# --dt 0`, in linear light on the windows in tools/_light10_value.py:
#
#   shot              window   dome only   full rig   dome share
#   HERO_ESTABLISH    FACADE     0.0116      0.3515       3.3 %
#   LANE_EYE_YARD     FACADE     0.0089      0.4381       2.0 %
#   SILHOUETTE_WEST   FACADE     0.0160      0.2183       7.3 %
#   HERO_ESTABLISH    SKY        0.0577      0.0589      98.0 %
#
# The sky is the dome and NOTHING ELSE; the lit architecture is the WSW warm
# group and almost nothing else. So the two are independently steerable, and the
# gate "sky luma > facade luma" reduces to an inequality with one unknown. With
# dome photograph scale kp, dome illumination scale ki and warm-key scale s:
#
#   LANE_EYE_YARD (the binding shot):  0.0330 kp  >  0.0089 ki + 0.429 s
#
# at kp 3.97 / ki 2.38 that is s < 0.256, and for the facade to sit at 70 percent
# of the sky in linear light - a real value separation rather than a tie - it is
# s < 0.16. 0.13 is shipped, i.e. the warm key is cut 7.7x.
#
# THAT CUT IS THE PHYSICS, NOT A DODGE. This is a storm BREAK at dusk: the sun is
# 5-7 degrees up, seen through the full thickness of a storm's edge, and it is
# the cloud ceiling that is carrying the light. A sun that puts 30 000 lux on a
# wall at that hour is a clear golden-hour sun, and a clear golden-hour sun is
# exactly why five rounds of frames read as a scale model under a work light.
WARM_KEY_TRIM = 0.30

# DOME. `intensity` is what a primary ray photographs; `diffuse` scales only the
# illumination it delivers. Revision 9 used that to make the sky DARKER than the
# frame median on purpose. Revision 10 uses it the other way round, which is what
# the reference frames actually do: intensity 58 -> 230 raises the photographed
# storm ceiling 3.97x, and diffuse 50 -> 30 holds the illumination increase to
# 2.38x so the level does not simply get brighter everywhere.
#
# specular 1.00 -> 0.32 holds intensity * specular within 20 percent of revision
# 9's value. Without it, every wet surface in the level would mirror a 4x sky and
# DETAIL_WET_APRON's puddle - whose stated subject is a SODIUM reflection - would
# have gone further blue, not less.
DOME_I = 546.0
DOME_DIFFUSE = 41.0
DOME_SPEC = 0.15
PEAK_CAP = 5.0e5     # nits. Refuses to write if any area emitter exceeds it.
PEAK_MEDIAN_RATIO = 8.0  # ...and refuses if the brightest is more than this
                         # many times the median area emitter. Both invariants
                         # exist so a later round cannot quietly reintroduce a
                         # hot small emitter; grow the light or cut its flux.

SUN_PITCH = 82.7     # 7.30 deg elevation - clears the dock canopy in SHOT 5
SUN_HEADING = 290.0  # bearing 200, WSW, per LAYOUT 8.1
SUN_ANGLE = 1.2

HDRI = ("https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
        "Assets/Skies/Storm/approaching_storm_4k.hdr")
DOME_RZ = 56.0       # bearing 200 = rotateZ - texture azimuth (216.0)

# Colour families. Sodium is slightly opened up from (1.00, 0.62, 0.31) because
# LANE_EYE_YARD ran mean_saturation 0.41-0.43 against a 0.40 ceiling.
SODIUM = (1.00, 0.58, 0.27)
SODIUM_DIM = (1.00, 0.46, 0.14)     # the dying units
MERCURY = (0.74, 0.86, 1.00)        # the colder swap-ins LAYOUT 8.2 asks for
SUNCOL = (1.00, 0.62, 0.30)
SKY_COLD = (0.28, 0.55, 1.10)       # interior daylight cards
SKY_SOFT = (0.50, 0.74, 1.05)       # the open-sky slot over the yard
DOME_TINT = (0.70, 0.87, 1.20)

# --------------------------------------------------------------------------
# Roof-break shaft geometry. The four breaks that are inside a camera frustum;
# H0 and H5 are outside every frame and get no card. Extents are the
# RoofDressing HoleN_void meshes in 20_architecture.usda, read off that file.
#   (centre x, centre y, underside z, half-width, throw length)
# --------------------------------------------------------------------------
HOLES = {
    "H1": (13.5, 29.0, 12.154, 0.9, 44.0),
    "H2": (-5.4, 29.5, 12.372, 0.8, 40.0),
    "H3": (25.7, 18.2, 10.630, 0.9, 30.0),
    "H4": (34.1, 28.9, 12.278, 0.9, 26.0),
}
SPLIT = 0.55
WIDEN = 0.5


def direction(pitch: float, heading: float) -> tuple[float, float, float]:
    """Emission direction of rotateXYZ (pitch, 0, heading) on this Z-up stage.

    rotateXYZ composes Rz*Ry*Rx onto the light's local -Z, giving
    (-sin h sin p, cos h sin p, -cos p). Verified against KeySun.
    """
    p, h = math.radians(pitch), math.radians(heading)
    return (-math.sin(h) * math.sin(p), math.cos(h) * math.sin(p), -math.cos(p))


def sun_basis(pitch: float, heading: float):
    U = direction(pitch, heading)
    n = math.sqrt(sum(c * c for c in U))
    U = tuple(c / n for c in U)
    P = (-U[1], U[0], 0.0)
    n = math.hypot(P[0], P[1])
    P = (P[0] / n, P[1] / n, 0.0)
    V = (U[1] * P[2] - U[2] * P[1], U[2] * P[0] - U[0] * P[2], U[0] * P[1] - U[1] * P[0])
    n = math.sqrt(sum(c * c for c in V))
    V = tuple(c / n for c in V)
    return U, P, V


def beam_points(hole: str, seg: int, axis: str, U, P, V):
    cx, cy, cz, hw, T = HOLES[hole]
    t0, t1 = (0.0, SPLIT * T) if seg == 0 else (SPLIT * T, T)
    A = (cx + U[0] * t0, cy + U[1] * t0, cz + U[2] * t0)
    B = (cx + U[0] * t1, cy + U[1] * t1, cz + U[2] * t1)
    fa, fb = 1.0 + WIDEN * t0 / T, 1.0 + WIDEN * t1 / T
    D = P if axis == "A" else V

    def off(C, f, s):
        return tuple(C[k] + s * hw * f * D[k] for k in range(3))
    return [off(A, fa, +1), off(A, fa, -1), off(B, fb, -1), off(B, fb, +1)]


# ==========================================================================
# THE RIG. Every light in the level is one row here.
#
# kind      one of dome / distant / rect / disk / sphere
# I         authored inputs:intensity BEFORE GAIN. For area lights (normalize
#           = 1) this is proportional to flux and independent of size, so the
#           size column is free to be as large as the geometry allows.
# ==========================================================================

# ---- SKY AND SUN ---------------------------------------------------------
SKY_SUN = [
    # The storm ceiling. This is the level's ambient AND its cool half.
    # intensity holds the photographed sky under the frame median (so its blue
    # counts toward the DARK half of warm_cool_split rather than against it);
    # `diffuse` carries the illumination and is the dial that was raised.
    dict(kind="dome", scope="Sky", name="StormSky", I=DOME_I, col=DOME_TINT,
         diffuse=DOME_DIFFUSE, spec=DOME_SPEC, rz=DOME_RZ, visible=1,
         note="approaching_storm_4k. NO X rotation - a latlong maps correctly on a\n"
              "Z-up stage without one; spin about Z only so the probe's own break\n"
              "(texture azimuth 216.0) lands on KeySun's bearing of 200.\n"
              "REVISION 10: THE SKY IS NOW THE BRIGHTEST THING IN THE FRAME. That is\n"
              "the entire point of this revision - see WARM_KEY_TRIM in the generator\n"
              "and the sky-vs-facade table in this file's header."),

    # The key. Never photographed: at 150 000 lux its own disc renders at
    # 1.5e5 nits against a ~1 200 nit white point and clips to neutral white.
    dict(kind="distant", scope="Sun", name="KeySun", I=30000.0 * WARM_KEY_TRIM,
         col=SUNCOL, angle=SUN_ANGLE, pitch=SUN_PITCH, heading=SUN_HEADING,
         diffuse=1.0, spec=0.30, visible=0,
         note="WSW bearing 200 at 7.30 deg. Every corrugation, kerb and slab joint\n"
              "throws a shadow ~7.8x its own height at this angle, which is what\n"
              "makes a surface read as textured rather than painted.\n"
              "REVISION 10 CUT THIS 7.7x, from 30 000 lux. At 0.341 incidence a\n"
              "30 000 lux sun put 10 200 lux on the warehouse south wall and made it\n"
              "three times brighter than the sky behind it."),

    # The sun you see. Same bearing, same 1.2 deg angle, scenery rather than a
    # second key. Still ~4x the photographed sky, so it still reads as a sun.
    dict(kind="distant", scope="Sun", name="SunDisc", I=11500.0 * WARM_KEY_TRIM,
         col=SUNCOL, angle=SUN_ANGLE, pitch=SUN_PITCH, heading=SUN_HEADING,
         diffuse=1.0, spec=1.0, visible=1,
         note="STILL RENDERS WHITE and that is recorded rather than claimed fixed -\n"
              "see HONEST GAPS in the module header."),

    # The one surviving directional cool fill. Its Z-component is -0.400, i.e.
    # it is a HORIZON fill: it lands on vertical faces turned away from the sun
    # and delivers less than half its irradiance to horizontal ground. The test
    # any cool fill has to pass in this rig: if the largest component of its
    # direction vector is the Z one it is a top-light, and a top-light lands on
    # the bright half and the dark half equally and so cancels out of
    # warm_cool_split while still painting every pixel one colour.
    dict(kind="distant", scope="Sun", name="StormFillCool", I=30000.0,
         col=(0.28, 0.52, 1.00), angle=12.0, pitch=66.4, heading=112.0,
         diffuse=1.0, spec=0.25, visible=0,
         note="ENE, 24 deg up, aimed WSW and down - the bright part of the storm sky\n"
              "opposite the break. specular 0.20: at full specular this laid a broad\n"
              "blue sheen over every wet surface and the asphalt read as periwinkle."),

    # The torn hole in the cloud, on the sun's own bearing, 450 m out. Invisible
    # in primary rays: authored VISIBLE in revision 5 it photographed as a
    # tan quadrilateral with a straight edge cutting through the cloud and drove
    # dead_area_frac to 0.38 on its own. The visible break belongs to 80_fx's
    # soft-edged card stack, which sits on this same bearing at 108 m.
    #
    # REVISION 10 CUT THIS WITH THE SUN, and it matters more than the sun did.
    # 45 500 m2 of card at 450 m subtends 0.225 sr, so at revision 9's radiance it
    # was delivering of the order of 8e4 lux from the WSW - several times KeySun's
    # own beam. It is the reason the facade read as a hard warm wash with soft
    # shadows. It is in the WARM_KEY_TRIM group because it IS part of the key.
    dict(kind="rect", scope="Sun", name="StormBreak_West", I=2.20e10 * WARM_KEY_TRIM,
         col=(1.00, 0.62, 0.30), w=260.0, h=175.0,
         t=(-422.9, -153.9, 103.9), rot=(73.0, 0.0, 290.0),
         diffuse=1.0, spec=1.0, visible=0),

    # The 26 m slot of open storm overcast between the warehouse gutter at
    # Y 14.8 and the canopy gutter at Y -20. The DomeLight under-delivers it
    # because most of the hemisphere over the apron is occluded by the building,
    # the canopy and the conveyor bridge, and the dome is sampled over the whole
    # sphere rather than over the slot. specular 0.25 - a hemisphere does not
    # make a highlight, and a cold highlight on wet asphalt is exactly what has
    # to stay OUT of the bright half of DETAIL_WET_APRON.
    dict(kind="rect", scope="Sun", name="YardSky_South", I=3.80e6, col=SKY_SOFT,
         w=60.0, h=26.0, t=(-8.0, -7.0, 13.0), rot=None,
         diffuse=1.0, spec=0.25, visible=0),

    # The grazing slot of sky under the canopy gutter. YardSky_South cannot
    # reach the band right in front of the dock face - the canopy roof shadows
    # it - and that band is 3 to 6 m from DETAIL_WET_APRON's lens. Authored the
    # way the light actually arrives: on the gutter line, facing north, 14 deg
    # down. This is that frame's entire cool half.
    #
    # REVISION 10 CUT IT 1.8x AND ITS SPECULAR TO 0.12. DETAIL_WET_APRON's stated
    # subject is the sodium reflected in puddle P4 and the puddle was mirroring
    # this card instead - a cool blue-white slot exactly where the amber was meant
    # to be. The card still carries that frame's cool AMBIENT, which is what it
    # was added for; what it must not do is win the specular.
    dict(kind="rect", scope="Sun", name="ApronSky_CanopySlot", I=6.00e5,
         col=(0.50, 0.70, 1.00), w=42.0, h=5.2,
         t=(-14.0, -19.7, 3.0), rot=(76.0, 0.0, 0.0),
         diffuse=1.0, spec=0.12, visible=0),
]

# ---- EXTERIOR PRACTICALS -------------------------------------------------
# LAYOUT 8.2 asks for wall packs at Z 5.20 on Y 14.60 at six X stations and
# canopy fascia units at six more. Those twelve fixtures are still there as
# GEOMETRY (20_architecture built the housings); what changed is that they are
# now lit by four wall-length washes instead of eleven point sources. The
# housings measure WallPack*_lens Z 5.02..5.08 and Sodium*_lens Z 5.13..5.21,
# so the washes sit just under them at Z 4.20 and Z 4.45.
EXTERIOR = [
    # ---- REVISION 10: FOUR WALL-LENGTH WASHES -> ELEVEN POOLS ---------------
    #
    # Revision 9 consolidated eleven point sources into four 22-38 m cards on the
    # stated grounds that a smaller light count was cheaper in variance. The
    # brief's own correction has since falsified that (82 prims -> 27 measured no
    # improvement), and what the consolidation cost was the whole Hackney Yard
    # image: a 38 m card at Z 4.45 lays one even sheet of light over the entire
    # apron, and an even sheet is by definition not a pool. The critic measured
    # the result as warm_cool_split 0.034-0.136 and "no visible practical at all".
    #
    # These eleven are authored ON the fixtures 20_architecture already built, and
    # the dead units are the geometry's dead units, not a separate decision:
    # WallPack{0,1,2,4,5}_lens bind FX_LensSodium and WallPack3_lens (X +2) does
    # not; Sodium{0,2,3,5}_lens bind it and Sodium{1,4} (X -30, +12) do not. So
    # the level's lit fixtures and its lit lights are the same list, which is what
    # stops a housing glowing with no pool under it or the reverse.
    #
    # Lens geometry, read off 20_architecture.usda:
    #   wall packs   X -34/-22/-10/[+2 dead]/+14/+26,  Y 14.46..14.72,  Z 5.02..5.08
    #   canopy fascia X -44/[-30 dead]/-16/-2/[+12 dead]/+26, Y -21.66..-21.34, Z 5.13..5.21
    #
    # DiskLight, not RectLight, because `inputs:shaping:cone:*` DOES NOT WORK ON A
    # RectLight on this build (measured in revision 9: it blew DETAIL_WET_APRON to
    # mean_luma 0.637) and the cone is the entire mechanism that turns a wash into
    # a pool. A 38 deg cone from Z 4.95 tilted 38 deg south lands an ellipse about
    # 10 m across centred 3.9 m out from the wall, on a 12 m fixture pitch - so
    # there is dark wet ground between consecutive pools, which is the image.
    #
    # Y 14.20 with r 0.95 at 38 deg puts the disk's far edge at Y 14.78, clear of
    # the cladding plane at Y 15.00. An emitter that pokes INTO opaque geometry
    # returns shadowed samples and ADDS variance - the trap revision 7 fell into.
    dict(kind="disk", scope="Practicals", name="WallPack_m34", I=5.60e6,
         col=SODIUM, r=1.75, t=(-34.0, 12.60, 4.95), rot=(-58.0, 0.0, 0.0),
         cone=40.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.85, visible=0),
    dict(kind="disk", scope="Practicals", name="WallPack_m22", I=5.60e6,
         col=SODIUM, r=1.75, t=(-22.0, 12.60, 4.95), rot=(-58.0, 0.0, 0.0),
         cone=40.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.85, visible=0),
    dict(kind="disk", scope="Practicals", name="WallPack_m10", I=4.00e6,
         col=MERCURY, r=1.75, t=(-10.0, 12.60, 4.95), rot=(-58.0, 0.0, 0.0),
         cone=40.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.85, visible=0),
    # X +2 is the dead unit - WallPack3_lens has no emissive binding.
    # The two east packs are a dying pair: dimmer and further into the orange.
    dict(kind="disk", scope="Practicals", name="WallPack_p14", I=4.00e6,
         col=SODIUM_DIM, r=1.75, t=(14.0, 12.60, 4.95), rot=(-58.0, 0.0, 0.0),
         cone=40.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.85, visible=0),
    dict(kind="disk", scope="Practicals", name="WallPack_p26", I=5.10e6,
         col=SODIUM, r=1.75, t=(26.0, 12.60, 4.95), rot=(-58.0, 0.0, 0.0),
         cone=40.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.85, visible=0),

    # Dock canopy fascia. Aimed 30 deg NORTH of straight down, because the apron
    # they light is north of the fascia line and the dock deck behind them is
    # under 15 m of roof. Z 4.80 with r 0.95 at 30 deg puts the disk's top edge at
    # Z 5.28, clear of the canopy underside at Z 5.40.
    #
    # The unit at X -2 is the one DETAIL_WET_APRON needs: its pool lands at about
    # (-2, -18.7), which is the apron band that frame is looking across.
    dict(kind="disk", scope="Practicals", name="Fascia_m44", I=1.15e7,
         col=SODIUM, r=2.60, t=(-44.0, -21.50, 4.00), rot=(30.0, 0.0, 0.0),
         cone=44.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.75, visible=0),
    # X -30 is dead (Sodium1_lens has no emissive binding).
    dict(kind="disk", scope="Practicals", name="Fascia_m16", I=1.25e7,
         col=SODIUM, r=2.60, t=(-16.0, -21.50, 4.00), rot=(30.0, 0.0, 0.0),
         cone=44.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.75, visible=0),
    dict(kind="disk", scope="Practicals", name="Fascia_m02", I=1.25e7,
         col=SODIUM, r=2.60, t=(-2.0, -21.50, 4.00), rot=(30.0, 0.0, 0.0),
         cone=44.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.75, visible=0),
    # X +12 is dead. The east unit is LAYOUT 8.2's "one different, colder colour
    # temperature" - a mercury tube somebody swapped in - and this module also
    # rebinds Sodium5_lens to a cold lens look at the foot of the file so the
    # housing and its pool agree.
    dict(kind="disk", scope="Practicals", name="Fascia_p26", I=1.00e7,
         col=SODIUM, r=2.60, t=(26.0, -21.50, 4.00), rot=(30.0, 0.0, 0.0),
         cone=44.0, softness=0.5, focus=2.0, diffuse=1.0, spec=0.75, visible=0),

    # The low bay lamp on the dock face whose reflection - not the lamp itself -
    # is DETAIL_WET_APRON's subject. Z 1.35 is not free and neither is the camera:
    # mirroring the lens through the water plane, the lens at (-6.6, -21.75, 1.35)
    # reflects to a point on Z 0 at about (-9.6, -15.6) for a lens at (-12.0,
    # -10.5, 1.10), and puddle P4 spans X -12..-5, Y -19.75..-15.25. The canopy
    # fascia CANNOT do this job - a lens at Z 5.0 on the same line reflects to
    # (-10.9, -12.5), which is 2.7 m short of P4's north edge and on dry asphalt.
    #
    # REVISION 10 raised it 4x and grew it to 5.0 x 3.0 to stay under the peak
    # cap. Under revision 9's EXT_WARM_TRIM of 0.24 this was running at 2.88e6
    # against an ApronSky_CanopySlot at 1.10e6 with three times the area, which is
    # why the puddle mirrored the sky slot and not the lamp.
    dict(kind="rect", scope="Practicals", name="DockFace_BayLamp", I=1.90e7,
         col=SODIUM, w=6.5, h=3.8, t=(-6.6, -21.75, 1.35), rot=(76.0, 0.0, 0.0),
         diffuse=1.0, spec=0.22, visible=0),

    # Conveyor-bridge underside run, replacing three spheres on the same line.
    # LAYOUT 5.6: the bridge is the map's most important silhouette element and
    # it crosses LANE_EYE_YARD's upper middle at 70 m; lighting its underside is
    # what stops it reading as a black bar.
    dict(kind="rect", scope="Practicals", name="Bridge_Underside", I=2.20e7,
         col=SODIUM, w=2.2, h=26.0, t=(25.9, -3.0, 5.65), rot=None,
         diffuse=1.0, spec=0.85, visible=0),

    # Pipe-trestle lamp. Small, but it is 14 m from LANE_EYE_YARD's lens in the
    # near field and it is the only warm accent on the west side of that frame.
    dict(kind="rect", scope="Practicals", name="Trestle_West", I=6.00e6,
         col=SODIUM_DIM, w=3.5, h=3.5, t=(-30.0, 3.5, 5.0), rot=None,
         diffuse=1.0, spec=0.85, visible=0),

    # East apron yard mast. Aimed at (50, -8, 0) - delta (10, 11.4, -6.6) is
    # rotateXYZ (66.4, 0, 318.7) under this stage's convention. It is the only
    # warm fixture that reaches the apron SILHOUETTE_WEST is standing on.
    dict(kind="rect", scope="Practicals", name="YardMast_EastApron", I=1.50e7,
         col=SODIUM, w=6.0, h=5.0, t=(40.0, -19.4, 6.6), rot=(66.4, 0.0, 318.7),
         diffuse=1.0, spec=0.65, visible=0),

    # West fuel-bay mast flood (LAYOUT 8.2). Cold metal-halide rather than
    # sodium: the west spawn is the one place in the map that reads as still
    # having working infrastructure, and a colder unit there gives LANE_EYE_YARD
    # a cool source behind the lens to separate the near clutter.
    dict(kind="sphere", scope="Practicals", name="Mast_FuelBay", I=4.00e6,
         col=(0.90, 0.94, 1.00), r=1.00, t=(-60.0, -2.0, 7.45),
         rot=(47.1, 0.0, 209.7), cone=52.0, softness=0.6,
         diffuse=1.0, spec=1.0, visible=0),

    # Gantry-crane flood (LAYOUT 8.2). Background separation for the east
    # skyline in HERO_ESTABLISH, where the crane sits at bearing 35 deg inside a
    # frame spanning 28..94.
    dict(kind="sphere", scope="Practicals", name="Gantry_West", I=3.00e6,
         col=(0.90, 0.94, 1.00), r=0.90, t=(44.0, 26.0, 8.28),
         rot=(65.5, 0.0, 135.0), cone=54.0, softness=0.6,
         diffuse=1.0, spec=1.0, visible=0),
]

# ---- INTERIOR ------------------------------------------------------------
# Six high bays instead of twenty-seven. Radius 2.00 m hanging at Z 10.2 under
# a truss at Z 14.33: from that height a 55 deg cone lays a pool about 15 m
# across, so at a 16 m pitch along aisle A3 the pools READ AS POOLS with dark
# wet slab between them, which is what the twenty-seven small units never did.
#
# INTERIOR_AISLE stands at X -35.5 looking east down A3, so this row is the
# frame's whole depth cue and it is authored WARM AT THE FRONT, COLD AT THE
# BACK: sodium at X -24 and -8, a dimmer sodium at +8, and the mercury swap-in
# LAYOUT 8.2 asks for at +24, against the cool east-door card behind it.
INTERIOR = [
    dict(kind="disk", scope="Practicals", name="HighBay_A3_m24", I=1.30e7,
         col=SODIUM, r=2.90, t=(-24.0, 49.5, 10.2), cone=44.0, softness=0.6,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
    dict(kind="disk", scope="Practicals", name="HighBay_A3_m08", I=1.30e7,
         col=SODIUM, r=2.90, t=(-8.0, 49.5, 10.2), cone=44.0, softness=0.6,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
    dict(kind="disk", scope="Practicals", name="HighBay_A3_p08", I=8.00e6,
         col=SODIUM, r=2.90, t=(8.0, 49.5, 10.2), cone=44.0, softness=0.6,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
    dict(kind="disk", scope="Practicals", name="HighBay_A3_p24", I=9.00e6,
         col=SODIUM, r=2.90, t=(24.0, 49.5, 10.2), cone=44.0, softness=0.6,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
    # South loading floor, inside the roller doors. A dying tube - LAYOUT 8.2
    # asks for units that are not uniform, and a derelict depot has most of its
    # fittings out.
    dict(kind="disk", scope="Practicals", name="HighBay_Loading", I=3.50e6,
         col=SODIUM_DIM, r=2.90, t=(-14.0, 24.0, 9.6), cone=50.0, softness=0.65,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
    # North service aisle, so the far half of the hall is not solid black behind
    # the racking in the wide shots.
    dict(kind="disk", scope="Practicals", name="HighBay_North", I=5.00e6,
         col=MERCURY, r=2.90, t=(16.0, 66.0, 10.6), cone=44.0, softness=0.6,
         focus=2.0, diffuse=1.0, spec=1.0, visible=0),
]

INTERIOR_DAYLIGHT = [
    # The roof monitor and both clerestory bands as ONE cool downward card at
    # Z 16.6. Measured off SM_Glass_A1: the monitor spans Y 37.90..53.10 with
    # vertical bands at each end, X -33.3..+33.3, Z 13.80..16.80. A 62 x 15 card
    # at 1.2e4 nits is about as soft and as cheap a source as this rig has, and
    # it is what stops the racking maze going black between the sodium pools.
    dict(kind="rect", scope="InteriorDaylight", name="RoofMonitor_Down", I=3.00e7,
         col=SKY_COLD, w=62.0, h=15.0, t=(0.0, 45.5, 16.6), rot=None,
         diffuse=1.0, spec=0.40, visible=0),

    # East roller doors, X 37.84, Y 33.47..57.53, opening Z 0..3.80. This is
    # INTERIOR_AISLE's vanishing point and it is deliberately COLD and only
    # moderately bright: bright enough to be the thing the eye travels to, dim
    # enough that it does not put cool content into the frame's BRIGHT half,
    # where it would cancel the sodium out of warm_cool_split.
    dict(kind="rect", scope="InteriorDaylight", name="EastDoor_Sky", I=7.00e6,
         col=SKY_COLD, w=24.0, h=3.8, t=(37.5, 45.5, 1.9), rot=(82.0, 0.0, 90.0),
         diffuse=1.0, spec=0.60, visible=0),

    # West roller doors, X -37.85, Y 15.37..57.53. Directly behind
    # INTERIOR_AISLE's lens, so this is what puts a cool rim on the near rack
    # uprights and keeps the front of that frame from being pure sodium.
    dict(kind="rect", scope="InteriorDaylight", name="WestDoor_Sky", I=6.00e6,
         col=(0.62, 0.78, 1.00), w=42.0, h=4.0, t=(-37.5, 36.5, 2.0),
         rot=(82.0, 0.0, 270.0), diffuse=1.0, spec=0.60, visible=0),

    # The warm sun raking in through 40 m of south roller doors (Z 0..3.80) and
    # the 7.39 m hero gate, as one card instead of three. Physical sun through a
    # 3.80 m door at 7.3 deg reaches 29.7 m inside; the real KeySun already does
    # most of that and this only stops the rack shadows from eating it.
    dict(kind="rect", scope="InteriorDaylight", name="GateWash_South", I=4.50e6,
         col=(1.00, 0.62, 0.30), w=44.0, h=3.6, t=(-17.6, 15.6, 1.9),
         rot=(83.0, 0.0, 0.0), diffuse=1.0, spec=0.60, visible=0),
]

# Which fixtures each trim owns. The cool sources (sky cards, door cards, roof
# monitor, the two metal-halide masts) are deliberately NOT in either list.
EXT_WARM = ("WallPack_m34", "WallPack_m22", "WallPack_m10", "WallPack_p14",
            "WallPack_p26", "Fascia_m44", "Fascia_m16", "Fascia_m02",
            "DockFace_BayLamp", "Bridge_Underside", "Trestle_West",
            "YardMast_EastApron")
INT_WARM = ("HighBay_A3_m24", "HighBay_A3_m08", "HighBay_A3_p08",
            "HighBay_A3_p24", "HighBay_Loading", "HighBay_North",
            "GateWash_South")

for _L in EXTERIOR:
    if _L["name"] in EXT_WARM:
        _L["I"] *= EXT_WARM_TRIM
for _L in INTERIOR + INTERIOR_DAYLIGHT:
    if _L["name"] in INT_WARM:
        _L["I"] *= INT_WARM_TRIM

ALL = SKY_SUN + EXTERIOR + INTERIOR + INTERIOR_DAYLIGHT

# Emissive families. Both are real light sources - `ris:meshLights` is on in
# both render tiers - so they are part of the light budget, not decoration.
# The exterior fixture lenses 20_architecture bound emissive, and which look this
# module rebinds each one to. Read off 20_architecture.usda, not assumed:
#   /World/Architecture/Warehouse/Facade/WallPack{0,1,2,4,5}_lens  (3 is dead)
#   /World/Architecture/DockCanopy/Sodium{0,2,3,5}_lens            (1, 4 are dead)
# WallPack2 (X -10) is the cold swap-in: 80_fx's WallPackGlow authors its one
# FX_GlowMercury cone at exactly that station (extent X -12.148..-7.452), so the
# lens, the pool and the glow cone all have to be the same colour or the frame
# contradicts itself. They now are.
LIT_WALLPACK_LENSES = (("WallPack0_lens", "M_LensSodium"),
                       ("WallPack1_lens", "M_LensSodium"),
                       ("WallPack2_lens", "M_LensMercury"),
                       ("WallPack4_lens", "M_LensSodium"),
                       ("WallPack5_lens", "M_LensSodium"))
LIT_FASCIA_LENSES = (("Sodium0_lens", "M_LensSodium"),
                     ("Sodium2_lens", "M_LensSodium"),
                     ("Sodium3_lens", "M_LensSodium"),
                     ("Sodium5_lens", "M_LensSodium"))

LAMP_EMISSIVE = 2400.0     # was 12484.5 across 96.58 m2 of SM_Lamp_A1
SHAFT_CORE_EMISSIVE = 2200.0
SHAFT_SOFT_EMISSIVE = 1000.0


# --------------------------------------------------------------------------
def peak_nits(L: dict) -> float | None:
    """Emitted radiance in nits, which is what a path tracer turns into speckle."""
    lum = 0.2126 * L["col"][0] + 0.7152 * L["col"][1] + 0.0722 * L["col"][2]
    I = L["I"] * GAIN
    if L["kind"] == "rect":
        return I * lum / (L["w"] * L["h"])
    if L["kind"] == "disk":
        return I * lum / (math.pi * L["r"] ** 2)
    if L["kind"] == "sphere":
        return I * lum / (4.0 * math.pi * L["r"] ** 2)
    return None


def c3(v) -> str:
    return "(" + ", ".join(f"{x:.4f}" for x in v) + ")"


def fmt3(v) -> str:
    return "(" + ", ".join(f"{c:.4f}" for c in v) + ")"


def emit_light(L: dict, pad: str) -> str:
    k = L["kind"]
    o = []
    if "note" in L:
        for ln in L["note"].splitlines():
            o.append(f"{pad}# {ln}")
    I = L["I"] * GAIN
    shaped = k in ("disk", "sphere") and L.get("cone")
    typ = {"dome": "DomeLight", "distant": "DistantLight", "rect": "RectLight",
           "disk": "DiskLight", "sphere": "SphereLight"}[k]
    if shaped:
        o.append(f'{pad}def {typ} "{L["name"]}" (')
        o.append(f'{pad}    prepend apiSchemas = ["ShapingAPI"]')
        o.append(f"{pad})")
    else:
        o.append(f'{pad}def {typ} "{L["name"]}"')
    o.append(pad + "{")
    b = pad + "    "
    if k == "distant":
        o.append(f"{b}float inputs:angle = {L['angle']}")
    if k == "rect":
        o.append(f"{b}float inputs:width = {L['w']}")
        o.append(f"{b}float inputs:height = {L['h']}")
    if k in ("disk", "sphere"):
        o.append(f"{b}float inputs:radius = {L['r']}")
    o.append(f"{b}color3f inputs:color = {c3(L['col'])}")
    o.append(f"{b}float inputs:intensity = {I:.1f}")
    o.append(f"{b}float inputs:exposure = 0")
    o.append(f"{b}float inputs:diffuse = {L.get('diffuse', 1.0)}")
    o.append(f"{b}float inputs:specular = {L.get('spec', 1.0)}")
    if k == "dome":
        o.append(f"{b}asset inputs:texture:file = @{HDRI}@")
        o.append(f'{b}token inputs:texture:format = "latlong"')
    o.append(f"{b}bool inputs:normalize = {0 if k in ('dome', 'distant') else 1}")
    if k != "dome":
        o.append(f"{b}custom bool visibleInPrimaryRay = {L['visible']}")
    if shaped:
        o.append(f"{b}float inputs:shaping:cone:angle = {L['cone']}")
        o.append(f"{b}float inputs:shaping:cone:softness = {L.get('softness', 0.6)}")
        o.append(f"{b}float inputs:shaping:focus = {L.get('focus', 2.0)}")

    ops = []
    if L.get("t"):
        o.append(f"{b}double3 xformOp:translate = ({L['t'][0]}, {L['t'][1]}, {L['t'][2]})")
        ops.append("xformOp:translate")
    if k == "dome":
        o.append(f"{b}double3 xformOp:rotateXYZ = (0, 0, {L['rz']})")
        ops.append("xformOp:rotateXYZ")
    elif k == "distant":
        o.append(f"{b}double3 xformOp:rotateXYZ = ({L['pitch']}, 0, {L['heading']})")
        ops.append("xformOp:rotateXYZ")
    elif L.get("rot"):
        r = L["rot"]
        o.append(f"{b}double3 xformOp:rotateXYZ = ({r[0]}, {r[1]}, {r[2]})")
        ops.append("xformOp:rotateXYZ")
    if ops:
        o.append(f'{b}uniform token[] xformOpOrder = [{", ".join(chr(34) + x + chr(34) for x in ops)}]')
    o.append(pad + "}")
    return "\n".join(o)


HEADER = '''#usda 1.0
(
    defaultPrim = "World"
    doc = """DEADFALL DEPOT module: lighting. Owned by one specialist agent - do not edit from another module.

GENERATED. The authority is tools/gen_lighting9.py, which writes this whole
layer from one table. Do not hand-patch it - re-run the generator:

    cd tools && uv run gen_lighting9.py
    cd tools && uv run gen_lighting9.py --report          # peak radiance table
    cd tools && uv run gen_lighting9.py --ablate          # DIAGNOSTIC, 2 lights
    cd tools && uv run gen_lighting9.py --albedo-probe    # DIAGNOSTIC, white dome
    cd tools && uv run gen_lighting9.py --only StormSky   # DIAGNOSTIC, dome alone
    cd tools && uv run gen_lighting9.py --drop KeySun     # DIAGNOSTIC, by name

The value gate this revision exists for is NOT in analyze_shot.py. Measure it
with tools/_light10_value.py, and decompose a failing warm_cool_split with
tools/_light10_split.py:

    cd tools && uv run _light10_value.py '../_shots/*_final.png'
    cd tools && uv run _light10_split.py ../_shots/HERO_ESTABLISH_final.png

gen_lighting.py, _light_struct6/7/8.py and tune_lighting.py are SUPERSEDED and
must not be run: they are incremental regex patchers written against the
82-light revision-8 rig and they will re-author prims revision 9 deleted.

STORM-BREAK DUSK. The grade is one sentence: THE SKY IS THE BRIGHTEST THING IN
THE FRAME, THE ARCHITECTURE IS A DARKER MASS, AND THE PRACTICALS ARE WARM POOLS
ON DARK WET GROUND.

=============================================================================
REVISION 10 - THE VALUE RELATIONSHIP, WHICH WAS INVERTED FOR FIVE ROUNDS
=============================================================================

THE FINDING, as the round-10 critic measured it: "sunlit facade mean luma 0.581,
sky mean luma 0.194 - the building is three times brighter than the sky behind
it. In every reference the sky is the brightest thing in frame and the
architecture is a dark mass carrying a rim. Ours reads as a scale model under a
work light." Revision 9 shipped that and did not know, because analyze_shot.py
has no operator that can see it: mean_luma, warm_cool_split, cool_pixel_frac and
dead_area_frac are all whole-frame statistics and every one of them passed.

So the first thing revision 10 built was the missing instrument,
tools/_light10_value.py - fixed pixel windows on open sky and on lit
architecture, per shot, verified by cropping them out and looking at them. Every
number below comes from it at `--final --warmup 120 --dt 0`.

-----------------------------------------------------------------------------
THE MEASUREMENT THAT MADE IT SOLVABLE - `gen_lighting9.py --only StormSky`
-----------------------------------------------------------------------------
    linear-light mean of each window, dome alone vs the full revision-9 rig

    shot              window   dome only   full rig   dome's share
    HERO_ESTABLISH    FACADE     0.0116     0.3515        3.3 %
    LANE_EYE_YARD     FACADE     0.0089     0.4381        2.0 %
    SILHOUETTE_WEST   FACADE     0.0160     0.2183        7.3 %
    HERO_ESTABLISH    SKY        0.0577     0.0589       98.0 %

THE SKY IS THE DOME AND NOTHING ELSE. THE LIT ARCHITECTURE IS THE WSW WARM GROUP
AND ALMOST NOTHING ELSE. That is why five rounds of surface work could not touch
it: the two quantities are driven by different prims and were never balanced
against each other. Once measured, the gate is one inequality in one unknown,
and LANE_EYE_YARD is the binding shot because its facade window is 8 m of
warehouse wall at 13 m.

WHAT CHANGED, all of it in tools/gen_lighting9.py:

 1. WARM_KEY_TRIM = 0.30 scales KeySun, its visible SunDisc and the
    StormBreak_West card together - they are one light in three prims. That is a
    3.3x cut from revision 9. StormBreak_West mattered more than the sun did:
    45 500 m2 of card at 450 m subtends 0.225 sr, so at revision 9's radiance it
    was delivering of the order of 8e4 lux from the WSW, several times KeySun's
    own beam, and it is what made the facade a hard warm wash.

    THAT CUT IS THE PHYSICS, NOT A DODGE. This is a storm BREAK at dusk: a 5-7
    degree sun seen through the full thickness of a storm's edge, with the cloud
    ceiling carrying the light. A sun that puts 30 000 lux on a wall at that hour
    is a clear golden-hour sun, and a clear golden-hour sun is precisely why the
    frames read as a scale model under a work light.

 2. THE DOME IS PHOTOGRAPHED 8.8x BRIGHTER AND ONLY 7.7x MORE ILLUMINATING.
    `intensity` 58 -> 512 is what a primary ray sees; `diffuse` 50 -> 39 holds
    the illumination back so the level does not simply get brighter everywhere.
    `specular` 1.00 -> 0.15 keeps intensity * specular within 20 percent of
    revision 9, because otherwise every wet surface would mirror a 9x sky and
    DETAIL_WET_APRON's puddle - whose subject is a SODIUM reflection - would have
    gone further blue rather than less.

 3. FOUR WALL-LENGTH WASHES BECAME ELEVEN POOLS, and EXT_WARM_TRIM went 0.24 ->
    1.00. Revision 9 consolidated eleven point sources into 22-38 m cards on the
    stated grounds that fewer lights meant less variance; the brief's own
    correction has since falsified that premise, and what the consolidation cost
    was the Hackney Yard image - a 38 m card lays one even sheet over the whole
    apron, and an even sheet is by definition not a pool. The eleven are DiskLights
    with cone shaping (which does NOT work on a RectLight on this build) sitting
    on the fixtures 20_architecture already built, and the dead units are that
    file's dead units: WallPack3_lens (X +2) and Sodium1/4_lens (X -30, +12) have
    no emissive binding, so they get no light either.

 4. THE FIXTURE LENSES ARE REBOUND FROM 9 000 NITS TO 2 800. sRGB 1.0 lands near
    1 200 nits here, so a 9 000 nit lens clips to flat white in all three
    channels - a white dot, not a sodium lamp. 60_lighting sublayers above
    50_materials so the rebinding at the foot of this file wins without editing
    that module. The cold swap-in LAYOUT 8.2 asks for is wall pack X -10, chosen
    because 80_fx already authors its one FX_GlowMercury cone at exactly that
    station and the two were contradicting each other.

=============================================================================
REVISION 9 - 82 LIGHTS DOWN TO {NLIGHTS}, AND THE NOISE HYPOTHESIS FALSIFIED
=============================================================================

READ THE ABLATION LADDER BELOW BEFORE SPENDING MORE TIME ON speckle_energy.
The brief this revision was written against stated, as established fact, that
"LIGHT COUNT IS THE LEVER: 2 lights -> speckle 0.006; 82 lights -> speckle
0.020". That is true of the trivial calibration scene. IT IS NOT TRUE OF THIS
LEVEL. Cutting 82 lights to 27 did not bring speckle_energy or chroma_speckle
to their gates on any shot, and on HERO_ESTABLISH it changed them by nothing.

-----------------------------------------------------------------------------
THE ABLATION LADDER - every row is `render.py --final --warmup 120`, measured
-----------------------------------------------------------------------------
    HERO_ESTABLISH                       speckle  chroma  firefly  mean_luma
      82 lights (revision 8, shipped)     0.017   0.011    0.025     0.229
      27 lights (revision 9)              0.017   0.011    0.028     0.302
       2 lights (dome + key sun only)     0.018   0.012    0.034     0.175
       2 lights AND no emissive geometry  0.018   0.012    0.035     0.190

    LANE_EYE_YARD
      82 lights                           0.027   0.015    0.068     0.161
      27 lights                           0.028   0.016    0.075     0.235
       1 light  (a single WHITE dome)     0.018   0.007      -       0.123

    DETAIL_WET_APRON
      82 lights                           0.025   0.015    0.062     0.135
      27 lights                           0.029   0.018    0.038     0.203
       1 light  (a single WHITE dome)     0.006   0.004      -       0.022

    INTERIOR_AISLE
      82 lights                           0.046   0.022    0.137     0.184
      27 lights                           0.044   0.020    0.122     0.177
       2 lights AND no emissive geometry  0.011   0.009    0.012     0.027

THREE THINGS FOLLOW, AND THEY ARE THE MOST USEFUL RESULT IN THIS REVISION.

 1. ON HERO_ESTABLISH THE LIGHT RIG CONTRIBUTES NOTHING MEASURABLE. Two analytic
    lights, no practicals, no emissive geometry, at mean_luma 0.190 - which is
    INSIDE the exposure gate - still measures speckle_energy 0.018 and
    chroma_speckle 0.012, i.e. 2x each gate. There is no rig this module can
    author that gets that frame under 0.009. The residue is scene-side:
    sub-pixel aliasing over an enormous amount of high-frequency prop,
    vegetation and decal geometry, plus the level's emissive card stack.

 2. speckle_energy IS AN ABSOLUTE MEASURE AND THEREFORE PARTLY AN EXPOSURE
    MEASURE. It is mean |pixel - 3x3 median| in sRGB, so the same relative noise
    reads higher on a brighter frame. Normalised by mean_luma, revision 9 is
    cleaner than revision 8 on every shot:
        HERO 0.074 -> 0.070   INTERIOR 0.250 -> 0.249   LANE 0.168 -> 0.119
        DETAIL 0.185 -> 0.143  SILHOUETTE 0.172 -> 0.160
    and revision 8 bought part of its lower absolute number by being too dark -
    mean_luma failed low on three of five frames. Some of that darkness was the
    renderer's own `fireflyFilter:maxUnexposedIntensityPerSample = 3200` clamp
    discarding energy from emitters running at 4-5e6 nits; capping peak radiance
    is why the same authored flux now reaches the film.

 3. INTERIOR_AISLE IS A SEPARATE, DIAGNOSED, CROSS-MODULE PROBLEM. Its 0.044 /
    0.020 / 0.122 is roughly double every other frame and it barely moved
    between 82 lights and 27. `80_fx.usda` authors /World/FX/DustMotes/Motes,
    whose own doc string reads "Sub-pixel emissive quads in the beams. They read
    as sparkle, not geometry", with extent X -37.29..31.90, Y 40.00..56.18,
    Z 0.07..12.47. INTERIOR_AISLE stands at (-35.5, 49.40, 2.40) and looks due
    east: that mesh occupies EXACTLY the volume this camera looks through, and
    the frame's noise is a uniform field of white sub-pixel dots including over
    surfaces no light in this module reaches. It also drives that frame's
    detail_density to 0.269 against a 0.200 ceiling - high-frequency noise reads
    as "texture" to that operator. 80_fx sublayers ABOVE 60_lighting so I cannot
    override or ablate it to prove this; it is filed as a request with the
    coordinates. REQUEST TO 80_fx: give Motes a real width, cut its density by
    an order of magnitude, or restrict it to the shafts it is named for.

WHAT REVISION 9 DID DO ABOUT VARIANCE, since the count was not the lever:

  * 82 prims -> 27, because a smaller rig is still the right rig and it made the
    level cleaner PER UNIT OF EXPOSURE (see 2 above). Consolidations, all
    flux-preserving unless noted - with `normalize = 1` an area light's power is
    fixed and only its peak radiance moves when you change its size:
         5 SphereLight south wall packs      ->  2 RectLight wall washes
         6 SphereLight dock canopy fascia    ->  2 RectLight fascia washes
         2 SphereLight dock-face bay lamps   ->  1 RectLight (flux cut 3x)
         3 SphereLight conveyor bridge       ->  1 RectLight underside run
        27 DiskLight   interior high bays    ->  6 DiskLight at radius 2.40
         6 RectLight + 6 SphereLight roof breaks -> 0; the beams are geometry
         3 RectLight   clerestory + monitor  ->  1 RectLight roof monitor
         3 RectLight   gate washes           ->  1 RectLight south gate wash
         2 RectLight   storm break + fringe  ->  1 RectLight break
         2 DistantLight cool fills           ->  1 DistantLight ENE horizon fill
         9 SphereLight minor floods          ->  3
    Deleted outright: Gable_Yard_West/East (folded into the wall washes),
    TankerGantry, EastPlatform, DockOffice_Broken, DC_p26, Bridge_East_N/S,
    Gantry_East, StormFillCool_S, StormBreak_Fringe, DockFace_BayLamp_m22.

  * PEAK RADIANCE IS CAPPED AT 8.0e5 NITS and the generator REFUSES TO WRITE if
    any emitter exceeds it, so the cap cannot be lost to a later edit. Revision
    8's worst were DockFace_BayLamp_m06 at 4.5e6 nits and Gable_Yard_West at
    5.3e6 - small, chromatic sodium spheres, which is what the critic
    photographed as "warm orange specks in the SKY of LANE_EYE_YARD". The
    brightest emitter in the level is now under 6e5 nits and the brightest is
    within 8x of the median area emitter.

  * The two emissive mesh families come down with everything else, because
    `ris:meshLights` is on in both render tiers and they are genuine emitters:
    SM_Lamp_A1 (45 fittings merged into one 96.58 m2 mesh) 12484 -> 2400 nits,
    the roof-shaft beam quads 12484/4994 -> 2200/1000 with their opacity cut
    from 0.44/0.27 to 0.34/0.20. Measured: removing both from the 2-light
    ablation on INTERIOR_AISLE took speckle 0.014 -> 0.011.

-----------------------------------------------------------------------------
THE COLOUR GRADE - what changed and why, with the mechanism stated once
-----------------------------------------------------------------------------
    warm_cool_split = |(R-B)_bright - (R-B)_dark| about the frame median.

It is an ORDERING requirement, not a colour one. Warm must land on what the
frame calls BRIGHT and cool on what it calls DARK, and any source that lands on
both halves in equal measure subtracts out of the difference no matter what
colour it is. Revision 4 answered a failing split by adding StormFillCool_Z, a
near-vertical saturated blue DistantLight putting 5 060 lux on every horizontal
surface with no falloff and no occlusion structure, and the metric did not move,
because a uniform top-light cannot move it. Revision 8 correctly deleted that
light and then left the level with almost no cool ambient at all.

REVISION 9'S ARRANGEMENT IS THE PHYSICAL ONE FOR THIS HOUR.

  * THE COOL HALF IS THE SKY AND IT IS DELIVERED BY THE DOME. That distinction
    is the whole fix. A DomeLight is occluded by the geometry a ray passes, so
    it fills OPEN shadow - yard, apron, aisle floor - and leaves crevices and
    contact shadows dark. That correlation with luminance is exactly what
    warm_cool_split measures and exactly what a DistantLight cannot have.
    `inputs:diffuse` 9.8 -> 50.0 with `inputs:intensity` 85.26 -> 58: measured
    on this build, `diffuse` scales the illumination a dome contributes WITHOUT
    changing what a primary ray sees of the sky, so the storm ceiling sits
    DARKER on film than before - its blue then counts toward the dark half -
    while the ambient it delivers is about 3.5x. `inputs:color`
    (0.58, 0.81, 1.22) is a bias over a probe that already carries the
    structure: decoded with tools/_light_probe.py, approaching_storm_4k is break
    core R:B 1.19 at +18.50 deg, opposite sky 0.28, zenith 0.62, horizon band
    0.79, cos-weighted ambient (0.94, 1.02, 1.31) = R:B 0.72.

    HARD LIMIT FOUND BY MEASUREMENT, do not cross it: `inputs:diffuse` ABOVE
    ABOUT 50 BLOWS DETAIL_WET_APRON OUT TO A FLAT WHITE FOG. Holding
    intensity * diffuse constant (58/50, 44/66 and 34/86 are all about 2 900)
    that frame measured mean_luma 0.203 / 0.611 / 0.637, dead_area_frac
    0.034 / 0.229 / 0.299 and mean_saturation 0.299 / 0.118 / 0.103. The
    illumination is unchanged, so this is the dome driving 80_fx's participating
    medium non-linearly, not a surface-lighting effect. 58 / 50 is shipped.

  * THE WARM HALF IS THE SUN, AND ONLY THE SUN, AT THE GLOBAL SCALE.
    KeySun (1.00, 0.72, 0.44) at 30 000 lux, bearing 200, elevation 7.30 deg.
    That is a 4.6x CUT from revision 8's 136 735 and it is deliberate: at
    7.3 deg a horizontal surface receives sin(7.3) = 12.7 percent of the beam
    while a west-facing wall receives 99 percent of it, so a sun this size
    lights the walls hard and the ground barely at all. That is the real dusk
    relationship and it is what lets the GROUND be sky-blue while the WALLS are
    amber - which is the COD dusk image the brief is asking for.

  * THE PRACTICALS ARE WARM AND LOCAL, in pools, with dark wet ground between.
    EXT_WARM_TRIM scales the whole exterior sodium family together so the
    balance can be swept without disturbing the dressing; the swept relationship
    between it and cool_pixel_frac is recorded in the generator.

  * cool_pixel_frac WAS NOT AN ALBEDO PROBLEM, and that was worth proving before
    blaming another module. Rendered under a SINGLE WHITE DomeLight and nothing
    else (`--albedo-probe`), the level reads cool_pixel_frac 0.672 on
    DETAIL_WET_APRON and 0.565 on LANE_EYE_YARD. Every point of it this module
    was losing, it was losing to its own sodium and its own sun.

=============================================================================
SHIPPED NUMBERS - REVISION 10. `render.py --final --warmup 120 --dt 0`
=============================================================================
    One batch, on the authored state of this file, tag R10h. USE --dt 0; the
    reason is under the revision-9 table further down and it still holds.

    THE VALUE GATE - tools/_light10_value.py, sRGB luma of the two windows
    (the linear ratio is in brackets; > 1.00 means the sky wins)

    shot              SKY    FACADE   ratio     round-9 shipped
    HERO_ESTABLISH   0.754   0.548   [1.79]     0.260 / 0.589  [0.17]
    LANE_EYE_YARD    0.643   0.525   [1.29]     0.205 / 0.641  [0.08]
    DETAIL_WET_APRON 0.570   0.426   [1.25]     0.087 / 0.338  [0.07]
    SILHOUETTE_WEST  0.713   0.598   [1.39]     0.364 / 0.465  [0.57]

    INVERTED ON FOUR OF FOUR, NOW CORRECT ON FOUR OF FOUR. The sky went from a
    seventh of the facade's linear luminance on LANE_EYE_YARD to 1.29 times it.

    DETAIL_WET_APRON's puddle P4, the shot whose stated subject is the canopy
    sodium reflected in standing water:
        window mirroring DockFace_BayLamp   luma 0.658   R-B +0.046
        window mirroring the cool sky slot  luma 0.448   R-B -0.050
    i.e. the warm patch is now both brighter AND on the opposite side of neutral
    from the water beside it. Round 9 measured +0.090 / -0.044 but at sky 0.087
    against facade 0.338 - the amber was there and the frame around it was wrong.

    analyze_shot.py, all five:

    shot             mean_luma  split   cool_pix  detail  dead  spkl  chrm
                     (.16-.42)(.12-.28) (>0.25) (.075-.20)(<.16)(<.009)(<.006)
    HERO_ESTABLISH    0.205 P  0.016 F  0.494 P  0.080 P 0.115  0.015 0.010
    INTERIOR_AISLE    0.197 P  0.069 F  0.369 P  0.110 P 0.002  0.021 0.016
    LANE_EYE_YARD     0.197 P  0.054 F  0.330 P  0.106 P 0.115  0.020 0.016
    DETAIL_WET_APRON  0.251 P  0.029 F  0.550 P  0.117 P 0.069  0.022 0.017
    SILHOUETTE_WEST   0.316 P  0.074 F  0.488 P  0.126 P 0.044  0.024 0.018

    p01_luma, p99_luma, dynamic_range, rms_contrast and mean_saturation are
    inside their bands on all five as well. Against revision 9 that is
    detail_density 4/5 -> 5/5 (INTERIOR_AISLE's 0.269 was the DustMotes noise
    field and it has come down to 0.110) and cool_pixel_frac 4/5 -> 5/5.

-----------------------------------------------------------------------------
WARM_COOL_SPLIT IS STILL FAILING AND I COULD NOT FIX IT. THE SWEEP IS BELOW.
-----------------------------------------------------------------------------
    It is 0.016-0.074 against a 0.12 floor and revision 9 shipped 0.139 on
    HERO_ESTABLISH. The regression is real and it is not an accident: it is the
    direct cost of the value fix, and the mechanism is worth more than another
    round of guessing.

    warm_cool_split = |(R-B)_bright - (R-B)_dark| about the frame median. On
    THIS level the dark half has never carried it - measured on the revision-9
    frame it was +0.024, and on every revision-10 frame it is +0.008 to +0.029,
    because the dark half is dark and |R-B| is bounded by luminance. So the whole
    metric has always come from the BRIGHT half, and in revision 9 the bright
    half was 76 m of sunlit facade at R-B +0.193 - the very thing the round-10
    critic photographed as the defect. Take the sun off the wall and the number
    goes with it.

    The obvious replacement is to warm the bright half from the dome instead.
    That was swept, and it trades one gate for another:

    DOME_TINT       HERO split  HERO cool_pix  LANE split  LANE cool_pix
    (1.00,0.96,0.90)   0.078       0.346         0.018       0.241 FAIL
    (0.94,0.95,0.98)   0.069       0.368         0.014       0.221 FAIL
    (0.84,0.92,1.08)   0.069       0.368         0.008       0.226 FAIL
    (0.72,0.88,1.18)   0.017       0.488         0.043       0.331
    (0.70,0.87,1.20)   0.016       0.494         0.054       0.330  SHIPPED

    A dome warm enough to move warm_cool_split takes LANE_EYE_YARD's
    cool_pixel_frac under its floor, because that camera looks EAST with the sun
    behind it and every surface facing the lens is a lit face. Both are hard
    gates and they are anti-correlated through a single parameter. I shipped the
    one that keeps cool_pixel_frac, because a level that fails cool_pixel_frac
    is the sepia wash the brief names as the round-8 finding, and because the
    round-10 mandate was the value relationship.

    WHAT WOULD ACTUALLY FIX IT, and it is not in this module: warm_cool_split
    wants the frame's BRIGHT MIDTONES warm while its brightest element stays a
    cool sky. That means the lit architecture has to be warm-albedo and darker,
    and right now it is pale near-white cladding - under a single WHITE dome
    (`--albedo-probe`) this level already reads cool. Measured on the shipped
    frame, LANE_EYE_YARD's `bldg` window - the north backdrop block - sits at
    linear 0.485 against a sky at 0.380, i.e. THAT building is brighter than the
    sky under ambient alone, which no light rig can undo. REQUEST TO
    50_materials: the warehouse cladding, the dock-office blockwork and the north
    annex need a materially lower and warmer albedo. That single change would
    give this rig back the warm bright half it is missing.

-----------------------------------------------------------------------------
REVISION 9's SHIPPED NUMBERS, kept for comparison
-----------------------------------------------------------------------------
    shot              mean_luma   split    cool_pix  detail  speckle chroma
                      (.16-.42) (.12-.28)  (>0.25) (.075-.20)(<.009)(<.006)
    HERO_ESTABLISH     0.240 P   0.139 P   0.279 P   0.099 P  0.017  0.011
    INTERIOR_AISLE     0.172 P   0.083 F   0.291 P   0.269 F  0.044  0.020
    LANE_EYE_YARD      0.216 P   0.141 P   0.199 F   0.165 P  0.029  0.017
    DETAIL_WET_APRON   0.206 P   0.041 F   0.256 P   0.165 P  0.029  0.018
    SILHOUETTE_WEST    0.184 P   0.006 F   0.445 P   0.163 P  0.029  0.016

    JUDGE THIS LEVEL WITH `--dt 0`. The default marches scene time one delta per
    warmup step, so with animated FX in the layer each --final frame lands on a
    different scene and the numbers are not reproducible. Measured on the
    identical authored state: SILHOUETTE_WEST came back at mean_luma 0.179 on one
    run and 0.424 on the next, with dead_area_frac 0.025 vs 0.077 - a fog frame
    and a clear one. With `--dt 0` two consecutive runs of that shot measured
    0.200 / 0.199 mean_luma, 0.433 / 0.437 cool_pixel_frac and 0.018 / 0.018
    speckle_energy, and LANE_EYE_YARD 0.206 / 0.206 and 0.029 / 0.029. Freezing
    scene time also LOWERED the noise on the shots that carry drifting mist -
    SILHOUETTE_WEST 0.028 -> 0.018 speckle and 0.016 -> 0.010 chroma when
    rendered on its own. Batch position still moves it (the same shot in a
    five-shot batch measured 0.029), which is a harness property, not a lighting
    one, and is recorded here rather than tuned around.

    AGAINST THE REVISION-8 STATE, measured the same way in the same session:
        mean_luma        2/5 pass -> 5/5 pass
        cool_pixel_frac  2/5 pass -> 4/5 pass
        warm_cool_split  1/5 pass -> 2/5 pass
    HERO_ESTABLISH now passes every metric analyze_shot.py checks except the two
    noise gates, and with margin rather than on the line.

-----------------------------------------------------------------------------
HONEST GAPS - what is still wrong after revision 9
-----------------------------------------------------------------------------
 * speckle_energy AND chroma_speckle FAIL ON ALL FIVE AND I COULD NOT FIX THEM
   FROM THIS MODULE. The ablation ladder above is the evidence: with two
   analytic lights and no emissive geometry, HERO_ESTABLISH still measures
   0.018 / 0.012 at an in-gate exposure, against gates of 0.009 / 0.006. What I
   did do - 82 prims to 27, an 8x cut in peak radiance, a 5x cut in mesh-light
   emission - improved noise per unit exposure on every shot and improved the
   absolute number on none of them by enough to matter. I do not believe this
   gate is reachable by lighting. Next places to look, in order: 80_fx's
   DustMotes (worth roughly a factor of two on INTERIOR_AISLE), the level's
   semi-transparent emissive card stack generally, and pixel filtering or
   supersampling in render.py, which 90_cameras owns. I did not touch the save
   path and I did not touch the analyzer.

 * SILHOUETTE_WEST's warm_cool_split IS 0.006 AND THE CAUSE IS THE CAMERA.
   90_cameras authors it at translate (56.0, -8.0, 1.65) / rotateXYZ (90.00, 0,
   90.00). LAYOUT 7.5 specifies (48.0, -8.0, 1.65) / (96.0, 0, 90.0) - 8 m
   further west and 6 degrees UP. Pitch 90.00 is DEAD LEVEL, so about 40 percent
   of the frame is open sky and ALL of it sits in the BRIGHT half of the
   histogram; the metric is then capped at whatever the sky's own hue is, no
   matter what the lighting does. I measured that frame at 0.001-0.037 across
   NINE different rigs this round, including a 2-light ablation (0.016) and a
   single-white-dome ablation (0.022). It does not respond to lighting at all.
   LAYOUT's 6 degrees up is what puts the conveyor bridge across frame centre as
   a black lintel and the sun disc UNDER it, which breaks the sky into pieces
   and gives the bright half something warm to be. CROSS-MODULE REQUEST to
   90_cameras: restore translate (48, -8, 1.65) and pitch 96.0.

 * DETAIL_WET_APRON's warm_cool_split IS 0.038. That frame is 45 mm of
   horizontal wet ground under an open sky slot; its bright half is standing
   water reflecting the overcast, which is cool BY PHYSICS, and its warm half is
   two sodium fixtures 10-14 m away. Every configuration that raised its split
   dropped its cool_pixel_frac below the floor and vice versa - the two gates
   pull in opposite directions on this specific frame - and I chose
   cool_pixel_frac, because a sepia close-up was the round-8 finding. The
   measured trade, so nobody re-derives it: KeySun at 150k / 100k / 58k / 40k lux
   gave split 0.090 / 0.110 / 0.020 / 0.010 against cool_pixel_frac
   0.034 / 0.035 / 0.053 / 0.053.

 * INTERIOR_AISLE's split is 0.091. The frame is authored cold-at-the-back - a
   cool card in the east roller doors, the mercury swap-in at the far bay -
   against warm sodium at the front, which is the right image; but its
   detail_density of 0.269 says a large part of what that operator measures is
   the DustMotes noise field rather than surface texture, and the same noise
   flattens the hue difference between the two halves.

 * LANE_EYE_YARD's cool_pixel_frac is 0.198 against 0.250. That camera looks due
   EAST with the sun behind it, so every surface facing the lens is a sun-lit
   face. Measured: it does not respond to the practicals (cutting the entire
   exterior sodium family 3.5x moved it 0.165 -> 0.193) and it barely responds
   to the sun (46 000 -> 22 000 lux moved it 0.193 -> 0.178). Under a single
   white dome the same frame reads 0.565, so the headroom exists; reaching it
   needs either a materially cooler dome than (0.58, 0.81, 1.22) - which starts
   making wet asphalt read as ice, the round-7 finding - or less saturated warm
   albedo in the yard dressing, which is 30_props and 50_materials.

 * THE SUN DISC IS IN THE FRAME AND IT IS WHITE. A DistantLight's primary-ray
   disc renders at about intensity * color nits, and there is no value that is
   both bright enough to be the sun and dim enough for blue to stay under the
   white point. Splitting the prim - KeySun invisible, SunDisc visible - puts a
   disc where LAYOUT 7.5 asks for it and keeps the shading correct, but a warm
   corona has to come from atmosphere, which 80_fx owns.

 * RUN-TO-RUN VARIANCE ON THIS HARNESS IS LARGER THAN IT LOOKS. Two --final
   renders of the identical authored state measured LANE_EYE_YARD at mean_luma
   0.205 vs 0.220 and firefly_frac 0.076 vs 0.038. Do not read a 5 percent
   change on one frame as a result.

 * `inputs:shaping:cone:*` DOES NOT WORK ON A RectLight ON THIS BUILD. Adding
   ShapingAPI and a cone to the wall washes and the canopy fascia - an attempt
   to turn washes into pools without adding prims - blew DETAIL_WET_APRON to
   mean_luma 0.637 with dead_area_frac 0.299. It is reverted. Cone shaping works
   correctly on DiskLight and SphereLight, which is where the six high bays and
   the two metal-halide masts use it.

-----------------------------------------------------------------------------
UNITS ON THIS RENDERER, measured rather than assumed
-----------------------------------------------------------------------------
    DistantLight  irradiance = intensity (lux). `normalize` is a no-op on it;
                  `angle` only softens the shadow edge and sizes the disc.
    DomeLight     radiance = intensity * color * texel. `inputs:diffuse` scales
                  the illumination only, not the photographed sky - but see the
                  hard limit of about 50 above.
    area light    radiance = intensity * color / area   (normalize = 1), so FLUX
                  IS PROPORTIONAL TO intensity ALONE and growing an emitter
                  lowers its peak radiance without changing what it delivers.
    sRGB 1.0      lands near 1 200 nits in the linear part of the curve.
    `visibleInPrimaryRay` is the BARE name. An `inputs:`-prefixed spelling
    parses, validates, and then silently does nothing. It is authored 0 on every
    light here except SunDisc; the DomeLight is deliberately left visible
    because it is the sky."""
    metersPerUnit = 1
    upAxis = "Z"
)
'''


def build() -> str:
    U, P, V = sun_basis(SUN_PITCH, SUN_HEADING)
    o: list[str] = []
    o.append(HEADER.replace("{NLIGHTS}", str(len(ALL))).rstrip("\n"))
    o.append("")
    o.append('over "World"')
    o.append("{")
    o.append('    def Xform "Lighting"')
    o.append("    {")

    # ---- lamp material ----
    o.append("""
        # =====================================================================
        # FITTING EMISSION - the interior high-bay fittings themselves
        # =====================================================================
        # LAYOUT 12.6: "SM_Lamp_A1 will render black unless the lighting agent
        # binds an emissive material". Warehouse01 merges all 45 fittings into
        # ONE mesh at /World/Architecture/Warehouse/Warehouse01/SM_Lamp_A1,
        # world X -27.06..+27.05, Y 17.67..73.37, Z 8.08..13.12, 96.58 m2 of
        # surface. It cannot be split, so the whole fitting gets the emission.
        #
        # REVISION 9 CUTS emissive_intensity 12484.5 -> 3200. `ris:meshLights`
        # is on in both render tiers, so this is 45 disjoint emitters and it
        # belongs in the light budget. 3200 nits is 2.7x the ~1 200 nit white
        # point, which is all a fitting needs to read as lit; the previous value
        # clipped to flat white AND sprayed.
        #
        # Authored here rather than in 50_materials because it is a lighting
        # decision on a prim 20_architecture owns; 60_lighting is stronger than
        # both, so the binding at the foot of this file wins by layer order and
        # neither file is touched.
        def Scope "Looks"
        {
            def Material "M_LampSodium"
            {
                token outputs:mdl:surface.connect = </World/Lighting/Looks/M_LampSodium/Shader.outputs:out>
                token outputs:surface.connect = </World/Lighting/Looks/M_LampSodium/Preview.outputs:surface>

                def Shader "Shader"
                {
                    uniform token info:implementationSource = "sourceAsset"
                    uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                    uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                    color3f inputs:diffuse_color_constant = (0.2600, 0.2200, 0.1900)
                    float inputs:reflection_roughness_constant = 0.3400
                    float inputs:metallic_constant = 0.2000
                    float inputs:specular_level = 0.5000
                    bool inputs:enable_emission = 1
                    color3f inputs:emissive_color = (1.0000, 0.6400, 0.3300)
                    float inputs:emissive_intensity = LAMP_E
                    token outputs:out
                }

                def Shader "Preview"
                {
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.2600, 0.2200, 0.1900)
                    float inputs:metallic = 0.2
                    float inputs:roughness = 0.34
                    float inputs:opacity = 1
                    color3f inputs:emissiveColor = (1.0000, 0.6400, 0.3300)
                    token outputs:surface
                }
            }

            # =================================================================
            # LENS EMISSION - the exterior fixtures, so the practicals are
            # VISIBLE and not merely present.
            # =================================================================
            # The round-10 critic's second finding was "five frames show no
            # visible practical at all". Part of that was flux (EXT_WARM_TRIM
            # 0.24) and part of it is here: 50_materials binds every wall-pack
            # and canopy lens to FX_LensSodium at emissive_intensity 9000, and
            # sRGB 1.0 lands near 1 200 nits on this build, so a 9 000 nit lens
            # clips to FLAT WHITE in all three channels. A white dot is not a
            # sodium lamp. 2 800 nits is 2.3x the white point - bright enough to
            # bloom, low enough that the amber survives the tonemap.
            #
            # Rebound rather than edited: 60_lighting sublayers above
            # 50_materials, so the overrides at the foot of this file win and
            # neither that file nor 20_architecture is touched. Only the lenses
            # that 20_architecture already bound emissive are rebound - the dead
            # units at wall-pack X +2 and fascia X -30 / +12 stay dead.
            def Material "M_LensSodium"
            {
                token outputs:mdl:surface.connect = </World/Lighting/Looks/M_LensSodium/Shader.outputs:out>
                token outputs:surface.connect = </World/Lighting/Looks/M_LensSodium/Preview.outputs:surface>

                def Shader "Shader"
                {
                    uniform token info:implementationSource = "sourceAsset"
                    uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                    uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                    color3f inputs:diffuse_color_constant = (0.3500, 0.2200, 0.0900)
                    float inputs:reflection_roughness_constant = 0.2200
                    float inputs:metallic_constant = 0.0000
                    float inputs:specular_level = 0.8000
                    bool inputs:enable_emission = 1
                    color3f inputs:emissive_color = (1.0000, 0.5850, 0.2000)
                    float inputs:emissive_intensity = 2800.00
                    token outputs:out
                }

                def Shader "Preview"
                {
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.3500, 0.2200, 0.0900)
                    float inputs:metallic = 0
                    float inputs:roughness = 0.22
                    float inputs:opacity = 1
                    color3f inputs:emissiveColor = (1.0000, 0.5850, 0.2000)
                    token outputs:surface
                }
            }

            # LAYOUT 8.2: "one should be a different, colder colour temperature".
            # That is the canopy fascia at X +26 - Sodium5 - and its DiskLight
            # carries the matching MERCURY colour, so the housing and the pool
            # under it agree instead of contradicting each other.
            def Material "M_LensMercury"
            {
                token outputs:mdl:surface.connect = </World/Lighting/Looks/M_LensMercury/Shader.outputs:out>
                token outputs:surface.connect = </World/Lighting/Looks/M_LensMercury/Preview.outputs:surface>

                def Shader "Shader"
                {
                    uniform token info:implementationSource = "sourceAsset"
                    uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                    uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                    color3f inputs:diffuse_color_constant = (0.1800, 0.2200, 0.2600)
                    float inputs:reflection_roughness_constant = 0.2200
                    float inputs:metallic_constant = 0.0000
                    float inputs:specular_level = 0.8000
                    bool inputs:enable_emission = 1
                    color3f inputs:emissive_color = (0.7400, 0.8600, 1.0000)
                    float inputs:emissive_intensity = 2600.00
                    token outputs:out
                }

                def Shader "Preview"
                {
                    uniform token info:id = "UsdPreviewSurface"
                    color3f inputs:diffuseColor = (0.1800, 0.2200, 0.2600)
                    float inputs:metallic = 0
                    float inputs:roughness = 0.22
                    float inputs:opacity = 1
                    color3f inputs:emissiveColor = (0.7400, 0.8600, 1.0000)
                    token outputs:surface
                }
            }
        }
""".replace("LAMP_E", f"{LAMP_EMISSIVE:.2f}").rstrip("\n"))

    # ---- scopes ----
    scopes = [
        ("Sky", "SKY - the storm ceiling. This is the level's ambient AND its cool half.",
         [L for L in ALL if L["scope"] == "Sky"]),
        ("Sun", "SUN, COOL FILL AND THE OPEN-SKY CARDS.",
         [L for L in ALL if L["scope"] == "Sun"]),
        ("Practicals", "PRACTICALS - warm sodium pools on dark wet ground.",
         [L for L in ALL if L["scope"] == "Practicals"]),
        ("InteriorDaylight", "INTERIOR DAYLIGHT - the warehouse needs its own solution.",
         [L for L in ALL if L["scope"] == "InteriorDaylight"]),
    ]
    for sname, title, lights in scopes:
        o.append("")
        o.append("        # =====================================================================")
        o.append(f"        # {title}")
        o.append("        # =====================================================================")
        o.append(f'        def Scope "{sname}"')
        o.append("        {")
        for L in lights:
            o.append("")
            o.append(emit_light(L, "            "))
        o.append("        }")

    # ---- roof shaft geometry ----
    o.append("""
        # =====================================================================
        # ROOF-BREAK SHAFTS - geometry, not lights
        # =====================================================================
        # The six breaks are real: they are the RoofDressing HoleN_void meshes in
        # 20_architecture.usda. Revision 4 gave each of them TWO lights (a cold
        # Sky_HN card and a collimated SunBar_HN sphere), which is twelve prims
        # and, at 12.65e6 on an r 1.10 sphere, twelve of the level's hotter
        # emitters. REVISION 9 DELETES ALL TWELVE. What the eye actually reads
        # as a shaft is the beam itself, and the beam is these crossed emissive
        # quads - so the geometry stays and the lights go.
        #
        # HONEST GEOMETRY NOTE, because it drives the shapes: the sun is at
        # 7.30 deg. A beam entering a hole 10.6-12.4 m up descends 0.128 m per
        # metre travelled, so it needs ~90 m to reach the slab and the building
        # is 76 m long - NO roof shaft in this map lands on the floor. These rake
        # east-north-east over the tops of the rack runs and out through the open
        # east roller doors at 2-7 m above the slab, which is a diagonal bar
        # across the upper half of INTERIOR_AISLE and is true for this hour
        # rather than a noon shaft faked at dusk.
        #
        # Each beam is two crossed quads along the sun vector, widening 1.5x over
        # its length and fading from ShaftCore to ShaftSoft at 55 percent because
        # a real shaft loses its edge as it picks up dust. doNotCastShadows on
        # every card: they are air and must not darken the slab under them.
        # Emissive intensity is cut about 4x with everything else in this
        # revision - these are mesh lights too.
        def Scope "Volumetrics"
        {
            def Scope "Looks"
            {
                def Material "L_ShaftCore"
                {
                    token outputs:mdl:surface.connect = </World/Lighting/Volumetrics/Looks/L_ShaftCore/Shader.outputs:out>
                    token outputs:surface.connect = </World/Lighting/Volumetrics/Looks/L_ShaftCore/Preview.outputs:surface>

                    def Shader "Shader"
                    {
                        uniform token info:implementationSource = "sourceAsset"
                        uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                        uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                        color3f inputs:diffuse_color_constant = (0.0000, 0.0000, 0.0000)
                        float inputs:reflection_roughness_constant = 1.000
                        float inputs:metallic_constant = 0.000
                        float inputs:specular_level = 0.000
                        bool inputs:enable_emission = 1
                        color3f inputs:emissive_color = (1.0000, 0.7200, 0.4200)
                        float inputs:emissive_intensity = SHAFT_C
                        bool inputs:enable_opacity = 1
                        float inputs:opacity_constant = 0.3400
                        float inputs:opacity_threshold = 0.0
                        token outputs:out
                    }

                    def Shader "Preview"
                    {
                        uniform token info:id = "UsdPreviewSurface"
                        color3f inputs:diffuseColor = (0.0000, 0.0000, 0.0000)
                        float inputs:roughness = 1.000
                        float inputs:metallic = 0
                        float inputs:opacity = 0.3400
                        color3f inputs:emissiveColor = (1.0000, 0.7200, 0.4200)
                        token outputs:surface
                    }
                }

                def Material "L_ShaftSoft"
                {
                    token outputs:mdl:surface.connect = </World/Lighting/Volumetrics/Looks/L_ShaftSoft/Shader.outputs:out>
                    token outputs:surface.connect = </World/Lighting/Volumetrics/Looks/L_ShaftSoft/Preview.outputs:surface>

                    def Shader "Shader"
                    {
                        uniform token info:implementationSource = "sourceAsset"
                        uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                        uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                        color3f inputs:diffuse_color_constant = (0.0000, 0.0000, 0.0000)
                        float inputs:reflection_roughness_constant = 1.000
                        float inputs:metallic_constant = 0.000
                        float inputs:specular_level = 0.000
                        bool inputs:enable_emission = 1
                        color3f inputs:emissive_color = (1.0000, 0.7800, 0.5400)
                        float inputs:emissive_intensity = SHAFT_S
                        bool inputs:enable_opacity = 1
                        float inputs:opacity_constant = 0.2000
                        float inputs:opacity_threshold = 0.0
                        token outputs:out
                    }

                    def Shader "Preview"
                    {
                        uniform token info:id = "UsdPreviewSurface"
                        color3f inputs:diffuseColor = (0.0000, 0.0000, 0.0000)
                        float inputs:roughness = 1.000
                        float inputs:metallic = 0
                        float inputs:opacity = 0.2000
                        color3f inputs:emissiveColor = (1.0000, 0.7800, 0.5400)
                        token outputs:surface
                    }
                }
            }

            def Xform "RoofShafts"
            {"""
              .replace("SHAFT_C", f"{SHAFT_CORE_EMISSIVE:.2f}")
              .replace("SHAFT_S", f"{SHAFT_SOFT_EMISSIVE:.2f}").rstrip("\n"))

    for hole in HOLES:
        for seg in (0, 1):
            for axis in ("A", "B"):
                pts = beam_points(hole, seg, axis, U, P, V)
                mat = "L_ShaftCore" if seg == 0 else "L_ShaftSoft"
                lo = [min(p[k] for p in pts) for k in range(3)]
                hi = [max(p[k] for p in pts) for k in range(3)]
                o.append("")
                o.append(f'                def Mesh "Beam_{hole}_{seg}{axis}" (')
                o.append('                    prepend apiSchemas = ["MaterialBindingAPI"]')
                o.append("                )")
                o.append("                {")
                o.append("                    uniform bool doubleSided = 1")
                o.append("                    bool primvars:doNotCastShadows = 1")
                o.append(f"                    float3[] extent = [{fmt3(lo)}, {fmt3(hi)}]")
                o.append("                    int[] faceVertexCounts = [4]")
                o.append("                    int[] faceVertexIndices = [0, 1, 2, 3]")
                o.append(f"                    rel material:binding = </World/Lighting/Volumetrics/Looks/{mat}>")
                o.append("                    point3f[] points = [" + ", ".join(fmt3(p) for p in pts) + "]")
                o.append('                    uniform token subdivisionScheme = "none"')
                o.append("                }")

    o.append("            }")
    o.append("        }")
    o.append("    }")
    o.append("")
    o.append("    # Fixture-emission bindings. 60_lighting sublayers ABOVE both")
    o.append("    # 20_architecture and 50_materials, so these overrides win without")
    o.append("    # either file being edited. Only lenses 20_architecture already bound")
    o.append("    # emissive are rebound - the dead units stay dead.")
    o.append('    over "Architecture"')
    o.append("    {")
    o.append('        over "Warehouse"')
    o.append("        {")
    o.append('            over "Warehouse01"')
    o.append("            {")
    o.append('                over "SM_Lamp_A1" (')
    o.append('                    prepend apiSchemas = ["MaterialBindingAPI"]')
    o.append("                )")
    o.append("                {")
    o.append("                    rel material:binding = </World/Lighting/Looks/M_LampSodium>")
    o.append("                }")
    o.append("            }")
    o.append("")
    o.append('            over "Facade"')
    o.append("            {")
    for n, look in LIT_WALLPACK_LENSES:
        o.append(f'                over "{n}" (')
        o.append('                    prepend apiSchemas = ["MaterialBindingAPI"]')
        o.append("                )")
        o.append("                {")
        o.append(f"                    rel material:binding = </World/Lighting/Looks/{look}>")
        o.append("                }")
        o.append("")
    o.pop()
    o.append("            }")
    o.append("        }")
    o.append("")
    o.append('        over "DockCanopy"')
    o.append("        {")
    for n, look in LIT_FASCIA_LENSES:
        o.append(f'            over "{n}" (')
        o.append('                prepend apiSchemas = ["MaterialBindingAPI"]')
        o.append("            )")
        o.append("            {")
        o.append(f"                rel material:binding = </World/Lighting/Looks/{look}>")
        o.append("            }")
        o.append("")
    o.pop()
    o.append("        }")
    o.append("    }")
    o.append("}")
    o.append("")
    return "\n".join(o)


def report() -> int:
    rows = []
    for L in ALL:
        n = peak_nits(L)
        if n is not None:
            rows.append((n, L["name"], L["kind"], L["I"] * GAIN))
    rows.sort(reverse=True)
    print(f"{len(ALL)} light prims. Peak radiance, brightest first (cap {PEAK_CAP:.1e} nits):")
    over = 0
    for n, name, kind, I in rows:
        flag = "  OVER CAP" if n > PEAK_CAP else ""
        if n > PEAK_CAP:
            over += 1
        print(f"  {n:12,.0f} nits   {kind:7} {name:24} I={I:,.0f}{flag}")
    if rows:
        med = rows[len(rows) // 2][0]
        ratio = rows[0][0] / med
        print(f"  median area-emitter radiance {med:,.0f} nits; "
              f"brightest is {ratio:.1f}x the median")
        if ratio > PEAK_MEDIAN_RATIO:
            print(f"  RATIO OVER {PEAK_MEDIAN_RATIO}x")
            over += 1
    return over


def main() -> None:
    global GAIN, ALL
    ap = argparse.ArgumentParser()
    ap.add_argument("--gain", type=float, default=GAIN)
    ap.add_argument("--report", action="store_true")
    # DIAGNOSTIC ONLY - writes a 2-light rig (dome + key) so the level can be
    # rendered with this module's contribution to path-trace variance removed.
    # It is what proved that the level's speckle is NOT this module's light
    # count; see the ABLATION block in 60_lighting.usda's header. Always re-run
    # without it before judging or shipping a frame.
    ap.add_argument("--ablate", action="store_true",
                    help="DIAGNOSTIC: emit only StormSky + KeySun (2 lights)")
    ap.add_argument("--albedo-probe", action="store_true",
                    help="DIAGNOSTIC: one WHITE DomeLight only - reads the scene's own albedo")
    ap.add_argument("--no-emissive", action="store_true",
                    help="DIAGNOSTIC: drop the roof-shaft quads and the lamp emission")
    # DIAGNOSTIC. Revision 10 needed to know how much of the facade's value is the
    # sun and how much is the dome before it could invert the sky/facade
    # relationship, and guessing that split is what would have cost another round.
    #   --only StormSky            dome alone
    #   --drop KeySun,SunDisc      everything except the sun
    ap.add_argument("--only", default=None,
                    help="DIAGNOSTIC: comma-separated light names to keep, all others dropped")
    ap.add_argument("--drop", default=None,
                    help="DIAGNOSTIC: comma-separated light names to drop")
    a = ap.parse_args()
    GAIN = a.gain
    if a.only:
        keep = {s.strip() for s in a.only.split(",")}
        ALL = [L for L in ALL if L["name"] in keep]
    if a.drop:
        gone = {s.strip() for s in a.drop.split(",")}
        ALL = [L for L in ALL if L["name"] not in gone]
    if a.ablate:
        ALL = [L for L in ALL if L["name"] in ("StormSky", "KeySun")]
    if a.albedo_probe:
        # DIAGNOSTIC: the level under a single WHITE dome. Whatever hue the frame
        # then shows is the SCENE'S OWN ALBEDO times the probe's cos-weighted
        # ambient (R:B 0.72), with no contribution from any light this module
        # aims. It is how the cool_pixel_frac ceiling on DETAIL_WET_APRON and
        # LANE_EYE_YARD was attributed to surface albedo rather than to lighting.
        ALL = [dict(kind="dome", scope="Sky", name="StormSky", I=1400.0,
                    col=(1.0, 1.0, 1.0), diffuse=1.0, spec=1.0, rz=DOME_RZ,
                    visible=1)]
    if a.no_emissive:
        global HOLES, LAMP_EMISSIVE
        HOLES = {}
        LAMP_EMISSIVE = 0.0

    over = report()
    if over:
        raise SystemExit(
            f"REFUSING TO WRITE: {over} emitter(s) exceed the {PEAK_CAP:.1e} nit peak-radiance "
            "cap. Grow the emitter or cut its flux - do not raise the cap. Peak radiance is "
            "what this renderer turns into speckle and the cap is the whole point of revision 9.")
    if a.report:
        return
    USDA.write_text(build(), encoding="utf-8")
    print(f"\nwrote {USDA}  ({len(ALL)} lights, gain {GAIN})")


if __name__ == "__main__":
    main()
