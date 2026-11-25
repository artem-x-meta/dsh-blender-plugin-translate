# -*- coding: utf-8 -*-
"""Split from audit.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403


def _mesh_totals():
    return {"objects": 0, "tris": 0, "boundary_edges": 0, "nonmanifold_edges": 0, "degenerate_faces": 0,
            "loose_verts": 0, "self_intersections": 0, "normals_inverted": 0, "out_of_bounds": 0,
            "empty_objects": 0, "loose_edges": 0, "normals_unknown": 0, "normals_checked": 0,
            "normals_multi_shell": 0, "analysis_incomplete": 0}


def _mesh_envelope(envelope):
    """Parse envelope; returns (err_payload_or_None, env)."""
    if not envelope:
        return None, None
    try:
        e = [float(x) for x in envelope]
        return None, (Vector((min(e[0], e[3]), min(e[1], e[4]), min(e[2], e[5]))),
                      Vector((max(e[0], e[3]), max(e[1], e[4]), max(e[2], e[5]))))
    except Exception as exc:
        return _j({"ok": False, "clean": False, "state": "error", "analyzed": False,
                   "error": "invalid envelope: %s" % exc}), None


def _mesh_loose_edges(me):
    """The old version counted loose edges through MeshEdge.link_faces; Blender 5.2 lacks that attribute, so it returns None (recomputed by bmesh later)."""
    if len(me.edges) == 0:
        return 0
    if hasattr(me.edges[0], "link_faces"):
        return int(sum(1 for e in me.edges if not e.link_faces))
    return None


def _mesh_topology(bm, info, eps_area):
    """bmesh topology counts + signed volume + closed test."""
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    info["boundary_edges"] = int(sum(1 for e in bm.edges if len(e.link_faces) == 1))
    info["nonmanifold_edges"] = int(sum(1 for e in bm.edges if not e.is_manifold))
    info["degenerate_faces"] = int(sum(1 for f in bm.faces if f.calc_area() <= float(eps_area)))
    info["loose_verts"] = int(sum(1 for v in bm.verts if not v.link_edges))
    # v0.9.6 (review fix): Blender 5.2's MeshEdge **has no** link_faces (the hasattr above is always false) ⇒
    # loose_edges stayed None and the total stayed 0 ("not checked" treated as "none"). Now computed from bmesh.
    if info["loose_edges"] is None:
        info["loose_edges"] = int(sum(1 for e in bm.edges if not e.link_faces))
    try:
        vol = float(bm.calc_volume(signed=True))
    except Exception:
        vol = None
    info["signed_volume"] = (round(vol, 6) if vol is not None else None)
    info["closed"] = bool(info["boundary_edges"] == 0 and info["nonmanifold_edges"] == 0)


def _mesh_normals(bm, info):
    """Judge orientation per connected shell (an aggregated signed volume is cancelled by a big outward shell plus a small inverted one)."""
    try:
        _out, _nstate, _shells, _nreason = _shell_normals(bm)
    except Exception as _ne:
        _out, _nstate, _shells = None, "unknown", []
        _nreason = "shell orientation analysis raised (%s: %s) ⇒ unknown, no pass conclusion" % (type(_ne).__name__, str(_ne)[:90])
    if not info["closed"]:
        _out, _nstate = None, "n/a"        # open mesh: overall orientation is meaningless
        _nreason = ""
    info["normals_state"] = _nstate
    # v2.6 (this round's feedback #5): multi-shell with every shell's orientation verifiable — a separate fifth state, not degraded
    info["multi_shell"] = bool(_nstate == "pass_multi_shell")
    info["normals_outward"] = _out
    info["normals_shell_count"] = len(_shells or [])
    info["normals_reason"] = _nreason or ""
    if _nstate != "n/a":
        info["normals_shells"] = _shells_brief(_shells)


def _mesh_island_split(bm, hit, info, island_split, min_island_verts, max_issues):
    """Connected-island bucketing (same island / cross island) + small-island filtering; only called after successful detection."""
    if not (island_split or int(min_island_verts or 0) > 0):
        return
    # connected islands: union-find over edge-connected vertices (an "island" = one connected shell; rivets/small hardware each form their own island)
    nv = len(bm.verts)
    par = list(range(nv))

    def _find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for e in bm.edges:
        a0, b0 = e.verts[0].index, e.verts[1].index
        ra, rb = _find(a0), _find(b0)
        if ra != rb:
            par[rb] = ra
    size = {}
    for i in range(nv):
        r = _find(i)
        size[r] = size.get(r, 0) + 1
    isl_of_face = {}
    for f in bm.faces:
        isl_of_face[f.index] = _find(f.verts[0].index)
    thr = int(min_island_verts or 0)
    same = cross = filt = small_isl = 0
    for rr in size.values():
        if thr and rr < thr:
            small_isl += 1
    kept = []
    for rec in hit:
        ia = isl_of_face.get(rec[0])
        ib = isl_of_face.get(rec[1])
        sza = size.get(ia, 0)
        szb = size.get(ib, 0)
        is_same = (ia == ib)
        if is_same:
            same += 1
        else:
            cross += 1
        drop = bool(thr and (sza < thr or szb < thr))
        if drop:
            filt += 1
        else:
            kept.append(rec + [bool(is_same), int(sza), int(szb)])
    info["islands"] = {"count": len(size), "small_islands": small_isl,
                       "min_island_verts": thr}
    info["self_intersections_same_island"] = same
    info["self_intersections_cross_island"] = cross
    info["self_intersections_filtered_small_island"] = filt
    info["self_intersections_kept"] = len(kept)
    info["self_intersection_pairs"] = kept[:int(max_issues)] if max_issues else []
    info["island_note"] = ("same-island self-intersection = one shell stabbing itself (usually a modeling accident); cross-island = two shells interpenetrating"
                           " (a rivet pressed into its host is this class and may be benign by process)")


def _mesh_intersections(bm, info, self_intersect, max_issues, min_dist, island_split, min_island_verts):
    """BVH self-intersection detection (including island bucketing); on exception it writes self_intersections_state=error, never read as "no self-intersection"."""
    info["self_intersections"] = 0
    info["self_intersection_pairs"] = []
    info["self_intersections_analyzed"] = False
    info["self_intersections_state"] = "skipped"      # not requested / error / pass / fail
    info["self_intersection_error"] = None
    if not (self_intersect and len(bm.faces) > 0):
        return
    try:
        from mathutils.bvhtree import BVHTree
        bvh = BVHTree.FromBMesh(bm)
        seen = set()
        hit = []
        for a, b in (bvh.overlap(bvh) or []):
            if a >= b:
                continue
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            fa, fb = bm.faces[a], bm.faces[b]
            va = set(v.index for v in fa.verts)
            vb = set(v.index for v in fb.verts)
            if va & vb:
                continue                     # adjacent faces share vertices → not a self-intersection
            if (fa.calc_center_median() - fb.calc_center_median()).length < float(min_dist):
                continue                     # coincident faces / thin-shell jitter → reported by degenerate
            hit.append([a, b, [round(x, 4) for x in fa.calc_center_median()]])
        info["self_intersections"] = len(hit)
        info["self_intersection_pairs"] = hit[:int(max_issues)]
        info["self_intersections_analyzed"] = True
        info["self_intersections_state"] = "fail" if hit else "pass"
        _mesh_island_split(bm, hit, info, island_split, min_island_verts, max_issues)
    except Exception as e:
        # a self-intersection check **exception** must not read as "no self-intersection" (it used to be a silent 0 ⇒ clean=true false pass)
        info["self_intersect_error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        info["self_intersections_analyzed"] = False
        info["self_intersections_state"] = "error"


def _mesh_world_aabb(ob, info, env):
    """World AABB / dimensions / out-of-bounds test."""
    mn, mx = None, None
    for c in ob.bound_box:
        p = ob.matrix_world @ Vector((c[0], c[1], c[2]))
        mn = p.copy() if mn is None else Vector((min(mn[i], p[i]) for i in range(3)))
        mx = p.copy() if mx is None else Vector((max(mx[i], p[i]) for i in range(3)))
    info["aabb"] = {"min": [round(float(x), 4) for x in mn], "max": [round(float(x), 4) for x in mx]}
    info["dimensions"] = [round(float(x), 4) for x in ob.dimensions]
    if env:
        out = [i for i in range(3) if mn[i] < env[0][i] - 1e-6 or mx[i] > env[1][i] + 1e-6]
        info["out_of_bounds"] = bool(out)
        info["out_of_bounds_axes"] = out


def _mesh_object_state(info):
    """Per-object three-state: fail (a defect really exists) / degraded (not finished or undeterminable) / pass."""
    _incomplete = (not info.get("self_intersections_analyzed")) or info.get("normals_state") == "unknown"
    info["analysis_incomplete"] = bool(_incomplete)
    if any(info.get(k) for k in ("boundary_edges", "nonmanifold_edges", "degenerate_faces", "loose_verts",
                                 "loose_edges", "self_intersections", "empty")):
        info["state"] = "fail"
    elif info.get("normals_outward") is False:
        info["state"] = "fail"
    elif _incomplete:
        info["state"] = "degraded"
    else:
        info["state"] = "pass"
        if info.get("normals_state") == "pass_multi_shell":
            info["state_detail"] = "pass_multi_shell"   # v2.6: a sub-state of pass, the gate passes as usual


def _mesh_object_info(ob, eps_area, self_intersect, max_issues, min_dist,
                      island_split, min_island_verts, env):
    """Single-object audit: topology / orientation / self-intersection / AABB / three-state."""
    me = ob.data
    info = {"name": ob.name, "verts": len(me.vertices), "polys": len(me.polygons), "tris": _tris(me),
            "loose_edges": _mesh_loose_edges(me), "empty": bool(len(me.vertices) == 0)}
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        _mesh_topology(bm, info, eps_area)
        _mesh_normals(bm, info)
        _mesh_intersections(bm, info, self_intersect, max_issues, min_dist, island_split, min_island_verts)
    finally:
        bm.free()
    _mesh_world_aabb(ob, info, env)
    _mesh_object_state(info)
    return info


def _mesh_totals_add(total, info):
    """Fold one object's counts into the totals."""
    total["objects"] += 1
    total["tris"] += info["tris"]
    for k in ("boundary_edges", "nonmanifold_edges", "degenerate_faces", "loose_verts", "loose_edges",
              "self_intersections"):
        total[k] += int(info.get(k) or 0)
    if info.get("normals_outward") is False:
        total["normals_inverted"] += 1
    if info.get("normals_state") == "unknown":
        total["normals_unknown"] += 1
    if info.get("normals_state") in ("pass", "pass_multi_shell", "fail"):
        total["normals_checked"] += 1
    if info.get("normals_state") == "pass_multi_shell":
        total["normals_multi_shell"] = int(total.get("normals_multi_shell") or 0) + 1
    if info.get("analysis_incomplete"):
        total["analysis_incomplete"] += 1
    if info.get("empty"):
        total["empty_objects"] += 1
    if info.get("out_of_bounds"):
        total["out_of_bounds"] += 1


