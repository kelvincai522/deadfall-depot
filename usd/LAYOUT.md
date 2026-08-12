# DEADFALL DEPOT — SPATIAL PLAN (LAYOUT AUTHORITY)

Author: layout agent. Every other module builds against this file.
Units: **metres**. Up: **+Z**. **+X = east, +Y = north.** World origin `(0,0,0)` is
the centre of the central yard, on the yard's finished asphalt surface.

Everything in this document is measured, not guessed. Asset dimensions were
verified with `tools/fetch_asset.py` before placement; the measurements are
quoted inline so you can re-check them.

---

## 0. TL;DR for each specialist

| Module | The three things you must not get wrong |
|---|---|
| `10_terrain` | Ground plate spans X `[-75, +75]`, Y `[-56, +94]`. Finished surface is **Z = 0.000 everywhere** including the warehouse slab — no step at the gate line. Puddles are *recessed* to Z = -0.045 with a water surface at Z = -0.012. |
| `20_architecture` | Warehouse01 goes at translate `(-1.24, 46.00, 0.00)`, scale `0.01`. Everything else in §5 is procedural box/cylinder geometry — the library has **no** dock, fence, silo, crane or vehicle assets. Build them. |
| `30_props` | Cover cadence in §6 is a hard requirement, not a suggestion: hard cover ≥ 0.9 m every **8–12 m** along every walking line. No asset repeated at the same yaw within 20 m. |
| `40_vegetation` | Weeds only in the cracks, the OOB margin, and the ballast. Poplar tree lines at Y = -52 and X = -73 (§5.19). Nothing inside the playable core taller than 1.4 m. |
| `50_materials` | Ground needs ≥ 6 distinguishable ground looks (§4). One tiled asphalt = automatic fail. |
| `60_lighting` | Sun is **WSW, 5.5° elevation** — `DistantLight rotateXYZ = (84.5, 0, 290.0)`. Practical positions in §8. |
| `70_physics` | Colliders per §9. The warehouse is a static triangle-mesh collider; the racking is box-approximated. |
| `80_fx` | Haze must be thickest in the yard and inside the warehouse (§8.4) — the sun shafts have nothing to catch otherwise. |
| `90_cameras` | Five shots, exact transforms in §7. `horizontalAperture = 36.0`, `verticalAperture = 20.25`, 16:9. |

---

## 1. The map in one paragraph

A rain-soaked distribution depot at the moment the storm breaks. A 76 × 73 m
steel warehouse occupies the north half of the site; its south face is a wall of
roller doors, and a 7.4 m truck gate sits dead centre of it. South of the
building is the yard — patched asphalt, standing water, pallet loads, drums,
IBC tanks — and south of *that* is a raised concrete loading dock under a steel
canopy. A conveyor bridge crosses the yard at X ≈ +26; an open pipe trestle
crosses it at X ≈ -30. Spawns sit at the west (fuel bay) and east (rail spur)
ends, 128 m apart. The last of the sun comes in from the west-southwest at 5.5°,
raking the corrugated south wall while sodium vapour practicals fight it.

Reference DNA: MW2019 *Hackney Yard* (wet yard + long lit building wall),
*Rundown* (industrial verticality), MWII *Farm 18* (interior racking maze).

---

## 2. Footprint and extents

| Extent | X | Y | Size |
|---|---|---|---|
| Terrain plate (incl. OOB margin) | `-75 … +75` | `-56 … +94` | **150 × 150 m** |
| Playable core | `-70 … +70` | `-46 … +76.25` | **140 × 122 m** |
| Spawn-to-spawn distance | `(-64, 4)` → `(+64, 4)` | | **128 m** |
| Vertical | | | Z `0 … 26` (water tower top) |

Spawn-to-first-contact at the centre cluster is ~64 m each side ≈ 13–15 s of
sprint. That is the COD number. The map is deliberately **not** larger; density
is doing the work.

---

## 3. Lane structure

Three lanes run **east–west** between the two spawns. Cross-connections are
listed with the exact coordinate at which they open.

```
        Y = +94  ┌──────────── NORTH OOB BACKDROP (silos, annex, weeds) ──────────┐
        Y=+76.25 ├───────────────────────────────────────────────────────────────┤
                 │                                                               │
                 │   LANE A — WAREHOUSE INTERIOR   (racking maze, 6 rack runs)    │
                 │   X -38 … +38    Y +15 … +76.25    ceiling 14.3 / ridge 18.0   │
                 │                                                               │
        Y = +15  ├══ ROLLER-DOOR WALL  X -37.9 … +2.6 ══╡ solid X +2.6 … +38 ════╡
                 │                                                               │
   W  │  LANE B — CENTRAL YARD          X -52 … +52    Y -16 … +15          │  E
   S  │  (contested middle at X -6…+14, Y -8…+6)                            │  S
   P  │                                                                      │  P
        Y = -16  ├─── ramps @ X -46/-14/+18 ─── dock face Y = -22 ──────────────┤
                 │   LANE C — LOADING DOCK (deck top Z +1.20, canopy Z +5.40)     │
                 │   X -52 … +52    Y -40 … -16     dock office roof Z +7.50      │
        Y = -40  ├──── rear service road  Y -40 … -34  (secondary flank) ────────┤
        Y = -56  └──────────── SOUTH OOB (ditch, poplar line, fence) ────────────┘
```

### 3.1 Lane A — Warehouse interior (north)

The building is entered through three gate walls (all measured off the asset,
see §5.1):

* **South roller doors** — X `-37.85 … +2.62`, at Y = 15.00, opening 0…3.80 m.
  This is the primary A↔B connection and it is *huge*: 40 m of openable wall.
* **South hero gate** — X `-3.15 … +3.16`, 7.39 m tall. The map's focal point.
* **West roller doors** — X = -37.85, Y `15.37 … 57.53`, 0…3.80 m. Connects
  Lane A to the west spawn.
* **East roller doors** — X = +37.84, Y `33.47 … 57.53`, 0…3.80 m. Connects
  Lane A to the east spawn.
* **Glass personnel door** — X `-1.74 … +1.73` at Y = 15.02, Z 1.90…2.57.

Because the south gates stop at X = +2.62, **the south-east quarter of the
interior is a hard, sealed corner.** That asymmetry is deliberate: it is the
defender's interior anchor, and it is where the mezzanine goes.

