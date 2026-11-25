# -*- coding: utf-8 -*-
"""DSH vehicle shell: reference image → longitudinal profile numbers → lofted shell → proportion gate + clearance (constructive interpenetration prevention).

Why it is designed this way (settled against the approaches on GitHub):
  * fpagerie/cargen (a Blender add-on) proves a car shell can be **generated from parameters**: length/width/height, wheelbase, front axle to nose, wheel + tyre radius,
    wheel width, wheel sink into the floor, grille height, hood angle/length, windshield angle, roof length/angle, rear window angle/height, trunk angle (meters + degrees, angles measured from horizontal).
  * The vehicle-design skill's "Proportion-First": wheel diameter / car height (WBR) sports car 35-40% / supercar 40-45% / muscle car 30-35% /
    SUV 25-30%; and it states outright that "no amount of surface detail can rescue wrong proportions".

Key design: **the wheel arches are cut analytically out of the profile** (at each station the bottom is lifted above the wheel circle + clearance), not a post-hoc boolean —
so "wheel through the body" is constructively impossible (interpenetration eliminated at the root, rather than detected afterwards).

ops:
    vehicle_spec(...)      — parameters → validated spec (a reference image can also be given so the proportions measured by human/img fill in)
    vehicle_package(spec)  — proportion gate: WBR / wheelbase ratio / front and rear overhang / track ratio / ride height, with per-type tolerances
    vehicle_base(spec)     — loft the shell (with analytic wheel arches) + four wheels + axle/ground markers
    vehicle_selftest / vehicle_help
"""
import json as json
import math

import bmesh as bmesh
import bpy as bpy


VEHICLE_VERSION = 1

