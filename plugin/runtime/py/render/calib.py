# -*- coding: utf-8 -*-
"""DSH gate calibration suite (v0.9.6 · consolidated design) — answers one question: **what can your gates actually catch?**

"The value ceiling of the plugin is set by your own gates" — and what sets the ceiling of the gates? **The defects they cannot catch.**
So: deliberately inject several classes of known defects and see whether each class is caught by some gate; at the same time run a **healthy baseline** (which must pass
everything), otherwise the gates are producing false positives and the calibration result is invalid.

    healthy baseline (all 4 gates pass)  ← the false-positive control; if it fails the whole calibration is void
    8 defect classes injected            → each judged caught / missed
    ⇒ capture rate + missed list + who caught it (which gate)

**Usage**: run it in a **headless clean scene** (it creates/deletes objects temporarily, and the dup gate needs a clean scene):
    blender_rt_headless(preload="calib", script='print("HEADLESS " + K.dsh_calib_api("run", {}))')
or via plan: blender_rt_plan(op="calib_run")   (it starts its own headless process)
"""
import json
import time

import bpy
import bmesh

CALIB_VERSION = 2
PFX = "__dsh_calib_"
# this suite's geometry is written in **mm** (3mm plate, 1.5mm interpenetration), and the gates' units are mm too (micro 0.3mm / min_mm 1.0)
# — so the baseline **and every defect class** must run at 1 unit = 1 mm. Previously CALIB_SCALE was set only for the baseline while the
# defect stage reset back to the scene units (prev_scale); the two stages used different units ⇒ the capture rate was not trustworthy (fixed in the v0.9.6 review).
CALIB_SCALE = 0.001


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("calib needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation was removed)
_api = _KIT.api  # shared kernel
def _purge():
    for o in [x for x in bpy.data.objects if x.name.startswith(PFX)]:
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        try:
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass
    for m in [x for x in bpy.data.meshes if x.name.startswith(PFX)]:
        try:
            bpy.data.meshes.remove(m, do_unlink=True)
        except Exception:
            pass
    for m in [x for x in bpy.data.materials if x.name.startswith(PFX)]:
        try:
            bpy.data.materials.remove(m, do_unlink=True)
        except Exception:
            pass


def _mk(name, builder, loc=(0, 0, 0)):
    """builder(bm) adds geometry to the bmesh; returns the object name."""
    me = bpy.data.meshes.new(PFX + name)
    ob = bpy.data.objects.new(PFX + name, me)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    bm = bmesh.new()
    builder(bm)
    bm.to_mesh(me)
    bm.free()
    return ob.name


def _build_healthy(with_rivet=True, with_selfint=False):
    """Healthy assembly: base plate (3mm thick) + two posts (**interpenetrating** the plate by 1mm, as the process requires) ± rivet."""
    import mathutils

    def plate(bm):
        bmesh.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Diagonal((40.0, 30.0, 3.0, 1.0)))

    def post(bm):
        bmesh.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Diagonal((8.0, 8.0, 20.0, 1.0)))

    names = [_mk("plate", plate)]
    names.append(_mk("post_a", post, loc=(-10.0, 0.0, 10.0)))    # bottom face z=0 interpenetrates the plate's top face z=1.5
    names.append(_mk("post_b", post, loc=(10.0, 0.0, 10.0)))
    if with_rivet:
        names.append(_mk("rivet", post, loc=(0.0, 0.0, 4.0)))
    if with_selfint:
        def two(bm):
            bmesh.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Diagonal((6.0, 6.0, 6.0, 1.0)))
            bmesh.ops.create_cube(bm, size=1.0,
                                  matrix=mathutils.Matrix.Translation((3.0, 0.0, 0.0)) @ mathutils.Matrix.Diagonal((6.0, 6.0, 6.0, 1.0)))
        names.append(_mk("selfint", two, loc=(0.0, 25.0, 3.0)))
    bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]
    return names


