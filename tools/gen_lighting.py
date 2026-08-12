"""Generate usd/modules/60_lighting.usda for DEADFALL DEPOT.

Storm-break dusk: a low warm WSW sun raking under a heavy storm ceiling, cool
blue storm shadow everywhere it does not reach, and the depot's sodium-vapour
practicals just kicked on.

The interior high-bay positions are not guessed: they are measured off the
merged SM_Lamp_A1 mesh inside Warehouse01.usd by clustering its points, so every
DiskLight/SphereLight sits inside a real fixture.

    cd tools && uv run gen_lighting.py
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "usd" / "modules" / "60_lighting.usda"
CACHE = ROOT / "_catalog" / "_assetcache"
WAREHOUSE = CACHE / "Assets/ArchVis/Industrial/Buildings/Warehouse/Warehouse01.usd"

NV = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"

SKIES = {
    "storm": "Assets/Skies/Storm/approaching_storm_4k.hdr",
    "evening": "Assets/Skies/Evening/evening_road_01_4k.hdr",
    "venice": "Assets/Skies/Clear/venice_sunset_4k.hdr",
    "parking": "Assets/Skies/Cloudy/abandoned_parking_4k.hdr",
    "signal": "Assets/Skies/Clear/signal_hill_sunrise_4k.hdr",
    "moonlit": "Assets/Skies/Night/moonlit_golf_4k.hdr",
    "kloppen": "Assets/Skies/Night/kloppenheim_02_4k.hdr",
}
SKY = "parking"
HDRI = NV + SKIES[SKY]

# ---------------------------------------------------------------------------
# The dial board. Everything a render iteration touches lives here.
# ---------------------------------------------------------------------------
DOME_INTENSITY = 280.0
DOME_TINT = (0.78, 0.90, 1.22)      # push the storm ambient cool
DOME_ROT_Z = 60.0                  # spin so the cloud break lands WSW (bearing ~200)

SUN_INTENSITY = 20000.0
SUN_COLOR = (1.000, 0.540, 0.245)   # ~3000 K, dusk sun through a storm break
SUN_ANGLE = 1.40                    # deg: crisp but not razor - dusk disc + haze

RIM_INTENSITY = 900.0               # cool skylight key from the opposite side
RIM_COLOR = (0.255, 0.420, 1.000)
RIM_ROT = (66.4, 0.0, 112.0)
RIM_ANGLE = 12.0

# Practicals. Sphere/disk intensity here is radiance-like, so these are big.
SODIUM = (1.000, 0.560, 0.245)      # HPS ~2100 K
SODIUM_OLD = (1.000, 0.470, 0.170)  # a browner, dying tube
MERCURY = (0.780, 0.930, 1.000)     # the one odd fixture, ~4300 K
HALIDE = (0.870, 0.930, 1.000)      # crane floods, ~5000 K

HIGHBAY_I = 1764000.0
HIGHBAY_R = 0.30
WALLPACK_I = 7280000.0
WALLPACK_R = 0.16
CANOPY_I = 6020000.0
CANOPY_R = 0.16
FLOOD_I = 22400000.0
FLOOD_R = 0.20
INTERIOR_MULT = 1.0
GATE_MULT = 1.0

rng = random.Random(20260807)


# ---------------------------------------------------------------------------
# Measure the warehouse high-bay fixtures
# ---------------------------------------------------------------------------
def highbay_positions() -> list[tuple[float, float, float]]:
    """Cluster SM_Lamp_A1's points into individual fixtures, in world space."""
    stage = Usd.Stage.Open(str(WAREHOUSE))
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath("/World/SM_Lamp_A1"))
    pts = np.array(mesh.GetPointsAttr().Get()) * 0.01 + np.array([-1.24, 46.0, 0.0])

    buckets: dict[tuple[int, int], list] = defaultdict(list)
    for key, p in zip(map(tuple, np.round(pts[:, :2] / 2.0).astype(int)), pts):
        buckets[key].append(p)

    coarse = np.array([np.array(v).mean(0) for v in buckets.values()])
    lows = np.array([np.array(v)[:, 2].min() for v in buckets.values()])

    used = np.zeros(len(coarse), bool)
    out = []
    for i in range(len(coarse)):
        if used[i]:
            continue
        grp, lo = [coarse[i]], [lows[i]]
        used[i] = True
        for j in range(i + 1, len(coarse)):
            if not used[j] and np.linalg.norm(coarse[i][:2] - coarse[j][:2]) < 3.0:
                grp.append(coarse[j])
                lo.append(lows[j])
                used[j] = True
        c = np.array(grp).mean(0)
        out.append((round(float(c[0]), 2), round(float(c[1]), 2), round(min(lo) + 0.18, 2)))
    out.sort(key=lambda p: (p[1], p[0]))
    return out


