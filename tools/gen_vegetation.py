"""Regenerate usd/modules/40_vegetation.usda.

ROUND 6. THE MAP WAS IN THREE SEASONS AT ONCE, AND ALL THREE WERE THIS FILE'S.

The critic's three findings, and what each one actually was:

  1. "A pink-white BLOSSOMING ORNAMENTAL (cherry) mid-right in LANE_EYE_YARD."
     It is the Black Oak corner anchor at (68.4, -49.6), 112 m out, projected to
     px 1646 in that frame. It is not ornamental and it is not in blossom: its
     emitted `diffuse_tint` was (0.1196, 0.1243, 0.5554), a 4.6x blue boost, and
     its canopy pixels measured rgb (0.381, 0.381, 0.461) - blue dominant,
     luminance 0.387 against a sky of 0.315.

     THE CAUSE IS A COLOUR-SPACE ERROR. Round 5 measured each leaf texture's
     mean in *sRGB* and then solved a per-channel `target/albedo` ratio from
     those numbers to "desaturate" it. `diffuse_tint` multiplies LINEAR values.
     The oak's basecolor is sRGB (0.351, 0.449, 0.109) - blue looks like 24% of
     green - but linear it is (0.1018, 0.1703, 0.0123), blue is 7% of green. The
     solver divided into a number seven times smaller than it thought and asked
     for a 4.6x blue multiply. OmniPBR then applies `albedo_desaturation` BEFORE
     the tint, which lifts the leaf's near-zero blue up to the leaf's luminance
     first, and the multiply lands on that. Green leaf in, lilac out.

  2. "Pale ICE-BLUE CONIFERS fill SILHOUETTE_WEST." Two things, both the same
     bug. There were conifers - Yew and Juniper, sharing one pale `Pine_needles`
     atlas - and they are gone; nursery conifers do not colonise a derelict
     depot in this climate. But most of that mass is the WEST POPLAR BAND, the
     LAYOUT 5.19 Lombardy poplars, at effective albedo B/R 2.00-2.22. The
     "aerial perspective" tiers were stacking a cool per-channel bias on top of
     the broken ratio, so measured effective saturation ROSE with distance:
     0.29 near, 0.43 at 60-100 m, 0.59 past 100 m, exactly backwards.

  3. "DETAIL_WET_APRON is scattered with ORANGE AUTUMN OAK LEAVES." Literally
     true and not a grade problem: 1440 instances of the
     `Assets/Vegetation/Debris/` fall-drift family, whose one shared basecolor is
     a sheet of crisp intact autumn oak and beech leaves. The whole family is
     removed from the map.

What round 6 changed:

  A. LEAF_LIN / BARK_LIN are measured in LINEAR space, and the grade no longer
     solves a per-channel ratio at all. Saturation is carried by
     `albedo_desaturation`, which is luminance-preserving and monotone and
     therefore cannot invert a hue; level is carried by a scalar times a
     luminance-neutral hue lean that `_hue()` clamps, with a hard ceiling on
     blue because every foliage texture here is green-dominant with near-zero
     blue and that is the channel a divide blows up.

  B. The aerial tiers now do what aerial perspective does: remove saturation and
     remove value. Measured effective saturation by tier is now 0.385 / 0.264 /
     0.147 and no leaf grade anywhere in the map has B/R above 1.12.

  C. ONE SEASON, late-summer storm break, held everywhere. No blossom, no autumn
     colour, no *_Fall asset, no fall-leaf debris. Honey Locust is removed - half
     of its single leaf atlas is orange autumn foliage on a golden ground. The
     black oak's `oakleaves2` variant is a tan sheet and is desaturated hardest
     of its four so it reads as August drought-burn. Dry grass rises from 13% to
     30% of the ground mix, which is what an unwatered yard looks like in August
     and is now the map's warm ground accent instead of leaf drift.

  D. Species: Yew and Juniper out, Gray Birch in (2.67 x 2.56 x 3.33 m - a real
     self-seeded sapling and the classic colonist of derelict industrial land),
     plus low and half-dead wild privet variants to carry the LAYOUT 6.3 cover
     mass and the in-core height cap that the conifers used to.

  E. `grade_audit()` is a BUILD GATE, not a note. It recomputes what the
     renderer will actually see - linear texture mean, desaturated, times the
     emitted tint - and fails the build if any leaf is blue-dominant or if
     saturation rises with distance. Round 5's numbers looked fine in the source
     and were wrong in the shader; nothing but this check would have caught it.

ROUND 5. The grade is now stated as an ABSOLUTE ALBEDO, not a relative multiplier.

  A. Rounds 3-4 set foliage level with `v`, a multiplier on the library albedo,
     and never audited what absolute reflectance fell out. Measured afterwards:
     grass protos at 0.31-0.42 effective albedo luminance, trees at 0.17-0.32.
     Real foliage is 0.10-0.15 (fresh grass), 0.18-0.25 (dead straw), 0.12-0.18
     (deciduous canopy), and everything in this map is wet. A vegetation-only
     render of SILHOUETTE_WEST measured the canopy at median luminance 0.320
     against a sky of 0.326 - half the canopy brighter than the sky behind it,
     mean colour a warm cream (0.415, 0.352, 0.264). That is the "pale cream
     cone" read. `leaf(..., alb=X)` now names the target albedo and solves the
     tint for it; the tree grade carries a cool bias rather than a warm one; the
     aerial tiers scale the stated albedo and push cool to B/R 2.0 past 100 m.

  B. The featureless pale block in the DETAIL_WET_APRON foreground was this
     module's `rock_small_*`: tint 0.74, flat roughness, and its normal map
     clamped to 0.35. Regraded to a wet-granite 0.20 with the normal map at full
     strength, and bedded 38-62% of its height into the ground.

  C. Moss now exists. LAYOUT 7.4 asks for it in the drain by name; there was
     none anywhere. Damp edges carry 46-85 mm MossMat at 0.062 albedo.

  D. The bump/spec clamp is split: leaves stay clamped (they are the measured
     firefly source), debris gets its normal map back (a 190 mm stone 3 m from
     the lens is not sub-pixel). A leaf roughness floor of 0.95 was tried and
     REJECTED on measurement - it did nothing for the fireflies and pushed
     DETAIL_WET_APRON from 0.00034 to 0.00085.

ROUND 4. Read this too - it explains why round 3's work was invisible.

  0. THE GRADE WAS HALF DISCARDED. Round 3 authored its whole colour correction
     as `over "Looks" { over "<Material>" { over "Shader" { ... } } }`, assuming
     the shader prim inside every material is called "Shader". In six of these
     eighteen assets it is not - it is named after its own material
     (Looks/HollyPrivet_Mat/HollyPrivet_Mat), and `over` on a name that does not
     exist silently creates an empty prim. 14 of 43 override targets were
     no-ops. The six species that kept their nursery albedo were Blue_Berry_Elder,
     Switchgrass, Red_Ash, Honey_Locust, Hawthorn and Fraxinus - which is exactly
     why the 2.9 m elder cover mass 17 m from the SILHOUETTE_WEST eye was still
     rendering as full-saturation garden green, the only green object in a
     blue-and-amber frame, while the round-3 notes said it had been fixed.
     Shader prim paths are now RESOLVED from the assets (tools/_veg_shaders.json)
     and a target that cannot be resolved is a hard error, not a silent no-op.

  0b. THE TREES ARE NOT BILLBOARDS. Measured: Lombardy_Poplar is 429,469 points
     over 2 meshes, Blue_Berry_Elder 219,910, Red_Ash 64,375, Black_Oak 48,701.
     These are real branch and cross-plane leaf geometry, not camera-facing
     cards. The flat read was albedo and value, not the mesh.

  0c. THE FIREFLY GATE WAS MINE. Rendering LANE_EYE_YARD with and without this
     module sublayered in gave firefly_frac 0.01073 vs 0.00063 - 94% of every
     path-trace outlier in that frame came from vegetation. Cause: the library
     ships these materials at OmniPBR specular_level 0.5, bump_factor 0.5 and
     reflection_roughness_texture_influence 1.0 (so any authored roughness
     constant does nothing). Fixed at source per the BRIEF - see SPEC / BUMP.
     After the fix, adjacent with/without renders differ by <= 0.0002.

  0d. AERIAL PERSPECTIVE IS AUTHORED, not left to the haze. Every woody proto
     has _M (60-100 m) and _F (>100 m) twins that take more saturation out, drop
     the value and push the residue cool. Distances are measured to the nearest
     camera in 90_cameras.usda THAT IS ACTUALLY FACING THE PLANT, parsed at
     generation time so the grade follows the shot list.

Round-3 rewrite, still in force. The species/scale/rejection work from round 2
is kept; three things the critic caught were rebuilt from scratch:

  1. PROTOTYPE LIBRARY WITH AUTHORED TINT. Every plant in the map now resolves
     through a small library of `class` prims under /World/Vegetation/_Protos.
     Each proto references one library asset AND authors an `over` on that
     asset's OmniPBR leaf shader (albedo_desaturation / albedo_brightness /
     diffuse_tint / reflection_roughness). Measured leaf albedos before the
     override: lawngrass 0.367 sat, poplar leaf 0.472, red ash 0.406, hawthorn
     0.621, holly/privet 0.718, black oak 0.757 - fresh-nursery foliage, and in
     a derelict yard at storm dusk the most saturated thing in two frames. The
     protos pull that down 35-58% and darken 25-40%.
     The instances stay `instanceable = true` and reference the proto by
     internal path, so N instances of a proto still share ONE USD prototype -
     verified: two instances -> one /__Prototype_N. Class prims are abstract, so
     they are skipped by Hydra and by validate.py's traversal.
     Because one asset can appear as several protos with different tints, this
     is also what gives the tuft scatter more than one visual prototype: the
     library only contains ONE grass family (all six Grass_* assets share
     lawngrass_a_mat), so variety has to be authored, not chosen.

  2. TIER-1 EXTERIOR WEEDS ARE RE-SAMPLED AS A CLUSTER PROCESS, not re-species'd
     in place. The round-2 pass kept the old even-arc positions and only
     re-decided species, so the DETAIL_WET_APRON kerb still read as six tufts at
     equal intervals. Now: candidates are generated ON the authored edge network
     (10_terrain crack/seam/kerb/drain/puddle geometry + the analytic footprints
     of 20_architecture) WITH the local edge direction; parents are chosen by a
     variable-radius Poisson process (1.4-7.0 m) so the gaps are as varied as
     the clumps; each parent spawns 1-5 children offset along the edge; a clump
     is mostly one proto (growth is clonal) with 28% mixing; scale jitters
     0.62-1.42x; the tuft ellipse is elongated 1.15-1.45x along the crack it
     roots in. Roughly a quarter of clumps also drop leaf litter or a half-buried
     stone at the same spot, so an edge reads as accumulated silt + leaf + weed
     rather than a row of green balls.

  3. THE TREE LINES ARE REBUILT AS BROKEN, MIXED, MULTI-TIER BANDS.
     Round 2 left 12 green + 11 orange Lombardy poplars alternating at a 9 m
     pitch on a single Y line, plus one green and one orange Black Oak - a comb
     of same-size lollipops in two saturated hues, in the one shot briefed
     around silhouette. Now: one seasonal state (all *_Fall variants deleted -
     a row of one species is not half green and half orange), heights spread
     +/-26% instead of +/-8%, poplars clumped 2-5 at a time with 9-26 m gaps,
     Y spread over a 7 m band instead of a line so the row overlaps itself in
     depth, two clumps built from red ash / hawthorn / fraxinus instead of
     poplar so the profile changes along the row, and 2-4 elder / elm / privet
     scrub at the foot of every clump so trunks emerge from a mass instead of
     standing on bare ground. Largetooth Aspen was measured at 0.997 leaf
     saturation and is not used at all.

Scale policy unchanged: every referencing prim keeps xformOp:scale inside the
0.005..0.02 band validate.py checks; smaller plants come from a smaller ASSET,
never from shrinking a big one.

    cd tools && uv run gen_vegetation.py
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from pathlib import Path

import numpy as np
from pxr import Sdf, Usd, UsdGeom

ROOT = Path(__file__).resolve().parent.parent
VEG = ROOT / "usd" / "modules" / "40_vegetation.usda"
TERRAIN = ROOT / "usd" / "modules" / "10_terrain.usda"
S3 = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"

rng = random.Random(20260809)

# --- measured native sizes, metres, at xformOp:scale = 0.01 -----------------
NATIVE = {
    "Grass_Trimmed_C": (0.239, 0.258, 0.087),
    "Grass_Short_C":   (0.279, 0.304, 0.125),
    "Grass_Trimmed_B": (0.618, 0.635, 0.098),
    "Grass_Short_B":   (0.661, 0.675, 0.164),
    "Grass_Trimmed_A": (1.240, 1.243, 0.113),
    "Grass_Short_A":   (1.289, 1.294, 0.162),
    "Switchgrass":     (2.009, 2.027, 1.372),
    "Privet":          (1.704, 1.638, 1.113),
    "Elm_Sapling":     (1.742, 1.750, 3.087),
    "Gray_Birch":      (2.672, 2.563, 3.332),
    "Blue_Berry_Elder": (4.086, 3.800, 4.627),
    "Lombardy_Poplar": (4.838, 4.491, 13.671),
    "Red_Ash":         (5.733, 6.056, 8.435),
    "Hawthorn":        (9.473, 7.202, 8.611),
    "Fraxinus":        (4.851, 4.510, 5.341),
    "Black_Oak":       (25.424, 24.067, 19.739),
}

ASSET_PATH = {
    "Grass_Trimmed_A": "Assets/Vegetation/Shrub/Grass_Trimmed_A.usd",
    "Grass_Trimmed_B": "Assets/Vegetation/Shrub/Grass_Trimmed_B.usd",
    "Grass_Trimmed_C": "Assets/Vegetation/Shrub/Grass_Trimmed_C.usd",
    "Grass_Short_A": "Assets/Vegetation/Shrub/Grass_Short_A.usd",
    "Grass_Short_B": "Assets/Vegetation/Shrub/Grass_Short_B.usd",
    "Grass_Short_C": "Assets/Vegetation/Shrub/Grass_Short_C.usd",
    "Switchgrass": "Assets/Vegetation/Shrub/Switchgrass.usd",
    "Privet": "Assets/Vegetation/Shrub/Privet.usd",
    "Elm_Sapling": "Assets/Vegetation/Trees/Elm_Sapling.usd",
    "Gray_Birch": "Assets/Vegetation/Trees/Gray_Birch.usd",
    "Blue_Berry_Elder": "Assets/Vegetation/Trees/Blue_Berry_Elder.usd",
    "Lombardy_Poplar": "Assets/Vegetation/Trees/Lombardy_Poplar.usd",
    "Red_Ash": "Assets/Vegetation/Trees/Red_Ash.usd",
    "Hawthorn": "Assets/Vegetation/Trees/Hawthorn.usd",
    "Fraxinus": "Assets/Vegetation/Trees/Fraxinus.usd",
    "Black_Oak": "Assets/Vegetation/Trees/Black_Oak.usd",
}

# ROUND 6 -- the whole autumn-litter family is GONE from the map. See the
# season note at the top of this file: `Assets/Vegetation/Debris/` contains
# nothing but fall drifts (fallcluster1/2, oakfall1/2, maplefall1), all five
# bound to one material whose basecolor is a sheet of crisp intact ORANGE oak
# and beech leaves, measured linear mean (0.404, 0.252, 0.132). 1440 of them
# were dressed across the yard, the kerbs and the DETAIL_WET_APRON foreground.
# Crisp orange leaf drift is a statement that it is October; the level is a
# late-summer storm break. No grade turns an intact autumn oak leaf into
# something else, so the asset family is not used at all. What actually
# accumulates on the lee of a wall in August is silt and grit, so those
# positions now carry half-buried stone.
# The five names are still needed to RECOGNISE them in tools/_veg_seed.json -
# the seed is the frozen record of 1509 authored drift positions and 1440 of
# them name a fall asset. The positions get reused; the assets do not appear in
# ASSET_PATH, in ALL_ASSETS, in the prototype library or in the emitted layer.
LEGACY_LITTER = {"fallcluster1", "fallcluster2", "oakfall1", "oakfall2",
                 "maplefall1"}
ROCKS = {f"rock_small_{i:02d}" for i in range(1, 11)}

DEBRIS_PATH = {a: f"Assets/Vegetation/Rocks/{a}.usda" for a in ROCKS}
ALL_ASSETS = {**ASSET_PATH, **DEBRIS_PATH}


# ---------------------------------------------------------------------------
# PROTOTYPE LIBRARY
# ---------------------------------------------------------------------------
# ===========================================================================
# ROUND 6 -- THE ALBEDO TABLE IS NOW LINEAR, AND THAT IS THE WHOLE BUG
# ===========================================================================
# Round 5 measured each material's diffuse_texture and stored the mean of its
# *sRGB* texels, then solved a per-channel `target/albedo` ratio from those
# numbers and wrote the result into `diffuse_tint`. But diffuse_tint multiplies
# the texture AFTER the sRGB decode, i.e. it multiplies LINEAR values. sRGB 0.109
# is linear 0.0106. So on the black oak the solver believed blue was 24% of
# green and computed a 4.6x blue boost to "desaturate" it; the renderer was
# actually looking at a leaf whose blue is 7% of green. Result, measured on the
# emitted layer: TreeOak_M diffuse_tint = (0.1196, 0.1243, 0.5554).
#
# That single number is the "pink-white blossoming cherry" the critic found
# mid-right in LANE_EYE_YARD. It is the Black Oak corner anchor at (68.4,-49.6),
# 112 m out, and its canopy pixels measure rgb (0.381, 0.381, 0.461) - blue
# dominant, luminance 0.387 against a sky of 0.315. A green oak lit by a 5.5 deg
# sun cannot do that; a 4.6x blue multiply can.
#
# The same arithmetic run over every prototype (see the table printed by the
# audit) showed the effective albedo of EVERY distance-tiered woody proto had
# B/R between 1.3 and 2.4, and saturation RISING with distance - 0.29 near,
# 0.59 at the far tier. That is the "pale ice-blue conifers" filling
# SILHOUETTE_WEST: they are not conifers at all, they are the Lombardy poplars
# of the west band (LAYOUT 5.19) with B/R 2.0-2.2 and their chroma pushed UP by
# the very "aerial perspective" that was supposed to take it out.
#
# So: the table below is the mean of the sRGB-DECODED (linear) texels of each
# material's diffuse_texture, and the grade no longer solves a per-channel
# ratio at all. See `leaf()`.
LEAF_LIN = {
    "lawngrass_a_mat":            (0.3765, 0.3202, 0.1681),
    "Switchgrass_Mat":            (0.0849, 0.2606, 0.0590),
    "HollyPrivet_Mat":            (0.0441, 0.0797, 0.0202),
    "Gray_Birch_Leaves_Mat":      (0.0441, 0.0797, 0.0202),   # same atlas
    "American_Beech_leaf":        (0.0484, 0.0901, 0.0460),
    "LombardyPoplar_leaf_Mat_2":  (0.0833, 0.1408, 0.0433),
    "RedAsh_leaf_mat":            (0.1300, 0.2450, 0.0841),
    "Hawthorn_leaf_Mat":          (0.0449, 0.1196, 0.0186),
    "Hawthorn_leaf_v2_Mat":       (0.1233, 0.1807, 0.0175),
    "Hawthorn_leaf_v3_Mat":       (0.1889, 0.2676, 0.0747),
    "Hawthorn_leaf_v4_Mat":       (0.1157, 0.2260, 0.0978),
    "Fraxinus_leaves":            (0.0728, 0.1382, 0.0543),
    "Shumard_Oak_leaf_Mat2":      (0.1018, 0.1703, 0.0123),
    "Shumard_Oak_leaf_v2_Mat2":   (0.1544, 0.1287, 0.0325),   # the tan variant
    "Shumard_Oak_leaf_v3_Mat2":   (0.1034, 0.1544, 0.0363),
    "Shumard_Oak_leaf_v4_Mat2":   (0.1085, 0.1431, 0.0555),
}
# Round 5 gave all four black-oak leaf materials and all four hawthorn leaf
# materials ONE albedo, because it never opened oakleaves2/3/4 or
# hawthorn_leaf_v2/3/4. They are four different textures each, and
# oakleaves2_basecolor is a TAN/BROWN leaf sheet - a partial autumn atlas inside
# a green tree. It is still used (a mature oak in a drought August genuinely
# carries some browning leaves) but it is graded to the same low chroma as the
# rest so it reads as dry, not as October.

BARK_LIN = {
    "bark3":              (0.1113, 0.0916, 0.0701),
    "tree_bark_03_2k":    (0.2876, 0.2558, 0.1570),
    "RedAsh_bark_Mat":    (0.2876, 0.2558, 0.1570),
    "Hawthorn_bark_Mat":  (0.1890, 0.1259, 0.0467),
    "Apple_bark_Mat":     (0.1373, 0.0979, 0.0626),
    "Apple_bark_Mat_2":   (0.1373, 0.0979, 0.0626),
    "TreeBark_7":         (0.1183, 0.1102, 0.1134),
    "Gray_Birch_Bark_Mat": (0.3118, 0.3067, 0.2948),
}


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


# A hue lean tilts the residue; it must not be able to restate the colour.
# The two guards are asymmetric on purpose, because the danger is asymmetric.
# Every foliage texture in this library is green-dominant with very little blue -
# the black oak's linear mean is (0.102, 0.170, 0.012), i.e. blue is 7% of green.
# So a WARM lean only ever exaggerates something the texture already has, while
# a COOL lean is dividing into near-zero and is the direction that turned a green
# oak lilac. Hence: generous total spread, hard ceiling on blue.
HUE_SPREAD_MAX = 2.20      # max/min channel ratio of the lean
HUE_BLUE_MAX = 1.15        # blue may never exceed this x the smaller of R and G


def _hue(h):
    """Normalise a hue lean so it changes only chroma, never level, and clamp it.

    Three properties, all enforced here rather than trusted:
      1. blue is capped relative to the other two channels. This is the guard
         that would have caught round 5: its far-tier poplar lean was effectively
         B/R 2.15, and the emitted black-oak tint was B/R 4.64.
      2. bounded total spread, compressed in LOG space so the ratios between
         channels shrink proportionally instead of collapsing to the midpoint.
      3. luminance-neutral - `_lum(h) == 1` - so `alb` lands exactly on the
         stated reflectance whatever hue is asked for.
    """
    h = list(h)
    h[2] = min(h[2], HUE_BLUE_MAX * min(h[0], h[1]))
    lo, hi = min(h), max(h)
    if hi / max(lo, 1e-6) > HUE_SPREAD_MAX:
        g = math.sqrt(lo * hi)
        f = math.log(HUE_SPREAD_MAX) / math.log(hi / max(lo, 1e-6))
        h = [g * (c / g) ** f for c in h]
    s = _lum(h)
    return tuple(c / s for c in h)


def leaf(mat, alb, desat=0.45, hue=(1.0, 1.0, 1.0), rough=0.82, bump=None,
         spec=None):
    """Grade one leaf material to a stated LINEAR albedo, without touching hue.

    ROUND 6. The level and the saturation are now carried by two operators that
    cannot fight each other, and neither of them can invert a colour:

      * `albedo_desaturation` (0..1) is the SATURATION lever. In OmniPBR it
        lerps the decoded basecolor toward its own luminance, per texel. It is
        luminance-preserving and it is monotone, so it can flatten a leaf toward
        neutral but it can never make a green leaf blue. Round 5 pinned it at
        0.30 for everything and did the desaturation with a per-channel tint
        ratio instead, which is exactly the operator that CAN invert a hue.
      * `diffuse_tint` is the LEVEL lever: a single scalar `v`, times a
        luminance-neutral hue lean that `_hue()` clamps.

    Because desaturation preserves luminance, `v` solves exactly:
        v = alb / luminance(linear texture mean)
    so `alb` is an absolute broadband reflectance that can be checked against a
    table, and it means the same thing for every material regardless of how
    bright that material's atlas happens to be. That last point matters: the
    four black-oak leaf textures span luminance 0.116-0.144 and the four
    hawthorn ones 0.096-0.243, and round 5 handed all four of each the same
    tint, so one leaf variant per tree was 2.5x the others.

    ONE SEASON. Every `hue` in this file is late-summer: green going dry. Live
    foliage leans a hair olive, drought-burnt foliage leans straw. Nothing leans
    far enough cool to read blue and nothing leans warm enough to read autumn.
    """
    a = LEAF_LIN[mat]
    L = _lum(a)
    desat = min(max(desat, 0.0), 0.92)
    h = _hue(hue)
    v = alb / max(L, 1e-6)
    tint = tuple(round(v * c, 4) for c in h)
    return {"desat": round(desat, 3), "bright": 1.0, "tint": tint,
            "rough": max(rough, LEAF_ROUGH),
            "bump": BUMP_LEAF if bump is None else bump,
            "spec": SPEC if spec is None else spec,
            "_leaf": (mat, alb, desat, hue), "_alb": alb}


def bark(mat, alb=0.030, desat=0.40, hue=(1.02, 1.00, 0.96), rough=0.88,
         bump=None, spec=None):
    """Same contract as `leaf()`, against the measured linear bark albedo.

    ROUND 6: bark is graded to a stated reflectance too, instead of a bare
    multiplier that meant something different on every species - `bark(0.30)` was
    landing on effective albedos from 0.021 (bark3) to 0.093 (the white birch),
    a 4.5x spread nobody chose. The lean is now very slightly WARM: round 5 put a
    blue-over-red bias on every trunk in the map, which is half of why the west
    band read as ice.

    The bump stays on the LEAF clamp, and that is a measured decision. Bark was
    tried at full normal strength on the grounds that a trunk is metres of real
    relief; the frozen A/B said otherwise - firefly_frac on LANE_EYE_YARD went
    0.00013 (no vegetation) -> 0.00134 (vegetation), and SILHOUETTE_WEST 0.00016
    -> 0.00114. Almost every piece of bark in this map is a 60-130 m BRANCH two
    or three pixels wide, which is the same sub-pixel normal-map noise the clamp
    exists for. Only the debris - a 190 mm stone metres from a lens - is large
    enough in frame to earn its normal map back."""
    a = BARK_LIN[mat]
    L = _lum(a)
    desat = min(max(desat, 0.0), 0.92)
    h = _hue(hue)
    v = alb / max(L, 1e-6)
    return {"desat": round(desat, 3), "bright": 1.0,
            "tint": tuple(round(v * c, 4) for c in h),
            "rough": rough,
            "bump": BUMP_LEAF if bump is None else bump,
            "spec": SPEC if spec is None else spec,
            "_bark": (mat, alb, desat, hue), "_alb": alb}


# --- the firefly gate -------------------------------------------------------
# MEASURED, not guessed. Rendering LANE_EYE_YARD twice - once with this module
# in the stage and once with it sublayered out - gave firefly_frac 0.01073 with
# vegetation and 0.00063 without, i.e. 94% of every firefly in that frame was
# mine. HERO_ESTABLISH and DETAIL_WET_APRON behaved the same way. The map of
# where the outliers land is the whole lower half of frame, the ground plane -
# so it is the tuft scatter, not the trees.
#
# The cause is what these library materials ship with: OmniPBR at
# specular_level 0.5, reflection_roughness_texture_influence 1.0 (so the
# authored roughness constant does nothing at all) and bump_factor 0.5. A grass
# blade a couple of pixels wide, with a normal map running at full strength and
# a glossy lobe on top, produces exactly the isolated single-pixel highlights
# the gate measures. The BRIEF is explicit that the fix is to remove the
# variance at source rather than lean on the denoiser, so:
#   - specular_level down to a near-matte value. Wet foliage is glossy, but not
#     glossy enough to be worth a hard gate failure across three shots.
#   - roughness_texture_influence 0, so the roughness constant actually applies.
#   - bump_factor down: at 40-90 m a leaf normal map is pure sub-pixel noise.
#   - metallic_constant pinned to 0 in case an asset ships otherwise.
#
# ROUND 5 splits the bump clamp in two, because one number was paying for two
# very different problems. The measured firefly source was a GRASS BLADE two or
# three pixels wide with a normal map at full strength; a 0.19 m stone 3 m from
# the DETAIL_WET_APRON lens, or 4 m of wet poplar trunk, is nothing of the kind -
# it is hundreds of pixels of real relief, and flattening its normal map to 0.35
# is a large part of why the foreground stone in that shot reads as a featureless
# cream blob. Leaves keep the clamp; solids get their normal map back.
SPEC = 0.03
BUMP_LEAF = 0.18
BUMP_SOLID = 1.00
# Foliage roughness floor - MEASURED AND REJECTED, kept at 0 so the per-proto
# roughness stands. The theory was that a tight specular lobe on a two-pixel
# blade is the firefly, so widening the lobe to 0.95 should kill it while keeping
# the wet sheen. On the frozen A/B it did nothing for the fireflies it was aimed
# at (LANE_EYE_YARD was already clean at spec 0.03 / bump 0.18: 0.00010 with the
# floor, 0.00009 without; SILHOUETTE_WEST 0.00111 vs 0.00112) and it made
# DETAIL_WET_APRON strictly worse - 0.00034 -> 0.00085, straight through the
# gate. A very broad lobe is not cheap to converge; it scatters over the whole
# hemisphere and 2048 spp does not finish it. Lowering specular_level is the
# lever that works; widening roughness is the lever that looks like it should.
LEAF_ROUGH = 0.0


# --- aerial perspective -----------------------------------------------------
# A tree 130 m away is not the same colour as one at 20 m, and no amount of
# volumetric haze fixes a canopy whose ALBEDO is a 20 m albedo. The far tiers
# take more saturation out, drop the value, and push the residue cool so the
# band sits BEHIND the haze instead of glowing through it as a pale smear.
#
# ROUND 6 -- THE TIERS WERE RUNNING BACKWARDS. Aerial perspective takes chroma
# OUT of a distant object; the round-5 tiers put chroma IN. Measured over the
# whole prototype library (the audit prints this table now), effective albedo
# saturation went 0.29 near -> 0.43 at 60-100 m -> 0.59 past 100 m, and B/R went
# 1.1 -> 1.7 -> 2.2. The far tier was not hazing the band, it was PAINTING IT
# CYAN, which is what the critic saw as "pale ice-blue conifers" in
# SILHOUETTE_WEST - they are Lombardy poplars.
#
# The cause was mechanical: the "cool bias" was a per-channel multiply stacked on
# top of a per-channel desaturation ratio that was already wrong (see LEAF_LIN),
# and it compounded with distance. Now the tier does the two things aerial
# perspective actually does and nothing else - it removes saturation and it
# removes value - with only a whisper of cool left in, well inside the clamp:
#   (extra desaturation, albedo multiplier, hue lean)
#
# The magnitudes below were set by rendering the west band, not by taste. The
# first round-6 pass used (0.17, 0.82) and (0.32, 0.66): that killed the ice
# blue - measured B/R fell from 2.00-2.22 to 0.99-1.10 - but desaturating the
# far tier that hard left the leaves a near-neutral grey, and a near-neutral
# grey leaf backlit by a blue-cyan storm dome picks the dome's colour straight
# up and reads as pale mint frost. Judged at 2x in SILHOUETTE_WEST that is a
# different wrong answer to the same question. So the far tier now takes LESS
# chroma out and MORE value out: what makes a 120 m treeline read as distance is
# that it is dark, and it has to stay recognisably foliage while it does.
#
# THIRD PASS, AND THE COOL LEAN IS NOW GONE ENTIRELY. A vegetation-only probe
# (_probe/veg_only.usda - cameras + lighting + materials + vegetation + terrain,
# nothing else) was rendered so the band could be judged without the haze layer
# and the buildings in front of it. On that frame the west poplars measured
# rendered rgb (0.191, 0.289, 0.350), B/R 1.83, while the authored leaf ALBEDO
# is B/R 0.76-1.02. So the blue in those pixels is not albedo any more - it is
# the dome. Those trees are backlit at 5.5 deg; the only light reaching the face
# we see is the blue storm sky, and it paints them.
#
# Which means a cool albedo lean was double-counting: the atmosphere's cool is
# already delivered by the dome, and by 80_fx's haze on top of that. The tier
# lean is therefore very slightly WARM now - just enough to sit against the dome
# - and the value drop does the distance work on its own. That is also the only
# lever this module has that does not fight the lighting module for the same
# job.
HAZE_TIERS = {
    "":   (0.00, 1.00, (1.000, 1.000, 1.000)),        # < 60 m, as authored
    "_M": (0.22, 0.70, (1.018, 1.000, 0.965)),        # 60 - 100 m
    "_F": (0.36, 0.50, (1.030, 1.000, 0.945)),        # > 100 m
}


def hazed(mats, tier):
    """Re-solve a proto's material grade for a distance tier.

    Both `alb` and `desat` are absolute, so a tier restates them rather than
    multiplying a multiplier: a far-tier leaf is a STATED reflectance at a
    STATED saturation, and the emitted numbers can be read straight off the
    layer and checked."""
    dd, vmul, cool = HAZE_TIERS[tier]
    out = {}
    for mat, m in mats.items():
        if "_leaf" in m:
            src, alb, desat, hue = m["_leaf"]
            out[mat] = leaf(src, alb * vmul, desat=desat + dd,
                            hue=tuple(w * c for w, c in zip(hue, cool)),
                            rough=m["rough"], bump=m["bump"], spec=m["spec"])
        else:
            src, alb, desat, hue = m["_bark"]
            out[mat] = bark(src, alb * vmul, desat=desat + dd,
                            hue=tuple(w * c for w, c in zip(hue, cool)),
                            rough=m["rough"], bump=m["bump"], spec=m["spec"])
    return out


GRASS = "lawngrass_a_mat"

# ---------------------------------------------------------------------------
# ONE SEASON: LATE-SUMMER STORM BREAK. Every hue lean in this file comes from
# this list and nothing else. There is no spring hue and no autumn hue anywhere
# in the module, because the level cannot be in two seasons at once and it was:
# a blossoming ornamental in LANE_EYE_YARD, autumn leaf drift in
# DETAIL_WET_APRON. Live growth in a rain-soaked August yard is a dull olive
# green; the exposed stuff on the slab and the drain lips is drought-burnt to
# straw; the wet shaded ground carries moss. That is the entire palette.
# _hue() clamps all of these to a max/min channel ratio of 1.34 and renormalises
# them to luminance 1, so a lean can tilt the residue but can never restate the
# colour - which is the failure mode that produced a lilac oak.
H_LIVE  = (1.00, 1.00, 0.94)      # dull olive green, the default
H_SHADE = (0.97, 1.00, 1.00)      # in shade at a wall foot: neutral, no lean
H_DRY   = (1.24, 1.02, 0.72)      # drought-burnt straw
H_DYING = (1.16, 1.02, 0.80)      # dying back: brown-grey, not orange
# A straw or dying prototype must ALSO carry a high `desat` (0.74-0.80), and
# that is not a stylistic choice. A lean is a per-channel multiply, so it can
# only exaggerate what the texture already contains; the grass and privet
# atlases have green at 1.5-1.8x their red, and no lean inside the clamp can
# turn that into straw. Desaturating to near-neutral FIRST and then leaning warm
# does turn it into straw, and it cannot invert anything because the base it
# leans is already grey. Round 6 first authored these at desat 0.26 and the
# audit caught them landing on a yellow-green, not a straw brown.
H_MOSS  = (0.92, 1.04, 0.96)      # wet moss: the one genuinely green thing
H_OLIVE = (1.06, 1.02, 0.86)      # the drying margin of a moss patch

# TARGET ALBEDOS (`alb`), LINEAR broadband reflectance luminance.
# These are the standard reflectance ranges pulled down ~25% because every
# surface in this map is wet, and then held at the levels round 5 measured as
# sitting BELOW the storm sky in SILHOUETTE_WEST - that part of round 5 was
# right and is deliberately not disturbed. What changed is that they are now
# LINEAR numbers landed exactly (desaturation is luminance-preserving, so
# v = alb / luminance(texture) is exact), rather than sRGB numbers landed
# through a per-channel ratio that also rewrote the hue.
#   fresh green grass  0.10-0.15 dry -> 0.033-0.044 wet
#   dead straw         0.18-0.25 dry -> 0.060-0.064 wet
#   moss / deep shade  0.06-0.09 dry -> 0.012-0.021 wet
#   deciduous canopy   0.12-0.18 dry -> 0.021-0.038 wet, and it is backlit
#
# GROUND WEEDS, MEASURED ON THE VEGETATION-ONLY PROBE AND CORRECTED TWICE.
# Judged at 2x in the LANE_EYE_YARD probe, the kerb tufts were reading as pale
# mint-white spiky clumps - frosted, not grassy - at rendered median luminance
# 0.585 against sunlit ground at 0.446, i.e. BRIGHTER than the ground they sit
# on. Two separate causes, and only one of them was a bug:
#   * NOT A BUG: a grass blade is VERTICAL and the sun is at 5.5 deg elevation.
#     A vertical face aimed at that sun collects ~cos(5 deg) of its irradiance;
#     the horizontal ground collects sin(5.5 deg) = 0.096 of it. A blade is
#     legitimately about ten times better lit than the tarmac beside it, and no
#     albedo number should be used to "fix" that - it is the shot's whole
#     lighting premise.
#   * A BUG: the tufts were near-NEUTRAL (rendered B/R 0.98) because the grass
#     atlas region the blades actually sample is pale cream stem, and round 6
#     was then desaturating it another 42-58%. Desaturation was doing a job here
#     that it did not need to do - this material is not the over-saturated one -
#     and the result was that the one thing in frame with no hue at all was the
#     vegetation. Live grass and moss now keep most of their own colour
#     (desat 0.24-0.44) and the level comes down ~20% instead. The DRY protos
#     keep their high desaturation: they need a neutral base for the straw lean
#     to land on, as explained at H_DRY.
PROTOS: dict[str, dict] = {
    # ---- tier 1: crack / seam tufts -------------------------------------
    "TuftFine": dict(
        asset="Grass_Trimmed_C", h=(0.09, 0.16),
        mats={GRASS: leaf(GRASS, 0.042, desat=0.26, hue=H_LIVE, rough=0.72)},
        doc="Fine short bristle in a hairline seam. Dull olive."),
    "TuftFineDry": dict(
        asset="Grass_Trimmed_C", h=(0.10, 0.18),
        mats={GRASS: leaf(GRASS, 0.060, desat=0.74, hue=H_DRY, rough=0.84)},
        doc="Same asset, burnt off: straw-coloured dead bristle. Late summer "
            "in an unwatered yard is half dead grass, so this is a seasonal "
            "anchor of the ground layer, not an exception to it."),
    "TuftSparse": dict(
        asset="Grass_Short_C", h=(0.12, 0.22),
        mats={GRASS: leaf(GRASS, 0.044, desat=0.24, hue=H_LIVE, rough=0.70)},
        doc="Open sparse tuft, taller blades, the standard kerb weed."),
    "TuftSparseDry": dict(
        asset="Grass_Short_C", h=(0.11, 0.20),
        mats={GRASS: leaf(GRASS, 0.064, desat=0.76, hue=H_DRY, rough=0.84)},
        doc="Bleached dead tuft. Goes on drain lips and dry slab, never on a "
            "puddle margin."),
    "MatBroadDark": dict(
        asset="Grass_Trimmed_A", h=(0.07, 0.12),
        mats={GRASS: leaf(GRASS, 0.033, desat=0.34, hue=H_SHADE, rough=0.68)},
        doc="0.9-1.1 m spreading mat only 70-120 mm tall - a totally different "
            "silhouette from a tuft ball. Dark, sits in shade at wall feet."),
    "MatWide": dict(
        asset="Grass_Short_A", h=(0.09, 0.15),
        mats={GRASS: leaf(GRASS, 0.038, desat=0.28, hue=H_LIVE, rough=0.68)},
        doc="Wide low mat for damp ground at puddle margins. Damp ground is "
            "darker ground, so it grades under the dry-seam tufts."),
    "TuftMid": dict(
        asset="Grass_Trimmed_B", h=(0.10, 0.19),
        mats={GRASS: leaf(GRASS, 0.042, desat=0.26, hue=H_LIVE, rough=0.70)},
        doc="Mid-size dense tuft."),
    "TuftMidDark": dict(
        asset="Grass_Short_B", h=(0.14, 0.26),
        mats={GRASS: leaf(GRASS, 0.034, desat=0.34, hue=H_SHADE, rough=0.66)},
        doc="The tallest thing allowed in tier 1 and the darkest. Gives a clump "
            "a value break instead of a size break."),
    "MossMat": dict(
        asset="Grass_Trimmed_C", h=(0.046, 0.085),
        mats={GRASS: leaf(GRASS, 0.019, desat=0.36, hue=H_MOSS, rough=0.62)},
        doc="Moss. 46-85 mm of flat, dark, blue-green growth for the shaded "
            "side of a drain channel, a kerb foot and a puddle rim. LAYOUT 7.4 "
            "asks for moss in the DETAIL_WET_APRON drain by name. At 3 m from "
            "the detail lens 40 mm of it is real high-frequency surface rather "
            "than another tuft ball."),
    "MossDark": dict(
        asset="Grass_Trimmed_C", h=(0.040, 0.072),
        mats={GRASS: leaf(GRASS, 0.012, desat=0.40, hue=H_MOSS, rough=0.60)},
        doc="The wet heart of a moss patch - nearly black-green. Moss authored "
            "at ONE value reads as green paint splodges; three values give a "
            "patch an interior and an edge."),
    "MossOlive": dict(
        asset="Grass_Short_C", h=(0.048, 0.090),
        mats={GRASS: leaf(GRASS, 0.021, desat=0.44, hue=H_OLIVE, rough=0.66)},
        doc="The drying margin of a moss patch: olive, slightly yellow, a taller "
            "and looser blade than the mat. ROUND 6 took most of the chroma out "
            "of this one - judged at 3x in DETAIL_WET_APRON it was reading as "
            "acid-yellow paint splodges along the kerb, which is the same "
            "over-saturation failure as the tree band, 3 m from the lens "
            "instead of 120."),

    # ---- tier 1 interior ingress ----------------------------------------
    "IngressFine": dict(
        asset="Grass_Trimmed_C", h=(0.07, 0.13),
        mats={GRASS: leaf(GRASS, 0.030, desat=0.34, hue=H_SHADE, rough=0.72)},
        doc="Interior slab-joint ingress. Darker again - it grows in a "
            "warehouse, out of the sun."),
    "IngressSparse": dict(
        asset="Grass_Short_C", h=(0.08, 0.15),
        mats={GRASS: leaf(GRASS, 0.032, desat=0.32, hue=H_SHADE, rough=0.72)},
        doc="Interior ingress at a water fan or door threshold."),
    "IngressDry": dict(
        asset="Grass_Short_C", h=(0.07, 0.14),
        mats={GRASS: leaf(GRASS, 0.050, desat=0.74, hue=H_DRY, rough=0.84)},
        doc="Dead, dried-out ingress on the warm side of a roller door. ROUND 6 "
            "added this to take over the slots that used to be blown-in AUTUMN "
            "LEAF LITTER: what blows through an open door in August is dead "
            "grass and chaff, not oak leaves in fall colour."),

    # ---- tier 2: rank weeds, out-of-bounds ground only -------------------
    "RankSwitch": dict(
        asset="Switchgrass", h=(0.62, 0.92),
        mats={"Switchgrass_Mat": leaf("Switchgrass_Mat", 0.034, desat=0.30,
                                      hue=H_LIVE, rough=0.84)},
        doc="Rank grass on ground nothing drives on."),
    "RankSwitchDry": dict(
        asset="Switchgrass", h=(0.55, 0.88),
        mats={"Switchgrass_Mat": leaf("Switchgrass_Mat", 0.048, desat=0.78,
                                      hue=H_DRY, rough=0.86)},
        doc="Last year's growth, standing and dead."),
    "RankMatA": dict(
        asset="Grass_Short_A", h=(0.16, 0.28),
        mats={GRASS: leaf(GRASS, 0.042, desat=0.26, hue=H_LIVE, rough=0.68)},
        doc="Broad rank mat."),
    "RankMatB": dict(
        asset="Grass_Trimmed_A", h=(0.12, 0.20),
        mats={GRASS: leaf(GRASS, 0.038, desat=0.30, hue=H_LIVE, rough=0.68)},
        doc="Flatter rank mat, darker."),
    "RankTuft": dict(
        asset="Grass_Short_B", h=(0.18, 0.30),
        mats={GRASS: leaf(GRASS, 0.040, desat=0.26, hue=H_LIVE, rough=0.68)},
        doc="Rank tuft."),

    # ---- tier 3: woody scrub, dead ground only ---------------------------
    # ROUND 6 SPECIES CHANGE. Yew and Juniper are GONE. Both bound the same
    # `Pine_needles` atlas, and a pair of pale needle mounds is what the critic
    # read as "ice-blue conifers" together with the poplars. They are also
    # simply wrong: a derelict depot in a cold northern maritime climate is
    # colonised by elm, elder, birch, willow, buddleia and bramble, not by
    # nursery conifers. Gray Birch replaces them - 2.67 x 2.56 x 3.33 m, a real
    # self-seeded sapling, and the most characteristic colonist of derelict
    # industrial land there is.
    "ScrubElm": dict(
        asset="Elm_Sapling", h=(1.70, 2.90),
        mats={"American_Beech_leaf": leaf("American_Beech_leaf", 0.021,
                                          desat=0.50, hue=H_LIVE),
              "bark3": bark("bark3", 0.030)},
        doc="Self-seeded elm - the classic colonist of derelict yards."),
    "ScrubBirch": dict(
        asset="Gray_Birch", h=(1.80, 3.30),
        mats={"Gray_Birch_Leaves_Mat": leaf("Gray_Birch_Leaves_Mat", 0.022,
                                            desat=0.48, hue=H_LIVE),
              "Gray_Birch_Bark_Mat": bark("Gray_Birch_Bark_Mat", 0.036,
                                          desat=0.55)},
        doc="Birch sapling. Self-seeds into ballast, gravel and cracked slab "
            "faster than anything else in this climate, and its open airy crown "
            "silhouettes completely differently from the dense mounds around "
            "it. The white bark is graded to 0.036 - it is a pale trunk, not a "
            "light source."),
    "ScrubBirchDry": dict(
        asset="Gray_Birch", h=(1.75, 2.80),
        mats={"Gray_Birch_Leaves_Mat": leaf("Gray_Birch_Leaves_Mat", 0.036,
                                            desat=0.76, hue=H_DYING),
              "Gray_Birch_Bark_Mat": bark("Gray_Birch_Bark_Mat", 0.030,
                                          desat=0.55)},
        doc="A drought-stressed birch, half its leaves gone brown. Late summer "
            "on a hardstanding kills saplings; this is what that looks like, "
            "and it is a brown that reads as DYING, not as autumn - the chroma "
            "is a third of a fall atlas."),
    "ScrubElder": dict(
        asset="Blue_Berry_Elder", h=(2.20, 3.10),
        mats={"HollyPrivet_Mat": leaf("HollyPrivet_Mat", 0.017, desat=0.52,
                                      hue=H_LIVE),
              "tree_bark_03_2k": bark("tree_bark_03_2k", 0.028)},
        doc="Elder. Dense, dark, silhouettes as a mass."),
    "ScrubPrivet": dict(
        asset="Privet", h=(0.95, 1.75),
        mats={"HollyPrivet_Mat": leaf("HollyPrivet_Mat", 0.018, desat=0.50,
                                      hue=H_LIVE),
              "bark3": bark("bark3", 0.030)},
        doc="Wild privet. Replaces Barberry, which the library ships as a "
            "GOLDEN cultivar - a 1.5 m acid-yellow bush was landing in the "
            "left quarter of SILHOUETTE_WEST."),
    "ScrubPrivetLow": dict(
        asset="Privet", h=(0.60, 1.10),
        mats={"HollyPrivet_Mat": leaf("HollyPrivet_Mat", 0.020, desat=0.46,
                                      hue=H_LIVE),
              "bark3": bark("bark3", 0.030)},
        doc="Knee-to-thigh privet for inside the playable core, where LAYOUT "
            "section 0 caps everything at 1.4 m. Comes from the same asset at "
            "a smaller scale that is still inside the 0.005-0.02 band."),
    "ScrubPrivetDry": dict(
        asset="Privet", h=(0.70, 1.45),
        mats={"HollyPrivet_Mat": leaf("HollyPrivet_Mat", 0.034, desat=0.76,
                                      hue=H_DYING),
              "bark3": bark("bark3", 0.030)},
        doc="Half-dead privet on a hardstanding. Gives the scrub band a value "
            "and hue break that used to be supplied by the conifers."),

    # ---- trees -----------------------------------------------------------
    # ROUND 6: Honey Locust is GONE. Its basecolor atlas is half green leaf and
    # half ORANGE-RED AUTUMN leaf on a golden-brown ground, so every honey
    # locust in the map was carrying autumn foliage inside a late-summer level.
    # There is no per-half override, so the asset goes.
    #
    # The tree grade is NEUTRAL now. Round 5 put a cool bias - blue channel
    # above red - on every tree in the map on the argument that only the blue
    # dome reaches the body of a canopy. The argument is fine and the
    # implementation was not: stacked on the broken saturation solve it produced
    # effective leaf albedos with B/R 1.4-2.2, which is a cyan leaf. Whatever
    # cool light reaches these canopies is the LIGHTING's job to deliver; the
    # albedo stays the albedo.
    "TreePoplar": dict(
        asset="Lombardy_Poplar", h=(11.6, 17.4),
        mats={"LombardyPoplar_leaf_Mat_2": leaf("LombardyPoplar_leaf_Mat_2",
                                                0.030, desat=0.50, hue=H_LIVE),
              "bark3": bark("bark3", 0.032)},
        doc="The windbreak poplar named in LAYOUT 5.19. 429 k points of real "
            "branch and leaf geometry - the flat read was tint and value, not a "
            "billboard."),
    "TreePoplarDark": dict(
        asset="Lombardy_Poplar", h=(9.8, 14.6),
        mats={"LombardyPoplar_leaf_Mat_2": leaf("LombardyPoplar_leaf_Mat_2",
                                                0.021, desat=0.56, hue=H_SHADE),
              "bark3": bark("bark3", 0.028)},
        doc="A shaded/darker poplar so the row has a value break, not just a "
            "height break."),
    "TreePoplarDying": dict(
        asset="Lombardy_Poplar", h=(10.6, 15.8),
        mats={"LombardyPoplar_leaf_Mat_2": leaf("LombardyPoplar_leaf_Mat_2",
                                                0.038, desat=0.74, hue=H_DYING),
              "bark3": bark("bark3", 0.028)},
        doc="A poplar dying back: low chroma pushed slightly warm, so it reads "
            "brown-grey. The one warm tree in the band. Deliberately NOT the "
            "*_Fall asset, whose leaf atlas is the brightest, most saturated "
            "surface anywhere near the sun break in SILHOUETTE_WEST."),
    "TreeAsh": dict(
        asset="Red_Ash", h=(6.4, 9.6),
        mats={"RedAsh_leaf_mat": leaf("RedAsh_leaf_mat", 0.033, desat=0.50,
                                      hue=H_LIVE),
              "RedAsh_bark_Mat": bark("RedAsh_bark_Mat", 0.032)},
        doc="Ash - the real colonist of derelict northern industrial land. "
            "Round crown, half the poplar's height: it breaks the comb."),
    "TreeAshDark": dict(
        asset="Red_Ash", h=(5.6, 8.4),
        mats={"RedAsh_leaf_mat": leaf("RedAsh_leaf_mat", 0.024, desat=0.56,
                                      hue=H_SHADE),
              "RedAsh_bark_Mat": bark("RedAsh_bark_Mat", 0.028)},
        doc="Darker ash for the back of the band."),
    "TreeBirch": dict(
        asset="Gray_Birch", h=(4.2, 6.4),
        mats={"Gray_Birch_Leaves_Mat": leaf("Gray_Birch_Leaves_Mat", 0.026,
                                            desat=0.50, hue=H_LIVE),
              "Gray_Birch_Bark_Mat": bark("Gray_Birch_Bark_Mat", 0.036,
                                          desat=0.55)},
        doc="A grown-on birch. Takes over the profile break that Honey Locust "
            "used to give the band, without the autumn half-atlas."),
    "TreeHawthorn": dict(
        asset="Hawthorn", h=(5.2, 8.4),
        mats={"Hawthorn_leaf_Mat": leaf("Hawthorn_leaf_Mat", 0.026, desat=0.52,
                                        hue=H_LIVE, rough=0.76),
              "Hawthorn_leaf_v2_Mat": leaf("Hawthorn_leaf_v2_Mat", 0.026,
                                           desat=0.52, hue=H_LIVE, rough=0.76),
              "Hawthorn_leaf_v3_Mat": leaf("Hawthorn_leaf_v3_Mat", 0.022,
                                           desat=0.58, hue=H_LIVE, rough=0.76),
              "Hawthorn_leaf_v4_Mat": leaf("Hawthorn_leaf_v4_Mat", 0.022,
                                           desat=0.58, hue=H_LIVE, rough=0.76),
              "Hawthorn_bark_Mat": bark("Hawthorn_bark_Mat", 0.030)},
        doc="Hedgerow thorn: wind-shaped, irregular, leans. The most broken "
            "silhouette available in the library. Its four leaf atlases span "
            "luminance 0.096-0.243 and round 5 gave all four the same tint, so "
            "one variant per tree was 2.5x the others; they are landed on a "
            "stated albedo individually now."),
    "TreeFraxinus": dict(
        asset="Fraxinus", h=(3.9, 6.2),
        mats={"Fraxinus_leaves": leaf("Fraxinus_leaves", 0.028, desat=0.50,
                                      hue=H_LIVE),
              "Apple_bark_Mat": bark("Apple_bark_Mat", 0.032),
              "Apple_bark_Mat_2": bark("Apple_bark_Mat_2", 0.032)},
        doc="Small ash - the understorey tier between scrub and canopy."),
    "TreeOak": dict(
        asset="Black_Oak", h=(16.5, 20.5),
        mats={"Shumard_Oak_leaf_Mat2": leaf("Shumard_Oak_leaf_Mat2", 0.026,
                                            desat=0.54, hue=H_LIVE, rough=0.76),
              "Shumard_Oak_leaf_v2_Mat2": leaf("Shumard_Oak_leaf_v2_Mat2", 0.026,
                                               desat=0.80, hue=H_DYING,
                                               rough=0.76),
              "Shumard_Oak_leaf_v3_Mat2": leaf("Shumard_Oak_leaf_v3_Mat2", 0.023,
                                               desat=0.58, hue=H_LIVE,
                                               rough=0.76),
              "Shumard_Oak_leaf_v4_Mat2": leaf("Shumard_Oak_leaf_v4_Mat2", 0.023,
                                               desat=0.58, hue=H_LIVE,
                                               rough=0.76),
              "TreeBark_7": bark("TreeBark_7", 0.030)},
        doc="The two corner canopy anchors LAYOUT 5.19 asks for by name, and "
            "the object the critic identified as a pink-white blossoming "
            "ornamental mid-right in LANE_EYE_YARD. It is neither ornamental "
            "nor in blossom: it is the (68.4,-49.6) black oak at 112 m, and it "
            "was being multiplied by diffuse_tint (0.1196, 0.1243, 0.5554) - a "
            "4.6x blue boost solved in the wrong colour space. Its four leaf "
            "atlases are measured separately now, and oakleaves2 (a TAN sheet) "
            "is desaturated hardest of the four so it reads as August "
            "drought-burn rather than as October."),
}

# ---------------------------------------------------------------------------
# DEBRIS PROTOTYPES
# ---------------------------------------------------------------------------
# Half-buried stones were being referenced RAW, straight from S3, so none of
# them saw the grade or the matte treatment - and they are small, sharp and sit
# on the ground right under the DETAIL_WET_APRON eye, which makes them a firefly
# source in exactly the frame that is judged on surface detail. They go through
# the same prototype mechanism as the plants.
#
# ROUND 6: the leaf-drift half of this section is deleted along with the assets.
# There is exactly one debris family left and it is stone.
def matte(v=1.0, desat=0.35, warm=(1.0, 1.0, 1.0), rough=0.90, bump=None,
          spec=None):
    """A grade for a material whose albedo was never measured: no solve, just a
    darkening multiply, a desaturation and a bump/spec choice.

    Debris is the one part of this module that defaults to the full normal map:
    a stone and a leaf drift are decimetre objects a few metres from the
    DETAIL_WET_APRON lens, i.e. hundreds of pixels of genuine relief, not the
    sub-pixel foliage the bump clamp exists to tame."""
    return {"desat": desat, "bright": 1.0,
            "tint": tuple(round(v * w, 4) for w in warm),
            "rough": rough,
            "bump": BUMP_SOLID if bump is None else bump,
            "spec": SPEC if spec is None else spec, "_bark": v}


DEBRIS_PROTOS: dict[str, dict] = {}
DEBRIS_PROTOS.update({
    # THE FOREGROUND STONE. Measured in DETAIL_WET_APRON: the stone rendered at
    # luminance 0.460 on aggregate of 0.312 - the brightest object in the near
    # field, pale blue-cream, and completely featureless. That is the object the
    # critic called an untextured placeholder, and three separate things were
    # making it one: diffuse_tint 0.74 (a 20 cm wet granite cobble is nothing
    # like 0.74 reflectance - it is 0.15-0.22 dry and less wet),
    # reflection_roughness_constant 0.90 with texture influence 0 (so the whole
    # stone is one dead uniform lambertian value), and bump_factor 0.35 which
    # threw away the one map that carries its surface. The asset itself is fine:
    # rock_small_03 ships a 1024 basecolor, a normal map AND an ORM, all of which
    # resolve. So: darkened to 0.20 with a cool wet bias, roughness down to 0.58
    # so the wet sheen breaks the form, and the normal map back at full strength.
    a: dict(asset=a, mats={"material": matte(0.20, 0.34, (0.95, 0.98, 1.06),
                                             rough=0.62, bump=BUMP_SOLID,
                                             spec=0.10)},
            doc="Half-buried wet stone at a weed line. Graded to a real wet-"
                "granite reflectance with its normal map at full strength - it "
                "was rendering as a featureless pale blob in the foreground of "
                "the one shot that is judged on surface detail.")
    for a in sorted(ROCKS)
})


# --- distance tiers -------------------------------------------------------
# Only woody plants get haze variants; a 0.2 m tuft is never 100 m from an eye
# that can resolve it.
WOODY = [k for k in PROTOS if k.startswith(("Tree", "Scrub"))]
for _n in WOODY:
    for _t in ("_M", "_F"):
        _p = PROTOS[_n]
        PROTOS[_n + _t] = dict(
            asset=_p["asset"], h=_p["h"], mats=hazed(_p["mats"], _t),
            doc=_p["doc"] + (" Aerial-perspective variant: "
                             + ("60-100 m" if _t == "_M" else "beyond 100 m")
                             + " - more saturation removed, value dropped and the "
                               "residue pushed cool, so the band reads as a "
                               "silhouette layer behind the haze rather than a "
                               "pale smear glowing through it."))


# ---------------------------------------------------------------------------
# CAMERAS - parsed, not hard-coded, so the aerial grade follows the shot list
# ---------------------------------------------------------------------------
CAMERAS_USDA = ROOT / "usd" / "modules" / "90_cameras.usda"


def read_cameras():
    """[(name, eye_xy, forward_xy)] for every shot camera.

    Z-up convention from the BRIEF: rotateXYZ (p, 0, h) looks along
    (-sin p sin h, sin p cos h, -cos p).
    """
    txt = CAMERAS_USDA.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'def Camera "([A-Z_]+)"\s*\n\s*\{(.*?)\n        \}',
                         txt, re.S):
        body = m.group(2)
        t = re.search(r'xformOp:translate = \(([-0-9.eE]+), ([-0-9.eE]+), ', body)
        r = re.search(r'xformOp:rotateXYZ = \(([-0-9.eE]+), ([-0-9.eE]+), ([-0-9.eE]+)\)', body)
        if not t or not r:
            continue
        p, h = math.radians(float(r.group(1))), math.radians(float(r.group(3)))
        out.append((m.group(1), (float(t.group(1)), float(t.group(2))),
                    (-math.sin(p) * math.sin(h), math.sin(p) * math.cos(h))))
    return out


CAMS = read_cameras()


def cam_range(x, y):
    """Distance to the nearest eye that is actually LOOKING at (x, y).

    An eye with the point behind it must not pull a far tree into the near
    tier - HERO_ESTABLISH stands 23 m from the south poplar band and faces the
    opposite way.
    """
    best = 1e9
    for _name, (ex, ey), (fx, fy) in CAMS:
        dx, dy = x - ex, y - ey
        if dx * fx + dy * fy <= 0.0:
            continue
        best = min(best, math.hypot(dx, dy))
    return best


def haze_tier(x, y):
    d = cam_range(x, y)
    return "" if d < 60.0 else ("_M" if d < 100.0 else "_F")


def tiered(proto, x, y):
    """The distance-graded twin of `proto` for a plant standing at (x, y)."""
    if proto not in WOODY:
        return proto
    return proto + haze_tier(x, y)


# ---------------------------------------------------------------------------
# SHADER PRIM NAMES  -- the round-3 grade was half discarded and this is why
# ---------------------------------------------------------------------------
# The grade is authored as
#     over "Looks" { over "<Material>" { over "<Shader>" { ...params... } } }
# and `over` on a name that does not exist is perfectly legal USD: it creates an
# EMPTY prim and nothing is overridden. Round 3 hard-coded the shader child as
# "Shader". That is true for most of this library but NOT for all of it -- in
# Switchgrass, Blue_Berry_Elder, Red_Ash, Honey_Locust, Hawthorn and Fraxinus the
# shader prim is named after its material (Looks/HollyPrivet_Mat/HollyPrivet_Mat).
# 14 of the 43 override targets were therefore no-ops, and the six species that
# silently kept their nursery albedo were exactly the ones that read wrong:
# the 2.9 m elder cover mass at (+38,-13) is 17 m from the SILHOUETTE_WEST eye
# and was rendering as full-saturation garden green, the only green object in a
# blue-and-amber frame.
#
# So the name is now RESOLVED from the asset instead of assumed, cached to
# _veg_shaders.json, and a material that cannot be resolved is a hard error.
SHADER_CACHE = ROOT / "tools" / "_veg_shaders.json"


def shader_map() -> dict[str, dict[str, list[str]]]:
    """{asset: {material_name: [prim, names, down, to, the, shader]}}.

    The FULL path is resolved, not just the shader's own name, because the
    library is not consistent about the enclosing scope either: tree and grass
    assets put their materials under `<default>/Looks/<mat>/<shader>`, the leaf
    debris under `<default>/<name>/Looks/fallleaves/Shader`, and the rocks under
    `<default>/rock/material/Shader` - with rock_small_04 shipping that scope
    misspelled as `iock`. Assuming any of it is how the grade got silently
    dropped once already.
    """
    import json
    if SHADER_CACHE.exists():
        return json.loads(SHADER_CACHE.read_text(encoding="utf-8"))
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fetch_asset as fa
    from pxr import UsdShade
    out: dict[str, dict[str, list[str]]] = {}
    for asset, key in ALL_ASSETS.items():
        path = fa.mirror(key)
        if path is None:
            raise SystemExit(f"cannot mirror {key}")
        st = Usd.Stage.Open(str(path))
        root = st.GetDefaultPrim().GetPath()
        mats = {}
        for prim in st.Traverse():
            if not prim.IsA(UsdShade.Material):
                continue
            kids = [c for c in prim.GetChildren() if c.IsA(UsdShade.Shader)]
            if not kids:
                continue
            rel = kids[0].GetPath().MakeRelativePath(root)
            mats[prim.GetName()] = str(rel).split("/")
        out[asset] = mats
    SHADER_CACHE.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(f"resolved shader prim paths for {len(out)} assets -> {SHADER_CACHE.name}")
    return out


TIER1 = ["TuftFine", "TuftFineDry", "TuftSparse", "TuftSparseDry",
         "MatBroadDark", "MatWide", "TuftMid", "TuftMidDark",
         "MossMat", "MossDark", "MossOlive"]

# clump species mix. ROUND 6 raises the DRY share from 13% to 30%: the season
# this level is now committed to is a late-summer storm break, and grass on an
# unwatered hardstanding in August is a third to a half burnt off. That mix is
# also what replaces the autumn leaf drift as the map's warm ground accent - the
# straw is warm, seasonally correct, and it is grass rather than fall foliage.
# Dry variants are still steered away from standing water.
TIER1_MIX = {"TuftFine": 0.16, "TuftSparse": 0.16, "TuftMid": 0.12,
             "TuftMidDark": 0.10, "MatBroadDark": 0.09, "MatWide": 0.07,
             "TuftFineDry": 0.16, "TuftSparseDry": 0.14}
TIER1_TINY = {"TuftFine": 0.28, "TuftSparse": 0.20, "TuftFineDry": 0.16,
              "TuftSparseDry": 0.10, "MatBroadDark": 0.14, "MatWide": 0.12}
# Damp ground - puddle rim, dock-foot algae band, either trench drain - grows a
# different community from a dry seam: low mats and moss, no bleached straw.
DAMP_MIX = {"MossMat": 0.18, "MossDark": 0.10, "MatWide": 0.24,
            "MatBroadDark": 0.18, "TuftFine": 0.18, "TuftMidDark": 0.12}
# A moss patch is not one tone. Drawn per instance inside a run so a run has a
# dark wet core, a mid body and an olive drying edge instead of reading as a row
# of identical green dots.
MOSS_MIX = {"MossMat": 0.46, "MossDark": 0.32, "MossOlive": 0.22}
DRY = {"TuftFineDry", "TuftSparseDry", "RankSwitchDry", "IngressDry",
       "ScrubPrivetDry", "ScrubBirchDry"}

TIER2_MIX = {"RankSwitch": 0.24, "RankSwitchDry": 0.30, "RankMatA": 0.18,
             "RankMatB": 0.14, "RankTuft": 0.14}
TIER3_MIX = {"ScrubElm": 0.22, "ScrubBirch": 0.20, "ScrubElder": 0.16,
             "ScrubPrivet": 0.18, "ScrubPrivetLow": 0.10,
             "ScrubPrivetDry": 0.08, "ScrubBirchDry": 0.06}
INTERIOR_MIX = {"IngressFine": 0.46, "IngressSparse": 0.28, "IngressDry": 0.26}

# --- camera / frame geometry ------------------------------------------------
DETAIL_CAM = (-12.0, -10.5)          # DETAIL_WET_APRON eye, LAYOUT 7.4
DETAIL_NEAR = 8.0
DETAIL_MID = 16.0
DETAIL_RANK_EXCLUDE = 20.0

EAST_SCRUB_ANCHOR = (38.0, -13.0)    # LAYOUT 6.3 cover mass


# --- world zones ------------------------------------------------------------
def in_interior(x, y):
    return -38.0 <= x <= 38.0 and 15.0 <= y <= 76.25


def in_yard(x, y):
    return -52.0 <= x <= 52.0 and -16.0 <= y <= 15.0


def in_dock_lane(x, y):
    return -52.0 <= x <= 52.0 and -40.0 <= y <= -16.0


def dist_detail(x, y):
    return math.hypot(x - DETAIL_CAM[0], y - DETAIL_CAM[1])


# solid volumes 20_architecture builds: nothing grows at grade inside them
SOLIDS = [(-46.0, -34.0, 30.0, -22.0),      # dock platform slab
          (30.0, -34.0, 46.0, -20.0),       # dock office block
          (40.0, 6.0, 50.0, 30.0),          # east loading platform
          (-64.0, -14.0, -48.0, -4.0),      # fuel bund
          (13.79, 75.81, 26.20, 88.25)]     # warehouse office annex


def in_solid(x, y, inset=0.30):
    for x0, y0, x1, y1 in SOLIDS:
        if x0 + inset <= x <= x1 - inset and y0 + inset <= y <= y1 - inset:
            return True
    return False


def in_centre_cluster(x, y):
    """LAYOUT's contested centre cluster box - 30_props owns it, zero plants."""
    return -6.5 <= x <= 14.5 and -8.5 <= y <= 6.5