SPEC_TMPL = {"name": "calib", "units": "mm", "tolerance_mm": 1.0, "gates": [
    {"id": "mesh", "op": "audit_mesh", "args": {}, "pass_if": "clean == True and totals[\"self_intersections\"] == 0"},
    {"id": "connectivity", "op": "audit_gate", "args": {}, "pass_if": "verdict == 'pass'"},
    {"id": "print", "op": "print_report", "args": {"min_mm": 1.0},
     "pass_if": "worst_p05_mm >= 1.0 and walls_ok == True"},
    {"id": "duplicates", "op": "audit_duplicates", "args": {"top_k": 5}, "pass_if": "len(materials) + len(meshes) == 0"},
]}


def _spec_for(names, break_gates=None):
    sp = json.loads(_j(SPEC_TMPL))
    sp["gates"][0]["args"] = {"objects": names, "self_intersect": True, "summary_only": True}
    sp["gates"][1]["args"] = {"objects": names}
    sp["gates"][2]["args"] = {"objects": names, "min_mm": 1.0}
    broken = set(str(x) for x in (break_gates or []))
    for g in sp["gates"]:
        if g["id"] in broken:
            # deliberately make this gate into an error (pass_if references a field that does not exist in the receipt) — used to prove
            # that "the gate could not run" is never recorded as "caught a defect" (for regression tests).
            g["pass_if"] = "definitely_not_a_field == 1"
    return sp


def _classify_defect(gates, expect):
    """Judge one gate receipt as a "real capture" (fixed in the v0.9.6 review).

    **Only state == 'fail' counts as a capture**. It used to be `caught = verdict != 'pass'` — so
      * error (the gate could not run: module not injected / pass_if wrong / the op threw)
      * degraded (the gate gave no verdict)
    were all recorded as "caught", inflating the capture rate (measured in practice: with the print module removed it still reported 8/8, where thin_wall nominally
    was only "caught" by print, and that gate was in fact error). The criterion is "the corresponding gate really fails", not "the whole package is not pass".

    Returns (caught, fails, errors, degraded).
    """
    gs = [g for g in (gates or []) if isinstance(g, dict)]
    fails = [g.get("id") for g in gs if g.get("state") == "fail"]
    errors = [g.get("id") for g in gs if g.get("state") == "error"]
    degraded = [g.get("id") for g in gs if g.get("state") == "degraded"]
    exp = [g for g in gs if g.get("id") == expect]
    caught = bool(exp) and exp[0].get("state") == "fail"
    return bool(caught), fails, errors, degraded


def _scale_now():
    try:
        return float(bpy.context.scene.unit_settings.scale_length)
    except Exception:
        return None


def _near(a, b, tol=1e-6):
    """scale_length is a **float32** attribute (0.001 is stored as 0.001000000047...) ⇒ comparisons need a relative tolerance."""
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    except Exception:
        return False


# ---------------------------------------------------------------- defect injection

def _d_delete_face(names, ctx):
    ob = bpy.data.objects[names[1]]
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES_ONLY")
    bm.to_mesh(ob.data); bm.free()
    return "deleted one face of the post (an opening → boundary_edges)"


def _d_flip_normals(names, ctx):
    ob = bpy.data.objects[names[1]]
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(ob.data); bm.free()
    return "flipped every normal on the post"


def _d_loose_verts(names, ctx):
    ob = bpy.data.objects[names[1]]
    bm = bmesh.new(); bm.from_mesh(ob.data)
    for p in ((0, 0, 0), (5, 5, 5)):
        bm.verts.new(p)
    bm.to_mesh(ob.data); bm.free()
    return "added two loose vertices (leftover point cloud)"


def _d_self_intersect(names, ctx):
    extra = _build_healthy(with_rivet=False, with_selfint=True)
    ctx["extra"] = [n for n in extra if n.startswith(PFX + "selfint")]
    return "added a self-intersecting part (two shells interpenetrating inside one object)"


def _d_shift_detach(names, ctx):
    ob = bpy.data.objects[names[1]]
    ob.location = (ob.location[0], ob.location[1] + 60.0, ob.location[2])
    return "moved the post 60mm so it detaches from the plate (a genuine floater)"


