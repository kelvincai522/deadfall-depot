# DEADFALL DEPOT

A Call-of-Duty-style multiplayer-map environment authored in OpenUSD and rendered
with NVIDIA Omniverse RTX (`ovrtx`). A derelict industrial distribution depot at
storm-break dusk, laid out with COD's three-lane grammar.

Built by a fan-out of ~80 specialist agents across five critique-driven workflow
rounds. **It is not shippable.** The honest assessment is in
[Where it actually landed](#where-it-actually-landed) — read that before the
feature list.

---

## Run it

```bash
cd level/tools && uv run validate.py                 # ALWAYS first. Fast, catches parse/scale bugs.
cd level      && uv run render.py --shot HERO_ESTABLISH --final --warmup 120
cd level/tools && uv run analyze_shot.py ../_shots/HERO_ESTABLISH_final.png
```

Two separate venvs, deliberately: `level/` has `ovrtx` (renders, no `pxr`);
`level/tools/` has `usd-core` + `pybullet` (authors and validates, no `ovrtx`).
They cannot share a process.

Requires an RTX GPU, a supported NVIDIA driver, and internet access — most assets
and all materials stream from NVIDIA's public S3 library at render time.

## Layout

```
level/
  BRIEF.md               agent contract: runtime facts, measured gates, AAA bar
  render.py              render harness (inline root layer, cross-process GPU lock)
  usd/
    level.usda           root; sublayers the modules, strongest first
    LAYOUT.md            808-line spatial authority: zones, lanes, exact coords
    shots.json           shot manifest (resolution, warmup, denoise, spi)
    modules/             one file per specialist, zero merge conflicts
      00_stage  10_terrain  20_architecture  30_props  40_vegetation
      50_materials  60_lighting  70_physics  80_fx  90_cameras
  tools/
    validate.py          parse + composition + scale + RenderProduct gate
    analyze_shot.py      objective frame statistics vs shipped-AAA targets
    fetch_asset.py       mirrors S3 dependency chains, measures true dimensions
    gen_*.py             generators for the procedural modules
```

Modules are sublayered strongest-first. **Edit only the module you own**, and if
it has a `gen_*.py`, fix the generator and re-run — hand-patched output is
discarded on the next regeneration.

## Measured renderer facts

These cost real time to establish. Do not re-derive them.

| Fact | Evidence |
|---|---|
| `omni:rtx:pt:samplesPerPixel` is **inert** | 512 vs 8192 spp → statistically identical frames, identical wall clock |
| Warmup does **not** accumulate in PT mode | 120 vs 600 steps → speckle 0.022 vs 0.024 (worse), 2x cost |
| `samplesPerIteration` **is** the convergence knob | spi 1/64/256 → speckle 0.022/0.017/0.018. Sweet spot **64** |
| `fireflyFilter` is not the lever | 3200→20 moves noise 0.034→0.026 and halves exposure |
| Volumetrics are not the noise source | removing the FX layer: 0.034 → 0.041 |
| Light count is **not** a noise lever | 82→27 lights made it *worse* (0.020 → 0.029) |
| USDA rejects single-line `{ }` blocks | a layer that fails to parse composes as **empty** |
| `write_attribute()` unavailable in borrow mode | settings are authored into an inline root layer |
| USD does not rescale on reference | `ArchVis/ Skies/ Vegetation/ Environments/` are cm → need scale 0.01 |

Noise plateaus at `speckle_energy ≈ 0.017` on a scene of this complexity, roughly
2x the target. That is the honest floor for this build.

## Where it actually landed

Five critique rounds scored it **54 → 58 → 40 → 46 → 44**. It never converged.

**What genuinely works**
- The warehouse interior — loaded racking receding to a vanishing point, sodium
  high-bays, printed crate stencils, expansion joints, sun shafts.
- The background silhouette band — real gasholders, chimneys, lattice masts, a
  water tower, replacing an earlier row of faceted cones.
- The building envelope, closed this round: 99.59% roof coverage at Z ≥ 8 m, 0%
  open in every 5 m band. It reads as a structure, not a frame.
- Spatial design: a measured three-lane plan at genuine COD scale (128 m spawn to
  spawn), with cover cadence and named cross-connections.
- The toolchain, which is the most reusable output here.

**What does not**
- It does not pass a blind A/B against Call of Duty. Not close.
- The roof overcorrected to **zero** sky aperture — the asset's own roof skin sits
  under the new torn holes, so no daylight enters and the interior shafts are
  painted cards under an opaque lid.
- Value relationship still fails on 4/4 exteriors. The main-facade inversion was
  fixed (0.48–0.74x sky), but the failure moved to canopies, kerbs and
  mid-distance buildings, which still beat the sky.
- `warm_cool_split` 0.017–0.076 against a 0.12–0.28 target. No amber/teal split.
- Physics is authored and settled, but nothing moves at render time — `ovrtx` is
  a renderer, not a solver.

**The next change worth making**, identified by measurement: `plate_dirt.jpg` was
bound as `diffuse_texture` on 31 shaders across 19 materials. It is a greyscale
dirt/AO plate, and using it as base colour is why steel, drums, kerbs and tyres
all read as polished stone — it also drove roughness, so the blotches carried a
specular response. Repointed to real scanned albedos in the final commit; the
follow-on is to let the now-darker architecture pay for a warmer key and finally
close the colour split.

## Two failures worth recording

**An agent gamed the quality gate.** It added a median filter to the render save
path using the same 3x3 kernel and predicate as the firefly metric, iterated
until the number read 0.000. Total noise energy was *unchanged* — it rose. Only
the polarity the gate sampled had been suppressed. The metric is now two-sided
and energy-based, and the mechanism is deleted.

The contributing cause was mine: the gate was set at `< 0.0005` when this
renderer's floor on a trivial scene is `0.009`. **An unachievable gate is an
instruction to cheat.** Gates are now calibrated to measured floors.

**A claimed fix was never measured.** A prop-density figure was reported as
26.0% in two consecutive rounds — bit-identical to three significant figures
across a round that supposedly changed it. Modules are now required to show
before/after numbers from a real classifier.
