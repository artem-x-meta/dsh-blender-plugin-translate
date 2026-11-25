# -*- coding: utf-8 -*-
"""Split from motion.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403



# ============================================================ URDF export

def _select_joints(joints):
    st = _store()
    if joints is None:
        ids = list(st["joints"])
    else:
        ids = [str(x) for x in _names(joints)]
        bad = [i for i in ids if i not in st["joints"]]
        if bad:
            return None, _j({"ok": False, "error": "there are unregistered joint ids", "unknown": bad,
                             "have": sorted(st["joints"])})
    recs = [st["joints"][i] for i in ids]
    return recs, None


def _group_conflicts(recs):
    """The same object appearing in several links = contradictory rigid-body ownership: URDF/USDA would count its geometry and mass twice → this must be blocked."""
    owner = {}
    for r in recs:
        for side in ("parent", "child"):
            lname = _link_name(r[side])
            for n in _names(r[side]):
                owner.setdefault(n, set()).add(lname)
    return {n: sorted(v) for n, v in owner.items() if len(v) > 1}


def _build_tree(recs, warnings):
    """Joint records → a single URDF tree (link = object group; degrade / drop edge / synthesize a fixed joint for orphans)."""
    links, edges, order = {}, {}, []
    for r in recs:
        pk, ck = _link_key(r["parent"]), _link_key(r["child"])
        for key in (pk, ck):
            if key not in links:
                links[key] = {"key": key, "names": list(key), "name": _link_name(key),
                              "frame": None, "joint": None}
        if ck in edges:
            warnings.append("link %s already has a parent joint (%s), skipping joint %s (URDF single-tree constraint)"
                            % (links[ck]["name"], edges[ck]["jid"], r["id"]))
            continue
        edges[ck] = {"jid": r["id"], "parent": pk, "child": ck, "rec": r}
        order.append(ck)
    if not links:
        return None
    # Root: a link with no parent joint
    roots = [k for k in links if k not in edges]
    if not roots:
        warnings.append("the joint graph is cyclic (no parentless link) → dropping one edge to break the cycle")
        drop = order[0]
        edges.pop(drop, None)
        roots = [k for k in links if k not in edges]
    root = sorted(roots, key=lambda k: links[k]["name"])[0]
    if len(roots) > 1:
        warnings.append("%d candidate roots (%s) → taking %s as the root; the rest are treated as unreachable below"
                        % (len(roots), ", ".join(links[k]["name"] for k in sorted(roots)), links[root]["name"]))
    # Reachability
    def _reach():
        seen = {root}
        q = [root]
        kids = {}
        for ck, e in edges.items():
            kids.setdefault(e["parent"], []).append(ck)
        while q:
            cur = q.pop(0)
            for c in kids.get(cur, []):
                if c not in seen:
                    seen.add(c)
                    q.append(c)
        return seen
    reach = _reach()
    guard = 0
    while len(reach) < len(links) and guard < len(links) + 2:
        guard += 1
        cand = sorted([k for k in links if k not in reach and k not in edges],
                      key=lambda k: links[k]["name"])
        if not cand:
            cand = sorted([k for k in links if k not in reach], key=lambda k: links[k]["name"])
            if cand:
                warnings.append("link %s is unreachable and carries a cyclic edge → dropping that edge to attach it to the root"
                                % links[cand[0]]["name"])
                edges.pop(cand[0], None)
                cand = [cand[0]]
        if not cand:
            break
        k = cand[0]
        warnings.append("link %s is unreachable from root %s → synthesized a fixed joint onto the root (URDF must be a single tree)"
                        % (links[k]["name"], links[root]["name"]))
        edges[k] = {"jid": "orphan_%s_fixed" % links[k]["name"], "parent": root, "child": k,
                    "rec": None, "synthesized": True}
        reach = _reach()
    # Frames: root = world origin, the rest = the joint anchor (with no anchor, fall back to the group's bbox centre)
    links[root]["frame"] = np.zeros(3).tolist()
    dgf = bpy.context.evaluated_depsgraph_get()
    for ck, e in edges.items():
        r = e["rec"]
        if r is not None and r.get("anchor"):
            links[ck]["frame"] = [float(x) for x in r["anchor"]]
            continue
        v, _f, _p = _group_tris(_objs(links[ck]["names"])[0], dgf)
        mn, mx, _d = _bbox(v)
        if mn is not None:
            links[ck]["frame"] = (((mn + mx) / 2.0).tolist())
            if r is not None:
                warnings.append("joint %s (kind=%s) has no anchor → the frame of link %s is the group's bbox centre "
                                "(%.4g, %.4g, %.4g) (the mesh is written relative to that frame)"
                                % (r["id"], r["kind"], links[ck]["name"], links[ck]["frame"][0],
                                   links[ck]["frame"][1], links[ck]["frame"][2]))
        else:
            links[ck]["frame"] = [0.0, 0.0, 0.0]
            warnings.append("link %s has neither a joint anchor nor geometry → frame is the world origin" % links[ck]["name"])
    return {"root": root, "links": links, "edges": edges, "reach": reach}


def _urdf_type(rec, warnings):
    k = str(rec["kind"]).lower()
    if k in ("revolute", "continuous", "prismatic", "fixed"):
        if k == "revolute" and not rec.get("limits"):
            warnings.append("joint %s is revolute but has no limits → exported as continuous"
                            " (URDF revolute requires lower/upper)" % rec["id"])
            return "continuous", None
        return k, None
    warnings.append("joint %s has kind=%s, degraded to fixed (URDF cannot express %s)" % (rec["id"], k, k))
    return "fixed", k


def _urdf_limits_attrs(utype, rec, fallback_travel_m, warnings):
    k = rec["kind"]
    if utype == "revolute":
        lo = float((rec.get("limits") or [0.0, 0.0])[0])
        hi = float((rec.get("limits") or [0.0, 0.0])[1])
        return ' lower="%s" upper="%s"' % (_fnum(math.radians(lo)), _fnum(math.radians(hi)))
    if utype == "prismatic":
        if rec.get("limits"):
            lo, hi = float(rec["limits"][0]), float(rec["limits"][1])
            return ' lower="%s" upper="%s"' % (_fnum(lo), _fnum(hi))
        warnings.append("joint %s is prismatic but has no limits → falling back to ±%s m of the model diagonal"
                        " (URDF without lower/upper reads as 0, which locks the degree of freedom)"
                        % (rec["id"], _fnum(fallback_travel_m)))
        return ' lower="%s" upper="%s"' % (_fnum(-fallback_travel_m), _fnum(fallback_travel_m))
    return ""


def _motion_export_urdf_p1(st):
    dir, fixed_base, joints, masses, mesh_format = (
        st["dir"], st["fixed_base"], st["joints"], st.get("masses"), st["mesh_format"])
    meters_per_unit, name = st["meters_per_unit"], st["name"]
    F, V, Vm, fn, fp, frame, k, mn, mx, objs, v = (st.get("F"), st.get("V"), st.get("Vm"), st.get("fn"), st.get("fp"), st.get("frame"), st.get("k"), st.get("mn"), st.get("mx"), st.get("objs"), st.get("v"))
    try:
        t0 = time.perf_counter()
        if not dir:
            return _j({"ok": False, "error": "dir is required (where the URDF and the meshes go)"})
        recs, err = _select_joints(joints)
        if err is not None:
            return _j(json.loads(err))
        if not recs:
            return _j({"ok": False, "error": "no joints to export (empty output must fail)",
                       "registered": sorted(_store()["joints"])})
        conf = _group_conflicts(recs)
        if conf:
            return _j({"ok": False, "error": "joint groups overlap: the same object belongs to several links (contradictory rigid-body ownership → "
                                            "geometry and mass would be counted twice) → make the parent/child groups of each joint non-overlapping",
                       "conflicts": conf, "units": {"length": "scene_unit"}})
        fmt = str(mesh_format or "obj").lower()
        if fmt not in ("obj", "stl"):
            return _j({"ok": False, "error": "mesh_format only supports obj / stl", "given": fmt})
        mpu = _mpu_arg(meters_per_unit)
        robot = _safe_name(name, "model")
        outdir = _win(dir)
        meshdir = os.path.join(outdir, "meshes")
        warnings = []
        try:
            os.makedirs(meshdir, exist_ok=True)
        except Exception as e:
            return _j({"ok": False, "error": "failed to create directory: %s: %s" % (type(e).__name__, e), "dir": outdir})

        tree = _build_tree(recs, warnings)
        if tree is None:
            return _j({"ok": False, "error": "the joint tree is empty (no links)"})
        links, edges, root = tree["links"], tree["edges"], tree["root"]
        dg = bpy.context.evaluated_depsgraph_get()
        masses = masses or {}

        # Fallback travel (m): the model bbox diagonal, lower bound 0.1 m
        allV = []
        for k, L in links.items():
            v, _f, _p = _group_tris(_objs(L["names"])[0], dg)
            if len(v):
                allV.append(v)
        fallback_travel_m = 0.1
        model_diag_m = 0.0
        if allV:
            mn, mx, _d = _bbox(np.concatenate(allV, axis=0))
            if mn is not None:
                model_diag_m = float(np.linalg.norm(mx - mn)) * mpu
                fallback_travel_m = max(0.1, model_diag_m)
        units_suspect = _units_warnings(mpu, model_diag_m, warnings)

        # One mesh per link (relative to the link frame, in m)
        mesh_files, link_geo = {}, {}
        for k, L in links.items():
            objs, _m, _n = _objs(L["names"])
            V, F, _parts = _group_tris(objs, dg)
            if len(V) == 0 or len(F) == 0:
                warnings.append("link %s has no triangles to export → that link has no visual/collision in the URDF" % L["name"])
                link_geo[k] = None
                continue
            frame = np.asarray(L["frame"] or [0.0, 0.0, 0.0], dtype=np.float64)
            Vm = (V - frame) * mpu
            fn = "%s.%s" % (L["name"], fmt)
            fp = os.path.join(meshdir, fn)
            try:
                if fmt == "obj":
                    _write_obj(fp, Vm, F, "DSH motion export: link %s / %d verts / %d tris / units m"
                                           % (L["name"], len(Vm), len(F)))
                else:
                    _write_stl(fp, Vm, F, "DSH motion link %s" % L["name"])
            except Exception as e:
                return _j({"ok": False, "error": "failed to write mesh %s: %s" % (fn, str(e)[:160])})
            mesh_files[k] = fn
            link_geo[k] = {"verts": int(len(Vm)), "tris": int(len(F)),
                           "min": _rl(Vm.min(axis=0), 6), "max": _rl(Vm.max(axis=0), 6),
                           "bytes": os.path.getsize(fp)}

        L = ['<?xml version="1.0" encoding="utf-8"?>',
             '<!-- DSH motion v%d export (pure string generation, SI units; bbox-approximated inertia) -->' % MOTION_VERSION,
             '<robot name="%s">' % _esc(robot)]
        if fixed_base:
            L.append('  <link name="world"/>')
            L.append('  <joint name="world_to_%s" type="fixed">' % _esc(links[root]["name"]))
            L.append('    <origin xyz="0 0 0" rpy="0 0 0"/>')
            L.append('    <parent link="world"/>')
            L.append('    <child link="%s"/>' % _esc(links[root]["name"]))
            L.append('  </joint>')
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _motion_export_urdf_p2(st):
    L, density, dg, edges, effort = st.get("L"), st["density"], st.get("dg"), st.get("edges"), st["effort"]
    fallback_travel_m, links, masses, mesh_files, meshdir = (
        st.get("fallback_travel_m"), st.get("links"), st.get("masses"), st.get("mesh_files"), st.get("meshdir"))
    mpu, note, outdir, robot, root = (
        st.get("mpu"), st["note"], st.get("outdir"), st.get("robot"), st.get("root"))
    velocity, warnings = st["velocity"], st.get("warnings")
    Lk, V, attrs, axis, cf, child, ck, com, dims, e, f, fn, frame, ixx, iyy, izz, jname, k, key, m_explicit, mass, mn, mx, org, parent, pf, r, tag, utype, vloc, vol = (st.get("Lk"), st.get("V"), st.get("attrs"), st.get("axis"), st.get("cf"), st.get("child"), st.get("ck"), st.get("com"), st.get("dims"), st.get("e"), st.get("f"), st.get("fn"), st.get("frame"), st.get("ixx"), st.get("iyy"), st.get("izz"), st.get("jname"), st.get("k"), st.get("key"), st.get("m_explicit"), st.get("mass"), st.get("mn"), st.get("mx"), st.get("org"), st.get("parent"), st.get("pf"), st.get("r"), st.get("tag"), st.get("utype"), st.get("vloc"), st.get("vol"))
    try:
        for k in sorted(links, key=lambda x: links[x]["name"]):
            Lk = links[k]
            V, F, _p = _group_tris(_objs(Lk["names"])[0], dg)
            frame = np.asarray(Lk["frame"] or [0.0, 0.0, 0.0], dtype=np.float64)
            dims, mass = [0.0, 0.0, 0.0], 0.0
            com = [0.0, 0.0, 0.0]
            if len(V):
                vloc = (V - frame) * mpu
                mn, mx = vloc.min(axis=0), vloc.max(axis=0)
                dims = (mx - mn).tolist()
                com = ((mn + mx) / 2.0).tolist()
                vol = max(0.0, dims[0] * dims[1] * dims[2])
                m_explicit = None
                for key in (Lk["name"],) + tuple(Lk["names"]):
                    if key in masses:
                        m_explicit = float(masses[key])
                        break
                mass = m_explicit if m_explicit is not None else float(density) * vol * BBOX_FILL_FACTOR
            ixx = max(MIN_INERTIA, mass / 12.0 * (dims[1] ** 2 + dims[2] ** 2))
            iyy = max(MIN_INERTIA, mass / 12.0 * (dims[0] ** 2 + dims[2] ** 2))
            izz = max(MIN_INERTIA, mass / 12.0 * (dims[0] ** 2 + dims[1] ** 2))
            if mass <= 0:
                warnings.append("link %s has zero mass (density %g × bbox volume × %.2f) → inertia clamped to %.0e"
                                % (Lk["name"], density, BBOX_FILL_FACTOR, MIN_INERTIA))
            L.append('  <link name="%s">' % _esc(Lk["name"]))
            L.append('    <inertial>')
            L.append('      <origin xyz="%s %s %s" rpy="0 0 0"/>' % tuple(_fnum(x) for x in com))
            L.append('      <mass value="%s"/>' % _fnum(mass))
            L.append('      <inertia ixx="%s" ixy="0" ixz="0" iyy="%s" iyz="0" izz="%s"/>'
                     % (_fnum(ixx), _fnum(iyy), _fnum(izz)))
            L.append('    </inertial>')
            fn = mesh_files.get(k)
            if fn:
                for tag in ("visual", "collision"):
                    L.append('    <%s>' % tag)
                    L.append('      <origin xyz="0 0 0" rpy="0 0 0"/>')
                    L.append('      <geometry>')
                    L.append('        <mesh filename="meshes/%s"/>' % _esc(fn))
                    L.append('      </geometry>')
                    L.append('    </%s>' % tag)
            else:
                warnings.append("link %s has no geometry: no visual/collision in the URDF" % Lk["name"])
            L.append('  </link>')
        for ck in sorted(edges, key=lambda x: links[x]["name"]):
            e = edges[ck]
            r = e["rec"]
            child = links[ck]
            parent = links[e["parent"]]
            pf = np.asarray(parent["frame"] or [0.0, 0.0, 0.0], dtype=np.float64)
            cf = np.asarray(child["frame"] or [0.0, 0.0, 0.0], dtype=np.float64)
            org = (cf - pf) * mpu
            if r is None:
                utype, degraded, jname = "fixed", None, e["jid"]
                axis = [0.0, 0.0, 1.0]
            else:
                utype, degraded = _urdf_type(r, warnings)
                jname = _safe_name(r["id"], "joint")
                axis = r.get("axis") or [0.0, 0.0, 1.0]
            L.append('  <joint name="%s" type="%s">' % (_esc(jname), utype))
            L.append('    <origin xyz="%s %s %s" rpy="0 0 0"/>' % tuple(_fnum(x) for x in org))
            L.append('    <parent link="%s"/>' % _esc(parent["name"]))
            L.append('    <child link="%s"/>' % _esc(child["name"]))
            if utype != "fixed":
                L.append('    <axis xyz="%s %s %s"/>' % tuple(_fnum(x) for x in axis))
                attrs = ""
                if r is not None:
                    attrs = _urdf_limits_attrs(utype, r, fallback_travel_m, warnings)
                L.append('    <limit%s effort="%s" velocity="%s"/>'
                         % (attrs, _fnum(effort), _fnum(velocity if utype != "prismatic" else velocity * mpu)))
            L.append('  </joint>')
        L.append('</robot>')
        text = "\n".join(L) + "\n"
        path = os.path.join(outdir, robot + ".urdf")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            return _j({"ok": False, "error": "failed to write URDF: %s: %s" % (type(e).__name__, e), "path": path})

        chk = _urdf_self_check(text, path, meshdir, mesh_files, root)
        rec_export = {"kind": "urdf", "path": path, "dir": outdir, "meshes": len(mesh_files),
                      "bytes": os.path.getsize(path), "links": len(links), "joints": len(edges),
                      "self_check_ok": chk["ok"], "warnings": len(warnings), "t": _now(),
                      "note": str(note)}
        _store()["exports"].append(rec_export)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _motion_export_urdf_p3(st):
    chk, edges, link_geo, links, mesh_files = (
        st.get("chk"), st.get("edges"), st.get("link_geo"), st.get("links"), st.get("mesh_files"))
    meshdir, model_diag_m, mpu, note, outdir = (
        st.get("meshdir"), st.get("model_diag_m"), st.get("mpu"), st["note"], st.get("outdir"))
    path, robot, root, t0, units_suspect = (
        st.get("path"), st.get("robot"), st.get("root"), st.get("t0"), st.get("units_suspect"))
    warnings = st.get("warnings")
    try:
        del _store()["exports"][:-50]
        _log("export_urdf", {"path": path, "links": len(links), "joints": len(edges),
                             "self_check_ok": chk["ok"]})
        if not chk["ok"]:
            return _j({"ok": False, "error": "URDF structural self-check failed (the product was written but is not valid)",
                       "path": path, "self_check": chk, "warnings": warnings})
        return _j({"ok": True, "op": "export_urdf", "path": path, "dir": outdir, "mesh_dir": meshdir,
                   "robot": robot, "root_link": links[root]["name"],
                   "links": [{"link": links[k]["name"], "objects": links[k]["names"],
                              "frame_m": _rl(np.asarray(links[k]["frame"] or [0, 0, 0]) * mpu, 6),
                              "mesh": mesh_files.get(k), "geo": link_geo.get(k)}
                             for k in sorted(links, key=lambda x: links[x]["name"])],
                   "joints": [{"joint": e["jid"], "type": (_urdf_type(e["rec"], [])[0] if e["rec"] else "fixed"),
                               "parent": links[e["parent"]]["name"], "child": links[e["child"]]["name"],
                               "synthesized": bool(e.get("synthesized")),
                               "degraded_from": (_urdf_type(e["rec"], [])[1] if e["rec"] else None)}
                              for e in [edges[c] for c in sorted(edges, key=lambda x: links[x]["name"])]],
                   "units": {"urdf": "SI (m / rad / kg / kg·m²)",
                             "meters_per_unit": mpu,
                             "model_diagonal_m": _r(model_diag_m, 6),
                             "scene_units_suspect": units_suspect,
                             "note": "scene units × meters_per_unit = meters; OBJ vertices are already meters;"
                                     "meters_per_unit may be \"scene\" to read scene.unit_settings.scale_length"},
                   "warnings": warnings, "self_check": chk,
                   "ms": int((time.perf_counter() - t0) * 1000), "note": str(note)})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def motion_export_urdf(dir=None, name="model", joints=None, meters_per_unit=0.001,
                       density=DEFAULT_DENSITY, masses=None, mesh_format="obj",
                       effort=DEFAULT_EFFORT, velocity=DEFAULT_VELOCITY, fixed_base=False, note=""):
    """Write <dir>/<name>.urdf + one mesh per link (OBJ) + warnings; run a structural self-check afterwards.

    Units: URDF output is SI (m / rad / kg / kg·m²); scene units are converted through meters_per_unit
          (default 0.001 = 1 scene unit = 1 mm, matching the upstream stage convention; pass 1.0 for metric scenes).
    Inertia: bbox approximation (centroid = bbox centre, box formula, fill factor BBOX_FILL_FACTOR=0.4, mass = volume × density).
    """
    st = dict(locals())
    for _fn_ in (_motion_export_urdf_p1, _motion_export_urdf_p2, _motion_export_urdf_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r


def _write_obj(path, V, F, header):
    lines = ["# " + header]
    for p in V:
        lines.append("v %.9g %.9g %.9g" % (float(p[0]), float(p[1]), float(p[2])))
    for t in F:
        lines.append("f %d %d %d" % (int(t[0]) + 1, int(t[1]) + 1, int(t[2]) + 1))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_stl(path, V, F, name):
    with open(path, "w", encoding="utf-8") as f:
        f.write("solid %s\n" % _safe_name(name))
        for t in F:
            a, b, c = V[int(t[0])], V[int(t[1])], V[int(t[2])]
            n = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(n))
            n = (n / ln) if ln > 1e-30 else np.zeros(3)
            f.write("  facet normal %.6g %.6g %.6g\n    outer loop\n" % (n[0], n[1], n[2]))
            for p in (a, b, c):
                f.write("      vertex %.9g %.9g %.9g\n" % (float(p[0]), float(p[1]), float(p[2])))
            f.write("    endloop\n  endfacet\n")
        f.write("endsolid %s\n" % _safe_name(name))


def _urdf_self_check(text, path, meshdir, mesh_files, root_key):
    problems = []
    chk = {"xml_parse": False, "link_names_unique": False, "joint_names_unique": False,
           "joint_endpoints_exist": False, "single_tree": False, "acyclic": False,
           "reachable_all": False, "mesh_files_exist": False,
           "counts": {"links": 0, "joints": 0, "meshes": len(mesh_files)},
           "problems": problems}
    try:
        root = ET.fromstring(text)
        chk["xml_parse"] = True
    except Exception as e:
        problems.append("XML parse failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        chk["ok"] = False
        return chk
    if root.tag != "robot":
        problems.append("root element is <%s>, not <robot>" % root.tag)
    lnames = [e.get("name") for e in root.findall("link")]
    jnames = [e.get("name") for e in root.findall("joint")]
    chk["counts"]["links"] = len(lnames)
    chk["counts"]["joints"] = len(jnames)
    chk["link_names_unique"] = (len(set(lnames)) == len(lnames))
    if not chk["link_names_unique"]:
        problems.append("duplicate link names")
    chk["joint_names_unique"] = (len(set(jnames)) == len(jnames))
    if not chk["joint_names_unique"]:
        problems.append("duplicate joint names")
    lset = set(lnames)
    ok_end = True
    kids, indeg = {}, {}
    for e in root.findall("joint"):
        pe = e.find("parent"); ce = e.find("child")
        p = pe.get("link") if pe is not None else None
        c = ce.get("link") if ce is not None else None
        if p not in lset or c not in lset:
            ok_end = False
            problems.append("parent/child of joint %s are not in the link list (%s → %s)" % (e.get("name"), p, c))
        else:
            kids.setdefault(p, []).append(c)
            indeg[c] = indeg.get(c, 0) + 1
    chk["joint_endpoints_exist"] = ok_end
    multi = [c for c, n in indeg.items() if n > 1]
    chk["single_tree"] = not multi
    if multi:
        problems.append("a link is the child of several joints (not a single tree): %s" % ", ".join(multi))
    start = None
    for n in lnames:
        if indeg.get(n, 0) == 0:
            start = n
            break
    seen, stack, cyclic = set(), list(kids.get(start, [])), False
    if start is not None:
        seen.add(start)
        while stack:
            cur = stack.pop()
            if cur in seen:
                cyclic = True
                break
            seen.add(cur)
            stack.extend(kids.get(cur, []))
    chk["acyclic"] = (start is not None) and (not cyclic)
    if start is None:
        problems.append("no parentless link (the root is not unique, or the graph is cyclic)")
    elif cyclic:
        problems.append("the joint tree contains a cycle")
    chk["reachable_all"] = bool(start is not None) and (len(seen) == len(lnames))
    if not chk["reachable_all"]:
        problems.append("links unreachable from root %s: %s"
                        % (start, ", ".join(sorted(lset - seen))))
    missing = []
    for fn in mesh_files.values():
        if not os.path.isfile(os.path.join(meshdir, fn)):
            missing.append(fn)
    chk["mesh_files_exist"] = not missing
    if missing:
        problems.append("mesh files are missing: %s" % ", ".join(missing))
    chk["root_link"] = start
    chk["ok"] = bool(chk["xml_parse"] and chk["link_names_unique"] and chk["joint_names_unique"]
                     and chk["joint_endpoints_exist"] and chk["single_tree"] and chk["acyclic"]
                     and chk["reachable_all"] and chk["mesh_files_exist"])
    return chk