def _mesh_summary_state(total):
    """Global three-state: clean means "checked and free of defects"."""
    bad = (total["boundary_edges"] or total["nonmanifold_edges"] or total["degenerate_faces"]
           or total["loose_verts"] or total["loose_edges"] or total["self_intersections"]
           or total["normals_inverted"] or total["out_of_bounds"] or total["empty_objects"])
    _incomplete = int(total.get("analysis_incomplete") or 0)
    if bad:
        return True, "fail", "defects really exist (see the non-zero count fields in totals)", _incomplete
    if _incomplete:
        return False, "degraded", ("%d objects were not fully checked / cannot be judged (the self-intersection check was skipped or raised, shell orientation unknown)"
                                   " — not analyzed must not be read as pass" % _incomplete), _incomplete
    return False, "pass", "", _incomplete


def _mesh_slim_parts(parts):
    """summary_only=true returns criterion fields only (dropping the detail lists), for verifiers / the gate."""
    _keep = ("name", "verts", "polys", "tris", "boundary_edges", "nonmanifold_edges",
             "degenerate_faces", "loose_verts", "loose_edges", "closed", "normals_outward", "normals_state",
             "normals_shell_count", "self_intersections", "self_intersections_analyzed",
             "self_intersections_state", "self_intersections_same_island", "self_intersections_cross_island",
             "self_intersections_filtered_small_island", "self_intersections_kept", "islands",
             "signed_volume", "empty", "out_of_bounds", "state", "multi_shell", "state_detail")
    return [{k: v for k, v in p.items() if k in _keep} for p in parts]


