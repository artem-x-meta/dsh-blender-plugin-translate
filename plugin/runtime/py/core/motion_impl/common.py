# -*- coding: utf-8 -*-
"""DSH motion/articulation layer (motion v1, Procedura integration batch 2) —— turns assembly relations into "verifiable joints
+ URDF/USDA export + a kinematic sweep proving it really moves".

Why it exists
    Upstream SpatiaOS/Procedura (MIT) uses NVIDIA Isaac for articulation verification: JointSpec → URDF/USDA → physics simulation.
    There is no Isaac on this machine (and none is planned), so the last step is replaced with two real things on the Blender side:
      ① **measured axes** (the analyzeRotationalSymmetry / analyzeContactRegion idea from geometry.ts) ——
         sample cap 3000, score threshold 0.55, degenerate (sphere/near-cube) criterion 0.08 are all copied verbatim;
      ② **driven sweep + BVH interference self-check** —— drive the child group around the joint axis (or along it) through N phases,
         and per phase compute interference pairs and the minimum distance against objects "not on this joint chain"; zero interference throughout plus real displacement ⇒ supported.
     URDF/USDA export of the joint tree (single-tree merge, spherical/6DOF/distance joint downgrade, SI units, bbox-approximated inertia) also lands here.

Boundaries (stated honestly; do not treat them as capabilities)
    * The sweep is a **kinematic** verification, not a physical one: there is no mass/friction/drive dynamics, it only answers "will it hit something if it moves along this axis".
    * The minimum distance approximates by **two-way vertex+face-centre sampling onto the other surface** (biased high relative to the upper bound); interference is decided by BVH triangle intersection (exact).
      Penetration depth is estimated from "the orientation of the nearest face normal" and is approximate.
    * Axis inference only works on "identifiable" geometry: cylinders/wheels/pins (rotational symmetry) or elongated contact bands (parent↔child contact region).
      A door-like thin plate around a hinge axis has **no** rotational symmetry → it honestly reports unresolved and never forces an axis.
    * USDA is **minimal usable ASCII**: the structure is readable (Xform / Mesh / joint custom attributes), it is not a complete UsdPhysics schema.

State lives in the persistent kernel K.dsh_motion (kept across calls); the API hangs off K.dsh_motion_api.
Entry points:
    blender_rt_headless(engine="none", preload="motion", script="print(K.dsh_motion_api['selftest']())")
    K.dsh_motion_api["dispatch"]("joint", {"jid": "hinge", "parent": "Base", "child": "Door"})
    K.dsh_motion_api["dispatch"]("measure", {"jid": "hinge", "phases": 8, "sweep_deg": 60})

Hard rules: empty output must be ok=false; the verdict is three-state (supported / refuted / unresolved, unresolved when evidence is thin);
        numbers carry units; at the end of a sweep the scene transform **must** be fully restored (compared object by object, mismatches reported).
"""
import math
import os
import time

import bpy
import numpy as np

MOTION_VERSION = 1

# ---- Axis inference (conventions copied from src/motion/geometry.ts) ----
SYMMETRY_SAMPLE_CAP = 3000       # upper bound on sample points scored per object
SYMMETRY_MIN_SCORE = 0.55        # below it → that axis is judged unresolved
DEGENERATE_GAP = 0.08            # difference between the runner-up and best axis ≤ it → degenerate (sphere/near-cube)
SYMMETRY_CELL_FRAC = 0.02        # spatial hash cell edge = bbox diagonal × it
SYMMETRY_CAP_FRAC = 0.05         # distance normalisation cap = bbox diagonal × it
CONTACT_SAMPLE_CAP = 4000        # contact-region sample cap
CONTACT_MIN_POINTS = 8           # minimum points in a contact region
ELONGATION_THRESHOLD = 2.0       # contact-band aspect-ratio threshold (below it, not hinge evidence)
CONSENSUS_ANGLE_DEG = 10.0       # criterion for candidates from several objects agreeing in direction

