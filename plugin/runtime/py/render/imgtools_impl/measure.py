# -*- coding: utf-8 -*-
"""Split from imgtools.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .analysis import _norm_roi, _rnd
from .contour import _circle_from_hole, _holes_of
from .cache import _draw_line, _img_entry

def _subpixel_edge(prof, i_edge):
    """Gradient-peak three-point parabola → subpixel edge position (returns i+0.5±0.5 when the edge lies between pixel i and i+1)."""
    prof = np.asarray(prof, dtype=np.float64)
    n = int(len(prof))
    if n < 4:
        return None
    try:
        i_edge = int(i_edge)
    except Exception:
        return None
    d = np.diff(prof)
    m = np.abs(d)
    if m.size < 3:
        return None
    lo = max(1, i_edge - 3)
    hi = min(len(m) - 2, i_edge + 2)
    if hi < lo:
        return None
    k = lo + int(np.argmax(m[lo:hi + 1]))
    a = float(m[k - 1])
    b = float(m[k])
    c = float(m[k + 1]) if k + 1 < len(m) else b
    den = a - 2.0 * b + c
    off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    off = max(-0.5, min(0.5, off))
    return float(k) + 0.5 + off


def _runs_1d(row, x0):
    """1D boolean → [(start_abs, end_abs)] (endpoints inclusive)."""
    row = np.asarray(row, dtype=bool)
    if row.size == 0:
        return []
    pad = np.zeros(row.size + 2, dtype=np.int8)
    pad[1:-1] = row.astype(np.int8)
    d = np.diff(pad)
    starts = np.flatnonzero(d == 1) + int(x0)
    ends = np.flatnonzero(d == -1) - 1 + int(x0)
    return [(int(s), int(e)) for s, e in zip(starts.tolist(), ends.tolist())]


def _probe_scan_y(ent, out, box, y_px, H, W, ppm):
    """Horizontal scan line (y_px): subpixel left/right edges / multiple segments. Updates out in place on success, returns an error receipt on failure."""
    x0, y0, bw, bh = box
    pos = int(round(float(y_px))) if y_px is not None else int(y0 + bh // 2)
    if not (0 <= pos < H):
        return _j({"ok": False, "error": "y_px out of bounds", "y_px": y_px, "shape_px": [W, H]})
    line = ent["mask"][pos, :]
    prof = ent["gray"][pos, :]
    runs = _runs_1d(line[x0:x0 + bw], x0)
    segs = []
    for (s, e) in runs:
        lsub = _subpixel_edge(prof, int(s))
        rsub = _subpixel_edge(prof, int(e))
        segs.append({"x0_px": (lsub if lsub is not None else float(s) - 0.5),
                     "x1_px": (rsub if rsub is not None else float(e) + 0.5),
                     "width_px": ((rsub if rsub is not None else float(e) + 0.5)
                                  - (lsub if lsub is not None else float(s) - 0.5))})
    if segs:
        left = segs[0]["x0_px"]
        right = segs[-1]["x1_px"]
        out.update({"y_px": pos, "segments": segs, "n_segments": len(segs),
                    "left_px": _rnd(left, 3), "right_px": _rnd(right, 3),
                    "width_px": _rnd(right - left, 3), "empty": False,
                    "width_mm": (round((right - left) / ppm, 4) if ppm else None)})
    else:
        out.update({"y_px": pos, "segments": [], "n_segments": 0, "left_px": None,
                    "right_px": None, "width_px": None, "empty": True,
                    "note": "this scan line has no foreground (change y_px or check roi)"})
    return None


def _probe_scan_x(ent, out, box, x_px, H, W, ppm):
    """Vertical scan line (x_px): subpixel top/bottom edges / multiple segments. Updates out in place on success, returns an error receipt on failure."""
    x0, y0, bw, bh = box
    pos = int(round(float(x_px))) if x_px is not None else int(x0 + bw // 2)
    if not (0 <= pos < W):
        return _j({"ok": False, "error": "x_px out of bounds", "x_px": x_px, "shape_px": [W, H]})
    line = ent["mask"][:, pos]
    prof = ent["gray"][:, pos]
    runs = _runs_1d(line[y0:y0 + bh], y0)
    segs = []
    for (s, e) in runs:
        tsub = _subpixel_edge(prof, int(s))
        bsub = _subpixel_edge(prof, int(e))
        segs.append({"y0_px": (tsub if tsub is not None else float(s) - 0.5),
                     "y1_px": (bsub if bsub is not None else float(e) + 0.5),
                     "height_px": ((bsub if bsub is not None else float(e) + 0.5)
                                   - (tsub if tsub is not None else float(s) - 0.5))})
    if segs:
        top = segs[0]["y0_px"]
        bot = segs[-1]["y1_px"]
        out.update({"x_px": pos, "segments": segs, "n_segments": len(segs),
                    "top_px": _rnd(top, 3), "bottom_px": _rnd(bot, 3),
                    "height_px": _rnd(bot - top, 3), "empty": False,
                    "height_mm": (round((bot - top) / ppm, 4) if ppm else None)})
    else:
        out.update({"x_px": pos, "segments": [], "n_segments": 0, "top_px": None,
                    "bottom_px": None, "height_px": None, "empty": True})
    return None


def _probe_holes(ent, out, op, box, x_px, y_px, ppm):
    """circle / holes: hole circle fit (Kasa); updates out in place, returns None."""
    hbox = list(ent.get("bbox_px") or box)
    holes, _filled = _holes_of(ent["mask"], hbox)
    rows = []
    for hrow in holes:
        hm = hrow.pop("mask", None)
        if hm is None:
            continue
        fit = _circle_from_hole(hm, int(hbox[0]), int(hbox[1]))
        row = {"bbox_px": hrow["bbox_px"], "center_px": hrow["center_px"],
               "area_px": int(hrow["area_px"])}
        if fit:
            dpx = float(fit["diameter_px"])
            row.update({"fit_center_px": _rnd(fit["center_px"], 3),
                        "radius_px": round(float(fit["radius_px"]), 3),
                        "diameter_px": round(dpx, 3),
                        "kasa_radius_px": round(float(fit["kasa_radius_px"]), 3),
                        "residual_px": round(float(fit["residual_px"]), 3),
                        "n_edge_px": int(fit["n_edge_px"]),
                        "is_circle": bool(fit.get("is_circle")),
                        "diameter_mm": (round(dpx / ppm, 4) if ppm else None)})
        rows.append(row)
    pick = None
    if op == "circle" and rows:
        if x_px is not None and y_px is not None:
            tx, ty = float(x_px), float(y_px)
            pick = min(rows, key=lambda r: (float(r["fit_center_px"][0]) - tx) ** 2
                       + (float(r["fit_center_px"][1]) - ty) ** 2) if rows and rows[0].get("fit_center_px") else None
        if pick is None:
            pick = max(rows, key=lambda r: float(r.get("diameter_px") or 0.0))
    out.update({"found": bool(len(rows)), "holes": rows[:12], "holes_count": len(rows)})
    if op == "circle":
        out["circle"] = pick
        if pick is None:
            out["hint"] = "no inner holes detected in the roi/image; give a tighter roi or check alpha/contrast"
    return None


def _probe_distance(out, p1_px, p2_px, ppm):
    """distance: distance between two points (with mm). Returns an error receipt on failure."""
    if p1_px is None or p2_px is None:
        return _j({"ok": False, "error": "distance needs p1_px and p2_px", "op": "distance"})
    try:
        ax, ay = float(p1_px[0]), float(p1_px[1])
        bx, by = float(p2_px[0]), float(p2_px[1])
    except Exception:
        return _j({"ok": False, "error": "p1_px/p2_px must be [x,y]", "p1_px": p1_px, "p2_px": p2_px})
    dist = math.hypot(bx - ax, by - ay)
    out.update({"p1_px": [ax, ay], "p2_px": [bx, by], "distance_px": _rnd(dist, 3),
                "distance_mm": (round(dist / ppm, 4) if ppm else None)})
    return None


def _probe_profile(ent, out, box, y_px, H, W):
    """profile: gray/mask profile along the scan line (downsampled to ≤256 points). Returns an error receipt on failure."""
    x0, y0, bw, bh = box
    pos = int(round(float(y_px))) if y_px is not None else int(y0 + bh // 2)
    if not (0 <= pos < H):
        return _j({"ok": False, "error": "y_px out of bounds", "y_px": y_px, "shape_px": [W, H]})
    prof = ent["gray"][pos, x0:x0 + bw]
    step = max(1, int(bw // 256))
    vals = prof[::step]
    mvals = ent["mask"][pos, x0:x0 + bw][::step]
    out.update({"axis": "x", "y_px": pos, "x0_px": x0, "step_px": step,
                "gray": [round(float(v), 4) for v in vals.tolist()],
                "mask": [int(1 if v else 0) for v in mvals.tolist()]})
    return None


def img_probe(image_id=None, path=None, op="scan_y", roi=None, y_px=None, x_px=None,
              p1_px=None, p2_px=None):
    """On-demand measurement (reads the cache, fast on the hot path): scan_y / scan_x subpixel left-right (top-bottom) edges and segments; circle/holes circular holes;
    distance between two points; profile gray profile. px_per_mm only comes from img_digest's calibration (never invented)."""
    t0 = time.time()
    op = str(op or "scan_y").strip().lower()
    ops_doc = {"scan_y": "horizontal scan line: left/right edges/width/segments at y_px (subpixel)",
               "scan_x": "vertical scan line: top/bottom edges/height/segments at x_px (subpixel)",
               "circle": "circular hole: the largest hole near x_px/y_px or inside roi, Kasa-fitted diameter/residual",
               "holes": "circle-fit list of every hole inside roi",
               "distance": "p1_px↔p2_px distance (with mm when calibrated)",
               "profile": "gray/mask profile along the scan line (downsampled to ≤256 points)"}
    if op in ("help", "ops", "list"):
        return _j({"ok": True, "ops": ops_doc, "version": IMG_VERSION})
    ent, err = _img_entry(image_id, path)
    if ent is None:
        return _j({"ok": False, "error": err,
                   "hint": "run img_digest(path=...) first (it caches mask/gray), or pass path directly"})
    H, W = ent["mask"].shape
    ppm = ent.get("px_per_mm")
    prov = {"image_md5": ent.get("md5"), "path": ent.get("path"), "px_per_mm": ppm, "shape_px": [W, H]}
    box = _norm_roi(roi, W, H)
    if box is None:
        return _j({"ok": False, "error": "bad roi: needs [x,y,w,h] with w/h>0 and intersecting the image",
                   "roi": roi, "shape_px": [W, H]})
    out = {"ok": True, "version": IMG_VERSION, "op": op, "provenance": prov, "roi": box}
    if op == "scan_y":
        errd = _probe_scan_y(ent, out, box, y_px, H, W, ppm)
    elif op == "scan_x":
        errd = _probe_scan_x(ent, out, box, x_px, H, W, ppm)
    elif op in ("circle", "holes"):
        errd = _probe_holes(ent, out, op, box, x_px, y_px, ppm)
    elif op == "distance":
        errd = _probe_distance(out, p1_px, p2_px, ppm)
    elif op == "profile":
        errd = _probe_profile(ent, out, box, y_px, H, W)
    else:
        return _j({"ok": False, "error": "unknown probe op", "op": op, "ops": sorted(ops_doc)})
    if errd is not None:
        return errd
    out["cached"] = True
    out["elapsed_ms"] = round((time.time() - t0) * 1000.0, 2)
    return _j(out)



