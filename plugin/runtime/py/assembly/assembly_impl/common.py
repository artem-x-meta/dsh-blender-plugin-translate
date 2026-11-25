# -*- coding: utf-8 -*-
"""DSH assembly layer v1 — all-pairs interpenetration scan / part manifest / N-way merge / assembly gate.

Why it exists (merge accidents from parallel multi-session modelling):
  the split builders each make their own .blend and the merger uses a hand-written append/join (no manifest, no interface frame, no hash),
  and after merging there is no "one call, verdict first" gate; the existing audit_interference / audit_overlap are **pairwise** operators,
  so a human must name the two parts to compare, while contract.interference_report, although all-pairs over a scope, still
  (a) truncates silently at the default limit=60, (b) skips fully contained parts early via continue because "their triangles do not intersect", and (c) has no per-pair verdict/classification.
  This module collapses "merge + check-up + shipping gate" into four things; every number is computed by the plugin and the model only reads the verdict and acts on repairs:

  1) scan (alias audit_clash_all) — all-pairs classified scan (read-only)
     cheap→expensive layering: evaluated-mesh pre-check → all-pairs AABB broad phase → exact tri-tri (BVH.overlap)
     → depth/volume (prefer reusing K.dsh_contract_api["interference_report"]; when unavailable use
       BVH nearest points + ray-parity inside/outside + low-discrepancy sampled volume) → **added full-containment branch** (triangles do not intersect but the AABB contains
       → use ray parity on small-part surface points to decide inside, and report contained/clash).
     classification: clash / hidden_ok / contact / gap / float / contained / unresolved.
     spec.allow expresses "hidden overlap allowed by this spec" (max_depth_mm / max_volume_mm3); allowed pairs are not false-flagged.
     coverage: coverage{complete,truncated,budget_hit}; anything untested/undecided ⇒ degraded (never silently passes).
     floaters: with a manifest use "connectivity-graph reachability + per-interface contact verification"; without one, fall back to audit_connectivity.

  2) manifest — part manifest (init|add_part|add_interface|add_allow|validate|seal|show)
     JSON read/write + validation: unique id / file exists / file_md5 / both interface ends exist / basis orthogonal / units consistent.
     It is the only allowlist source for allow (reproducible across processes, not dependent on K.dsh_contract's in-session state).

  3) merge — N-way merge (dry_run=true by default)
     append via libraries.load(link=False) in part-id lexicographic order → object name <partid>__<original name>
     → write custom props → manifest transform → recalc normals → optional txn snapshot → automatic gate.
     dry_run returns only the plan and writes nothing; a failing gate saves nothing (a failure writes nothing); on success it writes merge_receipt.json.

  4) gate — assembly shipping gate (verdict-first)
     runs mesh(audit_mesh) + normals + scan + floaters (manifest connectivity graph/connectivity) + interfaces + measure,
     aggregates the three-state; **export_allowed is true only when verdict=pass**; any skipped/degraded does not count as a pass.

  5) repair (alias fix_clash; the pure planner is fix_interference) — assembly repair
     scan → plan (translate clash/contained; float via audit_snap_floaters; boolean only with explicit consent) → snapshot →
     apply → re-scan, up to max_rounds rounds; policy=safe|manual|aggressive controls the low-risk auto-repair boundary.

  6) export (alias asm_export) — delivery close-out
     optional asm_merge(dry_run=false) → export GLB/FBX/OBJ → <out_dir>/<name>_manifest.json +
     append-only merge_ledger.jsonl (ts/action/manifest_md5/files/md5/gate_verdict).

Hard rules (following the v3 criterion of audit / gate):
  * empty output / bad arguments / an analysis that blows up ⇒ ok:false (no silent success);
  * unresolved (insufficient evidence) is never a pass; truncated / budget_hit ⇒ degraded;
  * read-only ops (scan / manifest show|validate / gate) do not change the scene; merge is the only write op (dry_run by default).
  * honest limits are written into each receipt's honest_limits (sampled depth/volume are estimates; inside/outside verdicts on open meshes / inward normals do not count).

Entry points (Python / after preload):
    K.dsh_assembly_api("scan", {"objects": ["GEO-a","GEO-b"], "spec": {"allow": [...]}})
    K.dsh_assembly_api("manifest", {"action": "init", "path": "...assembly.json", "assembly": "Aurora"})
    K.dsh_assembly_api("merge", {"manifest": "...assembly.json", "dry_run": true})
    K.dsh_assembly_api("gate", {"scope": ["COL_Geo"], "manifest": "...assembly.json"})
    K.dsh_assembly_api("repair", {"objects": ["GEO-a", "GEO-b"], "dry_run": true, "policy": "safe"})
    K.dsh_assembly_api("export", {"manifest": "...assembly.json", "out_dir": "D:/Blender/out",
                                  "name": "assembly", "merge": true, "formats": ["glb", "fbx", "obj"]})
"""
import hashlib
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Euler as Euler, Matrix as Matrix, Vector
from mathutils.bvhtree import BVHTree