# ---- Export ----
BBOX_FILL_FACTOR = 0.4           # fill factor from bbox volume → solid volume (copied from upstream)
MIN_INERTIA = 1e-6               # lower bound on inertia (kg·m²)
DEFAULT_DENSITY = 1000.0         # kg/m³
DEFAULT_EFFORT = 1000.0          # N·m / N
DEFAULT_VELOCITY = 100.0         # rad/s (angular) / m/s (linear)
MIN_LINK_MESH_DIAG = 1e-12

# ---- Joint kinds ----
AXIS_KINDS = ("revolute", "continuous", "prismatic")            # must have an axis
FIXED_KINDS = ("fixed",)
PASSIVE_KINDS = ("spherical", "d6", "distance", "planar", "floating",
                 "gear", "rack_and_pinion")                     # not expressible in URDF → downgraded to fixed
ALL_KINDS = AXIS_KINDS + FIXED_KINDS + PASSIVE_KINDS
VERDICTS = ("supported", "refuted", "unresolved")
MAX_DIST_SAMPLES = 400           # per-side sample cap of the minimum-distance probe
MAX_OVERLAP_REPORT = 8           # max triangle pairs reported per interfering pair


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("motion requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the former built-in implementation has been removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


def _store():
    K = _kernel()
    if K is None:
        raise RuntimeError("persistent kernel K required (use the blender_rt_* channel; in headless use preload='motion')")
    if not hasattr(K, "dsh_motion"):
        K.dsh_motion = {"joints": {}, "exports": [], "log": [], "seq": 0}
    return K.dsh_motion


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log(action, detail):
    try:
        st = _store()
    except Exception:
        return
    st["log"].append({"t": _now(), "action": action, "detail": detail})
    del st["log"][:-200]


def _out_dir():
    K = _kernel()
    d = getattr(K, "out_dir", None) if K is not None else None
    return d or os.path.join(os.path.expanduser("~"), "dsh_motion")


def _win(path):
    """WSL → Windows-side path (Blender is a Windows process). Uses K.win_path when available."""
    K = _kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return K.win_path(path)
        except Exception:
            pass
    s = str(path)
    if s.startswith("/mnt/") and len(s) > 6:
        return s[5].upper() + ":" + chr(92) + s[7:].replace("/", chr(92))
    return s


def _scene_mpu():
    """Scene units → metres (scale_length; a default of 1.0 means 1 unit = 1 m). Every number goes through it, never hard-coded."""
    try:
        v = float(bpy.context.scene.unit_settings.scale_length)
        return v if v > 0 else 1.0
    except Exception:
        return 1.0


def _mpu_arg(meters_per_unit):
    """meters_per_unit argument: a number is used directly; "auto"/"scene" read the scene scale_length; None → 0.001 (upstream stage convention)."""
    if isinstance(meters_per_unit, str):
        s = meters_per_unit.strip().lower()
        if s in ("auto", "scene"):
            return _scene_mpu()
        try:
            v = float(s)
        except Exception:
            return 0.001
        return v if v > 0 else 0.001
    try:
        v = float(meters_per_unit) if meters_per_unit is not None else 0.001
    except Exception:
        return 0.001
    return v if v > 0 else 0.001


def _units_warnings(mpu, model_diag_m, warnings):
    """Unit check: if the whole model measures under 1 cm after conversion ⇒ the scene is most likely metric (the 0.001 default is meant for mm scenes)."""
    suspect = bool(model_diag_m and model_diag_m > 0 and model_diag_m < 0.01)
    if suspect:
        warnings.append("Suspicious units: converted with meters_per_unit=%g the whole model diagonal is only %.4g m (under 1 cm) —— "
                        "if the scene is metric (Blender default scale_length=1.0), pass meters_per_unit=\"scene\" or 1.0;"
                        " the mass/inertia in the current output follow that conversion and may be off by several orders of magnitude" % (mpu, model_diag_m))
    return suspect


def _r(x, n=6):
    try:
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return round(v, n)
    except Exception:
        return x


def _rl(v, n=6):
    try:
        return [_r(float(x), n) for x in v]
    except Exception:
        return v


def _names(x):
    """Object-name argument: accepts str / list / {'objects': [...]}."""
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return _names(x.get("objects") or x.get("names") or x.get("list") or [])
    try:
        return [str(i) for i in x]
    except Exception:
        return [str(x)]


def _objs(names, mesh_only=True):
    out, missing, non_mesh = [], [], []
    for n in _names(names):
        ob = bpy.data.objects.get(n)
        if ob is None:
            missing.append(n)
            continue
        if mesh_only and ob.type != "MESH":
            non_mesh.append(n)
            continue
        out.append(ob)
    return out, missing, non_mesh


def _link_key(names):
    return tuple(sorted(str(n) for n in _names(names)))


def _safe_name(s, fallback="link"):
    t = "".join((c if (c.isalnum() or c in "_-.") else "_") for c in str(s))
    t = t.strip("_")
    return t or fallback


def _link_name(names):
    ns = _names(names)
    if not ns:
        return "link"
    if len(ns) == 1:
        return _safe_name(ns[0])
    return _safe_name("_".join(ns))


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fnum(x):
    """Numbers inside URDF/USDA: %.9g (keeps small magnitudes, switches to exponent notation when needed; URDF and USD both accept 1e-11).

    Note: an earlier "%.9f" wrote the mass/inertia of mm-scale models (e.g. 8.6e-11) out as "0" —— a silent error.
    """
    try:
        v = float(x)
    except Exception:
        return "0"
    if v != v or v in (float("inf"), float("-inf")):
        return "0"
    s = "%.9g" % v
    if "e" in s or "E" in s:
        m, e = s.lower().split("e")
        if m.endswith("."):
            m = m[:-1]
        return "%se%d" % (m, int(e))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


# ============================================================ geometry: world triangles / bbox / sampling

def _mesh_tris_world(ob, dg=None):
    """An object's (evaluated) triangles → world coordinates. Returns (V(N,3) float64, F(M,3) int32)."""
    obe = ob.evaluated_get(dg) if dg is not None else ob
    me = obe.to_mesh()
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        V = np.empty((nv, 3), dtype=np.float64)
        if nv:
            me.vertices.foreach_get("co", V.ravel())
        nt = len(me.loop_triangles)
        F = np.empty((nt, 3), dtype=np.int32)
        if nt:
            me.loop_triangles.foreach_get("vertices", F.ravel())
    finally:
        obe.to_mesh_clear()
    M = np.array(ob.matrix_world, dtype=np.float64)
    if len(V):
        V = V @ M[:3, :3].T + M[:3, 3]
    return V, F


def _group_tris(objs, dg=None):
    """A group of objects → merged world triangles (V, F, parts), parts = [{name, v0, v1}] so results can be attributed per object."""
    Vs, Fs, parts, off = [], [], [], 0
    for ob in objs:
        V, F = _mesh_tris_world(ob, dg)
        if len(V) == 0:
            continue
        Vs.append(V)
        Fs.append(F + off if len(F) else F)
        parts.append({"name": ob.name, "v0": off, "v1": off + len(V),
                      "verts": int(len(V)), "tris": int(len(F))})
        off += len(V)
    if not Vs:
        return (np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32), [])
    return (np.concatenate(Vs, axis=0), np.concatenate(Fs, axis=0) if Fs else np.zeros((0, 3), np.int32), parts)


