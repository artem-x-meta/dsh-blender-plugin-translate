# -*- coding: utf-8 -*-
"""DSH surface algorithm pack (surface) v1 — M0–M2/M4, pure bpy + numpy (no OCCT dependency).

Why it exists: the plugin already has modeling primitives such as geo.loft/sweep, but lacks the closed loop "surface spec → mesh → quality control":
  M0 SurfaceSpec (kind/units/sections/degree/continuity/closed/constraints/tessellation) validation and spec_hash;
  M1 surface generation: loft (Bézier/B-spline cross-section lofting) / sweep (sweep along a polyline, with twist/scale/orientation) / patch (four-sided patch) /
     tessellate (spec or object → mesh object); no bpy.ops, all bmesh + numpy;
  M2 validate: G0/G1/G2 continuity, curvature max/mean/hotspots, self-intersection (BVH tri-tri, triangle limit, degraded when exceeded),
     thickness (ray approximation), mesh quality (aspect ratio/normal consistency/watertight) → ok/verdict/metrics/defects/next;
  M4 help + selftest (bottle/fender/helmet three simplified baselines + self-intersection/thin-wall/bad-parameter negative cases);
  M5 blend/offset expose the interface only: pure Python does not do it, it explicitly returns ok:false + the OCCT requirement (no pretend implementation).

Rules (fixed; change here first when changing the algorithm):
  * all length inputs and receipt units are mm; internally converted to Blender units via scene.unit_settings.scale_length (K.dsh_kit.units());
  * the same spec (including tessellation) ⇒ the same spec_hash and byte-reproducible vertices (no random numbers, no bpy.ops);
  * lofting along v uses an interpolating B-spline (degree 1..7, default 3): the surface passes through every section; u uses Catmull-Rom
    (closed=ring closure) resampling; sweep uses a parallel transport frame + linear/per-point scale + accumulated twist;
  * patch is a tensor-product B-spline (evaluated with clamped knots when control_grid is larger than degree+1);
  * validate's fail never silently becomes pass: a confirmed defect (self-intersection/thin wall/excess curvature/flipped normal/degenerate face) ⇒ fail;
    insufficient resources (triangle count exceeded/thickness not measurable by rays) ⇒ degraded; "no thickness" on an open surface is n/a, not fail.

Entry (after preload):
    K.dsh_surface_api("loft", {"sections": [...], "degree": 3, "closed": True, "name": "Bottle"})
    K.dsh_surface_api("sweep", {"profile_mm": [...], "rail_mm": [...], "twist_deg": 30})
    K.dsh_surface_api("patch", {"control_grid": [[...]], "degree_u": 3, "degree_v": 3})
    K.dsh_surface_api("tessellate", {"spec_or_object": {...}|"ObjName", "quality": "normal"})
    K.dsh_surface_api("validate", {"spec_or_object": {...}|"ObjName"})
On-machine self-check: tests/e2e/blender/native/surface.py (run by tests/e2e/blender/native_runner.py, preload="surface,audit").
"""
import hashlib
import json
import math
import os as os
import sys
import time

import bpy as bpy

import numpy as np

SURFACE_VERSION = 1
KINDS = ("loft", "sweep", "patch")
CONTINUITY = ("G0", "G1", "G2")
ORIENTATIONS = ("auto", "up_z", "up_y", "fixed")
QUALITY_TESS = {"draft": (16, 16), "normal": (48, 48), "fine": (96, 96)}
MAX_TESS = 512
MAX_VERTS = 262144
DEFAULT_COLL = "COL_surface"
PFX = "SURF_"

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("surface.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")

_j = _KIT.j


# ────────────────────────────── basic helpers ──────────────────────────────
def _kernel():
    return sys.modules.get("dsh_rt_kernel")


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def _r(x, n=6):
    try:
        return round(float(x), int(n))
    except Exception:
        return None


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _spec_hash(norm):
    if not isinstance(norm, dict):
        return None
    d = {k: v for k, v in norm.items() if k != "spec_hash" and not str(k).startswith("_")}
    return hashlib.sha256(_canon(d).encode("utf-8")).hexdigest()