# ── img_measure: pixels → mm, compared against expectations (rows + delta + verdict) ──────────
def _feature_px(feature, ent):
    """Feature name → (px_len, label, p1, p2). Supports bbox_w/bbox_h/bbox_diag/circle[:n]/number:<key>."""
    if feature is None:
        return None, None, None, None
    f = str(feature).strip().lower().replace("-", "_").replace(" ", "_")
    sil = (ent or {}).get("silhouette") or {}
    bbox = sil.get("bbox_px") or (ent or {}).get("bbox_px")
    if bbox:
        x, y, w, h = [float(v) for v in bbox[:4]]
        if f in ("bbox_w", "width", "w", "outer_w"):
            return w, "bbox_w", [x, y], [x + w, y]
        if f in ("bbox_h", "height", "h", "outer_h"):
            return h, "bbox_h", [x, y], [x, y + h]
        if f in ("bbox_diag", "diag", "diagonal"):
            return math.hypot(w, h), "bbox_diag", [x, y], [x + w, y + h]
    if f.startswith("number:"):
        key = f.split(":", 1)[1]
        for nrow in (ent or {}).get("numbers") or []:
            if str(nrow.get("key")) == key and nrow.get("value") is not None and nrow.get("unit") == "px":
                return float(nrow["value"]), "number:" + key, None, None
        return None, None, None, None
    if f.startswith("circle") or f.startswith("hole") or f.startswith("feature"):
        parts = f.replace(":", "_").replace(".", "_").split("_")
        idx = 0
        for p in parts:
            if p.isdigit():
                idx = int(p)
                break
        feats = (ent or {}).get("features") or []
        cand = [ft for ft in feats
                if (ft.get("geom") or {}).get("diameter_px") or (ft.get("geom") or {}).get("radius_px")]
        if not cand:
            return None, None, None, None
        ft = cand[min(idx, len(cand) - 1)]
        g = ft.get("geom") or {}
        dpx = float(g.get("diameter_px") or (2.0 * float(g.get("radius_px") or 0.0)))
        c = g.get("center_px") or [0.0, 0.0]
        return dpx, "circle_diam", [float(c[0]) - dpx / 2.0, float(c[1])], [float(c[0]) + dpx / 2.0, float(c[1])]
    return None, None, None, None


