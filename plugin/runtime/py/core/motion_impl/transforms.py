# -*- coding: utf-8 -*-
"""Split from motion.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403



# ============================================================ sweep verification

_TF_FIELDS = ("location", "scale", "rotation_euler", "rotation_quaternion",
              "delta_location", "delta_scale", "delta_rotation_euler", "delta_rotation_quaternion")
TOL_MAT = 1e-6          # matrix_world comparison tolerance (Blender stores transforms as float32 internally)

# v2.6.1: the batch update helper prefers K.dsh_kit.BatchUpdates; when an old kernel/inline test does not have it, a local fallback is used,
# so "kit and module versions out of sync" does not raise AttributeError directly (the module does not hard-depend on the new kit).
_BatchUpdates = getattr(_KIT, "BatchUpdates", None)
if _BatchUpdates is None:
    class _BatchUpdates:  # noqa: F811 - local fallback, behaviour identical to the kit version
        def __init__(self, view_layer=None):
            import bpy as _bpy
            self.vl = view_layer or _bpy.context.view_layer
            self.stages = 0
            self.updates = 0
        def flush(self):
            self.vl.update()
            self.updates += 1
            return self


def _snap_transforms(objs):
    """Snapshot transforms: matrix (for comparison) + original fields (for restoring, bit-identical floats)."""
    snap = {}
    for ob in objs:
        fields = {}
        for f in _TF_FIELDS:
            v = getattr(ob, f, None)
            if v is None:
                continue
            try:
                fields[f] = [float(x) for x in v]
            except Exception:
                pass
        snap[ob.name] = {"mode": ob.rotation_mode,
                         "matrix": [float(x) for row in ob.matrix_world for x in row],
                         "parent_inverse": [float(x) for row in ob.matrix_parent_inverse for x in row],
                         "fields": fields}
    return snap


def _mat_of(rec):
    m = rec["matrix"]
    return Matrix([m[0:4], m[4:8], m[8:12], m[12:16]])


def _mat_now(ob):
    return [float(x) for row in ob.matrix_world for x in row]


def _snap_diff(a, b, tol=TOL_MAT):
    """Compare two {name: 16-element matrix} snapshots object by object, entry by entry → (max difference, out-of-tolerance objects, whether every entry is exactly equal)."""
    mx, bad = 0.0, []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        if va is None or vb is None or len(va) != len(vb):
            bad.append(k)
            continue
        d = max(abs(x - y) for x, y in zip(va, vb))
        mx = max(mx, d)
        if d > tol:
            bad.append(k)
    return mx, bad, bool(mx == 0.0)


def _restore_transforms(objs, snap, touched=None):
    """Restore transforms to the snapshot; only "touched" objects are written (untouched objects are merely compared entry by entry, never rewritten).

    v2.6.1 performance: field writes no longer update per object — write everything first, then one update and a single verification pass;
    only objects that fall back to writing the matrix need an extra update. Semantics match the old implementation (guarded by the native motion E2E's per-object matrix_world restore check).

    Returns (mismatches, pre_delta, wrote): pre_delta = the largest deviation found before restoring,
    and the residual deviation after restoring is written into each object's comparison (an empty mismatches means every entry is equal).
    """
    touched = set(touched or [])
    batch = _BatchUpdates()
    batch.flush()                            # starting baseline (same as the old implementation)
    mism, pre_max, post_max, wrote = [], 0.0, 0.0, []
    pending = []

    # first pass: write fields only, no per-object update
    for ob in objs:
        rec = snap.get(ob.name)
        if rec is None:
            mism.append({"name": ob.name, "reason": "this object is not in the snapshot"})
            continue
        now = _mat_now(ob)
        d = max(abs(a - b) for a, b in zip(rec["matrix"], now))
        pre_max = max(pre_max, d)
        if d <= TOL_MAT and ob.name not in touched:
            post_max = max(post_max, d)
            continue                        # untouched → every entry is equal, no write-back needed
        try:
            if ob.rotation_mode != rec["mode"]:
                ob.rotation_mode = rec["mode"]
            for f, v in rec["fields"].items():
                setattr(ob, f, v)
            ob.matrix_parent_inverse = _mat_of({"matrix": rec["parent_inverse"]})
        except Exception as e:
            mism.append({"name": ob.name, "reason": "field restore failed: %s" % str(e)[:120]})
            continue
        wrote.append(ob.name)
        pending.append((ob, rec))

    if not pending:
        return mism, pre_max, post_max, wrote

    batch.flush()                            # ★ one update instead of "one per object"
    residual = {}
    fallback = []
    for ob, rec in pending:
        now2 = _mat_now(ob)
        d2 = max(abs(a - b) for a, b in zip(rec["matrix"], now2))
        residual[ob.name] = d2
        if d2 > TOL_MAT:
            fallback.append((ob, rec))

    if fallback:
        for ob, rec in fallback:
            try:                            # fallback: write the matrix directly
                ob.matrix_world = _mat_of(rec)
            except Exception as e:
                mism.append({"name": ob.name, "reason": "matrix restore failed: %s" % str(e)[:120]})
                residual.pop(ob.name, None)
        batch.flush()
        # the matrix fallback may affect children / parent-child pairs with other pending objects ⇒ re-verify everything; anything still off gets one more single-object fix
        for ob, rec in pending:
            if ob.name not in residual:
                continue
            now3 = _mat_now(ob)
            d3 = max(abs(a - b) for a, b in zip(rec["matrix"], now3))
            residual[ob.name] = d3
            if d3 > TOL_MAT:
                try:
                    ob.matrix_world = _mat_of(rec)
                    batch.flush()
                    now4 = _mat_now(ob)
                    d4 = max(abs(a - b) for a, b in zip(rec["matrix"], now4))
                    residual[ob.name] = d4
                    if d4 > TOL_MAT:
                        mism.append({"name": ob.name, "reason": "transform not restored", "residual": d4,
                                     "want": _rl(rec["matrix"], 9), "got": _rl(now4, 9)})
                except Exception as e:
                    mism.append({"name": ob.name, "reason": "matrix restore failed: %s" % str(e)[:120]})
                    residual.pop(ob.name, None)

    for ob, rec in pending:
        if ob.name in residual:
            post_max = max(post_max, residual[ob.name])
    return mism, pre_max, post_max, wrote

def _phase_values(jrec, phases, sweep_deg, margin_frac, V):
    """Phase values: with limits use limits (leaving a margin at both ends), otherwise revolute uses ±sweep_deg/2."""
    k = jrec["kind"]
    if jrec.get("limits"):
        lo, hi = float(jrec["limits"][0]), float(jrec["limits"][1])
        unit = "deg" if k in ("revolute", "continuous") else "scene_unit"
    elif k in ("revolute", "continuous"):
        lo, hi = -abs(float(sweep_deg)) / 2.0, abs(float(sweep_deg)) / 2.0
        unit = "deg"
    else:  # prismatic: without limits, use 10% of the child's diagonal as the travel
        _, _, diag = _bbox(V)
        span = max(0.1 * (diag or 1.0), 1e-6)
        lo, hi = -span, span
        unit = "scene_unit"
    span = hi - lo
    if not (span > 0):
        return None, None, None, "limits/travel span is 0, cannot sweep"
    m = span * float(margin_frac)
    lo2, hi2 = lo + m, hi - m
    n = max(2, int(phases or 8))
    vals = [lo2 + (hi2 - lo2) * (i / float(n - 1)) for i in range(n)]
    return vals, unit, span, None