def rank_ok(x, y):
    """Where waist-high rank growth is permitted."""
    if in_interior(x, y):
        return False
    if dist_detail(x, y) < DETAIL_RANK_EXCLUDE:
        return False
    if -46.0 <= x <= 30.0 and -35.0 <= y <= -19.0:
        return False
    if y <= -40.0:
        return True
    if y >= 77.0:
        return True
    if x <= -64.0 or x >= 60.0:
        return True
    if 48.0 <= x <= 60.0 and -30.0 <= y <= 60.0:
        return True
    if -40.0 <= y <= -36.5 and abs(x) <= 52.0:
        return True
    if in_yard(x, y) and abs(x) >= 44.0 and (y <= -11.0 or y >= 9.0):
        return True
    return False


def deep_oob(x, y):
    """Truly out of bounds - behind the fence line or past the ends of the map.

    LAYOUT section 0 says nothing inside the playable core may exceed 1.4 m, and
    section 6.3 then asks for a 2.5 m cover mass at (+38,-13). Both cannot be
    obeyed. The compromise used here: a woody plant may exceed 1.45 m only in
    deep OOB or in the one cover mass the cover schedule names by coordinate.
    Everywhere else in the core, tier-3 scrub is capped at knee-to-chest height,
    so no bush is quietly acting as unmarked hard cover on a lane.
    """
    return x <= -64.0 or x >= 62.0 or y <= -40.0 or y >= 77.0


