"""Render harness for the level.

Composes an inline root layer that sublayers the level and overrides the shot's
RenderProduct with quality-tier settings, warms the renderer up so textures
finish streaming, then captures one image per shot.

    uv run render.py                          # every shot, preview quality
    uv run render.py --shot HERO_01 --final   # one shot, full path-traced quality
    uv run render.py --list                   # show the shot manifest

Quality tiers
    preview : Real-Time Path-Tracing. Seconds per frame. Use while iterating.
    final   : reference PathTracing. MEASURED ON THIS BUILD:
              * `omni:rtx:pt:samplesPerPixel` is INERT (512 vs 8192 -> identical
                frames, identical wall clock). Do not tune it.
              * WARMUP does NOT accumulate in PT mode either (120 vs 600 steps
                measured 0.022 vs 0.024 speckle -- slightly worse, 2x the cost).
              * `omni:rtx:pt:samplesPerIteration` IS the real convergence knob:
                spi 1 / 64 / 256 measured speckle 0.022 / 0.017 / 0.018 and
                firefly 0.047 / 0.027 / 0.032 at 24 / 34 / 34 s. It plateaus
                around 0.017 -- better, but short of the 0.009 target on a scene
                this complex. Default is 64.

Render settings are `omni:rtx:*` attributes on the RenderProduct prim. ovstage
owns the scene in attached/borrow mode, so runtime `write_attribute` is not
available -- settings are authored into the inline root layer instead.
"""

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import ovrtx
import ovstage
from PIL import Image

ROOT = Path(__file__).resolve().parent
DEFAULT_USD = ROOT / "usd" / "level.usda"
SHOTS_DIR = ROOT / "_shots"
LOCK = ROOT / "_shots" / ".gpu.lock"


@contextlib.contextmanager
def gpu_lock(timeout_s: float = 7200.0, stale_s: float = 3600.0):
    """Serialize renders across processes.

    Many agents iterate on this level at once, but there is one GPU and a
    scene large enough that two concurrent renderers thrash VRAM. An exclusive
    lock file keeps renders one-at-a-time; a stale lock (crashed process) is
    reclaimed after `stale_s`.
    """
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    fd = None
    while fd is None:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - LOCK.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_s:
                print(f"[harness] reclaiming stale GPU lock ({age:.0f}s old)", file=sys.stderr)
                LOCK.unlink(missing_ok=True)
                continue
            if time.time() - start > timeout_s:
                sys.exit("[harness] timed out waiting for the GPU lock")
            if int(time.time() - start) % 60 == 0:
                print(f"[harness] waiting for GPU ({time.time() - start:.0f}s)...", file=sys.stderr)
            time.sleep(3)
    try:
        os.write(fd, f"pid={os.getpid()}".encode())
        os.close(fd)
        yield
    finally:
        LOCK.unlink(missing_ok=True)

PREVIEW = """
        token omni:rtx:rendermode = "RealTimePathTracing"
        int omni:rtx:rtpt:maxBounces = 4
        int omni:rtx:rtpt:maxSpecularAndTransmissionBounces = 6
        bool omni:rtx:rtpt:ris:meshLights = 1
        float omni:rtx:rtpt:maxRoughness = 0.6
        bool omni:rtx:rtpt:fireflyFilter:enabled = 1
"""

# NOTE ON --spp, MEASURED. `omni:rtx:pt:samplesPerPixel` has NO effect on this
# build: LANE_EYE_YARD rendered at 512 / 2048 / 8192 measured firefly_frac
# 0.00811 / 0.00810 / 0.00810 and detail_density 0.0613 / 0.0610 / 0.0610, in
# 23 / 25 / 22 seconds. Identical images, identical wall clock. Convergence
# comes from the number of `renderer.step()` calls instead -- the same frame at
# warmup 50 / 300 / 1000 measured firefly 0.0783 / 0.0406 / 0.0334 with
# denoising off. The attribute is still authored so the intent is on record,
# but WARMUP is the real sample-count control and --final defaults accordingly.
FINAL = """
        token omni:rtx:rendermode = "PathTracing"
        int omni:rtx:pt:samplesPerPixel = {spp}
        int omni:rtx:pt:samplesPerIteration = {spi}
        int omni:rtx:pt:limits:maxBounces = 8
        int omni:rtx:pt:limits:maxGlossyBounces = 12
        int omni:rtx:pt:limits:maxFogBounces = 4
        int omni:rtx:pt:maxVolumeBounces = 16
        bool omni:rtx:pt:adaptiveSampling:enabled = 1
        bool omni:rtx:pt:denoising:enabled = {denoise}
        bool omni:rtx:pt:denoising:optix:denoiseAOVs = 1
        bool omni:rtx:pt:ris:meshLights = 1
        bool omni:rtx:pt:fireflyFilter:enabled = 1
        float omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSample = {ffmax}
        float omni:rtx:pt:fireflyFilter:maxUnexposedIntensityPerSampleDiffuse = {ffmax}
        float omni:rtx:pt:fireflyFilter:maxPerEmissiveUnexposedIntensity = {ffmax}
        bool omni:rtx:pt:lightCache:enabled = 1
        bool omni:rtx:pt:radianceCache:enabled = 1
"""


