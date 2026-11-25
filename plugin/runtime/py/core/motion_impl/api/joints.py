# -*- coding: utf-8 -*-
"""motion status/help surface: joint registry introspection (moved out of api.py)."""
from ..common import *  # noqa: F401,F403


# ============================================================ status / help

def motion_status():
    st = _store()
    js = {}
    counts = {"supported": 0, "refuted": 0, "unresolved": 0}
    for k, v in st["joints"].items():
        mv = (v.get("measured") or {}).get("verdict")
        av = v.get("axis_verdict") or "unresolved"
        vv = mv or av
        counts[vv if vv in counts else "unresolved"] = counts.get(vv if vv in counts else "unresolved", 0) + 1
        js[k] = {"kind": v["kind"], "parent": v["parent"], "child": v["child"],
                 "axis": v.get("axis"), "anchor": v.get("anchor"),
                 "axis_source": v.get("axis_source"), "axis_verdict": av,
                 "limits": v.get("limits"), "note": v.get("note"),
                 "measured": ({"verdict": mv, "moved": (v.get("measured") or {}).get("moved"),
                               "phases": len((v.get("measured") or {}).get("phases") or []),
                               "reason": (v.get("measured") or {}).get("reason"),
                               "restored_ok": (v.get("measured") or {}).get("restored_ok"),
                               "t": (v.get("measured") or {}).get("t")} if v.get("measured") else None),
                 "warnings": v.get("warnings") or []}
    return _j({"ok": True, "op": "status", "version": MOTION_VERSION,
               "joints": js, "joint_count": len(js),
               "verdict_counts": counts,
               "exports": st["exports"], "export_count": len(st["exports"]),
               "log_tail": st["log"][-10:],
               "units": {"length": "scene_unit (1 unit = %g m)" % _scene_mpu(), "angle": "deg"},
               "boundary": "joint axes are measurable (rotational symmetry / contact band); sweep is a kinematic check, not a physics check;"
                           "USDA is not the full UsdPhysics schema"})


def motion_help():
    return _j({
        "version": MOTION_VERSION,
        "ops": {
            "joint": "motion_joint(jid, parent, child, kind='revolute', axis=None, anchor=None, limits=None, "
                     "note='') — parent/child are object names or lists of object names (rigid group); if axis/anchor are not given they are inferred by measurement",
            "infer_axis": "motion_infer_axis(jid=None, objects=None, parent=None, sample_cap=3000, "
                          "min_score=0.55, max_distance=None) → evidence + three-state (a thin flat plate has no rotational symmetry about a hinge axis ⇒ unresolved)",
            "joints": "motion_joints() → registered joints + axis verdict + measurement summary",
            "measure": "motion_measure(jid=None, phases=8, sweep_deg=60, margin_frac=0.05, exclude=None, "
                       "chain_depth='full', max_candidates=64, max_samples=400) → sweep (interference pairs + minimum distance)",
            "export_urdf": "motion_export_urdf(dir, name='model', joints=None, meters_per_unit=0.001, "
                           "density=1000, masses=None, mesh_format='obj', effort=1000, velocity=100) "
                           "→ <dir>/<name>.urdf + <dir>/meshes/*.obj + structural self-check",
            "export_usda": "motion_export_usda(dir, name='model', joints=None, meters_per_unit=0.001, "
                           "density=1000, masses=None) → minimal usable ASCII USDA + structural self-check",
            "status": "motion_status() → joints + verdicts + export history (K.dsh_motion)",
            "selftest": "motion_selftest() → synthetic hinge self-test (runs headless, brings its own scene/cleanup)",
            "help": "motion_help()",
        },
        "typical": "K.dsh_motion_api['dispatch']('joint', {'jid':'hinge','parent':['Base'],"
                   "'child':['Door','Pin'],'kind':'revolute','limits':[-90,90]}) → "
                   "K.dsh_motion_api['dispatch']('measure', {'jid':'hinge','phases':8,'sweep_deg':60}) → "
                   "K.dsh_motion_api['dispatch']('export_urdf', {'dir': K.out_dir, 'name':'door'})",
        "rules": {
            "verdict": "supported / refuted / unresolved three-state; insufficient evidence is always unresolved (never force a yes/no)",
            "ok": "ok=false ⇔ unresolved or empty output (0 link / 0 joint / no axis / no child geometry)",
            "units": "revolute limits/phase=deg; prismatic=scene units; distances are given in both scene_unit and m; URDF=SI",
            "restore": "after the sweep, matrix_world is compared per object (all objects); mismatches are written into restored",
        },
        "boundary": [
            "sweep = kinematics + BVH interference, not Isaac-style physics validation (no mass/friction/drive dynamics)",
            "minimum distance is a sampling approximation (on the conservative/large side); interference is decided by BVH triangle intersection (exact)",
            "zero interference needs at least one 'bystander' object, otherwise the evidence is empty → that case is unresolved",
            "axis inference only works for identifiable geometry; contact-band evidence needs enough contact points within the parent group + max_distance",
            "when the two pieces of evidence (rotational symmetry / contact band) contradict each other it is always unresolved, never decided for the user",
            "export requires the joint groups not to overlap (an object can belong to only one link), otherwise ok=false",
            "USDA is the minimal usable ASCII, not the full UsdPhysics schema",
        ],
    })
