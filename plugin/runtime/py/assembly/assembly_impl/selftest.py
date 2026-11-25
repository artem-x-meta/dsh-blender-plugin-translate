# -*- coding: utf-8 -*-
"""Split from assembly.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .manifest import asm_manifest
from .scan import asm_scan
from .gate import asm_gate
from .merge import asm_merge

def _selftest_box(name, size, loc):
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co *= size
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    return ob


def asm_selftest():
    """In-module quick self-test: clash classification / manifest round trip / merge dry_run / bad parameters ok:false."""
    import tempfile
    ev = {}
    t0 = time.perf_counter()
    made, tmpdir = [], None
    prev_scale = float(bpy.context.scene.unit_settings.scale_length)
    try:
        bpy.context.scene.unit_settings.scale_length = 0.001
        a = _selftest_box("__dsh_asm_a", 20.0, (0, 0, 0))
        b = _selftest_box("__dsh_asm_b", 20.0, (19.0, 0, 0))
        made += [a, b]
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        r = json.loads(asm_scan(objects=["__dsh_asm_a", "__dsh_asm_b"], summary_only=False,
                                max_pairs=10, report_gap_mm=2.0))
        by = {}
        for p in r.get("pairs") or []:
            by[tuple(sorted([p.get("a"), p.get("b")]))] = p
        rec = by.get(("__dsh_asm_a", "__dsh_asm_b")) or {}
        ev["scan_clash"] = rec.get("class") == "clash"
        ev["scan_depth_measured"] = rec.get("depth_mm") is not None
        ev["scan_verdict_fail"] = r.get("verdict") == "fail"
        r_bad = json.loads(asm_scan(objects=["__dsh_asm_nope"]))
        ev["scan_bad_input_okfalse"] = r_bad.get("ok") is False
        tmpdir = tempfile.mkdtemp(prefix="dsh_asm_selftest_")
        partfile = os.path.join(tmpdir, "part_a.blend")
        bpy.ops.wm.save_as_mainfile(filepath=partfile, copy=True)
        man = os.path.join(tmpdir, "assembly.json")
        m1 = json.loads(asm_manifest(action="init", path=man, assembly="selftest", force=True))
        m2 = json.loads(asm_manifest(action="add_part", path=man,
                                     part={"id": "part_a", "file": partfile, "objects": ["__dsh_asm_a"]}))
        m3 = json.loads(asm_manifest(action="seal", path=man))
        ev["manifest_roundtrip"] = bool(m1.get("ok") and m2.get("ok") and m3.get("ok"))
        ev["manifest_sealed"] = bool(m3.get("sealed"))
        dry = json.loads(asm_merge(manifest=man, out_blend=os.path.join(tmpdir, "merged.blend"),
                                   dry_run=True))
        ev["merge_dry_run"] = bool(dry.get("ok") and dry.get("dry_run") is True)
        ev["merge_dry_no_write"] = not os.path.isfile(os.path.join(tmpdir, "merged.blend"))
        ev["merge_order"] = dry.get("order")
        ev["merge_target_names"] = (dry.get("parts") or [{}])[0].get("target_names")
        g_bad = json.loads(asm_gate(objects=[]))
        ev["gate_bad_input_okfalse"] = g_bad.get("ok") is False
        ok = all(v is True for k, v in ev.items() if k not in ("merge_order", "merge_target_names"))
        return _j({"ok": bool(ok), "version": ASSEMBLY_VERSION, "evidence": ev,
                   "ms": int((time.perf_counter() - t0) * 1000)})
    except Exception as e:
        import traceback
        return _j({"ok": False, "version": ASSEMBLY_VERSION, "evidence": ev,
                   "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                   "traceback": traceback.format_exc()[-600:]})
    finally:
        bpy.context.scene.unit_settings.scale_length = prev_scale
        for nm in [str(o.name) for o in made]:
            ob = bpy.data.objects.get(nm)
            if ob is not None:
                me = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                if me is not None and me.users == 0:
                    try:
                        bpy.data.meshes.remove(me, do_unlink=True)
                    except Exception:
                        pass
        if tmpdir:
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass


def asm_help():
    return _j({
        "module": "assembly.py", "version": ASSEMBLY_VERSION,
        "what": "Assembly layer: all-pairs interpenetration/containment classification scan + part manifest + N-way merge + assembly ship gate (verdict-first)",
        "ops": {
            "scan": {"alias": "audit_clash_all",
                     "sig": "scope|objects|file, manifest?, spec?, limit=0, max_pairs=20000, "
                            "depth_eps_mm=0.2, contact_eps_mm=0.3, report_gap_mm=5.0, summary_only=false",
                     "out": "verdict + counts{clash,hidden_ok,contact,gap,float,contained,unresolved} + "
                            "pairs + matrix(sparse) + coverage{complete,truncated,budget_hit} + offenders + repairs",
                     "why": "The old all-pairs loop `continue`d when triangles did not intersect ⇒ full containment was missed; this op adds a containment branch + per-pair classification + the allow allowlist"},
            "manifest": {"action": "init|add_part|add_interface|add_allow|validate|seal|show",
                         "sig": "path, assembly, part={id,file,objects,owner,transform,interface_frames}, "
                                "interfaces=[{id,a,b,frame_a,frame_b,fit,nominal_mm,tol_mm,allow_overlap_mm}], "
                                "allow=[{a,b,max_depth_mm,max_volume_mm3,reason}], check_files=true, check_md5=true",
                         "out": "errors[]/warnings[]/manifest_md5/verdict; validates id uniqueness/file/file_md5/both interface ends/basis orthogonality/units"},
            "merge": {"sig": "manifest, out_blend, dry_run=true, transform_policy=manifest|as_is|snap_interface, "
                             "snap_tol_mm=2.0, recalc_normals=true, snapshot=true, gate=true, strict=true",
                      "flow": "validate → (snapshot) → append in part id lexicographic order → rename to <partid>__<original name> → transform → "
                              "recalc normals → asm_gate → save + merge_receipt.json only if it passes; nothing is saved on failure"},
            "gate": {"alias": "merge_gate",
                     "sig": "scope|objects, manifest?, spec?, require{}, summary_only=true, strict=true, "
                            "tolerance_mm=0.5",
                     "gates": "mesh_health + normals + clash_all + floaters + interfaces + measure → three-state; "
                              "export_allowed only when verdict=pass"},
            "repair": {"alias": "fix_clash", "planner": "fix_interference",
                       "policy": "default (no policy given) = safe behaviour: automatic actions are translate/snap only, "
                                 "booleans need the explicit allow_boolean=true permission (keeps old calls working) "
                                 "| explicit policy=safe: booleans/scale hard-forbidden "
                                 "| manual: plan only, never auto-execute, never plan booleans "
                                 "| aggressive: keeps the old behaviour, booleans controlled by allow_boolean",
                       "sig": "scope|objects|manifest, spec?, dry_run=true, max_move_mm=50.0, "
                              "allow_boolean=false, snapshot=true, max_rounds=3, clearance_mm=0.5, policy",
                       "flow": "asm_scan → plan (clash/contained: translate the smaller-volume part along the AABB axis of least overlap "
                              "by the amount needed to separate the AABBs + clearance; float: audit_snap_floaters plan; allow_boolean with both parts "
                              "closed manifold: boolean-subtract the smaller part from the larger) → (dry_run=false) file-level snapshot → apply each action "
                              "→ view_layer.update → re-run asm_scan, up to max_rounds rounds",
                       "out": "dry_run=true: plan[]/blocked[]/expected (read-only, scene unchanged); "
                              "dry_run=false: before/after counts + residual + applied + blocked + snapshot",
                       "verdict": "dry_run: planned (actions exist) / blocked (no actions) / pass (was not broken); "
                                  "after execution: residual clash/contained/float=0 ⇒ ok:true with verdict = the re-scan's three-state, "
                                  "residual remains ⇒ ok:false + residual",
                       "safety": "dry_run defaults to true; booleans are only planned when allow_boolean=true and both parts are closed manifold; "
                                 "boolean execution requires a usable file-level snapshot (K.dsh_txn_api), otherwise it is refused; "
                                 "a target part with a parent/animation ⇒ blocked (moving the whole object would be overridden); "
                                 "plan[].risk / blocked[].blocked_reason are readable per entry",
                       "risk_policy": "safe never does booleans/scale automatically; manual only emits a plan; only aggressive keeps the allow_boolean boolean path"},
            "fix_interference": {"planner_only": True,
                                 "sig": "a?, b?, plan_only=true, manifest?, scope?, objects?, spec?, "
                                        "max_move_mm=50.0, allow_boolean=false, clearance_mm=0.5, max_rounds=3, "
                                        "policy=safe",
                                 "out": "plan[]/blocked[]/expected (read-only; a/b can restrict it to that pair)",
                                 "why": "what asm_scan / asm_gate put in repairs is exactly this planner call; use fix_clash to execute"},
            "export": {"alias": "asm_export",
                       "sig": "manifest?, scope|objects, out_dir?, name=assembly, formats=[glb,fbx,obj], "
                              "merge=false, dry_run=false, include_receipt=true, ledger=true, verify=true",
                       "flow": "merge=true and dry_run=false → asm_merge(dry_run=false) first (gate+snapshot inside, no export when the gate fails) "
                               "→ the official exporters write GLB/FBX/OBJ (io_scene_gltf2/io_scene_fbx enabled automatically) "
                               "→ <out_dir>/<name>_manifest.json + append-only <out_dir>/merge_ledger.jsonl",
                       "out": "{ok, verdict, dir, files{glb,fbx,obj,manifest,ledger,blend,obj_mtl}, counts, "
                              "gate, merge, md5, manifest_md5, warnings}; dry_run=true returns the plan only and writes nothing",
                       "verdict": "the gate's three-state; every format failing ⇒ ok:false; partial failure ⇒ ok:true + warnings",
                       "safety": "dry_run=true never writes to disk or creates directories; the manifest records per-file md5/bytes/gate/merge receipt; "
                                 "the ledger only appends, never rewrites"},
            "selftest": {"sig": "no arguments", "out": "in-module quick self-test (clash/manifest/merge dry_run/bad parameters)"},
        },
        "verdict_rules": {
            "scan": "clash>0 or contained>0 or float>0 ⇒ fail; unresolved/truncated/objects not fully judged ⇒ degraded; otherwise pass",
            "gate": "any fail ⇒ fail; any degraded/skipped ⇒ degraded; all pass ⇒ pass; "
                    "degraded ≠ pass, export_allowed only on pass",
            "unresolved": "insufficient evidence (open mesh / inward normals / not measured) is always unresolved and must not count as pass",
        },
        "manifest_schema": {"schema": MANIFEST_SCHEMA, "units": "mm", "coord": {"up": "Z", "forward": "-Y"},
                            "parts": "id/file/objects/owner/file_md5/transform{loc_mm,rot_euler_deg,scale}/interface_frames",
                            "interfaces": "id/a/b/frame_a/frame_b/fit/nominal_mm/tol_mm/allow_overlap_mm/clearance_min_mm",
                            "allow_pairs": "id/a/b/max_depth_mm/max_volume_mm3/reason"},
        "protocol": [
            "Parallel sessions: each part owner saves parts/*.blend → the Lead runs asm_manifest init/add_part/add_interface/seal → asm_merge(dry_run to inspect the plan) → asm_merge(dry_run=false) which runs asm_gate automatically",
            "The single source of allow is the manifest/spec (reproducible across processes); do not rely on the in-session declared state of K.dsh_contract",
            "Write in-design hidden overlap to spec.allow (max_depth_mm/max_volume_mm3); never let it through with a global threshold",
            "gate fails ⇒ nothing is saved; for fixes see offenders/repairs (fix_interference / fix_repair / adjust the interface frames)",
        ],
        "deps": {"required": "K.dsh_kit",
                 "optional": "contract (reused for the deep-dive)/audit (mesh+connectivity+measure)/clearance/gate/txn (merge snapshot)"},
        "honest_limits": ["sampled depth/volume are estimates", "full containment is reported as contained on a solid reading (hollow shells need human review)",
                          "open mesh/inward normals ⇒ unresolved", "all-pairs does not compute contact area", "shots is not implemented in this version"],
    })
