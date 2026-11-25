# -*- coding: utf-8 -*-
"""DSH pairwise clearance gate: **rule-table driven** nearest distance + interpenetration verdict.

Rule table: pairs=[{"id","a":[objects],"b":[objects],"min_mm","allow_overlap"}]
  ① Wheels/suspension/lights, the **must-not-touch** kind: give min_mm as the process clearance (including travel);
  ② Panels/skin, the **overlap-permitted** kind: allow_overlap=true (interpenetration is the design intent).

The boilerplate (JSON / API / dispatch / BVH / sampling / units) **all comes from the shared kernel kit** (K.dsh_kit);
this module keeps only the domain logic — it is the first sample of the kernelisation migration (252 lines → about 130, receipt keys and verdicts byte-identical).
"""
import json
import sys

CLEAR_VERSION = 2

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("clearance.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")

_j = _KIT.j


def clear_check(pairs=None, samples=1200, seed=0, include_hidden=True):
    """Rule-table driven clearance/interpenetration check. Returns per-pair gap_mm / interpenetrating / verdict."""
    mmu = _KIT.units()
    if not pairs:
        raise ValueError("pairs is required: [{id,a:[objects],b:[objects],min_mm,allow_overlap}]")
    rows, failed = [], []
    for i, spec in enumerate(list(pairs)):
        sp = dict(spec or {})
        pid = str(sp.get("id") or ("pair%d" % i))
        a_names = sp.get("a") or []
        b_names = sp.get("b") or []
        a_names = [a_names] if isinstance(a_names, str) else list(a_names)
        b_names = [b_names] if isinstance(b_names, str) else list(b_names)
        if not a_names or not b_names:
            rows.append({"id": pid, "verdict": "error", "error": "both a and b need object lists"})
            failed.append(pid)
            continue
        objs_a, miss_a = _KIT.objects(a_names)
        objs_b, miss_b = _KIT.objects(b_names)
        miss = miss_a + miss_b
        if miss:
            rows.append({"id": pid, "verdict": "error", "error": "Objects do not exist: %s" % miss[:4]})
            failed.append(pid)
            continue
        r = _KIT.pairwise_clearance(objs_a, objs_b, samples=samples, seed=seed)
        if r.get("error"):
            rows.append({"id": pid, "verdict": "error", "error": "One side has no triangles (empty object?)"})
            failed.append(pid)
            continue
        gap_mm = (r["gap_m"] * mmu) if r.get("gap_m") is not None else None
        inter = bool(r["interpenetrating"])
        n_ov = int(r["overlap_tri_pairs"])
        min_mm = float(sp.get("min_mm") or 0.0)
        allow = bool(sp.get("allow_overlap") or False)
        if inter and not allow:
            verdict, why = "fail", "Interpenetration: %d triangle pairs intersect" % n_ov
        elif (not inter) and gap_mm is not None and gap_mm < min_mm:
            verdict, why = "fail", "Gap %.3f mm < required %.3f mm" % (gap_mm, min_mm)
        else:
            verdict = "pass"
            why = ("Overlap allowed (%d triangle pairs intersect)" % n_ov) if inter else ("Gap %.3f mm ≥ %.3f mm" % (gap_mm or 0.0, min_mm))
        rows.append({"id": pid, "a": a_names[:6], "b": b_names[:6],
                     "gap_mm": (round(gap_mm, 4) if gap_mm is not None else None),
                     "interpenetrating": bool(inter), "overlap_tri_pairs": n_ov,
                     "min_mm": min_mm, "allow_overlap": allow, "verdict": verdict, "why": why})
        if verdict != "pass":
            failed.append(pid)
    gaps = [r["gap_mm"] for r in rows if r.get("gap_mm") is not None and not r.get("interpenetrating")]
    return _j({"ok": not failed, "verdict": ("pass" if not failed else "fail"), "pairs": rows,
               "pair_count": len(rows), "pairs_failed": failed,
               "min_clearance_mm": (round(min(gaps), 4) if gaps else None),
               "units": {"mm_per_unit": round(mmu, 6)},
               "note": "min_mm governs clearance, allow_overlap governs permitted overlap (panels) — do not cover both rules with a single threshold",
               "honest_limits": ["Clearance is measured with sample points: two large surfaces lying flush and parallel may be overestimated (interpenetration detection is exact)",
                                 "Only the given pairs are looked at: relationships that are not listed are never checked"]})


