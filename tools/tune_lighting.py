"""Photometric dial board for usd/modules/60_lighting.usda  (DEADFALL DEPOT).

WHAT THIS IS, AND WHY IT WAS REWRITTEN IN REVISION 6
----------------------------------------------------
`gen_lighting.py` authored revision 1 and is stale/guarded; it would delete the
ShapingAPI reflector cones, the RoofBreaks scope, the shaft cards and the extra
fills. The *structure* of 60_lighting.usda (which prims exist, where they hang,
what they are shaped like, the commentary) is therefore hand-authored and stays
hand-authored. This script owns the *numbers*: every intensity, colour, radius,
normalize flag and emissive level in the module.

REVISION 6 REPLACED THE WHOLE BASIS OF THE NUMBERS.
Revisions 1-5 tuned by relative multiplier off a snapshot (`flux=`, `warm_sat=`)
and never asked what the absolute values meant. They meant nothing physical:
27 DiskLights of radius 0.38 m were running at `inputs:intensity` 2.4e11 to
2.9e11 with `inputs:normalize = 0`, i.e. an emitted radiance of a quarter of a
TRILLION nits; SphereLights of radius 0.36 m at 1.2e7; a DistantLight KeySun at
200 000 (twice the irradiance of a real noon sun, for a light that is supposed
to be a 5.5 deg dusk sun through a storm break); and two emissive shaft
materials at 12 000 000 and 2 000 000 nits. Every one of the level's failing
gates falls out of that one fact:

  * firefly_frac  - a rare indirect path that lands on a 1e7..1e11 nit emitter
    returns a sample the firefly clamp cannot rescue and the reconstruction
    filter has to smear. 90_cameras.usda lines 639-647 diagnosed exactly this
    and had to buy the gate with a 2.2-2.6 px pixelFilter instead.
  * detail_density - a frame whose lit surfaces are pinned at the top of the
    tonemapper carries no albedo modulation at all. INTERIOR_AISLE's upper half
    was solid white; HERO's south wall was flat cream. There is no texture to
    measure in a clipped pixel, so the 2.3-3.4x miss is half exposure and half
    the pixel filter.
  * mean_saturation / warm_cool_split - KeySun at (1.00, 0.42, 0.09) x 200 000
    clips R and G and leaves B unclipped, so EVERY lit surface renders the same
    (1, 1, 0.6) tangerine regardless of its albedo, while the cold fills
    (1150 lux of (0.11, 0.33, 1.44), i.e. 1650 lux of pure blue on every
    up-facing surface) paint the yard indigo. Two clipped hues and no neutral.

So revision 6 authors the rig PHOTOMETRICALLY and calibrates it once. Every
emitter is specified as what the real fixture is - a luminous flux in lumens, a
sky luminance in nits, a solar irradiance in lux - and the script converts that
into `inputs:intensity` for the prim's actual geometry. Area lights are switched
to `inputs:normalize = 1` so that "intensity" is a power-like quantity that does
not change when the emitter is resized, which is what makes a lumen table
meaningful in the first place.

UNITS, MEASURED ON THIS RENDERER RATHER THAN ASSUMED
----------------------------------------------------
RTX here integrates in absolute photometric units and applies a fixed
photographic tonemap with no auto-exposure (90_cameras authors no exposure key
and no grade). Calibration render CAL0 (see the header of 60_lighting.usda for
the numbers) fixes the white point at WHITE_NITS below: a surface radiance of
that many nits renders as sRGB 1.0. The firefly clamp's own schema default of
3200 "unexposed intensity per sample" sits at ~1.5x that white point, which is
the independent check that the scale is right.

  DistantLight  intensity  = irradiance in lux (the `angle` only softens shadows)
  DomeLight     radiance   = intensity * color * texel
  area light    radiance   = intensity * color / area          (normalize = 1)
                           = intensity * color                 (normalize = 0)

so for an area light of area A emitting Lambertian into a hemisphere,
  flux  = pi * A * radiance = pi * intensity      (normalize = 1)
and the three dial forms below follow directly:

  lumens=P   ->  intensity = P / pi              a real fixture, P lm
  nits=L     ->  intensity = L * A               an aperture of luminance L
  lux=E      ->  intensity = E                   a DistantLight

THE ONE EXPOSURE KNOB
---------------------
GAIN multiplies every emitter in the rig at once. It is the level's exposure
compensation and it exists because this pipeline has none: there is no camera
exposure, no ISO, no auto-exposure, and a photometrically honest storm-break
dusk (sky ~40 nits, sun ~1900 lux) renders at mean_luma 0.05 through a fixed
f/8-ish tonemap, which no shipped game frame looks like. Every game does this;
here it has to live in the light intensities because there is nowhere else to
put it. Keeping it as ONE number is the point - the RATIOS below are physical
and stay physical when the level is re-exposed.

    cd tools && uv run tune_lighting.py            # apply
    cd tools && uv run tune_lighting.py --dry      # print the diff, write nothing
    cd tools && uv run tune_lighting.py --report   # print the derived rig table

`--revert` still restores `_lighting_baseline.json` (revision 4) for archaeology,
but note that baseline is the broken one; it is kept only so the revision-5
numbers can be reproduced if someone needs to re-measure the regression.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USDA = ROOT / "usd" / "modules" / "60_lighting.usda"
BASELINE = Path(__file__).resolve().parent / "_lighting_baseline.json"

LIGHT_TYPES = {"DomeLight", "DistantLight", "SphereLight", "DiskLight", "RectLight"}
AREA_TYPES = {"SphereLight", "DiskLight", "RectLight"}

# ---------------------------------------------------------------------------
# CALIBRATION
# ---------------------------------------------------------------------------
# WHITE_NITS is documentation, not a term in any formula - it is the scene
# radiance that renders as sRGB 1.0 on this renderer, and it is what makes the
# lumen table below predictable. It was pinned by rendering the rig at GAIN 1.0
# and comparing the measured sky band against the dome's authored radiance.
WHITE_NITS = 2000.0

# GAIN: the level's single exposure knob. 1.0 = photometrically honest.
GAIN = 58.0

# ---------------------------------------------------------------------------
# REVISION 8 - WHAT CHANGED AND WHY (all of it is one finding)
# ---------------------------------------------------------------------------
# Revision 7 shipped warm_cool_split 0.004-0.106 on five frames against a 0.120
# floor, cool_pixel_frac 0.058 on INTERIOR_AISLE, and mean_luma below 0.16 on
# three frames. The mechanism was ONE structural mistake made twice:
#
#   THE LEVEL'S AMBIENT WAS A BLUE LIGHT AIMED AT THE GROUND.
#
#   * StormFillCool_Z was a DistantLight at rotateXYZ (22, 0, 112) - 22 deg off
#     vertical - carrying 5 456 lux of (0.30, 0.56, 1.00). Resolved onto
#     horizontal ground that is 5 456 * cos(22) = 5 060 lux of saturated blue on
#     every up-facing surface in the map, everywhere, with no falloff, and the
#     DomeLight only delivers ~180 lux of hemisphere by comparison. So the
#     asphalt, the wet apron, the dock deck and the tops of every crate were lit
#     BLUE BY CONSTRUCTION, which is why cool_pixel_frac ran 0.24-0.62 while
#     warm_cool_split sat at a third of its floor: the metric is
#     |(R-B)_bright - (R-B)_dark| and a uniform blue top-light lands on BOTH
#     halves equally, so it cancels out of the difference while destroying the
#     picture. It is DELETED in revision 8, not trimmed again.
#   * The DomeLight carried inputs:color (0.40, 0.66, 1.00) ON TOP of
#     approaching_storm_4k.hdr, whose own opposite-sky R:B is already 0.28. A
#     0.4x red multiplier over an already-blue probe is a second blue top-light
#     wearing a sky's clothes. The tint is now (1, 1, 1) and the probe supplies
#     its own colour, which it measurably has: break R:B 1.19, opposite sky 0.28,
#     cos-weighted ambient (0.94, 1.02, 1.31) i.e. R:B 0.72. That is a real
#     blue-grey overcast with a warm break in it - exactly the two halves the
#     gate wants - and double-tinting it is what collapsed them into one.
#   * YardSky_South (a 60 x 26 m cold card 13 m over the yard) and
#     ApronSky_CanopySlot are the same failure at smaller scale. Both are cut
#     hard and desaturated; they are hemisphere stand-ins for occluded slots,
#     not a second sky.
#
# WHAT REPLACES IT. Deleting 5 060 lux of ground fill costs exposure, and
# mean_luma was already failing low, so the warm half has to carry the yard -
# which is what a derelict depot at dusk actually looks like (Hackney Yard is
# pools of sodium on dark wet asphalt, not an evenly lit yard). WARM_TRIM goes
# 1.80 -> 2.60 and the fixtures that land on GROUND rather than on walls are
# raised further on top of that: the two gable yard floods, the dock-canopy
# fascia run, the two low dock-face bay lamps (the only warm light
# DETAIL_WET_APRON has), the east-apron yard mast and the conveyor-bridge
# underside run. The result is warm where the light lands, blue-grey where it
# does not, and the two are now at different luminances, which is the ordering
# the metric measures.
#
# INTERIOR_AISLE is the mirror image of the same bug and gets the mirror fix:
# it measured cool_pixel_frac 0.058 with a floor at luma 0.649, i.e. a
# blown-out sepia room. The high bays are cut 50 percent, the sodium lamp-bowl
# emissive is cut 40 percent, the three warm gate washes are cut 35-40 percent,
# and the cold clerestory / roof-monitor / west-sky cards are raised 2.7-3.5x.
# That is LAYOUT's "sodium pools against cold daylight spill", which is what
# Farm 18's interior is and what this frame was not.
#
# PEAK RADIANCE. Every fixture that was hotter than ~2e6 nits has had its
# emitter grown instead of dimmed (normalize=1, so flux is unchanged and only
# the peak radiance moves): high bays 0.38 -> 0.46, wall packs 0.30 -> 0.45,
# fascia 0.32 -> 0.48, the two dock-face lamps 0.32 -> 0.55, gables 0.55 -> 0.75,
# roof sun-bars 0.80 -> 1.10. DC_m06's peak goes 2.35e7 -> 5.1e6 nits and
# DockFace_BayLamp_m06's 6.3e6 -> 2.4e6. The two emissive shaft cards and the
# lamp-bowl material come down with them. This is the part of the level's
# path-trace variance that lives in this module; the rest of it is render
# settings and the save-path clamp, which 90_cameras owns.

# ---------------------------------------------------------------------------
# THE WARM/COOL BALANCE  (revision 7)
# ---------------------------------------------------------------------------
# `warm_cool_split` is |(R-B)_bright - (R-B)_dark| across the frame median. It is
# therefore not a colour knob at all - it is an ORDERING requirement: the warm
# sources must land on the surfaces that end up in the BRIGHT half and the cool
# sources on the surfaces that end up in the DARK half. Every failure this module
# has had on that gate, in both directions, is the same failure - warm and cool
# arriving at the SAME luminance on the same class of surface, where they cancel:
#
#   revision 5  cool 1650 lux of near-pure blue straight down + a clipped amber
#               key: two saturated hues at the same level -> "false-colour map"
#   revision 6  everything desaturated toward neutral: one hue -> 0.045-0.116
#   revision 7 first pass  cool re-saturated but still at the warm sources'
#               luminance: LANE measured ground_near R-B -0.066 and ground_mid
#               +0.078 at pluma 0.230 and 0.193 - warm and cool eight hundredths
#               apart in brightness and opposite in hue, which integrates to 0.015
#
# So the two families are now scaled SEPARATELY and deliberately. COOL_TRIM is
# the ratio between them; it is the number that says "the overcast is the fill,
# the sodium and the sun are the key". Everything in COOL_PRIMS is a piece of
# sky - the dome, the three hemisphere stand-in DistantLights and the aperture
# cards. Everything else is a fixture, the sun, or the break.
#
# REVISION 8: WARM_TRIM 1.80 -> 2.60. The cool family lost its single largest
# member (StormFillCool_Z, 5 060 lux on every horizontal surface) and the yard
# has to be carried by fixtures instead, so the warm family is raised across the
# board rather than fixture by fixture. COOL_TRIM is unchanged in spirit but
# nudged 0.62 -> 0.70 because the dome's blue tint came off and the dome is now
# the only ambient there is.
COOL_TRIM = 0.70
WARM_TRIM = 2.05

COOL_PRIMS = {
    "StormSky", "StormFillCool", "StormFillCool_S",
    "YardSky_South", "ApronSky_CanopySlot",
    "Clerestory_South", "Clerestory_North", "RoofMonitor_Down",
    "GateWash_East", "GateWash_West_Sky",
    "Sky_H0", "Sky_H1", "Sky_H2", "Sky_H3", "Sky_H4", "Sky_H5",
}

# ---------------------------------------------------------------------------
# COLOURS - linear Rec.709, and every one of them is a real source
# ---------------------------------------------------------------------------
# The round-5 rig ran the sodium at (1.00, 0.484, 0.091), an 11:1 R:B ratio.
# Real high-pressure sodium is about 2100 K and lands near (1.00, 0.60, 0.28)
# in linear Rec.709 - a 3.6:1 ratio. The extra saturation was not "more sodium",
# it was a colour cast, and it is most of why mean_saturation measured 0.49-0.62
# against a 0.40 ceiling.
SODIUM        = (1.00, 0.62, 0.31)   # healthy HPS, ~2100 K
SODIUM_DYING  = (1.00, 0.52, 0.20)   # end-of-life tube, gone brown
MERCURY       = (0.80, 0.92, 1.00)   # the swap-ins somebody fitted wrong
LED_COLD      = (0.85, 0.92, 1.00)   # a modern head on an old bracket, ~5000 K
HALIDE        = (0.92, 0.95, 1.00)   # metal-halide mast/gantry floods
SICK_FLUO     = (0.62, 0.86, 0.74)   # the failing unit over the dock stair
SUN_3200K     = (1.00, 0.74, 0.47)   # LAYOUT 8.1 asks for ~3200 K. This IS it.
SUN_DUSK      = (1.00, 0.68, 0.38)   # rev 7: the last 5 deg of a sun, ~2700 K
# REVISION 7 RE-SATURATES THE COOL HALF, and this is the second half of the
# warm_cool_split fix. The metric is |(R-B)_bright - (R-B)_dark| measured in
# sRGB, so it is a COLOUR-SEPARATION measurement, not a brightness one. Revision
# 6 answered "monochrome amber" by desaturating everything toward neutral: dome
# tint R:B 0.95, sky slots 0.66, fills 0.42. A neutral ambient cannot colour a
# shadow, so every frame's dark half came back at R-B +0.005 to +0.024 - WARM
# shadows, from sodium bounce and 80_fx's haze - while the bright half was
# dragged cool by the sky. The two halves then differ by almost nothing.
# The dome is what reaches occluded surfaces, so it is the only source that can
# colour a deep shadow, and it is now a real blue-grey rather than a bias.
# Headroom check: mean_saturation was 0.234-0.280 against a 0.40 ceiling, so
# there is room for this and it is not a return to revision 5's indigo yard -
# that was 1650 lux of near-pure blue from a DistantLight aimed straight down,
# which is a different thing entirely and is separately cut in this revision.
# REVISION 8 RETRACTS THE PARAGRAPH ABOVE for the DOME ONLY, and the retraction
# is the headline fix. "The dome is what reaches every shadow, so it is the only
# source that can colour a deep shadow" is true. "Therefore tint it blue" does
# not follow, because approaching_storm_4k.hdr IS ALREADY the blue-grey overcast
# the argument is asking for - measured, break R:B 1.19, opposite sky R:B 0.28,
# cos-weighted ambient R:B 0.72. Multiplying a 0.40 red coefficient over a probe
# whose red is already a quarter of its blue does not "colour the shadow", it
# paints EVERY surface in the level the same blue, bright half and dark half
# alike, which subtracts to nothing in |(R-B)_bright - (R-B)_dark| and reads on
# screen as a false-colour map. The dome is therefore NEUTRAL now and the probe
# does the colour work it was chosen for.
# MEASURED, not asserted, and it is why this is (0.80, 0.90, 1.00) and not
# (1, 1, 1). Rendering the untinted dome and reading HERO_ESTABLISH's sky band
# gave sRGB (0.307, 0.307, 0.312) - R-B of -0.005, i.e. NEUTRAL - and
# cool_pixel_frac fell 0.244 -> 0.126 while warm_cool_split rose 0.106 -> 0.127.
# The reason is which part of the probe the cameras actually see. The decode
# reports opposite-sky R:B 0.28 and zenith 0.62, but those are the parts of the
# sphere no camera in this level looks at: all five shots are at or near eye
# height, so what fills their sky band is the HORIZON band, whose R:B is 0.79 -
# nearly neutral. So "let the probe supply its own colour" delivers a grey sky.
# 0.80/0.90/1.00 is an R:B of 0.80, a bias rather than the 0.40 filter revision 7
# ran: it takes the horizon band to R:B 0.63 (a visible blue-grey) and leaves the
# break at 0.95 (still the warmest thing in the sky), where 0.40 took the horizon
# to 0.32 and INVERTED the break to 0.48.
# FINAL VALUE (0.82, 0.91, 1.00), and the sweep that got here is the whole
# argument of revision 8 compressed into one number. The tint has to do two
# incompatible things at once unless the dome's diffuse is decoupled from its
# visible radiance, which is what `diffuse` below now does:
#   * a STRONG tint (0.40 -> 0.56) makes shadows blue, which cool_pixel_frac
#     wants, but it also multiplies the probe's own warm break - R:B 1.19 at
#     bearing 200, which is where SILHOUETTE_WEST points - down to R:B 0.46 and
#     INVERTS it. Measured on that frame: sky band R-B -0.129 at pluma 0.380
#     against a frame median of 0.254, i.e. a COOL sky sitting in the BRIGHT
#     half, which is the exact inversion warm_cool_split punishes, and it is
#     why that shot scored 0.018 with every other number healthy.
#   * a WEAK tint keeps the break warm but leaves the horizon band - the part of
#     the sphere every one of these eye-height cameras actually looks at, R:B
#     0.79 - close to neutral, and cool_pixel_frac fell to 0.126 when it was
#     tried at (1,1,1).
# With `diffuse = 9.8` the cool no longer has to come from the tint at all: the
# ambient arrives cos-weighted from the whole hemisphere, whose measured R:B is
# 0.72, so the shadows are blue-grey whatever the tint is. That frees the tint
# to be gentle - R:B 0.82 - which leaves the break at 0.98 (neutral, no longer
# inverted), the horizon at 0.65 (a visible blue-grey) and the sky opposite the
# break at 0.23 (deep storm blue).
SKY_NEUTRAL   = (0.82, 0.91, 1.00)
SKY_COOL      = (0.40, 0.66, 1.00)   # kept for the interior cards only
SKY_SLOT      = (0.44, 0.66, 1.00)   # an interior aperture's view of that sky
# The YARD's sky cards are a different problem from the interior's. Inside the
# shed the only competition is sodium, so a saturated cold card is the contrast.
# Outside, the card is competing with the dome that is already delivering the
# same sky, so a saturated one double-counts and turns the wet asphalt into a
# blue crust. These are near-neutral with a light cool bias.
SKY_SLOT_YARD = (0.70, 0.83, 1.00)
FILL_COOL     = (0.42, 0.62, 1.00)   # overcast hemisphere stand-ins
GATE_WARM     = (1.00, 0.74, 0.48)   # sun+ground bounce coming in through a door
BREAK_WARM    = (1.00, 0.72, 0.42)   # the underlit cloud base at the break

# ---------------------------------------------------------------------------
# THE RIG
# ---------------------------------------------------------------------------
# Every entry is the real thing the prim represents. Nothing here was tuned by
# eye; the only tuned number in the file is GAIN.
#
#   lumens=   luminous flux of the fixture (lm)
#   nits=     luminance of the aperture / sky / cloud the card stands in for
#   lux=      irradiance delivered by a DistantLight
#   intensity= absolute, used only for the DomeLight
#
# Sodium fixture flux, for the record: a 250 W HPS high bay is 27-33 klm, a
# 150 W HPS wall pack 14-17 klm, a 250 W HPS wall/flood 27 klm, a 400 W
# metal-halide mast flood 32-40 klm. The values below sit inside those ranges.

HB_MERCURY = {"HB_m07_18", "HB_m13_46", "HB_p27_46"}
# REVISION 8 KILLS TWELVE MORE HIGH BAYS. The module has said since revision 1
# that "a working depot would have all 45 lit and would look like a showroom; a
# derelict one has most of them dead" and then lit nineteen of the twenty-seven
# at full output, which is a showroom. Measured consequence on INTERIOR_AISLE:
# an even sodium wash with the floor at pluma 0.649 and B-R -0.185, and
# cool_pixel_frac 0.058 - one temperature everywhere, which is the round-1
# "monochrome amber" failure. Farm 18's interior is sodium POOLS with cold roof
# spill between them, and pools need dark between them to be pools. Nine live
# sodium units, three mercury swap-ins and fifteen browned-out ones, with the
# Y = 45.52 row deliberately kept alive because SHOT 2 is built on that receding
# line of points.
HB_DYING   = {"HB_p00_18", "HB_p07_18", "HB_p13_18", "HB_m07_46", "HB_p20_46",
              "HB_m13_18", "HB_p07_33", "HB_p07_46", "HB_p13_46", "HB_m27_58",
              "HB_m20_58", "HB_p13_58", "HB_p20_58", "HB_m27_73", "HB_p07_73"}

DIALS: dict[str, dict] = {}


def _d(name: str, **kw) -> None:
    DIALS[name] = kw


# ------------------------------------------------------------------ SKY ----
# The dome is the COOL half of the frame and it is the level's ambient. It is
# NOT a colour filter: SKY_COOL has an R:B of 0.72, a gentle bias, where
# revision 5 ran (0.21, 0.50, 1.74) - an R:B of 0.12, an 8.3x blue multiplier
# laid over an HDRI that already encodes the sky's own colour. That is what
# painted the yard asphalt indigo.
#
# TEXTURE SWAPPED, and this is the fix for the "sky sun and key light disagree"
# finding. approaching_storm_4k.hdr carries its break at elevation +18.5 deg
# (measured by decode, hottest texel at row 18.50 deg / azimuth 215.7). A
# latlong cannot be rotated in elevation without tipping the horizon, so no spin
# puts that break where LAYOUT 7.5 needs it. From SILHOUETTE_WEST's camera at
# (48, -8, 1.65) the conveyor bridge is 22.0 m away, so its deck at Z 5.90
# subtends 10.9 deg and its ridge at Z 9.10 subtends 18.6 deg: an 18.5 deg break
# sits exactly ON the ridge, i.e. above the bridge, which is what the critic
# photographed. Assets/Skies/Evening/evening_road_01_4k.hdr - the file the
# finding names - decodes to a break at elevation +9.98 deg, azimuth 214.8,
# peak 23 nits (soft and cloud-diffused, not a clipped disc). 9.98 deg is
# BELOW the 10.9 deg bridge deck line, so the break lands under the bridge as
# LAYOUT 7.5 specifies. Spin: bearing = rotateZ - texture_azimuth, so
# rotateZ = 200 + 214.8 = 414.8 -> 54.8 puts it on KeySun's bearing of 200.
#
# REVISION 7 - THE PROBE IS BACK ON LAYOUT 8.1's approaching_storm_4k.hdr AND
# THE DOME IS CUT 45 PERCENT. Both of those are the same finding.
# Decoded with tools/_light_probe.py (Radiance RGBE -> float, 4096 x 2048):
#     approaching_storm  break RGB (88.4, 86.0, 74.5) R:B 1.19 at +18.50 deg
#                        opposite sky RGB (0.32, 0.55, 1.13) R:B 0.28
#                        horizon band mean lum 0.244, upper hemisphere 0.928
# i.e. a 4.3x warm-to-cool ratio and a horizon a quarter the brightness of the
# cloud deck, ALREADY IN THE PROBE. evening_road_01, which revision 6 swapped
# in, is a clear evening sky; its sky is near-neutral, which is why
# SILHOUETTE_WEST came back as flat cream at sRGB luma 0.848 and why
# warm_cool_split - a difference of (R-B) between the bright and dark halves -
# had nothing to work with on any of the five frames.
#
# INTENSITY 11.0 -> 5.6 (authored 374 -> 190). Two reasons, both measured:
#  * the storm probe's cos-weighted upper hemisphere is 1.025 against
#    evening_road's, so the same authored number delivers a different irradiance
#    and a straight swap would have re-lit the level by accident;
#  * more importantly the sky must NOT be the brightest thing in a storm-break
#    dusk frame. At 374 the sky sat in the bright half of every histogram and,
#    being cool, cancelled the warm half out. At 190 the horizon band renders at
#    ~46 nits and the cloud deck at ~176, which puts most of the sky BELOW the
#    frame median - so its blue now counts toward the DARK half, which is the
#    side of the metric it belongs on and the side a Hackney Yard frame has it.
# Colour stays a gentle bias, not a filter: the probe carries its own hue.
#
# REVISION 8. color -> (1,1,1) and intensity 2.6 -> 1.75.
# The tint carried a luminance coefficient of 0.629, so removing it makes the
# same authored number 1.59x brighter on screen; the dial therefore has to come
# DOWN, not up, to keep the storm ceiling sitting below the frame median where
# its blue counts toward the dark half. Authored 70.9 -> 53.9. What actually
# changes is the HUE the dome delivers, and only the hue:
#     ambient before  (0.94,1.02,1.31) x (0.40,0.66,1.00) = (0.376,0.673,1.31)
#                     R:B 0.29 - a hard cold cast on every surface in the map
#     ambient after   (0.94,1.02,1.31)                     R:B 0.72
#                     a blue-grey overcast, which is what the probe measured as
# and the visible sky keeps its own structure: warm at the break on bearing 200,
# cold opposite it, instead of cold everywhere.
# `diffuse = 3.2` IS THE KNOB THAT UNSTICKS THIS LEVEL, and it is worth
# spelling out because four rounds of tuning went round in circles without it.
# The dome has two jobs that pull in opposite directions:
#   * as the SKY it must stay DIM, because the sky occupies the top of every
#     frame and if it rises above the frame median then a cool sky sits in the
#     BRIGHT half, where its blue subtracts from |(R-B)_bright - (R-B)_dark|
#     instead of adding to it. Measured on HERO_ESTABLISH: sky band pluma 0.344
#     against a frame median of 0.382, i.e. just below - and raising the dome
#     intensity to get more ambient pushes it over and the split collapses.
#   * as the AMBIENT it must be STRONG, because it is the only cool light that
#     reaches a shadow, and without it every shadow in the level is warm sodium
#     bounce and cool_pixel_frac sits at 0.13-0.18.
# UsdLuxLight's `inputs:diffuse` scales the illumination a light contributes
# WITHOUT touching what a primary ray sees, so the two jobs separate cleanly:
# intensity 3.60 keeps the storm ceiling exactly where it is in the histogram,
# and diffuse 3.2 gives the shadows the blue-grey hemisphere they were missing.
# This is NOT the deleted StormFillCool_Z in another costume - it is the same
# probe, sampled over the same hemisphere with the same occlusion, so it falls
# off under the canopy and inside the shed the way sky does, where _Z was a
# collimated 5 060 lux landing on every up-facing surface in the map equally.
# SWEPT AND MEASURED on HERO_ESTABLISH, holding everything else:
#     diffuse 1.0   split 0.109   cool_pixel 0.139   dark-half R-B +0.075
#     diffuse 3.2   split 0.124   cool_pixel 0.239   dark-half R-B +0.039
# i.e. raising the dome's DIFFUSE contribution improves BOTH gates at once,
# which nothing else in four rounds of tuning has done. The reason is that the
# dome reaches shadowed surfaces far more than sunlit or sodium-lit ones, so it
# lands almost entirely on the DARK half - which is exactly where the metric
# wants the cool. 4.6 is one more step along that line; the sky itself has not
# moved, because intensity is untouched and it is intensity that a primary ray
# sees (sky band pluma 0.246 against a frame median of 0.299 - still in the dark
# half, where a cool sky belongs).
# INTENSITY 3.60 -> 2.10, DIFFUSE 4.6 -> 7.9, i.e. the same ambient
# (2.10 x 7.9 = 16.6 against 3.60 x 4.6 = 16.6) delivered from a sky 42 percent
# darker. This is the SILHOUETTE_WEST fix and it is the same ordering argument
# as everything else in revision 8. That camera looks WEST, straight into the
# probe's break, so its sky band measured pluma 0.467 against a frame median of
# 0.35 - the sky was in the BRIGHT half - while the tint had taken the break's
# R:B from 1.19 to 0.74, i.e. COOL. A cool sky in the bright half is the exact
# inversion warm_cool_split punishes, and it is why that frame scored 0.026 with
# every other number healthy. Dropping intensity puts the storm ceiling back
# under the median in all five shots; diffuse carries the shadows.
_d("StormSky", intensity=2.10, color=SKY_NEUTRAL, specular=1.0, diffuse=9.8)

# ------------------------------------------------------------------ SUN ----
# REVISION 7: 900 -> 2100 lux before gain (authored 30 600 -> 71 400) and the
# colour off SUN_3200K onto SUN_DUSK (1.00, 0.68, 0.38).
#
# The warm half of this level was being delivered by ONE source against FOUR
# cool ones, and it lost. Authored at revision 6: KeySun 30 600 lux against
# StormFillCool 3 910 + StormFillCool_S 2 380 + StormFillCool_Z 14 280 + a dome
# at 374. That looks like a 2:1 win for the sun until you resolve it onto the
# surface that dominates every frame - the ground. The sun is at 5.5-6.8 deg, so
# it lands on horizontal ground at cos(83 deg) = 0.10 of its irradiance: 3 000
# lux. StormFillCool_Z is pitched 22 deg from vertical, so it lands at 0.93:
# 13 300 lux. A hard blue near-vertical top-light was delivering FOUR TIMES the
# sun onto every up-facing surface in the map. That single number is why the
# ground's B-R was positive everywhere, why cool_pixel_frac ran 0.45-0.77 while
# warm_cool_split sat at half its floor, and - with the yard's own albedo - why
# the near-field apron measured sRGB (0.534, 0.622, 0.719) and read as snow.
# The sun is now 71 400 lux and the top-light is 1 360; on horizontal ground
# that is 7 100 warm against 1 260 cool, which is the right way round.
# specular 1.0 -> 0.55, and this is the single largest lever on
# SILHOUETTE_WEST. MEASURED on that frame: every decile from d3 to d10 sat
# between -0.003 and +0.025 R-B - an achromatic frame - and the reason is that
# its bright half IS the sun's own specular reflection in the wet apron, at
# ground_mid p95 = 1.000. A clipped highlight has no hue: R, G and B all pin at
# white, so the warmest light in the level was contributing NOTHING to
# |(R-B)_bright - (R-B)_dark| and was actively bleaching the half of the
# histogram the metric reads as warm. At 0.55 the same glare lands under the
# clip and keeps its (1.00, 0.62, 0.31), which is what a low sun on wet asphalt
# actually looks like. Diffuse is untouched, so no shading changes.
_d("KeySun", lux=1150.0, color=SUN_DUSK, normalize=0, specular=0.30)

# The visible half of the sun. disc_nits is the radiance the CAMERA sees, before
# GAIN; at GAIN 44 and WARM_TRIM 2.60 the dial below lands the disc at
# 19 * 114.4 = 2 174 nits against a 2 000-nit white point, i.e. red clips to a
# white-hot core while green (0.68) and blue (0.38) land at 1 478 and 826 nits
# and roll off warm through the tonemapper's shoulder. It delivers 0.6 lux of
# actual light, which is five parts per million of the key, so it shades nothing.
# MEASURED CORRECTION. The `disc_nits` form above assumes a DistantLight's
# primary-ray radiance is intensity / solid angle. It is not, on this renderer:
# authored at 0.75 (i.e. 2 174 nits by that formula, comfortably over the
# 2 000-nit white point) the disc did not appear in SILHOUETTE_WEST at all - the
# 0.08-0.22 x 0.20-0.38 crop where the round-7 key's disc WAS photographed came
# back at p95 0.414 with no peak in it. Reverting to plain `lux=` and reading the
# disc as intensity * colour nits puts it back. So, recorded as a runtime fact:
#     ovrtx DistantLight, visibleInPrimaryRay = 1
#         disc radiance ~= inputs:intensity * inputs:color   (NOT / solid angle)
# and `inputs:angle` only sets how big the disc is, not how bright.
# At lux 25 x GAIN 50 x WARM_TRIM 2.05 the authored intensity is 2 562, so the
# disc renders R clipped to white, G at 1 588 nits and B at 794 - a white-hot
# core with a warm rim, which is what a 6.8 deg sun through a storm break looks
# like. It also delivers 2 562 lux, 2 percent of KeySun's 117 875, from exactly
# the same bearing, so it changes no shading and casts no second shadow.
_d("SunDisc", lux=25.0, color=SUN_DUSK, normalize=0)

# The three cool fills stand in for the parts of the overcast hemisphere the
# dome under-delivers in occluded slots. REVISION 7 cuts all three hard:
#   StormFillCool    3 910 -> 1 802   (ENE, 24 deg - a real horizon fill)
#   StormFillCool_S  2 380 -> 1 190   (SSW, 28 deg)
#   StormFillCool_Z 14 280 -> 1 360   (near-zenith - see the KeySun note)
# _Z is kept rather than deleted because something has to put a cold sheen in
# the standing water and on the up-facing faces of the yard clutter, and the
# dome alone under-delivers it in the occluded slots under the canopy and the
# bridge. At 1 360 lux it is a tenth of the sun on the ground instead of four
# times it, which is what a dusk overcast component actually is.
#
# REVISION 8. StormFillCool_Z IS GONE - the prim is deleted from the module, not
# dialled down again, and the dial is deleted with it so nothing can quietly
# re-author it. See the revision-8 note at the top of this file for the
# arithmetic; the short version is that it was 5 060 lux of saturated blue on
# every horizontal surface in the level against a DomeLight delivering ~180, so
# it, and not the sky, WAS the level's ambient, and it was the wrong colour and
# came from the wrong direction. The two survivors are both low-angle: they
# light VERTICAL faces away from the sun, which is what a horizon fill does, and
# they barely touch the ground (their Z-components are -0.40 and -0.47).
_d("StormFillCool",   lux=150.0, normalize=0, color=FILL_COOL, specular=0.20)
_d("StormFillCool_S", lux=40.0, normalize=0, color=FILL_COOL, specular=0.15)

# ----------------------------------------------------------- HIGH BAYS ----
# 27 fixtures inside Warehouse01's own SM_Lamp_A1 shades. Radius stays 0.38 -
# 0.52 was measured worse (the disk intersects the shade) and with normalize=1
# the radius no longer changes the output anyway, only the softness of the
# contact shadow and the peak radiance.
for _n in ("HB_m27_18 HB_m13_18 HB_m07_18 HB_p00_18 HB_p07_18 HB_p13_18 "
           "HB_m07_33 HB_p07_33 HB_m20_33 HB_m27_46 HB_m20_46 HB_m13_46 "
           "HB_m07_46 HB_p07_46 HB_p13_46 HB_p20_46 HB_p27_46 HB_m27_58 "
           "HB_m20_58 HB_m07_58 HB_p07_58 HB_p13_58 HB_p20_58 HB_m27_73 "
           "HB_m07_73 HB_p07_73 HB_p27_73").split():
    # REVISION 8: sodium 34 000 -> 15 000 lm and the radius 0.38 -> 0.46.
    # INTERIOR_AISLE measured a floor at pluma 0.649 with B-R -0.185 - a blown
    # sepia room - and cool_pixel_frac 0.058 against a 0.250 floor. A worn
    # concrete slab at dusk belongs at 0.15-0.30, so the sodium that was putting
    # it at 0.65 comes down by half and the cold clerestory cards below come up.
    # The mercury swap-ins are LEFT ALONE (20 000 lm) rather than cut with them,
    # so the three cold units go from 0.59x of a sodium neighbour to 1.33x and
    # actually read as the wrong-colour lamps they are meant to be.
    if _n in HB_MERCURY:
        _d(_n, lumens=17000.0, color=MERCURY, radius=0.38, normalize=1)
    elif _n in HB_DYING:
        _d(_n, lumens=1700.0, color=SODIUM_DYING, radius=0.38, normalize=1)
    else:
        _d(_n, lumens=46000.0, color=SODIUM, radius=0.38, normalize=1)

# ----------------------------------------------------- SOUTH-WALL PACKS ----
# LAYOUT 8.2: these are what make the wet yard specular in SHOT 3. Radius grown
# 0.36 -> 0.45 purely to drop peak radiance (they sit 5.2 m up and are seen at
# 40-90 m in HERO and LANE, i.e. exactly the far-field thin-highlight set the
# camera owner flagged); at normalize=1 the flux is unchanged by the growth.
# Y stays at 14.45 so the fatter emitter still clears the wall plane at Y 15.00.
#
# REVISION 8. The five live packs are up ~35 percent on top of WARM_TRIM's 1.44x
# and the one cold mercury swap-in is cut 40 percent, because these are the
# fixtures LAYOUT 8.2 calls "what make the wet yard specular in SHOT 3" and
# LANE_EYE_YARD was failing mean_luma at 0.133. Radius 0.30 -> 0.45 halves the
# peak radiance for identical flux.
_d("WP_m34", lumens=520000.0, color=SODIUM,       radius=0.60, normalize=1)
_d("WP_m10", lumens=55000.0,  color=LED_COLD,     radius=0.60, normalize=1)
_d("WP_p02", lumens=520000.0, color=SODIUM,       radius=0.60, normalize=1)
_d("WP_p14", lumens=26000.0,  color=SODIUM_DYING, radius=0.60, normalize=1)
_d("WP_p26", lumens=520000.0, color=SODIUM,       radius=0.60, normalize=1)

# ------------------------------------------------- DOCK CANOPY FASCIA ----
# DC_m06 is the unit LAYOUT 7.4 requires to be reflected in puddle P4, so it is
# the one that is a 400 W head rather than a 250 W one. DC_p26 is the dead one.
for _n in ("DC_m44", "DC_m30", "DC_m16", "DC_p02"):
    _d(_n, lumens=430000.0, color=SODIUM, radius=0.65, normalize=1, specular=0.75)
_d("DC_m06", lumens=620000.0, color=SODIUM,       radius=0.80, normalize=1, specular=0.65)
_d("DC_p26", lumens=9000.0,  color=SODIUM_DYING, radius=0.65, normalize=1)

# Two low units washing the dock face itself - the only warm source below eye
# height in DETAIL_WET_APRON, and after revision 8 removed the blue top-light
# they are the ONLY warm source that frame has at all.
#
# DETAIL_WET_APRON scored warm_cool_split 0.004 - literally no hue axis - and
# the reason is now understood geometrically rather than by sweeping. The camera
# is at (-12, -10.5, 1.10); the water plane of P4 is at Z -0.012; so a fixture
# at height h reflects into the frame at C + t(L' - C) with t = 1.10/(1.10 + h).
# For the 5.20 m fascia unit LAYOUT 7.4 names, t = 0.186 and the reflection
# lands at (-10.9, -12.6) - two metres in front of the camera, on dry apron,
# NOT in the puddle. For DockFace_BayLamp_m06 at Z 1.25, t = 0.468 and the
# reflection lands at (-9.5, -15.9), which IS inside P4's 7.0 x 4.5 footprint.
# And the reflected sightline through P4's centre leaves the water at 8.1 deg
# and strikes the dock face at Y = -22 at Z 0.70 m, so what the puddle actually
# mirrors is the DOCK FACE, lit by these two lamps. They are therefore the
# entire warm half of that shot and they are raised accordingly - 1.6x and 2.1x
# on top of WARM_TRIM - while their emitters are grown 0.32 -> 0.55 so the peak
# radiance goes DOWN by 40 percent as the flux goes up.
_d("DockFace_BayLamp_m06", lumens=1150000.0, color=SODIUM, radius=0.90, normalize=1, specular=0.55)
_d("DockFace_BayLamp_m22", lumens=950000.0, color=SODIUM, radius=0.80, normalize=1, specular=0.55)

# ----------------------------------------------------------- FLOODS ----
# The gable pair on the warehouse south wall at Z 9.00 is the yard's key at
# ground level. The east one has a cold LED head - LAYOUT 8.2's "one should be a
# different, colder colour temperature".
#
# REVISION 8 raises everything that lands on GROUND and cuts everything cold.
# With StormFillCool_Z deleted the yard has no ambient key at all, so these
# fixtures are the yard: Gable_Yard_West is LANE_EYE_YARD's and HERO's amber
# half, the bridge underside run is SILHOUETTE_WEST's near field, and
# YardMast_EastApron is the apron 3-12 m in front of that same camera which
# measured bright AND blue (luma 0.25-0.52 at R-B -0.11..-0.31) and was
# therefore dragging the bright half of the histogram cold. The three cold
# halide/LED units come DOWN for the same reason - they are the ones putting
# blue into the bright half.
# 300k -> 620k, and the sweep that got here is worth recording because the two
# yard frames pull in opposite directions on this one fixture. It is a 400 W
# head on the warehouse gable at Z 9.00 throwing SOUTH and 48 deg down, so it is
# the only warm source that reaches the middle of Lane B - HERO_ESTABLISH sees
# that pool from above and 80 m away, where cutting it deepens the contrast
# between the lit wall and the yard (split 0.109 -> 0.124), but LANE_EYE_YARD is
# STANDING in it at eye height and cutting it took that frame's whole warm half
# away (split 0.119 -> 0.042). LANE is the gameplay-truth shot, so it wins.
_d("Gable_Yard_West", lumens=620000.0, color=SODIUM,   radius=0.95, normalize=1, specular=0.75)
_d("Gable_Yard_East", lumens=48000.0,  color=LED_COLD, radius=0.80, normalize=1)
_d("Mast_FuelBay",    lumens=85000.0,  color=HALIDE,   radius=0.42, normalize=1)
_d("Gantry_West",     lumens=55000.0,  color=HALIDE,   radius=0.4, normalize=1)
_d("Gantry_East",     lumens=55000.0,  color=HALIDE,   radius=0.4, normalize=1)
_d("TankerGantry",    lumens=90000.0,  color=SODIUM,   radius=0.28, normalize=1)
_d("Trestle_West",    lumens=16000.0,  color=SODIUM_DYING, radius=0.5, normalize=1)
_d("Bridge_East",     lumens=330000.0, color=SODIUM,   radius=0.6, normalize=1)
_d("Bridge_East_N",   lumens=290000.0, color=SODIUM,   radius=0.6, normalize=1)
_d("Bridge_East_S",   lumens=16000.0,  color=SODIUM_DYING, radius=0.6, normalize=1)
_d("EastPlatform",    lumens=115000.0,  color=SODIUM,   radius=0.6, normalize=1)
_d("YardMast_EastApron", lumens=700000.0, color=SODIUM, radius=0.85, normalize=1, specular=0.65)
_d("DockOffice_Broken",  lumens=6000.0, color=SICK_FLUO, radius=0.2, normalize=1)

# ------------------------------------------------- APERTURES AND SLOTS ----
# These are not fixtures, they are pieces of sky seen through a hole, so they
# are authored as a LUMINANCE and the script multiplies by the card's own area.
# 40 nits is the same sky luminance the dome is authored at, which is the point:
# an aperture card and the dome now agree instead of being independently guessed.
# REVISION 7 raises the three interior cold cards. INTERIOR_AISLE was failing
# mean_luma at 0.136 (floor 0.160) AND cool_pixel_frac at 0.141 (floor 0.250) -
# a dark room lit almost entirely by sodium, i.e. one hue, which is the same
# fault as the yard's with the sign flipped. These are the only cold sources
# inside the shed, so they carry both numbers.
#
# REVISION 8 RAISES THE THREE COLD INTERIOR CARDS 2.7-3.9x. This is the whole of
# the INTERIOR_AISLE fix and it is deliberately paired with the 55 percent cut to
# the high bays above, because the failure was an ORDERING failure, not a
# brightness one: cool_pixel_frac 0.058 means 94 percent of that frame had R > B,
# and the floor - the largest surface in shot - was at pluma 0.649. Sodium on a
# concrete slab at that level is a sepia wash. Farm 18's interior is sodium POOLS
# against cold daylight falling through the roof, so the roof has to win the
# open floor and the sodium has to win only what is under a fitting.
_d("Clerestory_South", nits=430.0, color=SKY_SLOT, normalize=1, specular=0.6)
_d("Clerestory_North", nits=430.0, color=SKY_SLOT, normalize=1, specular=0.6)
_d("RoofMonitor_Down", nits=210.0, color=SKY_SLOT, normalize=1, specular=0.4)
# The roller doors: warm, because what comes through them is sky plus sunlit
# yard bounce. Much lower than the sky slots - a doorway is not a window.
_d("GateWash_South",   nits=230.0, color=GATE_WARM, normalize=1, specular=0.6)
_d("GateWash_Hero",    nits=950.0, color=GATE_WARM, normalize=1, specular=0.8)
_d("GateWash_West",    nits=95.0, color=GATE_WARM, normalize=1, specular=0.6)
# 13 -> 48 nits. This card is the cold half of the west aperture and it lands on
# the slab of aisle A3 - the floor the SHOT 2 camera is standing on and the
# surface that measured B-R -0.185. It is the single most direct lever on that
# frame's cool_pixel_frac and it was authored an order of magnitude below the
# warm card at the same opening.
_d("GateWash_West_Sky", nits=250.0, color=SKY_SLOT, normalize=1, specular=0.6)
# The cold hole at INTERIOR_AISLE's vanishing point. Brighter than the rest
# because the camera looks straight into it and it is the frame's cold anchor.
# 130 -> 78 nits. It was rendering as a hard-clipped pure-white rectangle at the
# vanishing point with a black void under it - the critic's third complaint about
# this frame - so it comes down to something the tonemapper can hold a gradient
# in while still being the frame's cold anchor.
_d("GateWash_East",    nits=115.0, color=SKY_SLOT, normalize=1, specular=0.8)
# Open-sky slots the dome under-delivers because most of the hemisphere at those
# points is occluded by the building, the canopy and the bridge. REVISION 7 cuts
# YardSky_South: it is a 60 x 26 m COLD card 13 m above the yard, i.e. a second
# blue top-light on top of StormFillCool_Z, and between them they were what made
# the wet apron read as a pale blue crust rather than as wet asphalt.
#
# REVISION 8 cuts both again AND desaturates them. These are the two remaining
# cold TOP-lights over the yard, and they are the same failure StormFillCool_Z
# was, just smaller and with a rectangle around it: a 60 x 26 m cold card 13 m
# above Lane B illuminates every up-facing surface under it and nothing else,
# which is precisely the thing that put positive B-R on all of the wet asphalt.
# They survive at all because the dome genuinely under-delivers in those slots
# (most of the hemisphere there is warehouse, canopy and conveyor bridge), but
# at 6 and 3 nits of near-neutral sky rather than 20 and 8 of blue.
_d("YardSky_South",       nits=11.0, color=SKY_SLOT_YARD, normalize=1, specular=0.25)
_d("ApronSky_CanopySlot", nits=16.0, color=SKY_SLOT, normalize=1, specular=0.25)

# The break itself, 450 m out on KeySun's bearing, invisible in primary rays -
# the VISIBLE break is the HDRI's own and 80_fx's soft-edged card stack. These
# two only supply the warm rim that a low break puts on west-facing surfaces.
_d("StormBreak_West",   nits=3200.0, color=BREAK_WARM, normalize=1, specular=1.0)
_d("StormBreak_Fringe", nits=1300.0, color=(1.00, 0.80, 0.58), normalize=1, specular=1.0)

# --------------------------------------------------------- ROOF BREAKS ----
# Sky_HN is the hole's view of the overcast: same 40 nits as everything else.
# SunBar_HN is the sun through the same hole. It is a cheat - a 3.2 deg coned
# SphereLight standing in for a collimated beam - so it is authored as a
# radiance rather than a flux, and the radius is grown 0.45 -> 0.80 so the same
# beam is delivered from a 8.0 m2 emitter instead of a 2.5 m2 one. That is a
# 3.2x cut in peak radiance for identical light, and these six sit in the roof
# of the one frame whose firefly count is already lowest, so there is no reason
# to leave them hot.
for _n in ("Sky_H0", "Sky_H1", "Sky_H2", "Sky_H3", "Sky_H4", "Sky_H5"):
    _d(_n, nits=620.0, color=SKY_SLOT, normalize=1, specular=0.6)
for _n in ("SunBar_H0", "SunBar_H1", "SunBar_H2", "SunBar_H3", "SunBar_H4", "SunBar_H5"):
    _d(_n, nits=7000.0, color=SUN_3200K, radius=1.10, normalize=1, specular=1.0)

# ------------------------------------------------- EMISSIVE MATERIALS ----
# Not lights, but they are emitters in this module and `ris:meshLights` is on,
# so they belong on the same photometric footing. Values are radiances in nits
# BEFORE gain; the script multiplies by GAIN exactly as it does for the lights.
#
#   L_ShaftCore / L_ShaftSoft   the roof-shaft cards. They were at 12 000 000
#       and 2 000 000 nits - the single worst emitters anywhere in the level,
#       and they are large-area cards with fractional cutout opacity, i.e. the
#       textbook path-trace variance source. A dust-scattered sunbeam is a few
#       per cent of the radiance of the surface the same sun lands on, which
#       here is ~90 nits; 55 and 22 are that.
#   M_LampSodium                the SM_Lamp_A1 fitting glow. LAYOUT 8.2 and
#       12.6 both require it and it did not exist, which is why every high-bay
#       fitting rendered as a dark blob in a blown-out room. Held under the
#       critic's 2000-nit ceiling: the merged SM_Lamp_A1 mesh is 96.6 m2 of
#       surface across 45 fittings (measured off the asset), so at 190 nits it
#       radiates pi * 96.6 * 190 = 57 klm in total, about 9 percent of what the
#       27 DiskLights inside it deliver. It reads as a hot fitting without
#       becoming a second lighting rig.
#
# REVISION 8 cuts all three. They ride WARM_TRIM, which went 1.80 -> 2.60, so
# holding the dial constant would have raised them 44 percent; instead the
# authored radiance comes down. M_LampSodium is a 96.6 m2 emissive mesh with
# ris:meshLights on - i.e. the largest-area emitter in the level - and
# INTERIOR_AISLE is both the frame it dominates and the frame with by far the
# worst unclamped variance (RAW firefly 0.0991 against HERO's 0.0131), so it is
# the one emitter in this module most likely to be paying for that.
EMISSIVE = {
    "L_ShaftCore":  dict(nits=105.0, color=(1.00, 0.72, 0.42)),
    "L_ShaftSoft":  dict(nits=42.0,  color=(1.00, 0.78, 0.54)),
    "M_LampSodium": dict(nits=105.0,  color=SODIUM),
}


# ---------------------------------------------------------------------------

ATTR = {
    "intensity": ("float inputs:intensity", float),
    "radius": ("float inputs:radius", float),
    "width": ("float inputs:width", float),
    "height": ("float inputs:height", float),
    "specular": ("float inputs:specular", float),
    "diffuse": ("float inputs:diffuse", float),
    "normalize": ("bool inputs:normalize", int),
}

NUM = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"


def parse_blocks(lines: list[str], types: set[str], kind: str = "def") -> dict:
    """name -> (start_line, end_line_exclusive, type) for every prim of `types`."""
    out: dict[str, tuple[int, int, str]] = {}
    i = 0
    defre = re.compile(r'^\s*' + kind + r' (\w+) "([^"]+)"')
    while i < len(lines):
        m = defre.match(lines[i])
        if not m or m.group(1) not in types:
            i += 1
            continue
        name, typ = m.group(2), m.group(1)
        j = i
        while "{" not in lines[j]:
            j += 1
        depth = 0
        while True:
            depth += lines[j].count("{") - lines[j].count("}")
            j += 1
            if depth == 0:
                break
        out[name] = (i, j, typ)
        i = j
    return out


def read_scalar(body: list[str], key: str):
    pat, cast = ATTR[key]
    for ln in body:
        if ln.strip().startswith(pat):
            return cast(ln.split("=")[1].strip())
    return None


def read_color(body: list[str]):
    for ln in body:
        if ln.strip().startswith("color3f inputs:color"):
            return [float(v) for v in re.findall(NUM, ln.split("=", 1)[1])]
    return None


def read_translate(body: list[str]):
    for ln in body:
        if ln.strip().startswith("double3 xformOp:translate"):
            return [float(v) for v in re.findall(NUM, ln.split("=", 1)[1])]
    return None


def snapshot(lines, blocks) -> dict:
    snap = {}
    for name, (a, b, typ) in blocks.items():
        body = lines[a:b]
        rec = {"type": typ}
        for k in ATTR:
            v = read_scalar(body, k)
            if v is not None:
                rec[k] = v
        c = read_color(body)
        if c:
            rec["color"] = c
        t = read_translate(body)
        if t:
            rec["translate"] = t
        snap[name] = rec
    return snap


def area_of(typ: str, geo: dict) -> float:
    """Emitting surface area in m^2, for the normalize=1 power convention."""
    if typ == "SphereLight":
        return 4.0 * math.pi * geo["radius"] ** 2
    if typ == "DiskLight":
        return math.pi * geo["radius"] ** 2
    if typ == "RectLight":
        return geo["width"] * geo["height"]
    raise ValueError(typ)


def fmt(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:.1f}"
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def resolve(name: str, typ: str, base: dict, dial: dict) -> dict:
    """Turn a photometric dial entry into concrete authored attribute values."""
    target = {k: base[k] for k in ATTR if k in base}
    for k in ("radius", "width", "height", "specular", "diffuse", "normalize"):
        if dial.get(k) is not None:
            target[k] = dial[k]

    g = GAIN * (COOL_TRIM if name in COOL_PRIMS else WARM_TRIM)
    if dial.get("intensity") is not None:
        target["intensity"] = dial["intensity"] * g
    elif dial.get("lux") is not None:
        target["intensity"] = dial["lux"] * g
    elif dial.get("lumens") is not None:
        target["intensity"] = dial["lumens"] * g / math.pi
    elif dial.get("nits") is not None:
        target["intensity"] = dial["nits"] * g * area_of(typ, target)
    elif dial.get("disc_nits") is not None:
        # A DistantLight authored by the RADIANCE OF ITS DISC rather than by the
        # irradiance it delivers. Primary-ray radiance = intensity / solid angle,
        # and the solid angle of a cone of full-width `disc_angle` is
        # pi * sin(angle/2)^2, so dividing by it makes the dial number the
        # number that lands on screen. Used for SunDisc, which is the visible sun
        # split off from the invisible key - see the note on that prim in
        # 60_lighting.usda. It rides GAIN like everything else so the sun tracks
        # the level's exposure instead of drifting off it.
        half = math.radians(dial.get("disc_angle", 1.2)) / 2.0
        target["intensity"] = dial["disc_nits"] * g * math.pi * math.sin(half) ** 2

    return target


def apply(lines: list[str], blocks: dict, base: dict, revert: bool) -> list[tuple[str, str]]:
    log: list[tuple[str, str]] = []
    for name, (a, b, typ) in blocks.items():
        if name not in base:
            continue
        bs = base[name]
        dial = {} if revert else DIALS.get(name, {})

        if dial:
            target = resolve(name, typ, bs, dial)
            color = list(dial["color"]) if dial.get("color") else (list(bs.get("color", [])) or None)
        else:
            target = {k: bs[k] for k in ATTR if k in bs}
            color = list(bs.get("color", [])) or None

        # NOTE: positions are STRUCTURE, not dials - _light_struct6.py owns
        # xformOp:translate, because the fourteen practicals that had to be
        # re-seated outside their housings must not be dragged back to the
        # revision-4 baseline by this script.
        for i in range(a, b):
            s = lines[i]
            st = s.strip()
            pad = s[: len(s) - len(s.lstrip())]
            for k, (pat, _) in ATTR.items():
                if st.startswith(pat) and k in target:
                    new = f"{pad}{pat} = {fmt(target[k])}\n"
                    if new != s:
                        log.append((name, f"{k} {st.split('=')[1].strip()} -> {fmt(target[k])}"))
                    lines[i] = new
            if st.startswith("color3f inputs:color") and color:
                new = f"{pad}color3f inputs:color = ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})\n"
                if new != s:
                    log.append((name, f"color -> {tuple(color)}"))
                lines[i] = new
    return log


def apply_emissive(lines: list[str], revert: bool) -> list[tuple[str, str]]:
    """Rewrite emissive_intensity / emissive_color on the module's own Materials."""
    log = []
    if revert:
        return log
    mats = parse_blocks(lines, {"Material"})
    for name, (a, b, _typ) in mats.items():
        spec = EMISSIVE.get(name)
        if not spec:
            continue
        # The three emissive materials are all warm (two sun-shaft cards and the
        # sodium lamp bowl), so they ride WARM_TRIM with the fixtures.
        val = spec["nits"] * GAIN * WARM_TRIM
        col = spec["color"]
        for i in range(a, b):
            s = lines[i]
            st = s.strip()
            pad = s[: len(s) - len(s.lstrip())]
            if st.startswith("float inputs:emissive_intensity"):
                new = f"{pad}float inputs:emissive_intensity = {val:.2f}\n"
                if new != s:
                    log.append((name, f"emissive_intensity {st.split('=')[1].strip()} -> {val:.2f}"))
                lines[i] = new
            elif st.startswith("color3f inputs:emissive_color") or \
                 st.startswith("color3f inputs:emissiveColor"):
                key = st.split()[1].split("=")[0]
                new = f"{pad}color3f {key} = ({col[0]:.4f}, {col[1]:.4f}, {col[2]:.4f})\n"
                if new != s:
                    log.append((name, f"{key} -> {col}"))
                lines[i] = new
    return log


