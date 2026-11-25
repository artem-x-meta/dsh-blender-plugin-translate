# -*- coding: utf-8 -*-
"""Split from surface_orig.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .build import surface_mesh_data

# ────────────────────────────── Object creation (bmesh, never bpy.ops) ──────────────────────────────
def _coll(name=None):
    nm = str(name or DEFAULT_COLL).strip() or DEFAULT_COLL
    c = bpy.data.collections.get(nm)
    if c is None:
        c = bpy.data.collections.new(nm)
        bpy.context.scene.collection.children.link(c)
    return c


def _bbox_mm(verts_mm):
    V = np.asarray(verts_mm, dtype=np.float64)
    if V.size == 0:
        return {"min_mm": None, "max_mm": None, "size_mm": None, "center_mm": None}
    lo = V.min(axis=0)
    hi = V.max(axis=0)
    return {"min_mm": [_r(x, 4) for x in lo], "max_mm": [_r(x, 4) for x in hi],
            "size_mm": [_r(x, 4) for x in (hi - lo)],
            "center_mm": [_r(x, 4) for x in ((hi + lo) / 2.0)]}


def _create_object(mesh_data, kind, norm, name=None, collection=None):
    """In-memory mesh (mm) → bmesh mesh object (Blender units); returns (object, info)."""
    import bmesh
    mmu = max(_mmu(), 1e-12)
    verts_u = np.asarray(mesh_data["verts_mm"], dtype=np.float64) / mmu
    faces = mesh_data["faces"]
    nm = str(name or "").strip() or (PFX + "%s_%s" % (kind, str(norm.get("spec_hash") or "nohash")[:8]))
    nm = nm.replace("\n", " ").strip()[:120]
    me = bpy.data.meshes.new(nm)
    bm = bmesh.new()
    made_faces = 0
    try:
        bverts = [bm.verts.new((float(v[0]), float(v[1]), float(v[2]))) for v in verts_u.tolist()]
        bm.verts.ensure_lookup_table()
        for f in faces:
            try:
                bm.faces.new([bverts[int(i)] for i in f])
                made_faces += 1
            except ValueError:
                continue
        bm.normal_update()
        bm.to_mesh(me)
    finally:
        bm.free()
    if made_faces == 0:
        bpy.data.meshes.remove(me, do_unlink=True)
        raise ValueError("no valid face at all (degenerate cross-section/profile?)")
    ob = bpy.data.objects.new(nm, me)
    coll = _coll(collection)
    coll.objects.link(ob)
    try:
        ob["surface.kind"] = kind
        ob["surface.version"] = int(SURFACE_VERSION)
        ob["surface.spec_hash"] = str(norm.get("spec_hash") or "")
        ob["surface.tessellation"] = json.dumps(norm.get("tessellation") or {}, ensure_ascii=False)
        ob["dsh.surface"] = "%s:%s" % (kind, str(norm.get("spec_hash") or "")[:12])
    except Exception:
        pass
    info = {"object": str(ob.name), "collection": str(coll.name), "mesh": str(me.name),
            "verts": int(len(me.vertices)), "tris": int(sum(max(0, len(p.vertices) - 2) for p in me.polygons)),
            "faces": int(len(me.polygons)), "bbox_mm": _bbox_mm(mesh_data["verts_mm"])}
    return ob, info


def _spec_summary(norm):
    d = {k: v for k, v in (norm or {}).items() if not str(k).startswith("_")}
    return d


def _build_from_norm(norm, name=None, collection=None):
    md = surface_mesh_data(norm)
    ob, info = _create_object(md, str(norm["kind"]), norm, name=name, collection=collection)
    return ob, info, md


def _op_ok(kind, norm, md, info, t0, extra=None):
    body = {"ok": True, "kind": kind, "object": info["object"], "collection": info["collection"],
            "mesh": info["mesh"], "verts": info["verts"], "tris": info["tris"],
            "bbox_mm": info["bbox_mm"], "spec_hash": norm["spec_hash"],
            "tessellation": norm["tessellation"], "meta": md["meta"],
            "spec": _spec_summary(norm),
            "note": "dimensions are in mm (converted internally per scene.unit_settings); identical spec+tessellation reproduces the same result"}
    if extra:
        body.update(extra)
    return _j(_receipt(body, t0))


# ────────────────────────────── M1 public ops ──────────────────────────────
def surface_loft(sections=None, degree=3, continuity="G1", closed=False, tessellation=None,
                 name=None, collection=None, constraints=None, units="mm", spec=None):
    """Bézier/B-spline cross-section loft: sections=[{z_mm, points_mm:[[x,y],...]}] → bmesh mesh object."""
    t0 = time.perf_counter()
    raw = spec if isinstance(spec, dict) else {
        "kind": "loft", "units": units, "sections": sections, "degree": degree,
        "continuity": continuity, "closed": closed, "tessellation": tessellation,
        "constraints": constraints}
    norm, errs = surface_spec_normalize(raw)
    if errs:
        return _err("loft spec validation failed", errors=errs[:12], stage="M0",
                    hint="sections needs at least 2, z_mm strictly increasing, points_mm as [[x,y],...] (≥3 points when closed=True)")
    try:
        ob, info, md = _build_from_norm(norm, name=name, collection=collection)
    except Exception as e:
        import traceback
        return _err("loft generation failed: %s: %s" % (type(e).__name__, str(e)[:240]), stage="M1",
                    traceback=traceback.format_exc()[-600:])
    return _op_ok("loft", norm, md, info, t0,
                  {"degree_used": md["meta"].get("degree_used")})


def surface_sweep(profile_mm=None, rail_mm=None, orientation="auto", twist_deg=0.0,
                  scale=1.0, tessellation=None, name=None, collection=None, closed=False,
                  constraints=None, units="mm", spec=None):
    """Sweep along a polyline: profile_mm 2D cross-section + rail_mm 3D path → bmesh mesh object."""
    t0 = time.perf_counter()
    raw = spec if isinstance(spec, dict) else {
        "kind": "sweep", "units": units, "profile_mm": profile_mm, "rail_mm": rail_mm,
        "orientation": orientation, "twist_deg": twist_deg, "scale": scale,
        "tessellation": tessellation, "closed": closed, "constraints": constraints}
    norm, errs = surface_spec_normalize(raw)
    if errs:
        return _err("sweep spec validation failed", errors=errs[:12], stage="M0",
                    hint="profile_mm needs at least 3 points (closed ring), rail_mm at least 2 non-repeated [x,y,z]")
    try:
        ob, info, md = _build_from_norm(norm, name=name, collection=collection)
    except Exception as e:
        import traceback
        return _err("sweep generation failed: %s: %s" % (type(e).__name__, str(e)[:240]), stage="M1",
                    traceback=traceback.format_exc()[-600:])
    return _op_ok("sweep", norm, md, info, t0, {"meta_extra": md["meta"]})


def surface_patch(control_grid=None, degree_u=3, degree_v=3, tessellation=None, name=None,
                  collection=None, constraints=None, units="mm", spec=None):
    """Four-sided B-spline patch: control_grid=[[[x,y,z],...],...] (rows=u, columns=v) → bmesh mesh object."""
    t0 = time.perf_counter()
    raw = spec if isinstance(spec, dict) else {
        "kind": "patch", "units": units, "control_grid": control_grid,
        "degree_u": degree_u, "degree_v": degree_v, "tessellation": tessellation,
        "constraints": constraints}
    norm, errs = surface_spec_normalize(raw)
    if errs:
        return _err("patch spec validation failed", errors=errs[:12], stage="M0",
                    hint="control_grid must be rectangular (≥2×2), and degree_u/v may not exceed the control-point count in that direction minus 1")
    try:
        ob, info, md = _build_from_norm(norm, name=name, collection=collection)
    except Exception as e:
        import traceback
        return _err("patch generation failed: %s: %s" % (type(e).__name__, str(e)[:240]), stage="M1",
                    traceback=traceback.format_exc()[-600:])
    return _op_ok("patch", norm, md, info, t0)


def _object_eval_mesh(ob):
    """Object → evaluated mesh (vertices in Blender-unit world coordinates, including object transform and modifiers)."""
    dg = bpy.context.evaluated_depsgraph_get()
    obe = ob.evaluated_get(dg)
    me = obe.to_mesh()
    try:
        if me is None:
            raise ValueError("object has no evaluable mesh")
        me.calc_loop_triangles()
        nv = len(me.vertices)
        v = np.empty(nv * 3, dtype=np.float64)
        me.vertices.foreach_get("co", v)
        v = v.reshape(-1, 3)
        mw = np.array(obe.matrix_world, dtype=np.float64)
        v = v @ mw[:3, :3].T + mw[:3, 3]
        idx = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", idx)
        idx = idx.reshape(-1, 3)
        return {"verts": v, "tris": idx}
    finally:
        try:
            obe.to_mesh_clear()
        except Exception:
            pass


def surface_tessellate(spec_or_object=None, quality="normal", name=None, collection=None,
                       tessellation=None, spec=None):
    """Surface spec or object → mesh object (a spec goes through M1 generation; an object means bake the evaluated mesh / apply modifiers)."""
    t0 = time.perf_counter()
    src = spec if isinstance(spec, dict) else spec_or_object
    if isinstance(src, dict):
        spec_obj = dict(src)
        if tessellation is not None:
            spec_obj["tessellation"] = tessellation
        elif spec_obj.get("tessellation") is None and quality:
            spec_obj["tessellation"] = str(quality)
        norm, errs = surface_spec_normalize(spec_obj)
        if errs:
            return _err("tessellate spec validation failed", errors=errs[:12], stage="M0")
        try:
            ob, info, md = _build_from_norm(norm, name=name, collection=collection)
        except Exception as e:
            return _err("tessellate generation failed: %s: %s" % (type(e).__name__, str(e)[:240]), stage="M1")
        return _j(_receipt({"ok": True, "mode": "spec", "object": info["object"],
                            "collection": info["collection"], "verts": info["verts"],
                            "tris": info["tris"], "bbox_mm": info["bbox_mm"],
                            "spec_hash": norm["spec_hash"], "tessellation": norm["tessellation"],
                            "meta": md["meta"], "spec": _spec_summary(norm)}, t0))
    if isinstance(src, str):
        ob = bpy.data.objects.get(src)
        if ob is None or ob.type != "MESH":
            return _err("object does not exist or is not a mesh: %r" % src, stage="M0")
        try:
            baked = _object_eval_mesh(ob)
        except Exception as e:
            return _err("object evaluation failed: %s: %s" % (type(e).__name__, str(e)[:200]), stage="M1")
        import bmesh
        mmu = max(_mmu(), 1e-12)
        nm = str(name or (str(ob.name) + "_tess"))
        me = bpy.data.meshes.new(nm)
        bm = bmesh.new()
        try:
            bv = [bm.verts.new(tuple(v)) for v in baked["verts"].tolist()]
            bm.verts.ensure_lookup_table()
            for tri in baked["tris"]:
                try:
                    bm.faces.new([bv[int(i)] for i in tri])
                except ValueError:
                    continue
            bm.normal_update()
            bm.to_mesh(me)
        finally:
            bm.free()
        nob = bpy.data.objects.new(nm, me)
        coll = _coll(collection)
        coll.objects.link(nob)
        try:
            nob["surface.kind"] = "tessellated"
            nob["surface.source"] = str(ob.name)
            nob["surface.version"] = int(SURFACE_VERSION)
        except Exception:
            pass
        verts_mm = baked["verts"] * mmu
        info = {"object": str(nob.name), "collection": str(coll.name), "mesh": str(me.name),
                "verts": int(len(me.vertices)),
                "tris": int(sum(max(0, len(p.vertices) - 2) for p in me.polygons)),
                "bbox_mm": _bbox_mm(verts_mm)}
        return _j(_receipt({"ok": True, "mode": "object_bake", "source": str(ob.name),
                            "object": info["object"], "collection": info["collection"],
                            "verts": info["verts"], "tris": info["tris"],
                            "bbox_mm": info["bbox_mm"],
                            "note": "the object was baked from its evaluated mesh (modifiers/transform already applied)"}, t0))
    return _err("spec_or_object must be a SurfaceSpec object or a mesh object name", stage="M0")


# ────────────────────────────── M5: interface only (no pretending to implement it) ──────────────────────────────
_OCCT_MSG = "not implemented in pure-python, OCCT backend required"


def surface_blend(a=None, b=None, method=None, params=None):
    """M5 interface: BRep blending/fillets need the OCCT kernel (this package has no such dependency); refuse explicitly rather than return a fake surface."""
    return _err(_OCCT_MSG, stage="M5", op="blend",
                hint="pure bpy+numpy does not do BRep blending/fillets; it opens up once an OCCT (pythonocc/OCP) backend is wired in."
                     "Currently available alternatives: build the transition surface by hand with loft/sweep/patch, or use the geo module's primitives + bevel")


def surface_offset(spec_or_object=None, distance_mm=None, params=None):
    """M5 interface: isometric offset needs OCCT (a robust offset self-intersects/flips faces in pure Python); refuse explicitly."""
    return _err(_OCCT_MSG, stage="M5", op="offset",
                hint="isometric surface offset self-intersects/flips faces in pure Python and is not implemented; it needs an OCCT backend."
                     "Currently available alternative: change the section parameters and re-loft (e.g. wall thickness of a bottle body via two lofts, inner and outer)")
# ────────────────────────────── M2: mesh analysis (everything in mm) ──────────────────────────────
class _SpecError(Exception):
    def __init__(self, errors):
        self.errors = errors or []
        Exception.__init__(self, "spec validation failed")


def _faces_to_tris(faces):
    out = []
    for f in faces:
        f = [int(i) for i in f]
        for k in range(1, len(f) - 1):
            out.append((f[0], f[k], f[k + 1]))
    return np.asarray(out, dtype=np.int64).reshape(-1, 3)