def _box(nm, x, size=20.0):
    import bpy
    import bmesh as _bm
    import mathutils
    me = bpy.data.meshes.new(nm)
    ob = bpy.data.objects.new(nm, me)
    bpy.context.scene.collection.objects.link(ob)
    bm = _bm.new()
    _bm.ops.create_cube(bm, size=1.0, matrix=mathutils.Matrix.Diagonal((size, size, size, 1.0)))
    bm.to_mesh(me)
    bm.free()
    ob.location = (x, 0.0, 0.0)
    return nm


def clear_selftest():
    """Self-test: a 10mm gap must pass · 2mm must fail · interpenetration must fail · permitted overlap must pass."""
    import bpy
    prev = float(bpy.context.scene.unit_settings.scale_length)
    made = []
    ev = {}
    try:
        bpy.context.scene.unit_settings.scale_length = 0.001
        a1, b1 = _box("__dsh_cl_a", 0.0), _box("__dsh_cl_b", 30.0)
        a2, b2 = _box("__dsh_cl_c", 0.0), _box("__dsh_cl_d", 22.0)
        a3, b3 = _box("__dsh_cl_e", 0.0), _box("__dsh_cl_f", 10.0)
        made = [a1, b1, a2, b2, a3, b3]
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        r = json.loads(clear_check(pairs=[
            {"id": "gap10", "a": [a1], "b": [b1], "min_mm": 5.0},
            {"id": "gap2", "a": [a2], "b": [b2], "min_mm": 5.0},
            {"id": "overlap", "a": [a3], "b": [b3], "min_mm": 1.0},
            {"id": "overlap_ok", "a": [a3], "b": [b3], "allow_overlap": True},
        ]))
        by = {x["id"]: x for x in r.get("pairs", [])}
        ev["gap10"] = {"gap_mm": by["gap10"].get("gap_mm"), "verdict": by["gap10"].get("verdict")}
        ev["gap2"] = {"gap_mm": by["gap2"].get("gap_mm"), "verdict": by["gap2"].get("verdict")}
        ev["overlap"] = {"inter": by["overlap"].get("interpenetrating"), "verdict": by["overlap"].get("verdict")}
        ev["allowed"] = {"verdict": by["overlap_ok"].get("verdict")}
        ev["top"] = {"ok": r.get("ok"), "failed": r.get("pairs_failed")}
        ok = (by["gap10"].get("verdict") == "pass" and abs((by["gap10"].get("gap_mm") or 0) - 10.0) < 0.6
              and by["gap2"].get("verdict") == "fail"
              and by["overlap"].get("verdict") == "fail" and by["overlap"].get("interpenetrating") is True
              and by["overlap_ok"].get("verdict") == "pass"
              and r.get("ok") is False and set(r.get("pairs_failed") or []) == {"gap2", "overlap"})
        return _j({"ok": bool(ok), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
    finally:
        bpy.context.scene.unit_settings.scale_length = prev
        for nm in made:
            o = bpy.data.objects.get(nm)
            if o is not None:
                me = o.data
                bpy.data.objects.remove(o, do_unlink=True)
                if me is not None and me.users == 0:
                    try:
                        bpy.data.meshes.remove(me, do_unlink=True)
                    except Exception:
                        pass


def clear_help():
    return _j({
        "module": "clearance.py", "version": CLEAR_VERSION,
        "what": "Pairwise clearance gate: rule-table driven (min_mm governs clearance / allow_overlap governs permitted overlap); reports nearest distance and the interpenetration verdict",
        "ops": ["clear_check(pairs)", "clear_selftest", "clear_help"],
        "pair_schema": {"id": "rule name", "a": ["object…"], "b": ["object…"], "min_mm": 5.0, "allow_overlap": False},
        "protocol": ["Wheels/suspension/lights, the **must-not-touch** kind: give min_mm as the process clearance (including suspension travel)",
                     "Panels/skin, the **overlap-permitted** kind: allow_overlap=true (interpenetration is the design intent)",
                     "Use it inside the gate: write the rules into spec.py first, then have gate_run judge them all in one pass"],
        "limits": ["Clearance is sample-point distance (large parallel flush surfaces may be overestimated); interpenetration detection is exact",
                   "Only relationships listed in pairs are looked at"],
        "kernel": "shared kernel K.dsh_kit v%s" % getattr(_KIT, "version", "?"),
    })


# Registration: one line (previously about 50 lines of hand-written _j + _DshApi + dispatch + registration)
_KIT.register("clearance", CLEAR_VERSION, {"check": clear_check, "selftest": clear_selftest, "help": clear_help},
              extra={"pairwise_clearance": _KIT.pairwise_clearance})