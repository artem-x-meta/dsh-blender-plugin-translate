# -*- coding: utf-8 -*-
"""Split from deliver.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .export import deliver_export

# ---------------------------------------------------------------- read-back self-check

def _dv_scan_obj(path):
    """Read an OBJ back and count for ourselves: f (triangles) / g / usemtl line count and unique material names / v / vn + **recompute the bbox from the v lines**."""
    n_f = n_g = n_u = n_v = n_vn = 0
    u_names = set()
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("f "):
                n_f += 1
            elif line.startswith("g "):
                n_g += 1
            elif line.startswith("usemtl "):
                n_u += 1
                u_names.add(line[7:].strip())
            elif line.startswith("v "):
                n_v += 1
                try:
                    a = line.split()
                    for i in range(3):
                        x = float(a[i + 1])
                        if x < lo[i]:
                            lo[i] = x
                        if x > hi[i]:
                            hi[i] = x
                except Exception:
                    pass
            elif line.startswith("vn "):
                n_vn += 1
    out = {"triangles": n_f, "groups": n_g, "usemtl": n_u, "usemtl_unique": len(u_names),
           "vertices": n_v, "normals": n_vn}
    if n_v:
        out["bbox_min"] = [_dv_r(x) for x in lo]
        out["bbox_max"] = [_dv_r(x) for x in hi]
        out["longest_edge"] = _dv_r(max(hi[i] - lo[i] for i in range(3)))
    return out


def _dv_scan_stl(path):
    """Read a binary STL back: 80-byte header + uint32 triangle count; also recompute the bbox from the vertex floats (the check bites into the file itself)."""
    b = os.path.getsize(path)
    lo = [1e30, 1e30, 1e30]
    hi = [-1e30, -1e30, -1e30]
    with open(path, "rb") as fh:
        fh.seek(80)
        raw = fh.read(4)
        if len(raw) == 4:
            n = struct.unpack("<I", raw)[0]
            body = fh.read(50 * n)
            if len(body) == 50 * n:
                for rec in struct.iter_unpack("<12fH", body):
                    for k in range(3):                      # 3 vertices
                        for i in range(3):                  # xyz
                            x = rec[3 + k * 3 + i]
                            if x < lo[i]:
                                lo[i] = x
                            if x > hi[i]:
                                hi[i] = x
    if len(raw) != 4:
        return {"triangles": None, "bytes": b, "error": "File is shorter than 84 bytes, so it is not a valid binary STL"}
    out = {"triangles": int(n), "bytes": b, "expected_bytes": 84 + 50 * int(n)}
    if hi[0] > -1e29:
        out["bbox_min"] = [_dv_r(x) for x in lo]
        out["bbox_max"] = [_dv_r(x) for x in hi]
        out["longest_edge"] = _dv_r(max(hi[i] - lo[i] for i in range(3)))
    return out


def _deliver_verify_p1(_state):
    manifest, path_or_dir = _state.get("manifest"), _state["path_or_dir"]
    cands, d, last, lm, prefer, stem = (_state.get("cands"), _state.get("d"), _state.get("last"), _state.get("lm"), _state.get("prefer"), _state.get("stem"))
    try:
        st = None
        try:
            st = _dv_store()
        except Exception:
            st = None
        p = path_or_dir
        if not p:
            last = (st or {}).get("last")
            if not last:
                return _dv_j({"ok": False, "error": "No path_or_dir given, and no recent export record to fall back on", "checks": []})
            p = last["dir"]
        p = _dv_win(p)
        if not os.path.exists(p):
            return _dv_j({"ok": False, "error": "Path does not exist: %s" % p, "checks": [
                {"name": "path_exists", "ok": False, "detail": "path does not exist: %s" % p}]})
        target_file = None
        if os.path.isfile(p):
            target_file = p
            d = os.path.dirname(p)
            if os.path.basename(p).endswith("_manifest.json"):
                if manifest == "auto":
                    manifest = p
        else:
            d = p
        checks = []

        def chk(name, ok, detail="", **extra):
            rec = {"name": name, "ok": bool(ok), "detail": detail}
            rec.update(extra)
            checks.append(rec)
            return bool(ok)

        # ---- 1. manifest
        man, man_path, man_src = None, None, None
        if manifest and manifest != "auto" and str(manifest) != "memory":
            man_path = _dv_win(manifest)
            if os.path.isfile(man_path):
                try:
                    man = json.loads(open(man_path, encoding="utf-8").read())
                    man_src = "explicit"
                except Exception as e:
                    chk("manifest_loadable", False, "Manifest parse failed (%s): %s" % (type(e).__name__, e), path=man_path)
            else:
                chk("manifest_exists", False, "The specified manifest does not exist: %s" % man_path, path=man_path)
        else:
            cands = []
            try:
                cands = sorted([os.path.join(d, n) for n in os.listdir(d) if n.endswith("_manifest.json")])
            except Exception:
                cands = []
            if target_file and not target_file.endswith("_manifest.json"):
                stem = os.path.basename(target_file).rsplit(".", 1)[0]
                prefer = os.path.join(d, stem + "_manifest.json")
                if os.path.isfile(prefer):
                    cands = [prefer] + [c for c in cands if c != prefer]
            if len(cands) > 1 and st and st.get("last") and st["last"].get("manifest"):
                lm = _dv_win(st["last"]["manifest"])
                if lm in cands:
                    cands = [lm] + [c for c in cands if c != lm]
            if cands:
                man_path = cands[0]
                try:
                    man = json.loads(open(man_path, encoding="utf-8").read())
                    man_src = "auto"
                except Exception as e:
                    chk("manifest_loadable", False, "Manifest parse failed (%s): %s" % (type(e).__name__, e), path=man_path)
            elif str(manifest) == "memory" and st and st.get("last"):
                man = st["last"]
                man_src = "memory(explicit memory mode, weaker than an on-disk manifest)"
        chk("manifest_available", man is not None,
            ("manifest source=%s path=%s" % (man_src, man_path)) if man is not None
            else "Directory %s has no *_manifest.json (exported with manifest=False, or the path is wrong) — pass manifest=<path> explicitly; "
                 "when there really is no manifest, use manifest='memory' to take the most recent export record (weaker, and flagged in the reply)" % d,
            manifest_path=man_path, manifest_source=man_src, candidates=len(cands) if str(manifest) == "auto" else None)
        if man is None:
            return _dv_j({"ok": False, "target": p, "manifest": man_path, "manifest_source": man_src,
                       "passed": len([c for c in checks if c["ok"]]), "failed": len([c for c in checks if not c["ok"]]),
                       "failed_checks": [c["name"] for c in checks if not c["ok"]], "checks": checks,
                       "hint": "Run deliver_export(..., manifest=True) first, then verify; or deliver_verify(<directory holding a manifest>)"})

        # ---- 2. per file: exists / bytes / md5 / face count
        flist = man.get("files") or []
        if not flist and target_file:
            flist = [{"role": os.path.basename(target_file).rsplit(".", 1)[-1], "path": target_file}]
        obs = {"files": {}}
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _deliver_verify_p2(_state):
    chk, flist, man, obs, target_file = (
        _state.get("chk"), _state.get("flist"), _state.get("man"), _state.get("obs"), _state.get("target_file"))
    base, dev, exists, exp_g, exp_hi, exp_lo, exp_u, ext, f, fp, got_bytes, got_md5, mt, nb, sc, want = (_state.get("base"), _state.get("dev"), _state.get("exists"), _state.get("exp_g"), _state.get("exp_hi"), _state.get("exp_lo"), _state.get("exp_u"), _state.get("ext"), _state.get("f"), _state.get("fp"), _state.get("got_bytes"), _state.get("got_md5"), _state.get("mt"), _state.get("nb"), _state.get("sc"), _state.get("want"))
    try:
        for f in flist:
            fp = _dv_win(f.get("path") or "")
            if not fp or not os.path.isfile(fp):
                if target_file and os.path.basename(fp) == os.path.basename(target_file):
                    fp = target_file
            base = os.path.basename(str(fp))
            exists = bool(fp) and os.path.isfile(fp)
            chk("file_exists:" + base, exists, ("exists %s" % fp) if exists else "a file listed in the manifest does not exist: %s" % fp, path=fp)
            if not exists:
                continue
            got_bytes = os.path.getsize(fp)
            got_md5 = _dv_md5(fp)
            obs["files"][base] = {"bytes": got_bytes, "md5": got_md5}
            chk("file_nonempty:" + base, got_bytes > 0, "%d bytes" % got_bytes, bytes=got_bytes)
            chk("md5_match:" + base, (not f.get("md5")) or got_md5 == f.get("md5"),
                "file md5=%s / manifest md5=%s" % (got_md5, f.get("md5")), md5=got_md5, manifest_md5=f.get("md5"))
            if f.get("bytes") is not None:
                chk("size_match:" + base, int(f["bytes"]) == got_bytes,
                    "file %d bytes / manifest %d bytes" % (got_bytes, int(f["bytes"])), bytes=got_bytes, manifest_bytes=int(f["bytes"]))
            ext = base.rsplit(".", 1)[-1].lower()
            if ext == "obj":
                sc = _dv_scan_obj(fp)
                obs["obj"] = sc
                chk("triangle_count_match:" + base, sc["triangles"] == int(man.get("counts", {}).get("triangles", f.get("triangles", -1))),
                    "OBJ has %d triangles / manifest %s" % (sc["triangles"], man.get("counts", {}).get("triangles", f.get("triangles"))),
                    triangles=sc["triangles"], manifest_triangles=man.get("counts", {}).get("triangles"))
                counts = man.get("counts") or {}
                exp_g = int(counts.get("groups", f.get("groups", counts.get("objects", f.get("objects", -1)))))
                exp_u = int(counts.get("usemtl", f.get("usemtl", -1)))
                exp_uu = counts.get("usemtl_unique", f.get("usemtl_unique"))
                exp_lines = exp_g if exp_g >= 0 else exp_u
                chk("obj_group_count_match:" + base, sc["groups"] == exp_g,
                    "g lines: %d / object(group) count: %d" % (sc["groups"], exp_g), groups=sc["groups"], manifest_groups=exp_g)
                chk("obj_usemtl_count_match:" + base, sc["usemtl"] == exp_lines,
                    "usemtl lines: %d / object(group) count: %d" % (sc["usemtl"], exp_lines),
                    usemtl=sc["usemtl"], manifest_lines=exp_lines)
                if exp_uu is None:
                    # Manifests from 3.0.0 and earlier stored counts.usemtl as the unique material
                    # count and had no usemtl_unique; accept them under the legacy rule, with line counts still checked via groups/objects.
                    meta_ok = exp_u in (sc["usemtl"], sc["usemtl_unique"])
                    chk("obj_usemtl_metadata_match:" + base, meta_ok,
                        "manifest usemtl=%d (legacy: unique material count or line count); file lines=%d / unique=%d"
                        % (exp_u, sc["usemtl"], sc["usemtl_unique"]),
                        manifest_usemtl=exp_u, usemtl=sc["usemtl"], usemtl_unique=sc["usemtl_unique"])
                else:
                    exp_uu = int(exp_uu)
                    meta_ok = exp_u == sc["usemtl"] and exp_uu == sc["usemtl_unique"]
                    chk("obj_usemtl_metadata_match:" + base, meta_ok,
                        "manifest usemtl=%d / usemtl_unique=%d; file lines=%d / unique=%d"
                        % (exp_u, exp_uu, sc["usemtl"], sc["usemtl_unique"]),
                        manifest_usemtl=exp_u, manifest_usemtl_unique=exp_uu,
                        usemtl=sc["usemtl"], usemtl_unique=sc["usemtl_unique"])
                chk("obj_has_normals:" + base, sc["normals"] >= 1, "vn lines: %d" % sc["normals"], normals=sc["normals"])
                # Recompute the bbox from the file's own v lines and compare it with the manifest's normalize record (never trust the manifest's self-report)
                nb = man.get("normalize") or {}
                exp_lo, exp_hi = nb.get("bbox_after_min"), nb.get("bbox_after_max")
                if sc.get("bbox_min") and exp_lo and exp_hi:
                    dev = max(abs(sc["bbox_min"][i] - float(exp_lo[i])) for i in range(3))
                    dev = max(dev, max(abs(sc["bbox_max"][i] - float(exp_hi[i])) for i in range(3)))
                    chk("obj_bbox_matches_manifest:" + base, dev <= 2e-4,
                        "file bbox=%s..%s / manifest record=%s..%s (max deviation %.2e, tolerance 2e-4 = two rounds of 5-decimal rounding)"
                        % (sc["bbox_min"], sc["bbox_max"], exp_lo, exp_hi, dev), max_dev=dev)
                if nb.get("applied") and sc.get("longest_edge") is not None:
                    want = 2.0 * float(nb.get("target_half_extent") or 0)
                    chk("obj_normalized_longest_edge:" + base, abs(sc["longest_edge"] - want) <= 1e-4 * max(1.0, want),
                        "longest edge in file %.5f / expected %.5f (2 × target_half_extent)" % (sc["longest_edge"], want),
                        longest=sc["longest_edge"], expected=want)
            elif ext == "stl":
                sc = _dv_scan_stl(fp)
                obs["stl"] = sc
                mt = int(man.get("counts", {}).get("triangles", f.get("triangles", -1)))
                chk("triangle_count_match:" + base, sc.get("triangles") == mt,
                    "STL header declares %s triangles / manifest %d" % (sc.get("triangles"), mt), triangles=sc.get("triangles"), manifest_triangles=mt)
                chk("stl_size_consistent:" + base, sc.get("expected_bytes") == got_bytes,
                    "84+50×%s = %s bytes / actual %d bytes" % (sc.get("triangles"), sc.get("expected_bytes"), got_bytes),
                    expected_bytes=sc.get("expected_bytes"), bytes=got_bytes)
                nb = man.get("normalize") or {}
                if nb.get("applied") and sc.get("longest_edge") is not None:
                    want = 2.0 * float(nb.get("target_half_extent") or 0)
                    chk("stl_normalized_longest_edge:" + base, abs(sc["longest_edge"] - want) <= 1e-4 * max(1.0, want),
                        "longest edge in file %.5f / expected %.5f (2 × target_half_extent)" % (sc["longest_edge"], want),
                        longest=sc["longest_edge"], expected=want)

        # ---- 3. units block / normalisation recoverable (archival rule)
        u = man.get("units") or {}
        note = str(u.get("note") or "")
        has_num = any(c.isdigit() for c in note)
        has_unit = ("mm" in note) or (" m" in note) or ("m =" in note)
        chk("units_note_has_units", bool(note) and has_num and has_unit,
            ("note=%s | meters_per_unit=%s m | millimeters_per_unit=%s mm"
             % (note, u.get("meters_per_unit"), u.get("millimeters_per_unit"))) if note
            else "The manifest has no unit-conversion block (units_note=False, or a legacy manifest)",
            meters_per_unit=u.get("meters_per_unit"), millimeters_per_unit=u.get("millimeters_per_unit"))
        nz = man.get("normalize") or {}
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def _deliver_verify_p3(_state):
    checks, chk, man, man_path, man_src = (
        _state.get("checks"), _state.get("chk"), _state.get("man"), _state.get("man_path"), _state.get("man_src"))
    nz, obs, p = _state.get("nz"), _state.get("obs"), _state.get("p")
    longest, ok, want = (_state.get("longest"), _state.get("ok"), _state.get("want"))
    try:
        if nz.get("applied"):
            ok = (float(nz.get("scale") or 0) > 0) and (nz.get("center") is not None) and (nz.get("bbox_before_min") is not None)
            chk("normalize_recoverable", ok,
                "scale=%s center=%s target_half_extent=%s original bbox=%s..%s (p_orig = p_out/scale + center)"
                % (nz.get("scale"), nz.get("center"), nz.get("target_half_extent"), nz.get("bbox_before_min"), nz.get("bbox_before_max")),
                scale=nz.get("scale"), center=nz.get("center"), target_half_extent=nz.get("target_half_extent"))
            if nz.get("bbox_after_size"):
                longest = max(nz["bbox_after_size"])
                want = 2.0 * float(nz.get("target_half_extent") or 0)
                chk("normalize_longest_edge", abs(longest - want) <= 1e-4 * max(1.0, want),
                    "longest edge after normalisation %.6f / expected %.6f (2 × target_half_extent)" % (longest, want),
                    longest=longest, expected=want)
        else:
            chk("normalize_recoverable", nz.get("bbox_before_min") is not None,
                "Not normalised (normalize=False): scale=1, center=(0,0,0), so the file scale is the original scale; original bbox=%s..%s"
                % (nz.get("bbox_before_min"), nz.get("bbox_before_max")), scale=1.0)

        passed = len([c for c in checks if c["ok"]])
        fail = [c["name"] for c in checks if not c["ok"]]
        return _dv_j({"ok": len(fail) == 0, "target": p, "manifest": man_path, "manifest_source": man_src,
                   "passed": passed, "failed": len(fail), "failed_checks": fail, "checks": checks,
                   "observed": obs, "counts": man.get("counts"),
                   "note": "Item-by-item check; any single FAIL means this deliverable cannot be archived per the manifest"})
    finally:
        _state.update((k, v) for k, v in locals().items() if k != "_state")

def deliver_verify(path_or_dir=None, manifest="auto"):
    """Read the artefacts back and self-check them item by item. Returns {ok, checks:[{name, ok, detail, ...numbers}], passed, failed}.

    Checks: manifest available / files exist and hold bytes / md5 matches the manifest / triangle count matches the manifest /
    OBJ g and usemtl line counts (= object count) match the manifest; usemtl_unique is only a unique-material diagnostic,
    and legacy manifests (3.0.0 and earlier, where usemtl held the unique material count) are accepted under the legacy rule.
    The units block carries units / normalisation is recoverable (scale+center+original bbox).
    `manifest="auto"` → look for `<name>_manifest.json` in the directory (of several, use the most recently exported one).
    """
    _state = dict(locals())
    for _fn_ in (_deliver_verify_p1, _deliver_verify_p2, _deliver_verify_p3):
        _r = _fn_(_state)
        if _r is not None:
            return _r


def deliver_help():
    return _dv_j({
        "version": DELIVER_VERSION,
        "api": "K.dsh_deliver_api",
        "ops": {
            "export": "export(dir, objects=None, scope=None, name='model', fmt='obj'|'stl', normalize=True, "
                      "target_half_extent=1.0, per_part_materials=True, manifest=True, units_note=True, include_hidden=False)",
            "verify": "verify(path_or_dir=None, manifest='auto') → item-by-item PASS/FAIL (md5 / face counts / g and usemtl line counts / units / normalisation recoverable); "
                      "manifest='auto' only looks at *_manifest.json on disk; only manifest='memory' takes the in-memory record of the most recent export (weaker)",
            "help": "help() → this quick reference",
        },
        "typical": "K.dsh_deliver_api['export']({'dir': 'D:/Blender/house', 'scope': 'House', 'name': 'house'}) "
                   "→ then K.dsh_deliver_api['verify']('D:/Blender/house')",
        "rules": ["Empty output (no objects picked / all empty meshes) → ok:false, never a silent success",
                  "Normalisation record scale/center/original bbox → p_orig = p_out / scale + center (archival rule)",
                  "OBJ: one g + usemtl per object (shared materials still get one line per object; usemtl_unique records only the unique material count); "
                  "MTL Kd comes from the material; when it cannot be read a deterministic grey is used and named in guessed_colors",
                  "STL carries no materials (per_part_materials has no effect on stl)",
                  "Axes: written as-is in Blender world Z-up, with no Y-up conversion"],
    })


def d_dispatch(op, args=None):
    """Unified entry point: the tool side sends {op, args} (the same unpacking style as txn/contract)."""
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception:
            args = {}
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    fn = d_ops().get(str(op))
    if fn is None:
        return _dv_j({"ok": False, "error": "unknown deliver op", "op": op, "ops": sorted(d_ops())})
    try:
        return fn(**kw)
    except TypeError as e:
        return _dv_j({"ok": False, "error": "argument mismatch: %s" % e, "op": op, "given": sorted(kw), "sig_hint": deliver_help()})


def d_ops():
    return {"export": deliver_export, "verify": deliver_verify, "help": deliver_help}