def _bbox(V):
    if V is None or len(V) == 0:
        return None, None, 0.0
    mn = V.min(axis=0)
    mx = V.max(axis=0)
    return mn, mx, float(np.linalg.norm(mx - mn))


def _sample_points(V, F, cap):
    """Deterministic sampling: vertices (uniform stride) + triangle centroids (adds shape information, avoids the holes you get from vertices alone)."""
    if len(V) == 0:
        return np.zeros((0, 3))
    step = max(1, int(math.ceil(len(V) / float(max(1, cap)))))
    P = V[::step]
    if len(F):
        cents = V[F].mean(axis=1)
        step2 = max(1, int(math.ceil(len(cents) / float(max(1, cap)))))
        P = np.concatenate([P, cents[::step2]], axis=0)
    return P


def _dense_samples(V, F, cap):
    """Area-weighted dense sampling (deterministic barycentric grid): big faces get more points by area —— this is what keeps contact-band analysis from being fooled by sparse vertices."""
    if len(V) == 0 or len(F) == 0:
        return _sample_points(V, F, cap)
    tri = V[F]
    areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    tot = float(areas.sum())
    if tot <= 1e-18:
        return _sample_points(V, F, cap)
    cap = max(8, int(cap))
    out, left = [], cap
    for idx in np.argsort(-areas, kind="stable"):     # deterministic: area descending
        if left <= 0:
            break
        n = int(max(1, min(left, round(cap * float(areas[idx]) / tot))))
        m = int(max(1, math.ceil(math.sqrt(2.0 * n))))
        a = V[F[idx]]
        cnt = 0
        for i in range(m):
            for j in range(m - i):
                u, v = i / float(m), j / float(m)
                out.append(a[0] + u * (a[1] - a[0]) + v * (a[2] - a[0]))
                cnt += 1
                if cnt >= n:
                    break
            if cnt >= n:
                break
        left -= cnt
    if not out:
        return _sample_points(V, F, cap)
    return np.asarray(out, dtype=np.float64)


