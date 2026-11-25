# -*- coding: utf-8 -*-
"""Split from gate.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .plan import _aggregate, _collect_echo, _eval_pass_if, _path_get, _status_of, gate_plan
from .run import gate_run


def _gate_selftest_p1(st):
    try:
        import bmesh  # noqa: F401  # handed to the next split stage through st
        ev = {}
        made = []
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _gate_selftest_p2a(st):
    bmesh, ev, made = st["bmesh"], st["ev"], st["made"]
    try:
        me = bpy.data.meshes.new("__dsh_gate_selftest")
        ob = bpy.data.objects.new("__dsh_gate_selftest", me)
        bpy.context.scene.collection.objects.link(ob)
        made.append(ob.name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        spec = {"name": "selftest", "units": "mm", "tolerance_mm": 1.0, "gates": [
            {"id": "ok_gate", "op": "audit_mesh", "args": {"objects": [ob.name]}, "pass_if": "clean == True"},
            {"id": "bad_gate", "op": "audit_mesh", "args": {"objects": [ob.name]}, "pass_if": "boundary_edges > 999999"},
        ]}
        plan = json.loads(gate_plan(spec=spec))
        ev["plan"] = {"ok": plan.get("ok"), "gates": plan.get("gate_count"),
                      "reads": (plan.get("gates") or [{}])[0].get("reads")}
        r = json.loads(gate_run(spec=spec))
        ev["run"] = {"verdict": r.get("verdict"), "ok": r.get("ok"), "failed": r.get("failed"),
                     "states": [g.get("state") for g in r.get("gates", [])],
                     "key0": (r.get("gates") or [{}])[0].get("key")}
        ok1 = (plan.get("ok") and r.get("verdict") == "fail" and r.get("ok") is False
               and r.get("failed") == ["bad_gate"] and r["gates"][0]["state"] == "pass")
        # an all-passing package ⇒ verdict=pass, ok=true
        spec2 = {"name": "selftest-pass", "gates": [
            {"id": "a", "op": "audit_mesh", "args": {"objects": [ob.name]}, "pass_if": "clean == True"}]}
        r2 = json.loads(gate_run(spec=spec2))
        ev["pass_case"] = {"verdict": r2.get("verdict"), "ok": r2.get("ok")}
        # the three-state rule is unit-tested directly (not by "contriving a really degraded scenario"): ok=null ⇒ degraded, and degraded must not count as pass
        ev["tri_state_unit"] = {
            "degraded": _status_of({"ok": None, "state": "degraded"}),
            "fail": _status_of({"ok": False}),
            "pass": _status_of({"ok": True, "clean": True}),
            "error": _status_of("not-a-dict"),
            "agg_degraded": _aggregate(["pass", "degraded"]),
            "agg_fail_beats_degraded": _aggregate(["degraded", "fail"]),
            "agg_all_pass": _aggregate(["pass", "pass"]),
        }
        u = ev["tri_state_unit"]
        ev["tri_state_ok"] = (u["degraded"] == "degraded" and u["fail"] == "fail" and u["pass"] == "pass"
                              and u["error"] == "error" and u["agg_degraded"] == "degraded"
                              and u["agg_fail_beats_degraded"] == "fail" and u["agg_all_pass"] == "pass")
        # v0.9.6 unit level: **nested three-state** (audit_connectivity's gate conclusion inside gate) + **skipped aggregation (tightened in v3)**
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _gate_selftest_p2b(st):
    ev = st["ev"]
    try:
        ev["nested_tri_unit"] = {
            "conn_pass": _status_of({"ok": True, "analyzed": True, "gate": {"ok": True, "state": "pass", "verdict": "pass"}}),
            "conn_fail": _status_of({"ok": True, "analyzed": True, "gate": {"ok": False, "state": "fail", "verdict": "fail"}}),
            "conn_unanalyzed": _status_of({"ok": True, "analyzed": False,
                                           "gate": {"ok": None, "state": "degraded", "verdict": "degraded"}}),
            "inter_unresolved": _status_of({"ok": True, "analyzed": True, "verdict": "unresolved"}),
            "inter_refuted_is_pass": _status_of({"ok": True, "analyzed": True, "verdict": "refuted"}),
            # v3 (Lead vetoed pass+skipped=pass): any skipped ⇒ top level degraded
            "agg_pass_skipped": _aggregate(["pass", "skipped"]),
            "agg_only_skipped": _aggregate(["skipped"]),
            "agg_degraded_skipped": _aggregate(["degraded", "skipped"]),
            "agg_fail_skipped": _aggregate(["fail", "skipped"]),
            "agg_fail_skipped_degraded": _aggregate(["skipped", "degraded", "fail", "pass"]),
            "agg_empty": _aggregate([]),
        }
        n = ev["nested_tri_unit"]
        ev["nested_tri_ok"] = (n["conn_pass"] == "pass" and n["conn_fail"] == "fail"
                               and n["conn_unanalyzed"] == "degraded" and n["inter_unresolved"] == "degraded"
                               and n["inter_refuted_is_pass"] == "pass"
                               and n["agg_pass_skipped"] == "degraded" and n["agg_only_skipped"] == "degraded"
                               and n["agg_degraded_skipped"] == "degraded" and n["agg_fail_skipped"] == "fail"
                               and n["agg_fail_skipped_degraded"] == "fail" and n["agg_empty"] == "degraded")
        # v3 unit level: degrade_if — the criterion is true but the evidence is untrustworthy ⇒ degraded (no fake pass).
        # Run a synthetic receipt straight through the **print preset's real expression**: resolution 1000mm vs min_mm 2mm ⇒ hit;
        # resolution 0.1mm ⇒ no hit ("degrade only when the resolution is untrustworthy"). echo walks dot paths for real fields.
        _preset_print = PRESETS["print"]["gates"][0]
        _dg_expr = _preset_print["degrade_if"]
        _coarse = {"warnings": [], "params": {"min_mm": 2.0},
                   "detail": {"walls": {"objects": [{"resolution_mm": 1000.0}]}}}
        _fine = {"warnings": [], "params": {"min_mm": 2.0},
                 "detail": {"walls": {"objects": [{"resolution_mm": 0.1}]}}}
        # v1.0.5 (issue #14): the bed_warning summary for the overhang side sits in the top-level warnings[] — non-empty must force degradation too
        _warned = {"warnings": ["Bed face height 0.5 is 0.5 mm above the set's lowest point 0.0"], "params": {"min_mm": 2.0},
                   "detail": {"walls": {"objects": [{"resolution_mm": 0.1}]}}}
        ev["degrade_if_unit"] = {
            "expr": _dg_expr,
            "coarse_hits": _eval_pass_if(_dg_expr, _coarse),
            "fine_hits": _eval_pass_if(_dg_expr, _fine),
            "warned_hits": _eval_pass_if(_dg_expr, _warned),
            "path_ok": _path_get(_coarse, "detail.walls.objects.0.resolution_mm") == (1000.0, True),
            "path_missing": _path_get(_coarse, "detail.walls.objects.9.resolution_mm")[1] is False,
            "echo": _collect_echo(_coarse, _preset_print.get("echo")),
            "plan_echo": (json.loads(gate_plan(preset="print"))["gates"][0] or {}).get("echo"),
        }
        ev["degrade_if_ok"] = bool(ev["degrade_if_unit"]["coarse_hits"] is True
                                   and ev["degrade_if_unit"]["fine_hits"] is False
                                   and ev["degrade_if_unit"]["warned_hits"] is True
                                   and ev["degrade_if_unit"]["path_ok"]
                                   and ev["degrade_if_unit"]["path_missing"]
                                   and ev["degrade_if_unit"]["echo"].get("params.min_mm") == 2.0
                                   and "warnings" in (ev["degrade_if_unit"]["plan_echo"] or [])
                                   and ev["degrade_if_unit"]["plan_echo"])
        # preset static contract (v3's skip/degrade fields): the gates are still there, the fields each reads are real, gates without a source get skipped
        pp = json.loads(gate_plan(preset="assembly"))
        _by = {x["id"]: x for x in (pp.get("gates") or [])}
        ev["preset_assembly"] = {
            "gate_count": pp.get("gate_count"),
            "mesh_self_intersect": (_by.get("mesh_health", {}).get("args") or {}).get("self_intersect"),
            "no_floaters_reads": _by.get("no_floaters", {}).get("reads"),
            "no_clash_reads": _by.get("no_clash", {}).get("reads"),
            "no_clash_skip_groups": len(_by.get("no_clash", {}).get("skip_if_missing") or []),
        }
        pa = ev["preset_assembly"]
        ev["preset_ok"] = (pa["gate_count"] == 3 and pa["mesh_self_intersect"] is True
                           and pa["no_floaters_reads"] == ["gate"] and pa["no_clash_reads"] == ["verdict"]
                           and pa["no_clash_skip_groups"] == 2)
        # v3: the print preset's resolution degradation must hold on a **real receipt** (not a synthetic one)
        # probe cube 1 unit = 1000mm: face size 1 unit ⇒ resolution_mm=1000 ≫ min_mm=2 ⇒ that gate is degraded;
        # the criterion itself is true (thin_samples_total==0 and walls_ok) — exactly where the old basis produced a fake pass.
        r5 = json.loads(gate_run(preset="print", overrides={"walls": {"mm_per_unit": 1000.0}}, detail=True))
        g5 = (r5.get("gates") or [{}])[0]
        _echo5 = g5.get("echo") or {}
        _rec5 = (g5.get("receipt") or {}).get("detail", {}).get("walls", {}).get("objects", [{}])
        ev["print_resolution_case"] = {
            "state": g5.get("state"), "verdict": r5.get("verdict"), "ok": r5.get("ok"),
            "pass_if_value": g5.get("pass_if_value"),
            "resolution_mm": _echo5.get("detail.walls.objects.0.resolution_mm"),
            "min_mm": _echo5.get("params.min_mm"),
            "receipt_resolution_mm": (_rec5[0] or {}).get("resolution_mm") if _rec5 else None,
        }
        p5 = ev["print_resolution_case"]
        ev["print_resolution_ok"] = bool(p5["state"] == "degraded" and p5["verdict"] == "degraded"
                                        and p5["ok"] is False and p5["pass_if_value"] is True
                                        and p5["resolution_mm"] == p5["receipt_resolution_mm"]
                                        and (p5["resolution_mm"] or 0) > (p5["min_mm"] or 0))
        # v1.0.5 (issue #14) **on a real machine**: "the platform face cannot be judged" on the overhang side must also land in warnings and keep the gate from going green.
        # The probe is a cube tilted 45° around X: it has **no horizontally downward-facing face** ⇒ print_overhang takes the min-fallback and writes
        # bed_warning ⇒ print_report's top-level warnings are non-empty and echo carries them out as well.
        # Note: this case only proves "warnings are really produced + really echoed + the gate really degrades"; "warnings alone can degrade"
        # is locked separately by the synthetic receipt _warned above (its resolution is 0.1mm ⇒ the resolution factor is ruled out).
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def _gate_selftest_p2c(st):
    bmesh, ev, made, ob, ok1 = st["bmesh"], st["ev"], st["made"], st["ob"], st["ok1"]
    r2 = st["r2"]
    try:
        import mathutils as _mu
        tilt_me = bpy.data.meshes.new("__dsh_gate_selftest_tilt")
        tilt_ob = bpy.data.objects.new("__dsh_gate_selftest_tilt", tilt_me)
        bpy.context.scene.collection.objects.link(tilt_ob)
        made.append(tilt_ob.name)
        tbm = bmesh.new()
        bmesh.ops.create_cube(tbm, size=1.0)
        bmesh.ops.rotate(tbm, cent=(0.0, 0.0, 0.0), verts=list(tbm.verts),
                         matrix=_mu.Matrix.Rotation(0.7853981633974483, 3, "X"))   # 45°
        tbm.to_mesh(tilt_me)
        tbm.free()
        bpy.context.view_layer.objects.active = tilt_ob
        r6 = json.loads(gate_run(preset="print", overrides={"walls": {"min_mm": 900.0, "mm_per_unit": 1000.0}},
                                 detail=True))
        g6 = (r6.get("gates") or [{}])[0]
        _echo6 = g6.get("echo") or {}
        _recv6 = g6.get("receipt") or {}
        ev["print_bed_warning_case"] = {
            "state": g6.get("state"), "verdict": r6.get("verdict"), "ok": r6.get("ok"),
            "pass_if_value": g6.get("pass_if_value"),
            "warnings_n": len(_recv6.get("warnings") or []),
            "echo_warnings_n": len(_echo6.get("warnings") or []),
            "bed_mode": _echo6.get("params.bed_mode"),
            "thin_total": _recv6.get("thin_samples_total"),
            # the gate-side receipt is trimmed (only the fields referenced by reads/echo are kept); warnings stay because degrade_if references them —
            # which is exactly the evidence that "the gate can read this warning"; the objects[] details are not in the trimmed receipt, don't look there.
            "receipt_has_objects": "objects" in _recv6,
        }
        p6 = ev["print_bed_warning_case"]
        ev["print_bed_warning_ok"] = bool(p6["state"] == "degraded" and p6["verdict"] == "degraded"
                                          and p6["ok"] is False and p6["pass_if_value"] is True
                                          and p6["warnings_n"] >= 1 and p6["echo_warnings_n"] >= 1
                                          and p6["bed_mode"] == "min-fallback"
                                          and p6["thin_total"] == 0)
        # no configured source ⇒ skipped (not error); when every gate is skipped ⇒ degraded
        r4 = json.loads(gate_run(spec={"name": "skip", "gates": [
            {"id": "c", "op": "audit_interference", "args": {},
             "skip_if_missing": [["a", "objects_a", "file_a"], ["b", "objects_b", "file_b"]],
             "pass_if": "verdict == 'refuted'"}]}))
        g4 = (r4.get("gates") or [{}])[0]
        ev["skip_case"] = {"state": g4.get("state"), "verdict": r4.get("verdict"),
                           "skipped": r4.get("skipped"), "coverage": r4.get("coverage")}
        ev["skip_ok"] = bool(g4.get("state") == "skipped" and r4.get("verdict") == "degraded"
                             and r4.get("skipped") == ["c"]
                             and (r4.get("coverage") or {}).get("all_gates_ran") is False)
        # an unknown op / a reference to a nonexistent field ⇒ an explicit error (not a silent pass)
        err = None
        try:
            gate_run(spec={"name": "e", "gates": [{"id": "x", "op": "not_an_op", "pass_if": ""}]})
        except Exception as e:
            err = str(e)[:80]
        ev["unknown_op_error"] = err
        # referencing a nonexistent field: **no exception is raised**; instead that gate is judged error and says which field is missing (more useful than throwing)
        r3 = json.loads(gate_run(spec={"name": "e2", "gates": [
            {"id": "y", "op": "audit_mesh", "args": {"objects": [ob.name]}, "pass_if": "nope_field == 1"}]}))
        g3 = (r3.get("gates") or [{}])[0]
        ev["bad_field"] = {"state": g3.get("state"), "error": (g3.get("error") or "")[:90], "verdict": r3.get("verdict")}
        ok = bool(ok1 and r2.get("verdict") == "pass" and r2.get("ok") is True and ev.get("tri_state_ok")
                  and ev.get("nested_tri_ok") and ev.get("preset_ok") and ev.get("skip_ok")
                  and ev.get("degrade_if_ok") and ev.get("print_resolution_ok")
                  and ev.get("print_bed_warning_ok")
                  and ev.get("unknown_op_error")
                  and (ev.get("bad_field") or {}).get("state") == "error"
                  and "nope_field" in ((ev.get("bad_field") or {}).get("error") or ""))
        return _j({"ok": ok, "evidence": ev})
    finally:
        st.update((k, v) for k, v in locals().items() if k != "st")

def gate_selftest():
    """Self-test: build one scenario that should pass + one gate that should fail, and assert that three-state judging and the pass_if/degrade_if/skipped semantics are all correct.

    Assertions added in v3: ① any skipped/degraded ⇒ top level degraded (pass+skipped no longer counts as pass);
    ② the print preset's degrade_if (real fields: min_mm vs resolution_mm) turns a gate whose "criterion is true but the resolution is
    untrustworthy" into degraded on a real receipt, and echo matches the real values in the receipt.
    """
    st = dict(locals())
    _gate_selftest_p1(st)
    try:
        for _fn_ in (_gate_selftest_p2a, _gate_selftest_p2b, _gate_selftest_p2c):
            _r = _fn_(st)
            if _r is not None:
                return _r
    except Exception as e:
        return _j({"ok": False, "evidence": st.get("ev"),
                   "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
    finally:
        for nm in (st.get("made") or []):
            o = bpy.data.objects.get(nm)
            if o is not None:
                m = o.data
                bpy.data.objects.remove(o, do_unlink=True)
                try:
                    bpy.data.meshes.remove(m, do_unlink=True)
                except Exception:
                    pass



def gate_help():
    return _j({
        "module": "gate.py", "version": GATE_VERSION,
        "what": "Spec-driven gate package: one spec runs every gate, three-state verdict (pass/fail/degraded; gates without a configured source are recorded as skipped). "
                "**Any skipped or degraded gate pushes the top level down to degraded** (fail wins) — skipped ≠ pass: "
                "the top level is pass only when every gate really ran and passed; a degrade_if hit (untrustworthy evidence, e.g. insufficient resolution) is likewise judged degraded. "
                "The receipt carries only the criterion fields + the evidence fields requested by echo",
        "ops": ["gate_plan (read-only, lists the gates)", "gate_run (executes; overrides={gate id:{args…}} supplies on-site parameters to a preset)",
                "gate_selftest", "gate_help"],
        "spec": {"name": "package name", "units": "mm", "tolerance_mm": 3.0,
                 "gates": [{"id": "gate name", "op": "audit_scene|audit_mesh|audit_connectivity|audit_interference|"
                                             "print_report|uv_stats|material_scan|fix_repair|audit_drift|deliver_verify…",
                            "args": "the op's arguments", "pass_if": "restricted expression, e.g. clean == True",
                            "skip_if_missing": "[optional] [[candidate keys…], …]: if a group gets none of them ⇒ that gate is recorded skipped (not run; "
                                                "since v3 skipped pushes the top level down to degraded)",
                            "degrade_if": "[optional] restricted expression: the criterion is true but the evidence is untrustworthy ⇒ that gate is degraded (no fake pass)",
                            "echo": "[optional] [dot paths…]: pull these real fields (e.g. detail.walls.objects.0.resolution_mm) "
                                    "into the receipt as evidence"}]},
        "spec_sources": ["inline dict", ".json file", ".py module (SPEC = {...} or NAME/UNITS/TOLERANCE_MM/GATES)", "preset"],
        "presets": PRESETS,
        "pass_if_examples": {
            "audit_scene": "args={summary_only:true, top_k:5, self_intersect:true} → pass_if=\"clean == True\" "
                           "(self_intersect:true must be explicit: skipping the self-intersection check by default honestly yields degraded/clean=false)",
            "audit_connectivity": "pass_if=\"gate['verdict'] == 'pass'\" — the top level has no state/verdict, the gate conclusion sits in the "
                                  "nested gate; not analyzed/not confirmed ⇒ degraded (must not be promoted to pass)",
            "audit_interference": "args={objects_a:[…], objects_b:[…]} → pass_if=\"verdict == 'refuted'\" "
                                  "(refuted = interference provably absent / supported = real interference / unresolved = insufficient evidence→degraded); "
                                  "a pairwise op, so without both sides configured this gate is skipped (v3: skipped ⇒ top level degraded)",
            "print_report": "pass_if=\"thin_samples_total == 0 and walls_ok == True\" **and** "
                            "degrade_if=\"params['min_mm'] < detail['walls']['objects'][0]['resolution_mm']\" "
                            "(the resolution basis lives in the per-object detail.walls.objects[].warning/resolution_mm, the top level has no "
                            "such field) — when min_mm is below the measurement resolution the gate is judged degraded; 'not measured' must not read as green; "
                            "echo=[\"detail.walls.objects.0.resolution_mm\", …] brings the real readings into the receipt",
            "uv_stats": "pass_if=\"ok == True\" (details in objects[].degenerate_uv_faces)",
        },
        "rules": ["verdict is three-state, ok is true only on pass (degraded ≠ pass)",
                  "**any skipped or degraded ⇒ top level degraded (fail wins)**: skipped ≠ pass, the bar must not be lowered for a "
                  "'healthy default preset'; a pass requires every gate to have really run and passed",
                  "the three-state can be nested inside the receipt's gate (audit_connectivity): read the top level first, then the nested gate/connectivity",
                  "pass_if / degrade_if only allow comparison/boolean/arithmetic/attributes plus min·max·len·abs·round·all·any·sum",
                  "referencing a field the receipt does not have ⇒ error plus the list of available fields (never silent)",
                  "a degrade_if hit (criterion true but evidence untrustworthy, e.g. min_mm < measurement resolution) ⇒ that gate is degraded, "
                  "and the real fields in echo are the degradation evidence",
                  "gates declaring skip_if_missing with no configured source are recorded skipped: listed in skipped/coverage, "
                  "pushing the top level down to degraded",
                  "by default the receipt returns only the fields used by pass_if + reason/error on failure + the evidence fields from echo"],
        "why": "In the field ≈600 lines of interference / redcheck / selfint_diag were hand-written for a single assembly; executing and evidencing that is the plugin's job",
    })


