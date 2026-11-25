# -*- coding: utf-8 -*-
"""DSH headless multi-view silhouette fitting (shapesolve) v1.

The problem: for parametric shapes (box bodies/brackets/vehicle-shell base bodies) "read the silhouette and back-derive the dimensions" currently needs a render + the naked eye,
and GUI/timers/bpy.render are all unreliable in headless mode. This module provides a **pure computation** path:
  reference image → foreground mask (alpha or Otsu) → **orthographic analytic projection + numpy triangle rasterization** (256²) of the current scene
  → IoU + profile-difference scoring → random search + coordinate refinement → best parameters + per-view IoU + sensitivity + reproducible script.

Why not bpy.render: ① headless EEVEE compilation/GPU dependency is heavy; ② solving needs hundreds of evaluations, rendering is far too slow;
③ an orthographic silhouette only needs projected triangles, and the geometric ground truth comes straight from the **evaluated mesh** (booleans/modifiers all count).

Rules (fixed; change here first when changing the algorithm):
  * camera: view direction f = normalize(look_at - from), up reference +Z (switches to +Y when f is near the Z axis), right = normalize(f × up),
    up' = right × f. Pixel mapping: u = res/2 + dot(p-look_at, right) × res/ortho_scale,
    v = res/2 - dot(p-look_at, up') × res/ortho_scale — i.e. ortho_scale is the world size of the frame **width**,
    look_at maps to the frame centre and pixel centres are at (i+0.5, j+0.5). **The reference image must be generated with the same camera parameters.**
  * mask: top→bottom (Blender image pixels are bottom→top, flipped on read); if the reference image has a valid alpha use alpha, otherwise Otsu.
  * scoring: score = Σ_view w·(w_iou·(1-IoU) + w_profile·profile_penalty) / Σw;
    profile_penalty = mean L1 of the row-width profile + column-height profile (normalized to [0,1]).
  * optimization: deterministic (np.random.default_rng(seed)); random sampling + per-coordinate stepping; iterations / budget_ms dual caps.
  * sensitivity: single-parameter perturbation of best by ±1% of range → drop in mean IoU; strong / weak / unidentifiable.

API is exposed on K.dsh_shapesolve_api: solve / selftest / help (one _KIT.register line at the end of the module).
Pure bpy + numpy, no PIL/scipy/cv2.

Headless run: tests/e2e/blender/native/shapesolve.py (executed by tests/e2e/blender/native_runner.py).
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np

SHAPESOLVE_VERSION = 1
MASK_MODES = ("auto", "alpha", "otsu", "luma")

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("shapesolve.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")

_j = _KIT.j


# ────────────────────────────── basic helpers ──────────────────────────────
def _kernel():
    return sys.modules.get("dsh_rt_kernel")


def _win(p):
    """WSL path → a form usable by Blender (a Windows process)."""
    s = str(p or "")
    if not s or not s.startswith("/"):
        return s
    K = _kernel()
    if K is not None and hasattr(K, "win_path"):
        try:
            return str(K.win_path(s))
        except Exception:
            pass
    return s


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def _vec3(v):
    if isinstance(v, dict):
        v = v.get("xyz")
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    out = []
    for x in v:
        f = _num(x)
        if f is None:
            return None
        out.append(f)
    return out


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _r(x, n=6):
    try:
        return round(float(x), int(n))
    except Exception:
        return None


def _receipt(body, t0=None):
    d = dict(body or {})
    d.setdefault("units", {"mm_per_unit": _r(_KIT.units(), 6)})
    if t0 is not None:
        d["ms"] = int((time.perf_counter() - t0) * 1000)
    return d


def _err(msg, **kw):
    d = {"ok": False, "error": str(msg)[:400], "hint": kw.pop("hint", None)}
    d.update(kw)
    return _j(_receipt(d))


# ────────────────────────────── input validation ──────────────────────────────
def _norm_params(raw):
    if not isinstance(raw, (list, tuple)) or not raw:
        return None, "params is required: [{name,min,max,init,integer}], at least 1 parameter"
    out, seen = [], set()
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            return None, "params[%d] is not an object" % i
        name = str(p.get("name") or "").strip()
        if not name:
            return None, "params[%d] is missing name" % i
        if name in seen:
            return None, "duplicate parameter name: %s" % name
        seen.add(name)
        lo, hi, ini = _num(p.get("min")), _num(p.get("max")), _num(p.get("init"))
        if lo is None or hi is None:
            return None, "min/max of parameter %s must be numbers" % name
        if not (hi > lo):
            return None, "max of parameter %s must be > min (min=%.6g max=%.6g)" % (name, lo, hi)
        if ini is None:
            ini = (lo + hi) / 2.0
        integer = bool(p.get("integer") or False)
        if integer:
            ini = float(int(round(ini)))
        ini = min(max(ini, lo), hi)
        out.append({"name": name, "min": float(lo), "max": float(hi), "init": float(ini),
                    "integer": integer,
                    "desc": str(p.get("desc") or "")})
    return out, None


def _norm_views(raw, resolution):
    if not isinstance(raw, (list, tuple)) or not raw:
        return None, "views is required: [{ref,from,look_at,ortho_scale}], at least 1 view"
    out = []
    for i, v in enumerate(raw):
        if not isinstance(v, dict):
            return None, "views[%d] is not an object" % i
        ref = v.get("ref")
        if not ref:
            return None, "views[%d] is missing ref (reference image path)" % i
        p = _win(ref)
        if not os.path.isfile(p):
            return None, "the reference image of views[%d] does not exist: %s" % (i, p)
        vf, vl = _vec3(v.get("from")), _vec3(v.get("look_at"))
        if vf is None or vl is None:
            return None, "from/look_at of views[%d] must be 3 numbers" % i
        d = np.linalg.norm(np.array(vl, dtype=np.float64) - np.array(vf, dtype=np.float64))
        if d < 1e-9:
            return None, "from and look_at of views[%d] coincide (view direction undefined)" % i
        osc = _num(v.get("ortho_scale"))
        if osc is None or osc <= 0:
            return None, "ortho_scale of views[%d] must be positive (the world size of the orthographic frame width)" % i
        mode = str(v.get("mask_mode") or "auto").lower()
        if mode not in MASK_MODES:
            return None, "views[%d] mask_mode supports only %s, got %r" % (i, list(MASK_MODES), v.get("mask_mode"))
        w = _num(v.get("weight"))
        if w is None:
            w = 1.0
        if w <= 0:
            return None, "weight of views[%d] must be > 0" % i
        out.append({"index": i, "ref": p, "ref_raw": str(ref),
                    "from": vf, "look_at": vl, "ortho_scale": float(osc),
                    "weight": float(w), "invert": bool(v.get("invert") or False),
                    "mask_mode": mode})
    return out, None


def _norm_objective(raw):
    raw = dict(raw or {}) if isinstance(raw, dict) else {}
    wi = _num(raw.get("iou"))
    wp = _num(raw.get("profile"))
    wi = 1.0 if wi is None else wi
    wp = 0.2 if wp is None else wp
    if wi < 0 or wp < 0:
        return None, "objective.iou / objective.profile must be >= 0"
    if wi + wp <= 1e-12:
        return None, "objective.iou and profile cannot both be 0 (without scoring there is no solution)"
    return {"iou": float(wi), "profile": float(wp)}, None
# ────────────────────────────── reference image → mask ──────────────────────────────
def _otsu_threshold(lum):
    """Otsu threshold (0..1) with a 256-bin histogram; a constant image returns None."""
    hist, _edges = np.histogram(lum, bins=256, range=(0.0, 1.0))
    total = float(hist.sum())
    if total <= 0:
        return None
    p = hist.astype(np.float64) / total
    omega = np.cumsum(p)
    idx = np.arange(256, dtype=np.float64)
    mu = np.cumsum(p * idx)
    mu_t = float(mu[-1])
    denom = omega * (1.0 - omega)
    denom[denom <= 1e-12] = 1e-12
    sigma = (mu_t * omega - mu) ** 2 / denom
    k = int(np.argmax(sigma))
    return (k + 0.5) / 256.0


def _load_ref_mask(path, res, mask_mode="auto", invert=False):
    """Read the reference image → top→bottom bool mask (res×res) + evidence info; on failure returns (None, reason).

    Foreground decision: ① valid alpha (some <0.5 and some >0.5) → alpha>0.5;
             ② otherwise Otsu: split the pixels into bright/dark classes; **the background hugs the border** — the class with fewer border pixels is judged foreground;
             ③ both classes fill the border / all one colour → failure (no guessing).
    """
    p = _win(path)
    if not p or not os.path.isfile(p):
        return None, "the reference image does not exist: %s" % p
    img = None
    try:
        img = bpy.data.images.load(p, check_existing=False)
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            return None, "invalid reference image size: %dx%d (%s)" % (w, h, p)
        px = np.array(img.pixels[:], dtype=np.float64)
        ch = max(1, len(px) // max(1, w * h))
        arr = px.reshape(h, w, ch)[::-1]     # Blender pixels are bottom→top; flip to top→bottom
    except Exception as e:
        return None, "reading the reference image failed: %s: %s" % (type(e).__name__, str(e)[:160])
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass
    if arr.shape[2] < 3:
        return None, "abnormal reference image channel count: %d" % arr.shape[2]
    mode = str(mask_mode or "auto").lower()
    info = {"path": p, "orig_size": [w, h], "mode": None, "threshold": None}
    use_alpha = False
    if arr.shape[2] >= 4 and mode in ("auto", "alpha"):
        alpha = arr[..., 3]
        if np.nanmin(alpha) < 0.5 and np.nanmax(alpha) > 0.5:
            mask = alpha > 0.5
            use_alpha = True
            info["mode"] = "alpha"
        elif mode == "alpha":
            return None, "the reference alpha is not clear-cut (min=%.3f max=%.3f) and cannot be used as an alpha mask" % (
                float(np.nanmin(alpha)), float(np.nanmax(alpha)))
    if not use_alpha:
        rgb = np.clip(arr[..., :3], 0.0, 1.0)
        lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
        thr = _otsu_threshold(lum)
        if thr is None:
            return None, "the reference image is constant; Otsu cannot separate foreground/background"
        bright = lum > thr
        info["threshold"] = _r(thr, 6)
        info["mode"] = "otsu"
        bw = max(2, int(round(min(w, h) * 0.05)))
        border = np.zeros((h, w), dtype=bool)
        border[:bw, :] = True
        border[-bw:, :] = True
        border[:, :bw] = True
        border[:, -bw:] = True
        b_bright = int(np.logical_and(bright, border).sum())
        b_dark = int(np.logical_and(~bright, border).sum())
        if b_bright > b_dark:
            mask = ~bright          # bright pixels hug the border ⇒ the background is bright ⇒ the foreground is dark
        elif b_dark > b_bright:
            mask = bright
        else:
            # both classes equally present at the border (object fills the frame / solid-colour border) → take the smaller-area class
            mask = bright if int(bright.sum()) <= int((~bright).sum()) else ~bright
    if invert:
        mask = ~mask
    fg = int(mask.sum())
    total = int(mask.size)
    if fg == 0 or fg == total:
        return None, ("the reference image cannot be separated into foreground/background (foreground %d / total %d, mode=%s) — use an alpha PNG or explicit invert/mask_mode"
                      % (fg, total, info["mode"]))
    if w != int(res) or h != int(res):
        yi = np.clip((np.arange(int(res)) * h / float(res)).astype(np.int64), 0, h - 1)
        xi = np.clip((np.arange(int(res)) * w / float(res)).astype(np.int64), 0, w - 1)
        mask = mask[np.ix_(yi, xi)]
        info["resized_from"] = [w, h]
    info["foreground_px"] = int(mask.sum())
    info["foreground_frac"] = _r(float(mask.mean()), 6)
    return {"mask": mask.astype(bool), "info": info}, None


# ────────────────────────────── orthographic analytic projection + rasterization ──────────────────────────────
def _view_basis(vfrom, vlook):
    """Orthographic camera basis: f=view direction (from→look_at), right/up' orthogonal to f (right-handed)."""
    f = np.array(vlook, dtype=np.float64) - np.array(vfrom, dtype=np.float64)
    n = float(np.linalg.norm(f))
    if n < 1e-12:
        raise ValueError("from and look_at coincide")
    f = f / n
    up_ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(f, up_ref))) > 0.99:
        up_ref = np.array([0.0, 1.0, 0.0])
    right = np.cross(f, up_ref)
    rn = float(np.linalg.norm(right))
    if rn < 1e-12:
        raise ValueError("the view direction is degenerate with up; the camera basis cannot be built")
    right = right / rn
    up = np.cross(right, f)
    return f, right, up