def _measure_scale(px_per_mm, ent):
    """Resolve px_per_mm (an explicit arg wins, then the digest cache); returns (ppm, src, err)."""
    ppm = None
    scale_src = None
    if px_per_mm is not None:
        try:
            ppm = float(px_per_mm)
        except Exception:
            return None, None, {"ok": False, "error": "px_per_mm must be a number", "px_per_mm": px_per_mm}
        if ppm <= 0:
            return None, None, {"ok": False, "error": "px_per_mm must be > 0", "px_per_mm": px_per_mm}
        scale_src = "arg"
    elif ent is not None and ent.get("px_per_mm"):
        ppm = float(ent["px_per_mm"])
        scale_src = "cached_digest"
    if ppm is None:
        return None, None, {"ok": False, "error": "no px_per_mm: cannot convert pixels to mm", "verdict": "needs_scale",
                            "hint": "calibrate with img_digest(path=..., known_len={'mm':...,'p1_px':...,'p2_px':...}), or pass px_per_mm directly"}
    return ppm, scale_src, None


def _measure_specs(targets, pairs):
    """targets/pairs → unified specs list; returns (specs, err)."""
    specs = []
    for src_list in (targets, pairs):
        if src_list is None:
            continue
        if isinstance(src_list, dict):
            for k, v in src_list.items():
                if isinstance(v, dict):
                    d = dict(v)
                    d.setdefault("key", k)
                    specs.append(d)
                else:
                    specs.append({"key": k, "px": v})
        elif isinstance(src_list, (list, tuple)):
            specs.extend(list(src_list))
    specs = [s for s in specs if s is not None]
    if not specs:
        return None, {"ok": False, "error": "give at least one targets / pairs entry (otherwise there is nothing to measure)",
                      "hint": "targets=[{key:'width', p1_px:[x1,y1], p2_px:[x2,y2], expect_mm:160}]"}
    return specs, None