ASSEMBLY_VERSION = 1
MANIFEST_SCHEMA = "dsh-assembly-manifest/1"
CLASSES = ("clash", "hidden_ok", "contact", "gap", "float", "contained", "unresolved")
FIT_CLASSES = ("clearance", "location", "press", "snap")
UNIT_MM_PER_UNIT = {"mm": 1000.0, "cm": 10.0, "m": 1.0}

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("assembly.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")

_j = _KIT.j


# ────────────────────────────── basic helper ──────────────────────────────
def _kernel():
    return sys.modules.get("dsh_rt_kernel")


def _api(name):
    K = _kernel()
    return getattr(K, "dsh_%s_api" % str(name), None) if K is not None else None


def _call_api(name, op, args=None):
    """Call another module's API (the Api is callable → returns a parsed dict); on failure returns (None, reason), never raises."""
    api = _api(name)
    if api is None:
        return None, ("K.dsh_%s_api does not exist — add %s to preload on the online path (e.g. preload=\"assembly,"
                      "audit,contract,clearance,gate\"); for offline see runtime/py/core/offline_bootstrap.py" % (name, name))
    try:
        out = api(str(op), dict(args or {}))
    except Exception as e:
        return None, "K.dsh_%s_api.%s call failed: %s: %s" % (name, op, type(e).__name__, str(e)[:180])
    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            return None, "K.dsh_%s_api.%s did not return JSON" % (name, op)
    if not isinstance(out, dict):
        return None, "K.dsh_%s_api.%s returned an unexpected type: %s" % (name, op, type(out).__name__)
    return out, None


def _path(p):
    """WSL path → the form usable by Blender (a Windows process); use K.win_path when it is available."""
    s = str(p or "")
    if not s or not s.startswith("/"):
        return s
    K = _kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return str(K.win_path(s))
        except Exception:
            pass
    return s


def _r(x, n=4):
    try:
        if x is None:
            return None
        return round(float(x), int(n))
    except Exception:
        return None


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if not math.isfinite(f):
        return None
    return f


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return [str(v)]


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path):
    p = _path(path)
    try:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _md5_text(t):
    return _sha256_bytes(str(t).encode("utf-8"))


def _receipt(body, t0=None):
    """Unified receipt skeleton: ok/verdict + units + elapsed time."""
    d = dict(body or {})
    d.setdefault("units", {"mm_per_unit": _r(_KIT.units(), 6)})
    if t0 is not None:
        d["ms"] = int((time.perf_counter() - t0) * 1000)
    return d


def _err(msg, **kw):
    d = {"ok": False, "error": str(msg)[:400], "hint": kw.pop("hint", None)}
    d.update(kw)
    return _j(_receipt(d))


# ────────────────────────────── object resolution / evaluated mesh ──────────────────────────────
def _pick_objects(scope=None, objects=None, include_hidden=False):
    """scope|objects → mesh objects in the current session. Empty/bad arguments go through info.error (the caller returns ok:false).

    Also accepts the {"objects": [...], "scope": ...} envelope; scope may be an object name/a collection name/a name prefix (same criterion as audit/contract).
    """
    info = {"objects": [], "names": [], "missing": [], "non_mesh": [], "hidden_skipped": 0,
            "scopes_missing": [], "error": None, "source": "session"}
    if isinstance(objects, dict):
        w = objects
        objects = w.get("objects") or w.get("names")
        if scope is None:
            scope = w.get("scope")
    names = _as_list(objects)
    if objects is not None and not names:
        info["error"] = "objects is an empty list (an empty output must fail; never scan the whole scene silently)"
        return info
    picked = []
    if names:
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                info["missing"].append(str(n))
            elif ob.type != "MESH":
                info["non_mesh"].append(str(n))
            else:
                picked.append(ob)
        if info["missing"] or info["non_mesh"]:
            info["error"] = ("objects contains objects that are missing or not meshes: missing=%s non_mesh=%s"
                             % (info["missing"][:6], info["non_mesh"][:6]))
            return info
    elif scope is not None:
        scopes = _as_list(scope)
        seen = set()
        for s in scopes:
            hit = []
            ob = bpy.data.objects.get(str(s))
            if ob is not None and ob.type == "MESH":
                hit.append(ob)
            coll = bpy.data.collections.get(str(s))
            if coll is not None:
                for o in coll.all_objects:
                    if o.type == "MESH":
                        hit.append(o)
            if not hit:
                hit = [o for o in bpy.data.objects if o.type == "MESH" and str(o.name).startswith(str(s))]
            if not hit:
                info["scopes_missing"].append(str(s))
            for o in hit:
                if str(o.name) not in seen:
                    seen.add(str(o.name))
                    picked.append(o)
        if info["scopes_missing"]:
            info["error"] = "nothing in scope matched any object/collection/name prefix: %s" % info["scopes_missing"][:6]
            return info
    else:
        picked = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    out = []
    for ob in picked:
        if not include_hidden:
            try:
                if ob.hide_render or ob.hide_viewport:
                    info["hidden_skipped"] += 1
                    continue
            except Exception:
                pass
        out.append(ob)
    info["objects"] = out
    info["names"] = [str(o.name) for o in out]
    if not out:
        info["error"] = ("0 visible meshes in the scope (hidden_skipped=%d) — an empty output must fail, it must not be read as 'no problems'"
                         % info["hidden_skipped"])
    return info


def _load_file_objects(path, include_hidden=False):
    """**Temporarily** append the objects of another .blend into the current session → (objs, info, cleanup).

    Only objects are taken (no scenes/collections/worlds); cleanup() is idempotent and removes the objects/temp collection/orphan data/library entries loaded by this call.
    """
    src = _path(path)
    info = {"path": src, "source": "file:%s" % src, "loaded": 0, "mesh": 0, "non_mesh": 0,
            "missing": [], "hidden_skipped": 0, "error": None, "name_of": {}}
    before = set(bpy.data.objects)
    before_libs = set(bpy.data.libraries)
    state = {"done": False, "obj": [], "coll": None}
    requested = []

    if not src or not os.path.isfile(src):
        info["error"] = "file does not exist or is not a file: %s" % src
        return [], info, (lambda: {"ok": True, "removed": {}, "note": "nothing was temporarily loaded"})

    try:
        with bpy.data.libraries.load(src, link=False) as (data_from, data_to):
            requested = [str(n) for n in data_from.objects]
            data_to.objects = list(requested)
    except Exception as e:
        got = [o for o in bpy.data.objects if o not in before]
        for o in got:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
        info["error"] = "cannot open/load failed: %s: %s" % (type(e).__name__, str(e)[:200])
        return [], info, (lambda: {"ok": True, "removed": {"objects": [str(o.name) for o in got]},
                                  "note": "failed halfway: did my best to delete the objects loaded by this call"})

    got = [o for o in getattr(data_to, "objects", []) or [] if o is not None]
    if len(got) == len(requested):
        info["name_of"] = {str(o.name): str(requested[i]) for i, o in enumerate(got) if o is not None}
    state["obj"] = list(got)
    info["loaded"] = len(got)
    meshes = [o for o in got if o.type == "MESH"]
    info["mesh"] = len(meshes)
    info["non_mesh"] = len(got) - len(meshes)
    objs = [o for o in meshes if include_hidden or not (o.hide_render or o.hide_viewport)]
    info["hidden_skipped"] = len(meshes) - len(objs)
    if not got:
        info["error"] = "the file contains no objects: %s" % src
    elif not meshes:
        info["error"] = "the file has no mesh objects: all %d objects are %s" % (
            len(got), "/".join(sorted(set(str(o.type) for o in got))))
    elif not objs:
        info["error"] = "all %d meshes in the file are hidden (include_hidden=false)" % len(meshes)
    else:
        try:
            coll = bpy.data.collections.new("DSH_ASM_FILE_TMP")
            bpy.context.scene.collection.children.link(coll)
            for o in objs:
                coll.objects.link(o)
            state["coll"] = coll
            bpy.context.view_layer.update()
            info["tmp_collection"] = str(coll.name)
        except Exception as e:
            info["error"] = "temp collection/linking failed: %s: %s" % (type(e).__name__, str(e)[:200])

    def cleanup():
        if state["done"]:
            return {"ok": True, "removed": {}, "note": "already cleaned"}
        state["done"] = True
        removed = {"objects": [], "libraries": [], "data": []}
        for o in state["obj"]:
            try:
                nm = str(o.name)
                me = o.data if o.type == "MESH" else None
                bpy.data.objects.remove(o, do_unlink=True)
                removed["objects"].append(nm)
                if me is not None and me.users == 0:
                    try:
                        bpy.data.meshes.remove(me, do_unlink=True)
                    except Exception:
                        pass
            except Exception:
                pass
        if state["coll"] is not None:
            try:
                bpy.data.collections.remove(state["coll"], do_unlink=True)
            except Exception:
                pass
        for lib in list(bpy.data.libraries):
            if lib not in before_libs:
                try:
                    nm = str(lib.name)
                    bpy.data.libraries.remove(lib, do_unlink=True)
                    removed["libraries"].append(nm)
                except Exception:
                    pass
        return {"ok": True, "removed": removed,
                "note": "close-out of the temporary load (runs on success or failure)"}

    if info["error"]:
        return [], info, cleanup
    return objs, info, cleanup


def _mesh_map(objs):
    """**Evaluated** world meshes of a group of objects → {name: md}; md holds tris/bvh/aabb/closed/normals_ok.

    Evaluated mesh (evaluated_get + to_mesh): a Boolean parent that was never applied is still measured by its final shape.
    Closedness is counted from triangle edges (boundary edge=1 / non-manifold edge>2); whether normals face outwards is read from the signed volume (meaningful only when closed).
    Honest limits: with several shells whose orientations disagree, the overall signed volume misses cases (gate runs audit_mesh shell by shell separately).
    """
    dg = bpy.context.evaluated_depsgraph_get()
    out, errors = {}, {}
    for ob in objs:
        nm = str(ob.name)
        obe = None
        try:
            obe = ob.evaluated_get(dg)
            me = obe.to_mesh()
            if me is None:
                errors[nm] = "no evaluated mesh"
                continue
            me.calc_loop_triangles()
            n = len(me.loop_triangles)
            if n == 0:
                errors[nm] = "0 triangles (empty after evaluation)"
                continue
            v = np.empty(len(me.vertices) * 3, dtype=np.float64)
            me.vertices.foreach_get("co", v)
            v = v.reshape(-1, 3)
            idx = np.empty(n * 3, dtype=np.int64)
            me.loop_triangles.foreach_get("vertices", idx)
            idx = idx.reshape(-1, 3)
            mw = np.array(obe.matrix_world, dtype=np.float64)
            tris = (v[idx.reshape(-1)] @ mw[:3, :3].T + mw[:3, 3]).reshape(-1, 3, 3)
            edges = np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]], axis=0)
            _u, cnt = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
            boundary = int((cnt == 1).sum())
            nonmanifold = int((cnt > 2).sum())
            a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
            vol_signed = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)
            areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
            closed = bool(boundary == 0 and nonmanifold == 0)
            normals_ok = bool(closed and vol_signed > 0.0)
            verts = tris.reshape(-1, 3)
            polys = [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(n)]
            bvh = BVHTree.FromPolygons([tuple(p) for p in verts.tolist()], polys, all_triangles=True)
            out[nm] = {
                "name": nm, "tris": tris, "tris_n": int(n), "bvh": bvh,
                "aabb": (tris.min(axis=(0, 1)).tolist(), tris.max(axis=(0, 1)).tolist()),
                "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
                "degenerate_faces": int((areas < 1e-12).sum()),
                "closed": closed, "volume_signed_m3": vol_signed, "normals_ok": normals_ok,
                "matrix_world": mw.tolist(), "skipped": None,
            }
        except Exception as e:
            errors[nm] = "%s: %s" % (type(e).__name__, str(e)[:160])
        finally:
            try:
                if obe is not None:
                    obe.to_mesh_clear()
            except Exception:
                pass
    return out, errors


# ────────────────────────────── geometric quantities (pure numpy + BVH) ──────────────────────────────
def _sample_surface_n(tris, n):
    """Deterministically sample triangle surface points by area + the source triangles' outward normals (same input, same output).

    The normals are used to push test points off the surface along the outward normal — relying only on "is the point inside" misjudges at coplanar boundaries/floating-point error.
    """
    tris = np.asarray(tris, dtype=np.float64)
    n = int(max(1, n))
    if len(tris) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    ab = tris[:, 1] - tris[:, 0]
    ac = tris[:, 2] - tris[:, 0]
    cross = np.cross(ab, ac)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    total = float(areas.sum())
    if total <= 0.0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    cum = np.cumsum(areas) / total
    k = np.arange(n, dtype=np.float64)
    f = (k + 0.5) / float(n)
    ti = np.clip(np.searchsorted(cum, f, side="right"), 0, len(tris) - 1)
    phi, psi = 0.6180339887498949, 0.7548776662466927
    u = np.mod((k + 1.0) * phi, 1.0)
    v = np.mod((k + 1.0) * psi, 1.0)
    flip = (u + v) > 1.0
    u[flip] = 1.0 - u[flip]
    v[flip] = 1.0 - v[flip]
    pts = tris[ti, 0] + u[:, None] * ab[ti] + v[:, None] * ac[ti]
    normals = cross[ti]
    ln = np.linalg.norm(normals, axis=1)
    normals = normals / np.maximum(ln, 1e-30)[:, None]
    return pts, normals


def _sample_surface(tris, n):
    """Deterministically sample triangle surface points by area (a low-discrepancy sequence, no random numbers → same input, same output)."""
    return _sample_surface_n(tris, n)[0]


_RAY_DIR = Vector((0.5773502691896258, 0.5773502691896258, 0.5773502691896258))


def _is_inside(p, bvh, direction=_RAY_DIR, eps=None, max_hits=4096):
    """Ray parity inside/outside test (globally exact for closed meshes; a fixed direction makes the result reproducible).

    Key point: the BVH maths is floating point, so the advance step from a surface point must be sized by the **coordinate magnitude** — a fixed 1e-6 is
    eaten by floating-point precision at 100+ unit coordinates (measured in practice: a large fully contained part was judged gap and the depth misreported as 17mm).
    """
    if bvh is None:
        return None, 0
    pp = Vector(p)
    step = float(eps) if eps is not None else max(1e-6, 1e-5 * max(1.0, abs(pp.x), abs(pp.y), abs(pp.z)))
    pp = pp + direction * step
    hits = 0
    while hits < int(max_hits):
        loc, _nor, _idx, _dist = bvh.ray_cast(pp, direction)
        if loc is None:
            break
        hits += 1
        sc = max(1.0, abs(loc.x), abs(loc.y), abs(loc.z))
        pp = loc + direction * max(1e-6, 1e-5 * sc)
    return (hits % 2) == 1, hits


_RAY_DIRS = (_RAY_DIR,
             Vector((-0.4741, 0.6342, -0.6107)).normalized(),
             Vector((0.8123, -0.3999, 0.4252)).normalized())


def _inside_vote(p, bvh):
    """Ray-parity vote over three different directions (a single direction fails on coplanar/grazing cases; a majority vote is sturdier)."""
    votes = []
    for d in _RAY_DIRS:
        inside, _h = _is_inside(p, bvh, d)
        if inside is None:
            return None, votes
        votes.append(bool(inside))
    return (sum(1 for v in votes if v) >= 2), votes


def _count_inside(points, bvh):
    n_in = 0
    tested = 0
    for p in points:
        inside, _votes = _inside_vote(p, bvh)
        if inside is None:
            continue
        tested += 1
        if inside:
            n_in += 1
    return n_in, tested


def _surface_gap(md_a, md_b, samples=600):
    """Surface nearest distance between two evaluated meshes (metres); sample points = area-weighted points + vertices."""
    best = None
    for md, other in ((md_a, md_b), (md_b, md_a)):
        pts = _sample_surface(md["tris"], samples)
        if len(pts) == 0:
            continue
        for p in pts:
            r = other["bvh"].find_nearest(Vector(p))
            if r is None or r[0] is None:
                continue
            d = float(r[3])
            if best is None or d < best:
                best = d
        for t in md["tris"]:
            for p in t:
                r = other["bvh"].find_nearest(Vector(p))
                if r is None or r[0] is None:
                    continue
                d = float(r[3])
                if best is None or d < best:
                    best = d
    return best


def _halton(k, base):
    f, r = 1.0, 0.0
    while k > 0:
        f /= float(base)
        r += f * float(k % base)
        k //= base
    return r