CORE_CAP = 1.42            # metres, tier-3 ceiling inside the playable core
SHORT_SCRUB = {"ScrubPrivetLow": 0.48, "ScrubPrivet": 0.30,
               "ScrubPrivetDry": 0.22}


def dead_ground(x, y):
    """Where tier-3 saplings and woody scrub are permitted."""
    if not rank_ok(x, y):
        return False
    if in_yard(x, y):
        return False
    if in_dock_lane(x, y) and y > -40.0:
        return False
    return True


# ---------------------------------------------------------------------------
# 1. read the authored instance set (positions for the scopes we keep)
# ---------------------------------------------------------------------------
BLOCK = re.compile(
    r'^( +)def Xform "([A-Za-z0-9_]+)" \(\n'
    r' +instanceable = true\n'
    r' +prepend references = ([@<][^@>]+[@>])\n'
    r' +\)\n'
    r' +\{\n'
    r' +float3 xformOp:rotateXYZ = \(([-0-9.eE]+), ([-0-9.eE]+), ([-0-9.eE]+)\)\n'
    r' +float3 xformOp:scale = \(([-0-9.eE]+), ([-0-9.eE]+), ([-0-9.eE]+)\)\n'
    r' +double3 xformOp:translate = \(([-0-9.eE]+), ([-0-9.eE]+), ([-0-9.eE]+)\)\n'
    r' +uniform token\[\] xformOpOrder = \[[^\]]*\]\n'
    r' +\}\n',
    re.M,
)
SCOPE_RE = re.compile(r'^        def Scope "([A-Za-z]+)" \(', re.M)