def _project_uv(world_verts, view, res):
    _f, right, up = _view_basis(view["from"], view["look_at"])
    rel = np.asarray(world_verts, dtype=np.float64) - np.array(view["look_at"], dtype=np.float64)
    s = float(res) / float(view["ortho_scale"])
    u = rel @ right * s + float(res) / 2.0
    v = float(res) / 2.0 - rel @ up * s
    return u, v


def _rasterize_tris(u, v, tris, res):
    """numpy triangle rasterization (pixel centres at i+0.5) → res×res bool mask."""
    res = int(res)
    mask = np.zeros((res, res), dtype=bool)
    if len(tris) == 0:
        return mask
    U = np.asarray(u, dtype=np.float64)[np.asarray(tris, dtype=np.int64)]
    V = np.asarray(v, dtype=np.float64)[np.asarray(tris, dtype=np.int64)]
    for k in range(len(U)):
        x0, x1, x2 = U[k]
        y0, y1, y2 = V[k]
        ix0 = int(math.floor(min(x0, x1, x2) - 0.5))
        ix1 = int(math.ceil(max(x0, x1, x2) - 0.5))
        iy0 = int(math.floor(min(y0, y1, y2) - 0.5))
        iy1 = int(math.ceil(max(y0, y1, y2) - 0.5))
        ix0 = max(0, ix0); iy0 = max(0, iy0)
        ix1 = min(res - 1, ix1); iy1 = min(res - 1, iy1)
        if ix1 < ix0 or iy1 < iy0:
            continue
        xs = np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5
        ys = np.arange(iy0, iy1 + 1, dtype=np.float64) + 0.5
        X, Y = np.meshgrid(xs, ys)
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12:
            continue
        w0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / den
        w1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        mask[iy0:iy1 + 1, ix0:ix1 + 1] |= inside
    return mask


