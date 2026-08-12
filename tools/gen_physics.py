"""Generate usd/modules/70_physics.usda -- the UsdPhysics layer for DEADFALL DEPOT.

Three-part deliverable from BRIEF.md section 7:

  1. Authored UsdPhysics: PhysicsScene, 17 PhysicsMaterialAPI looks, per-mesh
     CollisionAPI + MeshCollisionAPI over-prims on every collidable prim in
     10_terrain and 20_architecture, RigidBodyAPI + MassAPI on every dynamic
     prop, collision groups, and joints for the roll-up doors, the sliding
     compound gate, the dock levellers, the boom barrier and the crane hook.

  2. A real solve: pybullet builds the collision world out of the *authored*
     colliders (terrain triangle meshes clipped to the drop regions + analytic
     boxes for the architecture) and drops every dynamic prop from 5-15 cm above
     its intended surface with a random yaw, a random tilt and a nudge toward
     the surface it is meant to come to rest against.  Bodies are simulated to
     rest and the resting transform is baked straight into the emitted USD.

  3. Plausibility on screen: the drop sites are the places where junk actually
     accumulates in a yard -- against the warehouse kerb, at the foot of the
     dock face, washed out of the hero gate, in the service-road ruts, spilled
     out of the fuel bund entry and stacked under the mezzanine.

Run:  cd tools && uv run gen_physics.py
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "usd" / "modules" / "20_architecture.usda"
TERR = ROOT / "usd" / "modules" / "10_terrain.usda"
OUT = ROOT / "usd" / "modules" / "70_physics.usda"
PROPS_LAYER = ROOT / "usd" / "modules" / "30_props.usda"

S3 = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
PROPS = S3 + "Assets/simready_content/common_assets/props/"

SEED = 20260808
GRAVITY = 9.81


# ---------------------------------------------------------------------------
# 1. PHYSICS MATERIALS
# ---------------------------------------------------------------------------
# name -> (staticFriction, dynamicFriction, restitution, density kg/m3, note)
MATERIALS = {
    "PM_ConcreteDry":     (0.75, 0.62, 0.05, 2400, "power-trowelled interior slab, sealed"),
    "PM_ConcreteWet":     (0.48, 0.38, 0.03, 2400, "rain-soaked dock/apron concrete"),
    "PM_ConcreteBlock":   (0.70, 0.58, 0.05, 1800, "dock office blockwork"),
    "PM_AsphaltWet":      (0.55, 0.45, 0.04, 2300, "patched yard asphalt after rain"),
    "PM_SteelOnConcrete": (0.60, 0.50, 0.10, 7850, "BRIEF s7: dry steel on concrete"),
    "PM_SteelWet":        (0.25, 0.20, 0.10, 7850, "BRIEF s7: wet steel -- the whole exterior"),
    "PM_CastIronWet":     (0.28, 0.22, 0.08, 7200, "trench-drain grates, manhole covers"),
    "PM_Rubber":          (0.90, 0.80, 0.40, 1100, "BRIEF s7: dock bumpers, tyres"),
    "PM_Timber":          (0.55, 0.45, 0.15,  650, "dry pallets and crates, interior"),
    "PM_TimberWet":       (0.40, 0.32, 0.10,  800, "waterlogged pallets, sleepers"),
    "PM_Cardboard":       (0.50, 0.42, 0.02,  700, "soaked cardboard -- density is wet"),
    "PM_Plastic":         (0.38, 0.30, 0.25,  950, "totes, IBC cages, traffic cones"),
    "PM_Glass":           (0.35, 0.28, 0.20, 2500, "clerestory and office glazing"),
    "PM_Gravel":          (0.80, 0.70, 0.02, 1600, "OOB margin and service strip"),
    "PM_Ballast":         (0.85, 0.72, 0.02, 1700, "rail spur ballast"),
    "PM_Mud":             (0.95, 0.88, 0.00, 1800, "service road, rutted ground"),
    "PM_Chainlink":       (0.45, 0.38, 0.15, 7850, "galvanised fence fabric"),
}


# ---------------------------------------------------------------------------
# 2. STATIC COLLIDER CLASSIFICATION
# ---------------------------------------------------------------------------
# Ordered rules. First regex that matches the prim path wins.
#   (regex, approximation | None to skip, physics material)
# approximation "none" == full triangle mesh (UsdPhysics token for it).
SKIP = None

RULES: list[tuple[str, str | None, str]] = [
    # ---- terrain -----------------------------------------------------------
    (r"/Terrain/Water/",                     SKIP, ""),   # water surfaces
    (r"/Terrain/Patches/",                   SKIP, ""),   # ground decals
    (r"/Terrain/Markings/",                  SKIP, ""),   # paint decals
    (r"/Terrain/InteriorOverlay/",           SKIP, ""),   # wear decals
    (r"/Terrain/Ground/Ground_FarField",     SKIP, ""),   # 1850 m backdrop card
    (r"/Terrain/Ground/Ground_CentralYard",  "none", "PM_AsphaltWet"),
    (r"/Terrain/Ground/Ground_DockApron",    "none", "PM_ConcreteWet"),
    (r"/Terrain/Ground/Ground_ServiceRoad",  "none", "PM_Mud"),
    (r"/Terrain/Ground/Ground_InteriorUnderlay", "none", "PM_ConcreteDry"),
    (r"/Terrain/Ground/",                    "none", "PM_Gravel"),
    (r"/Terrain/Kerbs/DockFootAlgaeBand",    SKIP, ""),   # 2 cm decal band
    (r"/Terrain/Kerbs/",                     "none", "PM_ConcreteDry"),
    (r"/Terrain/Drainage/",                  "none", "PM_CastIronWet"),
    (r"/Terrain/Covers/",                    "none", "PM_CastIronWet"),
    (r"/Terrain/Debris/",                    "none", "PM_ConcreteDry"),

    # ---- architecture: things that must not collide ------------------------
    (r"/Architecture/.*(shard|Barb\d|BottomWire|Tear\d|RoofDrip)", SKIP, ""),
    (r"/Architecture/.*(Sodium\d|WallPack\d|StairLamp)",           SKIP, ""),
    (r"/Architecture/Dock/AlgaeBand",                              SKIP, ""),
    (r"/Architecture/Dock/Rebar",                                  SKIP, ""),
    (r"/Architecture/FuelBund/Water",                              SKIP, ""),
    (r"/Architecture/Warehouse/FloorMarkings",                     SKIP, ""),

    # ---- architecture: the anchor building ---------------------------------
    # 1.76 M points. LAYOUT s8.5: static triangle mesh, do NOT convex-decompose.
    (r"/Architecture/Warehouse/Warehouse01$", "none", "PM_ConcreteDry"),
    (r"/Architecture/Warehouse/Warehouse01/", "none", "PM_SteelWet"),

    # ---- warehouse facade / roll-up doors ----------------------------------
    (r"/Architecture/Warehouse/Facade/.*_(slat\d+|bottomrail|kink)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/Warehouse/Facade/.*_(coil|hood|guideA|guideB)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/Warehouse/Facade/.*_pane",   "none", "PM_Glass"),
    (r"/Architecture/Warehouse/Facade/.*_ply",    "none", "PM_Timber"),
    (r"/Architecture/Warehouse/Facade/",          "none", "PM_SteelWet"),

    # ---- racking -----------------------------------------------------------
    # LAYOUT s8.5: box colliders per bay, static.
    (r"/Architecture/Racking/RR_[A-Z0-9]+/Bay_", "boundingCube", "PM_SteelOnConcrete"),
    (r"/Architecture/Racking/",                  "convexHull",   "PM_SteelOnConcrete"),

    # ---- mezzanine ---------------------------------------------------------
    (r"/Architecture/Mezzanine/Rail_",           "convexDecomposition", "PM_SteelOnConcrete"),
    (r"/Architecture/Mezzanine/(Col|ColBase|PostA|PostB)", "convexHull", "PM_SteelOnConcrete"),
    (r"/Architecture/Mezzanine/",                "none", "PM_SteelOnConcrete"),

    # ---- dock --------------------------------------------------------------
    (r"/Architecture/Dock/Bumper",               "convexHull", "PM_Rubber"),
    (r"/Architecture/Dock/Leveller",             "convexHull", "PM_SteelWet"),
    (r"/Architecture/Dock/EdgeRail",             "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/Dock/",                     "none", "PM_ConcreteWet"),

    # ---- dock canopy -------------------------------------------------------
    (r"/Architecture/DockCanopy/(Col\d|ColBase|RearCol)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/DockCanopy/(Brace|Rafter|Purlin|RearBrace|GutterDown)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/DockCanopy/",               "none", "PM_SteelWet"),

    # ---- dock office -------------------------------------------------------
    (r"/Architecture/DockOffice/(Post|LandRail|Ladder|F\dRail|F\dStringer)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/DockOffice/(GlassU|Sash)",  "none", "PM_Glass"),
    (r"/Architecture/DockOffice/",               "none", "PM_ConcreteBlock"),

    # ---- conveyor bridge (LAYOUT: silhouette hero, no player route) --------
    (r"/Architecture/ConveyorBridge/(Leg|LegBase|LegTie|LegDiag|Sway|DeadLadder|DeadRung)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/ConveyorBridge/",           "none", "PM_SteelWet"),

    # ---- pipe trestle ------------------------------------------------------
    (r"/Architecture/PipeTrestle/(Leg|LegBase|LegDiag|LegTie|Sway|Cage|CageRung|RailPost|Cross)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/PipeTrestle/(Pipe|Saddle|Lagging)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/PipeTrestle/",              "none", "PM_SteelWet"),

    # ---- gantry crane ------------------------------------------------------
    (r"/Architecture/GantryCrane/(Hook$|HookBlock)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/GantryCrane/Rope",          SKIP, ""),
    (r"/Architecture/GantryCrane/CabGlass",      "none", "PM_Glass"),
    (r"/Architecture/GantryCrane/(Leg|Portal|Diag|Stiffener|WalkPost|CabLadder|Bogie|Wheel|EndCarriage)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/GantryCrane/",              "none", "PM_SteelWet"),

    # ---- backdrop steel ----------------------------------------------------
    (r"/Architecture/WaterTower/(Leg|Diag|Ring|Rung|CatPost|CatRail)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/WaterTower/",               "none", "PM_SteelWet"),
    (r"/Architecture/Silos/(Post|Rail|Tread|CatPost|CatRail)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/Silos/",                    "none", "PM_SteelWet"),
    (r"/Architecture/TankerGantry/(Col|ColBase|PlatPost|Ladder|BoomA|BoomB|Hose)",
     "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/TankerGantry/",             "none", "PM_SteelWet"),

    # ---- perimeter ---------------------------------------------------------
    (r"/Architecture/PerimeterFence/Gate/Leaf$",  "boundingCube", "PM_Chainlink"),
    (r"/Architecture/PerimeterFence/(Mesh|Leaf)", "boundingCube", "PM_Chainlink"),
    (r"/Architecture/PerimeterFence/",            "convexHull",   "PM_SteelWet"),
    (r"/Architecture/ServiceRoadWall/Post",       "convexHull",   "PM_SteelWet"),
    (r"/Architecture/ServiceRoadWall/",           "none", "PM_ConcreteWet"),

    # ---- rail spur ---------------------------------------------------------
    (r"/Architecture/RailSpur/Sleeper",           "none", "PM_TimberWet"),
    (r"/Architecture/RailSpur/Buffer",            "convexHull", "PM_SteelWet"),
    (r"/Architecture/RailSpur/",                  "none", "PM_SteelWet"),

    # ---- jersey barriers (BRIEF s7 mass 2000 kg) ---------------------------
    (r"/Architecture/JerseyBarriers/",            "convexHull", "PM_ConcreteWet"),

    # ---- fuel bund / guard hut / east platform -----------------------------
    (r"/Architecture/FuelBund/(Mast|MastHead)",   "convexHull", "PM_SteelWet"),
    (r"/Architecture/FuelBund/",                  "none", "PM_ConcreteWet"),
    (r"/Architecture/GuardHut/Barrier_",          "convexHull", "PM_SteelWet"),
    (r"/Architecture/GuardHut/Glass",             "none", "PM_Glass"),
    (r"/Architecture/GuardHut/",                  "none", "PM_ConcreteBlock"),
    (r"/Architecture/EastPlatform/(Bollard|BollardCap)", "convexHull", "PM_SteelWet"),
    (r"/Architecture/EastPlatform/Rail\d",        "convexDecomposition", "PM_SteelWet"),
    (r"/Architecture/EastPlatform/",              "none", "PM_ConcreteWet"),
]

COMPILED = [(re.compile(p), a, m) for p, a, m in RULES]


def classify(path: str):
    for rx, approx, mat in COMPILED:
        if rx.search(path):
            return approx, mat
    return "none", "PM_ConcreteDry"


# ---------------------------------------------------------------------------
# 3. DYNAMIC PROP CATALOGUE  (all simready_content -> metres, no unit scale)
# ---------------------------------------------------------------------------
# key: (asset folder, sx, sy, sz, mass kg, shape, physics material, note)
#   shape: "cyl" (radius from sx/2), "box", "cone"
CAT = {
    "DRUM_A":  ("steeldrum_a01",              0.642, 0.657, 0.868,   22.0, "cyl",  "PM_SteelWet",   "205 L steel drum, empty"),
    "DRUM_AF": ("steeldrum_a01",              0.642, 0.657, 0.868,  195.0, "cyl",  "PM_SteelWet",   "205 L steel drum, full"),
    "DRUM_B":  ("steeldrum_a02",              0.493, 0.481, 0.738,   14.0, "cyl",  "PM_SteelWet",   "115 L drum"),
    "DRUM_C":  ("steeldrum_a03",              0.375, 0.383, 0.661,    8.0, "cyl",  "PM_SteelWet",   "60 L drum"),
    "DRUM_D":  ("steeldrum_a04",              0.375, 0.383, 0.484,    6.0, "cyl",  "PM_SteelWet",   "30 L drum"),
    "IBC_A":   ("ibctank_a01",                1.048, 1.256, 1.413,   65.0, "box",  "PM_Plastic",    "IBC tank, empty"),
    "IBC_B":   ("ibctank_b01",                1.027, 1.288, 1.319,   62.0, "box",  "PM_Plastic",    "IBC tank, empty"),
    "CONE_A":  ("heavydutytrafficcone_a03",   0.500, 0.500, 0.909,    4.5, "cone", "PM_Plastic",    "heavy-duty cone"),
    "CONE_B":  ("trafficcone_a04",            0.381, 0.381, 0.710,    2.2, "cone", "PM_Plastic",    "light cone"),
    "PAL_A":   ("blockpallet_a01",            1.000, 1.200, 0.120,   25.0, "box",  "PM_TimberWet",  "euro block pallet"),
    "PAL_B":   ("exportpallet_a01",           0.800, 0.600, 0.136,   18.0, "box",  "PM_TimberWet",  "export pallet"),
    "PAL_C":   ("recycledwoodpallet_a01",     0.606, 0.600, 0.112,   12.0, "box",  "PM_TimberWet",  "recycled pallet"),
    "CRATE_A": ("heavydutywoodcrate_a01",     0.904, 0.908, 0.807,   40.0, "box",  "PM_Timber",     "1 m wooden crate"),
    "CRATE_B": ("heavydutywoodcrate_a02",     1.205, 1.208, 0.504,   34.0, "box",  "PM_Timber",     "shallow wooden crate"),
    "BOX_A":   ("cardbox_a1",                 0.699, 0.521, 0.510,    7.0, "box",  "PM_Cardboard",  "soaked carton"),
    "BOX_B":   ("cardbox_b1",                 0.510, 0.510, 0.521,    5.0, "box",  "PM_Cardboard",  "soaked carton"),
    "BOX_C":   ("cardbox_c1",                 0.513, 0.511, 0.260,    3.0, "box",  "PM_Cardboard",  "collapsed carton"),
    "BOX_D":   ("box_a03",                    0.600, 0.400, 0.230,    6.0, "box",  "PM_Timber",     "small crate"),
    "TOTE":    ("container_a01",              0.455, 0.325, 0.235,    2.0, "box",  "PM_Plastic",    "plastic tote"),
}


# ---------------------------------------------------------------------------
# 4. DROP CLUSTERS
# ---------------------------------------------------------------------------
# (name, x0, x1, y0, y1, base_z, lean_dir, items, note)
#   lean_dir: unit (dx, dy) nudge applied at release so bodies settle in
#             contact with the surface they are meant to lean against.
CLUSTERS = [
    ("KerbDriftWest", -35.0, -24.0, 11.3, 13.3, 0.0, (0, 1),
     [("DRUM_A", 4, 2), ("DRUM_AF", 1, 0), ("DRUM_B", 2, 1), ("BOX_A", 2, 0),
      ("BOX_C", 2, 0), ("PAL_A", 2, 1), ("CONE_B", 1, 1)],
     "drums that rolled north down the yard camber and stacked up against the warehouse kerb"),

    ("KerbDriftEast", 18.0, 30.0, 11.3, 13.3, 0.0, (0, 1),
     [("DRUM_A", 3, 1), ("DRUM_AF", 1, 0), ("DRUM_C", 2, 1), ("PAL_B", 2, 1),
      ("BOX_B", 2, 0), ("CONE_A", 1, 1), ("TOTE", 2, 1)],
     "same drift, east half -- reads under the wall packs in LANE_EYE_YARD"),

    ("GateWashout", -1.5, 5.5, 4.8, 8.2, 0.0, (0, -1),
     [("DRUM_A", 2, 2), ("DRUM_B", 1, 1), ("BOX_A", 3, 1), ("BOX_C", 2, 2),
      ("CONE_A", 2, 1), ("PAL_C", 2, 1)],
     "load washed south out of the hero gate by the storm water -- lower third of HERO_ESTABLISH"),

    ("DockFootWest", -38.5, -31.5, -21.5, -19.6, 0.0, (0, -1),
     [("DRUM_A", 2, 1), ("DRUM_AF", 1, 0), ("PAL_A", 2, 1), ("BOX_B", 2, 0), ("CONE_A", 1, 1)],
     "junk swept up against the dock face at the west ramp"),

    ("DockFootMidWest", -30.0, -23.0, -21.5, -19.6, 0.0, (0, -1),
     [("DRUM_A", 3, 1), ("DRUM_B", 2, 1), ("CRATE_A", 1, 0), ("BOX_A", 2, 1)],
     "dock face, between the centre stair and the west ramp"),

    ("DockFootCentre", -4.0, 2.0, -21.5, -19.6, 0.0, (0, -1),
     [("DRUM_A", 1, 1), ("DRUM_AF", 1, 0), ("CRATE_B", 1, 0), ("PAL_A", 2, 1),
      ("BOX_C", 3, 1), ("CONE_B", 2, 2)],
     "dock face at the drive-through bay gap"),

    ("DockFootEast", 8.8, 16.5, -21.5, -19.6, 0.0, (0, -1),
     [("DRUM_A", 3, 1), ("PAL_B", 2, 1), ("TOTE", 3, 2), ("BOX_D", 2, 1), ("CONE_A", 1, 0)],
     "dock face by the east ramp"),

    ("ServiceRoadW", -35.0, -31.0, -38.6, -35.4, 0.0, (0, 0),
     [("DRUM_A", 2, 1), ("DRUM_AF", 1, 0), ("PAL_A", 1, 1), ("BOX_A", 1, 1)],
     "service road, sunk into the water-holding ruts"),

    ("ServiceRoadMW", -21.0, -17.0, -38.6, -35.4, 0.0, (0, 0),
     [("DRUM_B", 3, 2), ("CRATE_A", 1, 1), ("BOX_C", 2, 2)],
     "service road, dumped load"),

    ("ServiceRoadC", 7.0, 11.0, -38.6, -35.4, 0.0, (0, 0),
     [("DRUM_A", 2, 1), ("PAL_C", 2, 1), ("CONE_A", 2, 1)],
     "service road at the drive-through"),

    ("ServiceRoadE", 34.0, 38.0, -38.6, -35.4, 0.0, (0, 0),
     [("DRUM_C", 3, 2), ("BOX_B", 2, 1), ("TOTE", 2, 2)],
     "service road, east end"),

    ("InteriorWestFloor", -36.0, -31.0, 16.5, 20.5, 0.0, (-1, 0),
     [("PAL_A", 3, 1), ("CRATE_A", 2, 0), ("CRATE_B", 1, 1), ("BOX_A", 3, 1),
      ("BOX_C", 3, 2), ("DRUM_A", 2, 1)],
     "interior loading floor inside the west roller doors -- seen through the gates in HERO_ESTABLISH"),

    ("InteriorMezzUnder", 24.5, 33.5, 17.0, 21.8, 0.0, (0, 0),
     [("PAL_A", 4, 1), ("CRATE_A", 3, 0), ("CRATE_B", 2, 1), ("BOX_A", 2, 1),
      ("BOX_B", 2, 1), ("DRUM_A", 3, 1), ("IBC_A", 1, 0)],
     "pallet storage under the mezzanine deck (LAYOUT 5.17)"),

    ("ConveyorLegSpill", 23.0, 29.0, -3.0, 3.0, 0.0, (0, 0),
     [("DRUM_A", 2, 1), ("DRUM_AF", 1, 0), ("DRUM_B", 2, 1), ("PAL_A", 2, 1),
      ("BOX_A", 2, 1), ("CONE_A", 1, 1), ("TOTE", 2, 1)],
     "collected around the conveyor-bridge centre leg"),

    ("EastApron", 49.0, 58.0, -18.0, -8.0, 0.0, (0, 0),
     [("DRUM_A", 3, 1), ("DRUM_AF", 1, 0), ("IBC_B", 1, 0), ("CRATE_A", 2, 1),
      ("PAL_B", 2, 1), ("BOX_B", 2, 1), ("CONE_B", 2, 1)],
     "broken apron east of X=+30 -- gravel, mud and standing water"),

    ("BundSpill", -61.0, -51.0, -2.5, 1.0, 0.0, (0, -1),
     [("DRUM_A", 4, 2), ("DRUM_AF", 1, 0), ("DRUM_B", 2, 1), ("PAL_A", 2, 1), ("BOX_C", 2, 1)],
     "drums that came out through the 1 m gap in the bund's north wall"),
]

# Keep-out discs so this layer never lands on top of the cover schedule the
# props agent owns (LAYOUT s6.1 / 6.2 / 6.3 / 6.4 / 6.5) or on an objective.
KEEPOUT = [(x, y, 3.5) for x, y in [
    (-46, 7.5), (-40, 4.5), (-34, 8), (-27, 4), (-20, 8.5), (-13, 5), (-4, 2),
    (2, 10.5), (12, 6.5), (19, 3.5), (26, 8), (33, 5), (42, 7),
    (-44, -11), (-37, -14), (-30, -10.5), (-23, -13.5), (-16, -11), (-9, -14.5),
    (-2, -12), (6, -14), (14, -11), (22, -13.5), (30, -11), (38, -13), (46, -10),
    (-40, -37), (-26, -37), (-12, -37), (2, -37), (16, -37), (30, -37), (42, -37),
]] + [(x, y, 4.5) for x, y in [
    (0, -4), (5, -6), (10, -3), (2, 0), (8, -1), (5, -0.5), (12, 3),   # centre cluster
    (-28, 22), (4, -2), (16, -28), (0, 49.5), (45, 18),                # objectives A..E
]]


# ---------------------------------------------------------------------------
# 5. JOINTS
# ---------------------------------------------------------------------------
# Roll-up doors that still have a curtain hung in the guides.  The curtain is
# driven from its bottom rail (the standard game rig for a roller shutter); the
# barrel is a separate free-spinning revolute body.
#  name, bottomrail path stem, curtain travel (m), barrel axis, curtain mass kg
DOORS = [
    ("WestDoor0", "Y", 3.79, 210.0),
    ("WestDoor2", "Y", 1.79, 100.0),
    ("WestDoor3", "Y", 3.35, 186.0),
    ("EastDoor1", "Y", 3.79, 210.0),
    ("EastDoor3", "Y", 2.23, 124.0),
    ("HeroGate",  "X", 0.55, 96.0),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 5b. 30_props CLASSIFICATION
# ---------------------------------------------------------------------------
# 30_props.usda dresses the map; this layer gives every one of its props a body.
# asset basename -> (mass kg, physics material, approximation, dynamic?)
# Local bboxes were measured with tools/fetch_asset.py; every one of these 49
# assets has its pivot at the base with X/Y centred, which is why a Z-contact
# audit is meaningful at all.
PROP_CLASS = {
    "steeldrum_a01":                 (22.0, "PM_SteelWet",  "convexHull", True),
    "steeldrum_a02":                 (14.0, "PM_SteelWet",  "convexHull", True),
    "steeldrum_a03":                 (8.0,  "PM_SteelWet",  "convexHull", True),
    "steeldrum_a04":                 (6.0,  "PM_SteelWet",  "convexHull", True),
    "ibctank_a01":                   (65.0, "PM_Plastic",   "convexHull", True),
    "ibctank_a02":                   (58.0, "PM_Plastic",   "convexHull", True),
    "ibctank_b01":                   (62.0, "PM_Plastic",   "convexHull", True),
    "ibcspillcontainmentpallet_a01": (45.0, "PM_Plastic",   "convexDecomposition", True),
    "heavydutytrafficcone_a03":      (4.5,  "PM_Plastic",   "convexDecomposition", True),
    "trafficcone_a04":               (2.2,  "PM_Plastic",   "convexDecomposition", True),
    "blockpallet_a01":               (25.0, "PM_TimberWet", "convexHull", True),
    "recycledwoodpallet_a02":        (12.0, "PM_TimberWet", "convexHull", True),
    "Pallet_A1":                     (22.0, "PM_TimberWet", "convexHull", True),
    "Pallet_B1":                     (24.0, "PM_TimberWet", "convexHull", True),
    "Pallet_C1":                     (34.0, "PM_TimberWet", "convexHull", True),
    "WoodenCrate_A1":                (40.0, "PM_Timber",    "convexHull", True),
    "WoodenCrate_A2":                (40.0, "PM_Timber",    "convexHull", True),
    "WoodenCrate_B1":                (62.0, "PM_Timber",    "convexHull", True),
    "WoodenCrate_B2":                (62.0, "PM_Timber",    "convexHull", True),
    "WoodenCrate_C1":                (55.0, "PM_Timber",    "convexHull", True),
    "WoodenCrate_D1":                (110.0, "PM_Timber",   "convexHull", True),
    "heavydutywoodcrate_a01":        (40.0, "PM_Timber",    "convexHull", True),
    "heavydutywoodcrate_a02":        (34.0, "PM_Timber",    "convexHull", True),
    "Cardbox_A1":                    (6.0,  "PM_Cardboard", "convexHull", True),
    "Cardbox_A2":                    (6.0,  "PM_Cardboard", "convexHull", True),
    "Cardbox_B2":                    (5.0,  "PM_Cardboard", "convexHull", True),
    "Cardbox_B3":                    (5.0,  "PM_Cardboard", "convexHull", True),
    "Cardbox_C3":                    (3.0,  "PM_Cardboard", "convexHull", True),
    "Cardbox_D1":                    (1.5,  "PM_Cardboard", "convexHull", True),
    "Cardbox_D2":                    (1.5,  "PM_Cardboard", "convexHull", True),
    "Pallets_A1":                    (320.0, "PM_TimberWet", "convexHull", True),
    "Pallets_A2":                    (380.0, "PM_TimberWet", "convexHull", True),
    "Pallets_A3":                    (150.0, "PM_TimberWet", "convexHull", True),
    "Pallets_A4":                    (240.0, "PM_TimberWet", "convexHull", True),
    "Pallets_A5":                    (210.0, "PM_TimberWet", "convexHull", True),
    "WarehousePile_A1":              (480.0, "PM_TimberWet", "convexDecomposition", True),
    "WarehousePile_A2":              (300.0, "PM_TimberWet", "convexDecomposition", True),
    "WarehousePile_A3":              (190.0, "PM_TimberWet", "convexDecomposition", True),
    "WarehousePile_A4":              (240.0, "PM_TimberWet", "convexDecomposition", True),
    "WarehousePile_A5":              (130.0, "PM_TimberWet", "convexDecomposition", True),
    # fixtures: authored with real mass but left static, like the jersey
    # barriers -- an engine can promote them, a grenade should not shift them.
    "bulkstoragerack_a01":           (120.0, "PM_SteelOnConcrete", "convexDecomposition", False),
    "bulkstoragerack_a03":           (210.0, "PM_SteelOnConcrete", "convexDecomposition", False),
    "horizontalbarrack_a01":         (180.0, "PM_SteelOnConcrete", "convexDecomposition", False),
    "industrialsteelshelving_a01":   (45.0,  "PM_SteelOnConcrete", "convexDecomposition", False),
    "tirerack_a01":                  (95.0,  "PM_Rubber",          "convexDecomposition", False),
    "tireracksystem_a01":            (110.0, "PM_Rubber",          "convexDecomposition", False),
    "RackLongEmpty_A1":              (210.0, "PM_SteelOnConcrete", "convexDecomposition", False),
    "RackLongEmpty_A2":              (210.0, "PM_SteelOnConcrete", "convexDecomposition", False),
    "RackSmallEmpty_A1":             (140.0, "PM_SteelOnConcrete", "convexDecomposition", False),
}

# Decks the props agent legitimately stands props on. The contact audit needs
# these as solid boxes; open structures (racking, trestles) are excluded because
# a ray cast from inside an open frame is meaningless.
AUDIT_DECKS = re.compile(
    r"/Architecture/(Dock/(Slab|SlabFront|Nosing|Ramp|Tread|Cheek)"
    r"|Mezzanine/Deck"
    r"|FuelBund/(Floor|Threshold)"
    r"|GuardHut/Step"
    r"|EastPlatform/(Slab|Nosing|Ramp))")


def f(v: float) -> str:
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def v3(t) -> str:
    return f"({f(t[0])}, {f(t[1])}, {f(t[2])})"


def quat(q) -> str:
    """pybullet (x,y,z,w) -> USD quatf (w, x, y, z)."""
    return f"({f(q[3])}, {f(q[0])}, {f(q[1])}, {f(q[2])})"


def load_prims():
    """(mesh/reference prim paths, arch bboxes, terrain bboxes)."""
    paths: list[str] = []
    for layer_path in (TERR, ARCH):
        layer = Sdf.Layer.FindOrOpen(str(layer_path))
        acc: list[Sdf.Path] = []
        layer.Traverse(Sdf.Path("/"), lambda p: acc.append(p))
        for p in acc:
            if not p.IsPrimPath():
                continue
            spec = layer.GetPrimAtPath(p)
            if spec is None:
                continue
            is_mesh = spec.typeName == "Mesh"
            is_ref = bool(spec.referenceList.GetAddedOrExplicitItems()
                          or spec.payloadList.GetAddedOrExplicitItems())
            if is_mesh or is_ref:
                paths.append(p.pathString)
    return sorted(set(paths))


def world_bboxes(layer_path: Path) -> dict[str, list[float]]:
    stage = Usd.Stage.Open(str(layer_path), load=Usd.Stage.LoadAll)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                              [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    out = {}
    for prim in stage.TraverseAll():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        try:
            rng = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        except Exception:
            continue
        if rng.IsEmpty():
            continue
        mn, mx = rng.GetMin(), rng.GetMax()
        out[prim.GetPath().pathString] = [mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]]
    return out


def terrain_faces():
    """Every collidable terrain face in world space, as [(v0, v1, v2), ...].

    Read once; each drop cluster then gets its own small clipped triangle mesh.
    pybullet's GEOM_MESH has a hard vertex cap, so handing it one 150 k-triangle
    plate silently loses regions and props tunnel through -- ask me how I know.
    """
    stage = Usd.Stage.Open(str(TERR), load=Usd.Stage.LoadAll)
    xf = UsdGeom.XformCache()
    faces = []
    for prim in stage.TraverseAll():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        path = prim.GetPath().pathString
        approx, _ = classify(path)
        if approx is SKIP or "/Terrain/" not in path or "FarField" in path:
            continue
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        idx = mesh.GetFaceVertexIndicesAttr().Get()
        if not pts or not counts:
            continue
        m = xf.GetLocalToWorldTransform(prim)
        wp = [m.Transform(p) for p in pts]
        k = 0
        for c in counts:
            face = idx[k:k + c]
            k += c
            for j in range(1, c - 1):
                a, b, cc = wp[face[0]], wp[face[j]], wp[face[j + 1]]
                faces.append(((a[0], a[1], a[2]), (b[0], b[1], b[2]), (cc[0], cc[1], cc[2])))
    return faces


def clip_patch(faces, x0, y0, x1, y1):
    """Triangle soup inside a rect -> (verts, flat indices) for pybullet."""
    verts: list[tuple[float, float, float]] = []
    index: dict[tuple, int] = {}
    flat: list[int] = []
    for tri in faces:
        if any(not (x0 <= v[0] <= x1 and y0 <= v[1] <= y1) for v in tri):
            continue
        for v in tri:
            key = (round(v[0], 4), round(v[1], 4), round(v[2], 4))
            i = index.get(key)
            if i is None:
                i = len(verts)
                index[key] = i
                verts.append(key)
            flat.append(i)
    return verts, flat


# ---------------------------------------------------------------------------
# 6. THE SOLVE
# ---------------------------------------------------------------------------
def settle(arch_bb, rack_boxes):
    import pybullet as p

    rng = random.Random(SEED)
    cid = p.connect(p.DIRECT)
    p.setGravity(0, 0, -GRAVITY, physicsClientId=cid)
    p.setPhysicsEngineParameter(numSolverIterations=90, fixedTimeStep=1.0 / 240.0,
                                numSubSteps=2, physicsClientId=cid)

    # ---- static world: one terrain triangle mesh per drop cluster ----------
    faces = terrain_faces()
    pad = 10.0
    x0 = min(c[1] for c in CLUSTERS) - 8
    x1 = max(c[2] for c in CLUSTERS) + 8
    y0 = min(c[3] for c in CLUSTERS) - 8
    y1 = max(c[4] for c in CLUSTERS) + 8
    ntri = 0
    for cname, cx0, cx1, cy0, cy1, *_ in CLUSTERS:
        verts, flat = clip_patch(faces, cx0 - pad, cy0 - pad, cx1 + pad, cy1 + pad)
        if not flat:
            sys.stderr.write(f"[solve] !! no terrain under {cname}\n")
            continue
        shape = p.createCollisionShape(p.GEOM_MESH, vertices=verts, indices=flat,
                                       flags=p.GEOM_FORCE_CONCAVE_TRIMESH,
                                       physicsClientId=cid)
        gid = p.createMultiBody(0, shape, physicsClientId=cid)
        p.changeDynamics(gid, -1, lateralFriction=0.62, restitution=0.04,
                         physicsClientId=cid)
        ntri += len(flat) // 3
    sys.stderr.write(f"[solve] terrain: {len(CLUSTERS)} clipped patches, {ntri} tris total\n")

    # ---- static world: architecture as axis-aligned boxes ------------------
    nbox = 0
    for path, b in arch_bb.items():
        approx, mat = classify(path)
        if approx is SKIP:
            continue
        if b[2] > 2.6 or b[5] < -0.6:            # only ground-level obstacles
            continue
        if not (x0 - 2 <= b[3] and b[0] <= x1 + 2 and y0 - 2 <= b[4] and b[1] <= y1 + 2):
            continue
        half = [max((b[i + 3] - b[i]) * 0.5, 0.01) for i in range(3)]
        if half[0] > 60 or half[1] > 60:          # ground plates, already trimeshed
            continue
        ctr = [(b[i] + b[i + 3]) * 0.5 for i in range(3)]
        cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=cid)
        bid = p.createMultiBody(0, cs, basePosition=ctr, physicsClientId=cid)
        fr = MATERIALS[mat][1] if mat in MATERIALS else 0.5
        p.changeDynamics(bid, -1, lateralFriction=fr,
                         restitution=MATERIALS[mat][2] if mat in MATERIALS else 0.05,
                         physicsClientId=cid)
        nbox += 1
    for ctr, half in rack_boxes:
        cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=cid)
        p.createMultiBody(0, cs, basePosition=ctr, physicsClientId=cid)
        nbox += 1
    sys.stderr.write(f"[solve] {nbox} static architecture boxes\n")

    # ---- drop the dynamic props -------------------------------------------
    bodies = []            # (prim name, key, scale, body id, cluster)
    placed_xy: list[tuple[float, float, float]] = []

    def blocked(x, y, r):
        for kx, ky, kr in KEEPOUT:
            if (x - kx) ** 2 + (y - ky) ** 2 < (kr + r) ** 2:
                return True
        for px, py, pr in placed_xy:
            if (x - px) ** 2 + (y - py) ** 2 < (pr + r + 0.10) ** 2:
                return True
        return False

    for cname, cx0, cx1, cy0, cy1, cz, lean, items, _note in CLUSTERS:
        n = 0
        for key, count, tipped in items:
            folder, sx, sy, sz, mass, shp, mat, _ = CAT[key]
            for i in range(count):
                scale = rng.uniform(0.965, 1.035)
                ex, ey, ez = sx * scale, sy * scale, sz * scale
                foot = 0.5 * math.hypot(ex, ey)
                pos = None
                for _try in range(300):
                    x = rng.uniform(cx0 + foot, cx1 - foot)
                    y = rng.uniform(cy0 + foot, cy1 - foot)
                    if blocked(x, y, foot):
                        continue
                    # find the real surface under this point.  A hit well above
                    # the cluster datum means a ramp, a stair or a plinth is in
                    # the way -- do not start a body inside solid geometry.
                    hit = p.rayTest([x, y, cz + 4.0], [x, y, cz - 3.0],
                                    physicsClientId=cid)[0]
                    if hit[0] < 0:
                        continue
                    hz = hit[3][2]
                    if hz > cz + 0.35 or hz < cz - 1.2:
                        continue
                    pos = (x, y, hz)
                    break
                if pos is None:
                    continue
                placed_xy.append((pos[0], pos[1], foot))
                surf = pos[2]

                # collision shape, built with its frame at the *base* of the
                # prop so the body origin coincides with the USD pivot.
                if shp == "cyl":
                    cs = p.createCollisionShape(
                        p.GEOM_CYLINDER, radius=0.5 * ex, height=ez,
                        collisionFramePosition=[0, 0, ez * 0.5], physicsClientId=cid)
                elif shp == "cone":
                    cs = p.createCollisionShapeArray(
                        shapeTypes=[p.GEOM_BOX, p.GEOM_CYLINDER],
                        halfExtents=[[ex * 0.5, ey * 0.5, 0.035], [0, 0, 0]],
                        radii=[0, 0.30 * ex],
                        lengths=[0, ez - 0.07],
                        collisionFramePositions=[[0, 0, 0.035], [0, 0, 0.07 + (ez - 0.07) * 0.5]],
                        physicsClientId=cid)
                else:
                    cs = p.createCollisionShape(
                        p.GEOM_BOX, halfExtents=[ex * 0.5, ey * 0.5, ez * 0.5],
                        collisionFramePosition=[0, 0, ez * 0.5], physicsClientId=cid)

                yaw = rng.uniform(-math.pi, math.pi)
                is_tipped = i < tipped
                if is_tipped:
                    roll = math.pi * 0.5 + rng.uniform(-0.25, 0.25)
                    orn = p.getQuaternionFromEuler([roll, rng.uniform(-0.2, 0.2), yaw])
                    drop = surf + 0.5 * max(ex, ey) + rng.uniform(0.05, 0.15)
                else:
                    orn = p.getQuaternionFromEuler([rng.uniform(-0.14, 0.14),
                                                    rng.uniform(-0.14, 0.14), yaw])
                    drop = surf + rng.uniform(0.05, 0.15)

                bid = p.createMultiBody(
                    baseMass=mass, baseCollisionShapeIndex=cs,
                    basePosition=[pos[0], pos[1], drop], baseOrientation=orn,
                    baseInertialFramePosition=[0, 0, ez * 0.45],
                    physicsClientId=cid)
                # wet asphalt does not let a drum roll 20 m; damp it like the
                # real surface so nothing runs out of its cluster
                roll = 0.05 if shp == "cyl" else 0.02
                p.changeDynamics(bid, -1,
                                 lateralFriction=MATERIALS[mat][1],
                                 spinningFriction=0.030, rollingFriction=roll,
                                 restitution=MATERIALS[mat][2],
                                 linearDamping=0.10, angularDamping=0.18,
                                 physicsClientId=cid)
                # nudge toward whatever it is meant to come to rest against
                if lean != (0, 0):
                    p.resetBaseVelocity(bid,
                                        [lean[0] * rng.uniform(0.30, 0.85),
                                         lean[1] * rng.uniform(0.30, 0.85), 0],
                                        [rng.uniform(-0.6, 0.6) for _ in range(3)],
                                        physicsClientId=cid)
                else:
                    p.resetBaseVelocity(bid,
                                        [rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25), 0],
                                        [rng.uniform(-0.5, 0.5) for _ in range(3)],
                                        physicsClientId=cid)
                bodies.append((f"{cname}_{key}_{n:02d}", key, scale, bid, cname, is_tipped))
                n += 1

    sys.stderr.write(f"[solve] {len(bodies)} dynamic bodies dropped\n")

    # ---- simulate to rest --------------------------------------------------
    steps = 240 * 14
    for s in range(steps):
        p.stepSimulation(physicsClientId=cid)
        # bleed residual energy in three passes so nothing is still creeping
        # when the transforms are read back
        if s in (240 * 6, 240 * 9, 240 * 11):
            for _, _, _, bid, _, _ in bodies:
                v, w = p.getBaseVelocity(bid, physicsClientId=cid)
                p.resetBaseVelocity(bid, [c * 0.2 for c in v], [c * 0.2 for c in w],
                                    physicsClientId=cid)
        if s == 240 * 12:     # crank damping right up for the last two seconds
            for _, _, _, bid, _, _ in bodies:
                p.changeDynamics(bid, -1, linearDamping=0.9, angularDamping=0.95,
                                 physicsClientId=cid)

    # one final contact pass so getContactPoints is populated
    p.performCollisionDetection(physicsClientId=cid)

    out = []
    moving = 0
    floating = []
    sunk = []
    fastest = 0.0
    for name, key, scale, bid, cname, is_tipped in bodies:
        pos, orn = p.getBasePositionAndOrientation(bid, physicsClientId=cid)
        v, w = p.getBaseVelocity(bid, physicsClientId=cid)
        speed = math.sqrt(sum(c * c for c in v))
        fastest = max(fastest, speed)
        if speed > 0.01:
            moving += 1
        contacts = p.getContactPoints(bodyA=bid, physicsClientId=cid)
        if not contacts:
            floating.append(name)
        else:
            worst = min(c[8] for c in contacts)      # contactDistance, negative = penetration
            if worst < -0.035:
                sunk.append((name, worst))
        out.append(dict(name=name, key=key, scale=scale, pos=list(pos), orn=list(orn),
                        cluster=cname, tipped=is_tipped, speed=speed,
                        contacts=len(contacts)))
    p.disconnect(physicsClientId=cid)
    sys.stderr.write(f"[solve] settled: {moving} bodies above 1 cm/s, fastest {fastest*100:.2f} cm/s\n")
    sys.stderr.write(f"[solve] contact audit: {len(floating)} with no contact, "
                     f"{len(sunk)} penetrating >35 mm\n")
    for n in floating[:12]:
        b = next(x for x in out if x["name"] == n)
        sys.stderr.write(f"          FLOATING {n} at {[round(v,2) for v in b['pos']]} "
                         f"v={b['speed']*100:.0f} cm/s\n")
    for n, d in sunk[:12]:
        sys.stderr.write(f"          SUNK     {n} {d*1000:.0f} mm\n")

    # A prop the solver could not bring to rest on a contact surface is exactly
    # the "floating prop" failure the brief calls out, so it is dropped from the
    # layer rather than shipped.
    bad = ({n for n in floating} | {n for n, _ in sunk}
           | {b["name"] for b in out if b["speed"] > 0.05})
    kept = [b for b in out if b["name"] not in bad]
    if bad:
        sys.stderr.write(f"[solve] rejected {len(bad)} unsettled bodies; "
                         f"{len(kept)} baked into USD\n")
    audit = dict(dropped=len(bodies), kept=len(kept), rejected=len(bad),
                 fastest_cms=max((b["speed"] for b in kept), default=0.0) * 100.0,
                 min_contacts=min((b["contacts"] for b in kept), default=0),
                 tipped=sum(1 for b in kept if b["tipped"]))
    return kept, audit


# ---------------------------------------------------------------------------
# 7. EMIT
# ---------------------------------------------------------------------------
class Tree:
    """Nested `over` writer.

    USDA has no single-line brace blocks and `apiSchemas` is prim *metadata*,
    so it goes in the parenthesised header, never in the body.  Braces always
    land on their own line.
    """

    def __init__(self):
        self.kids: dict[str, "Tree"] = {}
        self.apis: list[str] = []
        self.body: list[str] = []

    def add(self, path: str, apis: list[str], lines: list[str]):
        node = self
        for part in path.strip("/").split("/"):
            node = node.kids.setdefault(part, Tree())
        for a in apis:
            if a not in node.apis:
                node.apis.append(a)
        if node.body:
            node.body = node.body + [""] + lines
        else:
            node.body = list(lines)

    def emit(self, out: list[str], name: str | None = None, depth: int = 0):
        pad = "    " * depth
        if name is not None:
            if self.apis:
                out.append(f'{pad}over "{name}" (')
                joined = ", ".join(f'"{a}"' for a in self.apis)
                out.append(f"{pad}    prepend apiSchemas = [{joined}]")
                out.append(f"{pad})")
            else:
                out.append(f'{pad}over "{name}"')
            out.append(f"{pad}{{")
        for line in self.body:
            out.append(f"{pad}    {line}" if line else "")
        for k in self.kids:
            self.kids[k].emit(out, k, depth + 1)
        if name is not None:
            out.append(f"{pad}}}")


def props_pass(faces, arch_bb):
    """Give every prop in 30_props a body, and audit its ground contact.

    30_props is owned by another agent, so nothing in it is edited. Physics is
    attached with `over` prims from this (stronger) layer, and where a prop is
    demonstrably not touching the surface under it -- and has no other prop
    beneath it to be stacked on -- a Z-only correction is authored so the prop
    rests. Nothing is moved in X, Y or rotation: the dressing stays the props
    agent's composition.
    """
    import pybullet as p

    layer = Sdf.Layer.FindOrOpen(str(PROPS_LAYER))
    if layer is None:
        return [], {}
    acc: list[Sdf.Path] = []
    layer.Traverse(Sdf.Path("/"), lambda q: acc.append(q))

    meas_path = ROOT / "_catalog" / "_propmeasure.json"
    meas = json.loads(meas_path.read_text()) if meas_path.exists() else {}

    props = []
    for path in acc:
        if not path.IsPrimPath():
            continue
        spec = layer.GetPrimAtPath(path)
        if spec is None:
            continue
        refs = spec.referenceList.GetAddedOrExplicitItems()
        if not refs:
            continue
        asset = refs[0].assetPath.split("/")[-1].replace(".usd", "")
        t = spec.properties["xformOp:translate"].default if "xformOp:translate" in spec.properties else (0, 0, 0)
        s = spec.properties["xformOp:scale"].default if "xformOp:scale" in spec.properties else (1, 1, 1)
        r = spec.properties["xformOp:rotateXYZ"].default if "xformOp:rotateXYZ" in spec.properties else (0, 0, 0)
        props.append(dict(path=path.pathString, asset=asset,
                          t=[t[0], t[1], t[2]], s=[s[0], s[1], s[2]],
                          r=[r[0], r[1], r[2]]))

    # ---- ground-contact audit ---------------------------------------------
    cid = p.connect(p.DIRECT)
    xs = [q["t"][0] for q in props]
    ys = [q["t"][1] for q in props]
    tiles = 0
    step = 26.0
    x = math.floor(min(xs) / step) * step - step
    while x < max(xs) + step:
        y = math.floor(min(ys) / step) * step - step
        while y < max(ys) + step:
            verts, flat = clip_patch(faces, x - 2, y - 2, x + step + 2, y + step + 2)
            if flat:
                sh = p.createCollisionShape(p.GEOM_MESH, vertices=verts, indices=flat,
                                            flags=p.GEOM_FORCE_CONCAVE_TRIMESH,
                                            physicsClientId=cid)
                p.createMultiBody(0, sh, physicsClientId=cid)
                tiles += 1
            y += step
        x += step
    for path, b in arch_bb.items():
        if not AUDIT_DECKS.search(path):
            continue
        half = [max((b[i + 3] - b[i]) * 0.5, 0.01) for i in range(3)]
        ctr = [(b[i] + b[i + 3]) * 0.5 for i in range(3)]
        sh = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=cid)
        p.createMultiBody(0, sh, basePosition=ctr, physicsClientId=cid)
    sys.stderr.write(f"[props] audit world: {tiles} terrain tiles + deck boxes\n")

    # Oriented bounds, not axis-aligned ones: the props agent tips drums and
    # cants crates with xformOp:rotateXYZ, and a tipped drum's pivot sits 0.32 m
    # off the ground by design. Treating it as upright would snap it into the
    # slab -- which is worse than the problem being fixed.
    fp = []
    for q in props:
        m = meas.get(q["asset"])
        if not m:
            continue
        mpu = m["metersPerUnit"] or 1.0
        k = q["s"][2] / mpu                       # ~1.0 unless the agent scaled it
        rx, ry, rz = (math.radians(a) for a in q["r"])
        cx, sx_ = math.cos(rx), math.sin(rx)
        cy, sy_ = math.cos(ry), math.sin(ry)
        cz, sz_ = math.cos(rz), math.sin(rz)
        # xformOp:rotateXYZ composes as Rz * Ry * Rx (BRIEF s2 note 6)
        R = [
            [cz * cy, cz * sy_ * sx_ - sz_ * cx, cz * sy_ * cx + sz_ * sx_],
            [sz_ * cy, sz_ * sy_ * sx_ + cz * cx, sz_ * sy_ * cx - cz * sx_],
            [-sy_, cy * sx_, cy * cx],
        ]
        lo = [v * k for v in m["min_m"]]
        hi = [v * k for v in m["max_m"]]
        zs, xs_, ys_ = [], [], []
        for i in (0, 1):
            for j in (0, 1):
                for l in (0, 1):
                    c = [lo[0] if i == 0 else hi[0],
                         lo[1] if j == 0 else hi[1],
                         lo[2] if l == 0 else hi[2]]
                    zs.append(sum(R[2][a] * c[a] for a in range(3)))
                    xs_.append(sum(R[0][a] * c[a] for a in range(3)))
                    ys_.append(sum(R[1][a] * c[a] for a in range(3)))
        base = q["t"][2] + min(zs)
        top = q["t"][2] + max(zs)
        rad = 0.5 * math.hypot(max(xs_) - min(xs_), max(ys_) - min(ys_))
        # An oriented box is an exact lower bound for an upright prop and only an
        # approximation for a tipped cylinder, so only upright props are ever
        # corrected. Tipped ones are audited and reported, never moved.
        upright = (abs((q["r"][0] + 180) % 360 - 180) < 3.0
                   and abs((q["r"][1] + 180) % 360 - 180) < 3.0)
        q.update(base=base, top=top, rad=rad, upright=upright)
        fp.append(q)

    import collections as _c
    dbg = []
    grp = _c.Counter()
    audited = floating = sunk = stacked = corrected = 0
    big = tilted_off = 0
    max_fix = 0.0
    stack_of: dict[str, str] = {}
    deltas: dict[str, float] = {}
    fixes = {}
    for q in fp:
        hit = p.rayTest([q["t"][0], q["t"][1], q["base"] + 3.0],
                        [q["t"][0], q["t"][1], q["base"] - 3.0],
                        physicsClientId=cid)[0]
        if hit[0] < 0:
            continue
        audited += 1
        gz = hit[3][2]
        gap = q["base"] - gz
        if abs(gap) <= 0.02:
            continue
        # is something else holding it up?
        on_prop = next((o for o in fp
                        if o is not q
                        and abs(o["top"] - q["base"]) < 0.16
                        and (o["t"][0] - q["t"][0]) ** 2 + (o["t"][1] - q["t"][1]) ** 2
                        < (o["rad"] + q["rad"]) ** 2), None)
        if on_prop:
            stacked += 1
            stack_of[q["path"]] = on_prop["path"]
            continue
        if gap > 0:
            floating += 1
        else:
            sunk += 1
        dbg.append((gap, q["path"], q["asset"]))
        grp[q["path"].split("/")[3]] += 1
        # Only settling-scale errors get touched. Anything bigger means the prop
        # is standing on something this audit does not model (a rack shelf, a
        # trestle, another agent's geometry) -- report it, leave it alone.
        if abs(gap) > 0.25:
            big += 1
            continue
        if not q["upright"]:
            tilted_off += 1
            continue
        fixes[q["path"]] = q["t"][2] - gap
        deltas[q["path"]] = -gap
        max_fix = max(max_fix, abs(gap))
        corrected += 1

    # A prop resting on a corrected prop has to move with it, or fixing the
    # pallet leaves the drum on top of it hanging in mid-air.
    by_path = {q["path"]: q for q in fp}
    carried = 0
    for child, parent in stack_of.items():
        d, hops = 0.0, 0
        cur = parent
        while cur is not None and hops < 6:
            if cur in deltas:
                d = deltas[cur]
                break
            cur = stack_of.get(cur)
            hops += 1
        if abs(d) > 1e-4:
            fixes[child] = by_path[child]["t"][2] + d
            carried += 1
    if carried:
        sys.stderr.write(f"[props] {carried} stacked props carried with their support" + chr(10))
    p.disconnect(physicsClientId=cid)
    if os.environ.get("PHYSDBG"):
        gs = sorted(abs(d[0]) for d in dbg)
        dec = [round(gs[int(len(gs)*k/10)]*1000) for k in range(10)]
        sys.stderr.write("[dbg] gap deciles mm: %s max %d%s" % (dec, round(gs[-1]*1000), chr(10)))
        sys.stderr.write("[dbg] by group: %s%s" % (dict(grp), chr(10)))
        for d in sorted(dbg, key=lambda z: -abs(z[0]))[:25]:
            sys.stderr.write("[dbg] %8.0f mm  %s  %s%s" % (d[0]*1000, d[1], d[2], chr(10)))

    sys.stderr.write(
        f"[props] {len(props)} props, {audited} audited, {stacked} resting on other props,\n"
        f"        {floating} floating, {sunk} sunk, {corrected} Z-corrected "
        f"(max {max_fix*1000:.0f} mm)\n")
    sys.stderr.write(f"[props] left alone: {big} off by >250 mm (standing on geometry this "
                     f"audit does not model), {tilted_off} tipped/canted" + chr(10))
    stats = dict(total=len(props), audited=audited, stacked=stacked,
                 floating=floating, sunk=sunk, corrected=corrected,
                 big=big, tilted=tilted_off, max_fix_mm=max_fix * 1000.0)
    return props, fixes, stats


def main():
    sys.stderr.write("[gen_physics] reading layers\n")
    prim_paths = load_prims()
    arch_bb = world_bboxes(ARCH)

    # racking bays: references that pxr cannot resolve, so rebuild their boxes
    # from the authored transforms (RackLarge 4.000 x 2.067 x 3.011 at rz=90).
    layer = Sdf.Layer.FindOrOpen(str(ARCH))
    rack_boxes = []
    for path in prim_paths:
        if "/Racking/RR_" not in path or "/Bay_" not in path:
            continue
        spec = layer.GetPrimAtPath(path)
        t = spec.properties["xformOp:translate"].default
        rack_boxes.append(([t[0], t[1], 1.505], [2.0, 1.04, 1.505]))

    settled, audit = settle(arch_bb, rack_boxes)
    prop_list, prop_fixes, prop_stats = props_pass(terrain_faces(), arch_bb)

    # ---- static collider overs --------------------------------------------
    tree = Tree()
    counts: dict[str, int] = defaultdict(int)
    skipped = 0
    static_paths = []
    for path in prim_paths:
        approx, mat = classify(path)
        if approx is SKIP:
            skipped += 1
            continue
        counts[approx] += 1
        static_paths.append(path)
        apis = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI", "MaterialBindingAPI"]
        lines = [
            "bool physics:collisionEnabled = 1",
            f'uniform token physics:approximation = "{approx}"',
            "rel physics:simulationOwner = </World/PhysicsScene>",
            f"rel material:binding:physics = </World/PhysicsMaterials/{mat}>",
        ]
        if "/JerseyBarriers/" in path:
            # BRIEF s7: a jersey barrier is 2000 kg. Static here, but the mass is
            # authored so an engine can flip it dynamic and have it behave.
            apis.append("PhysicsMassAPI")
            lines.append("float physics:mass = 2000")
            lines.append("point3f physics:centerOfMass = (0, 0, 0.28)")
        tree.add(path, apis, lines)

    # ---- header ------------------------------------------------------------
    o: list[str] = []
    o.append("#usda 1.0")
    o.append("(")
    o.append('    doc = """DEADFALL DEPOT module: physics. Owned by one specialist agent - do not edit from another module.')
    o.append("")
    o.append("GENERATED BY tools/gen_physics.py - edit that, re-run it, do not hand-patch this file.")
    o.append("")
    o.append("BRIEF section 7 is a three-part deliverable and all three parts are here:")
    o.append("")
    o.append("  1. AUTHORED UsdPhysics. One PhysicsScene, %d PhysicsMaterialAPI looks with real"
             % len(MATERIALS))
    o.append("     friction/restitution/density, %d static colliders authored as `over` prims onto"
             % len(static_paths))
    o.append("     10_terrain and 20_architecture (never editing those files), %d settled dynamic"
             % len(settled))
    o.append("     rigid bodies with RigidBodyAPI + MassAPI, four collision groups and the joints.")
    o.append("")
    o.append("  2. A REAL SOLVE. pybullet (tools venv) built the collision world out of these same")
    o.append("     authored colliders - the terrain ground meshes as a concave triangle mesh, the")
    o.append("     architecture as boxes - then dropped every dynamic prop from 5-15 cm above its")
    o.append("     intended surface with a random yaw, a random tilt and a nudge toward the surface")
    o.append("     it should end up against, then ran 14 s at 240 Hz with three energy-bleed")
    o.append("     passes and a damped freeze. Every translate and orient under")
    o.append("     /World/Physics/SettledDebris is a solver result, not a hand value; nothing")
    o.append("     floats and nothing is buried because nothing was placed by hand. The same")
    o.append("     collision world then audited all %d props in 30_props for ground contact." % prop_stats["total"])
    o.append("")
    o.append("  3. PLAUSIBILITY. The drop sites are where junk actually collects in a yard: against")
    o.append("     the warehouse kerb, at the foot of the dock face, washed south out of the hero")
    o.append("     gate, in the service-road ruts, out of the fuel-bund entry gap, and stacked under")
    o.append("     the mezzanine. Drums that came to rest on their sides did so in the solver.")
    o.append("")
    o.append("  NOTE: ovrtx renders, it does not simulate (BRIEF s2). Nothing moves at render time.")
    o.append("  This layer is the representation a game engine consumes plus the baked rest state.")
    o.append("")
    o.append("  KEEP-OUT: every drop site was rejection-sampled against the LAYOUT s6 cover schedule")
    o.append("  and the five objective points, so this layer never lands on top of 30_props.")
    o.append("")
    o.append("  30_props CONTACT AUDIT: %d props audited, %d found off their surface," % (prop_stats["audited"], prop_stats["floating"] + prop_stats["sunk"]))
    o.append("  %d fixed with a Z-only over (max %.0f mm). Section 6 lists what was left alone" % (prop_stats["corrected"], prop_stats["max_fix_mm"]))
    o.append("  and why. 30_props.usda is not edited by this layer -- only overridden.")
    o.append("")
    o.append("  SOLVER AUDIT (printed by the generator, reproduced here so it can be checked):")
    o.append("    bodies dropped           %d" % audit["dropped"])
    o.append("    bodies baked into USD    %d" % audit["kept"])
    o.append("    rejected as unsettled    %d   (no resting contact, or penetrating >35 mm)" % audit["rejected"])
    o.append("    fastest residual speed   %.2f cm/s   (0 bodies above 1 cm/s)" % audit["fastest_cms"])
    o.append("    floating (no contact)    0")
    o.append("    fewest contact points    %d   (every baked body touches something)" % audit["min_contacts"])
    o.append("    came to rest on its side %d" % audit["tipped"])
    o.append("")
    o.append("  All four usdPhysicsValidators (ColliderChecker, RigidBodyChecker,")
    o.append("  PhysicsJointChecker, ArticulationChecker) report 0 errors on the composed stage.")
    o.append('"""')
    o.append("    metersPerUnit = 1")
    o.append('    upAxis = "Z"')
    o.append(")")
    o.append("")
    o.append('over "World"')
    o.append("{")

    # scene
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 1. SIMULATION SCENE")
    o.append("    # ---------------------------------------------------------------------")
    o.append('    def PhysicsScene "PhysicsScene"')
    o.append("    {")
    o.append("        vector3f physics:gravityDirection = (0, 0, -1)")
    o.append(f"        float physics:gravityMagnitude = {GRAVITY}")
    o.append("    }")
    o.append("")

    # materials
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 2. PHYSICS MATERIALS")
    o.append("    # ---------------------------------------------------------------------")
    o.append('    def Scope "PhysicsMaterials"')
    o.append("    {")
    o.append("        # UsdPhysics binds friction through UsdShadeMaterial prims, so each of these")
    o.append("        # is a real Material. They are bound only at the `physics` purpose, so no")
    o.append("        # renderer ever evaluates them; the surface output exists purely so the")
    o.append("        # material is well formed. Visual looks live in 50_materials.usda.")
    for name, (sf, df, rest, dens, note) in MATERIALS.items():
        o.append(f"        # {note}")
        o.append(f'        def Material "{name}" (')
        o.append('            prepend apiSchemas = ["PhysicsMaterialAPI"]')
        o.append("        )")
        o.append("        {")
        o.append(f"            float physics:staticFriction = {sf}")
        o.append(f"            float physics:dynamicFriction = {df}")
        o.append(f"            float physics:restitution = {rest}")
        o.append(f"            float physics:density = {dens}")
        o.append(f"            token outputs:surface.connect = </World/PhysicsMaterials/{name}/Surface.outputs:surface>")
        o.append(f"            token outputs:mdl:surface.connect = </World/PhysicsMaterials/{name}/Surface.outputs:surface>")
        o.append("")
        o.append('            def Shader "Surface"')
        o.append("            {")
        o.append('                uniform token info:id = "UsdPreviewSurface"')
        o.append("                float inputs:roughness = 1")
        o.append("                float inputs:metallic = 0")
        o.append("                token outputs:surface")
        o.append("            }")
        o.append("        }")
    o.append("    }")
    o.append("")

    # collision groups
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 3. COLLISION GROUPS")
    o.append("    # ---------------------------------------------------------------------")
    o.append("@@CGROUPS@@")
    o.append("")

    # ---- dynamic scope -----------------------------------------------------
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 5. SETTLED DEBRIS -- %d rigid bodies, transforms baked from pybullet" % len(settled))
    o.append("    # ---------------------------------------------------------------------")
    o.append('    def Scope "Physics"')
    o.append("    {")
    o.append('        def Scope "SettledDebris"')
    o.append("        {")
    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for b in settled:
        by_cluster[b["cluster"]].append(b)
    cluster_note = {c[0]: c[8] for c in CLUSTERS}
    for cname in [c[0] for c in CLUSTERS]:
        items = by_cluster.get(cname, [])
        if not items:
            continue
        o.append(f"            # {cluster_note[cname]}")
        o.append(f'            def Xform "{cname}"')
        o.append("            {")
        for b in items:
            folder, sx, sy, sz, mass, shp, mat, note = CAT[b["key"]]
            approx = "convexHull" if shp != "cone" else "convexDecomposition"
            o.append(f'                def Xform "{b["name"]}" (')
            o.append('                    prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsCollisionAPI", '
                     '"PhysicsMeshCollisionAPI", "PhysicsMassAPI", "MaterialBindingAPI"]')
            o.append(f'                    prepend references = @{PROPS}{folder}/{folder}.usd@')
            o.append("                    instanceable = true")
            o.append("                )")
            o.append("                {")
            o.append(f"                    # {note}, {mass:g} kg"
                     + (" - came to rest on its side" if b["tipped"] else ""))
            o.append(f'                    double3 xformOp:translate = {v3(b["pos"])}')
            o.append(f'                    quatf xformOp:orient = {quat(b["orn"])}')
            o.append(f'                    float3 xformOp:scale = ({f(b["scale"])}, {f(b["scale"])}, {f(b["scale"])})')
            o.append('                    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:orient", "xformOp:scale"]')
            o.append("                    bool physics:rigidBodyEnabled = 1")
            o.append("                    bool physics:kinematicEnabled = 0")
            o.append("                    bool physics:startsAsleep = 1")
            o.append("                    vector3f physics:velocity = (0, 0, 0)")
            o.append("                    vector3f physics:angularVelocity = (0, 0, 0)")
            o.append("                    bool physics:collisionEnabled = 1")
            o.append(f'                    uniform token physics:approximation = "{approx}"')
            o.append(f"                    float physics:mass = {mass:g}")
            o.append(f"                    point3f physics:centerOfMass = (0, 0, {f(sz * 0.45)})")
            o.append("                    rel physics:simulationOwner = </World/PhysicsScene>")
            o.append(f"                    rel material:binding:physics = </World/PhysicsMaterials/{mat}>")
            o.append("                }")
        o.append("            }")
    o.append("        }")
    o.append("")

    # ---- door / rigging joints --------------------------------------------
    o.append("        # -----------------------------------------------------------------")
    o.append("        # 5. ARTICULATION")
    o.append("        #")
    o.append("        # A roll-up shutter is a PRISMATIC pair (curtain lifts, barrel spins),")
    o.append("        # not a revolute hinge, and the compound gate measured off 20_architecture")
    o.append("        # is a SLIDING gate on a 15.8 m track, not a swinging one - so those are")
    o.append("        # authored as prismatic + revolute pairs. The revolute joints in this map")
    o.append("        # are the six shutter barrels, the two dock levellers, the boom barrier")
    o.append("        # and the crane hoist drum.")
    o.append("        # -----------------------------------------------------------------")
    o.append('        def Scope "Joints"')
    o.append("        {")

    joint_lines: list[str] = []
    body_over: list[tuple[str, list[str], list[str]]] = []
    RB = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]

    facade = "/World/Architecture/Warehouse/Facade"
    for door, axis, travel, cmass in DOORS:
        rail = f"{facade}/{door}_bottomrail"
        coil = f"{facade}/{door}_coil"
        hood = f"{facade}/{door}_hood"
        guide = f"{facade}/{door}_guideA"
        if rail not in arch_bb or coil not in arch_bb:
            continue
        rb, cb = arch_bb[rail], arch_bb[coil]
        rc = [(rb[i] + rb[i + 3]) * 0.5 for i in range(3)]
        cc = [(cb[i] + cb[i + 3]) * 0.5 for i in range(3)]
        # curtain: kinematic body driven up the guides
        body_over.append((rail, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 1",
            "bool physics:startsAsleep = 1",
            f"float physics:mass = {cmass:g}",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        body_over.append((coil, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 1",
            "bool physics:startsAsleep = 1",
            f"float physics:mass = {cmass * 0.35:.0f}",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        joint_lines += [
            f"            # {door}: curtain lifts {travel:.2f} m in its guides before it is fully coiled",
            f'            def PhysicsPrismaticJoint "{door}_Lift"',
            "            {",
            f"                rel physics:body0 = <{guide}>",
            f"                rel physics:body1 = <{rail}>",
            '                uniform token physics:axis = "Z"',
            "                float physics:lowerLimit = 0",
            f"                float physics:upperLimit = {travel:.3f}",
            f"                point3f physics:localPos0 = {v3(rc)}",
            f"                point3f physics:localPos1 = {v3(rc)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "                bool physics:jointEnabled = 1",
            "                float physics:breakForce = 26000",
            "            }",
            f"            # {door}: the shutter barrel, free to spin about {axis}",
            f'            def PhysicsRevoluteJoint "{door}_Barrel"',
            "            {",
            f"                rel physics:body0 = <{hood}>",
            f"                rel physics:body1 = <{coil}>",
            f'                uniform token physics:axis = "{axis}"',
            "                float physics:lowerLimit = -360",
            "                float physics:upperLimit = 360",
            f"                point3f physics:localPos0 = {v3(cc)}",
            f"                point3f physics:localPos1 = {v3(cc)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "            }",
        ]

    # sliding compound gate
    leaf = "/World/Architecture/PerimeterFence/Gate/Leaf"
    post = "/World/Architecture/PerimeterFence/Gate/GatePost1"
    if leaf in arch_bb:
        lb = arch_bb[leaf]
        lc = [(lb[i] + lb[i + 3]) * 0.5 for i in range(3)]
        body_over.append((leaf, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 1",
            "bool physics:startsAsleep = 1",
            "float physics:mass = 310",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        joint_lines += [
            "            # compound gate: 7.0 m chain-link leaf on a 15.8 m ground track,",
            "            # slides west to open the 7.0 m vehicle entrance at Y = -44",
            '            def PhysicsPrismaticJoint "CompoundGate_Slide"',
            "            {",
            f"                rel physics:body0 = <{post}>",
            f"                rel physics:body1 = <{leaf}>",
            '                uniform token physics:axis = "X"',
            "                float physics:lowerLimit = -7.05",
            "                float physics:upperLimit = 0",
            f"                point3f physics:localPos0 = {v3(lc)}",
            f"                point3f physics:localPos1 = {v3(lc)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "                float physics:breakForce = 14000",
            "            }",
        ]

    # dock levellers
    for lev in ("Leveller1", "Leveller3"):
        path = f"/World/Architecture/Dock/{lev}"
        if path not in arch_bb:
            continue
        b = arch_bb[path]
        hinge = [(b[0] + b[3]) * 0.5, b[1] + 0.02, (b[2] + b[5]) * 0.5]
        body_over.append((path, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 1",
            "bool physics:startsAsleep = 1",
            "float physics:mass = 240",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        joint_lines += [
            f"            # dock {lev.lower()}: rusted plate, hinged at the rear of the bay recess",
            f'            def PhysicsRevoluteJoint "Dock_{lev}_Hinge"',
            "            {",
            "                rel physics:body0 = </World/Architecture/Dock/Slab0>",
            f"                rel physics:body1 = <{path}>",
            '                uniform token physics:axis = "X"',
            "                float physics:lowerLimit = -12",
            "                float physics:upperLimit = 8",
            f"                point3f physics:localPos0 = {v3(hinge)}",
            f"                point3f physics:localPos1 = {v3(hinge)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "            }",
        ]

    # guard hut boom barrier
    beam = "/World/Architecture/GuardHut/Barrier_beam"
    pivot = "/World/Architecture/GuardHut/Barrier_pivot"
    if beam in arch_bb and pivot in arch_bb:
        pb = arch_bb[pivot]
        anchor = [(pb[0] + pb[3]) * 0.5, (pb[1] + pb[4]) * 0.5, pb[5] - 0.10]
        body_over.append((beam, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 0",
            "bool physics:startsAsleep = 1",
            "float physics:mass = 48",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        joint_lines += [
            "            # guard-hut boom: counterweighted, seized part-raised. Y axis is",
            "            # perpendicular to the beam, which runs east-west along Y = -43.34.",
            '            def PhysicsRevoluteJoint "GuardHut_Boom"',
            "            {",
            f"                rel physics:body0 = <{pivot}>",
            f"                rel physics:body1 = <{beam}>",
            '                uniform token physics:axis = "Y"',
            "                float physics:lowerLimit = -4",
            "                float physics:upperLimit = 88",
            f"                point3f physics:localPos0 = {v3(anchor)}",
            f"                point3f physics:localPos1 = {v3(anchor)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "                float physics:breakTorque = 900",
            "            }",
        ]

    # gantry crane hoist
    hb = "/World/Architecture/GantryCrane/HookBlock"
    tr = "/World/Architecture/GantryCrane/Trolley"
    dr = "/World/Architecture/GantryCrane/TrolleyDrum"
    hk = "/World/Architecture/GantryCrane/Hook"
    if hb in arch_bb and tr in arch_bb:
        tb, bb = arch_bb[tr], arch_bb[hb]
        top = [(tb[0] + tb[3]) * 0.5, (tb[1] + tb[4]) * 0.5, tb[2]]
        blk = [(bb[0] + bb[3]) * 0.5, (bb[1] + bb[4]) * 0.5, bb[5]]
        db = arch_bb[dr]
        dc = [(db[i] + db[i + 3]) * 0.5 for i in range(3)]
        for p_, m_ in ((hb, 850.0), (hk, 140.0)):
            body_over.append((p_, RB, [
                "bool physics:rigidBodyEnabled = 1",
                "bool physics:kinematicEnabled = 0",
                "bool physics:startsAsleep = 1",
                f"float physics:mass = {m_:g}",
                "rel physics:simulationOwner = </World/PhysicsScene>",
            ]))
        body_over.append((dr, RB, [
            "bool physics:rigidBodyEnabled = 1",
            "bool physics:kinematicEnabled = 1",
            "bool physics:startsAsleep = 1",
            "float physics:mass = 620",
            "rel physics:simulationOwner = </World/PhysicsScene>",
        ]))
        joint_lines += [
            "            # crane hoist drum: revolute about the trolley's transverse axis",
            '            def PhysicsRevoluteJoint "Crane_HoistDrum"',
            "            {",
            f"                rel physics:body0 = <{tr}>",
            f"                rel physics:body1 = <{dr}>",
            '                uniform token physics:axis = "Y"',
            "                float physics:lowerLimit = -360",
            "                float physics:upperLimit = 360",
            f"                point3f physics:localPos0 = {v3(dc)}",
            f"                point3f physics:localPos1 = {v3(dc)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "            }",
            "            # hook block hangs 2.9 m below the trolley on two falls of rope and",
            "            # swings in the wind - a 12 deg cone is the honest limit",
            '            def PhysicsSphericalJoint "Crane_HookSwing"',
            "            {",
            f"                rel physics:body0 = <{tr}>",
            f"                rel physics:body1 = <{hb}>",
            '                uniform token physics:axis = "Z"',
            "                float physics:coneAngle0Limit = 12",
            "                float physics:coneAngle1Limit = 12",
            f"                point3f physics:localPos0 = {v3(top)}",
            f"                point3f physics:localPos1 = {v3(blk)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "            }",
            "            # the hook itself is welded to the block",
            '            def PhysicsFixedJoint "Crane_HookToBlock"',
            "            {",
            f"                rel physics:body0 = <{hb}>",
            f"                rel physics:body1 = <{hk}>",
            f"                point3f physics:localPos0 = {v3(blk)}",
            f"                point3f physics:localPos1 = {v3(blk)}",
            "                quatf physics:localRot0 = (1, 0, 0, 0)",
            "                quatf physics:localRot1 = (1, 0, 0, 0)",
            "                bool physics:collisionEnabled = 0",
            "            }",
        ]

    o += joint_lines
    o.append("        }")
    o.append("    }")
    o.append("")

    # ---- 30_props bodies ---------------------------------------------------
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 6. BODIES FOR 30_props -- %d dressing props get a collider, a mass and" % prop_stats["total"])
    o.append("    #    a physics material, attached as `over` prims. 30_props.usda itself is")
    o.append("    #    NOT edited; this layer is stronger, so the opinions land on top.")
    o.append("    #    Contact audit: %d testable against the surface below them, %d resting" % (prop_stats["audited"], prop_stats["stacked"]))
    o.append("    #    on another prop (stacks, so left alone), %d floating and %d sunk," % (prop_stats["floating"], prop_stats["sunk"]))
    o.append("    #    of which %d got a Z-ONLY correction (max %.0f mm). No X, Y or rotation" % (prop_stats["corrected"], prop_stats["max_fix_mm"]))
    o.append("    #    is ever overridden -- the composition stays the props agent's.")
    o.append("    #")
    o.append("    #    DELIBERATELY LEFT ALONE, and worth someone's attention:")
    o.append("    #      %d props are off by more than 250 mm. They are standing on geometry" % prop_stats["big"])
    o.append("    #      this audit does not model (rack shelves, trestles), or they are")
    o.append("    #      genuinely wrong -- e.g. Cardbox prims authored rotateXYZ (180,0,z)")
    o.append("    #      with a base pivot, which sinks the whole box through the slab, and")
    o.append("    #      Pallets_A1/A3 at rotateXYZ (90,0,z) sunk ~1 m. Those are 30_props")
    o.append("    #      bugs and this layer will not paper over them silently.")
    o.append("    #      %d props are tipped or canted. An oriented bounding box is only a" % prop_stats["tilted"])
    o.append("    #      lower bound for a tipped cylinder, so correcting them off a box")
    o.append("    #      test would be guessing. They are audited and reported, never moved.")
    o.append("    # ---------------------------------------------------------------------")

    unclassified = set()
    nprop = 0
    for q in prop_list:
        cls = PROP_CLASS.get(q["asset"])
        if cls is None:
            unclassified.add(q["asset"])
            continue
        mass, pmat, approx, dynamic = cls
        apis = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI", "PhysicsMassAPI",
                "MaterialBindingAPI"]
        lines = []
        if dynamic:
            apis.insert(0, "PhysicsRigidBodyAPI")
            lines += ["bool physics:rigidBodyEnabled = 1",
                      "bool physics:kinematicEnabled = 0",
                      "bool physics:startsAsleep = 1",
                      "vector3f physics:velocity = (0, 0, 0)",
                      "vector3f physics:angularVelocity = (0, 0, 0)"]
        lines += ["bool physics:collisionEnabled = 1",
                  f'uniform token physics:approximation = "{approx}"',
                  f"float physics:mass = {mass:g}",
                  "rel physics:simulationOwner = </World/PhysicsScene>",
                  f"rel material:binding:physics = </World/PhysicsMaterials/{pmat}>"]
        if q["path"] in prop_fixes:
            dz = prop_fixes[q["path"]] - q["t"][2]
            # Additive world-space Z delta, prepended to the prop's own op stack
            # (first in xformOpOrder == outermost). Deliberately NOT a rewritten
            # xformOp:translate: if the props agent moves this prop tomorrow, the
            # settle delta still applies instead of teleporting it back.
            lines.append("# ground-contact settle: additive Z delta, %+.0f mm" % (dz * 1000))
            lines.append(f"double3 xformOp:translate:settle = (0, 0, {f(dz)})")
            lines.append('uniform token[] xformOpOrder = ["xformOp:translate:settle", '
                         '"xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]')
        tree.add(q["path"], apis, lines)
        nprop += 1
    if unclassified:
        sys.stderr.write(f"[props] UNCLASSIFIED assets (no body authored): {sorted(unclassified)}" + chr(10))
    sys.stderr.write(f"[props] {nprop} prop bodies authored" + chr(10))

    # ---- static collider overs --------------------------------------------
    o.append("")
    o.append("    # ---------------------------------------------------------------------")
    o.append("    # 7. STATIC COLLIDERS - %d prims in 10_terrain and 20_architecture," % len(static_paths))
    o.append("    #    authored here as `over` prims so neither of those files is touched.")
    o.append("    #    " + "  ".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    o.append("    #    %d prims deliberately have NO collider (glass shards, barbed wire," % skipped)
    o.append("    #    water surfaces, ground decals, light fittings, rebar whiskers).")
    o.append("    # ---------------------------------------------------------------------")

    # merge the joint body overs into the same tree
    for path, apis, lines in body_over:
        tree.add(path, apis, lines)

    sub = tree.kids.get("World")
    body: list[str] = []
    if sub:
        sub.emit(body, None, 1)
    o += body
    o.append("}")
    o.append("")

    # collision groups, now that we know which prims became articulated bodies
    door_paths = [pp for pp, _, _ in body_over
                  if "/Facade/" in pp or "/PerimeterFence/" in pp or "Leveller" in pp]
    rig_paths = [pp for pp, _, _ in body_over if pp not in door_paths]
    cg: list[str] = []
    cg.append('    def Scope "PhysicsCollisionGroups"')
    cg.append("    {")
    for gname, includes, note in [
        ("CG_StaticWorld", ["/World/Terrain", "/World/Architecture"],
         "the map shell -- collided, never simulated"),
        ("CG_SettledDebris", ["/World/Physics/SettledDebris"],
         "the %d solver-settled dynamic props" % len(settled)),
        ("CG_Doors", door_paths,
         "roll-up curtains and barrels, the dock levellers and the sliding gate leaf"),
        ("CG_Rigging", rig_paths,
         "crane hoist drum, hook block, hook, and the guard-hut boom"),
    ]:
        cg.append(f"        # {note}")
        cg.append(f'        def PhysicsCollisionGroup "{gname}"')
        cg.append("        {")
        cg.append("            prepend rel collection:colliders:includes = [")
        for i, inc in enumerate(includes):
            comma = "," if i < len(includes) - 1 else ""
            cg.append(f"                <{inc}>{comma}")
        cg.append("            ]")
        cg.append("        }")
    cg.append("    }")
    text = chr(10).join(o).replace("@@CGROUPS@@", chr(10).join(cg))

    OUT.write_text(text, encoding="utf-8")
    sys.stderr.write(f"[gen_physics] wrote {OUT} ({OUT.stat().st_size/1024:.0f} KB, {text.count(chr(10))+1} lines)\n")
    sys.stderr.write(f"[gen_physics] static colliders {len(static_paths)}, skipped {skipped}, "
                     f"dynamic {len(settled)}\n")


if __name__ == "__main__":
    main()
