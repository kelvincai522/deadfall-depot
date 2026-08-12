"""Validate the level's USD before spending GPU time on it.

The renderer's failure mode for a malformed layer is indirect and expensive: a
sublayer that fails to parse composes as *empty*, so the first symptom is
"Invalid render product path" tens of seconds into a run. This catches the real
error in under a second.

    uv run validate.py                  # validate usd/level.usda
    uv run validate.py ../usd/foo.usda  # validate a specific layer

Checks
  1. every layer parses as USDA text
  2. the stage composes, and each sublayer actually contributed prims
  3. stage metrics are metres + Z-up
  4. every RenderProduct has a camera rel, orderedVars, resolution, a RenderVar
  5. every camera rel resolves to a real Camera prim
  6. references to centimetre-authored assets carry a ~0.01 scale
  7. lights, materials and meshes are sane (intensity > 0, bound materials exist)

pxr has no https resolver, so unresolved remote assets are expected and are
reported as notes, not failures -- ovrtx resolves those at render time.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_catalog" / "library.json"

# Asset families known to be authored in centimetres (metersPerUnit 0.01).
# Referencing one into our metre stage without a 0.01 scale makes it 100x too big.
CM_PREFIXES = ("Assets/ArchVis/", "Assets/Skies/", "Assets/Vegetation/",
               "Assets/Scenes/", "Environments/", "Assets/Particles/")

errors: list[str] = []
warns: list[str] = []
notes: list[str] = []


def err(m): errors.append(m)
def warn(m): warns.append(m)
def note(m): notes.append(m)


def check_syntax(layer_path: Path) -> bool:
    try:
        layer = Sdf.Layer.FindOrOpen(str(layer_path))
    except Exception as exc:
        msg = str(exc).strip().splitlines()
        detail = next((l for l in msg if ".usda:" in l), msg[-1] if msg else str(exc))
        err(f"PARSE {layer_path.name}: {detail.strip()}")
        return False
    if layer is None:
        err(f"PARSE {layer_path.name}: layer could not be opened")
        return False
    return True


def walk_sublayers(layer_path: Path, seen: set) -> list[Path]:
    """Depth-first collect of local sublayers, syntax-checking each."""
    out = []
    if layer_path in seen or not layer_path.exists():
        return out
    seen.add(layer_path)
    if not check_syntax(layer_path):
        return out
    out.append(layer_path)
    layer = Sdf.Layer.FindOrOpen(str(layer_path))
    for sub in layer.subLayerPaths:
        if sub.startswith(("http://", "https://")):
            continue
        out += walk_sublayers((layer_path.parent / sub).resolve(), seen)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default=str(ROOT / "usd" / "level.usda"))
    ap.add_argument("--quiet", action="store_true", help="only print the verdict")
    args = ap.parse_args()

    root = Path(args.target).resolve()
    if not root.exists():
        print(f"FAIL: {root} does not exist")
        return 1

    layers = walk_sublayers(root, set())
    if errors:
        report(args.quiet)
        return 1

    stage = Usd.Stage.Open(str(root), load=Usd.Stage.LoadAll)
    if stage is None:
        err(f"stage failed to compose: {root}")
        report(args.quiet)
        return 1

    # --- stage metrics -----------------------------------------------------
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    up = str(UsdGeom.GetStageUpAxis(stage))
    if abs(mpu - 1.0) > 1e-6:
        err(f"stage metersPerUnit is {mpu}, expected 1 (metres)")
    if up != "Z":
        err(f"stage upAxis is {up}, expected Z")
    if not stage.GetDefaultPrim():
        err("stage has no defaultPrim")

    prims = list(stage.Traverse())
    note(f"{len(layers)} local layers, {len(prims)} composed prims")

    # A sublayer that parsed but contributed nothing is almost always a mistake.
    for lp in layers[1:]:
        layer = Sdf.Layer.FindOrOpen(str(lp))
        specs = [s for s in _spec_paths(layer) if s != "/"]
        if not specs:
            warn(f"sublayer contributes no prims: {lp.name}")

    # --- render products ---------------------------------------------------
    products = [p for p in prims if p.GetTypeName() == "RenderProduct"]
    if not products:
        err("no RenderProduct prims found -- nothing can be rendered")
    for p in products:
        path = p.GetPath().pathString
        cam_rel = p.GetRelationship("camera")
        targets = cam_rel.GetTargets() if cam_rel else []
        if not targets:
            err(f"{path}: no `rel camera`")
        else:
            cam = stage.GetPrimAtPath(targets[0])
            if not cam or not cam.IsValid():
                err(f"{path}: camera rel points at missing prim {targets[0]}")
            elif cam.GetTypeName() != "Camera":
                err(f"{path}: camera rel points at a {cam.GetTypeName()}, not a Camera")
        ov = p.GetRelationship("orderedVars")
        if not ov or not ov.GetTargets():
            err(f"{path}: no `rel orderedVars`")
        res = p.GetAttribute("resolution").Get() if p.GetAttribute("resolution") else None
        if not res:
            warn(f"{path}: no resolution authored")
        elif min(res) < 64:
            err(f"{path}: implausible resolution {tuple(res)}")
        if not any(c.GetTypeName() == "RenderVar" for c in p.GetChildren()):
            err(f"{path}: no RenderVar child")

    # --- cameras -----------------------------------------------------------
    cams = [p for p in prims if p.GetTypeName() == "Camera"]
    for c in cams:
        cam = UsdGeom.Camera(c)
        fl = cam.GetFocalLengthAttr().Get()
        ha = cam.GetHorizontalApertureAttr().Get()
        cr = cam.GetClippingRangeAttr().Get()
        if not fl or fl <= 0:
            err(f"{c.GetPath()}: focalLength {fl}")
        if not ha or ha <= 0:
            err(f"{c.GetPath()}: horizontalAperture {ha}")
        if cr and cr[0] <= 0:
            err(f"{c.GetPath()}: near clip {cr[0]} must be > 0")
        if fl and ha:
            import math
            fov = 2 * math.degrees(math.atan(ha / (2 * fl)))
            if not 40 <= fov <= 130:
                warn(f"{c.GetPath()}: horizontal FOV {fov:.0f}deg is outside a first-person range")

    # --- centimetre assets referenced without a rescale --------------------
    for prim in prims:
        refs = _reference_assets(prim)
        if not refs:
            continue
        needs_cm = [r for r in refs if any(k in r for k in CM_PREFIXES)]
        if not needs_cm:
            continue
        scale = _resolved_scale(prim)
        if scale is None:
            err(f"{prim.GetPath()}: references cm-authored asset with no scale op "
                f"-> will be 100x too large ({Path(needs_cm[0]).name})")
        elif not (0.005 < abs(scale[0]) < 0.02):
            warn(f"{prim.GetPath()}: references cm-authored asset with scale {scale[0]:g} "
                 f"(expected ~0.01)")

    # --- lights ------------------------------------------------------------
    lights = [p for p in prims if "Light" in p.GetTypeName()]
    if not lights:
        err("no lights in the stage")
    for lp in lights:
        i = lp.GetAttribute("inputs:intensity")
        v = i.Get() if i else None
        if v is not None and v <= 0:
            warn(f"{lp.GetPath()}: intensity {v}")
    note(f"{len(lights)} lights, {len(cams)} cameras, {len(products)} render products")

    # --- materials ---------------------------------------------------------
    missing_bind = 0
    for prim in prims:
        if not prim.IsA(UsdGeom.Mesh):
            continue
        rel = prim.GetRelationship("material:binding")
        if not rel or not rel.GetTargets():
            missing_bind += 1
            continue
        tgt = rel.GetTargets()[0]
        if not stage.GetPrimAtPath(tgt).IsValid():
            err(f"{prim.GetPath()}: material:binding -> missing {tgt}")
    if missing_bind:
        warn(f"{missing_bind} mesh(es) with no material:binding")

    mats = [p for p in prims if p.IsA(UsdShade.Material)]
    for m in mats:
        mat = UsdShade.Material(m)
        if not mat.GetSurfaceOutput("mdl").HasConnectedSource() and \
           not mat.GetSurfaceOutput().HasConnectedSource():
            warn(f"{m.GetPath()}: material has no connected surface output")
    note(f"{len(mats)} materials")

    report(args.quiet)
    return 1 if errors else 0


def _spec_paths(layer):
    out = []
    layer.Traverse(Sdf.Path("/"), lambda p: out.append(p.pathString))
    return out


def _reference_assets(prim) -> list[str]:
    out = []
    for arc in ("references", "payloads"):
        items = prim.GetMetadata(arc)
        if not items:
            continue
        for op in getattr(items, "GetAddedOrExplicitItems", lambda: [])():
            if op.assetPath:
                out.append(op.assetPath)
    return out


def _resolved_scale(prim):
    """Accumulated scale from this prim up to the stage root."""
    total = Gf.Vec3d(1, 1, 1)
    found = False
    p = prim
    while p and p.GetPath() != Sdf.Path("/"):
        x = UsdGeom.Xformable(p)
        if x:
            for op in x.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeScale:
                    v = op.Get()
                    if v is not None:
                        total = Gf.Vec3d(total[0] * v[0], total[1] * v[1], total[2] * v[2])
                        found = True
                elif op.GetOpType() == UsdGeom.XformOp.TypeTransform:
                    m = op.Get()
                    if m is not None:
                        s = Gf.Transform(m).GetScale()
                        total = Gf.Vec3d(total[0] * s[0], total[1] * s[1], total[2] * s[2])
                        found = True
        p = p.GetParent()
    return total if found else None


def report(quiet: bool):
    if not quiet:
        for n in notes:
            print(f"  note  {n}")
        for w in warns:
            print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    print(f"\n{'FAIL' if errors else 'PASS'}: {len(errors)} error(s), {len(warns)} warning(s)")


if __name__ == "__main__":
    sys.exit(main())