# Vehicle type → proportion ranges (source: the vehicle-design skill's Proportion-First protocol)
# WBR = wheel diameter / overall height. Ranges are **calibrated on real cars** (911(992) 1300/680 ⇒ 52%; Corolla 1435/632 ⇒ 44%;
# Range Rover 1870/781 ⇒ 42%) — the 35-45% in the vehicle-design skill is a different basis (relative to the body rather than overall height),
# so the overall-height basis is used here and stated explicitly, so the wrong reference is not taken.
TYPES = {
    "sports":    {"wbr": (0.46, 0.56), "wheelbase_over_len": (0.55, 0.65), "h_over_len": (0.24, 0.30)},
    "supercar":  {"wbr": (0.50, 0.58), "wheelbase_over_len": (0.55, 0.65), "h_over_len": (0.22, 0.28)},
    "muscle":    {"wbr": (0.44, 0.53), "wheelbase_over_len": (0.52, 0.62), "h_over_len": (0.26, 0.32)},
    "suv":       {"wbr": (0.38, 0.46), "wheelbase_over_len": (0.55, 0.68), "h_over_len": (0.32, 0.40)},
    "truck":     {"wbr": (0.34, 0.46), "wheelbase_over_len": (0.55, 0.70), "h_over_len": (0.33, 0.45)},
    "sedan":     {"wbr": (0.40, 0.48), "wheelbase_over_len": (0.55, 0.65), "h_over_len": (0.26, 0.32)},
}
DEFAULTS = {
    "profile_pts": None,   # explicit polyline profile (outer-surface reconstruction: control points come straight from the reference image)
    "type": "sports", "length_mm": 4300.0, "width_mm": 1850.0, "height_mm": 1250.0,
    "wheelbase_mm": 2600.0, "front_axle_from_front_mm": 900.0, "wheel_r_mm": 340.0, "wheel_w_mm": 245.0,
    "wheel_sink_frac": 0.15, "track_mm": 1580.0, "ride_mm": 110.0, "arch_clear_mm": 12.0,
    "grille_h_mm": 300.0, "hood_angle_deg": 3.0, "hood_len_mm": 1150.0, "windshield_angle_deg": 32.0,
    "roof_len_mm": 950.0, "roof_angle_deg": 0.0, "rear_window_angle_deg": 34.0, "rear_window_h_mm": 330.0,
    "trunk_angle_deg": 6.0,
}


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("vehicle needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original local implementation was removed)
_api = _KIT.api  # shared kernel
def _num(v, name, lo, hi, dflt=None):
    if v is None:
        if dflt is None:
            raise ValueError("%s is required" % name)
        return float(dflt)
    f = float(v)
    if not (lo <= f <= hi):
        raise ValueError("%s=%g out of range [%g, %g]" % (name, f, lo, hi))
    return f


def vehicle_spec(**kw):
    """parameters → validated spec (mm/deg). Missing values take the type defaults."""
    sp = dict(DEFAULTS)
    for k, v in (kw or {}).items():
        if v is not None and k in sp:
            sp[k] = v
    t = str(sp.get("type") or "sports").lower()
    if t not in TYPES:
        raise ValueError("unknown car type=%s (allowed %s)" % (sp.get("type"), sorted(TYPES)))
    sp["type"] = t
    sp["length_mm"] = _num(sp.get("length_mm"), "length_mm", 1500.0, 15000.0)
    sp["width_mm"] = _num(sp.get("width_mm"), "width_mm", 800.0, 4000.0)
    sp["height_mm"] = _num(sp.get("height_mm"), "height_mm", 500.0, 5000.0)
    sp["wheelbase_mm"] = _num(sp.get("wheelbase_mm"), "wheelbase_mm", 800.0, 10000.0)
    sp["front_axle_from_front_mm"] = _num(sp.get("front_axle_from_front_mm"), "front_axle_from_front_mm", 100.0, 5000.0)
    sp["wheel_r_mm"] = _num(sp.get("wheel_r_mm"), "wheel_r_mm", 100.0, 1200.0)
    sp["wheel_w_mm"] = _num(sp.get("wheel_w_mm"), "wheel_w_mm", 60.0, 900.0)
    sp["wheel_sink_frac"] = _num(sp.get("wheel_sink_frac"), "wheel_sink_frac", 0.0, 0.6)
    sp["track_mm"] = _num(sp.get("track_mm"), "track_mm", 500.0, 3500.0)
    sp["ride_mm"] = _num(sp.get("ride_mm"), "ride_mm", 20.0, 800.0)
    sp["arch_clear_mm"] = _num(sp.get("arch_clear_mm"), "arch_clear_mm", 0.0, 120.0)
    for k in ("grille_h_mm", "hood_len_mm", "roof_len_mm", "rear_window_h_mm"):
        sp[k] = _num(sp.get(k), k, 0.0, 8000.0)
    for k in ("hood_angle_deg", "windshield_angle_deg", "roof_angle_deg", "rear_window_angle_deg", "trunk_angle_deg"):
        sp[k] = _num(sp.get(k), k, -20.0, 80.0)
    # Consistency: wheelbase + front axle to nose must not exceed the length; track must not exceed width
    if sp["front_axle_from_front_mm"] + sp["wheelbase_mm"] > sp["length_mm"]:
        raise ValueError("front axle to nose(%.0f) + wheelbase(%.0f) = %.0f exceeds length %.0f"
                         % (sp["front_axle_from_front_mm"], sp["wheelbase_mm"],
                            sp["front_axle_from_front_mm"] + sp["wheelbase_mm"], sp["length_mm"]))
    if sp["track_mm"] + sp["wheel_w_mm"] > sp["width_mm"]:
        raise ValueError("track(%.0f) + wheel width(%.0f) exceeds width(%.0f)" % (sp["track_mm"], sp["wheel_w_mm"], sp["width_mm"]))
    if 2.0 * sp["wheel_r_mm"] > 0.65 * sp["height_mm"]:
        raise ValueError("wheel diameter(%.0f) is larger than car height(%.0f)" % (2.0 * sp["wheel_r_mm"], sp["height_mm"]))
    return sp


def vehicle_package(spec=None, **kw):
    """proportion gate (numbers only): WBR / wheelbase ratio / height-to-length ratio / front and rear overhang / track ratio / ride height. Per item pass/fail."""
    # Partial parameters must still pass: merge the given keys onto DEFAULTS and validate (otherwise a missing ride_mm and the like raise KeyError)
    if isinstance(spec, dict) and spec:
        kw = dict({k: x for k, x in spec.items() if k in DEFAULTS}, **kw)
    sp = vehicle_spec(**kw)
    t = str(sp.get("type") or "sports").lower()
    lim = TYPES.get(t, TYPES["sports"])
    wbr = (2.0 * sp["wheel_r_mm"]) / sp["height_mm"]
    wb_l = sp["wheelbase_mm"] / sp["length_mm"]
    h_l = sp["height_mm"] / sp["length_mm"]
    track_w = sp["track_mm"] / sp["width_mm"]
    front_oh = sp["front_axle_from_front_mm"] - sp["wheel_r_mm"]
    rear_oh = sp["length_mm"] - (sp["front_axle_from_front_mm"] + sp["wheelbase_mm"]) - sp["wheel_r_mm"]
    rows = [
        {"metric": "wheel_to_body_ratio", "value": round(wbr, 4), "range": list(lim["wbr"]),
         "verdict": "pass" if lim["wbr"][0] <= wbr <= lim["wbr"][1] else "fail",
         "note": "wheel diameter / car height: the eye is most sensitive to this one"},
        {"metric": "wheelbase_over_len", "value": round(wb_l, 4), "range": list(lim["wheelbase_over_len"]),
         "verdict": "pass" if lim["wheelbase_over_len"][0] <= wb_l <= lim["wheelbase_over_len"][1] else "fail"},
        {"metric": "height_over_len", "value": round(h_l, 4), "range": list(lim["h_over_len"]),
         "verdict": "pass" if lim["h_over_len"][0] <= h_l <= lim["h_over_len"][1] else "fail"},
        {"metric": "track_over_width", "value": round(track_w, 4), "range": [0.80, 0.92],
         "verdict": "pass" if 0.80 <= track_w <= 0.92 else "fail",
         "note": "track / width: too narrow looks like a toy, too wide puts the wheels outside"},
        {"metric": "front_overhang_mm", "value": round(front_oh, 1), "range": [0.0, 0.55 * sp["wheel_r_mm"] * 2],
         "verdict": "pass" if front_oh >= 0 else "fail"},
        {"metric": "rear_overhang_mm", "value": round(rear_oh, 1), "range": [0.0, 0.70 * sp["wheel_r_mm"] * 2],
         "verdict": "pass" if rear_oh >= 0 else "fail"},
        {"metric": "ride_mm", "value": round(sp["ride_mm"], 1), "range": [0.15 * sp["wheel_r_mm"], 0.60 * sp["wheel_r_mm"]],
         "verdict": "pass" if 0.15 * sp["wheel_r_mm"] <= sp["ride_mm"] <= 0.60 * sp["wheel_r_mm"] else "fail"},
    ]
    failed = [r["metric"] for r in rows if r["verdict"] == "fail"]
    return _j({"ok": not failed, "verdict": ("pass" if not failed else "fail"), "type": t, "rows": rows,
               "failed": failed, "spec_echo": {k: sp[k] for k in ("length_mm", "width_mm", "height_mm", "wheelbase_mm", "wheel_r_mm")},
               "note": "the proportion gate reads numbers only: pass it before building the shell; no amount of surface detail can rescue wrong proportions"})


def _profile_points(sp):
    """longitudinal profile key points (x from nose to tail, z up, in meters). Mirrors cargen's parameterization."""
    L = sp["length_mm"] / 1000.0
    H = sp["height_mm"] / 1000.0
    ride = sp["ride_mm"] / 1000.0
    # **Polyline profile**: when control points are given, use them directly as the upper outline (expresses shapes outside cargen's family such as box vans / pickups)
    if sp.get("profile_pts"):
        raw = [list(q) for q in sp["profile_pts"]]
        closed = len(raw[0]) >= 3      # [x, z_top, z_bottom] = **closed profile** (top and bottom both come from the reference image ⇒ can reach IoU≈1)
        pts = sorted([(float(q[0]) / 1000.0, float(q[1]) / 1000.0,
                       (float(q[2]) / 1000.0 if closed else ride)) for q in raw], key=lambda t: t[0])
        if len(pts) >= 3:
            top = [(x, zt) for (x, zt, zb) in pts]
            bot = [(x, zb) for (x, zt, zb) in pts]
            if abs(top[0][0]) > 1e-9:
                top = [(0.0, top[0][1])] + top
                bot = [(0.0, bot[0][1])] + bot
            if abs(top[-1][0] - L) > 1e-9:
                top = top + [(L, top[-1][1])]
                bot = bot + [(L, bot[-1][1])]
            return top + list(reversed(bot))
    return _profile_cargen(sp)


def _profile_cargen(sp):
    # ⚠ after the split these three lines must be recomputed here (they were in the removed head; missing them makes the whole profile computation throw)
    L = sp["length_mm"] / 1000.0
    H = sp["height_mm"] / 1000.0
    ride = sp["ride_mm"] / 1000.0
    grille = sp["grille_h_mm"] / 1000.0
    hood_l = sp["hood_len_mm"] / 1000.0
    roof_l = sp["roof_len_mm"] / 1000.0
    rw_h = sp["rear_window_h_mm"] / 1000.0
    a = math.radians(sp["hood_angle_deg"])
    b = math.radians(sp["windshield_angle_deg"])
    c = math.radians(sp["roof_angle_deg"])
    d = math.radians(sp["rear_window_angle_deg"])
    e = math.radians(sp["trunk_angle_deg"])
    x0, x1 = 0.0, hood_l
    z_hood_end = grille + math.tan(a) * hood_l
    x2 = x1 + (H - z_hood_end) / max(0.15, math.tan(b))          # windshield: rise to the roof
    x3 = x2 + roof_l
    z_roof_end = H + math.tan(c) * roof_l
    x4 = x3 + (z_roof_end - rw_h) / max(0.15, math.tan(d))       # rear window: drop to rw_h
    x5 = min(L, x4 + max(0.0, (L - x4) * 0.85))
    pts = [(0.0, ride), (0.0, grille), (x1, z_hood_end), (x2, H), (x3, z_roof_end),
           (x4, rw_h), (x5, rw_h - math.tan(e) * max(0.0, x5 - x4)), (L, max(ride, rw_h - math.tan(e) * (L - x4))),
           (L, ride)]
    return [p for p in pts if -0.05 <= p[0] <= L + 0.05]


def _bottom_top_at(sp, x, profile):
    """for a given x, return the bottom/top boundary z of the profile (linear interpolation)."""
    xs = [p[0] for p in profile]
    lo = profile[0][1]
    hi = profile[0][1]
    # bottom boundary: the polygon's lower envelope; top boundary: upper envelope
    segs = [(profile[i], profile[i + 1]) for i in range(len(profile) - 1)]
    for (p, q) in segs:
        if min(p[0], q[0]) - 1e-9 <= x <= max(p[0], q[0]) + 1e-9:
            if abs(q[0] - p[0]) < 1e-9:
                z = p[1]
            else:
                t = (x - p[0]) / (q[0] - p[0])
                z = p[1] + t * (q[1] - p[1])
            lo = min(lo, z)
            hi = max(hi, z)
    return lo, hi


def _arch_bottom(sp, x, base_lo):
    """analytic wheel arch: when a station falls inside a wheel's x range, lift the bottom above the wheel circle + clearance ⇒ a wheel can never cut into the shell."""
    clear = sp["arch_clear_mm"] / 1000.0
    r = sp["wheel_r_mm"] / 1000.0
    sink = sp["wheel_sink_frac"]
    fx = sp["front_axle_from_front_mm"] / 1000.0
    rx = fx + sp["wheelbase_mm"] / 1000.0
    wc_z = r * (1.0 - sink)                       # wheel centre height (the sink fraction sits below the floor line)
    out = base_lo
    for wx in (fx, rx):
        dx = abs(x - wx)
        if dx < r + clear:
            zc = wc_z + math.sqrt(max(0.0, (r + clear) ** 2 - dx ** 2))
            out = max(out, zc)
    return out


def _section(sp, x, n=16):
    """section ring at station x (superellipse, with width taper). Returns [(x, y, z), ...] (counter-clockwise)."""
    L = sp["length_mm"] / 1000.0
    W = sp["width_mm"] / 1000.0
    prof = sp["_profile"]
    lo, hi = _bottom_top_at(sp, x, prof)
    lo = _arch_bottom(sp, x, lo)
    if hi <= lo:
        hi = lo + 1e-4
    t = x / max(1e-9, L)
    # width taper: nose/tail pull in, widest in the middle; the roof is narrower than the beltline (tumblehome)
    taper = 1.0 - 0.55 * max(0.0, (abs(t - 0.5) - 0.28) / 0.22) ** 1.4
    hw = 0.5 * W * max(0.35, taper)
    zc = 0.5 * (lo + hi)
    hh = 0.5 * (hi - lo)
    pts = []
    for i in range(int(n)):
        th = 2.0 * math.pi * i / float(n)
        ct, st = math.cos(th), math.sin(th)
        yy = hw * math.copysign(abs(ct) ** (2.0 / 4.0), ct)
        zz = zc + hh * math.copysign(abs(st) ** (2.0 / 4.0), st)
        pts.append((x, yy, zz))
    return pts




__all__ = [name for name in list(globals()) if not name.startswith("__")]