def _mesh_payload(objs, parts, total, missing, env, summary_only, self_intersect):
    """Final receipt: verdict/reason/totals/aabb/note + slimming and hints."""
    bad, state, reason, _incomplete = _mesh_summary_state(total)
    mn, mx = _bounds(objs)
    slim = _mesh_slim_parts(parts) if summary_only else parts
    payload = {"ok": True, "clean": bool(not bad and state == "pass"), "state": state, "verdict": state,
               "reason": reason, "count": len(objs), "missing": missing,
               "totals": total, "objects": slim,
               "analysis": {"self_intersections": ("analyzed" if self_intersect else "skipped"),
                            "normals": ("unknown" if total.get("normals_unknown") else
                                        ("checked" if total.get("normals_checked") else "n/a")),
                            "incomplete_objects": _incomplete},
               "aabb": ({"min": [round(float(x), 4) for x in mn],
                         "max": [round(float(x), 4) for x in mx]} if mn else None),
               "envelope": ([[round(float(x), 4) for x in env[0]], [round(float(x), 4) for x in env[1]]]
                            if env else None),
               "note": "criterion: any non-zero among boundary/nonmanifold/degenerate/loose_verts/loose_edges/self_intersections/"
                       "normals_inverted/out_of_bounds/empty → clean=false and state=fail; "
                       "normals_outward is judged per **connected shell** (an aggregated signed volume is cancelled into a positive number by a big outward shell plus a small inverted one), "
                       "which only makes sense for closed meshes (given only when closed=true); when it cannot be judged, normals_state=unknown; "
                       "multi-shell with every shell's orientation verifiable gives normals_state=pass_multi_shell (not counted as degraded: fragment clusters / multi-shell set pieces are legitimate); "
                       "the self-intersection check being skipped (self_intersect=false) or raising ⇒ state=degraded, clean=false — no false pass"}
    if state == "degraded":
        payload["warn"] = "DEGRADED ≠ pass: " + reason
        if not self_intersect:
            payload["hint"] = "for a complete conclusion rerun with self_intersect=true (this gate's self-intersection check was explicitly skipped)"
    if summary_only:
        payload["slim"] = {"summary_only": True}
    elif len(_j(payload)) > 6000:
        payload["hint"] = ("the receipt is large (%d characters): to slim it use summary_only=true (criterion fields only), "
                           "or audit_scene(top_k=N) to look only at the dirtiest few" % len(_j(payload)))
    return payload