def _rot_pts(P, origin, axis, cos_t, sin_t):
    """Rodrigues: rotate the point set around (origin, axis)."""
    if len(P) == 0:
        return P
    k = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(k))
    if n < 1e-30:
        return P.copy()
    k = k / n
    v = P - origin
    dot = v.dot(k)
    cross = np.cross(np.broadcast_to(k, v.shape), v)
    return origin + v * cos_t + cross * sin_t + np.outer(dot, k) * (1.0 - cos_t)


def _nearest_dists(points, queries, cell, cap):
    """Nearest distance from each query point to points (27-cell hash); beyond the neighbourhood → clamped to cap (conservative)."""
    if len(queries) == 0:
        return np.zeros((0,))
    if len(points) == 0 or cell <= 1e-30:
        return np.full((len(queries),), cap)
    grid = {}
    for i, p in enumerate(points):
        key = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)), int(math.floor(p[2] / cell)))
        grid.setdefault(key, []).append(i)
    Pp = points
    out = np.full((len(queries),), cap, dtype=np.float64)
    for qi in range(len(queries)):
        q = queries[qi]
        cx = int(math.floor(q[0] / cell)); cy = int(math.floor(q[1] / cell)); cz = int(math.floor(q[2] / cell))
        best = cap
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    lst = grid.get((cx + dx, cy + dy, cz + dz))
                    if not lst:
                        continue
                    idx = np.asarray(lst, dtype=np.int64)
                    d = np.sqrt(((Pp[idx] - q) ** 2).sum(axis=1)).min()
                    if d < best:
                        best = float(d)
        out[qi] = best
    return out


def _canon_dir(d):
    """Deterministic sign: the largest component is made positive."""
    a = np.asarray(d, dtype=np.float64)
    n = float(np.linalg.norm(a))
    if n < 1e-30:
        return np.array([0.0, 0.0, 1.0])
    a = a / n
    ix = int(np.argmax(np.abs(a)))
    return -a if a[ix] < 0 else a


def _snap_axis(d):
    if abs(d[0]) >= 0.95:
        return "X"
    if abs(d[1]) >= 0.95:
        return "Y"
    if abs(d[2]) >= 0.95:
        return "Z"
    return None


def _angle_deg(a, b):
    a = np.asarray(a, dtype=np.float64); b = np.asarray(b, dtype=np.float64)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-30 or nb < 1e-30:
        return None
    c = float(np.clip(abs(np.dot(a, b)) / (na * nb), -1.0, 1.0))
    return math.degrees(math.acos(c))


def _dist_point_line(p, origin, axis):
    v = np.asarray(p, dtype=np.float64) - np.asarray(origin, dtype=np.float64)
    k = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(k))
    if n < 1e-30:
        return None
    k = k / n
    return float(np.linalg.norm(v - k * float(np.dot(v, k))))


__all__ = [name for name in list(globals()) if not name.startswith("__")]