Interior circulation is a **six-run racking maze** (§5.16). Rack runs are E–W
walls 3.01 m tall; you cannot see over them. Aisles run E–W at Y = 33.5, 41.5,
**49.5 (the main through-lane)**, 57.5, 65.5, 73.4. N–S movement happens only
through the staggered gaps cut into each run — no two runs have their gaps in
the same X column, so there is no straight N–S corridor anywhere.

### 3.2 Lane B — Central yard (middle)

31 m deep, 104 m long. Two walking lines:

* **North sub-lane, Y ≈ +6** — hugs the roller-door wall. Fast, exposed to the
  interior through every open gate, and covered by anyone inside.
* **South sub-lane, Y ≈ -12.5** — hugs the dock. Covered from the dock deck.

Between them, the **centre cluster** at X `-6 … +14`, Y `-8 … +6` — the map's
power position. It holds Lane B, it can see through the hero gate, and it is
overlooked by both the interior mezzanine and the dock office roof. Take it and
you win the middle; hold it too long and you die from above. That risk/reward
trade is the whole point of the map.

### 3.3 Lane C — Loading dock (south)

A 12 m deep concrete dock platform, **top at Z = +1.20**, running X `-46 … +30`
at Y `-34 … -22`, under a steel canopy at Z = +5.40. Four recessed truck bays
break the deck face at X = -38, -22, -6, +10. It is the elevated flank: 1.2 m of
height over the yard, hard cover along the dock face, and a canopy roof that
kills any fire from above.

Behind it, the **rear service road** at Y `-40 … -34` is a 6 m wide secondary
flank connecting both spawns behind the dock. It is narrow, dark, and dressed
with parked dollies and skips — a knife route, not a lane.

### 3.4 Cross-connections (no lane is a dead end)

| # | From | To | Where |
|---|---|---|---|
| X1 | Lane A | Lane B | 40 m of roller doors, Y = 15, X `-37.9 … +2.6` |
| X2 | Lane A | Lane B | Hero gate, X `-3.15 … +3.16`, Y = 15 |
| X3 | Lane A | west spawn | West doors, X = -37.85, Y `15.4 … 57.5` |
| X4 | Lane A | east spawn | East doors, X = +37.84, Y `33.5 … 57.5` |
| X5 | Lane B | Lane C | West ramp, X `-46 … -40`, Y `-22 … -16`, 1:5 grade |
| X6 | Lane B | Lane C | Centre stair, X `-15.5 … -12.5`, Y = -22, 6 risers |
| X7 | Lane B | Lane C | East ramp, X `+18 … +24`, Y `-22 … -16`, 1:5 grade |
| X8 | Lane C | service road | Bay gap at X `+2 … +8`, drive-through Y `-34 … -22` |
| X9 | Lane C | east spawn | Dock office external stair, X `+46 … +47.6`, Y `-30 … -24` → roof Z +7.50 |
| X10 | Lane B | east spawn | Open apron, X `+38 … +52`, Y `-14 … +6` |
| X11 | Lane B | west spawn | Open apron, X `-52 … -38`, Y `-14 … +12` |
| X12 | Lane A | Lane A (vertical) | Mezzanine stair, X = +23.4, Y `+31 … +35`, deck Z +4.20 |

Twelve connections across three lanes. Every lane has at least three ways in and
three ways out; every dead end I could find has been opened.

---

## 4. Zones and ground treatment

The terrain agent owns all of this. **The single most common way to fail this
brief is a uniformly tiled ground plane.** There are eight zones and each one
gets a distinct treatment.

### Z0 — GROUND PLATE (OOB margin)
`(-75, -56, -0.25) → (+75, +94, 0.00)`
Base plate under everything. Outside the playable core: compacted gravel, mud
ruts, broken concrete slabs half-buried, weeds through the cracks. Surface falls
0.15 m from the perimeter toward the yard so the water reads as *draining*.

### Z1 — WAREHOUSE INTERIOR
`(-38, +15, 0.00) → (+38, +76.25, 18.00)`
Power-trowelled concrete slab, sealed, **worn through to aggregate along the
aisle centrelines**. Forklift tyre-scuff arcs at every rack-run gap. Oil drip
trails running E–W down the main aisle. Aisle paint supplied by
`MarkingLines.usd` (§5.2). **Water ingress:** a 2–3 m wet fan inside every open
south roller door, and a 6 m slick fanning in from the hero gate at X = 0 — that
slick catches the low sun coming through the gate and is what makes the interior
shot work. Slab joints on a 6.0 m grid, several spalled.

### Z2 — CENTRAL YARD (Lane B)
`(-52, -16, -0.20) → (+52, +15, 0.00)`
Patched asphalt over an older concrete slab. Required layering:
* three visually distinct asphalt patch materials (fresh black, oxidised grey,
  crumbling aggregate), patch boundaries irregular, 4–14 m across
* exposed slab joints on a 5.0 m grid where the asphalt has worn away
* a 0.5 m cast-iron trench drain running E–W at **Y = -14.5**, X `-40 … +34`,
  grate top at Z = -0.030
* a second trench drain running N–S at **X = +18**, Y `-14.5 … +12`
* a 1.5 m wide, 0.12 m high concrete kerb strip against the warehouse wall at
  Y = 13.5, X `-38 … +38`, chipped and rebar-exposed in three places
* faded painted truck-turning circle, radius 9 m, centred (0, 2)

**Puddles** (recess to Z = -0.045, water surface Z = -0.012):

| ID | Centre | Size (m) | Job |
|---|---|---|---|
| P1 | `(-30, -3)` | 9.0 × 5.0 | mirrors the pipe trestle |
| P2 | `(2, -9)` | 12.0 × 6.0 | the big one — mirrors the warehouse + storm sky. Hero shot's lower third. |
| P3 | `(26, +6)` | 5.0 × 4.0 | mirrors the conveyor bridge |
| P4 | `(-8.5, -17.5)` | 7.0 × 4.5 | **SHOT 4 subject.** Must catch the reflection of the dock canopy sodium at `(-6, -23, 5.4)`. |
| P5 | `(44, -6)` | 6.0 × 3.5 | east apron, catches the sun disc in SHOT 5 |
| P6 | `(-48, +9)` | 4.0 × 3.0 | diesel-rainbow sheen, fuel bay overflow |

### Z3 — LOADING DOCK APRON (Lane C)
`(-52, -40, 0.00) → (+52, -16, 8.00)`
Concrete apron X `-46 … +30` with painted truck bays (4.0 m wide, faded yellow,
heavily tyre-scuffed, worn away entirely in the wheel paths). East of X = +30
the apron has broken up into **gravel and mud with standing water**. A 0.35 m
wide band of permanently wet, algae-dark concrete runs along the dock foot at
Y = -21.0. The rear service road (Y `-40 … -34`) is compacted mud with two deep
wheel ruts holding water.

