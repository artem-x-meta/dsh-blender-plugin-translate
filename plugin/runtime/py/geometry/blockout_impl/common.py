# -*- coding: utf-8 -*-
"""DSH Blockout blockout -- one call turns "stating the proportions clearly" into placeholder geometry that is renderable, exportable and handoff-ready.

Field problem: weaker models write geometry by hand first and add proportions later, so they often "look like they have parts but have no numbers when measured"; while reference images/assembly/interference checks
all need a **dimensionally trustworthy, uniformly named, collection-isolated** blockout. This module only produces the blockout (no finished detail):

ops (via blender_rt_plan; K.dsh_blockout_api is registered at the end of the module):
    base(name, template, units, anchor, parts, landmarks, collection, render, export, audit, reset,
         bevel_mm, template_scale, outdir)   # build one blockout (primitives built directly with bmesh, mm→BU conversion)
    batch(models, outdir, export, collection, cleanup, render)  # build N models in one process, per-model collection/cleanup
    export(objects|name|collection, glb, obj, render, outdir)   # add views/GLB to an already built scene (no rebuild)
    selftest / help

base parameters (all except name have defaults):
    name          model name (required; object name is BO-<name>-<id>, and the file name uses it too)
    template      none (default) | humanoid_prim | vehicle -- built-in proportion skeleton (mm, scalable via template_scale)
    units         mm (default) | cm | m -- the *_mm values in parts are interpreted in this unit (field names stay *_mm, not renamed)
    anchor        bottom (default, the model's lowest point sits on Z=0) | center (bounding-box center at Z=0) | origin (no offset)
    parts         [{id, prim:"box|cylinder|uv_sphere", size_mm|[sx,sy,sz] (box), radius_mm / depth_mm (cylinder),
                    radius_mm (uv_sphere), at_mm:[x,y,z], rot_deg:[rx,ry,rz], axis:"x|y|z" (cylinder axis),
                    mirror:true}]
                  box uses size_mm; cylinder uses radius_mm + depth_mm + axis; uv_sphere uses radius_mm.
                  mirror=true mirrors a second object across X (object name suffix -m, geometry truly mirrored, normals already fixed).
    landmarks     {"name": [x,y,z]} or [{name, at_mm}] -- recorded into the receipt only (translated together with anchor), no objects created
    collection    collection name (default BLOCKOUT; created if missing, linked into the scene if not linked)
    render        false/null skips | true uses defaults | {engine:"workbench", res:[512,512], views:"auto3",
                   sheet:true, outdir, tag, via:"auto|qc|internal", margin:1.12, lens:50}
    export        false/null skips | true (automatic <outdir>/<name>.glb) | {glb: path|true, obj: path|true}
    audit         when true, runs a mesh check on the built meshes (non-manifold edges/zero-area faces/loose vertices), independent of audit.py
    reset         when true, first clears old BO-* objects in the target collection (default false: keep what is there)
    bevel_mm      bevel width (default 1.5mm; 0=skip; adds a Bevel modifier only, **no apply**, export_apply on GLB export)
    template_scale overall scale of the built-in template (default 1.0; affects template parts only)
    outdir        output root (default location for render/export; default K.out_dir)

render artifacts: <outdir>/<tag>_<view>.png × N + optional <tag>_sheet.png (horizontal/grid montage, pure numpy)
    named views: front/back/left/right/top/bottom/iso/iso_l/iso_back/front_high,
    also "auto3" (= iso,front,right), "front,right,top", {"name","az","el"} or "az=35,el=20".
    via="auto" (default): if qc_render is in preload, prefer its render_views (Workbench + framing/lock/hash are all ready-made),
    falling back to the built-in Workbench render on failure; via="internal" forces the built-in one; via="qc" errors out when qc_render is missing.
    receipt views[i] = {name, path, ms, bytes, md5, coverage_estimate, bbox_px, res}.

Unit convention: **Blender's default 1 unit = 1 m** (follows scene.unit_settings.scale_length; mm_per_unit comes from kit.units()),
    mm values in parts → BU = mm / mm_per_unit (default ×0.001). Scene unit settings are not modified (the user's scene is not polluted).

Honest boundaries:
  · rendering supports Workbench only (no EEVEE/Cycles: a blockout must be fast and stable); all views are perspective (no orthographic);
  · the sheet is a simple horizontal/grid montage (no text annotations); the qc_render path also builds its own (independent of montage);
  · landmarks are recorded only and create no empties (avoids polluting object counts); audit is a built-in lightweight check, not the full audit.py suite;
  · batch cleans up per model by default (cleanup=true); to keep every model pass cleanup=false and make sure names are unique.
"""
import hashlib
import json as json
import math
import os
import re
import struct as struct
import sys
import tempfile
import time as time