def audit_mesh(objects=None, scope=None, envelope=None, eps_area=1e-9, self_intersect=True,
               max_issues=20, min_dist=1e-6, summary_only=False,
               island_split=False, min_island_verts=0):
    """v0.9.6 (field feedback #1): with island_split=true the self-intersections are bucketed by **connected island** (same island / cross island),
    and with min_island_verts=N an intersection where either side belongs to an island of <N vertices is ignored — rivets/small hardware pressed into a host by process
    necessarily intersect, and that is benign; this bucket is exactly the attribution experiment done by hand in the field (most of the 1640 shoulder-armor pairs were of this kind)."""
    """Mesh audit of a single object / a set of objects. With envelope=[x0,y0,z0,x1,y1,z1] it reports out_of_bounds."""
    objs, missing, err = _pick(objects, scope)
    if err:
        return _j({"ok": False, "error": err})
    objs = [o for o in objs if o.type == "MESH"]
    if not objs:
        # ★ hard rule: 0 meshes must fail (the external report's "silent empty output")
        return _j({"ok": False, "error": "0 meshes among the audit targets", "objects": objects, "scope": scope,
                   "hint": "most likely the build ran empty: check the object/collection names, or run audit_scene first to see what is in the scene",
                   "missing": missing})
    err, env = _mesh_envelope(envelope)
    if err:
        return err
    total = _mesh_totals()
    parts = []
    for ob in objs:
        info = _mesh_object_info(ob, eps_area, self_intersect, max_issues, min_dist,
                                 island_split, min_island_verts, env)
        _mesh_totals_add(total, info)
        parts.append(info)
    return _j(_mesh_payload(objs, parts, total, missing, env, summary_only, self_intersect))