def _measure_px_len(d, ent):
    """Resolve the pixel length of one spec; returns (px_len, method, p1, p2)."""
    p1 = d.get("p1_px") or d.get("p1") or d.get("a")
    p2 = d.get("p2_px") or d.get("p2") or d.get("b")
    px_len = None
    method = None
    if d.get("px") is not None or d.get("dist_px") is not None:
        try:
            px_len = float(d.get("px") if d.get("px") is not None else d.get("dist_px"))
            method = "given_px"
        except Exception:
            px_len = None
    elif isinstance(d.get("points"), (list, tuple)) and len(d["points"]) >= 2:
        try:
            p1, p2 = d["points"][0], d["points"][1]
            px_len = math.hypot(float(p2[0]) - float(p1[0]), float(p2[1]) - float(p1[1]))
            method = "two_points"
        except Exception:
            px_len = None
    elif p1 is not None and p2 is not None:
        try:
            px_len = math.hypot(float(p2[0]) - float(p1[0]), float(p2[1]) - float(p1[1]))
            method = "two_points"
        except Exception:
            px_len = None
    elif d.get("feature") is not None:
        px_len, _lbl, fp1, fp2 = _feature_px(d["feature"], ent)
        if px_len is not None:
            method = "feature:" + str(d["feature"])
            p1 = p1 or fp1
            p2 = p2 or fp2
    return px_len, method, p1, p2