def _d_floater(names, ctx):
    def cube(bm):
        import mathutils
        bmesh.ops.create_cube(bm, size=6.0, matrix=mathutils.Matrix.Diagonal((6.0, 6.0, 6.0, 1.0)))
    ctx["extra"] = [_mk("floater", cube, loc=(0.0, 80.0, 3.0))]
    return "left one isolated part far away"


def _d_thin_wall(names, ctx):
    bpy.context.scene.unit_settings.scale_length = CALIB_SCALE   # 1 unit = 1 mm (consistent with the whole run)
    ob = bpy.data.objects[names[0]]
    ob.scale = (1.0, 1.0, 0.1)                                # plate 3mm → 0.3mm
    return "thinned the plate to 0.3mm (below min_mm=1.0)"


def _d_dup_resource(names, ctx):
    me = bpy.data.meshes.new(PFX + "DupMesh")
    bpy.data.objects.new(PFX + "dup_holder_a", me)
    me2 = bpy.data.meshes.new(PFX + "DupMesh.001")
    bpy.data.objects.new(PFX + "dup_holder_b", me2)
    for n in (PFX + "DupMat", PFX + "DupMat.001"):
        bpy.data.materials.new(n).use_nodes = True
    return "created same-name forked resources (Foo / Foo.001)"


DEFECTS = [
    # (id, injector, **the gate that should catch it**, why that one)
    ("delete_face", _d_delete_face, "mesh", "an opening ⇒ boundary/nonmanifold ⇒ clean=false"),
    ("flip_normals", _d_flip_normals, "mesh", "the whole single shell faces inward ⇒ normals_inverted ⇒ clean=false"),
    ("loose_verts", _d_loose_verts, "mesh", "loose vertices ⇒ loose_verts>0 ⇒ clean=false (fixed in v0.9.6)"),
    ("self_intersect", _d_self_intersect, "mesh", "two shells interpenetrating in the same object ⇒ self_intersections>0"),
    ("shift_detach", _d_shift_detach, "connectivity", "the post detaches from the plate ⇒ a visible floater"),
    ("floater", _d_floater, "connectivity", "an isolated part far away ⇒ a visible floater"),
    ("thin_wall", _d_thin_wall, "print", "plate 0.3mm < min_mm=1.0"),
    ("dup_resource", _d_dup_resource, "duplicates", "Foo / Foo.001 same-name fork"),
]
DEFECT_TABLE = {d[0]: {"fn": d[1], "expect": d[2], "why": d[3]} for d in DEFECTS}


def _calib_pick(ids):
    """Which defects to run (ids may be empty/single/list); returns (want, err)."""
    want = [d[0] for d in DEFECTS]
    if ids:
        want = [str(x) for x in (ids if isinstance(ids, (list, tuple)) else [ids])]
        bad = [x for x in want if x not in DEFECT_TABLE]
        if bad:
            return None, {"ok": False, "error": "unknown defect id %s" % bad, "allowed": [d[0] for d in DEFECTS]}
    return want, None


def _calib_baseline(gate, broken):
    """Healthy baseline (must pass everything, otherwise the gates are producing false positives and the calibration is invalid); returns the baseline record."""
    # the whole chain (baseline + every defect class) is unified to mm; the scene units are reset once, only in finally
    bpy.context.scene.unit_settings.scale_length = CALIB_SCALE
    _purge()
    names = _build_healthy()
    sp = _spec_for(names, break_gates=broken)
    base = gate("run", {"spec": sp})          # _DshApi already parses it, do not json.loads again
    b_gates = [{"id": g.get("id"), "state": g.get("state")} for g in base.get("gates", [])]
    b_fail = [g["id"] for g in b_gates if g.get("state") == "fail"]
    b_err = [g["id"] for g in b_gates if g.get("state") == "error"]
    b_deg = [g["id"] for g in b_gates if g.get("state") == "degraded"]
    return {"verdict": base.get("verdict"), "failed": base.get("failed"), "gates": b_gates,
            "errors": b_err, "degraded": b_deg, "unit_scale": _scale_now(),
            "ok": bool(base.get("verdict") == "pass" and not b_err and not b_deg
                       and not b_fail)}