def _collect_scene_tris(max_tris=300000):
    """**Evaluated** world triangles of every visible mesh in the current scene → (V,T) or ("error", reason)."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts, tris, base, skipped = [], [], 0, []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH":
            continue
        try:
            if ob.hide_render or ob.hide_viewport:
                continue
        except Exception:
            pass
        obe = None
        try:
            obe = ob.evaluated_get(dg)
            me = obe.to_mesh()
            if me is None:
                skipped.append(str(ob.name))
                continue
            me.calc_loop_triangles()
            n = len(me.vertices)
            nt = len(me.loop_triangles)
            if n == 0 or nt == 0:
                skipped.append(str(ob.name))
                continue
            v = np.empty(n * 3, dtype=np.float64)
            me.vertices.foreach_get("co", v)
            v = v.reshape(-1, 3)
            idx = np.empty(nt * 3, dtype=np.int64)
            me.loop_triangles.foreach_get("vertices", idx)
            idx = idx.reshape(-1, 3)
            mw = np.array(obe.matrix_world, dtype=np.float64)
            wv = v @ mw[:3, :3].T + mw[:3, 3]
            verts.append(wv)
            tris.append(idx + base)
            base += n
        except Exception as e:
            skipped.append("%s(%s)" % (ob.name, str(e)[:60]))
        finally:
            try:
                if obe is not None:
                    obe.to_mesh_clear()
            except Exception:
                pass
    if not verts:
        return None, "no usable mesh in the scene (0 faces after evaluation): %s" % (skipped[:6] or "empty scene")
    V = np.concatenate(verts, axis=0)
    T = np.concatenate(tris, axis=0)
    if len(T) > int(max_tris):
        return None, ("evaluated mesh %d faces > max_tris %d — silhouette solving only suits base bodies/mid-low poly;"
                      " decimate first or keep only the target objects" % (len(T), int(max_tris)))
    return (V, T), None


def _profile_penalty(ref_mask, cur_mask):
    """Profile difference: mean L1 of the row-width profile + column-height profile (normalized to [0,1])."""
    res = float(ref_mask.shape[0])
    rr = ref_mask.sum(axis=1) / res
    cr = ref_mask.sum(axis=0) / res
    rc = cur_mask.sum(axis=1) / res
    cc = cur_mask.sum(axis=0) / res
    return float((np.abs(rr - rc).mean() + np.abs(cr - cc).mean()) / 2.0)


def _evaluate(apply_fn, param_vals, views, refs, resolution, objective):
    """apply(params) → evaluated mesh → per-view projection/raster → (total score, per-view detail, masks)."""
    apply_fn(dict(param_vals))
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    got, err = _collect_scene_tris()
    if err:
        raise RuntimeError("the evaluated mesh is unusable: %s" % err)
    V, T = got
    rows, masks = [], []
    total, wsum = 0.0, 0.0
    for view, ref in zip(views, refs):
        u, v = _project_uv(V, view, resolution)
        mask = _rasterize_tris(u, v, T, resolution)
        masks.append(mask)
        iou = _KIT.iou(mask, ref["mask"])[0]
        iou = 0.0 if iou is None else float(iou)
        pen = _profile_penalty(ref["mask"], mask)
        w = float(view.get("weight") or 1.0)
        s = w * (float(objective["iou"]) * (1.0 - iou) + float(objective["profile"]) * pen)
        rows.append({"view": int(view.get("index", len(rows))), "iou": _r(iou, 6),
                     "profile_penalty": _r(pen, 6), "objective": _r(s / max(w, 1e-12), 6),
                     "weighted_score": _r(s, 6), "foreground_px": int(mask.sum()),
                     "ref_foreground_px": int(ref["mask"].sum())})
        total += s
        wsum += w
    return (total / max(wsum, 1e-9)), rows, masks
# ────────────────────────────── setup compilation / parameter clipping ──────────────────────────────
def _compile_setup(setup):
    ns = {"__name__": "shapesolve_setup", "bpy": bpy, "np": np, "math": math}
    K = _kernel()
    if K is not None:
        ns["K"] = K
    try:
        exec(compile(setup, "<shapesolve setup>", "exec"), ns)
    except Exception as e:
        import traceback
        raise RuntimeError("setup execution failed: %s: %s | %s"
                           % (type(e).__name__, str(e)[:200], traceback.format_exc()[-300:]))
    fn = ns.get("apply")
    if not callable(fn):
        raise RuntimeError("setup must define a callable apply(params_dict): parameter name→value, responsible for setting the scene geometry to those parameters"
                           " (existing global names: %s)" % sorted(k for k in ns if not k.startswith("__"))[:12])
    return fn, ns


def _clip(defn, v):
    lo, hi = float(defn["min"]), float(defn["max"])
    try:
        x = float(v)
    except Exception:
        x = float(defn["init"])
    if not math.isfinite(x):
        x = float(defn["init"])
    x = min(max(x, lo), hi)
    if defn.get("integer"):
        x = float(min(hi, max(lo, int(round(x)))))
    return x


def _param_values(defs, init):
    out = {}
    for p in defs:
        v = (init or {}).get(p["name"], p["init"])
        out[p["name"]] = _clip(p, v)
    return out


def _mean_iou(rows):
    if not rows:
        return 0.0
    return float(sum(float(r.get("iou") or 0.0) for r in rows) / len(rows))


# ────────────────────────────── optimizer (random + coordinate refinement, deterministic) ──────────────────────────────
def _optimize(apply_fn, defs, views, refs, resolution, objective, iterations, budget_ms, seed, init):
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    names = [p["name"] for p in defs]
    defmap = {p["name"]: p for p in defs}
    t0 = time.perf_counter()

    def _elapsed_ms():
        return (time.perf_counter() - t0) * 1000.0

    def _budget_hit():
        return int(budget_ms) > 0 and _elapsed_ms() > float(budget_ms)

    best = _param_values(defs, init)
    best_score, best_rows, _m = _evaluate(apply_fn, best, views, refs, resolution, objective)
    eval_count, runs, budget_hit, no_improve = 1, 0, False, 0
    steps = {n: 0.25 * (float(defmap[n]["max"]) - float(defmap[n]["min"])) for n in names}
    min_step = {n: max(1e-8, 1e-4 * (float(defmap[n]["max"]) - float(defmap[n]["min"]))) for n in names}

    def _random_cand(center=None, sigma=0.18):
        out = {}
        for n in names:
            d = defmap[n]
            span = float(d["max"]) - float(d["min"])
            base = center[n] if center else float(d["init"])
            out[n] = _clip(d, base + float(rng.normal(0.0, sigma)) * span)
        return out

    for it in range(int(iterations)):
        if _budget_hit():
            budget_hit = True
            break
        if rng.random() < 0.45:
            cand = _random_cand(best, 0.18)
        else:
            n = names[it % len(names)]
            sign = 1.0 if rng.random() < 0.5 else -1.0
            cand = dict(best)
            cand[n] = _clip(defmap[n], cand[n] + sign * steps[n])
        cand = {n: _clip(defmap[n], cand[n]) for n in names}
        if all(abs(cand[n] - best[n]) < 1e-12 for n in names):
            cand = _random_cand(best, 0.10)
        try:
            score, rows, _m2 = _evaluate(apply_fn, cand, views, refs, resolution, objective)
        except Exception as e:
            raise RuntimeError("evaluation #%d failed (apply/evaluated mesh error): %s: %s"
                               % (it + 1, type(e).__name__, str(e)[:200]))
        eval_count += 1
        runs = it + 1
        if score < best_score - 1e-12:
            best, best_score, best_rows = cand, score, rows
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= 2 * len(names):
                for n in names:
                    steps[n] = max(min_step[n], steps[n] * 0.6)
                no_improve = 0
    return {"best": best, "best_score": float(best_score), "best_rows": best_rows,
            "eval_count": eval_count, "iterations_run": runs, "budget_hit": bool(budget_hit),
            "optimize_ms": int(_elapsed_ms())}


def _sensitivity(apply_fn, defs, views, refs, resolution, objective, best, best_score, base_iou):
    """Single-parameter ±1% of range perturbation → mean IoU drop → strong / weak / unidentifiable."""
    out = {}
    for p in defs:
        name = p["name"]
        span = float(p["max"]) - float(p["min"])
        delta = 0.01 * span
        trials = []
        for sign, label in ((1.0, "+1%"), (-1.0, "-1%")):
            cand = dict(best)
            cand[name] = _clip(p, cand[name] + sign * delta)
            if abs(cand[name] - best[name]) < 1e-12:
                cand[name] = _clip(p, cand[name] - sign * delta)
            try:
                s, rows, _m = _evaluate(apply_fn, cand, views, refs, resolution, objective)
            except Exception as e:
                trials.append({"direction": label, "state": "error", "error": "%s: %s"
                               % (type(e).__name__, str(e)[:160])})
                continue
            iou = _mean_iou(rows)
            trials.append({"direction": label, "value": _r(cand[name], 8),
                           "score": _r(s, 6), "iou": _r(iou, 6),
                           "iou_drop": _r(base_iou - iou, 6),
                           "score_delta": _r(s - best_score, 6)})
        drops = [t["iou_drop"] for t in trials if isinstance(t.get("iou_drop"), (int, float))]
        deltas = [t["score_delta"] for t in trials if isinstance(t.get("score_delta"), (int, float))]
        iou_drop = max(drops) if drops else 0.0
        score_delta = max(deltas) if deltas else 0.0
        if iou_drop >= 0.01 or score_delta >= 0.01:
            cls = "strong"
        elif iou_drop >= 0.002 or score_delta >= 0.002:
            cls = "weak"
        else:
            cls = "unidentifiable"
        out[name] = {"class": cls, "perturb": _r(delta, 8),
                     "fraction_of_range": 0.01, "iou_drop": _r(iou_drop, 6),
                     "score_delta": _r(score_delta, 6), "trials": trials,
                     "why": ("±1%% of range already drops the mean IoU by %.4f ⇒ this parameter is identifiable from the silhouette" % iou_drop)
                            if cls != "unidentifiable"
                            else ("±1%% of range has almost no effect on the silhouette ⇒ this parameter is unidentifiable under the current views/reference"
                                  " (add a view that can see it, or narrow the parameter range)")}
    return out
# ────────────────────────────── op: solve ──────────────────────────────
def _ss_init_initvals(defs, init):
    """Validate the init overrides (only declared parameter names are allowed); returns (init_vals, err)."""
    init_vals = {}
    if init is None:
        return init_vals, None
    if not isinstance(init, dict):
        return None, _err("init must be a {parameter name: value} object", stage="validate")
    allowed = {p["name"] for p in defs}
    for k, v in init.items():
        if str(k) not in allowed:
            return None, _err("unknown parameter %r in init" % k, allowed=sorted(allowed), stage="validate")
        nv = _num(v)
        if nv is None:
            return None, _err("init.%s must be a number" % k, stage="validate")
        init_vals[str(k)] = nv
    return init_vals, None


def _ss_validate(setup, params, views, resolution, objective, iterations, budget_ms, seed, max_tris, init):
    """Full input validation; returns (cfg, err)."""
    if not isinstance(setup, str) or not setup.strip():
        return None, _err("setup is required: Python code that must define apply(params_dict) (responsible for setting the scene geometry from the parameters)",
                          stage="validate")
    defs, perr = _norm_params(params)
    if perr:
        return None, _err(perr, stage="validate")
    res = _num(resolution)
    if res is None or int(res) != res or int(res) < 64 or int(res) > 512:
        return None, _err("resolution must be an integer in 64..512 (default 256)", stage="validate")
    res = int(res)
    nviews, verr = _norm_views(views, res)
    if verr:
        return None, _err(verr, stage="validate")
    obj, oerr = _norm_objective(objective)
    if oerr:
        return None, _err(oerr, stage="validate")
    it = _num(iterations)
    if it is None or int(it) != it or int(it) < 1:
        return None, _err("iterations must be an integer >= 1", stage="validate")
    it = int(it)
    bud = _num(budget_ms)
    if bud is None or bud < 0:
        return None, _err("budget_ms must be a number >= 0 (0 = unlimited)", stage="validate")
    sd = _num(seed)
    if sd is None or int(sd) != sd:
        return None, _err("seed must be an integer", stage="validate")
    sd = int(sd)
    mt = _num(max_tris)
    if mt is None or int(mt) < 1:
        mt = 300000
    mt = int(mt)
    init_vals, ierr = _ss_init_initvals(defs, init)
    if ierr is not None:
        return None, ierr
    return {"defs": defs, "res": res, "nviews": nviews, "obj": obj, "it": it, "bud": bud,
            "sd": sd, "mt": mt, "init_vals": init_vals}, None


def _ss_refs(nviews, res):
    """Load the reference mask per view; returns (refs, err)."""
    refs = []
    for vi, vw in enumerate(nviews):
        r, rerr = _load_ref_mask(vw["ref"], res, mask_mode=vw["mask_mode"], invert=vw["invert"])
        if rerr:
            return None, _err("the reference image of view %d is unusable: %s" % (vi, rerr), stage="ref")
        refs.append(r)
    return refs, None


def _ss_scene_ok(mt):
    """The initial scene must yield a projection mesh; returns err or None."""
    try:
        _got, gerr = _collect_scene_tris(mt)
    except Exception as e:
        gerr = "%s: %s" % (type(e).__name__, str(e)[:200])
    if not gerr:
        return None
    return _err("the initial scene has no mesh usable for projection: %s — setup must first create the baseline body, then apply modifies it" % gerr,
                stage="scene", hint="e.g. create_cube once in setup + apply(p) only changes object.scale")


def _ss_out(cfg, setup, best, final_score, final_rows, refs, sens, opt):
    """Receipt body (including the repro arguments/script and honest_limits)."""
    repro_args = {
        "setup": setup,
        "params": [dict(p, init=_r(best[p["name"]], 10)) for p in cfg["defs"]],
        "views": [{"ref": v["ref_raw"], "from": v["from"], "look_at": v["look_at"],
                   "ortho_scale": v["ortho_scale"], "weight": v["weight"],
                   "invert": v["invert"], "mask_mode": v["mask_mode"]} for v in cfg["nviews"]],
        "objective": cfg["obj"], "iterations": cfg["it"], "budget_ms": int(cfg["bud"]), "seed": cfg["sd"],
        "resolution": cfg["res"], "max_tris": cfg["mt"],
    }
    repro_script = ('K.dsh_shapesolve_api("solve", '
                    + json.dumps(repro_args, ensure_ascii=False) + ')')
    return {
        "ok": True, "version": SHAPESOLVE_VERSION,
        "best": {k: _r(v, 10) for k, v in best.items()},
        "score": _r(final_score, 6),
        "best_iou_mean": _r(_mean_iou(final_rows), 6),
        "per_view": final_rows,
        "refs": [{"view": r["info"].get("mode"), "path": r["info"].get("path"),
                  "orig_size": r["info"].get("orig_size"),
                  "foreground_frac": r["info"].get("foreground_frac"),
                  "threshold": r["info"].get("threshold")} for r in refs],
        "params": [{k: p[k] for k in ("name", "min", "max", "init", "integer")} for p in cfg["defs"]],
        "objective": cfg["obj"], "resolution": cfg["res"],
        "iterations": cfg["it"], "iterations_run": int(opt["iterations_run"]),
        "eval_count": int(opt["eval_count"]), "budget_hit": bool(opt["budget_hit"]),
        "seed": cfg["sd"], "optimize_ms": int(opt["optimize_ms"]),
        "sensitivity": sens,
        "repro": {"seed": cfg["sd"], "best": {k: _r(v, 10) for k, v in best.items()},
                  "args": repro_args, "script": repro_script,
                  "apply_best": "apply(%s)" % json.dumps({k: _r(v, 10) for k, v in best.items()},
                                                          ensure_ascii=False)},
        "scene_final": "apply(best) was applied again — the scene rests on the best parameters (not the last perturbation)",
        "note": "ortho_scale is the world size of the frame **width**; the reference image must be generated with the same from/look_at/ortho_scale",
        "honest_limits": [
            "an orthographic silhouette only constrains the projected shape: a dimension along the view direction needs at least one facing view to be identifiable (sensitivity will mark it unidentifiable)",
            "the reference image is aligned by absolute pixels outside the bbox (not stretched to the bbox), so a wrong ortho_scale misjudges everything",
            "triangle rasterization is area coverage (no AA), so an anti-aliased reference edge gives ~1px-level noise in IoU",
            "silhouette only: material/internal structure/occlusion do not take part in scoring; a multi-object scene is scored on the union silhouette of all visible meshes",
        ],
    }


def _ss_write_out(out, out_dir):
    """Write the receipt to disk (a failure only writes out.error, not fatal)."""
    if not out_dir:
        return out
    try:
        d = _win(out_dir)
        if d:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "shapesolve_receipt.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({k: v for k, v in out.items() if k != "repro"}, fh,
                          ensure_ascii=False, indent=2)
            out["out"] = {"dir": d, "receipt": p}
    except Exception as e:
        out["out"] = {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}
    return out


def shapesolve_solve(setup=None, params=None, views=None, objective=None, iterations=200,
                     budget_ms=10000, seed=0, out_dir=None, resolution=256, init=None,
                     max_tris=300000):
    """Multi-view orthographic silhouette fitting: back-derive params so the current scene's silhouette under the given cameras matches the reference images best.

    Inputs (full): setup / params / views / objective / iterations / budget_ms / seed /
                   out_dir / resolution / init (optional: override the initial parameter values) / max_tris
    Receipt: ok / best / score / best_iou_mean / per_view / sensitivity / repro / …
    """
    t0 = time.perf_counter()
    cfg, verr = _ss_validate(setup, params, views, resolution, objective, iterations,
                             budget_ms, seed, max_tris, init)
    if verr is not None:
        return verr
    try:
        apply_fn, _ns = _compile_setup(setup)
    except Exception as e:
        return _err(str(e), stage="setup")
    try:
        refs, rerr = _ss_refs(cfg["nviews"], cfg["res"])
    except Exception as e:
        return _err("reference image processing raised: %s: %s" % (type(e).__name__, str(e)[:200]), stage="ref")
    if rerr is not None:
        return rerr
    serr = _ss_scene_ok(cfg["mt"])
    if serr is not None:
        return serr
    try:
        opt = _optimize(apply_fn, cfg["defs"], cfg["nviews"], refs, cfg["res"], cfg["obj"],
                        cfg["it"], cfg["bud"], cfg["sd"], cfg["init_vals"])
    except Exception as e:
        import traceback
        return _err("optimization failed: %s: %s" % (type(e).__name__, str(e)[:240]), stage="optimize",
                    traceback=traceback.format_exc()[-600:])
    best = opt["best"]
    try:
        final_score, final_rows, _fm = _evaluate(apply_fn, best, cfg["nviews"], refs, cfg["res"], cfg["obj"])
    except Exception as e:
        return _err("final apply(best) failed: %s: %s" % (type(e).__name__, str(e)[:200]), stage="final")
    base_iou = _mean_iou(final_rows)
    sens = _sensitivity(apply_fn, cfg["defs"], cfg["nviews"], refs, cfg["res"], cfg["obj"],
                        best, final_score, base_iou)
    # wrap-up: leave the scene on best (the sensitivity perturbations change the scene, so apply once more)
    try:
        _evaluate(apply_fn, best, cfg["nviews"], refs, cfg["res"], cfg["obj"])
    except Exception:
        pass
    out = _ss_out(cfg, setup, best, final_score, final_rows, refs, sens, opt)
    out = _ss_write_out(out, out_dir)
    return _j(_receipt(out, t0))
# ────────────────────────────── in-module selftest / help ──────────────────────────────
def _mask_to_png(path, mask_topdown, res):
    """bool mask (top→bottom) → RGBA PNG (alpha=foreground); Blender pixels are bottom→top, so flip before writing."""
    img = bpy.data.images.new("__shapesolve_ref", width=int(res), height=int(res), alpha=True)
    arr = np.zeros((int(res), int(res), 4), dtype=np.float32)
    arr[..., 0:3] = 1.0
    arr[..., 3] = np.asarray(mask_topdown, dtype=np.float32)[::-1]
    try:
        img.pixels.foreach_set(arr.reshape(-1))
    except Exception:
        img.pixels[:] = arr.reshape(-1).tolist()
    img.filepath_raw = _win(path)
    img.file_format = "PNG"
    img.save()
    try:
        bpy.data.images.remove(img)
    except Exception:
        pass


def _analytic_box_mask(view, dims, res):
    """Independent analytic implementation: the exact rectangular mask of an axis-aligned box under an orthographic view (bypassing the rasterizer, as reference ground truth)."""
    _f, right, up = _view_basis(view["from"], view["look_at"])
    dx, dy, dz = [float(x) for x in dims]
    corners = np.array([[sx * dx / 2.0, sy * dy / 2.0, sz * dz / 2.0]
                        for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], dtype=np.float64)
    rel = corners - np.array(view["look_at"], dtype=np.float64)
    s = float(res) / float(view["ortho_scale"])
    u = rel @ right * s + float(res) / 2.0
    v = float(res) / 2.0 - rel @ up * s
    xs = np.arange(int(res), dtype=np.float64) + 0.5
    ys = np.arange(int(res), dtype=np.float64) + 0.5
    return ((ys[:, None] >= float(v.min())) & (ys[:, None] <= float(v.max())) &
            (xs[None, :] >= float(u.min())) & (xs[None, :] <= float(u.max())))


def shapesolve_selftest():
    """Fast in-module self-test: synthesize refs (analytic rectangles) → invert the box dimensions → bad arguments ok:false."""
    import tempfile
    ev, tmp = {}, None
    t0 = time.perf_counter()
    prev_scale = float(bpy.context.scene.unit_settings.scale_length)
    hidden = []
    objs = []
    try:
        bpy.context.scene.unit_settings.scale_length = 0.001
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and not ob.hide_render:
                hidden.append(ob)
                ob.hide_render = True
        import bmesh
        me = bpy.data.meshes.new("__ss_box")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new("__ss_box", me)
        bpy.context.scene.collection.objects.link(ob)
        objs.append(ob)
        setup = (
            "import bpy\n"
            "_ob = bpy.data.objects.get('__ss_box')\n"
            "def apply(p):\n"
            "    _ob.scale = (p['sx'], p['sy'], p['sz'])\n"
            "    bpy.context.view_layer.update()\n"
        )
        true_dims = (40.0, 20.0, 30.0)
        res = 128
        tmp = tempfile.mkdtemp(prefix="dsh_shapesolve_selftest_")
        views = [
            {"ref": os.path.join(tmp, "ref_a.png"), "from": [0, -200, 0], "look_at": [0, 0, 0],
             "ortho_scale": 100.0},
            {"ref": os.path.join(tmp, "ref_c.png"), "from": [0, 0, 200], "look_at": [0, 0, 0],
             "ortho_scale": 100.0},
        ]
        dims_by_view = [true_dims, true_dims]
        for vw, dims in zip(views, dims_by_view):
            _mask_to_png(vw["ref"], _analytic_box_mask(vw, dims, res), res)
        r = json.loads(shapesolve_solve(
            setup=setup,
            params=[{"name": "sx", "min": 5, "max": 60, "init": 30},
                    {"name": "sy", "min": 5, "max": 60, "init": 30},
                    {"name": "sz", "min": 5, "max": 60, "init": 30}],
            views=views, iterations=90, budget_ms=8000, seed=3, resolution=res))
        best = r.get("best") or {}
        errs = {}
        for i, k in enumerate(("sx", "sy", "sz")):
            got = float(best.get(k) or 0.0)
            errs[k] = abs(got - true_dims[i]) / true_dims[i]
        ev["solve_ok"] = r.get("ok") is True
        ev["param_rel_err_ok"] = bool(errs) and max(errs.values()) <= 0.10
        ev["iou_ok"] = all(float(p.get("iou") or 0.0) >= 0.85 for p in (r.get("per_view") or []))
        ev["repro_has_seed"] = "seed" in str((r.get("repro") or {}).get("script") or "")
        r_bad = json.loads(shapesolve_solve(setup=setup, params=[], views=views))
        ev["bad_params_okfalse"] = r_bad.get("ok") is False
        r_bad2 = json.loads(shapesolve_solve(setup="x = 1", params=[{"name": "a", "min": 0, "max": 1}],
                                             views=views))
        ev["bad_setup_okfalse"] = r_bad2.get("ok") is False
        ok = all(v is True for v in ev.values())
        return _j({"ok": bool(ok), "version": SHAPESOLVE_VERSION, "evidence": ev,
                   "best": best, "per_view": r.get("per_view"),
                   "rel_err": {k: _r(v, 5) for k, v in errs.items()},
                   "ms": int((time.perf_counter() - t0) * 1000)})
    except Exception as e:
        import traceback
        return _j({"ok": False, "version": SHAPESOLVE_VERSION, "evidence": ev,
                   "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                   "traceback": traceback.format_exc()[-600:]})
    finally:
        bpy.context.scene.unit_settings.scale_length = prev_scale
        for ob in objs:
            try:
                me2 = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                if me2 is not None and me2.users == 0:
                    bpy.data.meshes.remove(me2)
            except Exception:
                pass
        for ob in hidden:
            try:
                ob.hide_render = False
            except Exception:
                pass
        if tmp:
            try:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass


def shapesolve_help():
    return _j({
        "module": "shapesolve.py", "version": SHAPESOLVE_VERSION,
        "what": "headless multi-view orthographic silhouette fitting: reference mask ↔ evaluated-mesh analytic projection + numpy rasterization → IoU/profile scoring → "
                "random + coordinate refinement to solve for parameters → sensitivity/reproducible script; no dependency on GUI/timers/bpy.render",
        "ops": {
            "solve": {"sig": "setup, params[{name,min,max,init,integer}], views[{ref,from,look_at,ortho_scale,"
                            "weight,invert,mask_mode}], objective{iou,profile}, iterations=200, "
                            "budget_ms=10000, seed=0, out_dir?, resolution=256, init?, max_tris=300000",
                      "out": "best / score / best_iou_mean / per_view(iou,profile_penalty) / "
                             "sensitivity(strong|weak|unidentifiable) / repro.script / budget_hit"},
            "selftest": {"sig": "no arguments", "out": "synthesized refs invert the box dimensions + bad arguments ok:false"},
            "help": {"sig": "no arguments"},
        },
        "protocol": [
            "create the **baseline geometry** in setup first (create_cube once), and let apply(p) only change dimensions/position — it is called on every evaluation",
            "the reference image must be generated with the same from/look_at/ortho_scale; ortho_scale is the world size of the frame **width**, and look_at maps to the frame centre",
            "mask: use alpha when the reference has a valid alpha, otherwise Otsu (the background hugs the border → the class with fewer border pixels is foreground); if it cannot separate, ok:false",
            "with >=3 parameters give >=2–3 views of different orientations; sensitivity unidentifiable = that parameter's projection carries no information under the current views",
            "reproducible: the receipt's repro.script contains the seed/view pixel convention verbatim; repro.args' params.init already holds best",
        ],
        "mask_modes": ["auto (default: alpha preferred, otherwise Otsu)", "alpha", "otsu", "luma (same as otsu, luminance convention)"],
        "deps": {"required": "K.dsh_kit (_KIT.iou also comes from the kernel)", "optional": "none (pure bpy + numpy)"},
        "honest_limits": [
            "an orthographic silhouette only constrains the projected shape; a dimension along the view direction needs a facing view",
            "absolute pixel alignment: a wrong ortho_scale/reference resolution misjudges everything (no bbox-adaptive stretching)",
            "rasterization has no anti-aliasing; with an AA reference, IoU carries ~1px noise",
            "only the silhouette union is compared: material/internal structure/occlusion do not take part",
        ],
    })


# Registration: one line at the end of the module (K.dsh_shapesolve_api; ops = solve / selftest / help)
_KIT.register("shapesolve", SHAPESOLVE_VERSION, {
    "solve": shapesolve_solve, "selftest": shapesolve_selftest, "help": shapesolve_help})
