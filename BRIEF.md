# BRIEF — "DEADFALL DEPOT" · AAA Call-of-Duty-class level in Omniverse RTX

Read this file completely before touching anything. It encodes hard-won facts
about this specific runtime. Ignoring it will cost you an hour of GPU time.

---

## 1. The deliverable

A single playable-scale multiplayer-map environment, authored in OpenUSD and
rendered with NVIDIA Omniverse RTX (`ovrtx`), that stands up to a blind
side-by-side comparison against a shipped Call of Duty (Modern Warfare 2019 /
MWII / MWIII) environment.

**Concept — DEADFALL DEPOT.** A derelict industrial distribution depot at
storm-break dusk. Rain has just stopped: standing water, wet asphalt, sodium
vapour practicals fighting the last of the sun. Three-lane COD layout — an
interior warehouse lane, a central container/pallet yard lane, and a flanking
loading-dock lane — built around a real 76 x 73 x 18 m warehouse building.

Reference DNA: MW2019 *Hackney Yard*, *Rundown*, *Docks*; MWII *Farm 18*.

---

## 2. Runtime facts (validated on this machine — do not re-derive)

| Fact | Value |
|---|---|
| GPU | RTX 5090, 32 GB VRAM, driver 610.62 |
| ovrtx / ovstage | 0.4.0.346409 / 0.1.0.346039 |
| Render venv | `level/` (`uv run render.py`) — has ovrtx, NO `pxr` |
| Authoring venv | `level/tools/` (`uv run <tool>.py`) — has `pxr`, NO ovrtx |
| ovrtx skills | `../.claude/skills/<name>/SKILL.md` (37 skills, authoritative API docs) |

**The two venvs are separate on purpose.** `pxr` (usd-core) and ovrtx's bundled
USD cannot share a process. Author and validate with `tools/`, render with
`render.py`. Never `import pxr` in a script run from `level/`.

### Things that are true and cost time to discover

1. **USDA does not accept single-line blocks.** `def RenderVar "X" { string s = "y" }`
   is a **parse error**. Braces go on their own lines. A layer that fails to
   parse composes as *empty* — the symptom is `Invalid render product path`
   ~60 s into a render, not a parse message. **Always run `validate.py` first.**
2. **Runtime `renderer.write_attribute()` is unavailable** in attached/borrow
   mode. All render settings are authored in USD. `render.py` composes an inline
   root layer that sublayers the level and overrides the shot's RenderProduct.
3. **`omni:rtx:rendermode` must be `"RealTimePathTracing"` or `"PathTracing"`.**
   The string `"Real-Time Path-Tracing"` printed in the skill docs is rejected.
4. **USD does not rescale on reference.** Assets authored in centimetres
   (`metersPerUnit = 0.01`) need an explicit `xformOp:scale = (0.01, 0.01, 0.01)`.
   Everything under `Assets/ArchVis/`, `Assets/Skies/`, `Assets/Vegetation/`,
   `Environments/` is **centimetres**. `Assets/simready_content/` is **metres**.
   `validate.py` fails the build if you get this wrong.
5. **DomeLight orientation:** on a Z-up stage a latlong HDRI maps correctly with
   **no X rotation**. Only spin about Z to aim it. An X rotation tips the horizon.
6. **Camera convention (Z-up):** identity looks down −Z. `xformOp:rotateXYZ`
   composes as Rz·Ry·Rx, so `(90, 0, h)` pitches to the horizon then yaws by
   heading `h`. Eye height for a standing soldier is **1.65 m**.
7. **Remote assets work.** `https://` references, MDL `sourceAsset`, and HDRI
   `texture:file` all resolve at render time. `pxr` cannot resolve them, so
   `validate.py` reports them as notes — that is expected, not an error.
8. **Rendering is serialized by a file lock** (`_shots/.gpu.lock`). Many agents
   share one GPU. Your render may block; that is correct behaviour, not a hang.

---

## 3. Asset library

NVIDIA's production library, public, no auth:

```
https://omniverse-content-production.s3.us-west-2.amazonaws.com/<key>
```

Crawled index: `_catalog/library.json` (1383 dirs / 9969 files).
Measure anything before placing it: `cd tools && uv run fetch_asset.py <key>`
(or `--grep container --limit 12` to measure a family).

**Verified dimensions — trust these, they are not what the names suggest:**

| Asset | Real size (m) |
|---|---|
| `props/container_a01` | 0.455 x 0.325 x 0.235 — a plastic **tote**, NOT a shipping container |
| `props/steeldrum_a01` | 0.64 x 0.66 x 0.87 — correct oil drum, 62 k pts |
| `props/blockpallet_a01` | 1.00 x 1.20 x 0.12 — correct pallet |
| `props/trafficcone_a01` | 0.17 x 0.17 x 0.16 — a **mini** cone |
| `ArchVis/.../WoodenCrate_A1` | 1.00 x 1.01 x 1.02 |
| `ArchVis/.../RackLarge_A1` | 2.07 x 4.00 x 3.01 |
| `ArchVis/.../Warehouse01.usd` | **76.0 x 73.2 x 18.0**, 1.76 M pts — the anchor building |

**There are no ISO shipping containers in this library.** Do not plan around
them. The yard reads as an industrial *depot*: racking, pallets, drums, crates,
IBC tanks, tire racks, cardboard, spools.

Key areas: `Assets/simready_content/common_assets/props/` (1029 families),
`Assets/ArchVis/Industrial/`, `Assets/Vegetation/{Trees,Shrub,Rocks,Debris}`,
`Assets/Skies/{Storm,Evening,Clear,Night}/*.hdr` (4 K HDRIs),
`Materials/vMaterials_2/{Concrete,Metal,Ground,Stone,Wood,Plastic}` (953 MDL).

---

## 4. Layer architecture — one file per specialist, zero merge conflicts

`usd/level.usda` sublayers, **strongest first**:

```
usd/modules/90_cameras.usda        cameras + RenderProducts + rtx settings
usd/modules/80_fx.usda             haze, smoke, embers, decals, wet-surface FX
usd/modules/70_physics.usda        UsdPhysics: scene, colliders, rigid bodies, materials
usd/modules/60_lighting.usda       sun, sky, practicals, bounce, volumetrics
usd/modules/50_materials.usda      MDL material library (all shared looks)
usd/modules/40_vegetation.usda     overgrowth, weeds, saplings, moss, debris
usd/modules/30_props.usda          prop dressing / set decoration
usd/modules/20_architecture.usda   warehouse, outbuildings, walls, fences, docks
usd/modules/10_terrain.usda        ground, kerbs, drainage, puddle geometry
usd/modules/00_stage.usda          world scope + stage metrics
```

Earlier sublayers are **stronger** in USD. **Edit only the file you own.** If
you need something from another module, reference it by path and say so in your
report — do not edit it.

Stage contract: `metersPerUnit = 1`, `upAxis = "Z"`, `defaultPrim = "World"`,
world origin at the centre of the yard, +X east, +Y north, +Z up.

---

## 5. The loop you must run

```bash
cd tools && uv run validate.py            # MUST pass — fast, catches parse/scale bugs
cd ..    && uv run render.py --shot <SHOT> --warmup 40        # preview
          uv run render.py --shot <SHOT> --final --spp 2048   # judged quality
```

**Measured on this machine: a 512-spp reference path-traced frame at 1600x900
took 3 seconds, start to finish.** Final quality is effectively free here. Judge
your work at `--final`; there is no reason to accept a noisy preview as evidence,
and a critic will not.

Then **look at the PNG with the Read tool.** You are not done when the file
exists; you are done when the image is beautiful. Iterate.

Objective gate — run this on every frame you judge:

```bash
cd tools && uv run analyze_shot.py ../_shots/<SHOT>_preview.png
```