def audit_scene(envelope=None, limit=40, eps_area=1e-9, summary_only=False, top_k=None,
                self_intersect=False):
    """Whole-scene audit: first tells you "which objects are the dirtiest", then deep-dives with audit_mesh on demand.

    v0.9.6 (slimming): summary_only=true returns criterion fields only; top_k=N returns only the N dirtiest (defaults to limit).
    v0.9.6 (review fix): the self-intersection check **does not run by default** (keeping the performance contract of "one cheap screening"), but then the conclusion can only be
        **degraded** (clean=false) — "check skipped" must not read as "no problem". For a complete conclusion usable as a gate,
        pass self_intersect=true (runs the BVH self-intersection check on every object in the scene, cost proportional to face count).
    """
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        return _j({"ok": False, "error": "0 meshes in the scene (did the build run empty?)"})
    rows = []
    r = json.loads(audit_mesh(objects=[o.name for o in objs], envelope=envelope, eps_area=eps_area,
                              self_intersect=bool(self_intersect), max_issues=0))
    tot = r.get("totals", {})
    for info in r.get("objects", []):
        score = (info.get("boundary_edges") or 0) + 3 * (info.get("nonmanifold_edges") or 0) + \
                2 * (info.get("degenerate_faces") or 0) + 2 * (info.get("self_intersections") or 0) + \
                (info.get("loose_verts") or 0) + (info.get("loose_edges") or 0)
        rows.append({"name": info["name"], "tris": info["tris"], "boundary_edges": info.get("boundary_edges"),
                     "nonmanifold_edges": info.get("nonmanifold_edges"),
                     "degenerate_faces": info.get("degenerate_faces"), "closed": info.get("closed"),
                     "loose_verts": info.get("loose_verts"), "loose_edges": info.get("loose_edges"),
                     "self_intersections": info.get("self_intersections"),
                     "normals_outward": info.get("normals_outward"), "normals_state": info.get("normals_state"),
                     "state": info.get("state"), "score": score, "aabb": info.get("aabb")})
    rows.sort(key=lambda x: -x["score"])
    k = int(top_k) if top_k is not None else int(limit)
    rows_out = rows[:max(0, k)]
    # scene-level three-state: any object fail ⇒ fail; otherwise any "degraded" (including deliberately skipping the self-intersection check) ⇒ degraded; otherwise pass
    states = [x.get("state") for x in rows]
    if r.get("state") == "fail" or "fail" in states:
        state = "fail"
    elif (not self_intersect) or r.get("state") == "degraded" or "degraded" in states:
        state = "degraded"
    else:
        state = "pass"
    if summary_only:
        _keep = ("name", "score", "boundary_edges", "nonmanifold_edges", "degenerate_faces",
                 "loose_verts", "loose_edges", "self_intersections", "normals_outward", "normals_state",
                 "state", "tris", "closed")
        rows_out = [{kk: vv for kk, vv in row.items() if kk in _keep} for row in rows_out]
    reason = ""
    if state == "degraded":
        reason = ("the initial screening skipped the self-intersection check" if not self_intersect else "") + \
                 ("; " if not self_intersect else "") + \
                 ("%d objects cannot be judged (see worst[].normals_state/state)" % len([x for x in states if x == "degraded"])
                  if any(x == "degraded" for x in states) else "")
        reason = reason or "not fully checked"
    payload = {"ok": True, "count": len(objs), "totals": tot, "worst": rows_out,
               "clean": bool(r.get("clean") and state == "pass" and self_intersect),
               "state": state, "verdict": state, "reason": reason,
               "self_intersections_analyzed": bool(self_intersect), "aabb": r.get("aabb"),
               "slim": {"summary_only": bool(summary_only), "top_k": k, "rows_returned": len(rows_out)},
               "note": "worst is sorted by score=boundary+3*nonmanifold+2*degenerate+2*selfint+loose; "
                       "deep-dive with audit_mesh(objects=[...]); "
                       "this op does **not run the self-intersection check** by default ⇒ verdict=degraded (clean=false) —"
                       " for a complete conclusion usable as a gate pass self_intersect=true; when the receipt is too large add summary_only=true / top_k=N"}
    if state == "degraded":
        payload["warn"] = "DEGRADED ≠ pass: " + reason
    return _j(payload)


def _mat_sig(ob):
    """Material signature: node types + key input defaults (a coarse fingerprint to find "same-name forks")."""
    try:
        nt = ob.node_tree
        if nt is None:
            return "none"
        items = []
        for nd in sorted(nt.nodes, key=lambda n: n.name):
            key = str(nd.type) + ":" + str(getattr(nd, "blend_type", "")) + ":" + str(getattr(nd, "operation", ""))
            vals = []
            for inp in getattr(nd, "inputs", []) or []:
                dv = getattr(inp, "default_value", None)
                try:
                    if hasattr(dv, "__len__"):
                        vals.append(",".join("%.4f" % float(x) for x in dv))
                    else:
                        vals.append("%.4f" % float(dv))
                except Exception:
                    vals.append("-")
            items.append(key + "[" + "|".join(vals[:8]) + "]")
        return "|".join(items)[:600]
    except Exception:
        return "err"