def report(blocks: dict, base: dict) -> None:
    print(f"{'prim':26s} {'type':13s} {'authored':>14s} {'radiance(nits)':>15s}  spec")
    for name, (_a, _b, typ) in blocks.items():
        dial = DIALS.get(name)
        if not dial:
            print(f"{name:26s} {typ:13s} {'-- UNDIALLED --':>14s}")
            continue
        t = resolve(name, typ, base.get(name, {}), dial)
        if typ in AREA_TYPES:
            rad = t["intensity"] / area_of(typ, t) if t.get("normalize") else t["intensity"]
            note = f"{rad:15.1f}"
        elif typ == "DistantLight":
            note = f"{'(lux)':>15s}"
        else:
            note = f"{'(x texel)':>15s}"
        print(f"{name:26s} {typ:13s} {t['intensity']:14.1f} {note}  {t.get('specular')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--gain", type=float, default=None, help="override GAIN for this run")
    ap.add_argument("--set", action="append", default=[], metavar="PRIM:KEY=VALUE",
                    help="one-off dial override for a sweep, e.g. --set KeySun:lux=2600 "
                         "--set StormSky:intensity=3.1. Scalar keys only; it edits the "
                         "DIALS table in memory, so nothing here is a second code path. "
                         "Whatever a sweep settles on must then be written into DIALS.")
    a = ap.parse_args()

    for spec in a.set:
        prim, kv = spec.split(":", 1)
        key, val = kv.split("=", 1)
        if prim not in DIALS:
            raise SystemExit(f"--set: no dial named {prim!r}")
        UNITS = ("lumens", "nits", "lux", "intensity")
        if key in UNITS:
            for alt in UNITS:
                if alt != key:
                    DIALS[prim].pop(alt, None)
        DIALS[prim][key] = float(val)

    global GAIN
    if a.gain is not None:
        GAIN = a.gain

    text = USDA.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    blocks = parse_blocks(lines, LIGHT_TYPES)

    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    fresh = snapshot(lines, blocks)
    added = [n for n in fresh if n not in base]
    if added:
        base.update({n: fresh[n] for n in added})
        BASELINE.write_text(json.dumps(base, indent=1), encoding="utf-8")
        print(f"baseline: +{len(added)} new light(s) {added[:6]} -> {BASELINE.name}")

    # The baseline snapshot is revision 4 and predates the geometry changes in
    # this revision, so seed the resolver from the CURRENT authored geometry -
    # the dials override anything they set, and everything else must reflect
    # what is actually in the file.
    for n, rec in fresh.items():
        b = base.setdefault(n, {})
        for k in ("radius", "width", "height", "type"):
            if k in rec:
                b[k] = rec[k]

    missing = sorted(set(blocks) - set(DIALS))
    if missing:
        print(f"WARNING: {len(missing)} light prims have no dial: {missing}")

    if a.report:
        report(blocks, base)
        return

    log = apply(lines, blocks, base, a.revert)
    log += apply_emissive(lines, a.revert)
    print(f"GAIN={GAIN}  {len(blocks)} light prims, {len(log)} attribute changes")
    shown: dict[str, list] = {}
    for name, msg in log:
        shown.setdefault(re.sub(r"\d+", "#", name), []).append((name, msg))
    for grp, items in shown.items():
        print(f"  {grp}  ({len(items)})")
        for name, msg in items[:2]:
            print(f"      {name}: {msg}")

    if not a.dry:
        USDA.write_text("".join(lines), encoding="utf-8")
        print(f"wrote {USDA}")


if __name__ == "__main__":
    main()