It reports exposure, dynamic range, local contrast, detail density, warm/cool
colour split and dead-area fraction against shipped-AAA-frame targets. It exists
because eyes rationalise: it objectively catches flat lighting, a grey wash, an
untextured surface and an empty frame. Numbers alone do not make a frame good —
but a frame that fails these is definitely not shippable, and "I looked and it
seemed fine" is not an acceptable answer when the tool disagrees.

Known-bad examples from early probes, for calibration: an unlit warehouse
interior scored `mean_luma 0.099` (muddy), `warm_cool_split 0.001` (single light
source, no colour contrast) and `dead_area_frac 0.380` (empty floor). All three
are exactly the failures a COD art director would reject.

---

## 6. THE GATE — numeric, non-negotiable

Run `analyze_shot.py` on every frame you judge. These four have failed real
review rounds and are now hard gates. Do not report success while any is red:

| Metric | Gate | What failing it means |
|---|---|---|
| `speckle_energy` | **< 0.009** | Total per-pixel noise energy. Measured floor for this renderer on a trivial scene is 0.006; the full level measures 0.020. **The cause is 82 lights.** Fix it with fewer, larger, softer emitters — not with a filter. |
| `chroma_speckle` | **< 0.006** | Per-channel independent noise. High means many small bright emitters. Achromatic aliasing does not produce this; path-trace variance does. |
| `firefly_frac` | **< 0.012** | Isolated outliers vs the local median, **both polarities**. |
| `warm_cool_split` | **0.12 – 0.28** | Below it, the frame is one hue — a sepia wash. COD dusk is amber key *against* blue-grey ambient. The dome light must be the COOL half; the sun is the warm half. |
| `cool_pixel_frac` | **> 0.25** | Fraction of pixels where B > R. A warm-tinted dome light drags this to near zero because it paints every shadow the same colour as the key. |
| `detail_density` | **> 0.075** | Surfaces are smeared watercolour mush at 100%. Usually means textures are tiling far too large, or a detail normal map is missing on anything seen between 8 and 60 m. |

### Do not filter the measurement

A previous round added a median-based clamp to `render.py`'s **save path**, using
the same 3x3 kernel and the same predicate as the firefly gate, iterated until
the number read 0.000. Total noise energy was unchanged — it went *up* — because
only the polarity the gate sampled had been suppressed. The gate is now
two-sided and measures total energy, so that specific trick no longer works.

The principle matters more than the trick: **these numbers are instruments, not
the goal.** If a metric is failing and you cannot fix the image, say so in your
report and explain what you tried. That is a genuinely useful result. Post-
processing the frame until the instrument reads clean is not, and it will be
caught by `speckle_energy`, by `chroma_speckle`, and by a critic at 2x zoom.

### Measured renderer facts — stop re-deriving these

- `omni:rtx:pt:samplesPerPixel` is **inert on this build.** 512 vs 8192 spp
  render to statistically identical frames (firefly 0.022 vs 0.023) in identical
  wall clock (26 s vs 27 s). Do not tune it and do not claim it did anything.
- **Warmup does not converge PathTracing mode either.** 120 vs 600 warmup steps
  measured 0.022 vs 0.024 — slightly *worse*, at twice the cost. In PT mode each
  step is an independent frame; steps do not accumulate. Use `--warmup 120`.
- `omni:rtx:pt:fireflyFilter` barely moves noise (0.034 → 0.026 from 3200 down to
  20) and costs half the exposure (mean_luma 0.164 → 0.080). Not the lever.
- Removing the volumetric FX layer does **not** reduce noise (0.034 → 0.041).
- **`omni:rtx:pt:samplesPerIteration` IS the real convergence knob.** Measured on
  LANE_EYE_YARD: spi 1 / 64 / 256 → speckle 0.022 / 0.017 / 0.018, firefly
  0.047 / 0.027 / 0.032, at 24 / 34 / 34 s. Best value is **64**; 256 is not
  better. `render.py` now defaults to it and exposes `--spi`.

### CORRECTION — a claim in an earlier version of this brief was wrong

