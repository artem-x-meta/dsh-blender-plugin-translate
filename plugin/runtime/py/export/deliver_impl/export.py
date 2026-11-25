# -*- coding: utf-8 -*-
"""Split from deliver.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .materials import _dv_bbox, _dv_eval_part, _dv_grey_seed, _dv_mat_ref, _dv_material_of, _dv_units_info, _dv_write_mtl, _dv_write_obj, _dv_write_stl, _dv_write_text


def _dv_precheck(dir, fmt, target_half_extent, name):
    """Validate fmt / target_half_extent / name and resolve the output directory; returns (pre, err)."""
    f = str(fmt or "obj").strip().lower()
    if f not in _DV_FORMATS:
        return None, {"ok": False, "error": "Invalid fmt=%s" % fmt, "allowed": list(_DV_FORMATS),
                      "hint": "fmt='obj' (default, can carry a .mtl) or fmt='stl' (binary single file)"}
    try:
        the = float(target_half_extent)
    except Exception:
        return None, {"ok": False, "error": "target_half_extent must be a number", "given": target_half_extent}
    if the <= 0:
        return None, {"ok": False, "error": "target_half_extent must be > 0 (longest edge = 2 × target_half_extent)", "given": the}
    nm, changed_name = _dv_safe(name), None
    if nm != str(name or ""):
        changed_name = "name sanitised: %r → %r" % (name, nm)
    out_dir = dir
    if not out_dir:
        K = _dv_kernel()
        base = getattr(K, "out_dir", None) if K is not None else None
        out_dir = os.path.join(base or os.path.expanduser("~"), "deliver")
    out_dir = _dv_win(out_dir)
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        return None, {"ok": False, "error": "Cannot create the output directory (%s): %s" % (type(e).__name__, e), "dir": out_dir}
    return {"f": f, "the": the, "nm": nm, "changed_name": changed_name, "out_dir": out_dir}, None


def _dv_export_gate(require_gate, force_gate, gate_reason, gate_spec, gate_preset, gate_overrides, warn):
    """Delivery enforcement gate (defaults to false for legacy flows); returns (gate_rec, err)."""
    # Delivery enforcement gate (defaults to false for legacy flows; model_deliver / gate_deliver pass true).
    # The next minor release plans to default it on; for now a failed gate writes an explicit gate_warning in the receipt instead of failing silently.
    if not require_gate:
        warn.append("gate_warning: require_gate=false — the gate was not enforced before this export; for gated delivery use gate_deliver or require_gate=true")
        return None, None
    K = _dv_kernel()
    gapi = getattr(K, "dsh_gate_api", None) if K is not None else None
    if gapi is None:
        return None, {"ok": False, "blocked": True, "error": "require_gate=true but K.dsh_gate_api does not exist",
                      "hint": "headless warm-up: preload=\"gate\" (or run blender_rt_plan(op=\"gate_run\") first)"}
    if force_gate and not str(gate_reason or "").strip():
        return None, {"ok": False, "blocked": True,
                      "error": "force_gate=true requires gate_reason (written into the receipt)"}
    try:
        gate_rec = gapi("run", {"spec": gate_spec, "preset": gate_preset,
                                "overrides": gate_overrides})
        if isinstance(gate_rec, str):
            gate_rec = json.loads(gate_rec)
    except Exception as e:
        return None, {"ok": False, "blocked": True,
                      "error": "gate_run failed: %s: %s" % (type(e).__name__, str(e)[:220])}
    _gv = (gate_rec or {}).get("verdict")
    if _gv != "pass" and not force_gate:
        return None, {"ok": False, "blocked": True, "verdict": _gv, "gate": gate_rec,
                      "error": "Safety gate did not pass (verdict=%s): export refused" % _gv,
                      "hint": "See gate.failed/degraded/skipped; for degraded delivery use gate_deliver(allow_degraded=true); forcing an export needs force_gate=true+gate_reason"}
    return gate_rec, None


def _dv_collect_parts(objs, dg, warn):
    """Evaluate each object → parts (skipping evaluation failures/no triangles); returns (parts, failed, empty)."""
    parts, failed, empty = [], [], []
    for ob in objs:
        part, perr = _dv_eval_part(ob, dg)
        if part is None:
            failed.append({"name": ob.name, "why": perr})
            continue
        if part["triangles"] == 0:
            empty.append(ob.name)
            continue
        if part["degenerate"]:
            warn.append("%s: %d degenerate triangles (normals got the deterministic placeholder (0,0,1))" % (ob.name, part["degenerate"]))
        parts.append(part)
    return parts, failed, empty


def _dv_part_materials(parts):
    """Per-object material row + base colour (the same material shares one newmtl); returns (mats, by_src, guessed)."""
    mats, by_src, guessed, ref_by_key = [], {}, [], {}
    for p in parts:
        ob = bpy.data.objects.get(p["name"])
        if ob is not None:
            mname, kd, src, rough, metal, is_guess = _dv_material_of(ob)
        else:
            mname, kd, src, rough, metal, is_guess = None, _dv_grey_seed(p["name"]), "deterministic_grey", None, None, True
        key = mname if mname else ("__nomat__:" + p["name"])
        ref = ref_by_key.get(key)
        if ref is None:
            ref = _dv_mat_ref(mname if mname else ("mat_" + _dv_safe(p["name"], "part")),
                              set(m["ref"] for m in mats))
            ref_by_key[key] = ref
            mats.append({"ref": ref, "src": mname, "kd": [round(float(kd[0]), 6), round(float(kd[1]), 6), round(float(kd[2]), 6)],
                         "source": src, "rough": None if rough is None else round(float(rough), 6),
                         "metal": None if metal is None else round(float(metal), 6), "objects": [p["name"]]})
        else:
            for m in mats:
                if m["ref"] == ref:
                    m["objects"].append(p["name"])
                    break
        p["material"] = mname
        p["material_ref"] = ref
        p["material_source"] = src
        p["kd"] = [round(float(kd[0]), 6), round(float(kd[1]), 6), round(float(kd[2]), 6)]
        p["guessed"] = bool(is_guess)
        by_src[src] = by_src.get(src, 0) + 1
        if is_guess:
            guessed.append({"object": p["name"], "material": mname, "kd": p["kd"],
                            "why": "The object has no material slot or its colour cannot be read → a deterministic grey derived from the name md5 (not a true value)"})
    return mats, by_src, guessed


def _dv_normalize(parts, the, normalize):
    """bbox → normalize (archival rule: the scale/center/original-bbox trio must be kept); returns (norm, center, err)."""
    all_verts = []
    for p in parts:
        all_verts.extend(p["verts"])
    lo, hi = _dv_bbox(all_verts)
    size = [hi[i] - lo[i] for i in range(3)]
    center = [(lo[i] + hi[i]) * 0.5 for i in range(3)]
    longest = max(size) if size else 0.0
    norm = {"applied": False, "target_half_extent": the,
            "bbox_before_min": [_dv_r(v) for v in lo], "bbox_before_max": [_dv_r(v) for v in hi],
            "bbox_before_size": [_dv_r(v) for v in size], "center": [_dv_r(v) for v in center],
            "scale": 1.0, "center_offset": [0.0, 0.0, 0.0],
            "recover": "Original coordinates p_orig = p_out / scale + center (scale=1, center=0 means not normalised)"}
    if normalize:
        if not (longest > 0):
            return None, None, {"ok": False, "error": "Zero-size bounding box (geometry collapsed to a point / flattened to zero): normalisation is impossible",
                                "bbox_size": [_dv_r(v) for v in size]}
        scale = (2.0 * the) / longest
        center = [lo[i] + size[i] * 0.5 for i in range(3)]
        for p in parts:
            p["verts"] = [[(c[0] - center[0]) * scale, (c[1] - center[1]) * scale, (c[2] - center[2]) * scale]
                          for c in p["verts"]]
        lo2, hi2 = _dv_bbox([c for p in parts for c in p["verts"]])
        norm.update({"applied": True, "scale": _dv_r(scale, 9), "center": [_dv_r(v) for v in center],
                     "center_offset": [_dv_r(-v) for v in center],
                     "bbox_after_min": [_dv_r(v) for v in lo2], "bbox_after_max": [_dv_r(v) for v in hi2],
                     "bbox_after_size": [_dv_r(hi2[i] - lo2[i]) for i in range(3)],
                     "formula": "p_out = (p_orig - center) * scale",
                     "recover": "Original coordinates p_orig = p_out / scale + center (scale=%.9g)" % scale})
    else:
        norm.update({"bbox_after_min": norm["bbox_before_min"], "bbox_after_max": norm["bbox_before_max"],
                     "bbox_after_size": norm["bbox_before_size"],
                     "note": "normalize=False: the scale in the file is the original scene scale (scale=1, center=(0,0,0))"})
    return norm, center, None


def _dv_head(f, nm, parts, n_tri, n_v, units_note, units, norm, center, the):
    """OBJ file header (object count/triangles/units/normalisation record/axis declaration)."""
    head = ["# DSH deliver v%d  name=%s  fmt=%s" % (DELIVER_VERSION, nm, f),
            "# objects=%d triangles=%d vertices=%d" % (len(parts), n_tri, n_v)]
    if units_note:
        head.append("# units: " + units["note"])
    if norm.get("applied"):
        head.append("# normalize: scale=%.9g center=(%.6g, %.6g, %.6g) target_half_extent=%.6g  →  p_orig = p_out/scale + center"
                    % (norm["scale"], center[0], center[1], center[2], the))
    else:
        head.append("# normalize: not applied (file scale = original scene scale)")
    head.append("# axes: written as-is in Blender world Z-up (no Y-up conversion); normals are geometric face normals")
    return head


def _dv_write_files(f, nm, out_dir, per_part_materials, parts, mats, head, warn, n_tri):
    """Write OBJ(+MTL) or STL; returns (files, err)."""
    files = {}
    try:
        if f == "obj":
            obj_path = os.path.join(out_dir, nm + ".obj")
            mtl_name = (nm + ".mtl") if per_part_materials else None
            info = _dv_write_obj(obj_path, parts, head, mtl_name)
            files["obj"] = {"role": "obj", "path": _dv_win(obj_path), "bytes": os.path.getsize(obj_path),
                            "md5": _dv_md5(obj_path), "triangles": n_tri, "vertices": info["vertices"],
                            "normals": info["normals"], "groups": info["groups"], "usemtl": info["usemtl"],
                            "usemtl_unique": info["usemtl_unique"]}
            if mtl_name:
                mtl_path = os.path.join(out_dir, mtl_name)
                minfo = _dv_write_mtl(mtl_path, mats, ["# DSH deliver v%d  name=%s" % (DELIVER_VERSION, nm),
                                                       "# object → material mapping in %s_manifest.json" % nm])
                files["mtl"] = {"role": "mtl", "path": _dv_win(mtl_path), "bytes": os.path.getsize(mtl_path),
                                "md5": _dv_md5(mtl_path), "materials": minfo["materials"]}
        else:
            stl_path = os.path.join(out_dir, nm + ".stl")
            sinfo = _dv_write_stl(stl_path, parts, nm)
            files["stl"] = {"role": "stl", "path": _dv_win(stl_path), "bytes": sinfo["bytes"], "md5": _dv_md5(stl_path),
                            "triangles": sinfo["triangles"], "groups": len(parts)}
            if per_part_materials:
                warn.append("fmt='stl': STL carries no materials (per_part_materials has no effect on STL; ignored)")
    except Exception as e:
        return None, {"ok": False, "error": "Writing the file failed (%s): %s" % (type(e).__name__, e)}
    return files, None


def _dv_write_manifest(nm, f, out_dir, files, objects_rec, counts, mats, units, norm, guessed, by_src, excluded, warn):
    """Write the on-disk manifest <name>_manifest.json (the authoritative record); returns (rec, err)."""
    man = {"tool": "dsh-deliver", "api_version": DELIVER_VERSION, "generated_at": _dv_now(),
           "name": nm, "fmt": f, "dir": out_dir,
           "blender": bpy.app.version_string, "scene": bpy.context.scene.name if bpy.context.scene else None,
           "blend_filepath": bpy.data.filepath or None,
           "files": [dict(v, name=os.path.basename(str(v["path"]))) for v in files.values()],
           "objects": objects_rec, "counts": counts,
           "materials": [{"ref": m["ref"], "src": m["src"], "kd": m["kd"], "source": m["source"],
                          "rough": m["rough"], "metal": m["metal"], "objects": m["objects"]} for m in mats],
           "units": units, "normalize": norm, "guessed_colors": guessed,
           "material_color_sources": by_src, "excluded_hidden": excluded,
           "warnings": warn, "boundary": _DV_BOUNDARY,
           "recovery_rule": "The archive must allow recovering the original scale: p_orig = p_out / normalize.scale + normalize.center"}
    man_path = os.path.join(out_dir, nm + "_manifest.json")
    try:
        _dv_write_text(man_path, json.dumps(man, ensure_ascii=False, indent=2, default=str) + "\n")
    except Exception as e:
        return None, "Geometry was written, but the manifest failed to write (%s): %s" % (type(e).__name__, e)
    return {"path": _dv_win(man_path), "bytes": os.path.getsize(man_path), "md5": _dv_md5(man_path)}, None


def _dv_objects_record(parts):
    """Per-object summary for the receipt."""
    return [{"name": p["name"], "triangles": len(p["faces"]), "vertices": len(p["verts"]),
             "material": p.get("material"), "material_ref": p.get("material_ref"),
             "material_source": p.get("material_source"), "kd": p.get("kd"), "guessed": p.get("guessed")}
            for p in parts]


def _dv_finish(out_dir, nm, f, files, objects_rec, counts, mats, norm, units, guessed, by_src,
               excluded, empty, missing, warn, gate_rec, manifest, t0):
    """Result receipt + manifest + in-memory record + hint."""
    result = {"ok": True, "dir": out_dir, "name": nm, "fmt": f, "files": files, "counts": counts,
              "objects": objects_rec, "materials": mats, "normalize": norm, "units": units,
              "guessed_colors": guessed, "material_color_sources": by_src, "excluded_hidden": excluded,
              "skipped_empty": empty, "missing_objects": missing, "warnings": warn,
              "boundary": _DV_BOUNDARY, "ms": int((time.perf_counter() - t0) * 1000)}
    if gate_rec is not None:
        result["gate"] = gate_rec
    else:
        result["gate_warning"] = "require_gate=false (gate not enforced)"
    if manifest:
        mrec, merr = _dv_write_manifest(nm, f, out_dir, files, objects_rec, counts, mats, units, norm,
                                        guessed, by_src, excluded, warn)
        if merr:
            result["ok"] = False
            result["error"] = merr
            return result
        result["manifest"] = mrec
    else:
        warn.append("manifest=False: no manifest file (verify can only fall back to the most recent in-memory export record)")
    st = _dv_store()
    st["last"] = {"dir": out_dir, "name": nm, "fmt": f, "manifest": result.get("manifest", {}).get("path"),
                  "files": [dict(v, name=os.path.basename(str(v["path"]))) for v in files.values()],
                  "counts": counts, "normalize": norm, "units": units, "t": _dv_now(),
                  "authority": "in-memory record (K.dsh_deliver.last) — reference only; the authority is <name>_manifest.json on disk"}
    st["exports"].append({"t": _dv_now(), "dir": out_dir, "name": nm, "fmt": f, "objects": counts["objects"],
                          "triangles": counts["triangles"], "md5": {k: v.get("md5") for k, v in files.items()}})
    del st["exports"][:-50]
    result["hint"] = "Before delivering, run K.dsh_deliver_api['verify'](%r) to cross-check every item (md5 / face counts / g and usemtl line counts)" % out_dir
    return result


def deliver_export(dir=None, objects=None, scope=None, name="model", fmt="obj", normalize=True,
                   target_half_extent=1.0, per_part_materials=True, manifest=True, units_note=True,
                   include_hidden=False, require_gate=False, gate_spec=None, gate_preset=None,
                   gate_overrides=None, force_gate=False, gate_reason=""):
    """Export the selected meshes as deliverable OBJ(+MTL) / STL and write a manifest (with md5 / face counts / units / normalisation record).

    Typical one-liner: K.dsh_deliver_api["export"]({"dir": "D:/Blender/house", "scope": "House", "name": "house"})
    Empty output (no objects picked / none of them has triangles) → ok:false; never a silent success.
    """
    t0 = time.perf_counter()
    pre, perr = _dv_precheck(dir, fmt, target_half_extent, name)
    if perr:
        return _dv_j(perr)
    f, the, nm, out_dir = pre["f"], pre["the"], pre["nm"], pre["out_dir"]
    warn = []
    if pre["changed_name"]:
        warn.append(pre["changed_name"])
    gate_rec, gerr = _dv_export_gate(require_gate, force_gate, gate_reason, gate_spec,
                                     gate_preset, gate_overrides, warn)
    if gerr:
        return _dv_j(gerr)
    objs, missing, err, excluded = _dv_pick(objects, scope, include_hidden)
    if err:
        return _dv_j({"ok": False, "error": err, "dir": out_dir, "objects": objects, "scope": scope})
    if missing:
        warn.append("Objects do not exist (skipped): %s" % ", ".join(missing))
    if not objs:
        return _dv_j({"ok": False, "error": "Picked 0 meshes: neither objects nor scope named a valid object, or all were filtered out as hidden (include_hidden=False)",
                      "objects": objects, "scope": scope, "excluded_hidden": excluded, "dir": out_dir})
    dg = bpy.context.evaluated_depsgraph_get()
    parts, failed, empty = _dv_collect_parts(objs, dg, warn)
    if failed:
        warn.append("Evaluation failed (skipped): %s" % _dv_j(failed))
    if empty:
        warn.append("No triangles (skipped): %s" % ", ".join(empty))
    if not parts:
        return _dv_j({"ok": False, "error": "0 of the picked objects have triangles — empty output is not accepted (evaluation failed / empty mesh)",
                      "objects": [o.name for o in objs], "failed": failed, "empty": empty, "dir": out_dir})
    mats, by_src, guessed = _dv_part_materials(parts)
    norm, center, nerr = _dv_normalize(parts, the, normalize)
    if nerr:
        nerr["dir"] = out_dir
        return _dv_j(nerr)
    units = _dv_units_info() if units_note else {"suppressed": True, "reason": "units_note=False (the archival rule requires numbers to carry units; verify reports FAIL)"}
    n_tri = sum(len(p["faces"]) for p in parts)
    n_v = sum(len(p["verts"]) for p in parts)
    head = _dv_head(f, nm, parts, n_tri, n_v, units_note, units, norm, center, the)
    files, werr = _dv_write_files(f, nm, out_dir, per_part_materials, parts, mats, head, warn, n_tri)
    if werr:
        werr["dir"] = out_dir
        return _dv_j(werr)
    objects_rec = _dv_objects_record(parts)
    counts = {"objects": len(parts), "triangles": n_tri, "vertices": n_v, "materials": len(mats),
              "groups": len(parts), "usemtl": len(parts),
              "usemtl_unique": len(set(p["material_ref"] for p in parts))}
    return _dv_j(_dv_finish(out_dir, nm, f, files, objects_rec, counts, mats, norm, units, guessed,
                            by_src, excluded, empty, missing, warn, gate_rec, manifest, t0))