def _calib_defect(gate, did, broken):
    """Inject one defect class + judge the capture with the **corresponding gate**; returns the row (injection/execution exceptions also land in the row, without aborting the whole round)."""
    fn, expect = DEFECT_TABLE[did]["fn"], DEFECT_TABLE[did]["expect"]
    ctx = {}
    bpy.context.scene.unit_settings.scale_length = CALIB_SCALE
    _purge()
    row = {"id": did, "expect": expect, "unit_scale": _scale_now()}
    try:
        names = _build_healthy()
        note = fn(names, ctx)
        for n in ctx.get("extra") or []:
            if n not in names:
                names.append(n)
        row["injected"] = note
        # the defect function may have changed the units itself (e.g. thin_wall writes scale_length) ⇒ pull the calibration units back before running the gates,
        # so that "the injected defect" and "the gate's units" are compared in the same unit (otherwise the 0.3mm threshold may become 0.3 units)
        bpy.context.scene.unit_settings.scale_length = CALIB_SCALE
        sp = _spec_for(names, break_gates=broken)
        r = gate("run", {"spec": sp})
        caught, fails, errors, degraded = _classify_defect(r.get("gates"), expect)
        row.update({"caught": bool(caught), "verdict": r.get("verdict"),
                    "caught_by": fails, "caught_by_expected_gate": bool(expect in fails),
                    "gate_errors": errors, "gate_degraded": degraded,
                    "detail": {g.get("id"): g.get("key") for g in r.get("gates", [])
                               if g.get("state") != "pass"}})
        if not caught:
            row["naive_caught"] = bool(r.get("verdict") != "pass")   # the old criterion would misrecord this as caught
            if expect in errors:
                row["why_missed"] = "the corresponding gate %s itself errored — a gate that cannot run != a caught defect" % expect
            elif expect in degraded:
                row["why_missed"] = "the corresponding gate %s only returned degraded — no verdict != a caught defect" % expect
            else:
                row["why_missed"] = "the corresponding gate %s did not fail (a genuine miss)" % expect
    except Exception as e:
        row.update({"caught": None, "why_missed": "injection/execution exception",
                    "error": "%s: %s" % (type(e).__name__, str(e)[:180])})
    finally:
        # ← reset to CALIB_SCALE (not prev_scale): the remaining calibration stages stay in the same units
        try:
            bpy.context.scene.unit_settings.scale_length = CALIB_SCALE
        except Exception:
            pass
        _purge()
    return row