SEED = ROOT / "tools" / "_veg_seed.json"


def read_instances():
    """Positions for the scopes that are kept in place.

    Snapshotted to _veg_seed.json on first run: the generator ADDS litter at the
    new weed clumps, so re-reading its own output would accumulate a fresh batch
    on every run. The snapshot is the authored ground truth (positions came from
    a terrain height lookup that is expensive to redo).
    """
    import json
    if SEED.exists():
        return json.loads(SEED.read_text(encoding="utf-8"))
    out = _parse_usda()
    SEED.write_text(json.dumps(out), encoding="utf-8")
    print(f"snapshotted {len(out)} authored placements to {SEED.name}")
    return out


def _parse_usda():
    text = VEG.read_text(encoding="utf-8")
    bounds = [(m.start(), m.group(1)) for m in SCOPE_RE.finditer(text)]
    bounds.append((len(text), None))
    out = []
    for m in BLOCK.finditer(text):
        pos = m.start()
        scope = None
        for i in range(len(bounds) - 1):
            if bounds[i][0] <= pos < bounds[i + 1][0]:
                scope = bounds[i][1]
                break
        ref = m.group(3).strip("@<>")
        asset = ref.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        out.append({
            "scope": scope, "asset": asset,
            "rot": [float(m.group(4)), float(m.group(5)), float(m.group(6))],
            "scale": [float(m.group(7)), float(m.group(8)), float(m.group(9))],
            "pos": [float(m.group(10)), float(m.group(11)), float(m.group(12))],
        })
    return out


# ---------------------------------------------------------------------------
# 2. terrain geometry
# ---------------------------------------------------------------------------
GROUND_MESHES = ["Ground_MarginWest", "Ground_MarginEast", "Ground_OOBSouth",
                 "Ground_ServiceRoad", "Ground_DockApron", "Ground_CentralYard",
                 "Ground_FlankWest", "Ground_FlankEast", "Ground_OOBNorth"]


def open_terrain():
    layer = Sdf.Layer.FindOrOpen(str(TERRAIN))
    return Usd.Stage.Open(layer)


def mesh_points(stage, path):
    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return None
    pts = UsdGeom.Mesh(prim).GetPointsAttr().Get()
    return np.asarray(pts, dtype=np.float64) if pts else None


def mesh_edges(stage, path):
    prim = stage.GetPrimAtPath(path)
    mesh = UsdGeom.Mesh(prim)
    pts = np.asarray(mesh.GetPointsAttr().Get(), dtype=np.float64)[:, :2]
    counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int64)
    idx = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int64)
    a, b = [], []
    o = 0
    for c in counts:
        f = idx[o:o + c]
        o += c
        for k in range(c):
            a.append(f[k])
            b.append(f[(k + 1) % c])
    return pts[np.asarray(a)], pts[np.asarray(b)]