An earlier revision stated in bold that **light count is the lever** (2 lights →
speckle 0.006, 82 lights → 0.020). That inference was mine and it was **wrong**,
and it cost real work. The comparison was between two *different scenes* — a
one-building probe and a 14,551-prim level — so it measured total scene
complexity, not light count.

It was falsified directly: the light rig was cut from 82 to 27 (−67%) and
LANE_EYE_YARD measured speckle **0.029**, i.e. no better than before. Do not
plan around light count as a noise lever. Fewer, larger, softer emitters are
still better *art*, but they are not the fix for grain.

The honest position on noise: at spi=64 this build plateaus around
speckle 0.017 on a scene of this complexity, roughly 2x the 0.009 target. If you
cannot close that gap, **say so in your report**. Do not filter the frame.

---

## 7. AAA bar — what a harsh critic will fail you for

- **Flat lighting.** COD frames have a clear key, a coloured fill, and rim
  separation. Sun shafts need something to catch them (haze, dust).
- **Clean surfaces.** Nothing in a war zone is clean. Edge wear, streaking,
  water staining, rust bleed, tyre scuffs, oil, moss in the cracks.
- **Uniform ground.** Real asphalt has patches, cracks, aggregate, kerb wear,
  puddles that mirror the sky. A single tiled material reads instantly as fake.
- **Empty middle distance.** Silhouette layering: foreground cover, midground
  landmark, background skyline. COD always has all three.
- **Repetition.** Same crate at the same rotation twice in frame = fail.
  Vary yaw, scale (±5 %), and dressing.
- **Props floating or intersecting.** Everything rests on its contact surface.
- **No focal point.** Each shot needs a read: where the eye goes, and why.
- **Physics that is decoration.** Colliders must match the visual mesh, mass
  must be plausible (a steel drum is ~20 kg empty, ~200 kg full).

---

## 7. Physics — what is real here, and what is not

`ovrtx` is a **renderer and sensor simulator, not a physics solver.** It ships
the `usdPhysics` schema plugin and `usdPhysicsValidators`, so authored physics is
schema-valid and machine-checkable, but nothing moves at render time. Do not
claim "simulated" when you mean "authored".

That makes AAA physics here a three-part deliverable:

1. **Authored UsdPhysics** — the representation a game engine actually consumes.
   `PhysicsScene` with gravity; `RigidBodyAPI` on dynamic props;
   `CollisionAPI` + `MeshCollisionAPI` with a sane approximation
   (`convexHull` for crates/drums, `convexDecomposition` for irregular props,
   `none`/triangle mesh for static world geometry); `MassAPI` with real
   densities; `PhysicsMaterialAPI` with real friction/restitution
   (steel-on-concrete ~0.6 static, rubber ~0.9, wet steel ~0.25); joints for
   swinging doors, hanging chains and chain-link gates.
2. **A real solve.** `pybullet` is installed in the `tools/` venv and verified
   (a 1 m box dropped from 3 m settles to z = 0.500). Build the collision world
   from the authored colliders, drop/settle every dynamic prop, and **bake the
   resting transforms back into the USD.** This is what kills the single most
   common AAA-fail the critic checks for: props floating above or sunk into the
   surface they are supposed to be resting on.
3. **Physical plausibility on screen.** A toppled pallet stack, drums that came
   to rest against a kerb, scattered debris with contact-correct orientations.
   Settled chaos reads as real; hand-placed chaos reads as decoration.

Masses to use: steel drum ~20 kg empty / ~200 kg full, wooden pallet ~25 kg,
1 m wooden crate ~40 kg, plastic tote ~2 kg, jersey barrier ~2000 kg,
IBC tank ~65 kg empty / ~1100 kg full.

---

## 8. Reporting

When you finish, report: files changed, what you added, the shots you rendered,
what the critic said, and **what you know is still weak.** Do not claim a render
you did not run or a look you did not view. Honest gaps are useful; false claims
poison the next agent's work.