import bpy
import bmesh
import numpy as np  # noqa: F401  # re-exported to the split blockout modules
from mathutils import Euler as Euler, Matrix, Vector as Vector

BLOCKOUT_VERSION = 1

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("blockout.py requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")
_j = _KIT.j

DEFAULT_COLLECTION = "BLOCKOUT"
DEFAULT_MATERIAL = "BO_White"
DEFAULT_BEVEL_MM = 1.5
DEFAULT_RES = (512, 512)
VIEW_AUTO3 = ["iso", "front", "right"]
ALLOWED_TEMPLATES = ("none", "humanoid_prim", "vehicle")
ALLOWED_UNITS = ("mm", "cm", "m")
ALLOWED_ANCHORS = ("bottom", "center", "origin")
ALLOWED_PRIMS = ("box", "cylinder", "uv_sphere")
PART_KEYS = set(["id", "prim", "size_mm", "size", "radius_mm", "radius", "diameter_mm", "diameter",
                 "depth_mm", "depth", "at_mm", "at", "rot_deg", "rot", "axis", "mirror", "name"])
_RENDERABLE_TYPES = ("MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME",
                     "GPENCIL", "GREASEPENCIL")
_NAMED_VIEWS = {
    "front": (-90.0, 0.0), "back": (90.0, 0.0), "left": (180.0, 0.0), "right": (0.0, 0.0),
    "top": (0.0, 90.0), "bottom": (0.0, -90.0),
    "iso": (-45.0, 25.0), "iso_l": (45.0, 25.0), "iso_back": (135.0, 25.0), "front_high": (-90.0, 30.0),
}
_VIEW_ALIASES = {"isometric": "iso", "persp": "iso", "hero": "iso", "3q": "iso"}
_SHADING_ATTRS = ("light", "color_type", "show_cavity", "cavity_type", "show_object_outline",
                  "show_specular_highlight")
_RENDER_KEYS = set(["engine", "res", "views", "sheet", "outdir", "tag", "via", "margin", "lens",
                    "film_transparent", "warmup"])


# ────────────────────────────── small utilities ──────────────────────────────
def _err(msg, hint=None, op=None, **kw):
    d = {"ok": False, "error": str(msg)[:320]}
    if hint:
        d["hint"] = str(hint)[:420]
    if op:
        d["op"] = op
    d.update(kw)
    return d


def _safe_token(s, what="name", maxlen=64):
    t = re.sub(r"[^\w.-]+", "_", str(s if s is not None else "").strip(), flags=re.UNICODE).strip("_.-")
    if not t:
        raise ValueError("%s must not be empty (or is entirely illegal characters)" % what)
    return t[:maxlen]


def _mm_per_bu():
    try:
        v = float(_KIT.units())
        return v if v > 0 else 1000.0
    except Exception:
        return 1000.0


def _unit_to_mm(units):
    u = str(units or "mm").strip().lower()
    if u not in ALLOWED_UNITS:
        raise ValueError("units only supports %s (got %r)" % ("/".join(ALLOWED_UNITS), units))
    return {"mm": 1.0, "cm": 10.0, "m": 1000.0}[u]


