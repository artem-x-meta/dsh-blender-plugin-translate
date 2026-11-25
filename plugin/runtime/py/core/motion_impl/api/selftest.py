# -*- coding: utf-8 -*-
"""motion synthetic selftest harness (moved out of api.py; behavior preserved)."""
from ..common import *  # noqa: F401,F403
from ..infer import motion_infer_axis, motion_joint
from ..transforms import TOL_MAT, _snap_diff
from ..measure import motion_measure
from ..urdf import motion_export_urdf
from ..usda import motion_export_usda


# ============================================================ self-test

def _mk_box(name, size, loc):
    sx, sy, sz = [float(x) for x in size]
    me = bpy.data.meshes.new("MSH_" + name)
    v = [(-sx / 2, -sy / 2, -sz / 2), (sx / 2, -sy / 2, -sz / 2), (sx / 2, sy / 2, -sz / 2), (-sx / 2, sy / 2, -sz / 2),
         (-sx / 2, -sy / 2, sz / 2), (sx / 2, -sy / 2, sz / 2), (sx / 2, sy / 2, sz / 2), (-sx / 2, sy / 2, sz / 2)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(v, [], f)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = [float(x) for x in loc]
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _mk_cyl(name, radius, depth, loc, segs=32):
    """Cylinder along +Z; segs=32 ⇒ an exact 90° rotational self-map (synthetic evidence that makes the symmetry axis identifiable)."""
    r, d = float(radius), float(depth)
    v, f = [], []
    for i in range(segs):
        a = 2.0 * math.pi * i / segs
        x, y = r * math.cos(a), r * math.sin(a)
        v.append((x, y, -d / 2.0))
        v.append((x, y, d / 2.0))
    for i in range(segs):
        j = (i + 1) % segs
        f.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    f.append(tuple(reversed(range(0, 2 * segs, 2))))
    f.append(tuple(range(1, 2 * segs, 2)))
    me = bpy.data.meshes.new("MSH_" + name)
    me.from_pydata(v, [], f)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = [float(x) for x in loc]
    bpy.context.scene.collection.objects.link(ob)
    return ob


class _Selftest:
    """One synthetic hinge scene walked through every motion stage in order."""

    def __init__(self):
        self.checks = []
        self.res = {}
        self.made_objs = []
        self.made_meshes = []
        self.made_dirs = []
        self.pre_names = sorted(o.name for o in bpy.data.objects)
        self.outdir = os.path.join(_out_dir(), "motion_selftest")

    def chk(self, name, cond, detail):
        self.checks.append({"name": name, "ok": bool(cond), "detail": detail})
        return bool(cond)

    def build_scene(self):
        # ---- scene: hinge axis = world Z axis (through x=0,y=0)
        base = _mk_box("MS_Base", (1.0, 0.4, 0.06), (-0.05, 0.0, -0.06))
        door = _mk_box("MS_Door", (0.5, 0.04, 0.5), (0.29, 0.0, 0.25))     # x∈[0.04,0.54]
        pin = _mk_cyl("MS_Pin", 0.02, 0.6, (0.0, 0.0, 0.25))               # axis = Z, through the origin
        block = _mk_box("MS_Blocker", (0.08, 0.08, 0.6), (0.40, 0.21, 0.25))  # blocks the +y sweep path
        stand = _mk_box("MS_Stand", (0.2, 0.2, 0.2), (-1.5, 0.0, 0.1))     # for the orphan link
        bolt = _mk_box("MS_Bolt", (0.05, 0.05, 0.05), (-1.5, 0.2, 0.1))
        for ob in (base, door, pin, block, stand, bolt):
            self.made_objs.append(ob)
            self.made_meshes.append(ob.data)
        bpy.context.view_layer.update()
        self.chk("scene_built", len(self.made_objs) == 6, {"objects": [o.name for o in self.made_objs]})

    def register_and_infer(self):
        # ---- ① register the joint (no axis/anchor given → measured inference)
        r_joint = json.loads(motion_joint("selftest_hinge", ["MS_Base"], ["MS_Door", "MS_Pin"],
                                          kind="revolute", limits=[-30, 30], note="selftest hinge"))
        inf = json.loads(motion_infer_axis(jid="selftest_hinge"))
        true_axis = np.array([0.0, 0.0, 1.0])
        ang = _angle_deg(inf.get("axis") or [0, 0, 0], true_axis) if inf.get("axis") else None
        anchor = inf.get("anchor") or [0, 0, 0]
        anchor_off = _dist_point_line(anchor, [0.0, 0.0, 0.25], true_axis)
        self.res["infer"] = {"verdict": inf.get("verdict"), "axis": inf.get("axis"), "anchor": inf.get("anchor"),
                             "angle_to_true_axis_deg": _r(ang, 4) if ang is not None else None,
                             "anchor_offset_from_hinge_line": _r(anchor_off),
                             "reason": inf.get("reason"),
                             "per_object": [{"label": c.get("label"), "score": c.get("score"),
                                             "passed": c.get("passed"), "degenerate": c.get("degenerate"),
                                             "snapped": c.get("snapped")} for c in
                                            (inf.get("evidence") or {}).get("per_object", [])]}
        self.chk("infer_verdict_not_refuted", inf.get("verdict") in ("supported", "unresolved"),
                 {"verdict": inf.get("verdict"), "reason": inf.get("reason")})
        self.chk("infer_axis_clearance_lt_5deg", (ang is not None and ang < 5.0),
                 {"angle_deg": (None if ang is None else _r(ang, 4)), "axis": inf.get("axis"),
                   "note": "the pin (a cylinder) is rotationally symmetric about Z ⇒ the axis is identifiable"})
        self.chk("infer_anchor_on_hinge_line", (anchor_off is not None and anchor_off * _scene_mpu() <= 0.005),
                 {"offset_scene_unit": _r(anchor_off), "offset_m": _r((anchor_off or 0) * _scene_mpu()),
                  "tol_m": 0.005})
        self.chk("joint_registered_with_axis", bool(r_joint.get("ok") and r_joint.get("axis")),
                 {"ok": r_joint.get("ok"), "axis": r_joint.get("axis"), "axis_verdict": r_joint.get("axis_verdict"),
                  "warnings": r_joint.get("warnings")})
        # ---- for the orphan link (single-tree synthesis on export)
        motion_joint("selftest_spare", ["MS_Stand"], ["MS_Bolt"], kind="spherical", note="selftest orphan + degradation")

    def sweeps(self):
        # ---- ② unobstructed sweep: must be supported
        before = {o.name: [float(x) for row in o.matrix_world for x in row] for o in bpy.data.objects}
        m1 = json.loads(motion_measure(jid="selftest_hinge", phases=8, sweep_deg=60,
                                       exclude=self.pre_names + ["MS_Blocker"]))
        after1 = {o.name: [float(x) for row in o.matrix_world for x in row] for o in bpy.data.objects}
        self.res["sweep_clean"] = {"verdict": m1.get("verdict"), "moved": m1.get("moved"),
                                   "max_displacement_m": m1.get("max_displacement_m"),
                                   "phases": len(m1.get("phases") or []),
                                   "candidates": m1.get("candidates"),
                                   "restored_ok": (m1.get("restored") or {}).get("ok"),
                                   "reason": m1.get("reason"),
                                   "phase_values": [(p.get("value"), p.get("unit"),
                                                     len(p.get("collisions") or [])) for p in (m1.get("phases") or [])]}
        self.chk("sweep_clean_supported", m1.get("verdict") == "supported" and m1.get("moved") is True,
                 {"verdict": m1.get("verdict"), "moved": m1.get("moved"), "reason": m1.get("reason")})
        d1, bad1, exact1 = _snap_diff(before, after1)
        self.res["sweep_clean"]["restore_diff"] = {"max_delta": d1, "bad": bad1, "exact": exact1,
                                                   "tol": TOL_MAT}
        self.chk("sweep_clean_restored", (m1.get("restored") or {}).get("ok") is True and not bad1,
                 {"restored": m1.get("restored"), "diff": self.res["sweep_clean"]["restore_diff"]})
        # ---- ③ blocker in the sweep path: must be refuted and named
        m2 = json.loads(motion_measure(jid="selftest_hinge", phases=8, sweep_deg=60, exclude=self.pre_names))
        after2 = {o.name: [float(x) for row in o.matrix_world for x in row] for o in bpy.data.objects}
        off = m2.get("offenders") or []
        self.res["sweep_blocked"] = {"verdict": m2.get("verdict"), "offenders": off,
                                     "collisions": [{"phase": c.get("phase"), "other": c.get("other"),
                                                     "min_gap_m": c.get("min_gap_m"),
                                                     "penetration_m": c.get("penetration_m")}
                                                    for c in (m2.get("collisions") or [])],
                                     "reason": m2.get("reason"),
                                     "restored_ok": (m2.get("restored") or {}).get("ok")}
        self.chk("sweep_block_refuted", m2.get("verdict") == "refuted" and "MS_Blocker" in off,
                 {"verdict": m2.get("verdict"), "offenders": off, "reason": m2.get("reason")})
        self.chk("sweep_block_penetration_negative",
                 any((c.get("min_gap_m") is not None and c["min_gap_m"] < 0) for c in (m2.get("collisions") or [])),
                 {"collisions": self.res["sweep_blocked"]["collisions"]})
        d2, bad2, exact2 = _snap_diff(before, after2)
        self.res["sweep_blocked"]["restore_diff"] = {"max_delta": d2, "bad": bad2, "exact": exact2,
                                                     "tol": TOL_MAT}
        self.chk("sweep_block_restored", (m2.get("restored") or {}).get("ok") is True and not bad2,
                 {"restored": m2.get("restored"), "diff": self.res["sweep_blocked"]["restore_diff"]})

    def exports(self):
        # ---- ④ export structure self-check (URDF + USDA)
        os.makedirs(self.outdir, exist_ok=True)
        self.made_dirs.append(self.outdir)
        u = json.loads(motion_export_urdf(dir=self.outdir, name="selftest_model",
                                          joints=["selftest_hinge", "selftest_spare"],
                                          meters_per_unit=0.001, density=1000.0))
        s = json.loads(motion_export_usda(dir=self.outdir, name="selftest_model",
                                          joints=["selftest_hinge", "selftest_spare"],
                                          meters_per_unit=0.001, density=1000.0))
        self.res["urdf"] = {"ok": u.get("ok"), "path": u.get("path"),
                            "self_check": u.get("self_check"), "warnings": u.get("warnings"),
                            "links": [l.get("link") for l in (u.get("links") or [])],
                            "joints": [(j.get("joint"), j.get("type"), j.get("synthesized"),
                                        j.get("degraded_from")) for j in (u.get("joints") or [])]}
        self.res["usda"] = {"ok": s.get("ok"), "path": s.get("path"),
                            "self_check": s.get("self_check"), "warnings": s.get("warnings"),
                            "links": s.get("links"), "joints": s.get("joints")}
        self.chk("urdf_self_check_ok", bool(u.get("ok") and (u.get("self_check") or {}).get("ok")),
                 {"ok": u.get("ok"), "self_check": u.get("self_check"), "warnings": u.get("warnings")})
        self.chk("urdf_degraded_reported",
                 any("degraded" in str(w) for w in (u.get("warnings") or [])),
                 {"warnings": u.get("warnings")})
        self.chk("urdf_orphan_synthesized",
                 any("unreachable" in str(w) for w in (u.get("warnings") or []))
                 and any(j.get("synthesized") for j in (u.get("joints") or [])),
                 {"warnings": u.get("warnings"), "joints": self.res["urdf"]["joints"]})
        self.chk("usda_self_check_ok", bool(s.get("ok") and (s.get("self_check") or {}).get("ok")),
                 {"ok": s.get("ok"), "self_check": s.get("self_check"), "warnings": s.get("warnings")})
        # unit check: this scene is metric (0.5 units ≈ 0.5 m) yet is exported with 0.001 ⇒ it must report "Suspicious units" itself
        self.chk("units_guard_fires_on_implausible_scale",
                 (u.get("units") or {}).get("scene_units_suspect") is True
                 and any("Suspicious units" in str(w) for w in (u.get("warnings") or [])),
                 {"units": u.get("units"), "warnings": u.get("warnings")})
        # small magnitudes must not be written as 0: mass/inertia must keep their order of magnitude (the earlier "%.9f" wrote 8.6e-11 as 0)
        import re as _re
        _txt = open(u["path"], encoding="utf-8").read()
        _zeros = _re.findall(r'(?:mass value|inertia ixx|iyy|izz)="0"', _txt)
        self.chk("SI small magnitudes do not collapse to 0 (mass/inertia keep their order of magnitude)", not _zeros,
                 {"zeros": _zeros[:6], "sample": _re.findall(r'<mass value="[^"]+"', _txt)[:4]})

    def hard_rules(self):
        # ---- ⑤ empty output / missing axis must fail (hard rules)
        empty_joint = json.loads(motion_joint("selftest_bad", ["MS_Nope"], ["MS_AlsoNope"]))
        empty_export = json.loads(motion_export_urdf(dir=self.outdir, name="empty", joints=[]))
        no_axis_measure = json.loads(motion_measure(jid="selftest_spare", phases=4))
        self.res["hard_rules"] = {"empty_joint_ok": empty_joint.get("ok"),
                                  "empty_export_ok": empty_export.get("ok"),
                                  "empty_export_error": empty_export.get("error"),
                                  "no_axis_measure_ok": no_axis_measure.get("ok"),
                                  "no_axis_measure_verdict": no_axis_measure.get("verdict"),
                                  "no_axis_measure_reason": no_axis_measure.get("reason")}
        self.chk("empty_joint_must_fail", empty_joint.get("ok") is False, {"resp": empty_joint})
        self.chk("empty_export_must_fail", empty_export.get("ok") is False, {"resp": empty_export.get("error")})
        self.chk("no_axis_measure_unresolved",
                 no_axis_measure.get("ok") is False and no_axis_measure.get("verdict") == "unresolved",
                 {"resp": self.res["hard_rules"]})

    def build_axis_scene(self):
        # ---- ⑥ the three states of axis inference (the criteria really bite): a contact strip can fix the axis / a thin slab must be unresolved / a hypothesised axis can be refuted
        bar2 = _mk_box("MS_Bar", (1.0, 0.08, 0.08), (-3.0, 0.0, 0.0))          # top face z=0.04
        pl_a = _mk_box("MS_PlateNS", (0.5, 0.04, 0.3), (-3.4, 0.0, 0.17))      # non-square: no rotational symmetry
        pl_b = _mk_box("MS_PlateSQ", (0.5, 0.04, 0.5), (-2.6, 0.0, 0.27))      # square: also symmetric about the normal
        pad2 = _mk_box("MS_Pad", (0.6, 0.3, 0.04), (-5.0, 0.0, 0.0))
        flap = _mk_box("MS_Flap", (0.5, 0.03, 0.4), (-5.0, 0.0, 0.25))         # 0.03 gap to Pad
        for ob in (bar2, pl_a, pl_b, pad2, flap):
            self.made_objs.append(ob)
            self.made_meshes.append(ob.data)
        bpy.context.view_layer.update()

    def contact_axis(self):
        true_hinge = np.array([1.0, 0.0, 0.0])
        j_contact = json.loads(motion_joint("selftest_contact", ["MS_Bar"], ["MS_PlateNS"],
                                            kind="revolute", note="axis fixed by the contact strip"))
        ax_c = j_contact.get("axis") or [0, 0, 0]
        ang_c = _angle_deg(ax_c, true_hinge)
        anc_off_c = _dist_point_line(j_contact.get("anchor") or [0, 0, 0], [0.0, 0.0, 0.04], true_hinge)
        self.res["infer_contact"] = {"verdict": j_contact.get("axis_verdict"),
                                     "source": j_contact.get("axis_source"),
                                     "axis": j_contact.get("axis"), "anchor": j_contact.get("anchor"),
                                     "angle_to_true_deg": _r(ang_c, 4),
                                     "anchor_offset": _r(anc_off_c), "warnings": j_contact.get("warnings")}
        self.chk("contact_strip_axis_supported",
                 j_contact.get("axis_verdict") == "supported" and j_contact.get("axis_source") == "contact_region"
                 and ang_c is not None and ang_c < 5.0,
                 self.res["infer_contact"])
        self.chk("contact_strip_anchor_near_hinge_line", anc_off_c is not None and anc_off_c * _scene_mpu() <= 0.005,
                 {"offset_scene_unit": _r(anc_off_c), "offset_m": _r((anc_off_c or 0) * _scene_mpu()),
                  "tol_m": 0.005})

    def slab_and_square(self):
        j_slab = json.loads(motion_joint("selftest_slab", ["MS_Pad"], ["MS_Flap"], kind="revolute",
                                         note="thin slab without a pin: must be unresolved"))
        inf_slab = json.loads(motion_infer_axis(jid="selftest_slab"))
        self.res["infer_slab_unresolved"] = {"joint_axis_verdict": j_slab.get("axis_verdict"),
                                             "axis": j_slab.get("axis"),
                                             "verdict": inf_slab.get("verdict"),
                                             "best_score": [{"label": c.get("label"), "score": c.get("score"),
                                                             "degenerate": c.get("degenerate")}
                                                            for c in (inf_slab.get("evidence") or {}).get("per_object", [])],
                                             "contact": {k: (inf_slab.get("evidence") or {}).get("contact", {}).get(k)
                                                         for k in ("available", "reason", "close_points", "elongation")},
                                             "missing_evidence": inf_slab.get("missing_evidence"),
                                             "reason": inf_slab.get("reason")}
        self.chk("slab_without_pin_is_unresolved",
                 j_slab.get("axis") is None and j_slab.get("axis_verdict") == "unresolved"
                 and inf_slab.get("verdict") == "unresolved" and inf_slab.get("missing_evidence"),
                 self.res["infer_slab_unresolved"])
        j_sq = json.loads(motion_joint("selftest_square", ["MS_Bar"], ["MS_PlateSQ"], kind="revolute",
                                       note="square plate: symmetry axis conflicts with the contact strip"))
        inf_sq = json.loads(motion_infer_axis(jid="selftest_square"))
        self.res["infer_conflict"] = {"joint_axis_verdict": j_sq.get("axis_verdict"),
                                      "verdict": inf_sq.get("verdict"),
                                      "axis_conflict": inf_sq.get("axis_conflict"),
                                      "reason": inf_sq.get("reason")}
        self.chk("square_plate_conflict_unresolved",
                 inf_sq.get("verdict") == "unresolved" and bool(inf_sq.get("axis_conflict"))
                 and inf_sq.get("axis") is None,
                 self.res["infer_conflict"])

    def hypothesis_cases(self):
        motion_joint("selftest_wrongaxis", ["MS_Base"], ["MS_Pin"], kind="revolute",
                     axis=[1.0, 0.0, 0.0], anchor=[0.0, 0.0, 0.25], note="deliberately wrong axis (the child is only the pin)")
        inf_wrong = json.loads(motion_infer_axis(jid="selftest_wrongaxis"))
        self.res["infer_wrong_axis"] = {"verdict": inf_wrong.get("verdict"), "reason": inf_wrong.get("reason"),
                                        "nearest": ((inf_wrong.get("hypothesis") or {}).get("evidence") or {}).get("candidates")}
        self.chk("wrong_axis_hypothesis_refuted", inf_wrong.get("verdict") == "refuted",
                 self.res["infer_wrong_axis"])
        motion_joint("selftest_ambiguous", ["MS_Base"], ["MS_Door", "MS_Pin"], kind="revolute",
                     axis=[1.0, 0.0, 0.0], anchor=[0.0, 0.0, 0.25], note="the hypothesised direction is only a near-miss candidate")
        inf_amb = json.loads(motion_infer_axis(jid="selftest_ambiguous"))
        self.res["infer_ambiguous"] = {"verdict": inf_amb.get("verdict"), "reason": inf_amb.get("reason"),
                                       "nearest": ((inf_amb.get("hypothesis") or {}).get("evidence") or {}).get("candidates")}
        self.chk("ambiguous_hypothesis_not_refuted", inf_amb.get("verdict") == "unresolved",
                 self.res["infer_ambiguous"])

    def cleanup(self, keep=False):
        removed, failed = [], []
        for ob in self.made_objs:
            try:
                nm = str(ob.name)          # take the name first: the StructRNA goes invalid after remove
            except Exception:
                nm = "?"
            try:
                bpy.data.objects.remove(ob, do_unlink=True)
                removed.append(nm)
            except Exception as e:
                failed.append({"name": nm, "error": str(e)[:120]})
        for me in self.made_meshes:
            try:
                bpy.data.meshes.remove(me, do_unlink=True)
            except Exception:
                pass
        if not keep:
            for d in self.made_dirs:
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        self.res["cleaned"] = {"removed_objects": removed, "failed": failed,
                               "objects_left": sorted(o.name for o in bpy.data.objects),
                               "pre_existing": self.pre_names,
                               "dir_removed": (not keep),
                               "dir": self.outdir}

    def run(self):
        self.build_scene()
        self.register_and_infer()
        self.sweeps()
        self.exports()
        self.hard_rules()
        self.build_axis_scene()
        self.contact_axis()
        self.slab_and_square()
        self.hypothesis_cases()


def motion_selftest(keep=False):
    """Synthetic self-test: build a hinge (base plate + door plate + a pin along Z) → measure the axis → unobstructed sweep → sweep with a blocker added →
    URDF/USDA structure self-check → restore proof. Does not depend on the user's scene (pre-existing objects are always excluded), and cleans up at the end.
    """
    t0 = time.perf_counter()
    st = _Selftest()
    try:
        st.run()
    except Exception as e:
        st.checks.append({"name": "selftest_exception", "ok": False,
                          "detail": "%s: %s" % (type(e).__name__, str(e)[:300]),
                          "traceback": traceback.format_exc()[-1200:]})
    finally:
        st.cleanup(keep)

    fails = [c for c in st.checks if not c["ok"]]
    ok = not fails
    if not (st.res.get("cleaned") or {}).get("removed_objects"):
        ok = False
        fails.append({"name": "cleanup_ran", "ok": False, "detail": "cleanup did not run"})
    _log("selftest", {"ok": ok, "fails": [c["name"] for c in fails]})
    return _j({
        "ok": ok, "op": "selftest", "version": MOTION_VERSION,
        "checks": st.checks, "fails": fails, "fail_count": len(fails),
        "measured": st.res,
        "expect": ("the pin (a cylinder along Z) is identifiable ⇒ the measured axis is supported, within <5° of the true axis, and the anchor is on the hinge line; "
                   "an unobstructed 8-phase sweep = supported (zero interference and real displacement); putting the blocker in the sweep path ⇒ the same joint becomes "
                   "refuted and names MS_Blocker (minimum gap <0); the URDF/USDA structure self-checks all pass (including the spherical degradation and the "
                   "orphan link synthesized into a single tree); every object's matrix_world is identical item by item before and after the sweep; empty output / missing axis must be ok=false"),
        "notes": ["the self-test does not touch the user's scene: pre-existing objects are always excluded and never deleted",
                  "temporary objects/files are cleaned up in finally (keep=true keeps the artifacts for troubleshooting)"],
        "ms": int((time.perf_counter() - t0) * 1000),
    })