def _receipt(body, t0=None):
    d = dict(body or {})
    d.setdefault("units", {"mm_per_unit": _r(_KIT.units(), 6)})
    if t0 is not None:
        d["ms"] = int((time.perf_counter() - t0) * 1000)
    return d


def _err(msg, **kw):
    d = {"ok": False, "error": str(msg)[:400], "hint": kw.pop("hint", None)}
    d.update(kw)
    return _j(_receipt(d))


def _mmu():
    return float(_KIT.units())


def _mm2u(v):
    return float(v) / max(_mmu(), 1e-12)


def _u2mm(v):
    return float(v) * _mmu()


def _vec3(v):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    out = []
    for x in v:
        f = _num(x)
        if f is None:
            return None
        out.append(f)
    return out


def _vec2(v):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    out = []
    for x in v:
        f = _num(x)
        if f is None:
            return None
        out.append(f)
    return out


# ────────────────────────────── M0: SurfaceSpec validation ──────────────────────────────
def _norm_tessellation(raw, kind):
    base = {"loft": (48, 48), "sweep": (32, 48), "patch": (32, 32)}.get(kind, (32, 32))
    if raw is None:
        u, v = base
        quality = None
    elif isinstance(raw, str):
        q = raw.strip().lower()
        if q not in QUALITY_TESS:
            return None, [{"code": "BAD_QUALITY", "msg": "tessellation quality supports only %s" % list(QUALITY_TESS)}]
        u, v = QUALITY_TESS[q]
        quality = q
    elif isinstance(raw, dict):
        quality = str(raw.get("quality") or "").strip().lower() or None
        if quality is not None:
            if quality not in QUALITY_TESS:
                return None, [{"code": "BAD_QUALITY",
                               "msg": "tessellation.quality supports only %s" % list(QUALITY_TESS)}]
            du, dv = QUALITY_TESS[quality]
        else:
            du, dv = base
        u = _num(raw.get("u"))
        v = _num(raw.get("v"))
        u = int(round(du if u is None else u))
        v = int(round(dv if v is None else v))
    else:
        return None, [{"code": "BAD_TESSELLATION", "msg": "tessellation must be {u,v} / quality / a string"}]
    errs = []
    if u < 4 or u > MAX_TESS:
        errs.append({"code": "BAD_TESS_U", "msg": "tessellation.u must be in 4..%d (got %d)" % (MAX_TESS, u)})
    if v < 4 or v > MAX_TESS:
        errs.append({"code": "BAD_TESS_V", "msg": "tessellation.v must be in 4..%d (got %d)" % (MAX_TESS, v)})
    if u * v > MAX_VERTS:
        errs.append({"code": "TESS_TOO_BIG", "msg": "u*v=%d > %d, lower tessellation first" % (u * v, MAX_VERTS)})
    if errs:
        return None, errs
    return {"u": int(u), "v": int(v),
            "quality": quality,
            "source": ("quality" if quality is not None else ("dict" if isinstance(raw, dict) else "default"))}, []


def _norm_constraints(raw):
    out = {}
    errs = []
    if raw is None:
        return out, errs
    if not isinstance(raw, dict):
        return out, [{"code": "BAD_CONSTRAINTS", "msg": "constraints must be an object"}]
    for k, v in raw.items():
        key = str(k)
        if key in ("min_thickness_mm", "max_curvature_1_per_mm", "g1_tol_deg", "g2_tol_ratio"):
            f = _num(v)
            if f is None or f <= 0:
                errs.append({"code": "BAD_CONSTRAINT", "msg": "constraints.%s must be a positive number" % key})
            else:
                out[key] = float(f)
        elif key == "up":
            vec = _vec3(v)
            n = float(np.linalg.norm(np.array(vec))) if vec else 0.0
            if vec is None or n < 1e-9:
                errs.append({"code": "BAD_CONSTRAINT", "msg": "constraints.up must be a 3-vector with length>0"})
            else:
                out["up"] = [x / n for x in vec]
        elif key in ("closed_rail", "symmetry", "note"):
            out[key] = v
        else:
            out[key] = v
    return out, errs