# ---------------------------------------------------------------------------
# USDA emitters. Braces always on their own line - single-line blocks are a
# parse error in this runtime and a layer that fails to parse composes as empty.
# ---------------------------------------------------------------------------
def block(lines: list[str], indent: int) -> str:
    pad = " " * indent
    return "\n".join(pad + l for l in lines)


def sphere_light(name, pos, radius, color, intensity, indent=12, cone=None,
                 rot=None, comment=None, exposure=0.0, extra=None):
    pad = " " * indent
    api = ' (\n' + pad + '    prepend apiSchemas = ["ShapingAPI"]\n' + pad + ')' if cone else ""
    s = []
    if comment:
        for c in comment:
            s.append(f"{pad}# {c}")
    s.append(f'{pad}def SphereLight "{name}"{api}')
    s.append(pad + "{")
    s.append(f"{pad}    float inputs:radius = {radius}")
    s.append(f"{pad}    color3f inputs:color = ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})")
    s.append(f"{pad}    float inputs:intensity = {intensity:.1f}")
    s.append(f"{pad}    float inputs:exposure = {exposure}")
    s.append(f"{pad}    float inputs:diffuse = 1")
    s.append(f"{pad}    float inputs:specular = 1")
    s.append(f"{pad}    bool inputs:normalize = 0")
    if cone:
        angle, softness, focus = cone
        s.append(f"{pad}    float inputs:shaping:cone:angle = {angle}")
        s.append(f"{pad}    float inputs:shaping:cone:softness = {softness}")
        s.append(f"{pad}    float inputs:shaping:focus = {focus}")
    for e in extra or []:
        s.append(f"{pad}    {e}")
    s.append(f"{pad}    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    if rot:
        s.append(f"{pad}    double3 xformOp:rotateXYZ = ({rot[0]}, {rot[1]}, {rot[2]})")
        s.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
    else:
        s.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate"]')
    s.append(pad + "}")
    s.append("")
    return "\n".join(s)


def disk_light(name, pos, radius, color, intensity, indent=12, rot=None, comment=None):
    pad = " " * indent
    out = []
    for c in comment or []:
        out.append(f"{pad}# {c}")
    out.append(f'{pad}def DiskLight "{name}"')
    out.append(pad + "{")
    out.append(f"{pad}    float inputs:radius = {radius}")
    out.append(f"{pad}    color3f inputs:color = ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})")
    out.append(f"{pad}    float inputs:intensity = {intensity:.1f}")
    out.append(f"{pad}    float inputs:exposure = 0")
    out.append(f"{pad}    float inputs:diffuse = 1")
    out.append(f"{pad}    float inputs:specular = 1")
    out.append(f"{pad}    bool inputs:normalize = 0")
    out.append(f"{pad}    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    if rot:
        out.append(f"{pad}    double3 xformOp:rotateXYZ = ({rot[0]}, {rot[1]}, {rot[2]})")
        out.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
    else:
        out.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate"]')
    out.append(pad + "}")
    out.append("")
    return "\n".join(out)


def rect_light(name, pos, w, h, color, intensity, rot=None, indent=12, comment=None,
               exposure=0.0):
    pad = " " * indent
    s = []
    if comment:
        for c in comment:
            s.append(f"{pad}# {c}")
    s.append(f'{pad}def RectLight "{name}"')
    s.append(pad + "{")
    s.append(f"{pad}    float inputs:width = {w}")
    s.append(f"{pad}    float inputs:height = {h}")
    s.append(f"{pad}    color3f inputs:color = ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})")
    s.append(f"{pad}    float inputs:intensity = {intensity:.1f}")
    s.append(f"{pad}    float inputs:exposure = {exposure}")
    s.append(f"{pad}    float inputs:diffuse = 1")
    s.append(f"{pad}    float inputs:specular = 1")
    s.append(f"{pad}    bool inputs:normalize = 0")
    s.append(f"{pad}    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    if rot:
        s.append(f"{pad}    double3 xformOp:rotateXYZ = ({rot[0]}, {rot[1]}, {rot[2]})")
        s.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]')
    else:
        s.append(f'{pad}    uniform token[] xformOpOrder = ["xformOp:translate"]')
    s.append(pad + "}")
    s.append("")
    return "\n".join(s)


def main() -> None:
    bays = highbay_positions()
    assert len(bays) == 45, f"expected 45 high-bay fixtures, clustered {len(bays)}"

    # -- which high bays still work --------------------------------------
    # A derelict depot: most of the roof is dead. The row nearest the main
    # through-lane A3 (Y = 45.52) is kept mostly alive because SHOT 2's whole
    # lighting gag is a receding row of sodium points at the vanishing point.
    state = {}
    for (x, y, z) in bays:
        near_a3 = abs(y - 45.52) < 0.5
        r = rng.random()
        if near_a3:
            s = "on" if r < 0.80 else ("dying" if r < 0.90 else "dead")
        else:
            s = "on" if r < 0.42 else ("dying" if r < 0.52 else "dead")
        state[(x, y, z)] = s
    # exactly three fixtures are a colder mercury unit somebody swapped in
    live = [k for k, v in state.items() if v == "on"]
    for k in rng.sample(live, 3):
        state[k] = "mercury"

    parts: list[str] = []
    A = parts.append

    A(f'''#usda 1.0
(
    defaultPrim = "World"
    doc = """DEADFALL DEPOT module: lighting. Owned by one specialist agent - do not edit from another module.

STORM-BREAK DUSK. Three colour families, and the contrast between them is the mood:
  WARM  - a 7.0 deg WSW sun ({SUN_COLOR[0]:.2f},{SUN_COLOR[1]:.2f},{SUN_COLOR[2]:.2f}, ~3200 K) breaking under the storm
          ceiling. It rakes ACROSS the map: ~70 deg incidence on the
          corrugated south wall, straight down the east-west aisles through the
          open west roller doors, shadows running east-north-east over the wet
          yard. The disc is visible in SHOT 5, under the conveyor bridge and
          over the dock canopy - see the note on the DistantLight below.
  COOL  - everything the sun misses is lit by the storm sky: the 4K latlong
          abandoned_parking HDRI (a genuinely heavy overcast cloud bank over an
          industrial skyline - chosen over approaching_storm and venice_sunset
          by rendering all three, see the report), tinted cool, plus a low cool
          DistantLight from the ENE that gives silhouettes rim separation.
          Dusk shadows here are blue, never black and never neutral.
  AMBER - sodium-vapour practicals. 45 measured warehouse high bays (most dead,
          three swapped for a colder mercury unit, several dying), six warehouse
          south-wall packs, seven dock-canopy fascia units, and floods on the
          crane, the tanker gantry, the trestle and the dock office.

Everything is authored in world space under /World/Lighting. Light positions
inside the warehouse were MEASURED by clustering the points of the merged
SM_Lamp_A1 mesh in Warehouse01.usd - they are inside the real fixtures, not
guessed. Regenerate with: cd tools && uv run gen_lighting.py"""
    metersPerUnit = 1
    upAxis = "Z"
)

over "World"
{{
    def Xform "Lighting"
    {{
''')

    # ------------------------------------------------------------------ SKY
    A('''        # =====================================================================
        # SKY - the storm ceiling
        # =====================================================================
        def Scope "Sky"
        {
''')
    A(f'''            # 4K latlong overcast/storm HDRI. Z-up rule from the brief: a latlong maps
            # correctly with NO X rotation - an X rotation tips the horizon.
            # Spin about Z only. rotateZ 60 was picked by rendering 0/60/120/180/
            # 240/300 and looking: it puts the heavy cloud bank over the west and
            # east horizons (SHOT 5 and SHOT 3 respectively) and the brick
            # industrial skyline behind the dock, so the background layer is
            # never empty and the sun disc punches through cloud, not blue sky.
            # inputs:color is a deliberate cool multiplier: it pushes the whole
            # ambient - and therefore every shadow in the map - blue, which is
            # what separates it from the amber practicals.
            def DomeLight "StormSky"
            {{
                float inputs:intensity = {DOME_INTENSITY}
                float inputs:exposure = 0
                color3f inputs:color = ({DOME_TINT[0]}, {DOME_TINT[1]}, {DOME_TINT[2]})
                asset inputs:texture:file = @{HDRI}@
                token inputs:texture:format = "latlong"
                float inputs:diffuse = 1
                float inputs:specular = 1
                bool inputs:normalize = 0
                double3 xformOp:rotateXYZ = (0, 0, {DOME_ROT_Z})
                uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
            }}
        }}
''')

    # ------------------------------------------------------------------ SUN
    A('''
        # =====================================================================
        # SUN - the key, and the reason every surface reads as textured
        # =====================================================================
        def Scope "Sun"
        {
''')
    A(f'''            # rotateXYZ (83.0, 0, 290) composes Rz*Ry*Rx onto the light's -Z
            # emission axis, giving direction (+0.9327, +0.3394, -0.1219): the
            # sun sits WSW (bearing 200 deg from +X) at 7.0 deg elevation.
            #
            # DELIBERATE DEVIATION FROM LAYOUT 8.1, which specifies (84.5, 0,
            # 290) = 5.5 deg. At 5.5 deg the disc is OCCLUDED: the ray from
            # SHOT 5's camera (48, -8, 1.65) toward bearing 200 reaches only
            # Z 5.03 at the dock-canopy fascia line (Y = -20) and then climbs
            # into the underside of the canopy roof (Z 5.40-5.75) at Y ~ -21.3,
            # so the sun the layout wants "a quarter in from the left edge,
            # under the conveyor bridge" is simply behind the canopy. Clearing
            # the canopy needs > 6.66 deg; 7.0 deg clears it and still passes
            # UNDER the conveyor bridge (the ray is at Z 4.4 where the bridge
            # crosses at X +26, and the enclosure starts at Z 5.90). Rendered
            # and confirmed. The extra 1.5 deg changes nothing about the raking
            # - shadows are still ~8x the height of what casts them.
            # That is a raking angle by construction - at 7 deg every
            # corrugation, kerb, rut and slab joint casts a shadow ~8x its own
            # height, which is what makes a surface read as textured instead of
            # painted. Shadows run east-north-east across the yard.
            # angle {SUN_ANGLE} deg is roughly 3x the real solar disc: the sun
            # reads as a soft dusk disc rather than a hard point, contact
            # shadows stay crisp, and the far end of a 40 m shadow goes soft.
            def DistantLight "KeySun"
            {{
                float inputs:angle = {SUN_ANGLE}
                color3f inputs:color = ({SUN_COLOR[0]}, {SUN_COLOR[1]}, {SUN_COLOR[2]})
                float inputs:intensity = {SUN_INTENSITY}
                float inputs:exposure = 0
                float inputs:diffuse = 1
                float inputs:specular = 1
                bool inputs:normalize = 0
                double3 xformOp:rotateXYZ = (83.0, 0, 290.0)
                uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
            }}

            # Cool counter-key from the ENE at 24 deg, aimed WSW and down - the
            # bright part of the storm sky opposite the break. This is the fill
            # that keeps shadows blue rather than black and puts a cold rim on
            # every silhouette facing away from the sun (the conveyor bridge,
            # the crane, the poplar line). ~10 percent of the sun's intensity
            # and a wide {RIM_ANGLE} deg angle so it never reads as a second sun.
            def DistantLight "StormFillCool"
            {{
                float inputs:angle = {RIM_ANGLE}
                color3f inputs:color = ({RIM_COLOR[0]}, {RIM_COLOR[1]}, {RIM_COLOR[2]})
                float inputs:intensity = {RIM_INTENSITY}
                float inputs:exposure = 0
                float inputs:diffuse = 1
                float inputs:specular = 0.35
                bool inputs:normalize = 0
                double3 xformOp:rotateXYZ = ({RIM_ROT[0]}, {RIM_ROT[1]}, {RIM_ROT[2]})
                uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
            }}
        }}
''')

    # ------------------------------------------------------- INTERIOR HIGH BAY
    A('''
        # =====================================================================
        # PRACTICALS
        # =====================================================================
        def Scope "Practicals"
        {
            # -----------------------------------------------------------------
            # Warehouse high bays. 45 fixtures, positions measured off the
            # merged SM_Lamp_A1 mesh (9 columns x 5 rows, hanging Z 8.1-13.1).
            # A working depot would have all 45 lit and would look like a
            # showroom; a derelict one has most of them dead. Live units are
            # sodium, three are a colder mercury unit somebody swapped in, and
            # the "dying" ones sit at 12 percent - a tube at the end of its life
            # that has gone brown. The row at Y = 45.52 is kept mostly alive
            # because SHOT 2 is built on that receding line of sodium points.
            # -----------------------------------------------------------------
            def Scope "HighBay"
            {
''')
    live_n = dead_n = dying_n = merc_n = 0
    for (x, y, z) in bays:
        s = state[(x, y, z)]
        if s == "dead":
            dead_n += 1
            continue
        if s == "mercury":
            col, inten, merc_n = MERCURY, HIGHBAY_I * 0.85, merc_n + 1
        elif s == "dying":
            col, inten, dying_n = SODIUM_OLD, HIGHBAY_I * 0.12, dying_n + 1
        else:
            col, inten, live_n = SODIUM, HIGHBAY_I * rng.uniform(0.85, 1.12), live_n + 1
        nm = f"HB_{'m' if x < 0 else 'p'}{abs(int(round(x))):02d}_{int(round(y)):02d}"
        A(disk_light(nm, (x, y, z), HIGHBAY_R, col, inten, indent=16,
                     comment=[f"{s} sodium high bay" if s != "mercury" else "mercury swap-in"]))
    A('''            }
''')

    # ------------------------------------------------------- SOUTH WALL PACKS
    A('''
            # -----------------------------------------------------------------
            # Warehouse south-wall packs. Y = 14.60 (0.40 m proud of the wall at
            # Y = 15.00), Z = 5.20, X = -34 -22 -10 +2 +14 +26. Shaped cones
            # tilted 32 deg down and south so the light washes DOWN the
            # corrugated wall and out across the first 12 m of wet yard - this
            # is where SHOT 3's wet specular comes from, because the sun is
            # behind that camera and cannot supply it.
            # X = -22 is dead. X = -10 is the odd cold mercury unit. Uniform
            # practicals read as fake, so nothing here matches its neighbour.
            # -----------------------------------------------------------------
            def Scope "SouthWallPacks"
            {
''')
    wallpacks = [
        (-34.0, SODIUM, 1.00, "sodium, healthy"),
        (-22.0, None, 0.0, "DEAD - smashed lens, no lamp"),
        (-10.0, MERCURY, 0.80, "cold mercury swap-in - the odd one out"),
        (2.0, SODIUM, 1.15, "sodium, brightest - it is the one over the hero gate"),
        (14.0, SODIUM_OLD, 0.30, "dying, browned tube, half output"),
        (26.0, SODIUM, 0.90, "sodium, healthy"),
    ]
    for x, col, mult, note in wallpacks:
        if col is None:
            A(f"                # X = {x:+.0f} wall pack is DEAD - no light authored here on purpose.\n")
            continue
        nm = f"WP_{'m' if x < 0 else 'p'}{abs(int(x)):02d}"
        A(sphere_light(nm, (x, 14.60, 5.20), WALLPACK_R, col, WALLPACK_I * mult,
                       indent=16, cone=(78.0, 0.45, 12.0), rot=(-32.0, 0.0, 0.0),
                       comment=[note]))
    A('''            }
''')

    # ------------------------------------------------------- DOCK CANOPY
    A('''
            # -----------------------------------------------------------------
            # Dock-canopy fascia sodiums, Y = -21.50, Z = 5.20, under the
            # canopy soffit at Z +5.40. These are the only light on the dock
            # deck once the sun drops below the canopy, and they are what makes
            # Lane C read as a separate, warmer-lit lane from the yard.
            # X = +12 is dead. X = +26 is on its way out and flickers brown.
            # -----------------------------------------------------------------
            def Scope "DockCanopy"
            {
''')
    canopy = [
        (-44.0, SODIUM, 0.95, "sodium"),
        (-30.0, SODIUM, 1.05, "sodium"),
        (-16.0, SODIUM, 0.90, "sodium"),
        (-6.0, SODIUM, 1.20, "sodium - the SHOT 4 fixture, directly over puddle P4"),
        (2.0, SODIUM, 0.85, "sodium"),
        (12.0, None, 0.0, "DEAD"),
        (26.0, SODIUM_OLD, 0.22, "failing - brown, flickering, nearly out"),
    ]
    for x, col, mult, note in canopy:
        if col is None:
            A(f"                # X = {x:+.0f} canopy fixture is DEAD - no light authored here on purpose.\n")
            continue
        nm = f"DC_{'m' if x < 0 else 'p'}{abs(int(x)):02d}"
        A(sphere_light(nm, (x, -21.50, 5.20), CANOPY_R, col, CANOPY_I * mult,
                       indent=16, cone=(88.0, 0.55, 8.0), rot=(12.0, 0.0, 0.0),
                       comment=[note]))
    A(f'''                # LOW dock-face bay lamp over truck bay X = -6. This one exists for
                # SHOT 4 and the geometry is worked out, not assumed: the camera
                # sits at (-12, -10.5, 1.10) and puddle P4's water plane is at
                # Z -0.012, so a fixture's mirror image only lands INSIDE P4 if
                # the fixture is low. At Z 1.25 the reflected ray crosses the
                # water at about (-9.4, -16.1) - inside P4's 7.0 x 4.5 footprint.
                # A fixture up on the 5.40 m fascia would reflect ~40 m off the
                # end of the map, which is why the fascia unit alone is not
                # enough for that shot.
''')
    A(sphere_light("DockFace_BayLamp_m06", (-6.6, -22.10, 1.25), 0.11, SODIUM,
                   CANOPY_I * 0.55, indent=16, cone=(100.0, 0.6, 4.0),
                   rot=(58.0, 0.0, 0.0)))
    A('''            }
''')

    # ------------------------------------------------------- FLOODS
    A('''
            # -----------------------------------------------------------------
            # Yard and spawn floods. Every one of these is mounted on a
            # structure 20_architecture actually built - there are no floating
            # lights in this rig.
            # -----------------------------------------------------------------
            def Scope "Floods"
            {
''')
    floods = [
        ("Mast_FuelBay", (-60.0, -2.0, 8.0), (48.0, 0.35, 22.0), (47.1, 0.0, 209.7),
         HALIDE, 1.00, "West fuel-bay mast flood, aimed down-south-east into the bund at (-56,-9)."),
        ("Gantry_West", (44.0, 26.0, 9.0), (52.0, 0.40, 18.0), (65.5, 0.0, 135.0),
         HALIDE, 0.75, "Gantry-crane portal flood, west leg, raking south-west down the spur."),
        ("Gantry_East", (64.0, 26.0, 9.0), (52.0, 0.40, 18.0), (65.9, 0.0, 185.7),
         HALIDE, 0.75, "Gantry-crane portal flood, east leg."),
        ("TankerGantry", (-54.0, 8.0, 4.5), (66.0, 0.5, 10.0), (32.2, 0.0, 135.0),
         SODIUM, 0.55, "Tanker loading gantry underside lamp over the oil-black pad."),
        ("Trestle_West", (-30.0, 3.5, 5.05), (70.0, 0.6, 8.0), (0.0, 0.0, 0.0),
         SODIUM_OLD, 0.30, "Failing lamp clamped under the pipe trestle deck at X -30."),
        ("Bridge_East", (25.9, -3.5, 5.75), (70.0, 0.6, 8.0), (0.0, 0.0, 0.0),
         SODIUM, 0.45, "Lamp under the conveyor bridge deck at X +26 - lights the shadow it casts."),
        ("EastPlatform", (45.0, 8.0, 4.2), (60.0, 0.5, 12.0), (15.0, 0.0, 0.0),
         SODIUM, 0.40, "East loading-platform lamp, objective point E."),
    ]
    for nm, pos, cone, rot, col, mult, note in floods:
        A(sphere_light(nm, pos, FLOOD_R, col, FLOOD_I * mult, indent=16,
                       cone=cone, rot=rot, comment=[note]))
    A(f'''                # The one broken fixture the brief asks for, over the dock-office
                # external stair. Authored at 6 percent output with a green-sick
                # cast - a mercury lamp that has lost its phosphor and is
                # cycling. It reads as "this one is on its way out", and it is
                # the only cold source on the whole south-east corner.
''')
    A(sphere_light("DockOffice_Broken", (47.0, -27.0, 4.2), 0.10, (0.62, 0.86, 0.74),
                   FLOOD_I * 0.06, indent=16, cone=(96.0, 0.7, 3.0), rot=(34.0, 0.0, 200.0)))
    A('''            }
        }
''')

    # ------------------------------------------------------- INTERIOR DAYLIGHT
    A(f'''
        # =====================================================================
        # INTERIOR DAYLIGHT - the warehouse needs its own solution
        # =====================================================================
        # Measured off SM_Glass_A1 before 20_architecture deactivated it: the
        # building carries a raised roof monitor spanning Y 37.90 .. 53.10 with
        # VERTICAL clerestory bands at Y = 37.90 and Y = 53.10, X -33.3 .. +33.3,
        # Z 13.80 .. 16.80, plus sloped roof lights at Z 16.80 .. 18.00. Those
        # apertures are open now, so the DomeLight does pour through them - but
        # a 4K HDRI seen through a 3 m slot 14 m up delivers very little to the
        # floor, and the sun at 7 deg elevation entering a clerestory at
        # Z 13.8 would travel 112 m before it reached the slab, i.e. never.
        #
        # So the shafts are authored, in the apertures, pointing where the real
        # light would go:
        #   * two RectLights filling the clerestory bands, cool storm-sky
        #     coloured, facing INTO the hall and tilted down. These are the
        #     interior's ambient and its blue - without them the racking maze
        #     goes black between the sodium pools.
        #   * a warm low-angle bar at each open gate line, matching the sun that
        #     rakes in through the 40 m of south roller doors (Z 0 .. 3.80) and
        #     the 42 m of west roller doors. Physical sun through a 3.80 m door
        #     at 7 deg lands up to 30.9 m inside; these cards are deliberately
        #     weak (1200-1400) - the real sun already does most of this work,
        #     they only stop the rack shadows from eating it entirely.
        # =====================================================================
        def Scope "InteriorDaylight"
        {{
''')
    A(rect_light("Clerestory_South", (0.0, 38.20, 15.30), 66.0, 2.90, (0.42, 0.58, 1.00),
                 5700.0 * INTERIOR_MULT, rot=(76.0, 0.0, 0.0), indent=12,
                 comment=["South clerestory band, Y 37.90, Z 13.80-16.80. Faces north into",
                          "the hall and 14 deg down, so it lays a cool wash over the tops of",
                          "rack runs RR-N1/N2/N3 and skims the aisle floors beyond them."]))
    A(rect_light("Clerestory_North", (0.0, 52.80, 15.30), 66.0, 2.90, (0.40, 0.55, 1.00),
                 5100.0 * INTERIOR_MULT, rot=(-76.0, 0.0, 0.0), indent=12,
                 comment=["North clerestory band, Y 53.10. Faces south into the hall and 14 deg",
                          "down. Slightly dimmer and bluer than the south band - the storm break",
                          "is to the south-west, so the north sky is the colder half."]))
    A(rect_light("RoofMonitor_Down", (0.0, 45.50, 16.60), 62.0, 13.0, (0.46, 0.60, 1.00),
                 1350.0 * INTERIOR_MULT, rot=None, indent=12,
                 comment=["The sloped roof lights at Z 16.80-18.00, collapsed to one soft",
                          "downward card at Z 16.60 above the truss. This is what stops the",
                          "aisle floors reading as a black corridor with orange dots in it.",
                          "Low intensity on purpose: it is overcast sky, not a skylight in June."]))
    A(rect_light("GateWash_South", (-17.6, 15.60, 1.85), 40.0, 3.60, (1.000, 0.560, 0.250),
                 1400.0 * GATE_MULT, rot=(83.0, 0.0, 0.0), indent=12,
                 comment=["Warm sun wash through the 40 m of open south roller doors,",
                          "X -37.85..+2.62, opening Z 0..3.80. Faces north into the building and",
                          "7 deg down, matching the sun. This is the light that puts a",
                          "bright bar on the slab inside every open door and picks out the water",
                          "ingress fan the terrain module authored there."]))
    A(rect_light("GateWash_Hero", (0.0, 15.90, 3.40), 7.30, 6.60, (1.000, 0.520, 0.220),
                 9000.0 * GATE_MULT, rot=(84.0, 0.0, 0.0), indent=12,
                 comment=["The hero gate, X -3.15..+3.16, 7.39 m tall. Brighter and more",
                          "saturated than the rest of the south wall because it is the map's",
                          "focal point and the 6 m water slick fanning in from it is what makes",
                          "SHOT 2 work at 9000 against the 1200-1400 of the plain door bays.",
                          "Faces north, 6 deg down."]))
    A(rect_light("GateWash_West", (-37.55, 36.50, 1.85), 42.0, 3.60, (1.000, 0.580, 0.280),
                 1200.0 * GATE_MULT, rot=(83.0, 0.0, 270.0), indent=12,
                 comment=["West roller doors, X = -37.85, Y 15.37..57.53, Z 0..3.80. The sun",
                          "bearing is 200 deg, so it hits this wall nearly head-on and drives",
                          "straight EAST down the aisles - including A3 at Y 49.5, which is",
                          "exactly what SHOT 2 looks along. Faces east (+X), 7 deg down."]))
    A(rect_light("GateWash_East", (37.55, 45.50, 1.85), 24.0, 3.60, (0.62, 0.74, 1.00),
                 9000.0 * GATE_MULT, rot=(83.0, 0.0, 90.0), indent=12,
                 comment=["East roller doors, X = +37.84, Y 33.47..57.53. These face AWAY from",
                          "the sun, so this one is cool storm-sky, not warm sun - it is the",
                          "glowing cold hole at the vanishing point of SHOT 2, and the colour",
                          "contrast against the sodium row is the whole point of that frame."]))
    A('''        }
''')

    A('''    }
}
''')

    OUT.write_text("\n".join(parts), encoding="utf-8")
    n = sum(1 for _ in OUT.read_text(encoding="utf-8").splitlines())
    print(f"wrote {OUT} ({n} lines)")
    print(f"high bays: {live_n} sodium on, {merc_n} mercury, {dying_n} dying, {dead_n} dead")



# ---------------------------------------------------------------------------
# STALE-GENERATOR GUARD  (added by the revision-5 lighting pass)
# ---------------------------------------------------------------------------
# This script authored REVISION 1 of usd/modules/60_lighting.usda and has not
# been kept in step with the file since. What it emits today is a strict subset
# of what is authored there: 45 bare cosine-weighted high bays instead of 27
# with per-fixture ShapingAPI reflector cones, no RoofBreaks scope, no
# Volumetrics shaft cards, no StormBreak / YardSky / ApronSky /
# GateWash_West_Sky aperture cards, one cool fill instead of three, and none of
# the measured dead/dying/mercury fixture states. Running it WILL silently
# delete all of that - roughly 2,000 lines and five revisions of measured work.
#
# The live module is hand-authored. Numeric iteration on it goes through
# tools/tune_lighting.py, which is idempotent, keeps a revision-4 baseline
# snapshot in tools/_lighting_baseline.json, and can revert.
#
# If you genuinely want revision 1 back, pass --i-really-want-revision-1.
# ---------------------------------------------------------------------------
import sys as _sys

_STALE_MSG = (
    'REFUSING TO RUN: gen_lighting.py is STALE. It would overwrite '
    'usd/modules/60_lighting.usda with revision 1 and discard the roof breaks, '
    'volumetric shafts, shaped high-bay cones, extra cool fills and aperture '
    'cards authored since. Change lighting numbers with tools/tune_lighting.py '
    'instead. Override with --i-really-want-revision-1.'
)

if '--i-really-want-revision-1' not in _sys.argv:
    print(_STALE_MSG, file=_sys.stderr)
    raise SystemExit(2)

if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--sky", default=SKY, choices=sorted(SKIES))
    _ap.add_argument("--dome", type=float, default=DOME_INTENSITY)
    _ap.add_argument("--sun", type=float, default=SUN_INTENSITY)
    _ap.add_argument("--rim", type=float, default=RIM_INTENSITY)
    _ap.add_argument("--prac", type=float, default=1.0, help="multiplier on every practical")
    _ap.add_argument("--hb", type=float, default=1.0, help="extra multiplier on interior high bays")
    _ap.add_argument("--interior", type=float, default=1.0, help="multiplier on the cool clerestory cards")
    _ap.add_argument("--gate", type=float, default=1.0, help="multiplier on the warm gate-wash cards")
    _ap.add_argument("--domerot", type=float, default=DOME_ROT_Z)
    _a = _ap.parse_args()
    SKY = _a.sky
    HDRI = NV + SKIES[SKY]
    DOME_INTENSITY = _a.dome
    DOME_ROT_Z = _a.domerot
    SUN_INTENSITY = _a.sun
    RIM_INTENSITY = _a.rim
    HIGHBAY_I *= _a.prac * _a.hb
    WALLPACK_I *= _a.prac
    CANOPY_I *= _a.prac
    FLOOD_I *= _a.prac
    INTERIOR_MULT = _a.interior
    GATE_MULT = _a.gate
    main()
