# -*- coding: utf-8 -*-
"""Split from audit.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .mesh import audit_duplicates, audit_mesh, audit_scene, audit_selftest, purge_orphans
from .connectivity import audit_connectivity, audit_gate
from .drift import audit_drift
from .measure import audit_measure, audit_snap_floaters
from .overlap import audit_interference, audit_overlap

def audit_gate_selftest():
    """Synthetic self-check of the assembly-level criteria: visible floaters / micro-gap tolerance / attribution / drift, all four verified together."""
    made = []
    try:
        def cube(name, loc, size):
            me = bpy.data.meshes.new(name)
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=float(size))
            bm.to_mesh(me)
            bm.free()
            ob = bpy.data.objects.new(name, me)
            ob.location = tuple(loc)
            bpy.context.scene.collection.objects.link(ob)
            made.append(ob)
            return ob
        A = cube("DSH_GATE_A", (0, 0, 0), 1.0)
        B = cube("DSH_GATE_B", (3.0, 0, 0), 0.4)        # far-away floater (span far above 1%)
        C = cube("DSH_GATE_C", (-1.0002, 0, 0), 1.0)    # other side of A: 0.0002 m = 0.2 mm away from A's x=-0.5 face (a genuine micro gap)
        D = cube("DSH_GATE_D", (6.0, 0, 0), 1.0)        # reshaped variant: non-uniform scale (per-side normalization cannot cancel it)
        D.scale = (1.0, 1.0, 1.45)
        import math as _math
        F = cube("DSH_GATE_F", (0.6, 0.6, 0.0), 0.3)    # rotated 45° about Z: its bbox overlaps A's → the bbox test says micro,
        F.rotation_euler = (0.0, 0.0, _math.radians(45.0))   # but face to face is about 150 mm — the "bbox lies" case
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        r0 = json.loads(audit_connectivity(objects=["DSH_GATE_A", "DSH_GATE_B", "DSH_GATE_C", "DSH_GATE_F"]))
        r1 = json.loads(audit_drift("DSH_GATE_A", "DSH_GATE_A"))
        r2 = json.loads(audit_drift("DSH_GATE_A", "DSH_GATE_C"))
        r3 = json.loads(audit_drift("DSH_GATE_A", "DSH_GATE_D"))
        r4f = json.loads(audit_drift("DSH_GATE_A", "DSH_GATE_D", samples=3000, fast=True))
        r4g = json.loads(audit_drift("DSH_GATE_A", "DSH_GATE_D", samples=3000, fast=False))
        agree = float(r4g.get("chamfer", 0)) >= float(r4f.get("chamfer", 0)) - 1e-9

        def floater_at(pt):
            for f in r0.get("floaters", []):
                if all(f["bbox_min"][k] - 1e-6 <= pt[k] <= f["bbox_max"][k] + 1e-6 for k in range(3)):
                    return f
            return {}
        f_b, f_f = floater_at((3.0, 0, 0)), floater_at((0.6, 0.6, 0.0))
        tol_names = {tuple(sorted(t.get("objects") or [])) for t in r0.get("tolerated", [])}
        clauses = {
            "r0_ok": r0.get("ok") is True,
            "r0_analyzed": r0.get("analyzed") is True,
            "floater_count_2": r0.get("floater_count") == 2,
            "visible_2": r0.get("visible_floater_count") == 2,
            "B_floating_far": bool(f_b) and f_b.get("gap_mm", 0) > 1000,
            "F_bbox_micro": bool(f_f) and f_f.get("bbox_micro") is True,
            "F_not_confirmed": bool(f_f) and f_f.get("mesh_confirmed") is False,
            "A_tolerated": ("DSH_GATE_A",) in tol_names,
            "C_tolerated": ("DSH_GATE_C",) in tol_names,
            "micro_tolerated_2": r0.get("micro_floater_count") == 2,
            "gate_fail": r0.get("gate", {}).get("ok") is False,
            "drift_self_small": r1.get("ok") is True and r1.get("chamfer", 1) <= 0.005,
            "movement_reported": r2.get("ok") is True and r2.get("bbox_delta", {}).get("moved_mm", 0) > 0.1,
            "drift_reshaped_big": r3.get("ok") is True and r3.get("chamfer", 0) > 0.03,
            "nn_grid_ge_bvh": bool(agree),
        }
        bad = [k for k, v in clauses.items() if not v]
        ok = not bad
        return _j({"ok": bool(ok), "failed_clauses": bad,
                   "floaters_slim": [{"rank": f["rank"], "bbox_min": f["bbox_min"], "bbox_max": f["bbox_max"],
                                      "bbox_micro": f["bbox_micro"], "mesh_confirmed": f["mesh_confirmed"],
                                      "gap_mm": f["gap_mm"], "true_gap_units": f["true_gap_units"],
                                      "attribution": (f.get("attribution") or {}).get("object")}
                                     for f in r0.get("floaters", [])],
                   "tolerated_slim": [{"rank": t["rank"], "objects": t["objects"], "gap_mm": t["gap_mm"],
                                       "mesh_confirmed": t["mesh_confirmed"],
                                       "true_gap_units": t.get("true_gap_units")}
                                      for t in r0.get("tolerated", [])],
                   "floater_count": r0.get("floater_count"),
                   "visible": r0.get("visible_floater_count"), "micro": r0.get("micro_floater_count"),
                   "real": r0.get("real_floater_count"), "gate": r0.get("gate", {}).get("state"),
                   "micro_confirm": r0.get("micro_confirm"),
                   "F_bbox_micro": f_f.get("bbox_micro"), "F_mesh_confirmed": f_f.get("mesh_confirmed"),
                   "F_confirm_note": f_f.get("confirm_note"),
                   "connectivity": r0 if not ok else "ok",
                   "drift_self": r1.get("chamfer"), "drift_shifted_chamfer": r2.get("chamfer"),
                   "drift_shifted_moved_mm": r2.get("bbox_delta", {}).get("moved_mm"),
                   "drift_reshaped": r3.get("chamfer"), "drift_reshaped_band": r3.get("band"),
                   "nn_bvh": r4f.get("chamfer"), "nn_grid": r4g.get("chamfer"), "nn_grid_ge_bvh": bool(agree),
                   "expect": "floater_count=2 (B far away + F); A/C each touch the other (0.2mm gap & interpenetration) → go to tolerated, not counted as floaters; "
                             "F bbox_micro=true but mesh_confirmed=false → judged a floater (the bbox lie must be exposed; measured nearest 1.32mm); "
                             "micro_floater_count=2, gate=fail; same mesh chamfer≈0 (≤0.005); translation does not enter chamfer but "
                             "bbox_delta.moved_mm reports the center distance; non-uniform scale chamfer>0.03 (band=strong); grid convention ≥ BVH convention"})
    except Exception as e:
        import traceback
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                   "traceback": traceback.format_exc()[-800:]})
    finally:
        for ob in made:
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
            except Exception:
                pass


def audit_help():
    return _j({"version": AUDIT_VERSION,
               "ops": {"mesh": "audit_mesh(objects|scope, envelope, eps_area, self_intersect)",
                       "scene": "audit_scene(envelope, limit)",
                       "duplicates": "audit_duplicates()",
                       "purge_orphans": "purge_orphans()",
                       "connectivity": "audit_connectivity(objects|scope|file, visible_frac, micro_gap_mm, limit, max_tris)"
                                       " → connected components / floaters / micro gaps / attribution",
                       "gate": "audit_gate(objects|scope|file, envelope, micro_gap_mm, max_floater_span_fraction)"
                               " → shipping gate (connectivity + envelope + unanalyzed three-state)",
                       "drift": "audit_drift(a, b, samples, seed) → symmetric Chamfer distance (how far the two meshes changed)",
                       "measure": "audit_measure(objects|scope|file, neighbors, k) → world bbox + per-axis gap/overlap mm/%",
                       "snap_floaters": "audit_snap_floaters(objects|scope, dry_run=true) → snap visible floaters onto their nearest neighbor",
                       "overlap": "audit_overlap(a|objects_a, b|objects_b, file_a, file_b, limit, max_tris)"
                                  " → face-to-face overlap (BVH triangle-exact): pair_count / pairs / intersection_bbox / per_object",
                       "interference": "audit_interference(a|objects_a, b|objects_b, file_a, file_b, samples, seed, "
                                       "material_mm3, max_tris, rays) → A∩B volume estimate mm³ (Monte-Carlo ray parity)"
                                       " + three-state verdict",
                       "selftest": "audit_selftest()",
                       "gate_selftest": "audit_gate_selftest() → synthetic self-check of the assembly-level criteria"},
               "file_mode": "v0.9.1: connectivity / gate / measure all accept file=<.blend path> — "
                            "the objects in the file are **temporarily** appended into the session to run the same chain, then deleted in finally (objects/temp collections/"
                            "newly created orphan data/library entries), and the response gives source / file_load / cleanup; objects/scope then "
                            "act as an **object-name filter inside the file** (append brings no collection membership)."
                            "overlap / interference accept file_a/file_b on both ends (giving a/b as .blend paths directly also works).",
               "fields": "boundary_edges / nonmanifold_edges / degenerate_faces / loose_verts / loose_edges / "
                         "self_intersections / normals_outward / closed / tris / aabb / out_of_bounds;"
                         "mesh side three-state: state(=verdict) / reason / analysis{self_intersections,normals,incomplete_objects} / "
                         "normals_state{pass|fail|unknown|n/a} / normals_shells[{shell,signed_volume,closed,"
                         "winding_consistent,nested,relation,state}] / self_intersections_analyzed / "
                         "self_intersections_state{pass|fail|skipped|error};"
                         "assembly side: components / floaters[{span_fraction, gap_mm, bbox_micro, mesh_confirmed, true_gap_units, attribution}] / "
                         "tolerated[] (confirmed touching) / unconfirmed[] (unconfirmed → degraded) / gap_histogram / gate{state,offenders};"
                         "cross-part side: pair_count / pairs[{tri_a,tri_b,point,segment_len_mm}] / intersection_bbox / "
                         "overlap_faces_bbox / per_object / volume_mm3 / volume_ci95_mm3 / verdict{supported|refuted|unresolved} / why",
               "units": "thresholds in mm are always converted through the scene scale_length (the response has a units block); volume also gives volume_units3 and "
                        "volume_mm3 (units.volume_units3_to_mm3)",
               "honest_limits": "overlap: overlap() is **true triangle-triangle intersection**, but **coplanar faces that overlap each other are not reported** (measured) → "
                                "for coplanar contact use contact_probe; interference: Monte-Carlo is **not an exact boolean**, "
                                "non-manifold/open meshes are always unresolved (no number given); error ∝1/√samples (convention in error_caliber)",
               "hard_rule": "0 meshes ⇒ ok=false (a silent empty result must fail); large meshes ⇒ analyzed=false, "
                            "unanalyzed must not be read as connected/overlap-free; file= fails to open/no meshes/all hidden ⇒ ok=false"})


def audit_dispatch(op, args=None):
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
    ops = {"mesh": audit_mesh, "scene": audit_scene, "duplicates": audit_duplicates,
           "purge_orphans": purge_orphans, "selftest": audit_selftest, "help": audit_help,
           "connectivity": audit_connectivity, "gate": audit_gate, "drift": audit_drift,
           "measure": audit_measure, "snap_floaters": audit_snap_floaters,
           "overlap": audit_overlap, "interference": audit_interference,
           "gate_selftest": audit_gate_selftest}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown audit op", "op": op, "ops": sorted(ops)})
    try:
        return fn(**kw)
    except TypeError as e:
        msg = str(e)[:200]
        out = {"ok": False, "error": "argument mismatch: %s" % msg, "op": op, "help": audit_help(),
               "given": sorted(kw)}
        # targeted hint (measured feedback 2026-09-30): file= is accepted by only some ops, and a generic "argument mismatch"
        # makes the agent retry blindly (4 agents in the QBZ-191 project independently hit the same trap).
        bad = [k for k in ("file", "file_a", "file_b")
               if k in kw and ("unexpected keyword argument '%s'" % k) in msg]
        if bad:
            takes_file = ["connectivity", "gate", "measure", "overlap", "interference"]
            out["error_hint"] = (
                "`audit_%s` does not accept %s — across the whole audit family only %s accept file="
                "(overlap / interference use file_a / file_b)."
                "To run a single-part self-check on a part in **another .blend**, there is exactly one path:"
                "first bpy.ops.wm.open_mainfile(filepath=PATH) to actually open it,"
                "then audit_mesh(objects=[...]) (in headless, after preload=\"audit\", "
                "K.dsh_audit_api(\"mesh\", {...}) with the same convention)."
                % (op, "/".join(bad), " / ".join("audit_" + t for t in takes_file)))
            out["file_arg_ops"] = takes_file
        return _j(out)


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_audit_api = _DshApi({"version": AUDIT_VERSION, "dispatch": audit_dispatch, "mesh": audit_mesh,
                                "scene": audit_scene, "duplicates": audit_duplicates,
                                "purge_orphans": purge_orphans,
                                "connectivity": audit_connectivity, "gate": audit_gate, "drift": audit_drift,
                                "measure": audit_measure, "snap_floaters": audit_snap_floaters,
                                "overlap": audit_overlap, "interference": audit_interference,
                                "selftest": audit_selftest, "gate_selftest": audit_gate_selftest,
                                "help": audit_help})
