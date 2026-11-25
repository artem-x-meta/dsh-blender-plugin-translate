# -*- coding: utf-8 -*-
"""DSH delivery export (v0.9.0 / #13) — turns "it looks right in the scene" into "others can open the file, and the original scale can be derived back".

API hangs off K.dsh_deliver_api (DELIVER_VERSION = 1), entry points:
    blender_rt_cmd(name="...") / K.dsh_deliver_api["export"](...)
    it also works headless outside blender_rt_plan: after preload="deliver", call K.dsh_deliver_api["export"]({...}) directly

Capabilities:
  export(dir, objects, scope, name, fmt, normalize, target_half_extent, per_part_materials,
         manifest, units_note, include_hidden)
      takes world-space triangles from the **evaluated mesh** (evaluated_depsgraph_get().evaluated_get(ob).to_mesh(), modifiers/shape keys included)
      → writes OBJ (v/vn/f; one `g <object name>` line and one `usemtl <material name>` line per object,
      shared materials still get one line per object)
      or binary STL (single file); with per_part_materials=True it also writes `<name>.mtl` in the same directory (newmtl + Kd).
      normalize=True → scales the whole model so that "longest edge = 2 × target_half_extent", and writes **the scale factor / original bbox / original center**
      into the response and the manifest (**archival iron rule: the original scale must be derivable back**).
      manifest=True → writes `<name>_manifest.json` (per-file md5 + byte count + object count + triangle count + unit conversion block +
      normalize record + generation time + api version).
      units_note → explains mm/m from scene.unit_settings.scale_length (numbers always carry units).
  verify(path_or_dir, manifest="auto")
      reads the resulting OBJ/STL back and self-checks: file exists / triangle count matches the manifest / md5 matches the manifest /
      the OBJ's g line count and usemtl line count both match the object count; `usemtl_unique` is only a diagnostic of the distinct material count.
      **item-by-item PASS/FAIL + numbers**, never just a bare ok:true.
  help()   quick reference (including one typical call).

Hard rules (external feedback wording):
  ① empty output must be ok:false — if neither objects nor scope can produce anything, or none of the picked objects has a triangle, it always fails; no silent success;
  ② numbers carry units — coordinates are «scene units», and the conversion block gives both m and mm;
  ③ normalisation must be reversible — scale / center / original bbox all three present, p_orig = p_out / scale + center;
  ④ no new dependencies — only bpy / mathutils / numpy / json / os / struct / hashlib.
"""
import bpy
import hashlib
import json
import os as os
import struct as struct
import time

DELIVER_VERSION = 1
_DV_PRECISION = 5
_DV_FORMATS = ("obj", "stl")
_DV_BOUNDARY = ("what is exported is **evaluated** triangles (modifiers/shape keys already baked into the geometry), normals are geometric face normals (one per triangle); "
            "no UVs / custom normals / smoothing groups; the coordinate frame is Blender's world Z-up, **written out as is** (no Y-up conversion)")


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("deliver needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


def _dv_j(o):
    return json.dumps(o, ensure_ascii=False, default=str)


def _dv_kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _dv_store():
    """Delivery-side light state: remembers the last successful export (verify's manifest='auto' fallback + a receipt a human can read)."""
    K = _dv_kernel()
    if K is None:
        raise RuntimeError("the persistent kernel K is required (go through the blender_rt_* channel)")
    if not hasattr(K, "dsh_deliver"):
        K.dsh_deliver = {"exports": [], "last": None}
    st = K.dsh_deliver
    st.setdefault("exports", [])
    st.setdefault("last", None)
    return st


def _dv_now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _dv_win(path):
    K = _dv_kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return K.win_path(path)
        except Exception:
            pass
    s = str(path)
    if s.startswith("/mnt/") and len(s) > 6:
        return s[5].upper() + ":" + chr(92) + s[7:].replace("/", chr(92))
    return s


def _dv_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _dv_r(x, n=6):
    try:
        return round(float(x), n)
    except Exception:
        return x


def _dv_safe(name, default="model"):
    """Filename sanitisation (also blocks ../ and absolute-path injection)."""
    s = "".join((c if (c.isalnum() or c in "-_.") else "_") for c in str(name or ""))
    s = s.strip("._")
    return s or default


def _dv_pick(objects=None, scope=None, include_hidden=False):
    """Pick objects: (objs, missing, err, excluded_hidden).

    objects=[names] takes priority; otherwise the MESH objects in scope (a collection name, sub-collections included); otherwise every MESH in the scene.
    With include_hidden=False, filter by hide_render/hide_viewport (same rule as audit.py / contract.py).
    Tolerant: a whole {"objects":[...]} wrapper dict passed in also works.
    """
    if isinstance(objects, dict):
        w = objects
        objects = w.get("objects") or w.get("names") or w.get("list")
        if scope is None:
            scope = w.get("scope")
    missing = []
    if objects:
        want = [str(x) for x in (objects if isinstance(objects, (list, tuple)) else [objects])]
        got = []
        for n in want:
            o = bpy.data.objects.get(n)
            if o is None:
                missing.append(n)
            else:
                got.append(o)
    elif scope:
        coll = bpy.data.collections.get(str(scope))
        if coll is None:
            return [], [], "collection does not exist: %s" % scope, 0
        got = list(coll.all_objects)
    else:
        got = list(bpy.context.scene.objects)
    got = [o for o in got if o.type == "MESH"]
    if include_hidden:
        return got, missing, None, 0
    keep = [o for o in got if not (o.hide_render or o.hide_viewport)]
    return keep, missing, None, len(got) - len(keep)



__all__ = [name for name in list(globals()) if not name.startswith("__")]
