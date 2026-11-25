# -*- coding: utf-8 -*-
"""Split from blockout.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .templates import _dedupe_ids, _parse_export_opt, _parse_landmarks, _parse_part, _parse_render_opt, _template_parts
from .geometry import _audit_objects, _bbox_bu, _bbox_mm, _export_objs, _render_views, _tris_base, _tris_eval



# ────────────────────────────── op: base ──────────────────────────────
def _bo_parse_args(name, template, units, anchor, bevel_mm, template_scale, outdir, render, export,
                    audit, reset, parts, landmarks):
    """Parse/validate the base arguments; returns a dict (bad values raise ValueError)."""
    nm = _safe_token(name, "name")
    tmpl = str(template or "none").strip().lower()
    if tmpl not in ALLOWED_TEMPLATES:
        raise ValueError("template only supports %s (got %r)" % ("/".join(ALLOWED_TEMPLATES), template))
    un = str(units or "mm").strip().lower()
    un_mm = _unit_to_mm(un)
    anc = str(anchor or "bottom").strip().lower()
    if anc not in ALLOWED_ANCHORS:
        raise ValueError("anchor only supports %s (got %r)" % ("/".join(ALLOWED_ANCHORS), anchor))
    bevel_val = _num(bevel_mm, "bevel_mm", default=DEFAULT_BEVEL_MM, minv=0.0, maxv=20.0)
    tscale = _num(template_scale, "template_scale", default=1.0, gt=0.0, maxv=20.0)
    root = _root_outdir(outdir)
    ropt = _parse_render_opt(render, root, nm)
    eopt = _parse_export_opt(export, root, nm)
    do_audit = _bool(audit, "audit", False)
    do_reset = _bool(reset, "reset", False)
    lm_items, lm_warn = _parse_landmarks(landmarks, un)
    tmpl_parts = _template_parts(tmpl, tscale) if tmpl != "none" else []
    user_parts = []
    if parts is not None:
        if not isinstance(parts, (list, tuple)):
            raise ValueError("parts must be a list (got %r)" % (type(parts).__name__,))
        user_parts = list(parts)
    if not tmpl_parts and not user_parts:
        raise ValueError("no geometry parts: with template=none, parts is required; or pass template=humanoid_prim/vehicle")
    parsed = []
    for i, sp in enumerate(tmpl_parts):
        parsed.append(_parse_part(sp, i, "mm"))
    for j, sp in enumerate(user_parts):
        parsed.append(_parse_part(sp, len(parsed) + j, un))
    warnings = list(lm_warn)
    warnings.extend(_dedupe_ids(parsed))
    return {"nm": nm, "tmpl": tmpl, "un": un, "un_mm": un_mm, "anc": anc, "bevel_val": bevel_val,
            "root": root, "ropt": ropt, "eopt": eopt, "do_audit": do_audit, "do_reset": do_reset,
            "lm_items": lm_items, "parsed": parsed, "warnings": warnings}


def _bo_build(parsed, nm, col, mat, bevel_bu):
    """Build the primitive objects from parsed (material/location/rotation/bevel); returns (objs, recs)."""
    objs = []
    recs = []
    for p in parsed:
        stem = "BO-%s-%s" % (nm, p["id"])
        if p["prim"] == "box":
            me = _prim_box(p["size_bu"][0], p["size_bu"][1], p["size_bu"][2], stem)
        elif p["prim"] == "cylinder":
            me = _prim_cylinder(p["radius_bu"], p["depth_bu"], p["axis"], stem)
        else:
            me = _prim_sphere(p["radius_bu"], stem)
        try:
            me.materials.append(mat)
        except Exception:
            pass
        ob = bpy.data.objects.new(stem, me)
        col.objects.link(ob)
        ob.location = tuple(p["at_bu"])
        ob.rotation_mode = "XYZ"
        ob.rotation_euler = Euler([math.radians(a) for a in p["rot_deg"]], "XYZ")
        _add_bevel(ob, bevel_bu)
        objs.append(ob)
        recs.append({"id": p["id"], "object": ob.name, "prim": p["prim"],
                     "at_mm": [round(v * _mm_per_bu(), 4) for v in p["at_bu"]],
                     "size_mm": p["size_mm"], "radius_mm": p["radius_mm"],
                     "depth_mm": p["depth_mm"], "axis": p["axis"] if p["prim"] == "cylinder" else None,
                     "rot_deg": p["rot_deg"], "mirror": bool(p["mirror"]),
                     "mirror_object": None, "modifiers": ["Bevel"] if bevel_bu > 0 else []})
    return objs, recs


def _bo_mirror(objs, recs, col, bevel_bu):
    """Mirrored parts (done after the matrix update: true mirror + normal fix); appended to objs and backfilled into rec.mirror_object."""
    for ob, rec in list(zip(list(objs), recs)):
        if not rec["mirror"]:
            continue
        mob = _mirror_object(ob, ob.name + "-m", col)
        _add_bevel(mob, bevel_bu)
        rec["mirror_object"] = mob.name
        objs.append(mob)


def _bo_anchor(objs, anc):
    """anchor: shift the whole model (Z only; X/Y keep the input position so bboxes can be compared); returns dz."""
    mn0, mx0 = _bbox_bu(objs)
    if anc == "bottom":
        dz = -float(mn0.z)
    elif anc == "center":
        dz = -float(mn0.z + mx0.z) * 0.5
    else:
        dz = 0.0
    if abs(dz) > 1e-12:
        for ob in objs:
            ob.location.z = float(ob.location.z) + dz
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
    return dz


def _bo_extras(result, objs, nm, do_audit, ropt, eopt):
    """Optional extra artifacts: built-in check / render / export (failure sets ok=false with an error)."""
    if do_audit:
        result["audit"] = _audit_objects(objs)
        if not result["audit"].get("ok"):
            result["ok"] = False
            result.setdefault("error", "built-in check failed: %s" % (result["audit"].get("note") or ""))
            result.setdefault("hint", "see audit.per_object; a blockout is normally closed primitives, so non-manifold edges usually mean a bad parameter/mirror")
    if ropt is not None:
        try:
            result["render"] = _render_views(objs, ropt, nm)
            if not result["render"].get("ok"):
                result["ok"] = False
                result.setdefault("error", "render failed")
        except Exception as e:
            result["render"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:260]),
                                "hint": "rendering is an extra artifact; the geometry is already built in the scene (objects are in the receipt)"}
            result["ok"] = False
            result.setdefault("error", "render failed: %s" % str(e)[:200])
    if eopt is not None:
        try:
            result["export"] = _export_objs(objs, eopt)
            if not result["export"].get("ok"):
                result["ok"] = False
                result.setdefault("error", result["export"].get("error") or "export failed")
        except Exception as e:
            result["export"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:260])}
            result["ok"] = False
            result.setdefault("error", "export failed: %s" % str(e)[:200])
    return result


def blockout_base(name=None, template="none", units="mm", anchor="bottom", parts=None,
                  landmarks=None, collection=None, render=None, export=None, audit=False,
                  reset=False, bevel_mm=DEFAULT_BEVEL_MM, template_scale=1.0, outdir=None):
    t_start = time.perf_counter()
    try:
        a = _bo_parse_args(name, template, units, anchor, bevel_mm, template_scale, outdir, render,
                           export, audit, reset, parts, landmarks)
    except ValueError as e:
        return _err(e, hint="see K.dsh_blockout_api['help']() for the base parameters; each part needs prim+size+at_mm",
                    op="base")
    except Exception as e:
        return _err("%s: %s" % (type(e).__name__, str(e)), hint="argument parsing failed, the scene was not modified", op="base")
    try:
        col = _ensure_collection(collection or DEFAULT_COLLECTION)
        removed = _clear_bo_objects(col) if a["do_reset"] else []
        mat = _white_material()
        bevel_bu = a["bevel_val"] / _mm_per_bu()
        objs, recs = _bo_build(a["parsed"], a["nm"], col, mat, bevel_bu)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        _bo_mirror(objs, recs, col, bevel_bu)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        dz = _bo_anchor(objs, a["anc"])
        mn, mx = _bbox_bu(objs)
        geom_ms = int(round((time.perf_counter() - t_start) * 1000.0))
        landmarks_out = {}
        for lm_name, vals in a["lm_items"]:
            landmarks_out[lm_name] = [round((vals[i] + (dz if i == 2 else 0.0)) * _mm_per_bu(), 4)
                                      for i in range(3)]
        total_tris, per_tris = _tris_base(objs)
        for rec, t in zip(recs, per_tris):
            rec["tris"] = int(t)
        result = {
            "ok": True, "version": BLOCKOUT_VERSION, "op": "base", "name": a["nm"],
            "template": a["tmpl"], "units": a["un"], "anchor": a["anc"],
            "collection": col.name, "material": mat.name,
            "object_count": len(objs), "objects": [ob.name for ob in objs],
            "parts": recs, "total_tris": int(total_tris), "total_tris_eval": _tris_eval(objs),
            "bbox_mm": _bbox_mm(mn, mx),
            "landmarks": landmarks_out,
            "bevel_mm": a["bevel_val"], "reset_removed": removed,
            "units_meta": {"mm_per_unit": round(_mm_per_bu(), 6), "input": a["un"],
                           "input_mm_factor": a["un_mm"]},
            "warnings": a["warnings"],
            "ms": {"geom": geom_ms},
        }
        result = _bo_extras(result, objs, a["nm"], a["do_audit"], a["ropt"], a["eopt"])
        result["ms"]["total"] = int(round((time.perf_counter() - t_start) * 1000.0))
        return result
    except Exception as e:
        return _err("%s: %s" % (type(e).__name__, str(e)[:280]),
                    hint="the geometry build stage failed; partial objects may remain in the scene, roll back with K.dsh_qc_api or blender_rt_txn",
                    op="base", name=name)


# ────────────────────────────── op: batch ──────────────────────────────
def blockout_batch(models=None, outdir=None, export=None, collection=None, cleanup=True, render=None):
    t_start = time.perf_counter()
    try:
        if not isinstance(models, (list, tuple)) or not models:
            raise ValueError("models must be a non-empty list (each item is a base parameter dict with at least name+parts)")
        if len(models) > 100:
            raise ValueError("models accepts at most 100 items (got %d)" % len(models))
        cleanup_b = _bool(cleanup, "cleanup", True)
        root = _root_outdir(outdir)
        base_col = str(collection or "BLOCKOUT-BATCH").strip() or "BLOCKOUT-BATCH"
        names = []
        for i, m in enumerate(models):
            if not isinstance(m, dict):
                raise ValueError("models[%d] must be a dict (got %r)" % (i, type(m).__name__))
            mn = _safe_token(m.get("name") or ("m%02d" % i), "models[%d].name" % i)
            if mn in names:
                raise ValueError("duplicate name in models: %r (export file names would overwrite each other, rename first)" % mn)
            names.append(mn)
    except ValueError as e:
        return _err(e, hint="each batch item has the same shape as base; give at least {name, parts} per item", op="batch")
    except Exception as e:
        return _err("%s: %s" % (type(e).__name__, str(e)), op="batch")
    items = []
    ok_all = True
    for i, spec in enumerate(models):
        item = dict(spec)
        nm = names[i]
        item["name"] = nm
        if "collection" not in item or not item.get("collection"):
            item["collection"] = "%s-%s" % (base_col, nm)
        if item.get("render") is None and render is not None:
            item["render"] = render
        if item.get("export") is None and export is not None:
            item["export"] = export
        if item.get("outdir") is None:
            item["outdir"] = root
        try:
            r = blockout_base(**item)
        except TypeError as e:
            r = _err("parameter mismatch: %s" % str(e)[:220],
                     hint="batch items use the same parameter names as base (see help); unrecognized keys are listed", op="batch-item",
                     name=nm)
        except Exception as e:
            r = _err("%s: %s" % (type(e).__name__, str(e)[:240]), op="batch-item", name=nm)
        items.append(r)
        if not r.get("ok"):
            ok_all = False
        if cleanup_b:
            try:
                _remove_objects(r.get("objects") or [])
                _remove_collection_if_empty(item.get("collection"))
            except Exception:
                pass
    built = sum(1 for r in items if r.get("ok"))
    return {"ok": bool(ok_all), "op": "batch", "count": len(items), "built": built,
            "failed": [it.get("name") for it in items if not it.get("ok")],
            "items": items, "collection": base_col, "cleanup": cleanup_b, "outdir": root,
            "ms": int(round((time.perf_counter() - t_start) * 1000.0)),
            "total_ms": int(round((time.perf_counter() - t_start) * 1000.0))}


# ────────────────────────────── op: export (fill in for an already built scene) ──────────────────────────────
def _find_model_objects(objects=None, name=None, collection=None):
    found = []
    missing = []
    if objects:
        names = [objects] if isinstance(objects, str) else list(objects)
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                missing.append(str(n))
            elif ob.type == "MESH":
                found.append(ob)
    if name:
        prefix = "BO-%s-" % _safe_token(name, "name")
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and str(ob.name).startswith(prefix):
                found.append(ob)
    if collection:
        col = bpy.data.collections.get(str(collection))
        if col is None:
            missing.append("collection:%s" % collection)
        else:
            for ob in col.objects:
                if ob.type == "MESH" and str(ob.name).startswith("BO-"):
                    found.append(ob)
    uniq = []
    seen = set()
    for ob in found:
        if ob.name not in seen:
            seen.add(ob.name)
            uniq.append(ob)
    if missing:
        raise ValueError("cannot find these objects: %s" % missing[:6])
    if not uniq:
        raise ValueError("cannot find a built blockout: pass objects=[name] / name=<model name> / collection=<collection name>")
    return uniq


def blockout_export(objects=None, name=None, collection=None, glb=None, obj=None, export=None,
                    render=None, outdir=None):
    t_start = time.perf_counter()
    try:
        objs = _find_model_objects(objects=objects, name=name, collection=collection)
        root = _root_outdir(outdir)
        # export can be a nested dict, or glb/obj given at the same level
        exp = {}
        if isinstance(export, dict):
            exp.update(export)
        elif export is True:
            exp["glb"] = True
        elif isinstance(export, str) and export.strip():
            exp["glb"] = export
        elif export not in (None, False, 0):
            raise ValueError("export must be a dict / true / false / path string (got %r)" % (export,))
        if glb is not None:
            exp["glb"] = glb
        if obj is not None:
            exp["obj"] = obj
        stem = _safe_token(name or (objs[0].name if objs else "export"), "name")
        eopt = _parse_export_opt(exp if exp else None, root, stem)
        ropt = _parse_render_opt(render, root, stem)
        if eopt is None and ropt is None:
            raise ValueError("nothing was requested: give at least one of render=<view params> / glb= / obj=")
        mn, mx = _bbox_bu(objs)
        result = {"ok": True, "op": "export", "objects": [ob.name for ob in objs],
                  "object_count": len(objs), "bbox_mm": _bbox_mm(mn, mx)}
        if ropt is not None:
            try:
                result["render"] = _render_views(objs, ropt, stem)
                if not result["render"].get("ok"):
                    result["ok"] = False
            except Exception as e:
                result["render"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:260])}
                result["ok"] = False
                result.setdefault("error", "render failed: %s" % str(e)[:200])
        if eopt is not None:
            try:
                result["export"] = _export_objs(objs, eopt)
                if not result["export"].get("ok"):
                    result["ok"] = False
                    result.setdefault("error", result["export"].get("error") or "export failed")
            except Exception as e:
                result["export"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:260])}
                result["ok"] = False
                result.setdefault("error", "export failed: %s" % str(e)[:200])
        result["ms"] = int(round((time.perf_counter() - t_start) * 1000.0))
        return result
    except ValueError as e:
        return _err(e, hint="export does not rebuild geometry: build the objects with base first; names look like BO-<name>-<id>", op="export")
    except Exception as e:
        return _err("%s: %s" % (type(e).__name__, str(e)[:280]), op="export")