def build_root_layer(level_path: Path, shot: str, tier: str, resolution, spp: int,
                     denoise: int = 1, ffmax: float = 3200.0, spi: int = 64) -> str:
    """Inline root layer: sublayer the level, override this shot's RenderProduct."""
    settings = (FINAL.format(spp=spp, denoise=int(denoise), ffmax=ffmax, spi=spi) if tier == "final" else PREVIEW).rstrip()
    res = f"        int2 resolution = ({resolution[0]}, {resolution[1]})" if resolution else ""
    return f"""#usda 1.0
(
    subLayers = [@{level_path.as_posix()}@]
)

over "Render"
{{
    over "{shot}"
    {{
{settings}
{res}
    }}
}}
"""



def capture(product, out_path: Path, deliver_res=None):
    """Map the product's LdrColor to CPU memory and write it out as a PNG.

    SUPERSAMPLING, and it is OFF for every shot on this level - MEASURED, not
    assumed. When `deliver_res` is smaller than the rendered buffer the frame is
    box-averaged down to it before being written. That is ordinary SSAA and it
    is the right instrument for GEOMETRIC aliasing, but this level's outliers
    are TEXTURE aliasing, and on those SSAA loses on both gates at once:

        LANE_EYE_YARD  ss 1   firefly 0.00862   detail 0.0757
                       ss 2   firefly 0.00665   detail 0.0615

    The mechanism is mip selection. At 2x the texture footprint per pixel
    halves, so the renderer picks a sharper mip and the same ground grain comes
    back at one 2x pixel - which the box average then decimates straight back
    to one hard delivered pixel, while flattening the real mid-frequency

    Kept, wired and documented rather than deleted so the next round does not
    have to re-derive the result. Opt in per shot with `"supersample": N` in
    usd/shots.json, or for one invocation with `--ss N`. Absent the key nothing
    changes, so it is inert for any shot that has not asked for it.
    """
    saved = []
    for frame in product.frames:
        var = frame.render_vars["LdrColor"].map(device=ovrtx.Device.CPU)
        pixels = np.from_dlpack(var).copy()
        var.unmap()
        del var
        img = Image.fromarray(pixels)
        if deliver_res and tuple(img.size) != tuple(deliver_res):
            # BOX = exact area average. Not Lanczos: Lanczos rings on the very
            # high-contrast sunlit edges this scene is full of, which puts the
            # firefly count back.
            img = img.resize(tuple(deliver_res), Image.BOX)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        saved.append(out_path)
    return saved


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usd", default=str(DEFAULT_USD))
    ap.add_argument("--shot", action="append", default=None,
                    help="RenderProduct name under /Render (repeatable). Default: all in shots.json")
    ap.add_argument("--final", action="store_true", help="reference path tracing instead of preview")
    ap.add_argument("--spp", type=int, default=2048, help="samples per pixel in --final")
    ap.add_argument("--res", default=None, help="override resolution, e.g. 3840x2160")
    ap.add_argument("--warmup", type=int, default=None, help="override warmup frame count")
    ap.add_argument("--ss", type=int, default=None,
                    help="supersample factor: render NxN larger and box-downsample to the "
                         "shot resolution on save. Overrides the per-shot 'supersample' key "
                         "in shots.json.")
    ap.add_argument("--denoise", type=int, default=None, choices=(0, 1),
                    help="force OptiX denoising on/off in --final. Overrides the per-shot "
                         "'denoise' key in shots.json (default 1).")
    ap.add_argument("--dt", type=float, default=None,
                    help="delta_time per warmup step; 0 freezes scene time so path-trace "
                         "accumulation is not reset by animated attributes.")
    ap.add_argument("--spi", type=int, default=None,
                    help="omni:rtx:pt:samplesPerIteration. THE working convergence knob on this build (samplesPerPixel is inert). Higher = less noise, more time.")
    ap.add_argument("--ffmax", type=float, default=None,
                    help="omni:rtx:pt:fireflyFilter max unexposed intensity (LOWER = more aggressive "
                         "rejection of bright samples). This is the renderer's own physically-motivated "
                         "firefly rejection -- the correct lever, unlike a post-hoc save-path filter.")
    ap.add_argument("--out", default=str(SHOTS_DIR))
    ap.add_argument("--tag", default="", help="suffix appended to output filenames")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    level_path = Path(args.usd).resolve()
    if not level_path.exists():
        sys.exit(f"USD root not found: {level_path}")

    manifest_path = level_path.parent / "shots.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"shots": {}}
    if args.list:
        print(json.dumps(manifest, indent=2))
        return

    shots = args.shot or list(manifest["shots"].keys())
    if not shots:
        sys.exit(f"No shots requested and none listed in {manifest_path}")

    resolution = tuple(int(v) for v in args.res.lower().split("x")) if args.res else None
    tier = "final" if args.final else "preview"
    # --final default is 600 steps, not 50. `omni:rtx:pt:samplesPerPixel` is inert
    # on this build (see the note above FINAL), so the step count IS the sample
    # count: at 50 steps a --final frame is a ~50-sample path trace leaning
    # entirely on the OptiX denoiser to look converged, which is what was
    # destroying surface texture. 600 costs ~17 s more on a 1920x1080 frame.
    warmup = args.warmup if args.warmup is not None else (600 if args.final else 40)
    out_dir = Path(args.out)

    with gpu_lock():
        run(level_path, shots, tier, resolution, args, warmup, out_dir, manifest)