def _num(v, what, default=None, gt=None, minv=None, maxv=None):
    if v is None:
        if default is None:
            raise ValueError("%s is required" % what)
        return float(default)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError("%s is not a number: %r" % (what, v))
    if not math.isfinite(x):
        raise ValueError("%s is not a finite number: %r" % (what, v))
    if gt is not None and not x > gt:
        raise ValueError("%s must be > %g (got %g)" % (what, gt, x))
    if minv is not None and x < minv:
        raise ValueError("%s must be >= %g (got %g)" % (what, minv, x))
    if maxv is not None and x > maxv:
        raise ValueError("%s must be <= %g (got %g)" % (what, maxv, x))
    return x


def _bool(v, what="parameter", default=False):
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "y")
    raise ValueError("%s must be a bool (got %r)" % (what, v))


def _vec3(v, what, factor=None, default=None):
    """[x,y,z] / {"x","y","z"} → list[float]; multiply by factor when given (mm→BU conversion)."""
    if v is None:
        if default is None:
            raise ValueError("%s is required ([x,y,z])" % what)
        vals = list(default)
    elif isinstance(v, dict):
        try:
            vals = [v["x"], v["y"], v["z"]]
        except KeyError:
            raise ValueError("%s as a dict must give all three keys x/y/z" % what)
    elif isinstance(v, (list, tuple)) and len(v) == 3:
        vals = list(v)
    else:
        raise ValueError("%s must be [x,y,z] (got %r)" % (what, v))
    out = []
    for i, vv in enumerate(vals):
        x = _num(vv, "%s[%d]" % (what, i))
        out.append(x * float(factor) if factor else x)
    return out


def _box_size(v, what):
    if isinstance(v, (int, float)):
        s = _num(v, what, gt=0.0)
        return [s, s, s]
    if isinstance(v, dict):
        try:
            vals = [v["x"], v["y"], v["z"]]
        except KeyError:
            raise ValueError("%s as a dict must give x/y/z" % what)
    elif isinstance(v, (list, tuple)) and len(v) == 3:
        vals = list(v)
    else:
        raise ValueError("%s must be [sx,sy,sz] or a single number (cube)" % what)
    return [_num(x, "%s[%d]" % (what, i), gt=0.0) for i, x in enumerate(vals)]


def _win(p):
    """WSL path → Windows (when K.win_path is available); any other path unchanged."""
    s = str(p)
    try:
        if s.startswith("/") and _K is not None and hasattr(_K, "win_path"):
            return _K.win_path(s)
    except Exception:
        pass
    return s


def _norm_path(p, base=None):
    s = str(p)
    if s.startswith("/"):
        s = _win(s)
    elif base and not os.path.isabs(s) and not re.match(r"^[A-Za-z]:[\\/]", s):
        s = os.path.join(str(base), s)
    return s


def _root_outdir(raw):
    if raw:
        p = _norm_path(raw)
        try:
            os.makedirs(p, exist_ok=True)
        except Exception as e:
            raise ValueError("cannot create outdir: %s (%s)" % (p, str(e)[:120]))
        return p
    base = getattr(_K, "out_dir", None) or getattr(_K, "workdir", None) or tempfile.gettempdir()
    base = str(base)
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return tempfile.gettempdir()


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_receipt(path, expect_nonempty=True):
    if not path or not os.path.isfile(path):
        raise RuntimeError("file does not exist: %r" % (path,))
    n = int(os.path.getsize(path))
    if expect_nonempty and n <= 0:
        raise RuntimeError("file is empty: %s" % path)
    return {"path": path, "bytes": n, "md5": _md5(path)}


