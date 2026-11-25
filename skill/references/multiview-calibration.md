# Three-view calibration (multiview calibration)

> Companion to `SKILL.md` **§0.6.1 three-view calibration**; the current plugin prefers `img_calib` (multi-view calibration) and `shapesolve_solve` (silhouette back-solving), and this script serves as an independent recomputation / blind-test reference. It answers three very concrete questions:
> 1. **Can this reference image be converted to millimetres using "a single px_per_mm"?**
> 2. Can the three views **be combined** (merged into one scale)?
> 3. For dimensions across depth, how large is the error really?
>
> Pure standard library (no numpy / Blender needed); the script carries its own `--selftest`.

## 0. ★ First, correct a common misunderstanding: orthographic ⇏ the three views share the same px_per_mm

**Orthographic only guarantees that "within each individual view" pixels and millimetres are linear** (that view's `s` is constant, in-view residual ≈ 0).
It does **not** imply that the three views share the same `px_per_mm` — the three images can each have a different **output scale / resolution / crop**,
and still all be strictly orthographic.

**Measured in practice (this machine, Blender 5.2.2, measured directly with `world_to_camera_view`, no rendering)**:

| view | ortho_scale | pixel length of a 1000mm ruler | px_per_mm | parallax probe (x shift caused by changing depth by 2m) |
|---|---|---|---|---|
| front | 4.0 m | 480 px | 0.48 | **0.000 px** |
| side | 8.0 m | 240 px | 0.24 | **0.000 px** |
| top | 2.0 m | 960 px | 0.96 | **0.000 px** |

All three parallax probes are **0 px** ⇒ the three views **are all strictly orthographic**; yet `px_per_mm` differs by **300%** between them.
⇒ **"The three views must share the same px_per_mm" is wrong**. Sharing a scale is an **extra assumption** ("the three views come from the same engineering drawing /
the same render, same resolution, same crop") and must be **declared and verified separately**; it cannot be derived from orthogonality.

**Corollary (this directly determines how to judge)**: cross-view mutual checks must **convert to millimetres before comparing**; they cannot compare `s` directly.
Comparing `s` directly misreads "the three images are scaled differently" as "perspective", and then you go and change point picks that were fine to begin with.

## 1. When to use it

| Situation | Use it? |
|---|---|
| You have a front view / side view / top view, **and can confirm they come from the same drawing or the same render** | ✅ combined calibration, a joint `px_per_mm` may be merged |
| The three views come from different sources (screen captures / separate photos / resized images) | ⚠ **calibrate each view on its own**, cross-check with a shared dimension; **do not** merge |
| Only one image, or the three are not the same orthographic direction | ⚠ fall back to per-view calibration (own ruler + same-depth same-direction conversion) |
| Obviously a perspective photo / wide angle | First rectify with `img_rectify` (see §6; note that it **only rectifies the plane where the points were picked**), then handle as above |

## 2. How to pick points (≥3 per view)

1. Pick features with a **known real length**: wheelbase / wheel diameter / overall length / barrel length / window width … (record the source in `spec.py` or the project material).
2. Measure that feature's pixel length **along this view's image horizontal axis**. Key points:
   - The feature direction must be **parallel to the image horizontal axis** (for slanted ones, project first, otherwise you are measuring the hypotenuse);
   - Spread the 2–3 features within the same view as far apart as possible (a larger span makes the scale more stable);
   - ★ **At least 3 points per view** — a line solved from two points necessarily passes through those two points, so **the residual is always 0** and perspective cannot be detected.
3. **Then give at least one "shared dimension"**: a real dimension that can be measured in **two or more views** (overall height / overall length both work).
   All cross-view mutual checks rely on it. **Without a shared dimension, the three views cannot prove each other** — the conclusion can only be `unresolved`.
4. Fill in the JSON (example below) and run the script.

```json
{
  "views": {
    "front": {"image_width": 1920, "features": [
      {"name": "overall length", "u_mm": 9830, "px": 1474.5},
      {"name": "wheelbase", "u_mm": 4600, "px": 690.0},
      {"name": "wheel diameter", "u_mm":  660, "px":  99.0}
    ]},
    "side":  {"image_width": 1920, "features": [ /* as above, using known dimensions on the side view */ ]},
    "top":   {"image_width": 1920, "features": [ /* as above */ ]}
  },
  "shared": [
    {"name": "overall height", "measure": {"front": {"px": 812.0}, "side": {"px": 406.0}}}
  ],
  "same_scale_asserted": false
}
```

`u_mm` = the feature's known physical length **along this view's image horizontal axis** (mm); `px` = the same feature's pixel length in the image.
Write `same_scale_asserted: true` only when you **really know** the three views are on the same scale (e.g. a single scanned engineering drawing).

## 3. The script

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Three-view calibration (front / side / top): per-view least-squares solve for px_per_mm + cross-view consistency mutual checks.

Usage
    python3 multiview_calib.py calib.json      # read the calibration input, emit a report
    python3 multiview_calib.py --selftest      # synthetic-data self-check (see the four cases at the end)

Conventions (★ the core misunderstanding fixed in this version)
  u_mm = the known physical length of this feature **along this view's image horizontal axis** (difference of endpoints, mm)
  px   = the pixel length of the same feature in the reference image
  model: px = cx + s * u  (s = px_per_mm, cx = the pixel column that u=0 falls on)
  ★ Two points are necessarily passed through by the line (residual always 0); to judge "is this image orthographic", give at least 3 points per view.
  ★ Orthographic only guarantees that **within each view** px and mm are linear (in-view residual ≈ 0). It does **not** guarantee that the three views share
    the same px_per_mm -- the three images can each have their own output scale / resolution / crop and still be strictly orthographic.
    Therefore cross-view mutual checks must convert to **millimetres** before comparing (see shared_dimensions), not compare s directly.
"""
import json
import sys

RESID_TOL_PCT = 2.0   # in-view residual limit: >2% -> this view is internally non-linear (perspective, or feature points mis-measured)
SHARED_TOL_PCT = 3.0  # limit on the mutual difference between the mm values two views each convert the same physical dimension to: >3% -> the two views are incompatible
SAME_SCALE_TOL_PCT = 1.0  # the three views' px_per_mm may be treated as "the same output scale" only when they differ by <=1%


def fit_view(features, image_width=None):
    """Least-squares solve px = cx + s*u. features=[{name,u_mm,px}, ...] (>=2 points)."""
    pts = [(float(f["u_mm"]), float(f["px"])) for f in features]
    n = len(pts)
    if n < 2:
        raise ValueError("at least 2 feature points are needed to determine a scale (given %d)" % n)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((u - mx) ** 2 for u, _ in pts)
    if sxx <= 0:
        raise ValueError("all feature points coincide in u (sxx=0), cannot determine a scale")
    sxy = sum((u - mx) * (p - my) for u, p in pts)
    s = sxy / sxx
    if s <= 0:
        raise ValueError("the solved scale s<=0 (pixels and millimetres with opposite signs? check whether u_mm/px match)")
    cx = my - s * mx
    resid = [abs(p - (cx + s * u)) for u, p in pts]
    span = max(u for u, _ in pts) - min(u for u, _ in pts)
    resid_px = max(resid)
    resid_pct = (resid_px / (s * span) * 100.0) if span > 0 else 0.0
    return {"n": n, "s": s, "cx": cx, "sxx": sxx, "span_mm": span,
            "resid_px": resid_px, "resid_pct": resid_pct,
            "pp_offset_px": (None if image_width is None else cx - float(image_width) / 2.0),
            "per_point_px": [round(r, 3) for r in resid]}


def same_scale(fits):
    """Whether the three views' px_per_mm may be treated as the same output scale (this is an **extra assumption**, not a corollary of orthogonality)."""
    ss = [f["s"] for f in fits.values()]
    if not ss or min(ss) <= 0:
        return None, None
    spread = (max(ss) - min(ss)) / min(ss) * 100.0
    return (spread <= SAME_SCALE_TOL_PCT), spread


def shared_check(fits, shared):
    """Cross-view mutual check: convert the same physical dimension to millimetres with each view's **own** s, then see whether they agree.

    shared = [{"name": "overall height", "measure": {"front": {"px": 812.0}, "side": {"px": 150.0}}}, ...]
    """
    rows, bad = [], []
    for item in (shared or []):
        name = item.get("name") or "?"
        vals = {}
        for vname, m in (item.get("measure") or {}).items():
            if vname not in fits:
                continue
            vals[vname] = float(m["px"]) / fits[vname]["s"]
        if len(vals) < 2:
            rows.append({"name": name, "mm": vals, "disagree_pct": None,
                         "note": "measured in only 1 view -> cannot cross-check"})
            continue
        lo, hi = min(vals.values()), max(vals.values())
        d = (hi - lo) / lo * 100.0 if lo > 0 else float("inf")
        rows.append({"name": name, "mm": {k: round(v, 2) for k, v in vals.items()},
                     "disagree_pct": round(d, 3)})
        if d > SHARED_TOL_PCT:
            bad.append("shared dimension '%s' differs by %.2f%% between the two views > %.1f%% (%s)"
                       % (name, d, SHARED_TOL_PCT,
                          "; ".join("%s=%.1fmm" % (k, v) for k, v in vals.items())))
    return rows, bad


def combine(fits):
    """Merge only when the three views are confirmed to be on the same scale: inverse-variance weighting by sxx."""
    wsum = sum(f["sxx"] for f in fits.values())
    if wsum <= 0:
        raise ValueError("merge weight is 0")
    return sum(f["s"] * f["sxx"] for f in fits.values()) / wsum


def report(data):
    views = data.get("views") or {}
    if not views:
        raise ValueError("the input has no views")
    fits, bad = {}, []
    for name, v in views.items():
        f = fit_view(v.get("features") or [], v.get("image_width"))
        fits[name] = f
        if f["resid_pct"] > RESID_TOL_PCT:
            bad.append("%s in-view residual %.2f%% > %.1f%% (this view is internally non-linear: not an orthographic projection, "
                       "or the feature points were mis-measured)" % (name, f["resid_pct"], RESID_TOL_PCT))

    rows, shared_bad = shared_check(fits, data.get("shared"))
    bad += shared_bad

    is_same, spread = same_scale(fits)
    asserted = data.get("same_scale_asserted")

    L = ["=== Per-view least squares (px = cx + s*u) ===",
         "view     n  px_per_mm   mm_per_px  principal point offset px   residual px   residual %   span mm"]
    for name in sorted(fits):
        f = fits[name]
        pp = "-" if f["pp_offset_px"] is None else ("%+.1f" % f["pp_offset_px"])
        L.append("%-8s %d  %9.6f  %9.4f  %10s  %7.3f  %6.3f%%  %8.1f"
                 % (name, f["n"], f["s"], 1.0 / f["s"], pp, f["resid_px"], f["resid_pct"], f["span_mm"]))
    L.append("")
    L.append("=== Three-view px_per_mm consistency (note: this is an **extra assumption**, not a corollary of orthogonality) ===")
    L.append("  px_per_mm per view: " + ", ".join("%s=%.6f" % (k, v["s"]) for k, v in sorted(fits.items())))
    L.append("  mutual difference = %s" % ("-" if spread is None else "%.2f%%" % spread))
    if is_same:
        L.append("  -> three-view px_per_mm difference <= %.1f%%: **may** be treated as the same output scale (e.g. the same engineering drawing / "
                 "the same orthographic render)" % SAME_SCALE_TOL_PCT)
    else:
        L.append("  -> three-view px_per_mm difference > %.1f%%: **do not share the same scale**. This is **not necessarily** perspective --"
                 % SAME_SCALE_TOL_PCT)
        L.append("     the three images can each have their own output scale / resolution / crop and still all be strictly orthographic (measured in practice: all three parallax probes are 0px, "
                 "yet px_per_mm is 0.48 / 0.24 / 0.96, a 300% difference).")
        L.append("     Handling: **calibrate and convert each view on its own**, then cross-check with the shared dimensions below -- do not force one joint scale onto all three views.")
    L.append("")
    if rows:
        L.append("=== Cross-view mutual check (convert to millimetres before comparing; independent of output scale) ===")
        for r in rows:
            mm = r["mm"]
            L.append("  %-10s %s   difference %s"
                     % (r["name"], ", ".join("%s=%.1fmm" % (k, v) for k, v in sorted(mm.items())),
                        "-" if r["disagree_pct"] is None else "%.2f%%" % r["disagree_pct"]))
    else:
        L.append("=== Cross-view mutual check: the input gives no `shared` ===")
        L.append("  Without a shared dimension only in-view self-checks are possible -- the three views **cannot** prove each other.")
        L.append("  Give at least one real dimension measurable in two views (e.g. overall height / overall length), otherwise the conclusion can only be unresolved.")
    L.append("")

    if bad:
        L.append("=== Conclusion: fail (do not force a joint solve) ===")
        for b in bad:
            L.append("  x " + b)
        L.append("  Fall back to per-view calibration: determine s for each view using **its own** ruler only, and convert only dimensions at the same depth and in the same direction as that view's ruler.")
        L.append("  Dimensions across depth: the error is **not** a fixed ±5%, it grows linearly with depth -- estimate it first with "
                 "err ≈ Δz/(D+Δz) from §0.6.1, and record unresolved if you cannot estimate it.")
    elif not asserted and not is_same:
        L.append("=== Conclusion: each view is orthographic and the shared dimensions agree, but there is no basis for same-scale ===")
        L.append("  per-view calibration is usable; **do not** merge into one joint px_per_mm.")
        L.append("  If you confirm the three views come from the same drawing / the same render, add \"same_scale_asserted\": true to the input.")
    else:
        s = combine(fits)
        L.append("=== Conclusion: orthogonality passes (the three views can be combined) ===")
        L.append("  joint px_per_mm = %.6f (1 px = %.4f mm), inverse-variance weighted by each view's sxx" % (s, 1.0 / s))
        L.append("  Basis: three-view px_per_mm difference <=%.1f%% (same scale) **and** shared-dimension difference <=%.1f%%."
                 % (SAME_SCALE_TOL_PCT, SHARED_TOL_PCT))
        L.append("  Purpose: uniformly convert the pixel measurements of each view into millimetres, write them into spec.py, and note the source (image name + pixels + ruler).")
    return "\n".join(L)


# ------------------------------------------------------------------ selftest
def _synth(base_s=0.15, cx=960.0, width=1920, us=(0.0, 4600.0, 9830.0),
           view_k=None, in_view_drift=0.0, drift_view="front",
           shared_mm=2000.0, shared_px_override=None):
    """Synthesise a calibration input.

    view_k      = {view name: that view's **overall output scale factor**}
    shared      = one real dimension measurable in two views (2000mm by default)
    shared_px_override = {view name: override the pixel value of this dimension in that view} (used to fabricate "mis-measured / inconsistent")
    """
    view_k = view_k or {}
    out = {"views": {}, "shared": []}
    for name in ("front", "side", "top"):
        k = float(view_k.get(name, 1.0))
        feats = []
        for i, u in enumerate(us):
            drift = 1.0 + (in_view_drift * (u / float(us[-1])) if name == drift_view else 0.0)
            feats.append({"name": "f%d" % i, "u_mm": u, "px": round(cx + base_s * k * drift * u)})
        out["views"][name] = {"image_width": width, "features": feats}
    # the shared dimension is measured once each in the front / side views (each view drawn at its own output scale)
    meas = {}
    for name in ("front", "side"):
        k = float(view_k.get(name, 1.0))
        px = base_s * k * shared_mm
        if shared_px_override and name in shared_px_override:
            px = shared_px_override[name]
        meas[name] = {"px": round(px, 3)}
    out["shared"] = [{"name": "shared dimension", "measure": meas}]
    return out


def _selftest():
    cases = [
        ("A three views at the same scale (should pass and combine)",
         _synth(view_k={"side": 1.004, "top": 0.997}), "combined"),

        ("B in-view perspective (front scale drifts 15% with u -> in-view residual red)",
         _synth(in_view_drift=0.15), "in-view residual"),

        ("C three views at different output scales but all orthographic (side 0.5x and its ruler shrinks accordingly)"
         " -> should judge 'does not share a scale, but per-view calibration is usable', **not** misjudging perspective any more",
         _synth(view_k={"side": 0.5, "top": 0.75}), "per-view"),

        ("D different output scales + shared dimension differing by 6% (genuinely inconsistent) -> cross-view mutual check red",
         _synth(view_k={"side": 0.5, "top": 0.75},
                shared_px_override={"side": 0.5 * 0.15 * 2000.0 * 1.06}), "difference"),
    ]
    got = {}
    for title, data, key in cases:
        r = report(data)
        print("######## " + title + " ########")
        print(r)
        print()
        got[title[0]] = (r, key)
    ok_a = "joint px_per_mm" in got["A"][0]
    ok_b = ("in-view residual" in got["B"][0]) and ("fail" in got["B"][0])
    # C: one of three acceptable phrasings, and it must **not** judge "fail"
    ok_c = (("per-view calibration" in got["C"][0]) or ("per-view conversion" in got["C"][0])) \
        and ("fail" not in got["C"][0])
    ok_d = ("difference" in got["D"][0]) and ("fail" in got["D"][0])
    good = ok_a and ok_b and ok_c and ok_d
    print("SELFTEST %s  (A combined / B in-view residual red / C different scales per-view usable / D cross-view mutual check red)  "
          "A=%s B=%s C=%s D=%s" % ("PASS" if good else "FAIL", ok_a, ok_b, ok_c, ok_d))
    return 0 if good else 1


def main(argv):
    if "--selftest" in argv:
        return _selftest()
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
    print(report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

How to run:

```bash
python3 multiview_calib.py calib.json     # emit a report
python3 multiview_calib.py --selftest     # synthetic-data self-check: A combined / B in-view residual red / C different scales per-view usable / D cross-view mutual check red
```

## 4. Criteria (hard)

| Criterion | Threshold | Meaning | Handling |
|---|---|---|---|
| in-view residual | **> 2%** | the scale is inconsistent **within** that view ⇒ genuine perspective / non-linearity, or feature points mis-measured | that view cannot be measured by scale |
| shared-dimension mutual difference (after conversion to mm) | **> 3%** | the millimetre values the two views give for **the same real dimension** do not match ⇒ the two views are incompatible (one of them non-orthographic / wrong ruler picked / dimension mis-measured) | do not combine; convert per view and mark `unresolved` |
| three-view px_per_mm mutual difference | **> 1%** | the three views **do not share the same output scale** | **not equal to perspective** — just calibrate each view on its own; merge only when you have a separate "same scale" basis |
| principal point offset `cx − image width/2` | reference | diagnostic only: an absurd offset ⇒ a problem with point picking or cropping (not equal to non-orthographic) | re-check the point picks |

⚠ **`s` mutual difference over the limit ≠ judging perspective**. This is the most important convention fix in this file:
the old wording read "three-view px_per_mm inconsistent" directly as "non-orthographic / perspective", so people went and doubted the point picks and re-calibrated,
**whereas the real cause is that the three images are scaled differently**. The correct division of labour is:
**the in-view residual judges "is this image orthographic", the shared dimension judges "can the two views corroborate each other", and the `s` mutual difference only judges "can they be merged into one scale".**

All green **and** `same_scale_asserted` (or `s` mutual difference ≤1%) ⇒ take the **joint `px_per_mm`** inverse-variance weighted by `sxx`,
convert all three views uniformly into millimetres and write them into `spec.py`, with the source (image name + pixel coordinates + ruler).

## 5. ★ The error across depth is **not** a fixed ±5%

The old wording relaxed the tolerance of "dimensions across depth" to **±5%** across the board. That is not guaranteed — under perspective the scale varies with depth as `1/z`:

```text
err ≈ Δz / (D + Δz)            # D = distance from the camera to the near ruler, Δz = depth difference between the two points
```

**Measured in practice (this machine, Blender 5.2.2, measured directly with `world_to_camera_view`, D = 8 m)**:

| depth difference Δz | px_per_mm measured in practice | relative error versus the near scale | analytic Δz/(D+Δz) |
|---|---|---|---|
| 0 m | 0.295139 | 0.00% | 0.00% |
| 0.25 m | 0.286195 | **−3.03%** | −3.03% |
| 0.5 m | 0.277778 | **−5.88%** | −5.88% |
| 1.0 m | 0.262346 | **−11.11%** | −11.11% |
| 2.0 m | 0.236111 | **−20.00%** | −20.00% |
| 3.0 m | 0.214646 | **−27.27%** | −27.27% |

⇒ at an 8 m camera position, **a depth difference of only 0.5 m already exceeds ±5%**; at 3 m the error is **−27.3%**.
The analytic expression matches the measured values row by row to two decimal places, so it can be used directly as a formula.

**Discipline**:

1. For measurements across depth, **first compute** `Δz/(D+Δz)` and treat it as the error upper bound for this measurement (not ±5%);
2. If `D` or `Δz` cannot be estimated ⇒ record that dimension as **`unresolved`**; do not casually write "±5% should be enough";
3. If you want a genuine scale measurement ⇒ put the measured feature at the **same depth** as the ruler, or perform a **real camera calibration** of the reference image (intrinsics + extrinsics);
4. Homography rectification (`img_rectify`) solves **only one plane**, see §6.

## 6. ★ The homography (`img_rectify`) only rectifies "the plane where the points were picked"

A four-point homography is exactly valid for points that **lie exactly on the physical plane where the points were picked**; for points off that plane **the error grows rapidly with depth**.

**Measured in practice (this machine, Blender 5.2.2; pick 4 corner points on the z=0 plane to fit a homography, then use it to map other points of the same object)**:

| distance of the point from the z=0 plane | maximum error | converted to that camera position (1 m ≈ 190 px) |
|---|---|---|
| 0 m | **0.000 px** | 0 mm |
| 0.05 m | 9.906 px | **52 mm** |
| 0.20 m | 40.194 px | **211 mm** |
| 0.50 m | 103.464 px | **543 mm** |

**Discipline**:

1. **Planar reference** (a photographed drawing, a calibration board, a flat sticker, a calibration frame laid flat on the ground) ⇒ the homography is completely correct, use it with confidence;
2. **Solid objects** (car / person / building) ⇒ the homography only guarantees **that one plane** (e.g. the plane the car side's overall outline lies on) is right;
   the further a feature of the body is from that plane (flared wheel arch, fender curvature, forward-leaning A-pillar), the larger the error;
3. So the four points must be a **real rectangle on one plane**, and **measurements must only take features close to that plane**;
4. To make a whole solid object accurate ⇒ go for real camera calibration (intrinsics + extrinsics) or multi-view geometry, **not** a homography;
5. Strong oblique viewing magnifies point-picking error (the 543 mm in §6.3 comes from exactly that) — use `img_scan` to see the silhouette clearly before picking points.

## 7. Self-verification: how to know the calibration is right

- **With ground truth**: for an image you rendered yourself with an orthographic camera, `px_per_mm = rendered width px / ortho_scale_mm`
  (`bpy.context.scene.camera.data.ortho_scale`) — compare it against the value the script gives; the target error is **≤1%**.
  ★ Note this holds only under **the same orthographic setting**; change `ortho_scale` or change the resolution and `px_per_mm` changes (§0 measured table).
- **Without ground truth**: hold back a known dimension that does **not** participate in the fit and use it as a blind test; a blind-test deviation >2% means this image cannot be measured by scale.
- **Cross-view self-verification**: give a shared dimension (§2 item 3) and check whether the millimetre values converted from the two views differ by ≤3%.

## 8. How to verify (in one sentence)

The `--selftest` four synthetic cases respectively give **A combined / B in-view residual red / C different scales, per-view usable / D cross-view mutual check red**
(last line `SELFTEST PASS`); on real images: if the orthographic three views are on the same scale, the joint scale deviates from the render ground truth by ≤1%,
and if the three views are scaled differently the script reports "does not share a scale, per-view calibration is usable" and does **not** misjudge perspective.
