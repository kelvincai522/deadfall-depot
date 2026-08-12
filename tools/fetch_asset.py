"""Recursively mirror a USD asset and its composition dependencies from NVIDIA's
S3 library into a local cache, then measure it.

pxr has no https resolver, so remote assets can't be opened in place. This walks
the composition arcs (sublayers, references, payloads) layer by layer, fetching
each dependency to a path that mirrors its S3 key, which makes every relative
path inside the layers resolve correctly on disk.

    uv run fetch_asset.py Assets/simready_content/common_assets/props/container_a01/container_a01.usd
    uv run fetch_asset.py --measure-only <key> ...
    uv run fetch_asset.py --grep container --limit 12      # measure a family

Textures are not fetched: composition dependencies cover geometry, which is all
that bounding boxes need.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom

NV = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
CACHE = Path(__file__).resolve().parent.parent / "_catalog" / "_assetcache"
CATALOG = Path(__file__).resolve().parent.parent / "_catalog" / "library.json"
USD_EXT = (".usd", ".usda", ".usdc", ".usdz")


def s3_key(target: str) -> str:
    return target[len(NV):] if target.startswith(NV) else target.lstrip("/")


def fetch_one(key: str) -> Path | None:
    dst = CACHE / key
    if dst.exists():
        return dst if dst.stat().st_size > 0 else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(NV + key, dst)
        return dst
    except urllib.error.HTTPError as exc:
        print(f"    miss {key} ({exc.code})", file=sys.stderr)
        dst.write_bytes(b"")  # negative-cache so repeat runs stay fast
        return None


def normalize(base_key: str, dep: str) -> str | None:
    """Resolve a composition dependency recorded in `base_key` to an S3 key."""
    if dep.startswith(("http://", "https://")):
        return s3_key(dep) if dep.startswith(NV) else None
    if dep.startswith("omniverse://") or "://" in dep:
        return None
    parts = (Path(base_key).parent.as_posix() + "/" + dep).split("/")
    out: list[str] = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if out:
                out.pop()
        else:
            out.append(p)
    return "/".join(out)


def mirror(root_key: str, max_layers: int = 4000) -> Path | None:
    """Fetch root_key and everything it composes. Returns the local root path."""
    root_path = fetch_one(root_key)
    if root_path is None:
        return None
    seen, queue = {root_key}, [root_key]
    while queue and len(seen) < max_layers:
        key = queue.pop()
        local = CACHE / key
        if not local.exists() or local.stat().st_size == 0:
            continue
        if local.suffix.lower() not in USD_EXT:
            continue
        try:
            layer = Sdf.Layer.FindOrOpen(str(local))
        except Exception:
            continue
        if layer is None:
            continue
        for dep in layer.GetCompositionAssetDependencies():
            nk = normalize(key, dep)
            if nk and nk not in seen and Path(nk).suffix.lower() in USD_EXT:
                seen.add(nk)
                queue.append(nk)
                fetch_one(nk)
    return root_path


def measure(root_key: str) -> dict:
    local = mirror(root_key)
    if local is None:
        return {"key": root_key, "error": "fetch failed"}
    stage = Usd.Stage.Open(str(local), load=Usd.Stage.LoadAll)
    if stage is None:
        return {"key": root_key, "error": "open failed"}
    mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    up = str(UsdGeom.GetStageUpAxis(stage))
    dp = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    rng = cache.ComputeWorldBound(dp).ComputeAlignedRange()
    npts = sum(
        len(UsdGeom.Mesh(p).GetPointsAttr().Get() or [])
        for p in stage.Traverse()
        if p.IsA(UsdGeom.Mesh) and UsdGeom.Mesh(p).GetPointsAttr().HasAuthoredValue()
    )
    out = {"key": root_key, "upAxis": up, "metersPerUnit": mpu, "points": npts,
           "defaultPrim": dp.GetName()}
    if rng.IsEmpty():
        out["error"] = "empty bbox"
        return out
    mn, mx = rng.GetMin(), rng.GetMax()
    out["min_m"] = [round(v * mpu, 4) for v in mn]
    out["max_m"] = [round(v * mpu, 4) for v in mx]
    out["size_m"] = [round((mx[i] - mn[i]) * mpu, 4) for i in range(3)]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*", help="S3 keys or full URLs")
    ap.add_argument("--grep", help="substring match against the crawled catalog")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    targets = [s3_key(t) for t in args.targets]
    if args.grep:
        cat = json.loads(CATALOG.read_text())["dirs"]
        keys = sorted({f for v in cat.values() for f in v["files"]
                       if f.lower().endswith(USD_EXT) and args.grep.lower() in f.lower()})
        targets += keys[: args.limit]

    results = []
    for t in targets:
        print(f"[fetch] {t}", file=sys.stderr)
        results.append(measure(t))

    if args.json:
        print(json.dumps(results, indent=1))
        return
    print(f"\n{'size X x Y x Z (meters)':<34} {'up':<3} {'pts':>9}  asset")
    for r in results:
        if "size_m" in r:
            sz = " x ".join(f"{v:8.3f}" for v in r["size_m"])
            print(f"{sz:<34} {r['upAxis']:<3} {r['points']:>9,}  {r['key']}")
        else:
            print(f"{'-- ' + r.get('error', '?'):<34} {'':<3} {'':>9}  {r['key']}")


if __name__ == "__main__":
    main()