def audit_duplicates(limit=30, top_k=None):
    """Same-name resource audit: groups forks such as Foo / Foo.001 and compares whether the content differs."""
    k = int(top_k) if top_k is not None else int(limit)
    import hashlib
    out = {"ok": True, "materials": [], "meshes": [],
           "note": "same-name forks are mostly caused by first-come-first-served overwrites; if the content differs, two different resources are being mixed"}
    # materials
    groups = {}
    for m in bpy.data.materials:
        base = str(m.name).split(".")[0]
        groups.setdefault(("m", base), []).append(m)
    for (kind, base), items in sorted(groups.items()):
        if len(items) < 2:
            continue
        sigs = {}
        for m in items:
            sigs.setdefault(_mat_sig(m), []).append(m.name)
        out["materials"].append({"base": base, "variants": [m.name for m in items], "distinct_signatures": len(sigs),
                                 "users": [int(m.users) for m in items]})
    # meshes
    g2 = {}
    for me in bpy.data.meshes:
        base = str(me.name).split(".")[0]
        g2.setdefault(base, []).append(me)
    for base, items in sorted(g2.items()):
        if len(items) < 2:
            continue
        sigs = {}
        for me in items:
            h = hashlib.md5()
            h.update(("%d/%d" % (len(me.vertices), len(me.polygons))).encode())
            for v in me.vertices[:2000]:
                h.update(("%.5f,%.5f,%.5f;" % (v.co[0], v.co[1], v.co[2])).encode())
            sigs.setdefault(h.hexdigest()[:12], []).append(me.name)
        out["meshes"].append({"base": base, "variants": [m.name for m in items], "distinct_signatures": len(sigs),
                              "users": [int(m.users) for m in items]})
    out["count"] = {"materials": len(out["materials"]), "meshes": len(out["meshes"])}
    # v0.9.6: limit/top_k used to be accepted but ignored (silently ineffective) — now they really take effect and the truncated total is reported
    for _key in ("materials", "meshes"):
        if len(out[_key]) > k:
            out[_key + "_total"] = len(out[_key])
            out[_key] = out[_key][:k]
    out["slim"] = {"top_k": k, "materials": len(out["materials"]), "meshes": len(out["meshes"])}
    out["ok"] = True
    return _j(out)


def purge_orphans():
    """Purge datablocks with users==0 (matching set: orphan lights/cameras/meshes/materials/images)."""
    removed = {}
    targets = [("lights", bpy.data.lights), ("cameras", bpy.data.cameras), ("meshes", bpy.data.meshes),
               ("materials", bpy.data.materials), ("images", bpy.data.images), ("node_groups", bpy.data.node_groups),
               ("collections", bpy.data.collections)]
    for name, coll in targets:
        n = 0
        for db in list(coll):
            try:
                if int(db.users) == 0:
                    coll.remove(db, do_unlink=True)
                    n += 1
            except Exception:
                pass
        if n:
            removed[name] = n
    return _j({"ok": True, "removed": removed, "total": sum(removed.values()),
               "left": {k: len(getattr(bpy.data, k)) for k, _ in targets}})


def audit_selftest():
    """Synthetic self-test: build a "known-dirty" mesh and check whether every count is honest."""
    me = bpy.data.meshes.new("DSH_AUDIT_SELFTEST")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)     # open mesh → has boundary edges
    bmesh.ops.create_cube(bm, size=0.5)                                  # closed cube
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("DSH_AUDIT_SELFTEST", me)
    bpy.context.scene.collection.objects.link(ob)
    try:
        r = json.loads(audit_mesh(objects=[ob.name], self_intersect=False))
        empty = json.loads(audit_mesh(objects=["NoSuchObject"]))
        return _j({"ok": True, "boundary_edges": r["totals"]["boundary_edges"],
                   "tris": r["totals"]["tris"], "clean": r["clean"],
                   "empty_must_fail": (empty.get("ok") is False),
                   "expect": "boundary_edges>0 (open mesh) and clean=false; audit_mesh(a nonexistent name) must be ok=false"})
    finally:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
            bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass
