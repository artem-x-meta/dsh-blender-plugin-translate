# -*- coding: utf-8 -*-
"""Split from assembly.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _manifest_init(assembly=None, units="mm", coord=None):
    return {"schema": MANIFEST_SCHEMA, "units": str(units or "mm"),
            "coord": dict(coord or {"up": "Z", "forward": "-Y"}),
            "assembly": str(assembly or "unnamed-assembly"),
            "version": 1, "sealed": False, "sealed_md5": None,
            "parts": [], "interfaces": [], "allow_pairs": []}


def _load_manifest(src):
    """manifest = dict | JSON string | file path → (dict, error)."""
    if src is None or src == "":
        return None, "no manifest given (a dict / JSON string / .json path is required)"
    if isinstance(src, dict):
        try:
            return json.loads(json.dumps(src, default=str)), None
        except Exception as e:
            return None, "cannot deep-copy the manifest dict: %s: %s" % (type(e).__name__, str(e)[:160])
    s = str(src)
    if s.strip().startswith("{"):
        try:
            m = json.loads(s)
        except Exception as e:
            return None, "manifest JSON parse failed: %s: %s" % (type(e).__name__, str(e)[:160])
        return (m, None) if isinstance(m, dict) else (None, "the manifest must be a JSON object")
    p = _path(s)
    if not os.path.isfile(p):
        return None, "manifest file does not exist: %s" % p
    try:
        with open(p, "r", encoding="utf-8") as fh:
            m = json.load(fh)
    except Exception as e:
        return None, "manifest read failed: %s: %s" % (type(e).__name__, str(e)[:160])
    return (m, None) if isinstance(m, dict) else (None, "the manifest file content must be a JSON object")


def _manifest_md5(m):
    """Manifest content fingerprint (canonical JSON, excluding the two self-referencing fields manifest_md5 / sealed_md5)."""
    if not isinstance(m, dict):
        return None
    d = {k: v for k, v in m.items() if k not in ("manifest_md5", "sealed_md5")}
    return _md5_text(_canon(d))


def _write_json(path, obj):
    p = _path(path)
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, p)
    return p


def _manifest_counts(m):
    return {"parts": len(m.get("parts") or []), "interfaces": len(m.get("interfaces") or []),
            "allow_pairs": len(m.get("allow_pairs") or [])}


def _validate_frame(fr, pid, fid, E, W):
    origin = fr.get("origin_mm")
    if origin is not None:
        if not isinstance(origin, (list, tuple)) or len(origin) != 3 or any(_num(x) is None for x in origin):
            E("FRAME_BAD_ORIGIN", "part %s frame %s: origin_mm must be 3 numbers" % (pid, fid), pid)
    normal = fr.get("normal")
    if normal is None:
        W("FRAME_NO_NORMAL", "part %s frame %s: no normal, the interface orientation is undefined" % (pid, fid), pid)
    else:
        if not isinstance(normal, (list, tuple)) or len(normal) != 3 or any(_num(x) is None for x in normal):
            E("FRAME_BAD_NORMAL", "part %s frame %s: normal must be 3 numbers" % (pid, fid), pid)
        elif float(np.linalg.norm(np.array([float(x) for x in normal]))) < 1e-9:
            E("FRAME_BAD_NORMAL", "part %s frame %s: normal has length 0" % (pid, fid), pid)
    basis = fr.get("basis")
    if basis is None:
        W("FRAME_NO_BASIS", "part %s frame %s: no basis (x/y), the rotation around the normal is undetermined" % (pid, fid), pid)
        return
    try:
        if isinstance(basis, dict):
            bx, by = basis.get("x"), basis.get("y")
        elif isinstance(basis, (list, tuple)) and len(basis) >= 2:
            bx, by = basis[0], basis[1]
        else:
            raise ValueError("unrecognized basis shape")
        bx = np.array([float(x) for x in bx], dtype=np.float64)
        by = np.array([float(x) for x in by], dtype=np.float64)
        if bx.shape != (3,) or by.shape != (3,):
            raise ValueError("x/y must be 3 numbers")
    except Exception as e:
        E("FRAME_BAD_BASIS", "part %s frame %s: basis is invalid (%s)" % (pid, fid, str(e)[:100]), pid)
        return
    nx, ny = float(np.linalg.norm(bx)), float(np.linalg.norm(by))
    if abs(nx - 1.0) > 1e-3 or abs(ny - 1.0) > 1e-3:
        E("FRAME_BASIS_NOT_UNIT", "part %s frame %s: basis is not a unit vector (|x|=%.6f |y|=%.6f)"
          % (pid, fid, nx, ny), pid)
    dot = float(np.dot(bx, by))
    if abs(dot) > 1e-3:
        E("FRAME_BASIS_NOT_ORTHOGONAL", "part %s frame %s: basis x·y=%.6f (expected ≈0)" % (pid, fid, dot), pid)
    if normal is not None:
        try:
            nrm = np.array([float(x) for x in normal], dtype=np.float64)
            z = np.cross(bx, by)
            zn = float(np.linalg.norm(z))
            if zn > 1e-9:
                cosang = float(np.dot(z / zn, nrm / max(1e-12, float(np.linalg.norm(nrm)))))
                if cosang < 0.9:
                    W("FRAME_NORMAL_MISMATCH",
                      "part %s frame %s: normal disagrees with the basis cross-product direction (cos=%.3f); merge alignment may be off by 180°"
                      % (pid, fid, cosang), pid)
        except Exception:
            pass
def _manifest_validate_p1(st):
    m, mmu = st["m"], st.get("mmu")
    try:
        errors, warnings = [], []

        def E(code, msg, path=None):
            errors.append({"code": str(code), "msg": str(msg)[:400], "path": (str(path) if path is not None else None)})

        def W(code, msg, path=None):
            warnings.append({"code": str(code), "msg": str(msg)[:400], "path": (str(path) if path is not None else None)})

        if not isinstance(m, dict):
            E("BAD_MANIFEST", "the manifest must be a JSON object")
            return {"ok": False, "verdict": "fail", "errors": errors, "warnings": warnings,
                    "manifest_md5": None, "counts": {"parts": 0, "interfaces": 0, "allow_pairs": 0}}
        mmu = float(mmu if mmu is not None else _KIT.units())
        schema = m.get("schema")
        if schema is None:
            W("NO_SCHEMA", "the manifest has no schema (suggested %s)" % MANIFEST_SCHEMA)
        elif str(schema) != MANIFEST_SCHEMA:
            W("SCHEMA_MISMATCH", "schema=%r ≠ %s (validating on a best-effort v1 basis)" % (schema, MANIFEST_SCHEMA))
        units = str(m.get("units") or "mm")
        conv = UNIT_MM_PER_UNIT.get(units)
        if conv is None:
            E("BAD_UNITS", "units only supports mm/cm/m, got %r" % units)
        elif abs(mmu - conv) / conv > 0.01:
            W("UNIT_SCALE_SUSPECT",
              "manifest units=%s ⇒ expected 1 unit=%.3g mm, measured %.6g mm (set scene.unit_settings.scale_length "
              "to %.6g; otherwise every loc_mm/depth is read in the wrong unit)" % (units, conv, mmu, conv / 1000.0))

        parts = m.get("parts")
        if parts is None:
            parts = []
        if not isinstance(parts, list):
            E("PARTS_NOT_LIST", "parts must be an array")
            parts = []
        ids, by_id, frames_by_part = set(), {}, {}
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _manifest_validate_p2(st):
    E, W, by_id, check_files, check_md5 = (
        st.get("E"), st.get("W"), st.get("by_id"), st["check_files"], st["check_md5"])
    frames_by_part, ids, m, parts = st.get("frames_by_part"), st.get("ids"), st["m"], st.get("parts")
    f, fid, fids, fp, fr, frames, got, i, k, p, pid, tr, v, want = (st.get("f"), st.get("fid"), st.get("fids"), st.get("fp"), st.get("fr"), st.get("frames"), st.get("got"), st.get("i"), st.get("k"), st.get("p"), st.get("pid"), st.get("tr"), st.get("v"), st.get("want"))
    try:
        for i, p in enumerate(parts):
            if not isinstance(p, dict):
                E("BAD_PART", "parts[%d] is not an object" % i)
                continue
            pid = str(p.get("id") or "")
            if not pid:
                E("MISSING_PART_ID", "parts[%d] has no id" % i)
                continue
            if pid in ids:
                E("DUP_ID", "duplicate part id: %s" % pid, pid)
                continue
            ids.add(pid)
            by_id[pid] = p
            fp = p.get("file")
            if not fp:
                W("MISSING_FILE", "part %s has no file (usable only as a pure data manifest; merge skips it)" % pid, pid)
            else:
                f = _path(fp)
                if check_files and not os.path.isfile(f):
                    E("MISSING_FILE", "the file of part %s does not exist: %s" % (pid, f), pid)
                elif check_md5 and os.path.isfile(f):
                    want = str(p.get("file_md5") or "").lower()
                    if not want:
                        W("MISSING_FILE_MD5", "part %s has no file_md5, the file cannot be verified" % pid, pid)
                    else:
                        got = _sha256_file(f)
                        if got is None:
                            W("FILE_UNREADABLE", "the file of part %s cannot be read: %s" % (pid, f), pid)
                        elif got != want:
                            E("MD5_MISMATCH", "part %s file md5 mismatch (manifest=%s… measured=%s…)"
                              % (pid, want[:12], got[:12]), pid)
            tr = p.get("transform")
            if tr is not None:
                if not isinstance(tr, dict):
                    E("BAD_TRANSFORM", "part %s transform must be an object" % pid, pid)
                else:
                    for k in ("loc_mm", "rot_euler_deg", "scale"):
                        if k not in tr:
                            continue
                        v = tr.get(k)
                        if not isinstance(v, (list, tuple)) or len(v) != 3 or any(_num(x) is None for x in v):
                            E("BAD_TRANSFORM", "part %s transform.%s must be 3 numbers" % (pid, k), pid)
                            continue
                        if k == "scale" and any(float(x) <= 0.0 for x in v):
                            E("BAD_TRANSFORM", "part %s transform.scale must be > 0" % pid, pid)
            frames = p.get("interface_frames")
            fids = set()
            if frames is not None:
                if not isinstance(frames, list):
                    E("BAD_FRAMES", "part %s interface_frames must be an array" % pid, pid)
                else:
                    for fr in frames:
                        if not isinstance(fr, dict):
                            E("BAD_FRAME", "part %s has an interface_frame that is not an object" % pid, pid)
                            continue
                        fid = str(fr.get("id") or "")
                        if not fid:
                            E("MISSING_FRAME_ID", "part %s has an interface_frame without an id" % pid, pid)
                            continue
                        if fid in fids:
                            W("FRAME_ID_DUP", "duplicate frame id on part %s: %s" % (pid, fid), pid)
                            continue
                        fids.add(fid)
                        _validate_frame(fr, pid, fid, E, W)
            frames_by_part[pid] = fids

        interfaces = m.get("interfaces") or []
        if not isinstance(interfaces, list):
            E("INTERFACES_NOT_LIST", "interfaces must be an array")
            interfaces = []
        iids, iface_ids = set(), set()
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _manifest_validate_p3(st):
    E, W, by_id, conv, errors = st.get("E"), st.get("W"), st.get("by_id"), st.get("conv"), st.get("errors")
    frames_by_part, iface_ids, iids, interfaces, m = (
        st.get("frames_by_part"), st.get("iface_ids"), st.get("iids"), st.get("interfaces"), st["m"])
    mmu, units, warnings = st.get("mmu"), st.get("units"), st.get("warnings")
    a, aid, ap, b, fa, fb, fit, got, i, iid, it, k, md_, mv, nv, ref, v, want = (st.get("a"), st.get("aid"), st.get("ap"), st.get("b"), st.get("fa"), st.get("fb"), st.get("fit"), st.get("got"), st.get("i"), st.get("iid"), st.get("it"), st.get("k"), st.get("md_"), st.get("mv"), st.get("nv"), st.get("ref"), st.get("v"), st.get("want"))
    try:
        for i, it in enumerate(interfaces):
            if not isinstance(it, dict):
                E("BAD_INTERFACE", "interfaces[%d] is not an object" % i)
                continue
            iid = str(it.get("id") or "")
            if not iid:
                W("MISSING_INTERFACE_ID", "interfaces[%d] has no id" % i)
                iid = "IF#%d" % i
            if iid in iids:
                E("DUP_ID", "duplicate interface id: %s" % iid, iid)
                continue
            iids.add(iid)
            iface_ids.add(iid)
            a, b = str(it.get("a") or ""), str(it.get("b") or "")
            if a not in by_id:
                E("CONN_UNKNOWN_PART", "interface %s: side a=%r is not in parts" % (iid, a), iid)
            if b not in by_id:
                E("CONN_UNKNOWN_PART", "interface %s: side b=%r is not in parts" % (iid, b), iid)
            if a and a == b:
                E("SELF_INTERFACE", "both sides of interface %s are the same part: %s" % (iid, a), iid)
            fa, fb = it.get("frame_a"), it.get("frame_b")
            if fa is not None and a in frames_by_part and str(fa) not in frames_by_part[a]:
                E("FRAME_NOT_FOUND", "interface %s: side a=%s has no frame %r" % (iid, a, fa), iid)
            if fb is not None and b in frames_by_part and str(fb) not in frames_by_part[b]:
                E("FRAME_NOT_FOUND", "interface %s: side b=%s has no frame %r" % (iid, b, fb), iid)
            fit = it.get("fit")
            if fit is not None and str(fit) not in FIT_CLASSES:
                W("UNKNOWN_FIT", "interface %s: fit=%r is not one of %s (handled with the location criterion)"
                  % (iid, fit, list(FIT_CLASSES)), iid)
            for k in ("nominal_mm", "tol_mm", "allow_overlap_mm", "clearance_min_mm"):
                v = it.get(k)
                if v is None:
                    continue
                nv = _num(v)
                if nv is None or nv < 0:
                    E("BAD_INTERFACE_NUM", "interface %s: %s must be a non-negative number" % (iid, k), iid)

        allow = m.get("allow_pairs") or []
        if not isinstance(allow, list):
            E("ALLOW_NOT_LIST", "allow_pairs must be an array")
            allow = []
        aids = set()
        for i, ap in enumerate(allow):
            if not isinstance(ap, dict):
                E("BAD_ALLOW", "allow_pairs[%d] is not an object" % i)
                continue
            aid = str(ap.get("id") or "")
            if not aid:
                W("MISSING_ALLOW_ID", "allow_pairs[%d] has no id" % i)
                aid = "ALLOW#%d" % i
            if aid in aids:
                E("DUP_ID", "duplicate allow id: %s" % aid, aid)
                continue
            aids.add(aid)
            a, b = str(ap.get("a") or ""), str(ap.get("b") or "")
            if a not in by_id:
                E("ALLOW_UNKNOWN_PART", "allow %s: side a=%r is not in parts" % (aid, a), aid)
            if b not in by_id:
                E("ALLOW_UNKNOWN_PART", "allow %s: side b=%r is not in parts" % (aid, b), aid)
            ref = ap.get("interface")
            if ref is not None and str(ref) not in iface_ids:
                W("ALLOW_UNKNOWN_CONN", "allow %s: references a non-existent interface %r" % (aid, ref), aid)
            md_ = _num(ap.get("max_depth_mm"))
            mv = _num(ap.get("max_volume_mm3"))
            if md_ is None and mv is None:
                E("ALLOW_NO_LIMIT", "allow %s: max_depth_mm or max_volume_mm3 is required (an allowed overlap with no cap is a dangerous default)" % aid, aid)
            for k, nv in (("max_depth_mm", md_), ("max_volume_mm3", mv)):
                if nv is not None and nv < 0:
                    E("BAD_ALLOW_NUM", "allow %s: %s must be ≥ 0" % (aid, k), aid)

        sealed = bool(m.get("sealed"))
        if sealed:
            want = str(m.get("sealed_md5") or "")
            got = _manifest_md5(m)
            if want and got and want != got:
                E("MANIFEST_SEAL_MISMATCH", "the manifest was modified after seal (sealed_md5=%s… measured=%s…)"
                  % (want[:12], got[:12]))
        return {"ok": not errors, "verdict": "pass" if not errors else "fail",
                "errors": errors, "warnings": warnings, "manifest_md5": _manifest_md5(m),
                "sealed": sealed, "counts": _manifest_counts(m),
                "units": {"manifest_units": units, "mm_per_unit_scene": _r(mmu, 6),
                          "expected_mm_per_unit": conv}}
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _manifest_validate(m, check_files=False, check_md5=False, mmu=None):
    """Manifest validation → {ok, verdict, errors[], warnings[], manifest_md5, counts, units}.

    Checks: unique ids / file exists / file_md5 / both interface sides exist (including frame) / basis orthogonal / units consistent / seal integrity.
    check_files / check_md5 default to off (gate only looks at the structure; the validate action turns them on by default).
    """
    st = dict(locals())
    for _fn_ in (_manifest_validate_p1, _manifest_validate_p2, _manifest_validate_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r
def _obj_part_map(manifest, names):
    """Scene object name → part id: an explicit objects list / the same name / the merged-name <partid>__ prefix."""
    out = {}
    if not isinstance(manifest, dict):
        return out
    for p in manifest.get("parts") or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if not pid:
            continue
        for o in _as_list(p.get("objects")):
            out[str(o)] = pid
        for n in names:
            if n == pid or n.startswith(pid + "__"):
                out[str(n)] = pid
    return out


def _effective_spec(manifest, spec):
    """Merge manifest + spec into the allowlist: allow / clearance / interfaces."""
    sp = dict(spec) if isinstance(spec, dict) else {}
    allow = [dict(x) for x in (sp.get("allow") or []) if isinstance(x, dict)]
    clearance = [dict(x) for x in (sp.get("clearance") or []) if isinstance(x, dict)]
    interfaces = [dict(x) for x in (sp.get("interfaces") or []) if isinstance(x, dict)]
    if isinstance(manifest, dict):
        for x in manifest.get("interfaces") or []:
            if isinstance(x, dict):
                interfaces.append(dict(x))
        for ap in manifest.get("allow_pairs") or []:
            if isinstance(ap, dict):
                allow.append(dict(ap))
        for it in manifest.get("interfaces") or []:
            if not isinstance(it, dict):
                continue
            ov = _num(it.get("allow_overlap_mm"))
            if ov is not None and ov > 0:
                allow.append({"id": "IF-ALLOW-%s" % it.get("id"), "a": it.get("a"), "b": it.get("b"),
                              "max_depth_mm": ov, "max_volume_mm3": None,
                              "reason": "interface %s has allow_overlap_mm=%.4g" % (it.get("id"), ov),
                              "interface": it.get("id")})
    return {"allow": allow, "clearance": clearance, "interfaces": interfaces,
            "micro_gap_mm": _num(sp.get("micro_gap_mm"))}


def _allow_match(allow_list, obj_part, na, nb):
    """An allow entry's a/b can be an object name or a part id (including the merged prefix <partid>__)."""
    for ent in allow_list or []:
        ea, eb = str(ent.get("a") or ""), str(ent.get("b") or "")
        if not ea or not eb:
            continue

        def _hit(name, side):
            return name == side or obj_part.get(name) == side

        if (_hit(na, ea) and _hit(nb, eb)) or (_hit(na, eb) and _hit(nb, ea)):
            return ent
    return None
def _asm_manifest_p1(st):
    action, assembly, check_files, check_md5, coord = (
        st["action"], st["assembly"], st["check_files"], st["check_md5"], st["coord"])
    force, manifest, note, path, units = st["force"], st["manifest"], st["note"], st["path"], st["units"]
    d, k, p, val = (st.get("d"), st.get("k"), st.get("p"), st.get("val"))
    try:
        t0 = time.perf_counter()
        act = str(action or "show").strip().lower()
        if act == "init":
            m = _manifest_init(assembly, units, coord)
            if isinstance(manifest, dict):
                for k in ("schema", "assembly", "units", "coord", "parts", "interfaces", "allow_pairs"):
                    if k in manifest:
                        m[k] = manifest[k]
            if note:
                m["note"] = str(note)
            if not path:
                return _j(_receipt({"ok": True, "action": "init", "manifest": m,
                                    "manifest_md5": _manifest_md5(m), "path": None,
                                    "note": "no path given ⇒ only the skeleton is returned, nothing was written to disk"}, t0))
            if os.path.isfile(_path(path)) and not force:
                return _err("the manifest already exists, refusing to overwrite (only force=true overwrites): %s" % _path(path))
            val = _manifest_validate(m, check_files=False, check_md5=False)
            if not val["ok"]:
                return _err("init manifest self-validation failed", errors=val["errors"], warnings=val["warnings"])
            try:
                p = _write_json(path, m)
            except Exception as e:
                return _err("manifest write failed: %s: %s" % (type(e).__name__, str(e)[:160]))
            return _j(_receipt({"ok": True, "action": "init", "path": p, "manifest_md5": _manifest_md5(m),
                                "counts": _manifest_counts(m), "warnings": val["warnings"],
                                "next": "add_part → add_interface → add_allow(optional) → validate → seal"}, t0))
        src = manifest if manifest is not None else path
        m, merr = _load_manifest(src)
        if merr:
            return _err(merr)
        if act == "validate":
            val = _manifest_validate(m, check_files=bool(check_files), check_md5=bool(check_md5))
            d = {"ok": bool(val["ok"]), "action": "validate", "verdict": val["verdict"],
                 "path": _path(path) if path else None, "manifest_md5": val["manifest_md5"],
                 "errors": val["errors"], "warnings": val["warnings"],
                 "counts": val["counts"], "sealed": val["sealed"], "units": val["units"]}
            if not val["ok"]:
                d["hint"] = "fix the errors first; while the manifest itself is invalid, merge/gate refuse to give a verdict"
            return _j(_receipt(d, t0))
        if act == "show":
            val = _manifest_validate(m, check_files=False, check_md5=False)
            return _j(_receipt({"ok": bool(val["ok"]), "action": "show", "path": _path(path) if path else None,
                                "manifest": m, "manifest_md5": _manifest_md5(m),
                                "counts": _manifest_counts(m), "sealed": bool(m.get("sealed")),
                                "validation": {"verdict": val["verdict"],
                                               "errors": val["errors"][:20], "warnings": val["warnings"][:20]}},
                               t0))
        if act not in ("add_part", "add_interface", "add_allow", "seal"):
            return _err("unknown action: %s (supported: init|add_part|add_interface|add_allow|validate|seal|show)" % act)
        if not path:
            return _err("action=%s requires path (it writes back to the manifest file)" % act)
        if act == "seal":
            val = _manifest_validate(m, check_files=bool(check_files), check_md5=bool(check_md5))
            if not val["ok"]:
                return _err("seal refused: the manifest still has %d errors, fix them first" % len(val["errors"]),
                            errors=val["errors"][:20], warnings=val["warnings"][:20])
            if m.get("sealed") and not force:
                return _err("the manifest is already sealed (only force=true reseals)", sealed_md5=m.get("sealed_md5"))
            try:
                m["version"] = int(m.get("version") or 0) + 1
            except Exception:
                m["version"] = 2
            m["sealed"] = True
            m["sealed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            m["sealed_md5"] = _manifest_md5(m)
            if note:
                m["note"] = str(note)
            try:
                p = _write_json(path, m)
            except Exception as e:
                return _err("seal write failed: %s: %s" % (type(e).__name__, str(e)[:160]))
            return _j(_receipt({"ok": True, "action": "seal", "path": p, "sealed": True,
                                "version": m["version"], "sealed_md5": m["sealed_md5"],
                                "manifest_md5": _manifest_md5(m), "counts": _manifest_counts(m)}, t0))
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _asm_manifest_p2(st):
    act, allow, allow_pair, compute_md5, interface = (
        st.get("act"), st["allow"], st["allow_pair"], st["compute_md5"], st["interface"])
    interfaces, m, part, path, t0 = st["interfaces"], st.get("m"), st["part"], st["path"], st.get("t0")
    f, fp, got, it, p, pid, src_item, wp = (st.get("f"), st.get("fp"), st.get("got"), st.get("it"), st.get("p"), st.get("pid"), st.get("src_item"), st.get("wp"))
    try:
        if act == "add_part":
            p = dict(part) if isinstance(part, dict) else None
            if p is None:
                return _err("add_part needs part={id,file,objects,transform,interface_frames}")
            pid = str(p.get("id") or "")
            if not pid:
                return _err("part.id is required")
            if any(isinstance(x, dict) and str(x.get("id")) == pid for x in (m.get("parts") or [])):
                return _err("duplicate part id: %s" % pid)
            fp = p.get("file")
            if not fp:
                return _err("part.file is required (merge needs to know what to append from)")
            f = _path(fp)
            if not os.path.isfile(f):
                return _err("part.file does not exist: %s" % f)
            if compute_md5 or not p.get("file_md5"):
                got = _sha256_file(f)
                if got is None:
                    return _err("part.file cannot be read, so md5 cannot be computed: %s" % f)
                p["file_md5"] = got
            p.setdefault("transform", {"loc_mm": [0, 0, 0], "rot_euler_deg": [0, 0, 0], "scale": [1, 1, 1]})
            m.setdefault("parts", []).append(p)
            val = _manifest_validate(m, check_files=True, check_md5=False)
            if not val["ok"]:
                m["parts"].pop()
                return _err("add_part validation failed (nothing written)", errors=val["errors"][:20], warnings=val["warnings"][:20])
            try:
                wp = _write_json(path, m)
            except Exception as e:
                return _err("manifest write failed: %s: %s" % (type(e).__name__, str(e)[:160]))
            return _j(_receipt({"ok": True, "action": "add_part", "part": pid, "path": wp,
                                "file_md5": p.get("file_md5"), "manifest_md5": _manifest_md5(m),
                                "counts": _manifest_counts(m), "warnings": val["warnings"][:20]}, t0))
        if act == "add_interface":
            items = []
            if isinstance(interfaces, dict):
                items.append(dict(interfaces))
            elif isinstance(interfaces, (list, tuple)):
                items.extend([dict(x) for x in interfaces if isinstance(x, dict)])
            if isinstance(interface, dict):
                items.append(dict(interface))
            if not items:
                return _err("add_interface needs interface={id,a,b,frame_a,frame_b,fit,nominal_mm,tol_mm,allow_overlap_mm}")
            cur = m.setdefault("interfaces", [])
            added = []
            for it in items:
                it.setdefault("id", "IF-%d" % (len(cur) + 1))
                if any(isinstance(x, dict) and str(x.get("id")) == str(it.get("id")) for x in cur):
                    return _err("duplicate interface id: %s" % it.get("id"))
                cur.append(it)
                added.append(str(it.get("id")))
            val = _manifest_validate(m, check_files=True, check_md5=False)
            if not val["ok"]:
                for _ in added:
                    cur.pop()
                return _err("add_interface validation failed (nothing written)", errors=val["errors"][:20], warnings=val["warnings"][:20])
            try:
                wp = _write_json(path, m)
            except Exception as e:
                return _err("manifest write failed: %s: %s" % (type(e).__name__, str(e)[:160]))
            return _j(_receipt({"ok": True, "action": "add_interface", "added": added, "path": wp,
                                "manifest_md5": _manifest_md5(m), "counts": _manifest_counts(m),
                                "warnings": val["warnings"][:20]}, t0))
        # add_allow
        items = []
        for src_item in (allow, allow_pair):
            if isinstance(src_item, dict):
                items.append(dict(src_item))
            elif isinstance(src_item, (list, tuple)):
                items.extend([dict(x) for x in src_item if isinstance(x, dict)])
        if not items:
            return _err("add_allow needs allow={a,b,max_depth_mm,max_volume_mm3,reason} (or a list)")
        cur = m.setdefault("allow_pairs", [])
        added = []
        for it in items:
            it.setdefault("id", "ALLOW-%d" % (len(cur) + 1))
            if any(isinstance(x, dict) and str(x.get("id")) == str(it.get("id")) for x in cur):
                return _err("duplicate allow id: %s" % it.get("id"))
            cur.append(it)
            added.append(str(it.get("id")))
        val = _manifest_validate(m, check_files=True, check_md5=False)
        if not val["ok"]:
            for _ in added:
                cur.pop()
            return _err("add_allow validation failed (nothing written)", errors=val["errors"][:20], warnings=val["warnings"][:20])
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _asm_manifest_p3(st):
    added, m, path, t0, val = st.get("added"), st.get("m"), st["path"], st.get("t0"), st.get("val")
    wp = (st.get("wp"))
    try:
        try:
            wp = _write_json(path, m)
        except Exception as e:
            return _err("manifest write failed: %s: %s" % (type(e).__name__, str(e)[:160]))
        return _j(_receipt({"ok": True, "action": "add_allow", "added": added, "path": wp,
                            "manifest_md5": _manifest_md5(m), "counts": _manifest_counts(m),
                            "warnings": val["warnings"][:20]}, t0))
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def asm_manifest(action="show", path=None, assembly=None, units="mm", coord=None, part=None,
                 interfaces=None, interface=None, allow=None, allow_pair=None,
                 manifest=None, force=False, compute_md5=True, check_files=True, check_md5=True,
                 note=None):
    """Part manifest: init | add_part | add_interface | add_allow | validate | seal | show."""
    st = dict(locals())
    for _fn_ in (_asm_manifest_p1, _asm_manifest_p2, _asm_manifest_p3):
        _r = _fn_(st)
        if _r is not None:
            return _r
