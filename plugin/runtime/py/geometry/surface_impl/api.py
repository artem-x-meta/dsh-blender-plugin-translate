# -*- coding: utf-8 -*-
"""Split from surface_orig.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .objects import _bbox_mm, surface_blend, surface_loft, surface_offset, surface_patch, surface_sweep, surface_tessellate
from .validate import _circle_pts, _cleanup_objects, _meshes_equal, surface_validate



def _surface_selftest_p1(st):
    ev, made = (st.get("ev"), st.get("made"))
    try:
        prev_scale = float(bpy.context.scene.unit_settings.scale_length)
        bpy.context.scene.unit_settings.scale_length = 0.001      # 1 unit = 1 mm
        # ---- the three baselines ----
        ns = 8
        sections = []
        for k in range(ns):
            tpar = k / float(ns - 1)
            z = 160.0 * tpar
            r = 30.0 + 8.0 * math.sin(math.pi * tpar)
            sections.append({"z_mm": z, "points_mm": _circle_pts(24, r)})
        r_bottle = json.loads(surface_loft(sections=sections, degree=3, continuity="G1",
                                           closed=True, tessellation={"u": 32, "v": 24},
                                           name="__surface_eval_bottle"))
        if r_bottle.get("object"):
            made.append(r_bottle["object"])
        ev["bottle_ok"] = bool(r_bottle.get("ok") and r_bottle.get("verts", 0) > 0
                               and r_bottle.get("tris", 0) > 0)
        ev["bottle_bbox_z_mm"] = (r_bottle.get("bbox_mm") or {}).get("size_mm")
        # The fender section is an ellipse, but the **circumferential seam sits at the top (low curvature)** — a seam landing at the
        # high-curvature end of the long axis inflates the discrete normal angle (that is a sampling-resolution problem, not a G1 break).
        # This is also the seam placement real modeling should follow.
        fender_prof = []
        for k in range(24):
            ang = math.pi / 2.0 + 2.0 * math.pi * k / 24.0
            fender_prof.append([30.0 * math.cos(ang), 14.0 * math.sin(ang)])
        r_fender = json.loads(surface_sweep(
            profile_mm=fender_prof,
            rail_mm=[[0, 0, 0], [30, 5, 2], [60, 12, 4], [90, 20, 6], [120, 28, 8]],
            orientation="auto", twist_deg=20.0, scale=[1.2, 1.1, 1.0, 0.95, 0.9],
            tessellation={"u": 32, "v": 32}, closed=True, name="__surface_eval_fender"))
        if r_fender.get("object"):
            made.append(r_fender["object"])
        ev["fender_ok"] = bool(r_fender.get("ok") and r_fender.get("verts", 0) > 0)
        grid = []
        for i in range(4):
            row = []
            x = -40.0 + 80.0 * i / 3.0
            for j in range(4):
                y = -40.0 + 80.0 * j / 3.0
                z = 55.0 - 20.0 * (x / 40.0) ** 2 - 15.0 * (y / 40.0) ** 2
                row.append([x, y, z])
            grid.append(row)
        r_helmet = json.loads(surface_patch(control_grid=grid, degree_u=3, degree_v=3,
                                            tessellation={"u": 28, "v": 28},
                                            name="__surface_eval_helmet"))
        if r_helmet.get("object"):
            made.append(r_helmet["object"])
        ev["helmet_ok"] = bool(r_helmet.get("ok") and r_helmet.get("verts", 0) > 0)
        for key, r in (("bottle", r_bottle), ("fender", r_fender), ("helmet", r_helmet)):
            ev["%s_spec_hash_64" % key] = bool(len(str(r.get("spec_hash") or "")) == 64)
            v = json.loads(surface_validate(r.get("spec") or r.get("object"), draft=False))
            ev["%s_validate_ok" % key] = bool(v.get("ok") and v.get("verdict") in ("pass", "degraded"))
            ev["%s_validate_verdict" % key] = v.get("verdict")
        # determinism: two objects from the same spec agree coordinate by coordinate on the first 64 vertices
        r_b2 = json.loads(surface_loft(sections=sections, degree=3, continuity="G1", closed=True,
                                       tessellation={"u": 32, "v": 24}, name="__surface_eval_bottle2"))
        if r_b2.get("object"):
            made.append(r_b2["object"])
        same, meta = _meshes_equal(r_bottle.get("object"), r_b2.get("object"))
        ev["deterministic_verts"] = bool(same and r_bottle.get("spec_hash") == r_b2.get("spec_hash"))
        # ---- negative case 1: self-intersection (U-shaped path + a section larger than the curvature radius) ----
        rail_u = [[10.0 * math.sin(math.radians(a)), 10.0 * math.cos(math.radians(a)), 0.0]
                  for a in (-90, -60, -30, 0, 30, 60, 90)]
        r_bad = json.loads(surface_sweep(profile_mm=_circle_pts(18, 16.0), rail_mm=rail_u,
                                         tessellation={"u": 20, "v": 28}, closed=True,
                                         name="__surface_eval_selfint"))
        if r_bad.get("object"):
            made.append(r_bad["object"])
        v_bad = json.loads(surface_validate(r_bad.get("object"), thickness=False,
                                            self_intersection=True, draft=False))
        ev["self_intersection_caught"] = bool(v_bad.get("verdict") == "fail"
                                              and any(d.get("check") == "self_intersection"
                                                      for d in v_bad.get("defects") or []))
        # ---- negative case 2: thin wall (closed 100×100×0.5mm) ----
        import bmesh as _bm
        me = bpy.data.meshes.new("__surface_eval_thin")
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x *= 100.0
            v.co.y *= 100.0
            v.co.z *= 0.5
        bm.to_mesh(me)
        bm.free()
        thin = bpy.data.objects.new("__surface_eval_thin", me)
        bpy.context.scene.collection.objects.link(thin)
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")


def _surface_selftest_p2(st):
    _bm, r_bottle, sections, thin = st.get("_bm"), st.get("r_bottle"), st.get("sections"), st.get("thin")
    ev, made, t0 = (st.get("ev"), st.get("made"), st.get("t0"))
    try:
        made.append(str(thin.name))
        v_thin = json.loads(surface_validate(str(thin.name), min_thickness_mm=0.8,
                                             continuity=False, curvature=False))
        ev["thin_wall_caught"] = bool(v_thin.get("verdict") == "fail"
                                      and any(d.get("check") == "thickness" for d in v_thin.get("defects") or []))
        # ---- positive case: a 20mm thick closed box must pass the thickness check ----
        me2 = bpy.data.meshes.new("__surface_eval_thick")
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x *= 40.0
            v.co.y *= 40.0
            v.co.z *= 20.0
        bm.to_mesh(me2)
        bm.free()
        thick = bpy.data.objects.new("__surface_eval_thick", me2)
        bpy.context.scene.collection.objects.link(thick)
        made.append(str(thick.name))
        v_thick = json.loads(surface_validate(str(thick.name), min_thickness_mm=5.0,
                                              continuity=False, curvature=False))
        ev["thick_box_pass"] = bool(v_thick.get("verdict") == "pass")
        # ---- negative case 3: G1 discontinuity (degree=1 polyline section + centers swinging left and right) ----
        zig = []
        for k in range(4):
            zig.append({"z_mm": 30.0 * k,
                        "points_mm": _circle_pts(12, 8.0, 8.0, 20.0 * (k % 2), 0.0)})
        r_zig = json.loads(surface_loft(sections=zig, degree=1, continuity="G1", closed=True,
                                        tessellation={"u": 16, "v": 20},
                                        name="__surface_eval_zig"))
        if r_zig.get("object"):
            made.append(r_zig["object"])
        # the continuity target lives in the spec (object mode only gives a dihedral reference and does not judge fail) → it must be validated with the spec
        v_zig = json.loads(surface_validate(r_zig.get("spec"), thickness=False,
                                            self_intersection=False))
        ev["continuity_caught"] = bool(v_zig.get("verdict") == "fail"
                                       and any(d.get("check") == "continuity"
                                               for d in v_zig.get("defects") or []))
        # ---- tessellate: spec → object; object → baked object ----
        t_spec = json.loads(surface_tessellate(spec=r_bottle.get("spec"), quality="draft",
                                               name="__surface_eval_tess_spec"))
        if t_spec.get("object"):
            made.append(t_spec["object"])
        t_obj = json.loads(surface_tessellate(spec_or_object=r_bottle.get("object"),
                                              name="__surface_eval_tess_obj"))
        if t_obj.get("object"):
            made.append(t_obj["object"])
        ev["tessellate_spec_ok"] = bool(t_spec.get("ok") and t_spec.get("verts", 0) > 0)
        ev["tessellate_object_ok"] = bool(t_obj.get("ok") and t_obj.get("mode") == "object_bake")
        # ---- bad parameters ----
        bad = {}
        bad["loft_missing_sections"] = json.loads(surface_loft(sections=[])).get("ok") is False
        bad["loft_bad_units"] = json.loads(surface_loft(sections=sections, units="inch")).get("ok") is False
        bad["loft_tess_too_big"] = json.loads(surface_loft(sections=sections,
                                                           tessellation={"u": 9999, "v": 99})).get("ok") is False
        bad["patch_ragged"] = json.loads(surface_patch(control_grid=[[[0, 0, 0], [1, 0, 0]],
                                                                   [[0, 1, 0]]])).get("ok") is False
        bad["validate_missing_object"] = json.loads(surface_validate("__surface_no_such")).get("ok") is False
        bad["validate_bad_spec"] = json.loads(surface_validate({"kind": "loft", "sections": []})).get("ok") is False
        bad["blend_okfalse"] = json.loads(surface_blend(a="x", b="y")).get("ok") is False
        bad["offset_okfalse"] = json.loads(surface_offset(distance_mm=1.0)).get("ok") is False
        bad["tessellate_bad"] = json.loads(surface_tessellate(spec_or_object="__surface_no_such")).get("ok") is False
        ev["bad_params_okfalse"] = all(bad.values())
        ev["bad_params_detail"] = bad
        # ---- NaN check: every generated object's vertices are finite ----
        nan_ok = True
        for nm in made:
            ob = bpy.data.objects.get(nm)
            if ob is None or ob.type != "MESH":
                continue
            co = np.empty(len(ob.data.vertices) * 3, dtype=np.float64)
            ob.data.vertices.foreach_get("co", co)
            if not np.isfinite(co).all():
                nan_ok = False
        ev["no_nan_vertices"] = nan_ok
        ok = all(v is True for k, v in ev.items()
                 if isinstance(v, bool) and k not in ("bottle_validate_verdict", "fender_validate_verdict",
                                                      "helmet_validate_verdict"))
        return _j({"ok": bool(ok), "version": SURFACE_VERSION, "evidence": ev,
                   "ms": int((time.perf_counter() - t0) * 1000)})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")


def surface_selftest():
    """M4 self-test: three baselines — bottle body (loft) / fender (sweep) / simplified helmet (patch) — plus self-intersection/thin-wall/continuity negative cases and bad parameters."""
    ev = {}
    t0 = time.perf_counter()
    made = []
    before_objs = set(bpy.data.objects)
    st = dict(locals())
    try:
        for _fn_ in (_surface_selftest_p1, _surface_selftest_p2):
            _r = _fn_(st)
            if _r is not None:
                return _r
    except Exception as e:
        import traceback
        return _j({"ok": False, "version": SURFACE_VERSION, "evidence": ev,
                   "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                   "traceback": traceback.format_exc()[-800:]})
    finally:
        victims = list(made)
        for ob in list(bpy.data.objects):
            if str(ob.name).startswith("__surface_eval_") and ob not in before_objs:
                victims.append(str(ob.name))
        try:
            _cleanup_objects(victims)
        except Exception:
            pass



def _object_bbox_mm(ob):
    try:
        import numpy as _np
        M = ob.matrix_world
        pts = [_np.array([*(M @ v.co)]) * _KIT.units() for v in ob.data.vertices]
        return _bbox_mm(pts)
    except Exception:
        return {"min_mm": None, "max_mm": None, "size_mm": None, "center_mm": None}


def _safe_stem(text, fallback="surface"):
    s = str(text or "").strip() or fallback
    s = "".join(c if (c.isalnum() or c in "._-") else "_" for c in s)
    return (s[:80] or fallback)


def surface_export(spec_or_object=None, out_dir=None, name=None, apply_modifiers=True,
                   selection_only=True, max_tris=None):
    """Export a candidate as GLB (optionally running validate once), for external viewing/delivery.

    Units, mesh and validate all happen inside this module; the export only does "object → GLB"
    and writes no external index file, keeping the module's responsibility single.
    """
    try:
        import os
        src = spec_or_object
        if isinstance(src, dict) and "kind" not in src and src.get("object"):
            src = str(src.get("object"))
        if isinstance(src, dict):
            norm, errs = surface_spec_normalize(src)
            if errs:
                return _j({"ok": False, "op": "export", "error": "invalid spec", "detail": errs})
            ob = None
            kind = norm.get("kind")
            gen = {"loft": surface_loft, "sweep": surface_sweep, "patch": surface_patch}.get(kind)
            if gen is None:
                gen = surface_loft
            r = json.loads(gen(spec=norm) if False else gen(**({})))
            return _j({"ok": False, "op": "export", "error": "tessellate into an object before exporting",
                       "hint": "surface_tessellate(spec_or_object=<spec>) → take the object name → surface_export",
                       "detail": r.get("ok")})
        ob = bpy.data.objects.get(str(src)) if src is not None else None
        if ob is None or ob.type != "MESH":
            return _j({"ok": False, "op": "export",
                       "error": "no MESH object found: %r" % (src,),
                       "hint": "pass the object name returned by tessellate, or run surface_tessellate(spec) first"})
        tris = sum(max(0, len(p.vertices) - 2) for p in ob.data.polygons)
        if max_tris and tris > int(max_tris):
            return _j({"ok": False, "op": "export",
                       "error": "triangle count %d exceeds max_tris=%s (the panel viewer will stall; tessellate at a lower density first)"
                                % (tris, max_tris)})
        out_dir = str(out_dir) if out_dir else (bpy.path.abspath("//") or os.getcwd())
        os.makedirs(out_dir, exist_ok=True)
        stem = _safe_stem(name or ob.name)
        path = os.path.join(out_dir, stem + ".glb")
        prev_sel = [o for o in bpy.context.selected_objects]
        prev_active = bpy.context.view_layer.objects.active
        try:
            for o in list(prev_sel):
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            kwargs = {"filepath": path, "export_format": "GLB"}
            if selection_only:
                kwargs["use_selection"] = True
            if apply_modifiers:
                kwargs["export_apply"] = True
            bpy.ops.export_scene.gltf(**kwargs)
        finally:
            try:
                for o in prev_sel:
                    o.select_set(True)
                if prev_active is not None:
                    bpy.context.view_layer.objects.active = prev_active
            except Exception:
                pass
        size = os.path.getsize(path) if os.path.exists(path) else None
        out = {"ok": bool(size), "op": "export", "object": ob.name,
               "path": path, "file": os.path.basename(path), "bytes": size, "tris": tris}
        if not size:
            out["error"] = "the GLB was not written (check the exporter/permissions)"
            return _j(out)
        out["hint"] = "the GLB opens directly in an external viewer; add qc_render_views when you need reference-image IoU / materials / print checks"
        return _j(out)
    except Exception as e:
        import traceback
        return _j({"ok": False, "op": "export", "error": "%s: %s" % (type(e).__name__, e),
                   "traceback": traceback.format_exc()[-800:]})



# ────────────────────────────── M3: fit keeps the interface only (no fake implementation) ──────────────────────────────
_M3_FIT_MSG = "fit not implemented in pure-python, point-cloud/BRep solver required (M3)"


def surface_fit(*args, **kwargs):
    """M3 interface: fitting a point cloud/reference curves into a SurfaceSpec needs an external solver (this package does not depend on one), so it refuses explicitly."""
    return _err(_M3_FIT_MSG, stage="M3", op="fit", code="M3_NOT_IMPLEMENTED",
                next_action="for now supply the sections/control grid by hand with op=loft/sweep/patch; or use the vehicle_fit parametric polyline route",
                hint="pure bpy+numpy does not do robust surface fitting; it opens up once an OCCT/point-cloud fitting backend is wired in.")


def surface_help():
    return _j({
        "module": "surface.py", "version": SURFACE_VERSION,
        "what": "surface algorithm package: SurfaceSpec(M0) → loft/sweep/patch/tessellate generate a bmesh mesh (M1) → "
                "continuity/curvature/self-intersection/thickness/quality checkup (M2); M5 blend/offset explicitly not implemented (needs OCCT). Pure bpy+numpy.",
        "ops": {
            "loft": {"sig": "sections=[{z_mm,points_mm:[[x,y],...]}], degree=3, continuity=G0|G1|G2, "
                           "closed=false, tessellation={u,v}|draft|normal|fine, name?, collection?",
                     "out": "object/collection/verts/tris/bbox_mm/spec_hash/spec (reproducible)"},
            "sweep": {"sig": "profile_mm=[[x,y],...], rail_mm=[[x,y,z],...], orientation=auto|up_z|up_y|fixed, "
                            "twist_deg=0, scale=1|[...], tessellation, closed=false",
                      "out": "same as above; parallel-transport frame + per-point scale + accumulated twist"},
            "patch": {"sig": "control_grid=[[[x,y,z],...],...] (rows=u, columns=v), degree_u=3, degree_v=3, "
                            "tessellation",
                      "out": "same as above; tensor-product clamped B-spline patch"},
            "tessellate": {"sig": "spec_or_object=SurfaceSpec|object name, quality=draft|normal|fine, tessellation?",
                           "out": "spec → generate the mesh; object → bake the evaluated mesh (applies modifiers/transforms)"},
            "validate": {"sig": "spec_or_object, continuity=true, curvature=true, self_intersection=true, "
                                "thickness=true, draft=false, min_thickness_mm?, max_curvature?, max_tris=120000",
                         "out": "ok/verdict(pass|fail|degraded)/metrics/checks/defects/skipped/next"},
            "blend": {"sig": "a,b,...", "out": "M5: ok:false + 'not implemented in pure-python, OCCT backend required'"},
            "offset": {"sig": "spec_or_object,distance_mm", "out": "M5: same as above (a pure Python offset self-intersects/flips faces)"},
            "export": {"sig": "spec_or_object, out_dir, name, apply_modifiers=true, selection_only=true, max_tris?",
                       "out": "export GLB directly (viewable in the built-in workbench viewer, no three-view render needed)"},
            "fit": {"sig": "points/curves + tolerance",
                    "out": "M3: ok:false + 'not implemented in pure-python' (needs a point-cloud/BRep solver)"},
            "selftest": {"sig": "no arguments", "out": "three baselines + self-intersection/thin-wall/continuity negative cases + bad parameters"},
            "help": {"sig": "no arguments"},
        },
        "spec_schema": {"kind": "loft|sweep|patch", "units": "mm (the only supported unit)",
                        "tessellation": "{u,v} or quality",
                        "degree/continuity/closed/constraints": "loft degree/target continuity/circumferential closure/constraints",
                        "constraints": {"min_thickness_mm": "thickness target", "max_curvature_1_per_mm": "curvature upper bound",
                                        "g1_tol_deg": "G1 normal-angle tolerance", "g2_tol_ratio": "G2 curvature-jump tolerance",
                                        "closed_rail": "sweep path closure", "up": "the up vector of the fixed frame"}},
        "protocol": [
            "units: every length is mm; converted internally by scene.unit_settings.scale_length; do not pass inches straight in",
            "reproducible: the same spec (including tessellation) ⇒ the same spec_hash and identical vertices; the object name does not affect spec_hash",
            "validation reads the three-state verdict: fail = confirmed defect, degraded = a check could not run (over budget/unmeasurable), thickness is n/a on open surfaces",
            "self-intersection: a triangle count over max_tris ⇒ degraded (it is not treated as free of self-intersections); thickness is only meaningful for closed shells",
        ],
        "deps": {"required": "K.dsh_kit", "optional": "audit (you can cross-run audit_mesh as well; this module does not require it)"},
        "honest_limits": ["discrete curvature and ray thickness are both approximations", "M3 fit not implemented (needs a point-cloud/BRep solver)", "M5 blend/offset not implemented (needs OCCT)",
                          "patch/sweep continuity only checks the directions that carry a seam; a single patch has no internal seam",
                          "loft's z is linear along v (no extra swing); the section parameters are normalized by z"],
    })


# registration: K.dsh_surface_api (ops = loft/sweep/patch/tessellate/validate/blend/offset/selftest/help)
_KIT.register("surface", SURFACE_VERSION, {
    "loft": surface_loft, "sweep": surface_sweep, "patch": surface_patch,
    "tessellate": surface_tessellate, "validate": surface_validate,
    "blend": surface_blend, "offset": surface_offset, "export": surface_export,
    "fit": surface_fit, "selftest": surface_selftest, "help": surface_help})
