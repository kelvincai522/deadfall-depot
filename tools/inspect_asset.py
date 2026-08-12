"""Inspect a USD asset (local path or NVIDIA S3 URL): units, up-axis, bbox, materials, semantics.

Usage:
    uv run inspect_asset.py <url-or-path> [<url-or-path> ...]
    uv run inspect_asset.py --nv Assets/simready_content/common_assets/props/container_a01/container_a01.usd

Downloads remote assets into a local cache so pxr can open them without a
network resolver. Referenced sublayers/payloads resolve back to the S3 URL, so
we rewrite them into the cache on demand.
"""

import argparse
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdShade

NV = "https://omniverse-content-production.s3.us-west-2.amazonaws.com/"
CACHE = Path(__file__).resolve().parent.parent / "_catalog" / "_assetcache"


def fetch(url: str) -> Path:
    """Download `url` into the local cache, mirroring its S3 key path."""
    key = url[len(NV):] if url.startswith(NV) else urllib.parse.urlparse(url).path.lstrip("/")
    dst = CACHE / key
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dst)
    return dst


def resolve(target: str) -> Path:
    if target.startswith(("http://", "https://")):
        return fetch(target)
    p = Path(target)
    if p.exists():
        return p
    return fetch(NV + target.lstrip("/"))


def report(target: str) -> None:
    path = resolve(target)
    print(f"\n{'=' * 78}\n{target}\n  -> {path}  ({path.stat().st_size:,} bytes)\n{'=' * 78}")
    stage = Usd.Stage.Open(str(path))
    if stage is None:
        print("  !! failed to open")
        return

    print(f"  upAxis          : {UsdGeom.GetStageUpAxis(stage)}")
    print(f"  metersPerUnit   : {UsdGeom.GetStageMetersPerUnit(stage)}")
    print(f"  defaultPrim     : {stage.GetDefaultPrim().GetName() if stage.GetDefaultPrim() else None}")
    root = stage.GetRootLayer()
    if root.subLayerPaths:
        print(f"  subLayers       : {list(root.subLayerPaths)}")

    unloaded = [p.GetPath().pathString for p in stage.Traverse(Usd.PrimIsActive) if p.GetPayloads()]
    if unloaded:
        print(f"  payload prims   : {unloaded[:6]}")
        stage.Load()

    kinds, types, mats, sems = {}, {}, set(), set()
    npts = nprims = 0
    for prim in stage.Traverse():
        nprims += 1
        t = prim.GetTypeName()
        types[t] = types.get(t, 0) + 1
        if prim.IsA(UsdGeom.Mesh):
            attr = UsdGeom.Mesh(prim).GetPointsAttr()
            if attr and attr.HasAuthoredValue():
                npts += len(attr.Get() or [])
        if prim.IsA(UsdShade.Material):
            mats.add(prim.GetPath().pathString)
        for name in prim.GetPropertyNames():
            if "semantic" in name.lower() and name.endswith(("Data", "Type")):
                v = prim.GetAttribute(name).Get()
                if v:
                    sems.add(str(v))
    print(f"  prims           : {nprims}   mesh points: {npts:,}")
    print(f"  prim types      : {dict(sorted(types.items(), key=lambda kv: -kv[1])[:12])}")

    bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    dp = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    rng = bbox.ComputeWorldBound(dp).ComputeAlignedRange()
    if not rng.IsEmpty():
        mn, mx = rng.GetMin(), rng.GetMax()
        size = Gf.Vec3d(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])
        mpu = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
        print(f"  bbox (units)    : min={tuple(round(v, 3) for v in mn)} max={tuple(round(v, 3) for v in mx)}")
        print(f"  size (units)    : {tuple(round(v, 3) for v in size)}")
        print(f"  size (METERS)   : {tuple(round(v * mpu, 3) for v in size)}")
    if mats:
        print(f"  materials ({len(mats)}) : {sorted(mats)[:8]}")
        for mp in sorted(mats)[:3]:
            m = UsdShade.Material(stage.GetPrimAtPath(mp))
            for out_name in ("mdl:surface", "surface"):
                src = m.GetOutput(out_name.split(":")[-1])
                for ctx in (["mdl"], []):
                    o = m.GetSurfaceOutput(*ctx)
                    if o and o.HasConnectedSource():
                        shd = UsdShade.Shader(o.GetConnectedSource()[0].GetPrim())
                        aid = shd.GetSourceAsset("mdl")
                        print(f"      {mp}: mdl={aid} sub={shd.GetSourceAssetSubIdentifier('mdl')}")
                        break
                break
    if sems:
        print(f"  semantics       : {sorted(sems)[:10]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    args = ap.parse_args()
    for t in args.targets:
        try:
            report(t)
        except Exception as exc:  # keep going across a batch
            print(f"\n!! {t}: {type(exc).__name__}: {exc}", file=sys.stderr)
