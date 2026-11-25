# -*- coding: utf-8 -*-
"""Split from audit.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _conn_max_tris():
    import os
    try:
        v = int(os.environ.get("DSH_CONN_MAX_TRIS", "") or 0)
        return v if v > 0 else CONN_MAX_TRIS
    except Exception:
        return CONN_MAX_TRIS


def _units():
    """Scene unit conversion → (meters/unit, millimeters/unit). Every mm-based threshold is converted through this; never hard-code it."""
    m = 1.0
    try:
        m = float(bpy.context.scene.unit_settings.scale_length) or 1.0
    except Exception:
        m = 1.0
    return m, m * 1000.0


def _r(x, n=5):
    try:
        return round(float(x), n)
    except Exception:
        return x


def _objs_for(objects, scope, include_hidden=False):
    """Wrapper around _pick: additionally filter by hide_render/hide_viewport (same policy as _scope_objects in the contract layer)."""
    if isinstance(objects, dict):
        w = objects
        include_hidden = bool(w.get("include_hidden", include_hidden))
        objects = w.get("objects") or w.get("names") or w.get("list")
        if scope is None:
            scope = w.get("scope")
    got, missing, err = _pick(objects, scope)
    out = got if include_hidden else [o for o in got if not (o.hide_render or o.hide_viewport)]
    return out, missing, err


# ============================================================================
# v0.9.1: file= temporary load — unbinds the "session binding" (reports always use the original names from the file)
# ----------------------------------------------------------------------------
# Source: rifle-build "93 feedback": "check_* / audit_* all want the components registered in the
# session first, which is awkward when batch-processing 12 parts". Every detail below is measured in practice locally (Blender 5.2, 2026-09):
#   * bpy.data.libraries.load(link=False) is a **data API**: it works headless and in the GUI (bpy.ops.wm.append needs a GUI context);
#   * the loaded objects **belong to no collection** — unless they are linked into a temporary collection, evaluated_get gets no geometry (tris=0);
#   * dst.objects gets **filled in place** by Blender with objects → a copy must be passed in for the file's names to survive;
#   * when the session already has an object with the same name Blender appends .001/.002 → every report is mapped back to the file's original name through name_of;
#   * a file that cannot be opened raises OSError (check os.path.isfile once first, then a try as a fallback; the original error is copied into error verbatim);
#   * zero residue means deleting four things: objects / the temporary collection / data-blocks created by this run with users==0 / library entries that appeared in this run.
# ============================================================================

_PURGE_KINDS = ("meshes", "materials", "images", "node_groups", "lights", "cameras", "textures",
                "curves", "armatures", "actions")
_COUNT_KINDS = ("objects", "collections", "libraries") + _PURGE_KINDS
_REPORT_KINDS = ("objects", "collections", "libraries", "meshes", "materials", "images")   # only these 6 are reported in the response body


def _nm(ob, name_of=None):
    """Object display name: in file= mode use the original name from the file (when a name clash appends a suffix Blender renames the session-side object, which must not be reported directly)."""
    if name_of:
        n = name_of.get(str(ob.name))
        if n:
            return str(n)
    return str(ob.name)


def _named_boxes(objs, boxes, name_of=None):
    """_world_tris boxes (keys = session names) → re-keyed by the reported name (file= mode gives the file's original name)."""
    out = {}
    for ob in objs:
        b = boxes.get(ob.name)
        if b is not None:
            out[_nm(ob, name_of)] = b
    return out


def _id_snapshot():
    out = {}
    for k in _COUNT_KINDS:
        coll = getattr(bpy.data, k, None)
        out[k] = set(coll) if coll is not None else set()
    return out


def _id_counts():
    return {k: len(getattr(bpy.data, k)) for k in _COUNT_KINDS if getattr(bpy.data, k, None) is not None}


def _exc_body(e, tag=""):
    """The unified "analysis blew up" failure body (ok:false, never treated as success); carries a short traceback for locating the problem."""
    import traceback
    return {"ok": False, "error": "analysis failed%s: %s: %s" % ((" (%s)" % tag) if tag else "",
                                                                type(e).__name__, str(e)[:200]),
            "traceback": traceback.format_exc()[-600:]}


def _noop_cleanup():
    return {"ok": True, "removed": {}, "failed": [], "note": "nothing was temporarily loaded"}


def __load_file_objects_p1(st):
    path = st["path"]
    try:
        import os  # noqa: F401  # handed to the next split stage through st
        src = str(path or "")
        before = _id_snapshot()
        before_counts = _id_counts()
        state = {"done": False, "report": None}
        loaded, coll, objs, name_of = [], None, [], {}
        _shared = {"loaded": loaded, "coll": coll}   # the cleanup closure and the later helpers share these two references, which get rebound
        # "things this load created" — must be captured the moment load finishes: a single op may load **two** files
        # (the A and B sides of audit_overlap/interference), both cleanups run in finally, and only
        # the snapshot diff pins ownership on the spot, so the other side's data is never deleted (the first self-check round tripped over exactly this).
        mine = {"objects": [], "libraries": []}
        mine_ids = {k: [] for k in _PURGE_KINDS}

        def _capture_mine():
            for k in ("objects", "libraries"):
                cur = getattr(bpy.data, k, None)
                if cur is None:
                    continue
                mine[k] = [x for x in cur if x not in before.get(k, set())]
            for k in _PURGE_KINDS:
                cur = getattr(bpy.data, k, None)
                if cur is None:
                    continue
                mine_ids[k] = [x for x in cur if x not in before.get(k, set())]

        info = {"ok": False, "path": src, "source": "file:%s" % src, "requested": None, "loaded": 0,
                "mesh": 0, "non_mesh": 0, "missing": [], "hidden_skipped": 0, "renamed": [],
                "tmp_collection": None, "error": None, "_name_of": None}

    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def __load_file_objects_p2(st):
    _shared, before, before_counts, mine, mine_ids = (
        st.get("_shared"), st.get("before"), st.get("before_counts"), st.get("mine"), st.get("mine_ids"))
    state = st.get("state")
    try:
        def cleanup():
            """Must run in finally (idempotent): delete everything this temporary load created and report what was deleted."""
            if state["done"]:
                return state["report"]
            state["done"] = True
            rep = {"ok": True, "removed": {}, "failed": [], "counts_before": before_counts,
                   "counts_after": None,
                   "note": "wrap-up of the temporary load (runs whether it succeeded or not): objects / temporary collection / orphan data created by this run / library entries"}
            rm = {}
            # ① the objects loaded by this run (loaded + the on-the-spot diff) — deduplicated, and **only our own** are deleted
            victims, seen = [], set()
            for ob in list(_shared["loaded"]) + list(mine["objects"]):
                try:
                    key = int(ob.as_pointer())
                except Exception:
                    key = id(ob)
                if key in seen:
                    continue
                seen.add(key)
                victims.append(ob)
            names_rm = []
            for ob in victims:
                try:
                    nm_ob = str(ob.name)
                except Exception:
                    nm_ob = "?"
                try:
                    bpy.data.objects.remove(ob, do_unlink=True)
                    names_rm.append(nm_ob)
                except Exception as e:
                    rep["failed"].append("object %s: %s" % (nm_ob, str(e)[:80]))
            if names_rm:
                rm["objects"] = names_rm
            # ② the temporary collection
            _top_coll = _shared["coll"]
            if _top_coll is not None:
                cname = str(_top_coll.name)
                try:
                    bpy.data.collections.remove(_top_coll, do_unlink=True)
                    rm["collections"] = [cname]
                except Exception as e:
                    rep["failed"].append("collection %s: %s" % (cname, str(e)[:80]))
            # ③ data-blocks created by this run (delete only when users==0; ones still in use go into kept, not force-deleted)
            kept = {}
            for kind in _PURGE_KINDS:
                c2 = getattr(bpy.data, kind, None)
                if c2 is None:
                    continue
                for db in list(mine_ids.get(kind) or []):
                    if db in before.get(kind, set()):
                        continue
                    try:
                        users = int(db.users)
                    except Exception:
                        continue
                    if users == 0:
                        dname = str(db.name)
                        try:
                            c2.remove(db, do_unlink=True)
                            rm.setdefault(kind, []).append(dname)
                        except Exception as e:
                            rep["failed"].append("%s %s: %s" % (kind, dname, str(e)[:80]))
                    else:
                        kept.setdefault(kind, []).append(str(db.name))
            # ④ library entries that appeared in this run (measured in practice: even a link=False append leaves a Library with users==1, which can be removed directly)
            for lib in list(mine["libraries"]):
                if lib in before.get("libraries", set()):
                    continue
                lname = str(lib.name)
                try:
                    bpy.data.libraries.remove(lib, do_unlink=True)
                    rm.setdefault("libraries", []).append(lname)
                except Exception as e:
                    rep["failed"].append("library %s: %s" % (lname, str(e)[:80]))
            rep["removed"] = rm
            if kept:
                rep["kept"] = kept
            rep["counts_before"] = {k: before_counts.get(k) for k in _REPORT_KINDS}
            rep["counts_after"] = {k: _id_counts().get(k) for k in _REPORT_KINDS}
            rep["ok"] = not rep["failed"]
            state["report"] = rep
            return rep

    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def __load_file_objects_p3(st):
    _capture_mine, _shared, cleanup, include_hidden, info = (
        st.get("_capture_mine"), st.get("_shared"), st.get("cleanup"), st["include_hidden"], st.get("info"))
    names, os, src = st["names"], st.get("os"), st.get("src")
    all_names, coll, dst, keep, name_of, o, src_ctx, want = (st.get("all_names"), st.get("coll"), st.get("dst"), st.get("keep"), st.get("name_of"), st.get("o"), st.get("src_ctx"), st.get("want"))
    try:
        if not src or not os.path.isfile(src):
            info["error"] = "file does not exist or is not a file: %s" % src
            return [], cleanup, info
        try:
            with bpy.data.libraries.load(src, link=False) as (src_ctx, dst):
                all_names = [str(n) for n in src_ctx.objects]
                if names:
                    keep = set(str(x) for x in names)
                    want = [n for n in all_names if n in keep]
                    info["missing"] = sorted(keep - set(all_names))
                else:
                    want = list(all_names)
                info["requested"] = want
                dst.objects = list(want)          # ★ pass a copy: Blender fills this list in place with objects
        except Exception as e:
            _capture_mine()                       # a mid-way failure can still leave half the data behind → capture and delete it anyway
            info["error"] = "cannot open / load failed: %s: %s" % (type(e).__name__, str(e)[:200])
            return [], cleanup, info
        _capture_mine()                           # ★ pin down "what this load created" at exactly this moment
        got = list(dst.objects)
        loaded = [o for o in got if o is not None]
        _shared["loaded"] = loaded
        if len(got) == len(info["requested"]):
            name_of = {str(o.name): str(info["requested"][i]) for i, o in enumerate(got) if o is not None}
            info["renamed"] = [{"session": str(o.name), "file": str(info["requested"][i])}
                               for i, o in enumerate(got)
                               if o is not None and str(o.name) != str(info["requested"][i])]
        else:
            info["name_map_note"] = ("load returned %d entries != %d requested → the order is not assumed, names are reported as session names"
                                     % (len(got), len(info["requested"])))
        info["loaded"] = len(loaded)
        meshes = [o for o in loaded if o.type == "MESH"]
        info["mesh"] = len(meshes)
        info["non_mesh"] = len(loaded) - len(meshes)
        objs = [o for o in meshes if include_hidden or not (o.hide_render or o.hide_viewport)]
        info["hidden_skipped"] = len(meshes) - len(objs)
        info["_name_of"] = name_of
        if not loaded:
            info["error"] = "the file has no objects: %s" % src
            return [], cleanup, info
        if not meshes:
            info["error"] = "the file has no mesh objects: all %d objects are %s" % (
                len(loaded), "/".join(sorted(set(str(o.type) for o in loaded))))
            return [], cleanup, info
        if not objs:
            info["error"] = "all %d meshes in the file are hidden (with include_hidden=false they do not take part in the analysis)" % len(meshes)
            return [], cleanup, info
        try:
            coll = bpy.data.collections.new("DSH_AUDIT_FILE_TMP")
            _shared["coll"] = coll
            bpy.context.scene.collection.children.link(coll)
            for o in objs:
                coll.objects.link(o)
            bpy.context.view_layer.update()      # make the depsgraph see the new objects (otherwise evaluated_get returns no geometry)
            info["tmp_collection"] = str(coll.name)
        except Exception as e:
            info["error"] = "temporary collection / link failed: %s: %s" % (type(e).__name__, str(e)[:200])
            return [], cleanup, info
        info["ok"] = True
        info["mesh_names"] = [_nm(o, name_of) for o in objs]
        return objs, cleanup, info
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _load_file_objects(path, names=None, include_hidden=False):
    """**Temporarily** append the objects from another .blend into the current session → (objs, cleanup, info).

    * Objects only (no scenes/collections/world); when names is non-empty only those names are taken, and names
      that are not in the file go into info.missing.
    * Visibility: with include_hidden=False filter by hide_render/hide_viewport (same policy as _objs_for).
    * cleanup() is **idempotent** and returns the list of what was actually deleted (that is the cleanup field of the response body);
      it deletes: the objects loaded by this run (including non-mesh ones) / the temporary collection / data-blocks created by this run with users==0 / library entries that appeared in this run.
    * info["_name_of"] = {session name → original file name}; the caller pops it out to map the report (do not put it into the JSON).
    * Empty file / no (visible) mesh in the file / cannot be opened → info.ok=False + error (the original error is copied verbatim).
    """
    st = dict(locals())
    for _fn_ in (__load_file_objects_p1, __load_file_objects_p2, __load_file_objects_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r


def _file_names(objects=None, scope=None):
    """Filter names in file= mode: objects (list/string/wrapper dict) wins, otherwise scope is used as an **object name**.

    Why a collection name is only treated as an object name here: append only moves objects over, **collection membership does not come along** —
    to filter by an in-file collection you must append the collection into the session first, then use the session side (without file=).
    """
    if isinstance(objects, dict):
        w = objects
        objects = w.get("objects") or w.get("names") or w.get("list")
        if scope is None:
            scope = w.get("scope")
    if objects:
        return [str(x) for x in (objects if isinstance(objects, (list, tuple, set)) else [objects])]
    if scope:
        return [str(scope)]
    return None


def _objs_with_optional_file(objects, scope, include_hidden, file):
    """The unified entry point for the three ops: with file= load that file temporarily (names filter inside the file), otherwise use _objs_for (session).

    Returns a dict: {objs, missing, err, name_of, source, load, cleanup}
    — the caller runs cleanup in finally (whether it succeeded or failed); its return value is the cleanup field of the response body.
    """
    if not file:
        objs, missing, err = _objs_for(objects, scope, include_hidden)
        return {"objs": objs, "missing": missing, "err": err, "name_of": None,
                "source": None, "load": None, "cleanup": None}
    objs, cleanup, info = _load_file_objects(file, _file_names(objects, scope), include_hidden)
    name_of = info.pop("_name_of", None)
    return {"objs": objs, "missing": info.get("missing") or [],
            "err": None if info.get("ok") else info.get("error"),
            "name_of": name_of, "source": info.get("source"), "load": info, "cleanup": cleanup}


def _file_extras(res, S, crep):
    """Add the file= side's source / load summary / cleanup report to the response body (no old key is touched; it is purely additive)."""
    if S.get("source"):
        res["source"] = S["source"]
    if S.get("load") is not None:
        res["file_load"] = S["load"]
    if crep is not None:
        res["cleanup"] = crep
    return res


def _box_fields(lo, hi, mm_per_unit, digits=5):
    """World box → {min,max,size} plus the mm version (the unified "numbers carry units" format in the response body)."""
    lo = [float(x) for x in lo]
    hi = [float(x) for x in hi]
    size = [hi[k] - lo[k] for k in range(3)]
    return {"min": [_r(x, digits) for x in lo], "max": [_r(x, digits) for x in hi],
            "size": [_r(x, digits) for x in size],
            "min_mm": [_r(x * mm_per_unit, 4) for x in lo], "max_mm": [_r(x * mm_per_unit, 4) for x in hi],
            "size_mm": [_r(x * mm_per_unit, 4) for x in size]}


def _world_tris(objs):
    """Evaluated triangles → world coordinates. Returns (tris(N,3,3) float64, owner(N,) int32, boxes{name:(lo,hi)|None})."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    tris_all, owner_all, boxes = [], [], {}
    for k, ob in enumerate(objs):
        boxes.setdefault(ob.name, None)
        obe = None
        try:
            obe = ob.evaluated_get(dg)
            me = obe.to_mesh()
            if me is None:
                continue
            me.calc_loop_triangles()
            n = len(me.loop_triangles)
            if n == 0:
                obe.to_mesh_clear()
                continue
            v = np.empty(len(me.vertices) * 3, dtype=np.float64)
            me.vertices.foreach_get("co", v)
            v = v.reshape(-1, 3)
            idx = np.empty(n * 3, dtype=np.int32)
            me.loop_triangles.foreach_get("vertices", idx)
            mw = np.array(obe.matrix_world, dtype=np.float64)
            t = v[idx.reshape(-1, 3)] @ mw[:3, :3].T + mw[:3, 3]
            tris_all.append(t)
            owner_all.append(np.full(n, k, dtype=np.int32))
            p = t.reshape(-1, 3)
            boxes[ob.name] = (p.min(axis=0), p.max(axis=0))
            obe.to_mesh_clear()
        except Exception as e:
            boxes[ob.name] = None
            try:
                if obe is not None:
                    obe.to_mesh_clear()
            except Exception:
                pass
    if not tris_all:
        return None, None, boxes
    return np.concatenate(tris_all), np.concatenate(owner_all), boxes