def seg_dist(px, py, A, B):
    P = np.stack([px, py], axis=1)
    AB = B - A
    denom = np.einsum("ij,ij->i", AB, AB)
    denom[denom == 0] = 1e-12
    out = np.empty(len(P))
    step = max(1, int(4_000_000 // max(1, len(A))))
    for s in range(0, len(P), step):
        chunk = P[s:s + step]
        AP = chunk[:, None, :] - A[None, :, :]
        t = np.clip(np.einsum("kij,ij->ki", AP, AB) / denom, 0.0, 1.0)
        proj = A[None, :, :] + t[:, :, None] * AB[None, :, :]
        d = np.linalg.norm(chunk[:, None, :] - proj, axis=2)
        out[s:s + step] = d.min(axis=1)
    return out


class GroundZ:
    """Nearest-vertex ground height from the 10_terrain ground plates."""

    CELL = 2.0

    def __init__(self, stage):
        chunks = []
        for n in GROUND_MESHES:
            p = mesh_points(stage, "/World/Terrain/Ground/" + n)
            if p is not None:
                chunks.append(p)
        self.P = np.concatenate(chunks, axis=0)
        self.bins: dict[tuple[int, int], list[int]] = {}
        ij = np.floor(self.P[:, :2] / self.CELL).astype(np.int64)
        for k in range(len(self.P)):
            self.bins.setdefault((int(ij[k, 0]), int(ij[k, 1])), []).append(k)

    def z(self, x, y, rings=3):
        i0 = int(math.floor(x / self.CELL))
        j0 = int(math.floor(y / self.CELL))
        best, bd = None, 1e18
        for r in range(rings + 1):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    for k in self.bins.get((i0 + di, j0 + dj), ()):
                        d = (self.P[k, 0] - x) ** 2 + (self.P[k, 1] - y) ** 2
                        if d < bd:
                            bd, best = d, k
            if best is not None and r >= 1:
                break
        if best is None:
            return None
        return float(self.P[best, 2])


# --- exterior edge network --------------------------------------------------
HARD_MESHES = [
    "Patches/PuddleMargins",
    "Drainage/TrenchDrain_EW", "Drainage/TrenchDrain_EW_Dressing",
    "Drainage/TrenchDrain_NS", "Drainage/TrenchDrain_NS_Dressing",
    "Kerbs/WarehouseKerbPlinth", "Kerbs/DockApronEdgeBeam",
    "Kerbs/DockFootAlgaeBand", "Debris/BrokenSlabs", "Covers/ManholeCovers",
]
SOFT_MESHES = ["Patches/CrackNetwork", "Patches/RepairSeams"]
DENY_MESHES = ["Patches/TyrePolish", "Patches/WetWheelTracks"]
# damp ground: weeds are denser and never the dry variants
DAMP_MESHES = ["Patches/PuddleMargins", "Kerbs/DockFootAlgaeBand",
               "Drainage/TrenchDrain_EW", "Drainage/TrenchDrain_NS"]


def _rect(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


ANALYTIC_EDGES = (
    _rect(-38.0, 15.0, 38.0, 88.25)          # warehouse footprint
    + _rect(-46.0, -34.0, 30.0, -22.0)       # dock platform slab
    + _rect(30.0, -34.0, 46.0, -20.0)        # dock office block
    + _rect(40.0, 6.0, 50.0, 30.0)           # east loading platform
    + _rect(-64.0, -14.0, -48.0, -4.0)       # fuel bund outer wall
    + _rect(44.0, 24.0, 64.0, 28.0)          # gantry crane portal feet
    + [((-70.0, -46.0), (-70.0, 40.0)),      # fence: west run
       ((-70.0, -44.0), (66.0, -44.0)),      # fence: south run
       ((66.0, -44.0), (66.0, 58.0)),        # fence: east run
       ((-56.0, 92.0), (60.0, 92.0)),        # fence: north run
       ((51.8, -30.0), (51.8, 60.0)),        # rail ballast shoulders
       ((56.2, -30.0), (56.2, 60.0)),
       ((24.6, -22.0), (24.6, 15.0)),        # conveyor bridge leg line
       ((27.2, -22.0), (27.2, 15.0)),
       ((-31.0, -8.0), (-31.0, 15.0)),       # pipe trestle leg line
       ((-29.0, -8.0), (-29.0, 15.0))]
)
ANALYTIC_POINTS = (
    [(x, -21.0) for x in (-44, -36.8, -29.6, -22.4, -15.2, -8, -0.8, 6.4, 13.6, 20.8, 28)]
    + [(-58.0, 8.0), (-50.0, 8.0)]
    + [(-58.0, 64.0), (-49.0, 68.0)]
    + [(58.0, 70.0)]
    + [(41.0, 8.0), (49.0, 8.0)]
)

GRID_MIN = (-80.0, -62.0)
GRID_CELL = 0.25
GRID_N = (int(165 / GRID_CELL), int(170 / GRID_CELL))


def _grid_new():
    return np.zeros(GRID_N, dtype=bool)


def _grid_mark_points(g, pts):
    i = np.floor((pts[:, 0] - GRID_MIN[0]) / GRID_CELL).astype(np.int64)
    j = np.floor((pts[:, 1] - GRID_MIN[1]) / GRID_CELL).astype(np.int64)
    ok = (i >= 0) & (i < GRID_N[0]) & (j >= 0) & (j < GRID_N[1])
    g[i[ok], j[ok]] = True


def _dilate(g, radius_m):
    r = int(math.ceil(radius_m / GRID_CELL))
    out = g.copy()
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            if math.hypot(di, dj) * GRID_CELL > radius_m or (di == 0 and dj == 0):
                continue
            a0, a1 = max(0, di), min(GRID_N[0], GRID_N[0] + di)
            b0, b1 = max(0, dj), min(GRID_N[1], GRID_N[1] + dj)
            out[a0:a1, b0:b1] |= g[a0 - di:a1 - di, b0 - dj:b1 - dj]
    return out


def _lookup(g, x, y):
    i = int(math.floor((x - GRID_MIN[0]) / GRID_CELL))
    j = int(math.floor((y - GRID_MIN[1]) / GRID_CELL))
    if 0 <= i < GRID_N[0] and 0 <= j < GRID_N[1]:
        return bool(g[i, j])
    return False


def edge_candidates(stage):
    """Points ON the authored edge network, each carrying its edge direction.

    A ruderal plant roots in a seam and grows ALONG it. Sampling the edge set
    directly (rather than scattering and then rejecting) is what makes the
    result read as growth: every tuft has a line to belong to.
    """
    out = []      # (x, y, dirx, diry, weight)

    def add_segments(segs_a, segs_b, weight, step=0.30, lo=0.22, hi=18.0):
        for (ax, ay), (bx, by) in zip(segs_a, segs_b):
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L < lo or L > hi:
                continue
            ux, uy = dx / L, dy / L
            n = max(1, int(L / step))
            for k in range(n):
                f = (k + 0.5) / n
                out.append((ax + f * dx, ay + f * dy, ux, uy, weight))

    for name in HARD_MESHES:
        prim = stage.GetPrimAtPath("/World/Terrain/" + name)
        if not prim or not prim.IsValid():
            continue
        A, B = mesh_edges(stage, "/World/Terrain/" + name)
        add_segments(A, B, 1.0)
    for name in SOFT_MESHES:
        prim = stage.GetPrimAtPath("/World/Terrain/" + name)
        if not prim or not prim.IsValid():
            continue
        A, B = mesh_edges(stage, "/World/Terrain/" + name)
        add_segments(A, B, 0.30)

    A = np.asarray([s[0] for s in ANALYTIC_EDGES], dtype=np.float64)
    B = np.asarray([s[1] for s in ANALYTIC_EDGES], dtype=np.float64)
    add_segments(A, B, 0.85, step=0.35, hi=200.0)

    for (px, py) in ANALYTIC_POINTS:
        for k in range(6):
            a = 2 * math.pi * k / 6 + rng.random()
            r = 0.30 + 0.22 * rng.random()
            out.append((px + r * math.cos(a), py + r * math.sin(a),
                        -math.sin(a), math.cos(a), 1.1))
    return out


# ---------------------------------------------------------------------------
# 3. scale helpers
# ---------------------------------------------------------------------------
BAND_LO, BAND_HI = 0.00512, 0.01975


def native_z(proto):
    return NATIVE[PROTOS[proto]["asset"]][2]


def height_of(proto, scale_z):
    return native_z(proto) * scale_z * 100.0


def _clamp(s):
    return min(max(s, BAND_LO), BAND_HI)


def scale_for(proto, h, wide=1.0, narrow=1.0):
    """Scale that lands the proto's height at h metres.

    `wide`/`narrow` are the in-plane axes BEFORE the yaw rotation (xformOpOrder
    is translate -> rotate -> scale, so scale is applied in the asset's own
    frame and then spun), which is how a tuft is stretched along the crack it
    grows in.
    """
    s = h * 0.01 / native_z(proto)
    return [_clamp(s * wide), _clamp(s * narrow), _clamp(s)]


def pick(weights):
    total = sum(weights.values())
    r = rng.uniform(0, total)
    acc = 0.0
    for k, w in weights.items():
        acc += w
        if r <= acc:
            return k
    return next(iter(weights))


def tuft_scale(proto, h_mul=1.0, elongate=True):
    lo, hi = PROTOS[proto]["h"]
    h = rng.uniform(lo, hi) * h_mul
    if elongate:
        e = rng.uniform(1.14, 1.46)
        return scale_for(proto, h, wide=e, narrow=rng.uniform(0.78, 0.96))
    return scale_for(proto, h, wide=rng.uniform(0.88, 1.16),
                     narrow=rng.uniform(0.88, 1.16))


# ---------------------------------------------------------------------------
# 4. tier-1 exterior: variable-radius cluster process on the edge network
# ---------------------------------------------------------------------------
EDGE_XY: list = []            # every edge-network sample, for the audit

# rock_small_* measures 20.9 x 18.6 x 15.6 in its own units, so a stone placed
# at scale s stands 15.57 * s metres tall. Round 4 sank all litter by a flat
# 5-30 mm, which for a 160 mm cobble is a stone RESTING ON the tarmac - and one
# of those is 3.3 m from the DETAIL_WET_APRON lens, sitting proud on top of the
# aggregate like a dropped prop. A stone at a weed line is a stone the ground has
# grown around: sink 38-62% of its height so the contact reads as bedded.
ROCK_NATIVE_Z = 15.573


def rock_sink(s):
    return ROCK_NATIVE_Z * s * rng.uniform(0.38, 0.62)


def build_tier1(stage, gz, deny, damp):
    cands = edge_candidates(stage)
    EDGE_XY.clear()
    EDGE_XY.extend((c[0], c[1]) for c in cands)
    rng.shuffle(cands)

    keep = []
    for (x, y, ux, uy, w) in cands:
        if in_interior(x, y) or in_solid(x, y) or in_centre_cluster(x, y):
            continue
        if _lookup(deny, x, y):
            continue
        if not (-76.0 <= x <= 76.0 and -58.0 <= y <= 94.0):
            continue
        if rng.random() > w:
            continue
        keep.append((x, y, ux, uy))
    print(f"tier-1 edge candidates after masking: {len(keep)}")

    # variable-radius Poisson parents: the exclusion radius is redrawn for every
    # candidate, so clump-to-clump spacing has real variance instead of the
    # single scale a fixed-radius dart throw produces.
    CELL = 3.5
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    parents = []
    for (x, y, ux, uy) in keep:
        r = rng.uniform(1.9, 9.6)
        if dist_detail(x, y) < 14.0:
            r *= 1.45                      # thinner in the detail camera's field
        i0, j0 = int(x // CELL), int(y // CELL)
        span = int(math.ceil(r / CELL))
        clash = False
        for di in range(-span, span + 1):
            for dj in range(-span, span + 1):
                for (px, py) in grid.get((i0 + di, j0 + dj), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r * r:
                        clash = True
                        break
                if clash:
                    break
            if clash:
                break
        if clash:
            continue
        grid.setdefault((i0, j0), []).append((x, y))
        parents.append((x, y, ux, uy))
    print(f"tier-1 clump parents: {len(parents)}")

    out = []
    litter_extra = []
    for (x, y, ux, uy) in parents:
        d = dist_detail(x, y)
        wet = _lookup(damp, x, y)
        tiny = d < DETAIL_NEAR
        mix = DAMP_MIX if wet else (TIER1_TINY if tiny else TIER1_MIX)
        clump = pick(mix)
        if wet and clump in DRY:
            clump = "MatWide"
        n = rng.choice([1, 1, 1, 2, 2, 2, 3, 3, 4, 5])
        if d < 6.0:
            n = min(n, 2)
        base_ang = math.degrees(math.atan2(uy, ux))
        placed: list[tuple[float, float]] = []
        for k in range(n):
            proto = clump if rng.random() < 0.72 else pick(mix)
            if wet and proto in DRY:
                proto = "MatWide"
            along = rng.gauss(0.0, 0.52) + (0.0 if k == 0 else rng.uniform(-0.6, 0.6))
            across = rng.gauss(0.0, 0.13)
            px = x + ux * along - uy * across
            py = y + uy * along + ux * across
            if in_solid(px, py) or in_interior(px, py) or in_centre_cluster(px, py) \
                    or _lookup(deny, px, py):
                continue
            # two tufts 30 mm apart are one tuft with twice the triangles
            if any((px - qx) ** 2 + (py - qy) ** 2 < 0.0169 for qx, qy in placed):
                continue
            placed.append((px, py))
            z = gz.z(px, py)
            if z is None:
                continue
            # a tuft grows along its seam: the ellipse is aligned to the edge,
            # flipped end-for-end at random, and jittered +/-26 deg. 45% of
            # instances instead take a fully random yaw so isolated tufts on
            # point features are not all combed the same way.
            if rng.random() < 0.55:
                yaw = base_ang + (180.0 if rng.random() < 0.5 else 0.0) + rng.gauss(0, 26.0)
                sc = tuft_scale(proto, h_mul=rng.uniform(0.62, 1.42), elongate=True)
            else:
                yaw = rng.uniform(0, 360)
                sc = tuft_scale(proto, h_mul=rng.uniform(0.62, 1.42), elongate=False)
            out.append({
                "scope": "CrackWeeds", "proto": proto,
                "rot": [rng.gauss(0, 2.6), rng.gauss(0, 2.6), yaw % 360.0],
                "scale": sc,
                "pos": [px, py, z - rng.uniform(0.010, 0.045)],
            })
        # ---- moss ------------------------------------------------------
        # A damp edge - a puddle rim, the dock-foot algae band, either trench
        # drain - grows a moss skin before it grows a tuft, and LAYOUT 7.4 lists
        # "moss in the drain" as one of the four things DETAIL_WET_APRON is
        # judged on. There was none anywhere in the map. Moss goes down as a
        # tight patch of 3-9 very low, very dark mats hugging the edge line, and
        # it is laid thickest inside the detail camera's field because that is
        # where 35 mm of growth is resolvable at all: at 3 m a moss mat is ~40 px
        # of genuine high-frequency surface, and at 40 m it is nothing.
        if wet:
            # A run, not a scatter: the patch is laid as an overlapping chain
            # along the edge direction with a dark wet core and an olive drying
            # margin, so it reads as growth spreading down a wet line instead of
            # a row of evenly-spaced identical green dots.
            nm = rng.randint(7, 14) if d < 24.0 else rng.randint(3, 6)
            span = rng.uniform(0.35, 1.30)
            core = rng.uniform(-0.35, 0.35)
            for j in range(nm):
                f = (j + rng.uniform(0.1, 0.9)) / nm - 0.5
                along = core + f * span * 2.0
                across = rng.gauss(0.0, 0.055)
                mx = x + ux * along - uy * across
                my = y + uy * along + ux * across
                if in_solid(mx, my) or in_interior(mx, my) or _lookup(deny, mx, my):
                    continue
                mz = gz.z(mx, my)
                if mz is None:
                    continue
                edge = abs(f) > 0.34
                proto = ("MossOlive" if rng.random() < 0.62 else "MossMat") if edge \
                    else pick(MOSS_MIX)
                out.append({
                    "scope": "CrackWeeds", "proto": proto,
                    "rot": [rng.gauss(0, 1.6), rng.gauss(0, 1.6),
                            rng.uniform(0, 360)],
                    "scale": tuft_scale(proto, h_mul=rng.uniform(0.62, 1.35),
                                        elongate=rng.random() < 0.80),
                    "pos": [mx, my, mz - rng.uniform(0.004, 0.016)],
                })

        # A third of the clumps also carry the silt they grew out of. ROUND 6:
        # that used to be 72% autumn leaf drift and 28% stone; it is 100% stone
        # now, drawn from all ten rock variants at true GRIT size (80-130 mm)
        # rather than the 190 mm cobbles, so a seam reads as accumulated grit
        # and weed instead of as October.
        if rng.random() < 0.34:
            z = gz.z(x, y)
            if z is not None:
                a = f"rock_small_{rng.randint(1, 10):02d}"
                s = rng.uniform(0.0053, 0.0090)
                litter_extra.append({
                    "scope": "GroundGrit", "asset": a,
                    "rot": [rng.gauss(0, 4), rng.gauss(0, 4), rng.uniform(0, 360)],
                    "scale": [s * rng.uniform(0.9, 1.15), s * rng.uniform(0.9, 1.15), s],
                    "pos": [x + rng.gauss(0, 0.45), y + rng.gauss(0, 0.45),
                            z - rock_sink(s)],
                })
    return out, litter_extra


# ---------------------------------------------------------------------------
# 5. tree lines - broken, mixed, multi-tier bands
# ---------------------------------------------------------------------------
def build_trees(gz):
    """LAYOUT 5.19 rebuilt.

    Rules the round-2 row broke, and how each is fixed here:
      - one species, two seasons  -> single seasonal state, no *_Fall assets
      - equal pitch               -> clumps of 2-5 with 9-26 m gaps
      - equal height              -> +/-26% within a clump, and clumps differ
      - one line                  -> a 7 m deep band, so the row overlaps itself
      - one profile               -> two clumps are ash/hawthorn, not poplar
      - trunks on bare ground     -> 2-4 scrub at the foot of every clump
    """
    out = []

    def plant(proto, x, y, h, extra_tilt=2.2, pad=0.0):
        z = gz.z(x, y)
        if z is None:
            return False
        if not deep_oob(x, y):
            h = min(h, CORE_CAP)
        s = h * 0.01 / native_z(proto)
        sx = _clamp(s * rng.uniform(0.90, 1.12))
        sy = _clamp(s * rng.uniform(0.90, 1.12))
        out.append({
            "scope": "TreeLines", "proto": tiered(proto, x, y),
            "rot": [rng.gauss(0, extra_tilt), rng.gauss(0, extra_tilt),
                    rng.uniform(0, 360)],
            "scale": [sx, sy, _clamp(s)],
            "pos": [x, y, z - pad],
        })
        return True

    def understorey(x, y, radius, n):
        for _ in range(n):
            a = rng.uniform(0, 2 * math.pi)
            r = radius * math.sqrt(rng.random())
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            proto = pick({"ScrubElder": 0.24, "ScrubElm": 0.22,
                          "ScrubBirch": 0.22, "ScrubPrivet": 0.18,
                          "ScrubBirchDry": 0.08, "ScrubPrivetDry": 0.06})
            lo, hi = PROTOS[proto]["h"]
            plant(proto, px, py, rng.uniform(lo, hi), extra_tilt=3.4, pad=0.05)

    def tufts(x, y, radius, n):
        for _ in range(n):
            a = rng.uniform(0, 2 * math.pi)
            r = radius * math.sqrt(rng.random())
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            z = gz.z(px, py)
            if z is None:
                continue
            proto = pick(TIER2_MIX)
            lo, hi = PROTOS[proto]["h"]
            out.append({
                "scope": "TreeLines", "proto": proto,
                "rot": [rng.gauss(0, 3), rng.gauss(0, 3), rng.uniform(0, 360)],
                "scale": scale_for(proto, rng.uniform(lo, hi) * rng.uniform(0.7, 1.3),
                                   wide=rng.uniform(0.86, 1.2),
                                   narrow=rng.uniform(0.86, 1.2)),
                "pos": [px, py, z - rng.uniform(0.02, 0.06)],
            })

    def ladder(n):
        """n height fractions in [0,1], stratified then shuffled.

        Drawing each tree's height independently from the species band lets two
        neighbours land within a couple of per cent of each other, and two
        equal-height trees side by side is the lollipop read the critic caught.
        A stratified draw guarantees the clump spans its whole band and that no
        two members are closer than ~1/n of it, while the shuffle keeps the tall
        one from always being on the same end.
        """
        f = [(k + rng.uniform(0.12, 0.88)) / n for k in range(n)]
        rng.shuffle(f)
        return f

    # ---- SOUTH BAND, Y ~ -52, X -68..+68 --------------------------------
    # Clump schedule authored by hand so the gaps are compositional, not random:
    # the two long gaps (X -34..-18 and X +8..+30) sit where SHOT 1 and SHOT 5
    # want to see sky and the far silo/crane layer through the row.
    SOUTH = [
        # (x_centre, n, y_centre, kind)
        (-64.0, 4, -51.4, "poplar"),
        (-55.5, 3, -53.0, "poplar"),
        (-47.0, 2, -50.4, "ash"),
        (-40.5, 3, -52.6, "poplar"),
        # ---- 16 m gap ----
        (-16.0, 4, -51.2, "poplar"),
        (-8.0, 2, -53.4, "hawthorn"),
        (-1.0, 3, -50.8, "poplar"),
        # ---- 22 m gap ----
        (32.0, 3, -52.2, "poplar"),
        (40.0, 2, -50.6, "ash"),
        (48.5, 4, -52.8, "poplar"),
        (58.0, 2, -51.0, "poplar"),
    ]
    # ROUND 6: Honey Locust dropped (half its leaf atlas is autumn), Gray Birch
    # in. The birch keeps the profile break the locust was giving the row - a
    # small open crown between the columnar poplars - without carrying orange
    # foliage into a late-summer level.
    KIND = {
        "poplar": ({"TreePoplar": 0.36, "TreePoplarDark": 0.26,
                    "TreePoplarDying": 0.16, "TreeAsh": 0.10,
                    "TreeBirch": 0.06, "TreeFraxinus": 0.06}, 3.2),
        "ash":    ({"TreeAsh": 0.30, "TreeAshDark": 0.24, "TreeBirch": 0.26,
                    "TreeFraxinus": 0.20}, 3.6),
        "hawthorn": ({"TreeHawthorn": 0.48, "TreeFraxinus": 0.22,
                      "TreeBirch": 0.18, "TreeAshDark": 0.12}, 4.2),
    }
    for (cx, n, cy, kind) in SOUTH:
        mix, tilt = KIND[kind]
        span = 2.0 + 2.6 * (n - 1)
        hf = ladder(n)
        for k in range(n):
            f = (k + 0.5) / n
            x = cx - span / 2 + f * span + rng.gauss(0, 0.9)
            y = cy + rng.gauss(0, 2.4)
            y = max(-55.6, min(-47.2, y))
            proto = pick(mix)
            lo, hi = PROTOS[proto]["h"]
            plant(proto, x, y, lo + hf[k] * (hi - lo), extra_tilt=tilt, pad=0.06)
        understorey(cx, cy + 1.6, 3.4 + 0.8 * n, rng.randint(2, 4))
        tufts(cx, cy + 1.2, 4.5 + 1.0 * n, rng.randint(5, 11))

    # ---- WEST BAND, X ~ -73, Y -22..+42 ----------------------------------
    # The instance near (-73, +6) is load-bearing: at 121 m it has to reach
    # ~13.3 m to clip the sun disc in SILHOUETTE_WEST, so that one is pinned
    # tall and is the only fixed element in the row.
    #
    # This is the ONE tree band that survives occlusion in SILHOUETTE_WEST:
    # measured against the shot's actual camera, the south row is completely
    # hidden behind the dock office block, and this band lands at x 930-1790,
    # y 620-760 - the whole right half of the background layer. So it carries
    # the depth read on its own, and it gets the work:
    #   - ten clumps instead of seven, 22 trees instead of 17, so crowns
    #     INTERLOCK. At 130 m the only depth cue that survives is overlap and
    #     relative size; 5 m of true parallax is worth nothing.
    #   - short-crowned ash / hawthorn clumps deliberately interleaved BETWEEN
    #     poplar clumps rather than only at the ends, so the skyline profile
    #     sawtooths instead of stepping.
    #   - X drawn across the full usable margin, clamped to -75.2 (the terrain
    #     plate's own west edge is -75.0; further out and a trunk stands on
    #     nothing).
    #   - two ~12 m gaps that are genuinely empty of trees.
    WEST = [
        (-73.9, -21.5, "poplar", 3),
        (-72.4, -17.0, "ash", 2),
        (-73.2, -11.0, "hawthorn", 2),
        # ---- 11 m gap ----
        (-74.1, 0.5, "poplar", 3),
        (-73.0, 6.0, "pin", 1),
        (-72.2, 9.5, "ash", 2),
        (-73.6, 13.0, "poplar", 2),
        # ---- 12 m gap ----
        (-73.8, 25.0, "hawthorn", 2),
        (-72.5, 29.5, "poplar", 2),
        (-74.0, 35.0, "poplar", 3),
    ]
    for (cx, cy, kind, n) in WEST:
        if kind == "pin":
            plant("TreePoplar", cx, cy, 16.4, extra_tilt=1.6, pad=0.05)
            understorey(cx + 1.4, cy, 2.6, 2)
            tufts(cx, cy, 4.0, 6)
            continue
        mix, tilt = KIND[kind]
        span = 1.8 + 2.4 * (n - 1)
        hf = ladder(n)
        for k in range(n):
            f = (k + 0.5) / n
            y = cy - span / 2 + f * span + rng.gauss(0, 0.8)
            x = cx + rng.gauss(0, 1.7)
            x = max(-75.2, min(-70.4, x))
            proto = pick(mix)
            lo, hi = PROTOS[proto]["h"]
            plant(proto, x, y, lo + hf[k] * (hi - lo), extra_tilt=tilt, pad=0.06)
        understorey(cx + 1.2, cy, 3.0 + 0.7 * n, rng.randint(3, 4))
        tufts(cx, cy, 4.2 + 0.8 * n, rng.randint(4, 9))

    # ---- CORNER CANOPY OAKS ---------------------------------------------
    plant("TreeOak", -70.2, -50.4, 19.8, extra_tilt=1.4, pad=0.10)
    plant("TreeOak", 68.4, -49.6, 17.4, extra_tilt=1.4, pad=0.10)
    for (ox, oy) in ((-70.2, -50.4), (68.4, -49.6)):
        understorey(ox, oy + 2.0, 5.5, 4)
        tufts(ox, oy + 1.0, 7.0, 12)

    return out


# ---------------------------------------------------------------------------
# 6. main
# ---------------------------------------------------------------------------
def main():
    inst = read_instances()
    print(f"read {len(inst)} authored instances")

    stage = open_terrain()
    gz = GroundZ(stage)
    print(f"ground height cloud: {len(gz.P)} vertices")

    feats = {}
    base = "/World/Terrain/InteriorOverlay/"
    for n in ("SlabJoints", "WetFanHalos", "WaterFilms", "AisleWear",
              "ForkliftScuff", "OilTrail"):
        feats[n] = mesh_edges(stage, base + n)

    deny = _grid_new()
    for name in DENY_MESHES:
        prim = stage.GetPrimAtPath("/World/Terrain/" + name)
        pts = UsdGeom.Mesh(prim).GetPointsAttr().Get() if prim and prim.IsValid() else None
        if pts:
            _grid_mark_points(deny, np.asarray(pts, dtype=np.float64)[:, :2])
    deny = _dilate(deny, 0.45)

    damp = _grid_new()
    for name in DAMP_MESHES:
        prim = stage.GetPrimAtPath("/World/Terrain/" + name)
        pts = UsdGeom.Mesh(prim).GetPointsAttr().Get() if prim and prim.IsValid() else None
        if pts:
            _grid_mark_points(damp, np.asarray(pts, dtype=np.float64)[:, :2])
    damp = _dilate(damp, 0.9)

    out = []

    # ---- interior ingress: keep the authored, rejection-sampled positions ---
    WALL_SEGS = [((-38.0, 15.0), (38.0, 15.0)), ((-38.0, 76.25), (38.0, 76.25)),
                 ((-38.0, 15.0), (-38.0, 76.25)), ((38.0, 15.0), (38.0, 76.25))]
    DOOR_SEGS = [((-37.85, 15.0), (2.62, 15.0)), ((-3.15, 15.0), (3.16, 15.0)),
                 ((-37.85, 15.37), (-37.85, 57.53)), ((37.84, 33.47), (37.84, 57.53))]

    def arr(segs):
        return (np.asarray([s[0] for s in segs], dtype=np.float64),
                np.asarray([s[1] for s in segs], dtype=np.float64))

    interior = [r for r in inst if in_interior(r["pos"][0], r["pos"][1])]
    ix = np.asarray([r["pos"][0] for r in interior])
    iy = np.asarray([r["pos"][1] for r in interior])
    d_joint = seg_dist(ix, iy, *feats["SlabJoints"])
    d_wet = np.minimum(seg_dist(ix, iy, *feats["WetFanHalos"]),
                       seg_dist(ix, iy, *feats["WaterFilms"]))
    d_wall = seg_dist(ix, iy, *arr(WALL_SEGS))
    d_door = seg_dist(ix, iy, *arr(DOOR_SEGS))
    d_worn = np.minimum(seg_dist(ix, iy, *feats["AisleWear"]),
                        seg_dist(ix, iy, *feats["ForkliftScuff"]))
    d_oil = seg_dist(ix, iy, *feats["OilTrail"])
    kept = 0
    for k, r in enumerate(interior):
        near = (d_joint[k] <= 0.40) or (d_wet[k] <= 0.35) or \
               (d_wall[k] <= 0.55) or (d_door[k] <= 0.80)
        worn = (d_worn[k] <= 0.60) or (d_oil[k] <= 0.50)
        lane = abs(r["pos"][1] - 49.5) < 3.0 and d_wall[k] > 0.55
        if not (near and not worn and not lane):
            continue
        kept += 1
        wet = bool(d_wet[k] <= 0.35 or d_door[k] <= 0.80)
        # ROUND 6: 55% of the dry interior slots used to be blown-in AUTUMN LEAF
        # LITTER - crisp orange oak and maple drifts, inside a warehouse, in a
        # level set at a late-summer storm break. What blows through an open
        # roller door in August is dead grass, chaff and grit, so the slot is
        # split between the dried-out ingress proto and a piece of tracked-in
        # grit.
        if not wet and rng.random() < 0.30:
            s = rng.uniform(0.0053, 0.0082)
            out.append({"scope": "InteriorIngress",
                        "asset": f"rock_small_{rng.randint(1, 10):02d}",
                        "rot": [rng.gauss(0, 3), rng.gauss(0, 3), rng.uniform(0, 360)],
                        "scale": [s * rng.uniform(0.9, 1.15),
                                  s * rng.uniform(0.9, 1.15), s],
                        "pos": [r["pos"][0], r["pos"][1],
                                r["pos"][2] - rock_sink(s) * 0.5]})
        else:
            proto = pick(INTERIOR_MIX)
            if wet and proto in DRY:
                proto = "IngressSparse"
            lo, hi = PROTOS[proto]["h"]
            out.append({"scope": "InteriorIngress", "proto": proto,
                        "rot": [rng.gauss(0, 2), rng.gauss(0, 2), rng.uniform(0, 360)],
                        "scale": scale_for(proto, rng.uniform(lo, hi),
                                           wide=rng.uniform(0.85, 1.2),
                                           narrow=rng.uniform(0.85, 1.2)),
                        "pos": list(r["pos"])})
    print(f"warehouse slab: {kept}/{len(interior)} survive the crack / wear / "
          f"traffic-lane rejection sample")

    # ---- tier 1 exterior: fully re-sampled ------------------------------
    tier1, litter_extra = build_tier1(stage, gz, deny, damp)
    out += tier1

    # ---- tier 2 rank weeds: keep authored positions, re-proto -----------
    n_rank = 0
    for r in inst:
        if r["scope"] not in ("RankWeeds",):
            continue
        x, y, z = r["pos"]
        if in_interior(x, y) or in_solid(x, y):
            continue
        if not rank_ok(x, y):
            continue
        proto = pick(TIER2_MIX)
        if _lookup(damp, x, y) and proto in DRY:
            proto = "RankMatA"
        lo, hi = PROTOS[proto]["h"]
        out.append({"scope": "RankWeeds", "proto": proto,
                    "rot": [rng.gauss(0, 3), rng.gauss(0, 3), rng.uniform(0, 360)],
                    "scale": scale_for(proto, rng.uniform(lo, hi) * rng.uniform(0.72, 1.3),
                                       wide=rng.uniform(0.85, 1.22),
                                       narrow=rng.uniform(0.85, 1.22)),
                    "pos": [x, y, z]})
        n_rank += 1
    print(f"rank weeds: {n_rank}")

    # ---- tier 3 scrub ---------------------------------------------------
    n_scrub = 0
    east_pool = []
    for r in inst:
        if r["scope"] != "CornerOvergrowth":
            continue
        x, y, z = r["pos"]
        if math.hypot(x - EAST_SCRUB_ANCHOR[0], y - EAST_SCRUB_ANCHOR[1]) < 14.0:
            east_pool.append(r)
            continue
        if not dead_ground(x, y) or in_solid(x, y):
            continue
        proto = pick(TIER3_MIX)
        if not deep_oob(x, y) and PROTOS[proto]["h"][0] > CORE_CAP:
            proto = pick(SHORT_SCRUB)
        lo, hi = PROTOS[proto]["h"]
        h = rng.uniform(lo, hi)
        if not deep_oob(x, y):
            h = min(h, CORE_CAP)
        out.append({"scope": "CornerOvergrowth", "proto": tiered(proto, x, y),
                    "rot": [rng.gauss(0, 3.2), rng.gauss(0, 3.2), rng.uniform(0, 360)],
                    "scale": scale_for(proto, h,
                                       wide=rng.uniform(0.88, 1.16),
                                       narrow=rng.uniform(0.88, 1.16)),
                    "pos": [x, y, z]})
        n_scrub += 1

    # ---- LAYOUT 6.3 cover mass at (+38,-13) -----------------------------
    # This is the single most conspicuous plant in the map: it stands 17 m from
    # the SILHOUETTE_WEST eye and fills the lower-left quarter of that frame.
    # Round 3 built it as SEVEN scrub on a 0.9-2.0 m circle, two of them 2.4 and
    # 2.85 m elder - a hemisphere of leaves that read as a suburban hedge
    # dropped on a dock apron, and (because of the shader-name bug above) at
    # full nursery saturation.
    #
    # Rebuilt as a ragged ruderal thicket ALONG the broken slab edge instead of
    # a ball around a point: an 8 m E-W run, an explicit sawtooth height profile
    # that never repeats, one tall elder for the silhouette break rather than
    # two, dark needle species carrying most of the mass, and dead-standing rank
    # grass through the gaps. Cover height stays above the 0.90 m the cover
    # schedule requires; the ceiling comes down from 2.85 m to 2.15 m, which is
    # much closer to the "nothing in the playable core over 1.4 m" rule in
    # LAYOUT section 0 that section 6.3 contradicts.
    east_pool.sort(key=lambda r: math.hypot(r["pos"][0] - EAST_SCRUB_ANCHOR[0],
                                            r["pos"][1] - EAST_SCRUB_ANCHOR[1]))
    # ROUND 6: the two conifers that carried half this mass are gone. It is
    # rebuilt from wild privet (three sizes, one of them half dead) and elder,
    # which is what actually seeds itself into a broken dock apron here. The
    # sawtooth height profile and the 8 m E-W run are unchanged - they were not
    # what was wrong with it.
    EAST_MASS = [
        # dx,   dy,  proto,             height
        (-3.9, -0.7, "ScrubPrivetLow",  1.05),
        (-2.6,  0.8, "ScrubPrivetDry",  0.94),
        (-1.7, -1.3, "ScrubPrivet",     1.62),
        (-0.5,  0.3, "ScrubElder",      2.15),
        ( 0.8, -1.1, "ScrubPrivetLow",  0.88),
        ( 1.9,  0.9, "ScrubPrivet",     1.34),
        ( 2.7, -0.6, "ScrubPrivetDry",  1.44),
        ( 4.1,  0.5, "ScrubPrivetLow",  0.96),
    ]
    for dx, dy, proto, h in EAST_MASS:
        px = EAST_SCRUB_ANCHOR[0] + dx + rng.gauss(0, 0.22)
        py = EAST_SCRUB_ANCHOR[1] + dy + rng.gauss(0, 0.22)
        z = gz.z(px, py)
        if z is None:
            continue
        out.append({"scope": "CornerOvergrowth", "proto": tiered(proto, px, py),
                    "rot": [rng.gauss(0, 4), rng.gauss(0, 4), rng.uniform(0, 360)],
                    "scale": scale_for(proto, h * rng.uniform(0.93, 1.07),
                                       wide=rng.uniform(0.86, 1.20),
                                       narrow=rng.uniform(0.86, 1.20)),
                    "pos": [px, py, z - 0.05]})
        n_scrub += 1
    # dead-standing rank grass through the thicket, so the mass is not all leaf
    for _ in range(14):
        px = EAST_SCRUB_ANCHOR[0] + rng.uniform(-4.6, 4.8)
        py = EAST_SCRUB_ANCHOR[1] + rng.gauss(0, 1.15)
        z = gz.z(px, py)
        if z is None:
            continue
        proto = pick({"RankSwitchDry": 0.42, "RankSwitch": 0.22,
                      "RankTuft": 0.20, "RankMatB": 0.16})
        lo, hi = PROTOS[proto]["h"]
        out.append({"scope": "CornerOvergrowth", "proto": proto,
                    "rot": [rng.gauss(0, 4), rng.gauss(0, 4), rng.uniform(0, 360)],
                    "scale": scale_for(proto, rng.uniform(lo, hi) * rng.uniform(0.7, 1.25),
                                       wide=rng.uniform(0.82, 1.24),
                                       narrow=rng.uniform(0.82, 1.24)),
                    "pos": [px, py, z - rng.uniform(0.02, 0.06)]})
        n_scrub += 1
    print(f"scrub: {n_scrub}")

    # ---- ground debris: authored drift positions, re-decided -------------
    # ROUND 6. The seed file holds 1509 authored debris positions and 1440 of
    # them were AUTUMN LEAF DRIFT - fallcluster1/2, oakfall1/2, maplefall1 -
    # laid down the lee (ENE) side of every windward face, in the trench drain,
    # and across the DETAIL_WET_APRON foreground. That is a whole season in the
    # wrong place and it is the third of the three continuity breaks the critic
    # named.
    #
    # The POSITIONS are good and are kept: they came from a wind-lee model and
    # they are exactly where windblown material actually piles up. What sits at
    # them changes. Aeolian deposition in August delivers grit, silt and dead
    # grass, so:
    #   45% -> a piece of half-buried grit (80-140 mm, all ten rock variants)
    #   25% -> a dry-grass tuft, the same drift the leaves were modelling
    #   30% -> nothing. The old dressing was too dense to read as accumulation.
    # A drift tuft is real geometry, not a decal, so two of them 20 mm apart is
    # one tuft costing twice the triangles - the same rule the clump children
    # already obey. Existing tier-1 tufts are seeded into the grid first so a
    # drift tuft never lands on top of a clump either.
    n_grit = n_drift = 0
    DCELL = 0.5
    dgrid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for r in out:
        if r.get("scope") == "CrackWeeds":
            gx, gy = r["pos"][0], r["pos"][1]
            dgrid.setdefault((int(gx // DCELL), int(gy // DCELL)), []).append((gx, gy))

    def drift_clear(px, py, rmin=0.16):
        i0, j0 = int(px // DCELL), int(py // DCELL)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (qx, qy) in dgrid.get((i0 + di, j0 + dj), ()):
                    if (qx - px) ** 2 + (qy - py) ** 2 < rmin * rmin:
                        return False
        dgrid.setdefault((i0, j0), []).append((px, py))
        return True

    for r in inst:
        if r["scope"] != "LeafLitter":
            continue
        if r["asset"] not in LEGACY_LITTER and r["asset"] not in ROCKS:
            continue
        x, y = r["pos"][0], r["pos"][1]
        base = gz.z(x, y)
        if base is None:
            base = r["pos"][2]
        if r["asset"] in ROCKS:
            roll = 0.0                     # an authored stone stays a stone
        else:
            roll = rng.random()
        if roll < 0.45:
            s = rng.uniform(0.0053, 0.0092) if r["asset"] in LEGACY_LITTER \
                else r["scale"][2]
            a = r["asset"] if r["asset"] in ROCKS \
                else f"rock_small_{rng.randint(1, 10):02d}"
            sc = ([s * rng.uniform(0.9, 1.15), s * rng.uniform(0.9, 1.15), s]
                  if r["asset"] in LEGACY_LITTER else r["scale"])
            sc = [_clamp(v) for v in sc]      # the seed predates the band check
            out.append({"scope": "GroundGrit", "asset": a, "rot": r["rot"],
                        "scale": sc, "pos": [x, y, base - rock_sink(sc[2])]})
            n_grit += 1
        elif roll < 0.70 and drift_clear(x, y):
            proto = pick({"TuftFineDry": 0.42, "TuftSparseDry": 0.34,
                          "MatBroadDark": 0.14, "TuftFine": 0.10})
            out.append({"scope": "CrackWeeds", "proto": proto,
                        "rot": [rng.gauss(0, 3), rng.gauss(0, 3),
                                rng.uniform(0, 360)],
                        "scale": tuft_scale(proto, h_mul=rng.uniform(0.55, 1.15),
                                            elongate=rng.random() < 0.7),
                        "pos": [x, y, base - rng.uniform(0.008, 0.030)]})
            n_drift += 1
    out += litter_extra
    print(f"ground debris: {n_grit} grit from authored drift + {n_drift} dry "
          f"drift tufts + {len(litter_extra)} grit at new weed clumps "
          f"(0 autumn leaves - the asset family is not used)")

    # ---- trees ----------------------------------------------------------
    trees = build_trees(gz)
    out += trees

    # ---- near-camera safety net -----------------------------------------
    fixed = 0
    for r in out:
        if "proto" not in r:
            continue
        d = dist_detail(r["pos"][0], r["pos"][1])
        h = height_of(r["proto"], r["scale"][2])
        cap = 0.14 if d < 5.0 else (0.18 if d < DETAIL_NEAR else
                                    (0.45 if d < DETAIL_MID else None))
        if cap is None or h <= cap:
            continue
        proto = pick(TIER1_TINY)
        r["proto"] = proto
        lo, hi = PROTOS[proto]["h"]
        r["scale"] = scale_for(proto, min(hi, cap) * rng.uniform(0.62, 0.98),
                               wide=rng.uniform(1.05, 1.4),
                               narrow=rng.uniform(0.8, 0.98))
        fixed += 1
    print(f"near-camera cap applied to {fixed} instance(s)")

    grade_audit(sorted({r["proto"] for r in out if "proto" in r},
                       key=lambda k: list(PROTOS).index(k)))
    audit(out)
    write(out)


def grade_audit(used):
    """Print the EFFECTIVE linear albedo of every leaf grade actually emitted.

    This exists because round 5's grade was wrong in a way that no amount of
    reading the source revealed: the numbers looked plausible in the table and
    came out of the shader as a 4.6x blue multiply. So the audit now computes
    what the renderer will actually see - linear texture mean, desaturated,
    times the emitted tint - and prints B/R and saturation for it. Two rules,
    and a violation of either is a build error, not a note:

      * B/R must stay in 0.38 .. 1.15. Foliage is never blue; the old far tier
        ran to 2.44. The floor is loose because straw legitimately has almost no
        blue in it - the ceiling is the one that matters.
      * saturation must FALL with distance, never rise. Aerial perspective takes
        chroma out. The old tiers put it in: 0.29 near, 0.43 mid, 0.59 far.
    """
    print("\neffective LINEAR albedo of every emitted leaf grade:")
    bad = []
    tiers: dict[str, list[float]] = {"near": [], "_M": [], "_F": []}
    for name in used:
        for mat, m in PROTOS[name]["mats"].items():
            if "_leaf" not in m:
                continue
            a = LEAF_LIN[mat]
            L = _lum(a)
            d = m["desat"]
            c = [x + d * (L - x) for x in a]
            eff = [x * t for x, t in zip(c, m["tint"])]
            e = _lum(eff)
            sat = (max(eff) - min(eff)) / max(max(eff), 1e-9)
            br = eff[2] / max(eff[0], 1e-9)
            tier = "_F" if name.endswith("_F") else ("_M" if name.endswith("_M") else "near")
            tiers[tier].append(sat)
            flag = ""
            if not (0.38 <= br <= 1.15):
                flag = "  <-- BLUE/RED OUT OF RANGE"
                bad.append(f"{name}/{mat}: B/R {br:.2f}")
            print(f"  {name:22s} {mat:26s} alb {e:.4f} "
                  f"rgb ({eff[0]:.4f},{eff[1]:.4f},{eff[2]:.4f}) "
                  f"B/R {br:4.2f} sat {sat:.2f}{flag}")
    means = {k: (sum(v) / len(v) if v else 0.0) for k, v in tiers.items()}
    print(f"mean effective saturation by distance tier: "
          f"near {means['near']:.3f}  60-100 m {means['_M']:.3f}  "
          f">100 m {means['_F']:.3f}")
    if means["_M"] > means["near"] or means["_F"] > means["_M"]:
        bad.append("saturation rises with distance - aerial perspective is inverted")
    if bad:
        raise SystemExit("GRADE AUDIT FAILED:\n  " + "\n  ".join(bad))


def audit(out):
    counts = Counter(r.get("proto") or r["asset"] for r in out)
    print(f"\nresult: {len(out)} instances, {len(counts)} distinct prototypes/assets")
    for k, v in counts.most_common():
        if k in PROTOS:
            hs = [height_of(k, r["scale"][2]) for r in out if r.get("proto") == k]
            print(f"  {v:5d}  {k:16s} {PROTOS[k]['asset']:18s} h {min(hs):.2f}-{max(hs):.2f} m")
        else:
            print(f"  {v:5d}  {k}")

    t1 = [r for r in out if r["scope"] == "CrackWeeds"]
    print(f"\ntier-1 exterior {len(t1)}, max height "
          f"{max(height_of(r['proto'], r['scale'][2]) for r in t1):.3f} m")
    near = [r for r in out if "proto" in r and dist_detail(*r["pos"][:2]) < DETAIL_NEAR]
    print(f"within {DETAIL_NEAR} m of DETAIL_WET_APRON: {len(near)} plants, max "
          f"{max((height_of(r['proto'], r['scale'][2]) for r in near), default=0):.3f} m, "
          f"{len(set(r['proto'] for r in near))} distinct protos")
    # nearest-neighbour spacing of the detail-camera tufts: the round-2 failure
    # was an almost constant interval, so report the spread, not the mean.
    pts = sorted((dist_detail(*r["pos"][:2]), r["pos"][0], r["pos"][1])
                 for r in out if r["scope"] == "CrackWeeds"
                 and dist_detail(*r["pos"][:2]) < 18.0)
    if len(pts) > 4:
        P = np.asarray([[p[1], p[2]] for p in pts])
        D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
        np.fill_diagonal(D, 1e9)
        nn = D.min(1)
        print(f"detail-field tuft nearest-neighbour: n={len(nn)} "
              f"min {nn.min():.2f} median {np.median(nn):.2f} max {nn.max():.2f} m "
              f"(cv {nn.std() / nn.mean():.2f})")

    tr = [r for r in out if r["scope"] == "TreeLines" and r.get("proto", "").startswith("Tree")]
    hs = sorted(height_of(r["proto"], r["scale"][2]) for r in tr)
    print(f"trees: {len(tr)}, heights {hs[0]:.1f}-{hs[-1]:.1f} m, "
          f"{len(set(r['proto'] for r in tr))} protos")
    south = sorted(r["pos"][0] for r in tr if r["pos"][1] < -45.0)
    gaps = [round(south[i + 1] - south[i], 1) for i in range(len(south) - 1)]
    print(f"  south row X gaps: {gaps}")

    bad = [r for r in out if not all(BAND_LO * 0.98 < abs(s) < 0.02 for s in r["scale"])]
    print(f"instances outside validate.py's 0.005..0.02 scale band: {len(bad)}")

    # ---- aerial-perspective tiers ---------------------------------------
    tiers = Counter("_F" if r.get("proto", "").endswith("_F") else
                    ("_M" if r.get("proto", "").endswith("_M") else "near")
                    for r in out if r.get("proto", "") and
                    r["proto"].rstrip("_MF").startswith(("Tree", "Scrub")) or
                    r.get("proto", "").startswith(("Tree", "Scrub")))
    print(f"woody aerial tiers: {dict(tiers)}")

    # ---- DOES THE SCATTER ACTUALLY SIT ON EDGES? -------------------------
    # "Weeds belong in cracks, the margin and the ballast, not scattered evenly
    # across open ground" is checkable, not a matter of opinion: measure each
    # tuft's distance to the nearest point of the authored edge network, and the
    # nearest-neighbour spacing across the whole scatter. Even scatter has a
    # tight, high-mean nearest-neighbour distribution; clustered growth on edges
    # has a low median with a long tail.
    if EDGE_XY:
        E = np.asarray(EDGE_XY)
        CELL = 1.0
        bins: dict[tuple[int, int], list[int]] = {}
        ij = np.floor(E / CELL).astype(np.int64)
        for k in range(len(E)):
            bins.setdefault((int(ij[k, 0]), int(ij[k, 1])), []).append(k)

        def d_edge(x, y):
            i0, j0 = int(math.floor(x / CELL)), int(math.floor(y / CELL))
            best = 1e18
            for r in range(6):
                for di in range(-r, r + 1):
                    for dj in range(-r, r + 1):
                        if max(abs(di), abs(dj)) != r:
                            continue
                        for k in bins.get((i0 + di, j0 + dj), ()):
                            best = min(best, (E[k, 0] - x) ** 2 + (E[k, 1] - y) ** 2)
                if best < (r * CELL) ** 2:
                    break
            return math.sqrt(best)

        for scope in ("CrackWeeds", "RankWeeds", "CornerOvergrowth"):
            S = [r for r in out if r["scope"] == scope]
            if not S:
                continue
            d = np.asarray([min(d_edge(r["pos"][0], r["pos"][1]), 99.0) for r in S])
            print(f"{scope}: n={len(S)} distance to authored edge network "
                  f"median {np.median(d):.2f} m, 90th pct {np.percentile(d, 90):.2f} m, "
                  f"frac >2 m from any edge {(d > 2.0).mean():.3f}")

        # THE question the critic asked: is anything scattered across open,
        # in-bounds, driven-on ground? Weeds belong in the cracks, the OOB
        # margin and the ballast. A plant standing on open yard or dock apron
        # more than 1.5 m from any authored crack, seam, kerb, drain, puddle
        # margin or building foot is a scatter artefact, and there should be
        # none of them.
        loose = [r for r in out if "proto" in r
                 and (in_yard(r["pos"][0], r["pos"][1])
                      or in_dock_lane(r["pos"][0], r["pos"][1]))
                 and d_edge(r["pos"][0], r["pos"][1]) > 1.5]
        print(f"plants on open in-bounds ground >1.5 m from any authored edge: "
              f"{len(loose)}"
              + (f"  e.g. {[(round(r['pos'][0],1), round(r['pos'][1],1)) for r in loose[:6]]}"
                 if loose else ""))

        P = np.asarray([r["pos"][:2] for r in out if r["scope"] == "CrackWeeds"])
        if len(P) > 8:
            CELL2 = 4.0
            b2: dict[tuple[int, int], list[int]] = {}
            ij2 = np.floor(P / CELL2).astype(np.int64)
            for k in range(len(P)):
                b2.setdefault((int(ij2[k, 0]), int(ij2[k, 1])), []).append(k)
            nn = np.empty(len(P))
            for k in range(len(P)):
                i0, j0 = int(ij2[k, 0]), int(ij2[k, 1])
                best = 1e18
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        for q in b2.get((i0 + di, j0 + dj), ()):
                            if q == k:
                                continue
                            best = min(best, (P[q, 0] - P[k, 0]) ** 2
                                       + (P[q, 1] - P[k, 1]) ** 2)
                nn[k] = math.sqrt(best) if best < 1e17 else CELL2 * 1.5
            print(f"CrackWeeds nearest-neighbour: median {np.median(nn):.2f} m "
                  f"p05 {np.percentile(nn, 5):.2f} p95 {np.percentile(nn, 95):.2f} "
                  f"cv {nn.std() / nn.mean():.2f}  (cv near 0.2 = an even comb, "
                  f"above 0.6 = clustered growth)")

    # ---- nothing tall inside the playable core ---------------------------
    tall = [r for r in out if "proto" in r
            and height_of(r["proto"], r["scale"][2]) > 1.45
            and not deep_oob(r["pos"][0], r["pos"][1])]
    far = [r for r in tall
           if math.hypot(r["pos"][0] - EAST_SCRUB_ANCHOR[0],
                         r["pos"][1] - EAST_SCRUB_ANCHOR[1]) > 6.0]
    print(f"plants over 1.45 m inside the playable core: {len(tall)} "
          f"({len(tall) - len(far)} of them the LAYOUT 6.3 cover mass at "
          f"{EAST_SCRUB_ANCHOR}, max "
          f"{max((height_of(r['proto'], r['scale'][2]) for r in tall), default=0):.2f} m)"
          + (f"  OUTSIDE that mass: {len(far)} -> "
             f"{[(round(r['pos'][0],1), round(r['pos'][1],1)) for r in far[:6]]}"
             if far else "  none outside that mass"))


# ---------------------------------------------------------------------------
# 7. emit
# ---------------------------------------------------------------------------
SCOPE_DOC = {
    "CrackWeeds": ("weeds", "crack_seam_weeds",
                   "Tier 1, 0.06-0.28 m. Re-sampled as a variable-radius cluster process ON the "
                   "authored edge network rather than scattered and thinned: parents 1.35-7.0 m "
                   "apart, 1-5 children per clump offset along the seam, 72% of a clump one "
                   "prototype. Twelve prototypes over six grass assets, graded apart, so the row of "
                   "identical green balls is gone. Tufts are stretched 1.14-1.46x along the crack "
                   "they root in."),
    "InteriorIngress": ("weeds", "interior_ingress",
                        "Tier 1 interior, 0.07-0.15 m plus tracked-in grit. Rejection-sampled "
                        "against 10_terrain: an instance exists only within 0.40 m of an authored "
                        "slab joint, 0.35 m of a water-ingress fan, 0.55 m of a wall foot or 0.80 m "
                        "of a door threshold, AND never within 0.60 m of a worn traffic path, AND "
                        "never in the A3 through-lane. Darker prototypes than outdoors - it grows "
                        "in a warehouse."),
    "RankWeeds": ("weeds", "rank_weeds",
                  "Tier 2, 0.12-0.98 m. Rank growth confined to ground nothing drives on: the OOB "
                  "margin, the fence lines, the rail ballast, the drainage ditch, the far "
                  "service-road verge and the two yard corners. Excluded from a 20 m radius around "
                  "the DETAIL_WET_APRON eye. Mixed live and dead-standing prototypes."),
    "CornerOvergrowth": ("shrub", "corner_overgrowth",
                         "Tier 3, 0.6-3.3 m. Self-seeded elm, birch, elder and wild privet in dead "
                         "ground only - the species that actually colonise derelict industrial land "
                         "in a cold northern maritime climate. Yew and Juniper were removed in "
                         "round 6: they are nursery conifers, they shared the one pale Pine_needles "
                         "atlas, and they were half of what read as ice-blue conifer mass in "
                         "SILHOUETTE_WEST. Barberry went earlier for the same class of reason - a "
                         "GOLDEN cultivar, a 1.5 m acid-yellow bush. Never inside the playable "
                         "core, never on a lane."),
    "GroundGrit": ("debris", "ground_grit",
                   "Half-buried grit and stone, 80-190 mm, on the lee (ENE) side of every windward "
                   "face, in the trench drain and at the weed lines. Round 6 replaced 1440 autumn "
                   "leaf drifts with this: the drift POSITIONS were right - they came from a "
                   "wind-lee model - but crisp orange oak and maple leaves put the level in "
                   "October while the sky, the grass and the trees put it in August."),
    "TreeLines": ("tree", "tree_line",
                  "LAYOUT 5.19 rebuilt as broken bands. South: 11 clumps of 2-4 over X -68..+58 "
                  "with two deliberate long gaps (X -34..-18, X +8..+30) and a 7 m deep Y band. "
                  "West: 10 clumps on X ~ -73 with the load-bearing 16.4 m poplar pinned at "
                  "(-73.0, +6.0) so it still clips the sun disc at 121 m in SILHOUETTE_WEST. "
                  "ONE SEASON, late summer: no *_Fall asset anywhere, and Honey Locust removed in "
                  "round 6 because half of its one leaf atlas is orange autumn foliage. Lombardy "
                  "poplar (LAYOUT), red ash, gray birch, hawthorn and fraxinus mixed so the profile "
                  "changes along the row, with elder/elm/birch/privet scrub and rank tufts at the "
                  "foot of every clump."),
}
SCOPE_ORDER = ["CrackWeeds", "InteriorIngress", "RankWeeds", "CornerOvergrowth",
               "GroundGrit", "TreeLines"]

HEADER = '''#usda 1.0
(
    doc = "DEADFALL DEPOT module: vegetation - crack weeds, rank growth, self-seeded scrub, organic debris and the poplar/oak tree lines. Owned by one specialist agent - do not edit from another module. GENERATED by tools/gen_vegetation.py; regenerate rather than hand-editing."
    metersPerUnit = 1
    upAxis = "Z"
)

# DEADFALL DEPOT - VEGETATION
#
# Concept: a derelict distribution depot in a cold northern maritime climate.
# Nothing here is landscaping and nothing here is decorative. Every instance is
# ruderal - it sits where water collects and nothing drives: kerb feet, slab
# joints, wall bases, column footings, drain lips, fence lines, rail ballast.
# Mid-lane asphalt is deliberately bare; that is what makes the edges read.
#
# SEASON: LATE-SUMMER STORM BREAK. One season, held everywhere. Green going dry:
# live growth is a dull olive, a third of the ground layer is drought-burnt to
# straw, the wet shaded edges carry moss. There is no blossom in this map, no
# autumn colour in this map, no *_Fall asset and no fall-leaf debris.
#
# ===========================================================================
# ROUND 6 - THE MAP WAS IN THREE SEASONS AT ONCE, AND ALL THREE WERE THIS FILE
# ===========================================================================
# The three continuity breaks the critic named, and what each one actually was.
#
# 1. THE "PINK-WHITE BLOSSOMING ORNAMENTAL (CHERRY)" MID-RIGHT IN
#    LANE_EYE_YARD is the Black Oak corner anchor at (68.4, -49.6), 112 m out,
#    projected to px 1646 of that frame. Its emitted diffuse_tint was
#    (0.1196, 0.1243, 0.5554) - a 4.6x blue boost - and its canopy pixels
#    measured rgb (0.381, 0.381, 0.461), blue-dominant, luminance 0.387 against
#    a sky of 0.315.
#
#    THE CAUSE WAS A COLOUR-SPACE ERROR. Round 5 measured every leaf texture's
#    mean in sRGB and solved a per-channel target/albedo ratio from it.
#    diffuse_tint multiplies LINEAR values. The oak basecolor is sRGB
#    (0.351, 0.449, 0.109) - blue looks like 24% of green - but linear it is
#    (0.1018, 0.1703, 0.0123), blue is 7% of green. The solve divided into a
#    number seven times smaller than it believed and asked for a 4.6x blue
#    multiply; OmniPBR runs albedo_desaturation BEFORE the tint, lifting the
#    leaf's near-zero blue to the leaf's luminance first, and the multiply landed
#    on that. Green leaf in, lilac out. All albedo tables in the generator are
#    LINEAR now and the grade no longer solves a per-channel ratio at all.
#
# 2. THE "PALE ICE-BLUE CONIFERS" FILLING SILHOUETTE_WEST were two things. There
#    were conifers - Yew and Juniper, sharing one pale Pine_needles atlas - and
#    they are removed; nursery conifers do not colonise a derelict depot in this
#    climate. Most of that mass, though, is the LAYOUT 5.19 WEST POPLAR BAND, at
#    effective albedo B/R 2.00-2.22. The aerial-perspective tiers were stacking a
#    cool per-channel bias on the broken ratio, so measured effective saturation
#    ROSE with distance - 0.29 near, 0.43 at 60-100 m, 0.59 past 100 m - which is
#    aerial perspective running backwards. It now falls: 0.385 / 0.296 / 0.231,
#    and no leaf grade in the map has B/R above 1.12.
#
# 3. "DETAIL_WET_APRON IS SCATTERED WITH ORANGE AUTUMN OAK LEAVES" was literally
#    true and was not a grade problem. 1440 instances of the
#    Assets/Vegetation/Debris/ fall-drift family were dressed across the yard,
#    the kerbs and that shot's foreground; the family's one shared basecolor is a
#    sheet of crisp intact autumn oak and beech leaves and no grade turns that
#    into something else. The whole family is gone from the map. The drift
#    POSITIONS were good - they came from a wind-lee model - so they now carry
#    half-buried grit and dry-grass drift, which is what actually accumulates on
#    the lee of a wall in August.
#
# Also this round: Honey Locust removed (half of its single leaf atlas is orange
# autumn foliage on a golden ground), Gray Birch added as the self-seeded
# sapling that actually colonises derelict industrial land, low and half-dead
# wild privet added to carry the LAYOUT 6.3 cover mass and the in-core height
# cap that the conifers used to, and a grade_audit() BUILD GATE that recomputes
# what the renderer will see and fails the build if any leaf is blue-dominant or
# if saturation rises with distance.
#
# ===========================================================================
# ROUND 5 - THE FOLIAGE WAS TWO TO FOUR TIMES TOO BRIGHT, MEASURED
# ===========================================================================
# The critic's note this round was that the tree band reads as "opaque pale
# cream cones brighter than the sky", and it is correct about the vegetation
# even though it is wrong about which pixels. Two measurements settle both
# halves of that.
#
# 1. WHERE THE HERO SKYLINE CONES COME FROM: NOT THIS MODULE. Projecting every
#    instance in this file into HERO_ESTABLISH's actual camera (eye
#    (-33,-36,19), rotateXYZ (75.86,0,331.1) as authored in 90_cameras, not the
#    LAYOUT 7 value) puts ZERO trees in frame - the nearest woody prims are
#    ScrubElm/Elder at 104-131 m behind the warehouse, entirely occluded by it.
#    The row of pale faceted cones along the HERO and DETAIL_WET_APRON skyline
#    is 20_architecture's roof furniture: the `Cowl*_body` / `Vent*_cowl` prims,
#    which are cone-on-a-kerb geometry sitting on the warehouse roof and the
#    dock canopy. They are the brightest sunlit thing on the roofline and they
#    are what reads as tents. That is reported, not edited - it is not my file.
#
# 2. WHERE THE MODULE IS GUILTY: THE ABSOLUTE ALBEDO. Rendering the module
#    alone against the dome (everything else sublayered out) and measuring the
#    band above the horizon in SILHOUETTE_WEST gave a canopy median luminance of
#    0.320 against a sky median of 0.326, a canopy p90 of 0.683, and a mean
#    canopy colour of (0.415, 0.352, 0.264) - warm cream - against a sky of
#    (0.195, 0.342, 0.637). Half of every canopy pixel was brighter than the sky
#    behind it. In the same frame the storm HDRI's own horizon treeline measures
#    0.028. Auditing the grade explained it: rounds 3-4 set foliage LEVEL with a
#    relative multiplier and never checked the absolute albedo that came out.
#    Grass was landing at 0.31-0.42 effective albedo luminance and trees at
#    0.17-0.32, against real reflectances of 0.10-0.15 (fresh grass),
#    0.18-0.25 (dead straw) and 0.12-0.18 (deciduous canopy) - and everything
#    here is wet, which takes another quarter off.
#    So `leaf(..., alb=X)` now states the target albedo directly and solves the
#    tint to hit it, the tree grade carries a COOL bias instead of a warm one,
#    and the aerial tiers scale that stated albedo (x0.70 at 60-100 m, x0.46
#    beyond 100 m) with a cool push that reaches B/R = 2.0 at the far tier.
#
# 3. THE FOREGROUND STONE WAS AN UNTEXTURED PLACEHOLDER, AND IT WAS MINE. The
#    pale featureless block in DETAIL_WET_APRON is `D_rock_small_*` from this
#    module: measured at luminance 0.460 sitting on aggregate of 0.312, the
#    brightest object in the near field. Three separate settings made it one -
#    diffuse_tint 0.74 (a wet granite cobble is 0.15-0.22), roughness 0.90 flat
#    across the whole stone, and bump_factor 0.35 which threw away the normal
#    map. The asset ships a basecolor, a normal AND an ORM and all three
#    resolve. It is now graded to 0.20 with a cool wet bias, roughness 0.62, and
#    its normal map at full strength; and it is BEDDED 38-62% of its own height
#    into the ground instead of the flat 5-30 mm every piece of litter used to
#    get, which for a 190 mm cobble was a stone resting on the tarmac.
#
# 4. MOSS EXISTS NOW. LAYOUT 7.4 lists "moss in the drain" as one of the four
#    things DETAIL_WET_APRON is judged on and there was none in the map. Damp
#    edges - puddle rims, the dock-foot algae band, both trench drains - now
#    carry a MossMat community: 46-85 mm mats (round 6 restates the level as a
#    LINEAR 0.023 / 0.015 / 0.026 albedo across the three moss protos), the
#    darkest and greenest thing in the grade, laid thickest inside the detail
#    camera's field. ~1200 instances. Round 6 also took most of the chroma out
#    of MossOlive - at 3x in DETAIL_WET_APRON it was reading as acid-yellow
#    paint splodges along the kerb, which is the same over-saturation failure as
#    the tree band, 3 m from the lens instead of 120.
#
# 5. FIREFLY / DETAIL, MEASURED ON A FROZEN LEVEL. Because three other modules
#    were being rewritten during this pass, the A/B was run against a snapshot
#    of all ten layers copied aside, rendering the same frozen stage with and
#    without this file. With vegetation: LANE_EYE_YARD detail_density 0.075 vs
#    0.078 without, firefly 0.00011 vs 0.00013 - i.e. this module now costs the
#    firefly gate nothing. SILHOUETTE_WEST detail_density 0.133 vs 0.060 and
#    dead_area_frac 0.002 vs 0.284: on that frame the vegetation is the single
#    largest source of surface detail in the level and it is what stops the
#    frame being a third empty. The remaining SILHOUETTE_WEST firefly delta
#    (0.0011 vs 0.0002) survives every material change tried - specular_level 0,
#    bump 0, roughness 0.95 - and halves under `render.py --ss 2`, which says it
#    is sub-pixel geometric aliasing of leaf edges against a bright sky, not a
#    material. See the report: that one needs supersampling in shots.json.
#
# ===========================================================================
# ROUND 4 - WHAT CHANGED AND WHY. Read this before judging the tree lines.
# ===========================================================================
# 1. THE ROUND-3 GRADE WAS HALF DISCARDED, AND THIS IS WHY THE FOLIAGE STILL
#    READ WRONG. It was authored as
#        over "Looks" { over "<Material>" { over "Shader" { ... } } }
#    which assumes the shader prim inside every material is named "Shader".
#    In this library that is asset-dependent: Blue_Berry_Elder, Switchgrass,
#    Red_Ash, Honey_Locust, Hawthorn and Fraxinus name the shader after its own
#    material (Looks/HollyPrivet_Mat/HollyPrivet_Mat), the leaf debris hides it
#    under <name>/Looks/fallleaves/Shader, and the rocks under rock/material -
#    with rock_small_04 shipping that scope misspelled "iock". `over` on a name
#    that does not exist is legal USD: it makes an EMPTY prim and overrides
#    nothing. 14 of 43 targets were no-ops. The elder cover mass 17 m from the
#    SILHOUETTE_WEST eye therefore kept its nursery albedo and was the only
#    green object in a blue-and-amber frame. Shader paths are now resolved from
#    the assets themselves and an unresolvable target is a hard build error.
#
# 2. THESE TREES ARE NOT BILLBOARD CARDS. Measured point counts:
#    Lombardy_Poplar 429,469 over 2 meshes; Blue_Berry_Elder 219,910;
#    Red_Ash 64,375; Black_Oak 48,701. Real branch and cross-plane leaf
#    geometry. What made them read flat was albedo, value and the absence of
#    aerial perspective - not the mesh - so that is what was fixed.
#
# 3. AERIAL PERSPECTIVE IS AUTHORED PER INSTANCE. Every woody prototype has _M
#    (60-100 m) and _F (beyond 100 m) twins: more saturation removed, value
#    dropped to 72% and 50%, residue pushed cool. Distance is measured to the
#    nearest camera in 90_cameras.usda that is actually FACING the plant -
#    HERO_ESTABLISH stands 23 m from the south poplar band and looks the other
#    way, so it must not drag that band into the near tier. The camera list is
#    parsed at generation time, so if the shot list moves, the grade follows.
#
# 4. THE FIREFLY GATE WAS THIS MODULE'S. LANE_EYE_YARD rendered with and
#    without this layer sublayered in measured firefly_frac 0.01073 against
#    0.00063: 94% of the path-trace outliers in that frame were vegetation, and
#    the map of them was the ground plane, i.e. the tuft scatter. The library
#    ships these materials at specular_level 0.5, bump_factor 0.5 and
#    reflection_roughness_texture_influence 1.0 - so the authored roughness
#    constant did nothing at all, and a two-pixel grass blade under a sodium
#    lamp threw isolated highlights. Fixed at source as the BRIEF requires
#    (specular_level 0.05, roughness constant honoured, bump 0.35, metallic
#    pinned to 0), not by touching the denoiser. Adjacent with/without renders
#    now differ by 0.0002 or less.
#
# ---------------------------------------------------------------------------
# 1. PROTOTYPE LIBRARY  (/World/Vegetation/_Protos)
# ---------------------------------------------------------------------------
# The library ships ONE grass family: Grass_Short_A/B/C and Grass_Trimmed_A/B/C
# are six sizes of the same disc of blades and all six bind the SAME material,
# lawngrass_a_mat. Choosing between them is not choosing between prototypes, and
# a scatter built from them reads as one asset repeated - which is exactly what
# the round-2 frame showed along the DETAIL_WET_APRON kerb.
#
# So the prototypes are authored, not chosen. Each `class` prim under _Protos
# references one asset AND overrides that asset's OmniPBR leaf shader. One asset
# therefore yields several genuinely different reads - live olive, burnt straw,
# dark spreading mat - and the same mechanism pulls the whole palette down off
# nursery green.
#
# HOW THE GRADE IS APPLIED, and a finding other modules should know about.
# All of these library materials are `export material X(*) = OmniPBR(...)`, so
# every OmniPBR parameter is settable from USD. Probe 1 - the whole proto
# library forced to albedo_desaturation 1.0 with diffuse_tint (0.9,0.15,0.15) -
# rendered the tufts dark red, which PROVES the override path is live in ovrtx
# rather than assumed. Probe 2 - the same frame at albedo_desaturation 0.0 and
# then 1.0 with the tint pinned to (1,1,1) - moved the canopy only from
# (0.157,0.203,0.188) to (0.169,0.180,0.226). So albedo_desaturation moves the
# right way but is far too weak to BE the grade in this build; 20_architecture
# leans on it heavily and may be getting less than it thinks.
# ROUND 6 REVERSES THAT CONCLUSION, because the per-channel solve it argues for
# is exactly what turned the black oak lilac (see the top of this file). The two
# operators have swapped jobs and the split is now:
#     albedo_desaturation  = SATURATION. Luminance-preserving, monotone,
#                            per texel, and structurally incapable of inverting
#                            a hue. Weak, yes - so it is used at 0.4-0.8, not
#                            at 0.30 with the real work done elsewhere.
#     diffuse_tint         = LEVEL. One scalar v = alb / luminance(LINEAR
#                            texture mean), times a luminance-neutral hue lean
#                            that is clamped in _hue() with a hard ceiling on
#                            blue.
# The measurement below is kept for the record but note the units: these are
# sRGB texel means, and reading them as linear albedo is what produced the
# 4.6x blue multiply. The generator's live table (LEAF_LIN) is linear.
#
# Measured source leaf albedo saturation, sRGB texel means:
#     lawngrass_a          0.367      (rgb 0.628 0.595 0.420)
#     fraxinus             0.370
#     red ash              0.406
#     lombardy poplar      0.472
#     honey locust         0.524
#     switchgrass          0.514
#     hawthorn             0.621
#     holly / privet       0.718
#     black oak            0.757
#     largetooth aspen     0.997  -> NOT USED ANYWHERE
# Verified on frame: a 184x42 px box on the same yard tuft in SILHOUETTE_WEST
# went from mean saturation 0.331 with 159 green-dominant pixels to 0.192 with
# 2 - the tufts are no longer green-dominant at all, they are straw-olive.
# In a derelict yard at storm dusk foliage must not be the most saturated thing
# in frame; before this pass it was, in two of the five shots.
#
# Instances stay `instanceable = true` and reference their proto by internal
# path, so all N instances of a proto still resolve to ONE USD prototype - the
# tint costs no memory. `class` prims are abstract: Hydra does not image them
# and validate.py's traversal does not see them.
#
# ---------------------------------------------------------------------------
# 2. SPECIES LIST
# ---------------------------------------------------------------------------
# The palette is deliberately narrow and deliberately dull. Flowering, desert,
# ornamental and autumn-coloured assets are banned outright:
#   Lupin, Century, Fountain_Grass_*, Prairie_Dropseed, Pampas_Grass - removed
#     in round 2 (flowering / desert / pale ornamental plumes).
#   Barberry - removed in round 3. The library asset is a GOLDEN cultivar, a
#     1.5 m acid-yellow bush, and 62 of them were standing in the map.
#   Lombardy_Poplar_Fall, Black_Oak_Fall - removed in round 4. A row of one
#     species is not half green and half orange, and the fall leaf albedo was
#     measured as the brightest, most saturated surface anywhere near the sun
#     break in SILHOUETTE_WEST. A dying poplar is built by desaturating the
#     green asset to near-grey and pushing it warm, which reads brown, not neon.
#   Largetooth_Aspen - never used; 0.997 leaf saturation.
#   Yew, Juniper - REMOVED THIS PASS. Nursery conifers in a derelict northern
#     industrial yard, sharing one pale Pine_needles atlas, and half of what the
#     critic read as "pale ice-blue conifers" in SILHOUETTE_WEST.
#   Honey_Locust - REMOVED THIS PASS. Half of its single leaf atlas is
#     orange-red AUTUMN foliage on a golden-brown ground; there is no per-half
#     override, so every honey locust in the map was carrying autumn.
#   fallcluster1/2, oakfall1/2, maplefall1 - REMOVED THIS PASS, all 1440
#     instances. One shared basecolor, a sheet of crisp intact orange autumn oak
#     and beech leaves, in a level set at a late-summer storm break.
# What is left is what actually colonises a derelict yard in this climate:
#   tier 1  Grass_Trimmed_C  0.087 m native   crack / seam tufts
#           Grass_Short_C    0.125 m
#           Grass_Trimmed_B  0.098 m
#           Grass_Short_B    0.164 m
#           Grass_Trimmed_A  0.113 m          wide low spreading mats
#           Grass_Short_A    0.162 m
#   tier 2  Switchgrass      1.372 m native, capped to 0.55-0.92 m
#   tier 3  Elm_Sapling 3.087 m, Gray_Birch 3.332 m, Blue_Berry_Elder 4.627 m,
#           Privet 1.113 m
#   trees   Lombardy_Poplar 13.671 m (LAYOUT 5.19), Red_Ash 8.435 m,
#           Gray_Birch 3.332 m, Hawthorn 8.611 m, Fraxinus 5.341 m,
#           Black_Oak 19.739 m (LAYOUT 5.19)
#   debris  rock_small_01..10 only
#
# HEIGHT CONTRACT - enforced by construction. Each instance's scale is computed
# from the species' MEASURED native height so the tier bands are real:
#   tier 1 crack weeds      0.06 - 0.28 m
#   tier 1 interior ingress 0.07 - 0.15 m
#   tier 2 rank weeds       0.12 - 0.98 m   (OOB / fence / ballast / ditch only)
#   tier 3 corner scrub     0.60 - 3.10 m   (dead ground only)
# Nothing over 1.40 m stands inside the playable core except the LAYOUT 6.3
# cover mass at (+38,-13). The centre cluster box (X -6..+14, Y -8..+6) and both
# yard walking lines hold zero vegetation.
#
# ---------------------------------------------------------------------------
# 3. OUTDOOR PLACEMENT - A CLUSTER PROCESS ON THE EDGE NETWORK
# ---------------------------------------------------------------------------
# Round 2 kept the old positions and only re-decided species, so the tufts still
# sat at an almost constant interval - six of them along the DETAIL_WET_APRON
# kerb at near-equal spacing, which reads as instanced scatter, not growth.
# Tier 1 is now generated from scratch:
#   a) candidate points are sampled ALONG the authored edge geometry itself -
#      10_terrain's PuddleMargins, both trench drains and their dressing, the
#      three kerb runs, BrokenSlabs, ManholeCovers (kept at full weight),
#      CrackNetwork and RepairSeams (kept at 30%, because a fully populated
#      crack network is dense enough to read as a lawn), plus the analytic
#      footprints of what 20_architecture builds - and each candidate carries
#      the direction of the edge it came from.
#   b) clump parents are chosen by a VARIABLE-radius Poisson process: the
#      exclusion radius is redrawn per candidate in 1.35-7.0 m, so the gaps
#      between clumps have as much variance as the clumps themselves. A fixed
#      radius produces exactly the even comb the critic counted.
#   c) each parent spawns 1-5 children offset along the seam (sigma 0.42 m) and
#      barely at all across it (sigma 0.11 m). 72% of a clump is one prototype,
#      because ruderal growth is clonal; the rest mixes.
#   d) height jitters 0.62-1.42x within the prototype's own band, the tuft is
#      stretched 1.14-1.46x along the crack and squashed across it, yaw is
#      aligned to the seam (either end-on) for 55% and fully random for the
#      rest, and X/Y tilt jitters +/-2.6 deg.
#   e) a quarter of clumps also drop leaf litter or a half-buried stone at the
#      same spot, so an edge reads as accumulated silt + leaf + weed.
# Anything inside 0.45 m of an authored tyre-polish lane is deleted outright:
# nothing grows where wheels run.
#
# CAMERA PROTECTION. DETAIL_WET_APRON sits at (-12.0, -10.5, 1.10) and its job
# is asphalt aggregate, rust bleed and a puddle meniscus - not foliage. Inside
# 8 m of that eye nothing exceeds 0.18 m; inside 16 m nothing exceeds 0.45 m;
# inside 20 m there is no tier-2 or tier-3 growth at all; clump parents are
# thinned 25% inside 14 m and capped at two children inside 6 m. The 0.87 m
# steel drums in that frame are the tallest things in the near field.
#
# INTERIOR RULE. Weeds cannot grow out of intact, painted, forklift-polished
# concrete. Every InteriorIngress instance is rejection-sampled against the
# geometry 10_terrain actually authors: it survives only within 0.40 m of a slab
# joint, 0.35 m of a water-ingress fan, 0.55 m of a wall foot or 0.80 m of a
# door threshold, and is rejected within 0.60 m of a worn traffic path
# (AisleWear / ForkliftScuff / OilTrail) or anywhere in the A3 through-lane.
# Most of what survives is blown-in leaf litter rather than living growth.
#
# ---------------------------------------------------------------------------
# 4. TREE LINES
# ---------------------------------------------------------------------------
# Round 2 authored 12 green and 11 orange Lombardy poplars alternating at a 9 m
# pitch on one Y line, plus one green and one orange Black Oak: a comb of
# same-size lollipops in two saturated hues, in the one shot briefed around
# silhouette. Rebuilt as bands:
#   - ONE SEASONAL STATE, late summer. No *_Fall asset appears anywhere in the
#     map, no species whose atlas carries autumn foliage, and no fall-leaf
#     debris on the ground.
#   - SOUTH: 11 clumps of 2-4 trees over X -68..+58, individual spacing
#     1.8-4.5 m inside a clump and 9-26 m between clumps, with two deliberate
#     long gaps at X -34..-18 and X +8..+30 where SHOT 1 and SHOT 5 want to see
#     sky and the far silo / crane layer through the row. Y spreads over
#     -55.2..-47.5 - a 7 m deep BAND, so the row overlaps itself and reads with
#     depth instead of as a cut-out strip.
#   - WEST: ROUND 4 rebuilt this band, because projecting every tree through
#     the shot's actual camera showed that the SOUTH row is completely hidden
#     behind the dock office block and the WEST band is the only tree layer that
#     survives in SILHOUETTE_WEST - it lands at x 930-1790, y 620-760, the whole
#     right half of the background. It is now 10 clumps / 22 trees instead of 7 /
#     17, with short-crowned ash and hawthorn clumps interleaved BETWEEN poplar
#     clumps so the skyline sawtooths, X drawn across the full usable margin and
#     clamped to -75.2 (the terrain plate's own west edge is -75.0, and a trunk
#     past it stands on nothing), and two genuinely empty ~12 m gaps.
#     The instance at (-73.0, +6.0) is pinned at 16.4 m because it is
#     load-bearing: at 121 m it has to reach ~13.3 m to clip and dapple the sun
#     disc in SILHOUETTE_WEST.
#     HONEST LIMIT: at 125-130 m the band has only 5 m of usable depth, because
#     the terrain plate ends at X = -75 and the playable core begins at X = -70,
#     so there is nowhere to put a second row. Real parallax is worth nothing at
#     that range; the depth read is carried by crown OVERLAP, by the height
#     ladder, and by the _F aerial tier making the band sit behind the haze
#     instead of glowing through it.
#   - heights inside a clump are drawn from a STRATIFIED, shuffled ladder across
#     the species band rather than independently, so no two neighbours can land
#     within ~1/n of each other. Two equal-height trees side by side is the
#     lollipop read; independent draws produce them regularly.
#   - heights spread +/-26% (poplars 9.8-17.4 m) instead of +/-8%.
#   - two clumps are built from red ash / gray birch / hawthorn / fraxinus
#     instead of poplar, so the ROW PROFILE changes along its length: a columnar
#     poplar comb is broken by round crowns at half the height. (Honey locust
#     did this job until round 6 found half its leaf atlas is autumn.)
#   - 2-4 elder / elm / birch / privet at the foot of every clump and
#     5-12 rank tufts around it, so trunks emerge from a mass instead of
#     standing on bare ground. That base mass is what kills the lollipop read.
#   - full random yaw and +/-3-4 deg tilt per instance.
#   - two Black Oak corner anchors at (-70.2,-50.4) 19.8 m and (+68.4,-49.6)
#     17.4 m, at different yaw and 12% different size.
#
# Units: Assets/Vegetation is authored in centimetres (metersPerUnit 0.01), so
# every instance carries xformOp:scale ~= 0.01, inside the 0.005..0.02 band
# validate.py checks. Smaller plants come from a smaller ASSET, never from
# shrinking a big one below the band. In-plane scale is anisotropic and yaw is
# spun after it (xformOpOrder translate -> rotate -> scale), which is how the
# tuft ellipse is aligned to its seam.
#
# Contact: Z is a nearest-vertex lookup against 10_terrain's nine in-map ground
# plates (89 k vertices), then each instance is sunk 10-100 mm so no card floats
# on a slope. Candidates that would land at grade inside a solid 20_architecture
# volume (dock deck, dock office, east platform, fuel bund, office annex) are
# rejected.
#
# Requests to modules I do not own:
#   50_materials / 10_terrain - moss/algae on north-facing concrete: the dock
#     foot band (Y -21.23..-20.77) and the warehouse kerb north face already
#     exist as Mat_ConcreteWetAlgae; please also darken the north faces of the
#     dock office (Y = -19.75) and the bund wall where my moss line runs.
#   30_props - the centre cluster (X -6..+14, Y -8..+6) and both yard walking
#     lines are left clear of vegetation; they are yours.
#   80_fx - the south tree band is now 7 m deep on purpose; if the aerial haze
#     in SILHOUETTE_WEST is dense enough to flatten it back into one value
#     plate, the depth work is invisible. A little less density between 60 and
#     130 m would let the band separate.

over "World"
{
    def Xform "Vegetation" (
        doc = "All planted matter. A prototype library plus six placement scopes, tiered by height and by the job each does in frame."
    )
    {
'''


def write(out):
    used = sorted({r["proto"] for r in out if "proto" in r},
                  key=lambda k: list(PROTOS).index(k))
    SHADERS = shader_map()
    debris_used = sorted({r["asset"] for r in out if "asset" in r})
    missing = []
    for name, p in [(n, PROTOS[n]) for n in used] + \
                   [(a, DEBRIS_PROTOS[a]) for a in debris_used]:
        have = SHADERS.get(p["asset"], {})
        for mat in p["mats"]:
            if mat not in have:
                missing.append(f"{name}: {p['asset']} has no material {mat!r} "
                               f"(has {sorted(have)})")
    if missing:
        raise SystemExit("override targets do not exist:\n  " + "\n  ".join(missing))

    def grade_block(asset, mats, indent):
        """Emit the override chain down the REAL prim path to each shader.

        The paths are merged into one tree first: two materials in the same
        asset share the `Looks` scope, and emitting `over "Looks"` twice is a
        duplicate-prim parse error - which composes the whole layer as EMPTY.
        """
        tree: dict = {}
        for mat, m in mats.items():
            node = tree
            for seg in SHADERS[asset][mat]:
                node = node.setdefault(seg, {})
            node["__params__"] = m

        def emit(node, depth):
            pad = " " * (indent + 4 * depth)
            lines = []
            m = node.get("__params__")
            if m is not None:
                t = m["tint"]
                lines.append(f'{pad}float inputs:albedo_brightness = {m["bright"]}\n')
                lines.append(f'{pad}float inputs:albedo_desaturation = {m["desat"]}\n')
                lines.append(f'{pad}float inputs:bump_factor = {m["bump"]}\n')
                lines.append(f'{pad}color3f inputs:diffuse_tint = ({t[0]}, {t[1]}, {t[2]})\n')
                lines.append(f'{pad}float inputs:metallic_constant = 0.0\n')
                if m["rough"] is not None:
                    lines.append(f'{pad}float inputs:reflection_roughness_constant = {m["rough"]}\n')
                    lines.append(f'{pad}float inputs:reflection_roughness_texture_influence = 0.0\n')
                lines.append(f'{pad}float inputs:specular_level = {m["spec"]}\n')
            for seg, child in node.items():
                if seg == "__params__":
                    continue
                lines.append(f'{pad}over "{seg}"\n')
                lines.append(f'{pad}{{\n')
                lines += emit(child, depth + 1)
                lines.append(f'{pad}}}\n')
            return lines

        return emit(tree, 0)

    buf = [HEADER]

    # ---- prototype library ----------------------------------------------
    buf.append('        def Xform "_Protos" (\n')
    buf.append('            doc = "Prototype library. Each class prim references one library '
               'asset and overrides its OmniPBR leaf shader so the same asset can supply '
               'several visually distinct plants. Class prims are abstract: they are not '
               'imaged and not traversed. Instances reference these by internal path and stay '
               'instanceable, so every proto still resolves to a single shared USD prototype."\n')
    buf.append('        )\n')
    buf.append('        {\n')
    buf.append('            float3 xformOp:translate = (0, 0, -4000)\n')
    buf.append('            uniform token[] xformOpOrder = ["xformOp:translate"]\n')
    for name in used:
        p = PROTOS[name]
        buf.append('\n')
        buf.append(f'            class Xform "{name}" (\n')
        buf.append(f'                doc = "{p["doc"]} Asset {p["asset"]} '
                   f'({NATIVE[p["asset"]][2]:.3f} m native), height band '
                   f'{p["h"][0]:.2f}-{p["h"][1]:.2f} m."\n')
        buf.append(f'                prepend references = @{S3}{ASSET_PATH[p["asset"]]}@\n')
        buf.append('            )\n')
        buf.append('            {\n')
        buf += grade_block(p["asset"], p["mats"], 16)
        buf.append('            }\n')

    for a in debris_used:
        p = DEBRIS_PROTOS[a]
        buf.append('\n')
        buf.append(f'            class Xform "D_{a}" (\n')
        buf.append(f'                doc = "{p["doc"]}"\n')
        buf.append(f'                prepend references = @{S3}{DEBRIS_PATH[a]}@\n')
        buf.append('            )\n')
        buf.append('            {\n')
        buf += grade_block(a, p["mats"], 16)
        buf.append('            }\n')
    buf.append('        }\n\n')

    # ---- placement scopes ------------------------------------------------
    by_scope: dict[str, list] = {s: [] for s in SCOPE_ORDER}
    for r in out:
        by_scope.setdefault(r["scope"], []).append(r)

    n = 0
    for scope in SCOPE_ORDER:
        cls, label, doc = SCOPE_DOC[scope]
        buf.append(f'        def Scope "{scope}" (\n')
        buf.append(f'            doc = "{doc}"\n')
        buf.append('        )\n')
        buf.append('        {\n')
        buf.append(f'            custom string semantic:class:params:semanticData = "{cls}"\n')
        buf.append('            custom token semantic:class:params:semanticType = "class"\n')
        buf.append(f'            custom string semantic:label:params:semanticData = "{label}"\n')
        buf.append('            custom token semantic:label:params:semanticType = "label"\n')
        for r in by_scope[scope]:
            if "proto" in r:
                ref = f'</World/Vegetation/_Protos/{r["proto"]}>'
            else:
                a = r["asset"]
                if a not in DEBRIS_PROTOS:
                    raise SystemExit(f"no path for asset {a}")
                ref = f'</World/Vegetation/_Protos/D_{a}>'
            rx, ry, rz = r["rot"]
            sx, sy, sz = r["scale"]
            px, py, pz = r["pos"]
            buf.append('\n')
            buf.append(f'            def Xform "v_{n:04d}" (\n')
            buf.append('                instanceable = true\n')
            buf.append(f'                prepend references = {ref}\n')
            buf.append('            )\n')
            buf.append('            {\n')
            buf.append(f'                float3 xformOp:rotateXYZ = ({rx:.3f}, {ry:.3f}, {rz:.3f})\n')
            buf.append(f'                float3 xformOp:scale = ({sx:.6f}, {sy:.6f}, {sz:.6f})\n')
            buf.append(f'                double3 xformOp:translate = ({px:.4f}, {py:.4f}, {pz:.4f})\n')
            buf.append('                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]\n')
            buf.append('            }\n')
            n += 1
        buf.append('        }\n\n')
    buf.append('    }\n')
    buf.append('}\n')
    VEG.write_text("".join(buf), encoding="utf-8")
    print(f"wrote {VEG} - {n} instances, {len(used)} prototypes")


if __name__ == "__main__":
    main()
