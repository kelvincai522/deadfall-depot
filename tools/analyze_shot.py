"""Objective image statistics for judging a render against AAA game frames.

A critic's eye is the final authority, but eyes rationalise. These numbers catch
the failures that "looks fine to me" misses -- flat lighting, a dead frame, a
grey wash, an empty middle distance -- and they are comparable run to run, so
you can prove an iteration actually improved something.

    uv run analyze_shot.py ../_shots/HERO_final.png
    uv run analyze_shot.py ../_shots/*.png --json

Targets are drawn from the statistics of shipped AAA console frames (Modern
Warfare-era: strong key/fill separation, deep but not crushed shadows, warm/cool
split, dense high-frequency surface detail). They are guide rails, not a rubric
to game -- a deliberately foggy shot will legitimately fail contrast.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# (label, low, high, why it matters)
#
# The tighter bands on warm_cool_split / cool_pixel_frac / firefly_frac come from
# a critique round that measured them against shipped frames and caught failures
# the original loose bands passed. They are deliberately strict.
TARGETS = {
    "mean_luma":       (0.16, 0.42, "overall exposure; below is muddy, above is washed out"),
    "p01_luma":        (0.00, 0.06, "shadows must actually reach black"),
    "p99_luma":        (0.72, 1.00, "highlights must actually reach white"),
    "dynamic_range":   (0.70, 1.00, "p99-p01; a flat frame has a small range"),
    "rms_contrast":    (0.14, 0.40, "local contrast; the #1 tell of flat lighting"),
    "detail_density":  (0.075, 0.200, "high-frequency energy; low means smeared, untextured surfaces"),
    "mean_saturation": (0.10, 0.40, "colour presence; near 0 is a grey wash"),
    "warm_cool_split": (0.12, 0.28, "warm key vs cool shadow; a single hue reads as a sepia wash"),
    "cool_pixel_frac": (0.25, 0.85, "fraction of pixels where B>R; COD dusk is amber AGAINST blue"),
    "dead_area_frac":  (0.00, 0.16, "fraction of frame that is near-flat; empty sky/ground"),
    # CALIBRATION, measured on this build. A deliberately trivial scene (one
    # building, 2 lights, no props, no volumetrics) renders at firefly 0.009 /
    # speckle 0.006 / chroma 0.004. That is this renderer's floor, so a gate
    # below it is unachievable by any amount of art effort -- and an impossible
    # gate is what drives an agent to filter the measurement instead of fixing
    # the image. These bands sit at the achievable floor, not at zero.
    #
    # The same shot in the full level (82 lights) measures 0.034 / 0.020 / 0.012.
    # The 4x gap is scene lighting complexity, not the renderer: the fix is fewer,
    # larger, softer emitters -- not a stronger filter.
    "firefly_frac":    (0.0000, 0.0120, "isolated outliers vs 3x3 median, BOTH polarities; floor for this build is ~0.009"),
    "speckle_energy":  (0.0000, 0.0090, "mean |pixel - local median|; total noise energy, immune to one-sided filtering"),
    "chroma_speckle":  (0.0000, 0.0060, "per-channel independent noise; high = too many small bright emitters"),
}


def srgb_to_linear(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def analyze(path: Path) -> dict:
    img = Image.open(path).convert("RGB")
    a = np.asarray(img, dtype=np.float32) / 255.0
    h, w, _ = a.shape
    lin = srgb_to_linear(a)
    luma = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    # perceptual luma for percentiles reads closer to how the eye judges exposure
    pluma = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]

    p01, p50, p99 = (float(np.percentile(pluma, p)) for p in (1, 50, 99))
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    # High-frequency energy: mean absolute Laplacian, a texture/detail proxy.
    g = pluma
    lap = (4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    detail = float(np.abs(lap).mean())

    # Warm/cool split: how differently coloured the bright half is from the dark
    # half. AAA dusk lighting has a warm key against cool shadow; a single-source
    # flat render has almost none.
    bright = pluma > p50
    if bright.sum() > 32 and (~bright).sum() > 32:
        wb = a[bright].mean(axis=0)
        wd = a[~bright].mean(axis=0)
        warm = float(abs((wb[0] - wb[2]) - (wd[0] - wd[2])))
    else:
        warm = 0.0

    # Dead area: 16x16 tiles whose internal variation is negligible.
    ty, tx = h // 16, w // 16
    tiles = pluma[: ty * 16, : tx * 16].reshape(ty, 16, tx, 16).transpose(0, 2, 1, 3)
    tile_std = tiles.reshape(ty, tx, -1).std(axis=2)
    dead = float((tile_std < 0.012).mean())

    # Fireflies: isolated pixels far from their 3x3 neighbourhood. A path trace
    # that has not converged sprays these; no shipped game frame has them, so
    # they are the single loudest "this is a render" signal.
    #
    # MEASURED ON BOTH POLARITIES, deliberately. A previous round added a
    # save-path median clamp that suppressed only the BRIGHT side -- the exact
    # side a one-sided gate samples -- and drove this metric to 0.000 while total
    # speckle energy actually rose. Dark outliers are the same noise with the
    # opposite sign, so counting both makes the gate measure the image rather
    # than one half of a filter's output.
    from PIL import ImageFilter
    med = np.asarray(Image.fromarray((pluma * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(3)),
                     dtype=np.float32) / 255.0
    d = pluma - med
    firefly = float((np.abs(d) > 0.10).mean())
    firefly_bright = float((d > 0.10).mean())
    firefly_dark = float((d < -0.10).mean())
    speckle_energy = float(np.abs(d).mean())

    # Chromatic speckle: per-channel independent noise shows up as variance in
    # (R-B) on a flat surface. Texture aliasing is achromatic; path-trace
    # variance is not. This distinguishes "needs a better filter" from
    # "needs less variance at the source".
    rb = a[..., 0] - a[..., 2]
    rb_med = np.asarray(Image.fromarray(((rb + 1) * 127.5).astype(np.uint8)).filter(ImageFilter.MedianFilter(3)),
                        dtype=np.float32) / 127.5 - 1.0
    chroma_speckle = float(np.abs(rb - rb_med).mean())

    # Cool-pixel fraction: how much of the frame is actually on the cool side.
    cool_frac = float((a[..., 2] > a[..., 0]).mean())

    stats = {
        "file": path.name,
        "resolution": [w, h],
        "firefly_frac": firefly,
        "firefly_bright": firefly_bright,
        "firefly_dark": firefly_dark,
        "speckle_energy": speckle_energy,
        "chroma_speckle": chroma_speckle,
        "cool_pixel_frac": cool_frac,
        "mean_luma": float(luma.mean()),
        "median_luma": p50,
        "p01_luma": p01,
        "p99_luma": p99,
        "dynamic_range": p99 - p01,
        "rms_contrast": float(pluma.std()),
        "detail_density": detail,
        "mean_saturation": float(sat.mean()),
        "warm_cool_split": warm,
        "dead_area_frac": dead,
        "clipped_black_frac": float((pluma < 0.004).mean()),
        "clipped_white_frac": float((pluma > 0.996).mean()),
    }

    flags = []
    for k, (lo, hi, why) in TARGETS.items():
        v = stats[k]
        if v < lo:
            flags.append(f"{k}={v:.3f} BELOW target {lo:.3f} — {why}")
        elif v > hi:
            flags.append(f"{k}={v:.3f} ABOVE target {hi:.3f} — {why}")
    if stats["clipped_white_frac"] > 0.06:
        flags.append(f"clipped_white_frac={stats['clipped_white_frac']:.3f} — blown highlights over 6% of frame")
    if stats["clipped_black_frac"] > 0.10:
        flags.append(f"clipped_black_frac={stats['clipped_black_frac']:.3f} — crushed shadows over 10% of frame")
    stats["flags"] = flags
    stats["verdict"] = "PASS" if not flags else "REVIEW"
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    paths = []
    for pat in args.images:
        p = Path(pat)
        paths.extend(sorted(p.parent.glob(p.name)) if any(c in pat for c in "*?") else [p])
    paths = [p for p in paths if p.exists()]
    if not paths:
        sys.exit("no images found")

    results = [analyze(p) for p in paths]
    if args.json:
        print(json.dumps(results, indent=1))
        return

    for r in results:
        print(f"\n=== {r['file']}  {r['resolution'][0]}x{r['resolution'][1]}  [{r['verdict']}] ===")
        for k in ("mean_luma", "p01_luma", "p99_luma", "dynamic_range", "rms_contrast",
                  "detail_density", "mean_saturation", "warm_cool_split", "cool_pixel_frac",
                  "dead_area_frac", "firefly_frac", "speckle_energy", "chroma_speckle"):
            lo, hi, _ = TARGETS[k]
            mark = " " if lo <= r[k] <= hi else "!"
            print(f"  {mark} {k:<17} {r[k]:7.3f}   target {lo:.3f}-{hi:.3f}")
        for f in r["flags"]:
            print(f"    FLAG {f}")


if __name__ == "__main__":
    main()