def _measure_row(key, px_len, method, p1, p2, d, ppm):
    """One spec → row (mm conversion + comparison against the expected value); an error row when no pixel length can be resolved."""
    if px_len is None:
        return {"key": key, "verdict": "error",
                "error": "cannot resolve a pixel length (give p1_px/p2_px, px, points or feature)"}
    value_mm = float(px_len) / ppm
    expect_mm = None
    if d.get("expect_mm") is not None:
        try:
            expect_mm = float(d["expect_mm"])
        except Exception:
            expect_mm = None
    if expect_mm is None and d.get("expect_px") is not None:
        try:
            expect_mm = float(d["expect_px"]) / ppm
        except Exception:
            expect_mm = None
    delta_mm = None
    delta_pct = None
    verdict = "measured"
    why = None
    if expect_mm is not None:
        delta_mm = value_mm - expect_mm
        delta_pct = (100.0 * delta_mm / expect_mm) if expect_mm else None
        try:
            tol = abs(float(d["tol_mm"])) if d.get("tol_mm") is not None \
                else abs(expect_mm) * float(d.get("tol_pct", 2.0)) / 100.0
        except Exception:
            tol = abs(expect_mm) * 0.02
        verdict = "pass" if abs(delta_mm) <= tol + 1e-9 else "fail"
        why = "|delta|=%.4f mm %s tol %.4f mm" % (abs(delta_mm), "<=" if verdict == "pass" else ">", tol)
    return {"key": key, "value_px": round(float(px_len), 4),
            "value_mm": round(value_mm, 4),
            "expect_mm": (round(expect_mm, 4) if expect_mm is not None else None),
            "delta_mm": (round(delta_mm, 4) if delta_mm is not None else None),
            "delta_pct": (round(delta_pct, 3) if delta_pct is not None else None),
            "verdict": verdict, "why": why, "method": method,
            "p1_px": _rnd(p1, 3), "p2_px": _rnd(p2, 3)}


def _measure_verdict(rows):
    """Overall verdict: any error/fail ⇒ fail; any pass ⇒ pass; otherwise measured."""
    fails = [r for r in rows if r.get("verdict") == "fail"]
    errors = [r for r in rows if r.get("verdict") == "error"]
    if errors or fails:
        return "fail"
    if any(r.get("verdict") == "pass" for r in rows):
        return "pass"
    return "measured"


def _measure_annotate(rows, ent, out_dir):
    """Draw the measurement lines onto the image and save it; returns None on failure (not fatal)."""
    if not out_dir or ent is None:
        return None
    try:
        arr, p2_, _n, _l = _load_ex(ent.get("path"), max_px=16000000)
        ov = arr.copy()
        for r in rows:
            if r.get("p1_px") and r.get("p2_px"):
                _draw_line(ov, r["p1_px"], r["p2_px"], [1.0, 0.2, 0.2], 2)
        return _save(ov, os.path.join(str(out_dir), "measure_annotated.png"))
    except Exception:
        return None


def img_measure(image_id=None, path=None, px_per_mm=None, targets=None, pairs=None, out_dir=None):
    """Convert pixel measurements to mm and compare against the expected values: rows[{key,value_mm,expect_mm,delta_mm,delta_pct,verdict}].

    Each targets/pairs entry: {key, p1_px, p2_px} or {key, px} or {key, feature:"bbox_w"|"circle:0"},
    optional expect_mm / expect_px / tol_mm / tol_pct (default 2%). Without px_per_mm ⇒ ok:false + needs_scale.
    """
    ent = None
    ent_err = None
    if image_id is not None or (path is not None and str(path).strip() != ""):
        ent, ent_err = _img_entry(image_id, path)
        if ent is None:
            return _j({"ok": False, "error": ent_err,
                       "hint": "path must exist; image_id requires img_digest first"})
    ppm, scale_src, serr = _measure_scale(px_per_mm, ent)
    if serr is not None:
        return _j(serr)
    specs, sperr = _measure_specs(targets, pairs)
    if sperr is not None:
        return _j(sperr)
    rows = []
    for i, raw in enumerate(specs):
        d = raw if isinstance(raw, dict) else {}
        key = str(d.get("key") or d.get("id") or ("m%d" % (i + 1)))
        px_len, method, p1, p2 = _measure_px_len(d, ent)
        rows.append(_measure_row(key, px_len, method, p1, p2, d, ppm))
    verdict = _measure_verdict(rows)
    annotated = _measure_annotate(rows, ent, out_dir)
    return _j({"ok": bool(verdict != "fail"), "verdict": verdict, "rows": rows, "count": len(rows),
               "provenance": {"image_md5": (ent or {}).get("md5"), "px_per_mm": ppm,
                              "scale_source": scale_src, "units": "mm",
                              "image_path": ((ent or {}).get("path") or (str(path) if path else None))},
               "annotated": annotated,
               "note": "pass/fail is only judged when expect_mm is given; delta_pct is a percentage relative to the expected value"})