def _norm_sections(raw, closed):
    errs = []
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, [{"code": "BAD_SECTIONS", "msg": "loft.sections needs at least 2 sections"}]
    out, zs = [], []
    for i, sec in enumerate(raw):
        if not isinstance(sec, dict):
            errs.append({"code": "BAD_SECTION", "msg": "sections[%d] must be {z_mm, points_mm}" % i, "path": i})
            continue
        z = _num(sec.get("z_mm"))
        if z is None:
            errs.append({"code": "BAD_SECTION_Z", "msg": "sections[%d].z_mm must be a number" % i, "path": i})
            continue
        pts_raw = sec.get("points_mm")
        if not isinstance(pts_raw, (list, tuple)) or len(pts_raw) < (3 if closed else 2):
            errs.append({"code": "BAD_SECTION_POINTS",
                         "msg": "sections[%d].points_mm needs at least %d [x,y]" % (i, 3 if closed else 2), "path": i})
            continue
        pts = []
        bad = False
        for p in pts_raw:
            v = _vec2(p)
            if v is None:
                bad = True
                break
            pts.append(v)
        if bad:
            errs.append({"code": "BAD_SECTION_POINTS", "msg": "sections[%d].points_mm contains an invalid [x,y]" % i, "path": i})
            continue
        out.append({"z_mm": float(z), "points_mm": pts})
        zs.append(float(z))
    if len(out) != len(raw):
        return None, errs
    for a, b in zip(zs, zs[1:]):
        if b <= a:
            errs.append({"code": "SECTIONS_NOT_SORTED",
                         "msg": "sections' z_mm must be strictly increasing (%.4g → %.4g); sort them before lofting" % (a, b)})
            break
    return out, errs


def _norm_profile(raw, closed, field="profile_mm", min_n=3):
    if not isinstance(raw, (list, tuple)) or len(raw) < (min_n if closed else 2):
        return None, [{"code": "BAD_PROFILE",
                       "msg": "%s needs at least %d [x,y]" % (field, min_n if closed else 2)}]
    pts = []
    for p in raw:
        v = _vec2(p)
        if v is None:
            return None, [{"code": "BAD_PROFILE", "msg": "%s contains an invalid [x,y]" % field}]
        pts.append(v)
    return pts, []


def _norm_rail(raw):
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, [{"code": "BAD_RAIL", "msg": "rail_mm needs at least 2 [x,y,z]"}]
    pts = []
    for p in raw:
        v = _vec3(p)
        if v is None:
            return None, [{"code": "BAD_RAIL", "msg": "rail_mm contains an invalid [x,y,z]"}]
        if pts and float(np.linalg.norm(np.array(v) - np.array(pts[-1]))) < 1e-12:
            return None, [{"code": "BAD_RAIL", "msg": "rail_mm has adjacent duplicate points (the tangent is undefined); deduplicate first"}]
        pts.append(v)
    return pts, []


def _norm_control_grid(raw):
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None, [{"code": "BAD_GRID", "msg": "control_grid needs at least 2 rows"}]
    rows = []
    for i, row in enumerate(raw):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            return None, [{"code": "BAD_GRID", "msg": "control_grid[%d] needs at least 2 columns" % i}]
        pts = []
        for p in row:
            v = _vec3(p)
            if v is None:
                return None, [{"code": "BAD_GRID", "msg": "control_grid contains an invalid [x,y,z]"}]
            pts.append(v)
        rows.append(pts)
    ncol = len(rows[0])
    if any(len(r) != ncol for r in rows):
        return None, [{"code": "BAD_GRID", "msg": "control_grid must be rectangular (all rows the same length)"}]
    return rows, []