### Z4 — WEST FUEL BAY / WEST SPAWN
`(-70, -24, 0.00) → (-38, +34, 6.00)`
Cracked asphalt inner, 6 m gravel apron at the outer edge. A 14 × 10 m
**oil-black concrete pad** under the tanker gantry, centred `(-56, +6)` — this
should read as the darkest ground in the map. Rutted mud with standing water at
`(-52, +4)`. Diesel rainbow sheen on P6. Weeds through every crack at the fence
line.

### Z5 — EAST RAIL SPUR / EAST SPAWN
`(+38, -24, 0.00) → (+70, +60, 10.00)`
Ballast gravel bed 4.4 m wide centred on X = +54, crown at Z = +0.10, running
Y `-30 … +60`, with rails and sleepers (§5.14). Mud and rank weeds between the
sleepers. Concrete loading-platform slab X `+40 … +50`, Y `+6 … +30`, top
Z = +1.10. Cracked asphalt elsewhere, sand drift against the fence.

### Z6 — NORTH BACKDROP (OOB)
`(-52, +76.25, 0.00) → (+52, +94, 4.00)`
Gravel service strip, waist-high weeds, broken concrete, stacked pallet waste.
Not enterable. Contains the warehouse's own low office annex (part of
Warehouse01, world X `13.79 … 26.20`, Y `75.81 … 88.25`, roof Z 3.20).

### Z7 — SOUTH PERIMETER (OOB)
`(-75, -56, 0.00) → (+75, -40, 14.00)`
Mud, rank weeds, gravel. A drainage ditch running E–W at Y = -48, 2.5 m wide,
0.6 m deep, holding standing water the full length. Poplar tree line at Y = -52.

---

## 5. Landmark placements — exact world coordinates

`scale 0.01` is required on every `Assets/ArchVis/`, `Assets/Skies/`,
`Assets/Vegetation/` reference. `Assets/simready_content/` is already metres —
**do not scale it.**

### 5.1 WAREHOUSE01 — the anchor
```
asset      Assets/ArchVis/Industrial/Buildings/Warehouse/Warehouse01.usd
translate  (-1.24, 46.00, 0.00)
rotateXYZ  (0, 0, 0)
scale      (0.01, 0.01, 0.01)
```
Local bbox `min (-36.76, -31.00, 0.00)`, `max (39.24, 42.25, 17.99)`.
The translate is chosen so the **south gate wall lands exactly on Y = +15.00**
and the building is **centred on X = 0** (world X `-38.00 … +38.00`).