def _calib_receipt(rows, baseline, prev_scale, scale_after, broken, t0):
    """Summary receipt: ok/capture_rate/missed/unit_ok + the rule and the hints."""
    caught = [r for r in rows if r.get("caught") is True]
    missed = [r["id"] for r in rows if r.get("caught") is not True]
    gate_errors = sorted({g for r in rows for g in (r.get("gate_errors") or [])} |
                         set((baseline or {}).get("errors") or []))
    # this only counts as a problem when "that gate is exactly the corresponding gate of some defect" (already reflected in missed); other gate errors are noise/warnings
    blocking_errors = sorted({g for r in rows for g in (r.get("gate_errors") or []) if g == r.get("expect")})
    false_captures = [{"id": r["id"], "naive_verdict": r.get("verdict"), "why": r.get("why_missed")}
                      for r in rows if r.get("caught") is not True and r.get("naive_caught")]
    baseline_ok = bool(baseline and baseline.get("ok"))
    unit_ok = bool(
        prev_scale is not None and scale_after is not None and _near(scale_after, prev_scale)
        and all(_near(r.get("unit_scale"), CALIB_SCALE) for r in rows))
    ok = bool(baseline_ok and not missed and unit_ok)
    warnings = []
    if gate_errors:
        warnings.append("some gates reported error in the actual run: %s — error does not count as a capture (a gate that cannot run != a caught defect), "
                        "capture_rate already excludes them under the new criterion" % gate_errors)
    if false_captures:
        warnings.append("under the old criterion (verdict != pass) the cases in false_captures would be misrecorded as captured")
    return {"ok": ok, "baseline_pass": baseline_ok, "baseline": baseline,
            "defects": rows, "caught": len(caught), "total": len(rows),
            "capture_rate": (round(len(caught) / float(len(rows)), 3) if rows else None),
            "missed": missed, "gate_errors": gate_errors, "blocking_gate_errors": blocking_errors,
            "false_captures": false_captures, "warnings": warnings,
            "units": {"calib_scale": CALIB_SCALE, "scene_before": prev_scale, "scene_after": scale_after,
                      "defect_scales": sorted({r.get("unit_scale") for r in rows},
                                              key=lambda x: (x is None, x)),
                      "unit_ok": unit_ok},
            "valid_run": baseline_ok, "unit_ok": unit_ok, "break_gates": broken,
            "rule": "captured ⇔ the defect's **corresponding gate** (defects[].expect) has state=='fail';"
                    "error/degraded never count as a capture",
            "note": ("the healthy baseline must pass completely (otherwise the gates are producing false positives and the calibration is invalid); every defect class must be caught by the **corresponding gate** (defects[].expect)"
                     " with state='fail' — error (the gate cannot run)/degraded (no verdict) do not count as a capture;"
                     "the missed ids are exactly the gates you still have to add" if baseline_ok else
                     "⚠ the healthy baseline did not pass ⇒ this calibration is invalid: first look at which gate in baseline.gates is error/degraded/fail"
                     " (gate misconfigured / module not injected / scene not clean); please run in a headless factory scene"),
            "ms": int((time.time() - t0) * 1000)}


def calib_run(ids=None, keep=False, prefix_note=None, break_gates=None):
    """Run the calibration: healthy baseline (must pass completely) + every defect class (must really be caught by the **corresponding gate**).

    v0.9.6 (review fixes):
      ① the capture criterion changed from "the whole package's verdict != pass" to "**the corresponding gate's state == fail**" — error (the gate cannot run)
         and degraded (no verdict) do not count as captures, avoiding an inflated capture rate;
      ② units unified: the baseline and every defect class run at CALIB_SCALE (1 unit = 1 mm), and finally resets the scene units;
         every row receipt carries unit_scale, and unit_ok is reported at the end.
    break_gates=["mesh", ...] deliberately turns some gates into errors, used to verify ① (regression test).
    """
    gate = _api("gate")
    if gate is None:
        return _j({"ok": False, "error": "the gate module is required (preload=\"calib,gate\" or use the calib_run op)"})
    want, perr = _calib_pick(ids)
    if perr:
        return _j(perr)
    broken = [str(x) for x in (break_gates if isinstance(break_gates, (list, tuple, set)) else ([break_gates] if break_gates else []))]
    t0 = time.time()
    prev_scale = _scale_now()
    scale_after = None
    rows = []
    baseline = None
    try:
        baseline = _calib_baseline(gate, broken)
        _purge()
        for did in want:
            rows.append(_calib_defect(gate, did, broken))
    finally:
        try:
            bpy.context.scene.unit_settings.scale_length = prev_scale
            scale_after = _scale_now()
        except Exception:
            scale_after = None
        if not keep:
            _purge()
    return _j(_calib_receipt(rows, baseline, prev_scale, scale_after, broken, t0))