# ────────────────────────────── scene / collection / material ──────────────────────────────
def _ensure_collection(name):
    nm = str(name or DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION
    col = bpy.data.collections.get(nm)
    if col is None:
        col = bpy.data.collections.new(nm)
        bpy.context.scene.collection.children.link(col)
        return col
    linked = False
    try:
        for c in bpy.context.scene.collection.children_recursive:
            if c is col:
                linked = True
                break
    except Exception:
        linked = True
    if not linked:
        try:
            bpy.context.scene.collection.children.link(col)
        except Exception:
            pass
    return col


def _white_material():
    mat = bpy.data.materials.get(DEFAULT_MATERIAL)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(DEFAULT_MATERIAL)
    mat.use_nodes = True
    bsdf = None
    try:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                bsdf = node
                break
    except Exception:
        bsdf = None
    if bsdf is not None:
        try:
            bsdf.inputs["Base Color"].default_value = (0.82, 0.82, 0.82, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.6
            bsdf.inputs["Metallic"].default_value = 0.0
        except Exception:
            pass
    mat.diffuse_color = (0.82, 0.82, 0.82, 1.0)
    return mat


def _add_bevel(ob, width_bu):
    if width_bu <= 0:
        return None
    mod = ob.modifiers.new("Bevel", "BEVEL")
    try:
        mod.width = float(width_bu)
        mod.segments = 2
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(30.0)
        mod.clamp_overlap = True
    except Exception:
        pass
    return mod


def _remove_objects(names):
    removed = []
    for nm in list(names or []):
        ob = bpy.data.objects.get(str(nm))
        if ob is None:
            continue
        data = ob.data if ob.type == "MESH" else None
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append(str(nm))
        except Exception:
            continue
        if data is not None and data.users == 0:
            try:
                bpy.data.meshes.remove(data, do_unlink=True)
            except Exception:
                pass
    return removed


def _remove_collection_if_empty(name):
    if not name:
        return False
    col = bpy.data.collections.get(str(name))
    if col is None:
        return False
    try:
        if len(col.objects) or len(col.children):
            return False
        bpy.data.collections.remove(col)
        return True
    except Exception:
        return False


def _clear_bo_objects(col):
    """reset: clear old BO-* objects in the target collection (only the BO- prefix is recognized, the user's own parts are untouched)."""
    removed = []
    for ob in list(col.objects):
        if str(ob.name).startswith("BO-"):
            data = ob.data if ob.type == "MESH" else None
            nm = str(ob.name)
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except Exception:
                continue
            removed.append(nm)
            if data is not None and data.users == 0:
                try:
                    bpy.data.meshes.remove(data, do_unlink=True)
                except Exception:
                    pass
    return removed


# ────────────────────────────── primitive (built directly with bmesh, no bpy.ops) ──────────────────────────────
def _mesh_from_bm(bm, name):
    me = bpy.data.meshes.new(str(name))
    try:
        bm.to_mesh(me)
    finally:
        bm.free()
    try:
        me.validate(verbose=False)
        me.update()
    except Exception:
        pass
    return me


def _prim_box(sx, sy, sz, name):
    bm = bmesh.new()
    try:
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(float(sx), float(sy), float(sz)), verts=list(bm.verts))
    except Exception:
        bm.free()
        raise
    return _mesh_from_bm(bm, name)


def _prim_cylinder(radius, depth, axis, name, segments=24):
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=int(segments),
                              radius1=float(radius), radius2=float(radius), depth=float(depth))
        ax = str(axis or "z").lower()
        if ax == "x":
            bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0),
                             matrix=Matrix.Rotation(math.radians(90.0), 3, "Y"), verts=list(bm.verts))
        elif ax == "y":
            bmesh.ops.rotate(bm, cent=(0.0, 0.0, 0.0),
                             matrix=Matrix.Rotation(math.radians(90.0), 3, "X"), verts=list(bm.verts))
    except Exception:
        bm.free()
        raise
    return _mesh_from_bm(bm, name)


def _prim_sphere(radius, name, u_segments=24, v_segments=12):
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=int(u_segments), v_segments=int(v_segments),
                                  radius=float(radius))
    except Exception:
        bm.free()
        raise
    return _mesh_from_bm(bm, name)


def _mirror_object(ob, new_name, col):
    """True mirror (local x→-x + faces reversed + world matrix S·M·S); normals are not inverted and the export needs no negative scale."""
    me = ob.data.copy()
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        for v in bm.verts:
            v.co.x = -v.co.x
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(me)
    finally:
        bm.free()
    try:
        me.validate(verbose=False)
        me.update()
    except Exception:
        pass
    nob = bpy.data.objects.new(str(new_name), me)
    col.objects.link(nob)
    S = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    nob.matrix_world = S @ ob.matrix_world @ S
    return nob


__all__ = [name for name in list(globals()) if not name.startswith("__")]