def surface_spec_normalize(spec):
    """M0: validate/normalize a SurfaceSpec → (norm, errors). norm contains spec_hash."""
    errors = []

    def E(code, msg, path=None):
        errors.append({"code": str(code), "msg": str(msg)[:400], "path": path})

    if not isinstance(spec, dict):
        return None, [{"code": "BAD_SPEC", "msg": "spec must be a JSON object"}]
    kind = str(spec.get("kind") or "").strip().lower()
    if kind not in KINDS:
        E("BAD_KIND", "kind supports only %s (got %r)" % (list(KINDS), spec.get("kind")))
    units = str(spec.get("units") or "mm").strip().lower()
    if units != "mm":
        E("BAD_UNITS", "units supports only mm (got %r); convert other units first" % spec.get("units"))
    degree = _num(spec.get("degree"))
    degree = 3 if degree is None else int(round(degree))
    if degree < 1 or degree > 7:
        E("BAD_DEGREE", "degree must be in 1..7 (got %r)" % spec.get("degree"))
    continuity = str(spec.get("continuity") or "G1").strip().upper()
    if continuity not in CONTINUITY:
        E("BAD_CONTINUITY", "continuity supports only %s" % list(CONTINUITY))
    closed = bool(spec.get("closed") or False)
    constraints, cerrs = _norm_constraints(spec.get("constraints"))
    for c in cerrs:
        E(c["code"], c["msg"])
    tess, terr = _norm_tessellation(spec.get("tessellation"), kind)
    for c in terr:
        E(c["code"], c["msg"])
    norm = {"kind": kind, "units": "mm", "degree": degree, "continuity": continuity,
            "closed": closed, "constraints": constraints, "tessellation": tess}
    if kind == "loft":
        sections, serrs = _norm_sections(spec.get("sections"), closed)
        for c in serrs:
            E(c["code"], c["msg"])
        norm["sections"] = sections
    elif kind == "sweep":
        profile, perrs = _norm_profile(spec.get("profile_mm"), closed, "profile_mm", 3)
        for c in perrs:
            E(c["code"], c["msg"])
        rail, rerrs = _norm_rail(spec.get("rail_mm"))
        for c in rerrs:
            E(c["code"], c["msg"])
        orientation = str(spec.get("orientation") or "auto").strip().lower()
        if orientation not in ORIENTATIONS:
            E("BAD_ORIENTATION", "orientation supports only %s" % list(ORIENTATIONS))
        twist = _num(spec.get("twist_deg"))
        twist = 0.0 if twist is None else twist
        scale = spec.get("scale")
        if isinstance(scale, (list, tuple)):
            sc = [_num(x) for x in scale]
            if any(x is None or x <= 0 for x in sc):
                E("BAD_SCALE", "every entry of the scale list must be positive")
            elif len(sc) not in (len(rail or []), 1):
                E("BAD_SCALE", "the scale list length must be 1 or == the rail point count (%d)" % len(rail or []))
            scale = [float(x) for x in sc]
        else:
            s = _num(scale)
            s = 1.0 if s is None else s
            if s <= 0:
                E("BAD_SCALE", "scale must be > 0")
            scale = float(s)
        norm.update({"profile_mm": profile, "rail_mm": rail, "orientation": orientation,
                     "twist_deg": float(twist), "scale": scale})
    elif kind == "patch":
        grid, gerrs = _norm_control_grid(spec.get("control_grid"))
        for c in gerrs:
            E(c["code"], c["msg"])
        du = _num(spec.get("degree_u"))
        dv = _num(spec.get("degree_v"))
        du = int(round(du if du is not None else degree))
        dv = int(round(dv if dv is not None else degree))
        # control_grid rows=u, columns=v; degree_u ≤ rows-1, degree_v ≤ columns-1
        for nm, val, n in (("degree_u", du, len(grid) if grid else 0),
                           ("degree_v", dv, len(grid[0]) if grid else 0)):
            if val < 1:
                E("BAD_DEGREE", "%s must be >= 1 (got %r)" % (nm, val))
            elif n and val > n - 1:
                E("BAD_DEGREE", "%s=%d exceeds the control point limit %d" % (nm, val, max(1, n - 1)))
        norm.update({"control_grid": grid, "degree_u": du, "degree_v": dv})
    if errors:
        return None, errors
    norm["spec_hash"] = _spec_hash(norm)
    return norm, []


__all__ = [name for name in list(globals()) if not name.startswith("__")]