def run(level_path, shots, tier, resolution, args, warmup, out_dir, manifest):
    t0 = time.time()
    print("[harness] creating renderer (first run compiles shaders, 1-2 min)...", file=sys.stderr)
    renderer = ovrtx.Renderer()
    stage = ovstage.Stage("cod.level")
    renderer.attach_ovstage(stage)
    print(f"[harness] renderer up in {time.time() - t0:.1f}s", file=sys.stderr)

    ordinal = 0
    try:
        for shot in shots:
            product = f"/Render/{shot}"
            entry = manifest["shots"].get(shot, {})
            shot_res = resolution or tuple(entry.get("resolution", ())) or None

            # Supersample: render bigger, deliver at shot_res. See capture().
            ss = args.ss if args.ss is not None else int(entry.get("supersample", 1))
            ss = max(1, ss)
            deliver_res = shot_res
            if ss > 1 and shot_res:
                shot_res = (shot_res[0] * ss, shot_res[1] * ss)

            denoise = args.denoise if args.denoise is not None else int(entry.get("denoise", 1))
            shot_warmup = warmup if args.warmup is not None else int(entry.get("warmup", warmup))

            print(f"[harness] === {shot} [{tier}] res={shot_res or 'as-authored'}"
                  f"{f' ss={ss} -> {deliver_res}' if ss > 1 else ''}"
                  f" warmup={shot_warmup}{'' if denoise else ' denoise=OFF'}"
                  f" ===", file=sys.stderr)
            t0 = time.time()

            ordinal += 1
            ffmax = args.ffmax if args.ffmax is not None else float(entry.get("ffmax", 3200.0))
            spi = args.spi if args.spi is not None else int(entry.get("spi", 64))
            root = build_root_layer(level_path, shot, tier, shot_res, args.spp, denoise, ffmax, spi)
            ovstage.population.open_usd_from_string(stage, root, ordinal=ordinal)
            stage.advance_write_floor(ordinal, ovstage.Scope.ALL).wait()
            print(f"[harness]   stage loaded in {time.time() - t0:.1f}s", file=sys.stderr)

            # Discard the previous shot's accumulated samples AND renderer-global
            # settings state. Several omni:rtx:* settings -- pixelFilter:radius
            # most importantly -- were only being honoured on the FIRST product
            # of an invocation, so a batched `render.py --final` scored
            # differently from five `--shot` invocations (firefly 0.00724 vs
            # 0.00061 on LANE_EYE_YARD). reset() is what the render-settings
            # skill prescribes after changing a setting, and it makes the two
            # runs equivalent instead of making the batch a trap.
            renderer.reset()

            # Warmup covers texture streaming AND sample accumulation: in
            # PathTracing each step contributes samples, so this loop is the
            # sample count. See the note above FINAL.
            dt = args.dt if args.dt is not None else (1.0 / 60)
            for i in range(shot_warmup):
                renderer.step(render_products={product}, delta_time=dt, ordinal=ordinal)
                if (i + 1) % 200 == 0:
                    print(f"[harness]   warmup {i + 1}/{shot_warmup}  ({time.time() - t0:.0f}s)", file=sys.stderr)

            products = renderer.step(render_products={product}, delta_time=dt, ordinal=ordinal)
            name = f"{shot}{('_' + args.tag) if args.tag else ''}_{tier}.png"
            for _, prod in products.items():
                for path in capture(prod, out_dir / name, deliver_res if ss > 1 else None):
                    print(f"[harness]   SAVED {path}  ({time.time() - t0:.0f}s)", file=sys.stderr)
            del products
    finally:
        renderer.detach_ovstage()
        stage.destroy()
        renderer.destroy()


if __name__ == "__main__":
    main()