def _overlap_volume(md_a, md_b, n=600):
    """Intersection volume estimate: low-discrepancy sampling inside the AABB intersection box + ray parity on both sides → p × box volume (reports the binomial standard error)."""
    lo_a, hi_a = md_a["aabb"]
    lo_b, hi_b = md_b["aabb"]
    lo = [max(lo_a[i], lo_b[i]) for i in range(3)]
    hi = [min(hi_a[i], hi_b[i]) for i in range(3)]
    if any(hi[i] <= lo[i] for i in range(3)):
        return {"volume_m3": 0.0, "stderr_m3": 0.0, "p": 0.0, "box_volume_m3": 0.0, "n": 0}
    box = 1.0
    for i in range(3):
        box *= (hi[i] - lo[i])
    n = int(max(32, min(int(n), 4000)))
    hit = 0
    for i in range(n):
        p = [lo[0] + _halton(i + 1, 2) * (hi[0] - lo[0]),
             lo[1] + _halton(i + 1, 3) * (hi[1] - lo[1]),
             lo[2] + _halton(i + 1, 5) * (hi[2] - lo[2])]
        ia, _ = _is_inside(p, md_a["bvh"])
        if not ia:
            continue
        ib, _ = _is_inside(p, md_b["bvh"])
        if ib:
            hit += 1
    p = hit / float(n) if n else 0.0
    stderr = math.sqrt(max(0.0, p * (1.0 - p) / float(n))) if n else 0.0
    return {"volume_m3": p * box, "stderr_m3": stderr * box, "p": p, "box_volume_m3": box, "n": n,
            "hit": hit}


def _depth_measure(md_a, md_b, samples=1200, vol_n=600):
    """Penetration depth + intersection volume (its own fallback implementation, used when contract is unavailable).

    Depth = the nearest distance from a surface point buried inside the other body to the other surface (an SDF approximation). Three key corrections:
      ① push the test point off the surface along the **source triangle's outward normal** before the inside test — testing the surface point directly misjudges at coplanar boundaries/floating-point noise;
      ② ray parity **majority vote** over three different directions;
      ③ points closer than 2δ to the other surface (grazing, distance untrustworthy) are discarded outright and not used to build the depth.
    Volume = low-discrepancy sampling estimate inside the AABB intersection box (deterministic).
    """
    pa, na = _sample_surface_n(md_a["tris"], samples)
    pb, nb = _sample_surface_n(md_b["tris"], samples)
    if len(pa) == 0 or len(pb) == 0:
        return {"depth_mm": None, "depth_mean_mm": None, "volume_mm3": None, "method": "sampling failed"}

    def _diag(md):
        lo, hi = md["aabb"]
        return float(np.linalg.norm(np.array(hi, dtype=np.float64) - np.array(lo, dtype=np.float64)))

    delta = max(1e-6, 1e-5 * max(_diag(md_a), _diag(md_b), 1.0))

    def _collect(points, normals, other):
        out = []
        for p, n in zip(points, normals):
            q = np.asarray(p, dtype=np.float64) + np.asarray(n, dtype=np.float64) * delta
            inside, _votes = _inside_vote(q, other["bvh"])
            if not inside:
                continue
            r = other["bvh"].find_nearest(Vector(p))
            if r is None or r[0] is None:
                continue
            d = float(r[3])
            if d < 2.0 * delta:            # grazing: neither inside nor distance is trustworthy
                continue
            out.append(d)
        return out

    d_ab = _collect(pa, na, md_b)
    d_ba = _collect(pb, nb, md_a)
    dep = d_ab + d_ba
    vol = _overlap_volume(md_a, md_b, n=vol_n)
    mmu = _KIT.units()
    depth_max_m = max(dep) if dep else 0.0
    return {
        "depth_mm": depth_max_m * mmu,
        "depth_mean_mm": (sum(dep) / len(dep) * mmu) if dep else 0.0,
        "volume_mm3": vol["volume_m3"] * (mmu ** 3),
        "volume_stderr_mm3": vol["stderr_m3"] * (mmu ** 3),
        "volume_p": vol["p"],
        "surface_inside_frac": (len(dep) / float(len(pa) + len(pb))) if (len(pa) + len(pb)) else 0.0,
        "direction": "A→B" if d_ab else ("B→A" if d_ba else "no buried points"),
        "method": "BVH nearest distance + outward-normal-offset ray parity (three-direction vote) + low-discrepancy volume sampling (assembly.py's own fallback)",
    }


__all__ = [name for name in list(globals()) if not name.startswith("__")]