def calib_selftest():
    """Self-check: the baseline must pass; all 8 defect classes must really be caught by **their own corresponding gate**; the units must be reset to the original value afterwards.

    Two regressions are pinned too (v0.9.6 review fixes):
      ① the classifier: error / degraded do **not** count as captures ("a gate that cannot run" != "a caught defect");
      ② with one gate removed (break_gates), ok must be false and gate_errors non-empty — no fake pass allowed.
    """
    # ① pure classifier unit test (does not depend on the scene)
    g_err = [{"id": "mesh", "state": "error"}, {"id": "connectivity", "state": "pass"}]
    g_deg = [{"id": "print", "state": "degraded"}]
    g_fail = [{"id": "mesh", "state": "fail"}]
    c1 = _classify_defect(g_err, "mesh")
    c2 = _classify_defect(g_deg, "print")
    c3 = _classify_defect(g_fail, "mesh")
    c4 = _classify_defect([{"id": "mesh", "state": "pass"}], "mesh")
    classifier_ok = (c1[0] is False and c2[0] is False and c3[0] is True and c4[0] is False
                     and c1[1] == [] and c1[2] == ["mesh"] and c2[3] == ["print"])
    r = json.loads(calib_run())
    # ② deliberately make the mesh gate error: delete_face/flip_normals/loose_verts/self_intersect must not be recorded as "caught" because of that
    rb = json.loads(calib_run(ids=["delete_face", "loose_verts"], break_gates=["mesh"]))
    broken_rows = rb.get("defects") or []
    broken_ok = (rb.get("ok") is False and bool(rb.get("gate_errors"))
                 and all(x.get("caught") is not True for x in broken_rows)
                 and all(x.get("caught_by_expected_gate") is False for x in broken_rows))
    return _j({"ok": bool(classifier_ok and r.get("valid_run") and r.get("unit_ok")
                          and (r.get("capture_rate") or 0) >= 1.0 and not r.get("missed") and broken_ok),
               "classifier_rejects_error_and_degraded": classifier_ok,
               "broken_gate_not_counted_as_caught": broken_ok,
               "capture_rate": r.get("capture_rate"), "missed": r.get("missed"),
               "baseline_pass": r.get("baseline_pass"), "unit_ok": r.get("unit_ok"),
               "units": r.get("units"),
               "evidence": {"caught": r.get("caught"), "total": r.get("total"),
                            "gate_errors": r.get("gate_errors"),
                            "baseline_failed": (r.get("baseline") or {}).get("failed"),
                            "expect_map": {d["id"]: d["expect"] for d in (r.get("defects") or [])}}})


def calib_help():
    return _j({
        "module": "calib.py", "version": CALIB_VERSION,
        "what": "gate calibration: inject 8 known defect classes and measure how many of them your gates catch; the healthy baseline doubles as the false-positive control",
        "defects": [{"id": d[0], "expect_gate": d[2], "why": d[3]} for d in DEFECTS],
        "gates_used": [g["id"] + " → " + g["op"] for g in SPEC_TMPL["gates"]],
        "ops": ["calib_run (everything, or ids=[...]; break_gates=[...] deliberately makes gates error for regressions)",
                "calib_selftest", "calib_help"],
        "capture_rule": "only **the corresponding gate's state=='fail'** counts as a capture; error (the gate cannot run)/degraded (no verdict) do not — "
                        "the old criterion 'verdict != pass means caught' lets broken gates inflate the capture rate",
        "units": "the baseline and every defect class run at scale_length=%s (1 unit = 1 mm), and the scene units are reset afterwards; "
                 "a receipt with units.unit_ok=false means the units were not kept under control and this run's conclusion is not trustworthy" % CALIB_SCALE,
        "how": ["prefer blender_rt_plan(op='calib_run') (the plugin starts its own headless clean scene)",
                "or blender_rt_headless(preload='calib,gate,printcheck', "
                "script='print(\"HEADLESS \" + K.dsh_calib_api(\"run\", {}))')"],
        "reading": ["baseline_pass=false ⇒ this calibration is invalid (the gates are producing false positives / are misconfigured / the scene is not clean)",
                    "the missed list = the blind spots of your gates = the gates to add next",
                    "gate_errors non-empty ⇒ some gate never ran at all; fix the gates before talking about capture rate",
                    "false_captures ⇒ the cases the old criterion would misjudge as captured",
                    "capture_rate is **one number** for this project's gate strength; after changing/adding gates just run it again and compare"],
    })


def calib_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    kw = {}
    for k, v in (args or {}).items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    ops = {"run": calib_run, "selftest": calib_selftest, "help": calib_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown calib op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unknown parameters %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_calib_api = _DshApi({"version": CALIB_VERSION, "dispatch": calib_dispatch,
                                "run": calib_run, "selftest": calib_selftest, "help": calib_help})