Resulting world geometry (all verified against the asset's mesh bboxes):

| Feature | World |
|---|---|
| South (gate) wall | Y = 15.00 |
| North wall, main hall | Y = 76.25 |
| West wall | X = -38.00 |
| East wall | X = +38.00 (gate plane X = +37.84) |
| Truss / ceiling | Z ≈ 14.33 |
| Ridge | Z = 17.99 |
| Interior lamp fittings (`SM_Lamp_A1`) | X `-27.06 … +27.05`, Y `17.67 … 73.37`, Z `8.08 … 13.12` |
| Clerestory glazing | Z up to 17.96 |
| Blue-banded north wall | Y `73.26 … 76.25`, Z 0 … 10.21 |
| Office annex | X `13.79 … 26.20`, Y `75.81 … 88.25`, Z 0 … 3.20 |

### 5.2 WAREHOUSE FLOOR MARKINGS
```
asset      Assets/ArchVis/Industrial/Buildings/Warehouse/MarkingLines.usd
translate  (0.00, 46.00, 0.006)
scale      (0.01, 0.01, 0.01)
```
Local bbox `min (-37.84, -30.19, 0)` `max (37.84, 42.23, 0.001)` — this asset is
centred on its own X = 0, which is **1.24 m different from the warehouse's
pivot**, hence translate X = 0.00 rather than -1.24. Lifted 6 mm to beat
z-fighting against the slab.

### 5.3 DOCK PLATFORM  *(procedural — no asset exists)*
`PROCEDURAL/concrete_dock_platform` at `(-8.00, -28.00, 0.00)`
Slab X `-46 … +30`, Y `-34 … -22`, **top Z = +1.20**, 0.35 m chipped nosing with
exposed rebar in three places. Four recessed truck bays 3.6 m wide × 1.0 m deep
cut into the north face at X = -38, -22, -6, +10, each with a pair of black
rubber dock bumpers (0.35 × 0.25 × 0.45) and a rusted dock leveller plate. Bay
gap (drive-through to the service road) at X `+2 … +8`.

### 5.4 DOCK CANOPY  *(procedural)*
`PROCEDURAL/steel_dock_canopy` at `(-8.00, -27.50, 0.00)`
Corrugated roof deck X `-46 … +30`, Y `-35 … -20`, **underside Z = +5.40**,
0.35 m thick, falling 0.25 m to a gutter along Y = -20. Eleven Ø0.30 m columns
on the line Y = -21.00 at X = -44, -36.8, -29.6, -22.4, -15.2, -8, -0.8, +6.4,
+13.6, +20.8, +28. Three roof panels missing (X ≈ -30, -4, +19) so rain-light
falls through in bars. Sodium wall-packs under the fascia — see §8.2.

### 5.5 DOCK OFFICE  *(procedural)*
`PROCEDURAL/dock_office_block` at `(+38.00, -27.00, 0.00)`
Two-storey block X `+30 … +46`, Y `-34 … -20`, parapet **Z = +7.50**. Blockwork,
water-stained, two ground-floor windows blown out. External steel stair on the
east face, X `+46 … +47.6`, Y `-30 … -24`, landing at Z +7.50. **The roof is a
legal power position** overlooking Lane C and the east half of Lane B.

### 5.6 CONVEYOR BRIDGE (east)  *(procedural)*
`PROCEDURAL/enclosed_conveyor_bridge` at `(+25.90, -3.50, 5.90)`
Enclosed truss X `+24.6 … +27.2`, spanning Y `-22 … +15`, **deck Z = +5.90**,
ridge Z = +9.10. Corrugated skin with six panels missing. Legs (0.35 m box
section, cross-braced) at Y = +10, 0, -12, -21. North end terminates in a
1.8 m square stub tower against the warehouse wall; **the access ladder is
collapsed — no player route.** This is the single most important silhouette
element in the map: it crosses the yard's E–W sightline, throws shadow bars
across the wet asphalt, and in SHOT 5 the sun burns underneath it.

### 5.7 PIPE TRESTLE (west)  *(procedural)*
`PROCEDURAL/open_pipe_trestle` at `(-30.00, +3.50, 5.20)`
Open steel trestle X `-31 … -29`, spanning Y `-8 … +15`, **deck Z = +5.20**,
carrying four Ø0.40 m lagged pipes up to Z +5.90 (lagging split, insulation
hanging). Legs at Y = +12, +4, -6. South end is a 1.8 m square stub tower at
Y = -8 with a caged ladder (cage crushed — no player route). Deliberately
*different* from 5.6 so the two do not read as a repeat.

### 5.8 GANTRY CRANE (east skyline)  *(procedural)*
`PROCEDURAL/rail_gantry_crane` at `(+54.00, +26.00, 0.00)`
Portal legs at X = +44 and X = +64, footprint Y `+24 … +28`. Main beam soffit
**Z = +9.00**, top of beam Z = +10.60. Trolley at X = +52 with a hook block hung
at Z = +5.50. Straddles the rail spur. Primary east-side skyline silhouette;
reads clearly over the warehouse in SHOT 1.

### 5.9 WATER TOWER (north-east backdrop)  *(procedural)*
`PROCEDURAL/steel_water_tower` at `(+58.00, +70.00, 0.00)`
Four splayed legs from a 7 m square base to a Ø9.0 m riveted tank,
tank **Z 14.00 … 24.00**, conical roof to **Z = 26.00**, catwalk and handrail at
Z = 14.00. Out of bounds. Its job is to be visible over the warehouse roof from
the yard so the background layer is never empty.

### 5.10 SILO PAIR (north-west backdrop)  *(procedural)*
`PROCEDURAL/storage_silos` at `(-58.00, +64.00, 0.00)`
Two cylinders Ø7.0: one at `(-58, +64)`, Z 0 … 16.00; one at `(-49, +68)`,
Z 0 … 12.50. Conical tops, external spiral stair on the taller one, connecting
catwalk at Z = +12.00. Out of bounds, north-west backdrop.

### 5.11 FUEL BUND WALL  *(procedural)*
`PROCEDURAL/concrete_bund` at `(-56.00, -9.00, 0.00)`
Open-topped concrete bund, outer X `-64 … -48`, Y `-14 … -4`, wall 0.30 m thick,
**top Z = +0.90**. Interior floor at Z = -0.20 holding 0.15 m of oily standing
water. A 1.0 m gap in the north wall at X = -56 is the way in. Contains 3 IBC
tanks and 18 steel drums (§6.3). Chest-high cover with a lethal interior.

### 5.12 TANKER LOADING GANTRY  *(procedural)*
`PROCEDURAL/loading_gantry` at `(-54.00, +8.00, 0.00)`
Two Ø0.35 m columns at `(-58, +8)` and `(-50, +8)`, cross-beam soffit
**Z = +4.60**, folded access platform at Z = +3.20, articulated hose boom hanging
to Z = +2.10. West-spawn landmark and sightline break.

### 5.13 COMPOUND FENCE  *(procedural)*
`PROCEDURAL/chainlink_perimeter` at `(0, 0, 0)`
2.40 m chain-link on Ø0.06 m posts at 3.0 m centres, three-strand barbed top
canted outward. Runs:
* X = -70, Y `-46 … +40`
* Y = -44, X `-70 … +66`
* X = +66, Y `-44 … +58`
* Y = +92, X `-56 … +60` (north OOB)
Three bays are leaning or collapsed — at `(-70, +12)`, `(+18, -44)`,
`(+66, +20)` — because a pristine perimeter fence in a derelict depot is a lie.
Note: `Assets/ArchVis/Industrial/Railing/MetalFencing_A*.usd` measured
0.23–1.23 × 0.23–0.73 × **1.072 m** — those are *handrail* modules, not fencing.
Use them on the dock edge and the mezzanine, **not** for the perimeter.

### 5.14 RAIL SPUR  *(procedural)*
`PROCEDURAL/rail_and_ballast` at `(+54.00, +15.00, 0.00)`
Ballast crown 4.4 m wide, top Z = +0.10. Rails (0.075 × 0.16 head, top
Z = +0.28) at X = +53.28 and X = +54.72. Sleepers 2.60 × 0.26 × 0.16 at 0.65 m
centres, Y `-30 … +60`, every fourth one rotted or missing.

### 5.15 EAST LOADING PLATFORM  *(procedural)*
`PROCEDURAL/concrete_platform` at `(+45.00, +18.00, 0.00)`
Slab X `+40 … +50`, Y `+6 … +30`, **top Z = +1.10**. Ramp down to grade at
Y `+2 … +6`. Two Ø0.20 m steel bollards at `(+41, +8)` and `(+49, +8)`.

### 5.16 WAREHOUSE RACKING — six runs
```
asset      Assets/ArchVis/Industrial/Racks/RackLarge_A1.usd
scale      (0.01, 0.01, 0.01)
rotateXYZ  (0, 0, 90)
```
Measured: local `min (-1.0333, -2.000, 0.000)` `max (1.0333, 2.000, 3.0113)` —
**pivot is centred in X and Y, base sits on Z = 0.** With `rotate_z = 90` each
unit occupies **4.000 m in X × 2.067 m in Y × 3.011 m tall**, so `translate =
(x_centre, y_centre, 0)` places it directly.

Six runs, 8.00 m pitch in Y, giving **5.94 m aisles**:

| Run | Y centre | Y extent | Unit X centres | Gaps (no units) |
|---|---|---|---|---|
| RR-S3 | 29.5 | 28.47 … 30.53 | -36 + 4k, k = 0…18 | omit k where X ∈ {-20, -16} and {+12, +16} |
| RR-S2 | 37.5 | 36.47 … 38.53 | same | omit X ∈ {-32, -28} and {0, +4} |
| RR-S1 | 45.5 | 44.47 … 46.53 | same | omit X ∈ {-12, -8} and {+24, +28} |
| RR-N1 | 53.5 | 52.47 … 54.53 | same | omit X ∈ {-28, -24} and {+8, +12} |
| RR-N2 | 61.5 | 60.47 … 62.53 | same | omit X ∈ {-4, 0} and {+20, +24} |
| RR-N3 | 69.5 | 68.47 … 70.53 | same | omit X ∈ {-36, -32} and {+14, +18} |

Every gap is 8.0 m of clear N–S passage, and **no two runs share a gap column**,
so there is no straight N–S corridor through the interior. Resulting aisles:

| Aisle | Y centre | Width | Role |
|---|---|---|---|
| South loading floor | 21.7 | 13.47 m | inside the roller doors — trucks, staging, A↔B |
| A1 | 33.50 | 5.94 m | |
| A2 | 41.50 | 5.94 m | |
| **A3 (main through-lane)** | **49.50** | 5.94 m | west door → east door. SHOT 2. |
| A4 | 57.50 | 5.94 m | |
| A5 | 65.50 | 5.94 m | |
| North service aisle | 73.39 | 5.72 m | flank behind everything |

Vary each run: use `RackLarge_A1 … A9` and `RackLong_A1 … A9` interchangeably
(RackLong measures 1.081 × 4.000 × 3.109 and makes a shallower run), leave 3–4
bays empty, tilt two bays 4–6° as if struck by a forklift, and collapse one bay
entirely at `(-22, 45.5)`.

### 5.17 INTERIOR MEZZANINE (south-east)  *(procedural)*
`PROCEDURAL/steel_mezzanine` at `(+30.00, +23.00, 0.00)`
Deck X `+22 … +38`, Y `+15 … +31`, **deck top Z = +4.20**, 0.02 m chequer plate
on 0.35 m I-beams at 3.2 m centres, 1.10 m handrail (use
`MetalFencing_A2.usd`, 1.230 × 0.230 × 1.072, scale 0.01, on 1.2 m pitch).
Open stair at X = +23.4, Y `+31 … +35`. Underside is pallet storage. This is the
interior's power position and it covers the sealed south-east corner.

### 5.18 CENTRE CLUSTER (the contested middle)  *(props + procedural)*
Anchor `(+4.00, -1.00, 0.00)`, occupying X `-6 … +14`, Y `-8 … +6`. Contents in
§6.2. This is the map's focal point at ground level; it must read as a distinct
*object* from 60 m away, not as scattered clutter.

### 5.19 TREE LINES
```
asset      Assets/Vegetation/Trees/Lombardy_Poplar.usd   (4.84 × 4.49 × 13.67 m)
scale      (0.01, 0.01, 0.01)   ± 6 % per instance
```
* **South line** — Y = -52.0, X from -60 to +60 at ~9.0 m pitch (15 trees),
  jitter Y ± 1.8 m, yaw random 0–360°, scale 0.94–1.06.
* **West line** — X = -73.0, Y from -20 to +40 at ~9.0 m pitch (8 trees). One of
  these must sit at approximately `(-73, +6)` so it clips the sun disc in
  SHOT 5 and dapples it.
* Two `Black_Oak.usd` (25.4 × 24.1 × 19.7 m) at `(-70, -50)` and `(+68, -50)` as
  heavy canopy anchors on the south-west and south-east corners.

---

## 6. Cover schedule — the 8-to-12-metre rule

**Rule for the props agent, non-negotiable:** along every walking line there is
a piece of hard cover at least 0.90 m tall every **8–12 m**, alternating side of
the centreline. No asset appears twice at the same yaw within 20 m. Every
instance gets a random yaw and a ±5 % uniform scale. Everything rests on its
contact surface — all the props below have their pivot at the base (verified).

Verified prop dimensions used here:

| Asset | Size (m) | Metres? |
|---|---|---|
| `simready…/steeldrum_a01` | 0.642 × 0.657 × 0.868 | yes, no scale |
| `simready…/ibctank_a01` | 1.048 × 1.256 × 1.413 | yes |
| `simready…/ibctank_b01` | 1.027 × 1.288 × 1.319 | yes |
| `simready…/bulkstoragerack_a01` | 0.906 × 1.552 × 1.836 | yes |
| `simready…/bulkstoragerack_a03` | 1.226 × 2.454 × 2.431 | yes |
| `simready…/horizontalbarrack_a01` | 1.544 × 2.861 × 1.270 | yes |
| `simready…/tireracksystem_a01` | 0.503 × 1.883 × 2.500 | yes |
| `simready…/tirerack_a01` | 0.850 × 1.530 × 2.314 | yes |
| `simready…/industrialsteelshelving_a01` | 0.311 × 0.918 × 2.411 | yes |
| `simready…/heavydutytrafficcone_a03` | 0.500 × 0.500 × 0.909 | yes |
| `simready…/trafficcone_a04` | 0.381 × 0.381 × 0.710 | yes |
| `ArchVis…/Piles/WarehousePile_A1` | 3.525 × 3.087 × 2.027 | **cm — scale 0.01** |
| `ArchVis…/Piles/WarehousePile_A4` | 1.727 × 1.925 × 1.507 | cm |
| `ArchVis…/Piles/Pallets_A1` | 1.896 × 2.133 × 1.461 | cm |
| `ArchVis…/Piles/Pallets_A3` | 1.293 × 1.293 × 1.044 | cm |
| `ArchVis…/Wooden/WoodenCrate_A1` | 1.002 × 1.009 × 1.017 | cm |
| `ArchVis…/Wooden/WoodenCrate_C1` | 1.006 × 1.010 × 1.908 | cm |
| `ArchVis…/Pallets/Pallet_A1` | 1.204 × 0.800 × 0.209 | cm |
| `ArchVis…/Shelves/RackLongEmpty_A1` | 1.081 × 4.000 × 3.010 | cm |

> Reminder from the brief, re-verified: `props/container_a01` is a **0.46 m
> plastic tote**, and `props/trafficcone_a01` is a **0.16 m mini cone**. There
> are no ISO shipping containers in this library. Do not plan around them.

### 6.1 Lane B — north sub-lane (walking line Y = +6.0)

| X | Y | Content | Height |
|---|---|---|---|
| -46 | +7.5 | 6 × `steeldrum_a01`, 2 tipped on their side | 0.87 |
| -40 | +4.5 | 2 × `ibctank_a01` on `ibcspillcontainmentpallet_a01` | 1.55 |
| -34 | +8.0 | 2 × `WarehousePile_A1`, yaws 12° and -31° | 2.03 |
| -27 | +4.0 | 2 × `bulkstoragerack_a03` back to back | 2.43 |
| -20 | +8.5 | 5 × `WoodenCrate_C1` + 3 × `WoodenCrate_A1`, jogged | 1.91 |
| -13 | +5.0 | 4 × `tireracksystem_a01` in a line = 7.5 m wall | 2.50 |
| -4 | +2.0 | 3 × `steeldrum_a01` + 1 tipped, low so the gate reads | 0.87 |
| +2 | +10.5 | 1 × `Pallets_A1` on 1 × `Pallets_A3`, shrink-wrapped | 2.40 |
| +12 | +6.5 | 3 × `Pallets_A1`, 2 × `Pallets_A3`, staggered | 1.46 |
| +19 | +3.5 | 3 × `WarehousePile_A4` + 1 × `WarehousePile_A2` | 1.51 |
| +26 | +8.0 | conveyor-bridge leg + 1 × `RackLongEmpty_A1` tipped over | 3.01 |
| +33 | +5.0 | 7 × `steeldrum_a01` + 12 soaked `Cardbox_*` | 0.87 |
| +42 | +7.0 | bollards + tyre pile + rubble | 1.20 |

The X = -4 and X = +2 entries are deliberately *offset from the gate axis* — they
frame the 7.4 m hero gate rather than block it. That is the only place in the map
where the clear run stretches to 14 m, and it is the money shot.

### 6.2 Centre cluster (X -6…+14, Y -8…+6)

| Item | Position | Height |
|---|---|---|
| Concrete jersey barriers ×3, broken ring | `(0,-4)`, `(+5,-6)`, `(+10,-3)` | 0.82 |
| Pallet-load tower A (`Pallets_A1` ×2 stacked + wrap) | `(+2, 0)` | 2.90 |
| Pallet-load tower B (`WarehousePile_A1` + `Pallets_A3`) | `(+8, -1)` | 2.85 |
| Collapsed rack bay bridging A↔B, `rotate_z = 12` | `(+5, -0.5)` | 2.60 |
| IBC battery 3 × 2 (`ibctank_a01`/`_b01` mixed) | `(+12, +3)` | 1.41 |
| 14 × `steeldrum_a01`, 4 on their side | scattered X -6…+13 | 0.87 |
| Puddle **P2** 12 × 6 | `(+2, -9)` | — |

### 6.3 Lane B — south sub-lane (walking line Y = -12.5)

| X | Y | Content | Height |
|---|---|---|---|
| -44 | -11 | IBC battery 3 × 2 on spill pallets | 1.55 |
| -37 | -14 | 4 × `Pallets_A1` staggered | 1.46 |
| -30 | -10.5 | 12 × `steeldrum_a01`, 4 tipped | 0.87 |
| -23 | -13.5 | 2 × `horizontalbarrack_a01` + loose steel offcuts | 1.27 |
| -16 | -11 | 3 × jersey barrier | 0.82 |
| -9 | -14.5 | trench-drain crossing, 2 rusted drums, a fallen `heavydutytrafficcone_a03` half in P4 — **SHOT 4 subject** | 0.91 |
| -2 | -12 | `WoodenCrate_C1` ×3 + soaked cardboard | 1.91 |
| +6 | -14 | tyre pile + concrete rubble | 1.10 |
| +14 | -11 | 3 × `bulkstoragerack_a01` | 1.84 |
| +22 | -13.5 | conveyor-bridge leg + wrapped pallet stack | 2.40 |
| +30 | -11 | 8 × `steeldrum_a01` + weeds through the broken slab | 0.87 |
| +38 | -13 | broken slab, rubble, 4 × `Pampas_Grass` (1.65 × 1.62 × 2.51, cm) | 2.51 |
| +46 | -10 | rusted skip + puddle P5 | 1.60 |

Inside the fuel bund (5.11): 3 IBC tanks at `(-61,-11)`, `(-57,-8)`, `(-52,-11)`
and 18 drums stacked two-high against the west wall.

### 6.4 Lane C — dock deck (top Z = +1.20)

76 m of continuous deck is a sniper alley if left bare. Break it every ~9 m:

| X on deck | Content (all sitting at Z = +1.20) | Height above deck |
|---|---|---|
| -42 | wrapped pallet stack | 2.40 |
| -33 | 2 × `industrialsteelshelving_a01` against the wall | 2.41 |
| -24 | dock leveller plate on end + 3 drums | 1.35 |
| -15 | crate wall, `WoodenCrate_C1` ×4 | 1.91 |
| -6 | pallet jack + 6 stacked `Pallet_A1` | 1.25 |
| +3 | `bulkstoragerack_a03` | 2.43 |
| +12 | 5 drums + cardboard | 0.87 |
| +21 | `tirerack_a01` ×2 | 2.31 |

Rear service road (Y = -37): parked dollies, skips and drum pairs at
X = -40, -26, -12, +2, +16, +30, +42.

### 6.5 Lane A — aisle islands

Each E–W aisle gets 5–7 islands. The main through-lane (A3, Y = 49.5) is the one
a critic will look at, so it is specified exactly:

| X | Content | Height |
|---|---|---|
| -30 | 1 × `Pallets_A3` + spilled sacks | 1.60 |
| -22 | collapsed rack bay + spilled cardboard (`WarehousePile_A3`) | 2.20 |
| -12 | 3 × `steeldrum_a01` + 1 × `ibctank_b01` | 1.40 |
| -2 | wrapped pallet stack (`Pallets_A1` ×2) + tipped drum | 2.40 |
| +8 | fallen rack beam + burst boxes | 1.10 |
| +18 | 1 × `RackLongEmpty_A1`, `rotate_z = 0`, dragged into the aisle | 3.01 |
| +28 | pallet jack + shrink-wrapped load | 2.00 |

Segment lengths along A3: 8.0 / 8.0 / 10.0 / 10.0 / 10.0 / 10.0 / 9.8 m. The
longest unbroken sightline in the interior is **10 m**.

Aisles A1, A2, A4, A5 and the north service aisle follow the same cadence with
different assets and different X offsets (shift the pattern by +3, -5, +7, -2 m
respectively so no two aisles read alike).

---

## 7. Camera shots

Convention (Z-up, from the brief and re-derived here):
`xformOp:rotateXYZ = (p, 0, h)` gives view direction `(-sin p · sin h,
sin p · cos h, -cos p)`.
* `p = 90` → horizon. `p < 90` → looking **down** by `(90 - p)°`. `p > 90` →
  looking **up**.
* `h = 0` → north (+Y). `h = 90` → west (-X). `h = 180` → south (-Y).
  `h = 270` → east (+X). Camera-right is `(cos h, sin h)`; camera-up is +Z.

All cameras: `horizontalAperture = 36.0`, `verticalAperture = 20.25` (16:9),
`clippingRange = (0.05, 4000)`. Preview 1920 × 1080, final 3840 × 2160.
All five focal lengths give a horizontal FOV inside 40–130°, so `validate.py`
will not warn.

| Shot | translate | rotateXYZ | focal | HFOV | Job |
|---|---|---|---|---|---|
| `HERO_ESTABLISH` | `(-54.0, -38.0, 11.0)` | `(84.3, 0, 314.0)` | 28 | 65.5° | hero establishing |
| `INTERIOR_AISLE` | `(-35.5, 49.4, 2.40)` | `(87.0, 0, 270.0)` | 24 | 73.7° | interior |
| `LANE_EYE_YARD` | `(-44.0, 2.0, 1.65)` | `(90.0, 0, 270.0)` | 28 | 65.5° | lane-level, eye height 1.65 |
| `DETAIL_WET_APRON` | `(-12.0, -10.5, 1.10)` | `(83.0, 0, 218.0)` | 45 | 43.6° | detail / texture |
| `SILHOUETTE_WEST` | `(48.0, -8.0, 1.65)` | `(96.0, 0, 90.0)` | 35 | 54.4° | silhouette / skyline |

### 7.1 `HERO_ESTABLISH`
Elevated three-quarter view from the south-west, looking north-east across the
whole yard at the warehouse's south wall. Aim point is the hero gate at
`(4, 18, 3)`, 80.6 m away, 5.7° below the camera.

Frame audit (bearings measured from the camera; higher bearing = further left):
frame spans bearing 11.1°…76.8°; the warehouse occupies 29.9°…82.1°, the hero
gate sits at 44.5° — **dead centre**. The roof at Z 18 lands well inside the top
of frame with ~12 m of storm sky above it. Ground enters the bottom of frame
23 m ahead, so the dock canopy and the west yard clutter carry the foreground.
Layering: dock canopy + yard clutter (fore) → warehouse south wall raked by the
WSW sun (mid) → gantry crane, water tower, silos, storm sky (back).

### 7.2 `INTERIOR_AISLE`
Standing 2.5 m inside the west wall in the main through-lane A3, looking due
east down 73 m of racking to the glowing east roller doors. Camera is at
Y = 49.4 rather than the aisle centreline 49.50 so the two rack walls are not
symmetric — that asymmetry is what sells the depth. 3° down-tilt puts the wet
floor slick in the lower third. The interior lamps (`SM_Lamp_A1`, Z 8.08…13.12)
are above the frame's top edge for the first 33 m and then converge into it —
they become a receding row of sodium points at the vanishing point. The seven
aisle islands (§6.5) keep it from reading as an empty corridor.

### 7.3 `LANE_EYE_YARD`
Soldier eye height, exactly 1.65 m, dead horizon, standing in the yard at the
west end of Lane B looking due east. This is the gameplay-truth shot.
The warehouse wall enters the upper left from 20 m out and rakes away; the dock
canopy enters the lower right from 37 m out; the pipe-trestle legs at X = -30
frame the near field at 14 m; the centre cluster sits 38–58 m out at frame
centre as the focal read; the conveyor bridge crosses the upper middle at 70 m
as a lintel; the gantry crane and storm sky close the background.
Sun is behind the camera, so shadows recede *into* frame — the wet specular has
to come from the practicals on the warehouse wall and the dock canopy (§8.2),
which is precisely the *Hackney Yard* look.

### 7.4 `DETAIL_WET_APRON`
Low, close, 1.10 m, tilted 7° down toward `(-6.6, -17.4, 0.02)`, 8.8 m away.
Subject: puddle **P4** (7.0 × 4.5 at `(-8.5, -17.5)`), the cast-iron trench
drain crossing the frame 5 m out at X ≈ -8.9, two rusted `steeldrum_a01` at
`(-5.2, -19.6)` and `(-4.3, -19.0)` bleeding rust into the water, and a fallen
`heavydutytrafficcone_a03` half submerged. The dock face (Y = -22) closes the
composition 14.6 m out with its bumpers and a rusted leveller plate. The sodium
practical at `(-6, -23, 5.4)` is above the frame — **only its reflection is in
shot**, which is the point. What is being judged here: aggregate in the asphalt,
rust bleed streaking, the meniscus at the puddle edge, moss in the drain, tyre
scuff over faded paint.

### 7.5 `SILHOUETTE_WEST`
Eye height, 6° up, looking **due west** down the length of the map into the
storm break. Frame spans bearing 152.8°…207.2°; the sun sits at bearing 200°,
5.5° elevation — about a quarter in from the left edge, and **under the conveyor
bridge**, which crosses the frame centre 22 m out with its deck at 12° and its
ridge at 22°. The warehouse south wall occupies the right of frame from X = +3.3
westward — 41 m of raking silhouette. Dock canopy silhouette on the left. The
west poplar at `(-73, +6)` clips the sun disc at 121 m. Layers, front to back:
conveyor bridge → yard clutter and P5 → warehouse wall + dock canopy → pipe
trestle → poplars + sun. This is the shot that has to look like a screenshot.

---

## 8. Notes to the modules I do not own

I have not edited any module file. These are requests, with coordinates.

### 8.1 Sun and sky (`60_lighting`)
* **DistantLight** `rotateXYZ = (84.5, 0, 290.0)`. That emits toward
  `(+0.936, +0.341, -0.096)`, i.e. the sun sits **WSW at 5.5° elevation**
  (bearing 200° from +X). Chosen so that: the warehouse south wall is raked at
  70° incidence (corrugation shadows pop), the west wall is near-frontally lit,
  shadows run east across the yard, and the disc lands where SHOT 5 needs it.
  `inputs:angle` ≈ 1.2° for a soft dusk edge; colour ~3200 K.
* **DomeLight** `Assets/Skies/Storm/approaching_storm_4k.hdr`.
  **No X rotation** (a latlong maps correctly on a Z-up stage without one).
  Spin about Z only, so the bright break in the cloud lands at bearing ~200°.

### 8.2 Practicals (`60_lighting`)
| Where | Position | Notes |
|---|---|---|
| Interior high bays | reuse `SM_Lamp_A1` at Z 8.08…13.12, X `-27.1…+27.1`, Y `17.7…73.4` | bind an emissive sodium MDL **and** add matching RectLights |
| Warehouse south wall packs | Z = 5.20, Y = 14.60, X = -34, -22, -10, +2, +14, +26 | these are what make the wet yard specular in SHOT 3 |
| Dock canopy fascia | Z = 5.20, Y = -21.50, X = -44, -30, -16, -2, +12, +26 | the one at X = -6 must be reflected in P4 for SHOT 4 |
| West fuel-bay mast flood | `(-60, -2, 8.0)`, aimed at the bund | |
| Gantry crane floods | `(+44, +26, 9.0)` and `(+64, +26, 9.0)` | |
| Dock office | one broken flickering unit over the stair at `(+47, -27, 4.2)` | |

Two of the twelve wall packs should be dead, and one should be a different,
colder colour temperature. Uniform practicals read as fake.

### 8.3 Materials (`50_materials`)
Minimum ground look count: **six** distinguishable ground materials (interior
slab, yard asphalt fresh, yard asphalt oxidised, crumbling aggregate, dock
concrete, gravel/ballast) plus mud and standing water. Every vertical surface in
the yard needs water streaking below its top edge; every steel surface needs
rust bleed running downhill from its fixings.

### 8.4 FX (`80_fx`)
Haze density must be highest where the shafts are: inside the warehouse
(X `-38…+38`, Y `15…76`, Z `0…14`) so the clerestory and the open gates throw
visible beams, and in the yard between Y `-16…+15` up to Z 8 so the low sun
rakes through the conveyor bridge and the pipe trestle. Add drifting mist off
the wet asphalt in the first 0.6 m. Post-rain drip lines off the canopy edge at
Y = -20 and the warehouse gutter at Y = 14.8.

### 8.5 Physics (`70_physics`)
* Warehouse01: static triangle-mesh collider (it is 1.76 M points — do **not**
  convex-decompose it).
* Racking: box colliders per bay, static.
* Procedural architecture: box colliders matching the visual boxes exactly.
* Dynamic: `steeldrum_a01` ~20 kg empty / 200 kg full (use 22 kg so they move),
  `WoodenCrate_A1` 35 kg, `Pallet_A1` 22 kg, traffic cones 3 kg, `ibctank_a01`
  60 kg empty / 1050 kg full. Everything else static.
* Ground plane collider at Z = 0 across the full plate.

---

## 9. Sightline audit

Requirement: cover breaks every 8–15 m. Measured worst cases:

| Line | Length | Longest clean segment | Broken by |
|---|---|---|---|
| Interior aisle A3 (main) | 75.7 m | **10.0 m** | 7 islands, §6.5 |
| Interior aisles A1/A2/A4/A5 | 75.7 m | 12 m | 5–7 islands each |
| Interior N–S | — | **16 m** | staggered rack gaps; no aligned column exists |
| Lane B north sub-lane | 104 m | **14 m** (hero-gate approach, intentional) | §6.1 |
| Lane B south sub-lane | 104 m | **8 m** | §6.3 |
| Lane B open diagonal `(-52,-14)`→`(+52,+14)` | 107 m | **17 m** | centre cluster, pipe trestle, bridge legs, rusted skip at `(+36,+2)` |
| Lane C dock deck | 76 m | **9 m** | §6.4 |
| Lane C service road | 96 m | **14 m** | parked dollies/skips |
| Spawn-to-spawn straight `(-64,4)`→`(+64,4)` | 128 m | **14 m** | warehouse wall, centre cluster, bridge |

The single 17 m segment on the yard diagonal is the map's longest exposure. That
is intentional and it is the map's one "power lane" — it is covered from the
mezzanine, the dock roof and the centre cluster, so holding it costs you.

---

## 10. Objectives and spawns (for anyone dressing gameplay space)

| Point | Position | Character |
|---|---|---|
| WEST SPAWN | `(-64, +4)`, 12 × 16 m | fuel bay; exits N to the west doors, E to the yard, S to the west ramp |
| EAST SPAWN | `(+64, +4)`, 12 × 16 m | rail spur; exits N along the ballast to the east doors, W to the yard, SW to the dock office stair |
| **A** | `(-28, +22)` | west warehouse floor, inside the roller doors |
| **B** | `(+4, -2)` | the centre cluster — the map's heart |
| **C** | `(+16, -28)` | east dock deck, under the canopy |
| **D** | `(0, +49.5)` | interior main aisle |
| **E** | `(+45, +18)` | east loading platform |

Hardpoint rotation A → B → C → D → E pulls the fight through all three lanes and
both elevations.

---

## 11. Verticality summary

| Level | Z | Access |
|---|---|---|
| Yard / interior grade | 0.00 | — |
| East loading platform | +1.10 | ramp at Y +2…+6 |
| Dock deck | +1.20 | ramps X5/X7, stair X6 |
| Interior mezzanine | +4.20 | stair at X = +23.4, Y +31…+35 |
| Pipe trestle deck | +5.20 | **no access** — visual only |
| Dock canopy roof | +5.75 | **no access** |
| Conveyor bridge deck | +5.90 | **no access** — visual only |
| Dock office roof | +7.50 | external stair X9 |
| Warehouse truss | +14.33 | — |
| Warehouse ridge | +17.99 | — |
| Water tower top | +26.00 | OOB backdrop |

Three player-accessible elevations (+1.2, +4.2, +7.5) is the right number for a
map this size. More would fragment the fight.

---

## 12. Honest gaps

Things a downstream agent should know are unresolved, so nobody is surprised:

1. **The library has one building.** Everything in §5 marked *procedural* has to
   be built from box/cylinder geometry by the architecture agent. There are no
   trucks, forklifts, shipping containers, dumpsters, silos, cranes, fences or
   pipes in this library — I checked all 4 975 USD files in
   `_catalog/library.json`. The depot reads through racking, pallets, drums,
   crates, IBC tanks, tyre racks and cardboard, exactly as the brief warns.
2. **The empty yard is the risk.** A 104 × 31 m yard filled only with 0.9–2.5 m
   props will read as flat unless the procedural structures in §5.3–5.8 actually
   get built. The conveyor bridge and the pipe trestle are load-bearing for the
   composition of three of the five shots.
3. **No render has been run from this plan.** I authored no USD and captured no
   image. Every frame audit in §7 is analytic (bearings, FOV half-angles and
   distances computed from the placements above), not observed. The first agent
   to render `LANE_EYE_YARD` should expect to nudge the camera 1–3 m.
4. **`validate.py` currently fails**, with `no RenderProduct prims found` and
   `no lights in the stage`. That is the pre-existing state of the empty stage —
   those prims belong to `90_cameras.usda` and `60_lighting.usda`, which I do not
   own and did not touch. This document adds no USD and therefore cannot fix it.
5. **The warehouse floor extends north to Y = 88.25** (under the office annex)
   while the main hall wall is at Y = 76.25. The terrain agent should not lay
   yard material over that strip; leave it to the building.
6. **Interior lamp meshes are geometry, not lights.** `SM_Lamp_A1` will render
   black unless the lighting agent binds an emissive material and/or adds real
   lights at those positions.
