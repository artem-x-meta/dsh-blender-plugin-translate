# -*- coding: utf-8 -*-
"""DSH evaluation base (evalharness) v1 — P2-B: turns "can the plugin actually catch defects" into one re-runnable command.

Why it exists: calib only calibrates the gate; assembly/scan and imgtools have no shared replay entry point for defect-detection capability.
This module does three things (**all on the real machine, all runnable headless**):
  1) Synthetic defect injection (assembly suite): D1 shallow clash / D3 fully contained / D4 12mm hidden overlap within design (allow) /
     D5 face contact / D7 floater / D8 inverted normals → calls K.dsh_assembly_api("scan"/"gate") → caught/missed per case;
  2) Synthetic reference-image replay (reference suite): rectangle/ring/slant PNG → K.dsh_img_api("digest"/"probe"/"measure")
     → asserts bbox / px_per_mm / readability / needs_scale;
  3) Gate baseline (core suite): K.dsh_calib_api("run") → capture_rate / baseline_pass.
Outputs a three-state verdict + per-suite cases + capture_rate / missed / false_positive / baseline_pass +
out_json (path + md5) + ms. **A missing module means skipped + degraded; it never pretends to pass.**

Discipline:
  * Only touch test objects carrying the __eval_ prefix; clean up at the end (success or failure); restore scene units afterwards;
  * Objects already in the user's scene are **left alone** (scan/gate receive only the test object names; calib uses its own __dsh_calib_ prefix);
  * Bad arguments ⇒ ok:false; a missing dependency or a crashing suite = skipped/degraded/fail, never silently counted as pass;
  * Pure bpy + numpy (no PIL/scipy/cv2); reference images are written as PNG through a bpy image.

How to run (native E2E): tests/e2e/blender/native/evalharness.py is executed by
    tests/e2e/blender/native_runner.py; the host entry point is tests/e2e/blender/test_native_e2e.py.
"""
import json
import math
import os
import sys
import tempfile
import time

import bpy
import numpy as np

EVALHARNESS_VERSION = 1
PFX = "__eval_"
SUITES = ("core", "assembly", "reference")
# **Hard dependencies** per suite (missing → that suite is skipped); assembly/audit and friends are reference items (a stricter path is used when present)
SUITE_DEPS = {
    "core": {"required": ("calib",), "optional": ("gate", "audit", "printcheck", "contract")},
    "assembly": {"required": ("assembly",), "optional": ("audit", "contract", "clearance", "gate")},
    "reference": {"required": ("imgtools",), "optional": ()},
}
MODULE_ATTR = {"assembly": "dsh_assembly_api", "audit": "dsh_audit_api", "calib": "dsh_calib_api",
               "imgtools": "dsh_img_api", "gate": "dsh_gate_api", "contract": "dsh_contract_api",
               "clearance": "dsh_clearance_api", "mesh_fix": "dsh_fix_api",
               "printcheck": "dsh_print_api", "txn": "dsh_txn_api", "shapesolve": "dsh_shapesolve_api"}

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("evalharness.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")

_j = _KIT.j


# ────────────────────────────── basic helpers ──────────────────────────────
def _kernel():
    return sys.modules.get("dsh_rt_kernel")


def _api(name):
    K = _kernel()
    if K is None:
        return None
    return getattr(K, MODULE_ATTR.get(name, "dsh_%s_api" % name), None)


def _present():
    out = {}
    for name in sorted(set(list(MODULE_ATTR.keys()))):
        out[name] = _api(name) is not None
    return out


def _call(name, op, args=None):
    """Call a sub-op of K.dsh_<name>_api → (dict|None, error)."""
    api = _api(name)
    if api is None:
        return None, "K.%s does not exist (include %s in preload)" % (MODULE_ATTR.get(name, name), name)
    try:
        out = api(str(op), dict(args or {}))
    except Exception as e:
        return None, "K.%s.%s call failed: %s: %s" % (name, op, type(e).__name__, str(e)[:200])
    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            return None, "K.%s.%s returned non-JSON" % (name, op)
    if not isinstance(out, dict):
        return None, "K.%s.%s returned an unexpected type: %s" % (name, op, type(out).__name__)
    return out, None


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def _r(x, n=4):
    try:
        return round(float(x), int(n))
    except Exception:
        return None


def _win(p):
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


def _sha256_file(path):
    import hashlib
    try:
        h = hashlib.sha256()
        with open(_win(path), "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
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


# ────────────────────────────── scene / PNG helpers ──────────────────────────────
def _purge():
    """Delete every __eval_ object/mesh (idempotent; only touches its own prefix)."""
    removed = []
    for ob in [o for o in bpy.data.objects if str(o.name).startswith(PFX)]:
        try:
            nm = str(ob.name)
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            removed.append(nm)
            if me is not None and me.users == 0:
                try:
                    bpy.data.meshes.remove(me, do_unlink=True)
                except Exception:
                    pass
        except Exception:
            pass
    for me in [m for m in bpy.data.meshes if str(m.name).startswith(PFX)]:
        try:
            bpy.data.meshes.remove(me, do_unlink=True)
        except Exception:
            pass
    return removed


def _cube(name, size, loc=(0.0, 0.0, 0.0), flip=False):
    """Create a cube with the __eval_ prefix (size is in scene units; the caller guarantees the mm convention)."""
    import bmesh
    nm = str(name)
    if not nm.startswith(PFX):
        nm = PFX + nm
    me = bpy.data.meshes.new(nm)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co *= float(size)
    if flip:
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(nm, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = tuple(float(x) for x in loc)
    return ob.name


def _update():
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass


def _write_png(path, rgb_topdown, alpha_topdown=None):
    """Top-down RGB(A) numpy → PNG (Blender pixels run bottom→top, so flip before writing)."""
    h, w = int(rgb_topdown.shape[0]), int(rgb_topdown.shape[1])
    img = bpy.data.images.new(os.path.basename(str(path)), width=w, height=h, alpha=True)
    arr = np.ones((h, w, 4), dtype=np.float32)
    rgb = np.asarray(rgb_topdown, dtype=np.float32)
    if rgb.ndim == 2:
        rgb = np.stack([rgb, rgb, rgb], axis=-1)
    arr[..., 0:3] = np.clip(rgb[::-1], 0.0, 1.0)
    if alpha_topdown is not None:
        arr[..., 3] = np.clip(np.asarray(alpha_topdown, dtype=np.float32)[::-1], 0.0, 1.0)
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
    return _win(path)
# ────────────────────────────── assembly suite: synthetic defect injection ──────────────────────────────
def _pair_key(a, b):
    x, y = str(a), str(b)
    return (x, y) if x <= y else (y, x)


def _pairs_by_key(scan):
    out = {}
    for p in scan.get("pairs") or []:
        if isinstance(p, dict):
            out[_pair_key(p.get("a"), p.get("b"))] = p
    return out


def _floater_objects(scan):
    names = set()
    for f in scan.get("floaters") or []:
        if not isinstance(f, dict):
            continue
        if f.get("object"):
            names.add(str(f.get("object")))
        for o in f.get("objects") or []:
            names.add(str(o))
    return names


def _gate_state(gate, gid):
    for g in (gate or {}).get("gates") or []:
        if isinstance(g, dict) and str(g.get("id")) == str(gid):
            return g
    return {}


def _suite_deps(suite, present):
    req = list(SUITE_DEPS[suite]["required"])
    opt = list(SUITE_DEPS[suite]["optional"])
    return {"required": req, "optional": opt,
            "present": [x for x in req + opt if present.get(x)],
            "missing": [x for x in req if not present.get(x)],
            "optional_missing": [x for x in opt if not present.get(x)]}


def _asm_probe_scene():
    """Build the six defect probes (D1 shallow clash / D3 fully contained / D4 in-design overlap / D5 face contact / D7 floater / D8 inverted normals); returns (names, spec)."""
    _purge()
    names = []
    names.append(_cube("D1_a", 20.0, (0.0, 0.0, 0.0)))
    names.append(_cube("D1_b", 20.0, (19.0, 0.0, 0.0)))           # shallow clash, 1mm
    names.append(_cube("D3_big", 40.0, (100.0, 0.0, 0.0)))
    names.append(_cube("D3_small", 6.0, (100.0, 0.0, 0.0)))       # fully contained (no face intersection)
    names.append(_cube("D4_a", 40.0, (0.0, 100.0, 0.0)))
    names.append(_cube("D4_b", 40.0, (0.0, 100.0, 28.0)))         # 12mm in-design overlap along z
    names.append(_cube("D5_a", 20.0, (0.0, 200.0, 0.0)))
    names.append(_cube("D5_b", 20.0, (20.0, 200.0, 0.0)))         # face contact, gap=0
    names.append(_cube("D7_float", 6.0, (240.0, 0.0, 0.0)))       # floater
    names.append(_cube("D8_inv", 20.0, (300.0, 300.0, 0.0), flip=True))  # normals pointing inwards
    _update()
    spec = {"allow": [{"id": "ALLOW_D4", "a": PFX + "D4_a", "b": PFX + "D4_b",
                       "max_depth_mm": 13.0, "max_volume_mm3": 25000.0,
                       "reason": "evalharness: 12mm hidden overlap within design (1mm sampling tolerance allowed)"}]}
    return names, spec


def _asm_scan_gate(res, names, spec):
    """Run assembly.scan + assembly.gate and extract pairs/floats/normals/offenders; returns a 7-tuple."""
    scan, serr = _call("assembly", "scan",
                       {"objects": list(names), "spec": spec, "summary_only": False,
                        "max_pairs": 500, "report_gap_mm": 5.0})
    if serr:
        res["errors"].append("assembly.scan: %s" % serr)
    gate, gerr = _call("assembly", "gate",
                       {"objects": list(names), "spec": spec, "summary_only": True, "strict": True})
    if gerr:
        res["errors"].append("assembly.gate: %s" % gerr)
    pairs = _pairs_by_key(scan or {})
    floats = _floater_objects(scan or {})
    norm_gate = _gate_state(gate, "normals")
    inverted = [str(x) for x in (norm_gate.get("inverted") or [])]
    offenders = set()
    for p in (scan or {}).get("offenders") or []:
        if isinstance(p, dict):
            offenders.add(_pair_key(p.get("a"), p.get("b")))
    return scan, gate, pairs, floats, norm_gate, inverted, offenders


def _asm_cases(pairs, floats, norm_gate, scan, present, offenders, inverted):
    """Verdicts for the six cases; returns (cases, unverified, false_positive)."""
    cases = []
    unverified = []
    false_positive = 0

    def _pair_case(cid, a, b, expect, allowed=False):
        nonlocal false_positive
        rec = pairs.get(_pair_key(a, b), {})
        got = rec.get("class") if rec else "missing"
        ok = got == expect
        if expect != "missing" and not rec and not (scan or {}).get("ok"):
            unverified.append(cid)
            ok = False
        cases.append({"id": cid, "expect": expect, "got": got, "ok": bool(ok),
                      "declared": bool(rec.get("declared")),
                      "depth_mm": rec.get("depth_mm"), "volume_mm3": rec.get("volume_mm3")})
        if allowed and _pair_key(a, b) in offenders:
            false_positive += 1
            cases[-1]["false_positive"] = True
        return ok

    _pair_case("D1_shallow_clash", PFX + "D1_a", PFX + "D1_b", "clash")
    _pair_case("D3_contained", PFX + "D3_big", PFX + "D3_small", "contained")
    _pair_case("D4_hidden_ok_allowed", PFX + "D4_a", PFX + "D4_b", "hidden_ok", allowed=True)
    _pair_case("D5_face_contact", PFX + "D5_a", PFX + "D5_b", "contact")
    d7 = PFX + "D7_float"
    got7 = "float" if d7 in floats else ("unresolved" if not floats else "missing")
    cases.append({"id": "D7_floater", "expect": "float", "got": got7, "ok": got7 == "float"})
    if not present.get("audit") and got7 != "float":
        unverified.append("D7_floater")
    d8 = PFX + "D8_inv"
    got8 = str(norm_gate.get("state") or "missing")
    d8_ok = bool(got8 == "fail" and d8 in inverted)
    cases.append({"id": "D8_inverted_normals", "expect": "gate_normals_fail", "got": got8,
                  "ok": d8_ok, "inverted": inverted[:6]})
    if not present.get("audit") and not d8_ok:
        unverified.append("D8_inverted_normals")
    return cases, unverified, false_positive


def _asm_baseline(res):
    """Clean baseline: two parts in face contact + a manifest interface → the gate must pass (guards against a detector that always fails)."""
    try:
        _purge()
        ca = _cube("clean_a", 20.0, (0.0, 0.0, 0.0))
        cb = _cube("clean_b", 20.0, (20.0, 0.0, 0.0))
        _update()
        man = {"schema": "dsh-assembly-manifest/1", "units": "mm", "assembly": "eval-clean",
               "parts": [{"id": ca, "objects": [ca]}, {"id": cb, "objects": [cb]}],
               "interfaces": [{"id": "IF-clean", "a": ca, "b": cb, "fit": "location",
                               "nominal_mm": 0.0, "tol_mm": 0.5}],
               "allow_pairs": []}
        g2, g2err = _call("assembly", "gate",
                          {"objects": [ca, cb], "manifest": man, "summary_only": True, "strict": True})
        if g2err:
            res["errors"].append("baseline gate: %s" % g2err)
        res["baseline_pass"] = bool((g2 or {}).get("verdict") == "pass"
                                    and (g2 or {}).get("export_allowed") is True)
        res["evidence"]["baseline_gate"] = {"verdict": (g2 or {}).get("verdict"),
                                            "export_allowed": (g2 or {}).get("export_allowed")}
    finally:
        _purge()


def _asm_evidence(scan, gate, floats, norm_gate, inverted, offenders):
    """Evidence block (scan/gate/floaters/normals/offenders)."""
    return {
        "scan_ok": bool((scan or {}).get("ok")),
        "scan_verdict": (scan or {}).get("verdict"),
        "scan_counts": (scan or {}).get("counts"),
        "scan_coverage": {k: (scan or {}).get("coverage", {}).get(k)
                          for k in ("complete", "truncated", "budget_hit")},
        "floaters": sorted(floats)[:10],
        "gate_verdict": (gate or {}).get("verdict"),
        "gate_export_allowed": (gate or {}).get("export_allowed"),
        "gate_normals": {"state": norm_gate.get("state"), "inverted": inverted[:6]},
        "offenders": sorted(["%s|%s" % k for k in offenders])[:10],
    }


def _asm_finalize(res, scan, gate, unverified, min_capture):
    """Aggregate state/warnings (errors → fail; missing dependencies → degraded; capture rate/false positives/baseline → fail/pass)."""
    scan_ok = bool((scan or {}).get("ok")) and (scan or {}).get("verdict") == "fail"
    gate_ok = bool((gate or {}).get("verdict") in ("fail", "degraded")
                   and (gate or {}).get("export_allowed") is False)
    rate = res["capture_rate"] or 0.0
    if res["errors"]:
        res["state"] = "fail"
    elif unverified:
        res["state"] = "degraded"
        res["warnings"].append("missing dependencies leave %d cases unconfirmed: %s (%s)"
                               % (len(unverified), unverified, res["dependencies"]["optional_missing"]))
    elif rate < float(min_capture) or res["false_positive"] or res["baseline_pass"] is not True                 or not scan_ok or not gate_ok:
        res["state"] = "fail"
    else:
        res["state"] = "pass"
    if not scan_ok:
        res["warnings"].append("scan did not return verdict=fail (%r) — the conclusion the injected defects should produce never appeared"
                               % (scan or {}).get("verdict"))
    if not gate_ok:
        res["warnings"].append("gate did not refuse (verdict=%r export_allowed=%r)"
                               % ((gate or {}).get("verdict"), (gate or {}).get("export_allowed")))


def _run_assembly(min_capture=0.8):
    """assembly suite: D1 shallow clash / D3 fully contained / D4 12mm allow / D5 face contact / D7 floater / D8 inverted normals."""
    t0 = time.perf_counter()
    present = _present()
    res = {"id": "assembly", "state": "skipped", "dependencies": _suite_deps("assembly", present),
           "cases": [], "capture_rate": None, "missed": [], "false_positive": 0,
           "baseline_pass": None, "warnings": [], "errors": [], "evidence": {}}
    if not present.get("assembly"):
        res["warnings"].append("K.dsh_assembly_api does not exist — assembly suite skipped (not installed / not preloaded)")
        res["ms"] = int((time.perf_counter() - t0) * 1000)
        return res
    prev_scale = float(bpy.context.scene.unit_settings.scale_length)
    try:
        bpy.context.scene.unit_settings.scale_length = 0.001     # 1 unit = 1 mm
        names, spec = _asm_probe_scene()
        scan, gate, pairs, floats, norm_gate, inverted, offenders = _asm_scan_gate(res, names, spec)
        cases, unverified, false_positive = _asm_cases(pairs, floats, norm_gate, scan, present, offenders, inverted)
        res["false_positive"] = false_positive
        _asm_baseline(res)
        caught = [c for c in cases if c.get("ok") is True]
        res["cases"] = cases
        res["capture_rate"] = _r(len(caught) / float(len(cases)), 4) if cases else None
        res["missed"] = [c["id"] for c in cases if c.get("ok") is not True]
        res["evidence"].update(_asm_evidence(scan, gate, floats, norm_gate, inverted, offenders))
        _asm_finalize(res, scan, gate, unverified, min_capture)
    except Exception as e:
        import traceback
        res["state"] = "fail"
        res["errors"].append("%s: %s" % (type(e).__name__, str(e)[:240]))
        res["traceback"] = traceback.format_exc()[-800:]
    finally:
        try:
            bpy.context.scene.unit_settings.scale_length = prev_scale
        except Exception:
            pass
        _purge()
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res

# ────────────────────────────── reference suite: synthetic reference-image replay ──────────────────────────────
def _gen_ref_images(tmp):
    """Build three synthetic reference images: a rectangle (known size + alpha), a ring (alpha), and a slant line (opaque greyscale → Otsu)."""
    res = 512
    yy, xx = np.mgrid[0:res, 0:res]
    rect = np.zeros((res, res), dtype=bool)
    rect[100:250, 80:380] = True
    rgb_rect = np.where(rect, 0.10, 1.0)
    p_rect = _write_png(os.path.join(tmp, "eval_rect.png"), rgb_rect, rect.astype(np.float32))
    cy = cx = 256.0
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    ring = (d <= 100.0) & (d >= 50.0)
    rgb_ring = np.where(ring, 0.10, 1.0)
    p_ring = _write_png(os.path.join(tmp, "eval_ring.png"), rgb_ring, ring.astype(np.float32))
    s45 = math.sqrt(0.5)
    u = (xx - cx) * s45 + (yy - cy) * s45
    v = -(xx - cx) * s45 + (yy - cy) * s45
    line = (np.abs(u) <= 120.0) & (np.abs(v) <= 8.0)
    rgb_line = np.where(line, 0.10, 0.90)          # opaque: goes through Otsu (dark object on a light background)
    p_line = _write_png(os.path.join(tmp, "eval_slant.png"), rgb_line, None)
    return {"rect": p_rect, "ring": p_ring, "slant": p_line,
            "rect_bbox": [80, 100, 300, 150], "ring_diameter_px": 100.0}


def _ref_case(cases, cid, ok, expect=None, got=None, **extra):
    """Record one case (appends to cases and returns a bool)."""
    row = {"id": cid, "ok": bool(ok), "expect": expect, "got": got}
    row.update(extra)
    cases.append(row)
    return bool(ok)


def _ref_rect_cases(res, cases, paths, st):
    """① rectangle digest (bbox/px_per_mm) ② probe horizontal width / vertical height ③ measure pixels→mm."""
    dig, derr = _call("imgtools", "digest",
                      {"path": paths["rect"], "views": ["front", "side"],
                       "known_len": {"mm": 100.0, "p1_px": [80, 175], "p2_px": [380, 175]}})
    if derr:
        res["errors"].append("img.digest(rect): %s" % derr)
    dig = dig or {}
    bbox = ((dig.get("silhouette") or {}).get("bbox_px") or [])
    want_bbox = paths["rect_bbox"]
    bbox_ok = (len(bbox) >= 4 and all(abs(float(bbox[i]) - float(want_bbox[i])) <= 3.0
                                      for i in range(4)))
    ppm = _num((dig.get("scale") or {}).get("px_per_mm"))
    ppm_ok = ppm is not None and abs(ppm - 3.0) / 3.0 <= 0.01
    _ref_case(cases, "digest_rect_ok", dig.get("ok") is True and dig.get("verdict") == "ready_for_spec",
              "ok+ready_for_spec", dig.get("verdict"), verdict=dig.get("verdict"))
    _ref_case(cases, "digest_rect_bbox", bbox_ok, want_bbox, bbox)
    _ref_case(cases, "digest_rect_px_per_mm", ppm_ok, 3.0, ppm)
    pr_y, _e = _call("imgtools", "probe", {"path": paths["rect"], "op": "scan_y", "y_px": 175})
    pr_y = pr_y or {}
    wpx = _num(pr_y.get("width_px"))
    _ref_case(cases, "probe_scan_y_width", (pr_y.get("ok") is True and wpx is not None
                                            and abs(wpx - 300.0) <= 4.0), 300.0, wpx)
    pr_x, _e = _call("imgtools", "probe", {"path": paths["rect"], "op": "scan_x", "x_px": 230})
    pr_x = pr_x or {}
    hpx = _num(pr_x.get("height_px"))
    _ref_case(cases, "probe_scan_x_height", (pr_x.get("ok") is True and hpx is not None
                                             and abs(hpx - 150.0) <= 4.0), 150.0, hpx)
    meas, _e = _call("imgtools", "measure",
                     {"path": paths["rect"],
                      "targets": [{"key": "width", "p1_px": [80, 175], "p2_px": [380, 175],
                                   "expect_mm": 100.0, "tol_pct": 0.02}]})
    meas = meas or {}
    rows = meas.get("rows") or []
    row0 = rows[0] if rows else {}
    vm = _num(row0.get("value_mm"))
    _ref_case(cases, "measure_width_ok", (meas.get("ok") is True and row0.get("verdict") == "pass"
                                         and vm is not None and abs(vm - 100.0) <= 1.0),
              100.0, vm, verdict=row0.get("verdict"))
    st.update({"dig": dig, "bbox": bbox, "want_bbox": want_bbox, "bbox_ok": bbox_ok, "ppm": ppm,
               "ppm_ok": ppm_ok, "meas": meas, "row0": row0, "wpx": wpx, "hpx": hpx, "vm": vm})


def _ref_ring_cases(res, cases, paths, st):
    """④ ring: digest ok + probe circle diameter."""
    dig_r, rerr = _call("imgtools", "digest", {"path": paths["ring"], "views": ["front", "side"]})
    if rerr:
        res["errors"].append("img.digest(ring): %s" % rerr)
    dig_r = dig_r or {}
    circ, _e = _call("imgtools", "probe",
                     {"path": paths["ring"], "op": "circle", "x_px": 256, "y_px": 256})
    circ = circ or {}
    c = circ.get("circle") or {}
    dpx = _num(c.get("diameter_px"))
    _ref_case(cases, "digest_ring_ok", dig_r.get("ok") is True, True, dig_r.get("verdict"),
              verdict=dig_r.get("verdict"))
    _ref_case(cases, "probe_circle_diameter", (circ.get("ok") is True and dpx is not None
                                               and abs(dpx - 100.0) <= 6.0
                                               and c.get("is_circle") is True), 100.0, dpx)
    st.update({"dig_r": dig_r, "dpx": dpx})


def _ref_slant_cases(res, cases, paths, st):
    """⑤ slant: principal axis 45° (mod 180), bbox fill ratio ⑥ uncalibrated needs_scale."""
    dig_l, lerr = _call("imgtools", "digest", {"path": paths["slant"]})
    if lerr:
        res["errors"].append("img.digest(slant): %s" % lerr)
    dig_l = dig_l or {}
    axis = _num((dig_l.get("silhouette") or {}).get("principal_axis_deg"))
    aspect = _num((dig_l.get("silhouette") or {}).get("aspect_wh"))
    fill = _num((dig_l.get("silhouette") or {}).get("fill_ratio"))
    axis_ok = axis is not None and abs(((float(axis) - 45.0 + 90.0) % 180.0) - 90.0) <= 6.0
    _ref_case(cases, "digest_slant_axis", dig_l.get("ok") is True and axis_ok, 45.0, axis,
              aspect=aspect)
    # a 45° slant's bbox is a square (aspect≈1), so thinness has to come from the bbox fill ratio
    _ref_case(cases, "digest_slant_thin", fill is not None and fill < 0.5, "<0.5", fill, aspect=aspect)
    _ref_case(cases, "digest_uncalibrated_needs_scale", dig_l.get("verdict") == "needs_scale",
              "needs_scale", dig_l.get("verdict"))
    meas2, _e = _call("imgtools", "measure",
                      {"path": paths["slant"], "targets": [{"key": "w", "px": 200.0}]})
    _ref_case(cases, "measure_needs_scale_okfalse", (meas2 or {}).get("ok") is False
              and (meas2 or {}).get("verdict") == "needs_scale",
              "ok=false+needs_scale", (meas2 or {}).get("verdict"))
    st.update({"dig_l": dig_l, "axis": axis, "aspect": aspect, "fill": fill, "meas2": meas2})


def _ref_readability(res, dig, dig_r):
    """Readability assertion: a detected feature of >=8px must be marked readable; unreadable rows are only counted, never penalised."""
    fps = 0
    feats = list(dig_r.get("features") or []) + list(dig.get("features") or [])
    for f in feats:
        if not isinstance(f, dict):
            continue
        size = _num(f.get("size_px")) or 0.0
        if size >= 8.0 and f.get("readable") is not True:
            fps += 1
    # <8px corners inside unreadable are an **honest low-readability report**, not false positives; only a >=8px feature marked unreadable counts
    res["false_positive"] = int(fps)
    res["evidence"]["readability"] = {
        "features": len(feats),
        "unreadable_lt8px": (len(dig.get("unreadable") or []) + len(dig_r.get("unreadable") or [])),
    }


def _ref_evidence(st):
    """Evidence block (rectangle/probe/measure/ring/slant)."""
    return {
        "rect": {"bbox_px": st["bbox"], "want_bbox_px": st["want_bbox"], "px_per_mm": st["ppm"],
                 "verdict": st["dig"].get("verdict")},
        "probe": {"scan_y_width_px": st["wpx"], "scan_x_height_px": st["hpx"]},
        "measure": {"value_mm": st["vm"], "verdict": st["row0"].get("verdict")},
        "ring": {"circle_diameter_px": st["dpx"], "digest_verdict": st["dig_r"].get("verdict")},
        "slant": {"principal_axis_deg": st["axis"], "aspect_wh": st["aspect"],
                  "verdict": st["dig_l"].get("verdict")},
    }


def _ref_finalize(res, min_capture):
    """Three-state aggregation (errors/capture_rate/false positives/baseline)."""
    rate = res["capture_rate"] or 0.0
    if res["errors"]:
        res["state"] = "fail"
    elif rate < float(min_capture) or res["false_positive"] or res["baseline_pass"] is not True:
        res["state"] = "fail"
    else:
        res["state"] = "pass"


def _run_reference(min_capture=0.8, keep=False):
    """reference suite: assertions on imgtools digest/probe/measure against synthetic images (rectangle/ring/slant)."""
    t0 = time.perf_counter()
    present = _present()
    res = {"id": "reference", "state": "skipped", "dependencies": _suite_deps("reference", present),
           "cases": [], "capture_rate": None, "missed": [], "false_positive": 0,
           "baseline_pass": None, "warnings": [], "errors": [], "evidence": {}}
    if not present.get("imgtools"):
        res["warnings"].append("K.dsh_img_api does not exist — reference suite skipped (not installed / not preloaded)")
        res["ms"] = int((time.perf_counter() - t0) * 1000)
        return res
    tmp = None
    try:
        tmp = tempfile.mkdtemp(prefix="dsh_evalharness_ref_")
        paths = _gen_ref_images(tmp)
        res["evidence"]["tmp_dir"] = tmp
        cases = []
        st = {}
        _ref_rect_cases(res, cases, paths, st)
        _ref_ring_cases(res, cases, paths, st)
        _ref_slant_cases(res, cases, paths, st)
        _ref_readability(res, st["dig"], st["dig_r"])
        dig_ok = [c for c in cases if c.get("ok") is True]
        res["cases"] = cases
        res["capture_rate"] = _r(len(dig_ok) / float(len(cases)), 4) if cases else None
        res["missed"] = [c["id"] for c in cases if c.get("ok") is not True]
        res["baseline_pass"] = bool(
            st["dig"].get("ok") is True and st["dig"].get("verdict") == "ready_for_spec"
            and st["bbox_ok"] and st["ppm_ok"] and st["meas"].get("ok") is True
            and st["dig_l"].get("verdict") == "needs_scale" and (st["meas2"] or {}).get("ok") is False)
        res["evidence"].update(_ref_evidence(st))
        _ref_finalize(res, min_capture)
    except Exception as e:
        import traceback
        res["state"] = "fail"
        res["errors"].append("%s: %s" % (type(e).__name__, str(e)[:240]))
        res["traceback"] = traceback.format_exc()[-800:]
    finally:
        if tmp and not keep:
            try:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass
    if keep and tmp:
        res["warnings"].append("keep=true: the reference-image temp directory is kept at %s (deleted by default)" % tmp)
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res


# ────────────────────────────── core suite: gate baseline (calib) ──────────────────────────────
def _run_core(min_capture=0.8):
    t0 = time.perf_counter()
    present = _present()
    res = {"id": "core", "state": "skipped", "dependencies": _suite_deps("core", present),
           "cases": [], "capture_rate": None, "missed": [], "false_positive": 0,
           "baseline_pass": None, "warnings": [], "errors": [], "evidence": {}}
    if not present.get("calib"):
        res["warnings"].append("K.dsh_calib_api does not exist — core suite skipped (not installed / not preloaded)")
        res["ms"] = int((time.perf_counter() - t0) * 1000)
        return res
    r, err = _call("calib", "run", {})
    if err:
        res["state"] = "fail"
        res["errors"].append("calib.run: %s" % err)
        res["ms"] = int((time.perf_counter() - t0) * 1000)
        return res
    r = r or {}
    res["capture_rate"] = _r(r.get("capture_rate"), 4) if r.get("capture_rate") is not None else None
    res["baseline_pass"] = bool(r.get("baseline_pass")) if r.get("baseline_pass") is not None else None
    res["missed"] = [str(x) for x in (r.get("missed") or [])]
    cases = [{"id": "baseline_gate", "expect": True, "got": res["baseline_pass"],
              "ok": res["baseline_pass"] is True}]
    for row in r.get("defects") or []:
        if isinstance(row, dict):
            cases.append({"id": str(row.get("id")), "expect": row.get("expect"),
                          "got": bool(row.get("caught")), "ok": row.get("caught") is True,
                          "caught_by": row.get("caught_by"),
                          "why_missed": row.get("why_missed")})
    res["cases"] = cases
    res["evidence"] = {"calib_ok": bool(r.get("ok")), "unit_ok": r.get("unit_ok"),
                       "valid_run": r.get("valid_run"), "defects": r.get("total"),
                       "caught": r.get("caught"),
                       "gate_errors": (r.get("gate_errors") or [])[:6],
                       "warnings": (r.get("warnings") or [])[:6]}
    miss_opt = res["dependencies"]["optional_missing"]
    rate = res["capture_rate"] or 0.0
    if miss_opt:
        res["state"] = "degraded"
        res["warnings"].append("core dependencies are incomplete (%s) ⇒ the calib baseline may be untrustworthy; numbers are reported without judging a pass" % miss_opt)
    elif res["baseline_pass"] is not True:
        res["state"] = "fail"
        res["warnings"].append("The healthy baseline failed ⇒ this calibration is invalid (the gate is misfiring, misconfigured, or the scene is not clean)")
    elif rate < float(min_capture):
        res["state"] = "fail"
    elif r.get("ok") is not True:
        res["state"] = "degraded"
        res["warnings"].append("calib ok=false (see gate_errors/missed); not counted as a pass")
    else:
        res["state"] = "pass"
    res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res
# ────────────────────────────── op: run ──────────────────────────────
SUITE_RUNNERS = {"core": _run_core, "assembly": _run_assembly, "reference": _run_reference}
SUITE_ORDER = ("core", "assembly", "reference")


def _norm_suites(suite):
    if suite is None:
        return list(SUITE_ORDER), None
    raw = suite
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        s = str(raw).strip().lower()
        if s in ("", "all", "*"):
            return list(SUITE_ORDER), None
        items = [x for x in s.replace("+", ",").replace(" ", ",").split(",") if x]
    items = [x.strip().lower() for x in items if str(x).strip()]
    bad = [x for x in items if x not in SUITE_RUNNERS]
    if bad:
        return None, "Unknown suite: %s (supported: %s or all)" % (bad, list(SUITE_ORDER))
    if not items:
        return None, "suite is empty (supported: %s or all)" % list(SUITE_ORDER)
    dedup = []
    for x in SUITE_ORDER:
        if x in items:
            dedup.append(x)
    return dedup, None


def _aggregate(suites):
    states = [s.get("state") for s in suites]
    if any(st == "fail" for st in states):
        verdict = "fail"
    elif any(st in ("degraded", "skipped") for st in states):
        verdict = "degraded"
    elif states and all(st == "pass" for st in states):
        verdict = "pass"
    else:
        verdict = "degraded"
    caught = sum(1 for s in suites for c in (s.get("cases") or []) if c.get("ok") is True)
    total = sum(1 for s in suites for c in (s.get("cases") or []))
    missed = []
    for s in suites:
        for c in s.get("cases") or []:
            if c.get("ok") is not True:
                missed.append("%s:%s" % (s.get("id"), c.get("id")))
    fps = sum(int(s.get("false_positive") or 0) for s in suites)
    baselines = [s.get("baseline_pass") for s in suites if s.get("baseline_pass") is not None]
    baseline = None
    if baselines:
        baseline = all(bool(x) for x in baselines)
    return {"verdict": verdict,
            "capture_rate": _r(caught / float(total), 4) if total else None,
            "caught": caught, "total": total, "missed": missed, "false_positive": fps,
            "baseline_pass": baseline}


def evalharness_run(suite="all", out_json=None, keep=False, min_capture=0.8):
    """Run the evaluation suites (core|assembly|reference|all) and output the verdict/suite details/capture rate plus an optional JSON dump.

    The user's scene is read-only: every test object carries the __eval_ prefix and is cleaned up at the end; scene units are restored afterwards.
    """
    t0 = time.perf_counter()
    suites_req, serr = _norm_suites(suite)
    if serr:
        return _err(serr, stage="validate", allowed=list(SUITE_ORDER) + ["all"])
    mc = _num(min_capture)
    if mc is None or mc < 0.0 or mc > 1.0:
        return _err("min_capture must be a number in 0..1 (default 0.8)", stage="validate")
    present = _present()
    user_before = set(str(o.name) for o in bpy.data.objects if not str(o.name).startswith(PFX))
    prev_scale = float(bpy.context.scene.unit_settings.scale_length)
    suites = []
    kept_dirs = []
    try:
        for sid in suites_req:
            runner = SUITE_RUNNERS[sid]
            try:
                if sid == "reference":
                    r = runner(float(mc), bool(keep))
                else:
                    r = runner(float(mc))
            except Exception as e:
                import traceback
                r = {"id": sid, "state": "fail", "cases": [], "capture_rate": None,
                     "missed": [], "false_positive": 0, "baseline_pass": None,
                     "warnings": [], "errors": ["%s: %s" % (type(e).__name__, str(e)[:240])],
                     "traceback": traceback.format_exc()[-600:],
                     "dependencies": _suite_deps(sid, present), "ms": None}
            suites.append(r)
            if keep and sid == "reference":
                d = (r.get("evidence") or {}).get("tmp_dir")
                if d:
                    kept_dirs.append(d)
    finally:
        try:
            bpy.context.scene.unit_settings.scale_length = prev_scale
        except Exception:
            pass
        _purge()
    leftovers = [str(o.name) for o in bpy.data.objects if str(o.name).startswith(PFX)]
    user_after = set(str(o.name) for o in bpy.data.objects if not str(o.name).startswith(PFX))
    agg = _aggregate(suites)
    body = {"ok": True, "version": EVALHARNESS_VERSION, "suite": list(suites_req),
            "verdict": agg["verdict"],
            "capture_rate": agg["capture_rate"], "caught": agg["caught"], "total": agg["total"],
            "missed": agg["missed"], "false_positive": agg["false_positive"],
            "baseline_pass": agg["baseline_pass"],
            "suites": suites,
            "modules": present,
            "modules_missing": [k for k, v in present.items() if not v],
            "min_capture": _r(mc, 4),
            "out_json": None,
            "kept_dirs": kept_dirs if keep else [],
            "scene": {"user_objects_before": len(user_before), "user_objects_after": len(user_after),
                      "user_scene_unchanged": bool(user_before == user_after),
                      "eval_leftovers": leftovers,
                      "scene_clean": bool(not leftovers and user_before == user_after)},
            "verdict_line": "evaluation %s (capture_rate=%s missed=%d fp=%d baseline=%s)"
                            % (agg["verdict"], agg["capture_rate"], len(agg["missed"]),
                               agg["false_positive"], agg["baseline_pass"]),
            "note": ("degraded = some suite was skipped/degraded or a dependency is missing; this is not a pass; "
                     "fail = a suite assertion failed, or the gate misfired and the baseline did not pass. Read the verdict first, then the per-suite cases."),
            "honest_limits": [
                "capture_rate is the detection rate over **this base's synthetic defect set**, not a real project's acceptance rate",
                "assembly suite geometry is synthetic with 1 unit=1mm; a real model's face counts/topology differences will change the results",
                "reference suite judges bbox/px_per_mm/readability; photographs (perspective/lighting/weak contrast) are outside its coverage",
                "core suite relies on calib's 8-class defect set; when gate dependencies such as printcheck are missing it only reports degraded numbers",
                "The user's scene is only guaranteed to be untouched by this base (test objects carry the __eval_ prefix and are cleaned up, with units restored)",
            ]}
    if out_json:
        try:
            p = _win(out_json)
            d = os.path.dirname(p)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            payload = dict(body)
            payload["scene"] = body["scene"]
            payload["out_json"] = {"path": p, "md5": None}
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            md5 = _sha256_file(p)
            body["out_json"] = {"path": p, "md5": md5,
                                "bytes": (os.path.getsize(p) if os.path.isfile(p) else None)}
        except Exception as e:
            return _err("writing out_json failed: %s: %s" % (type(e).__name__, str(e)[:200]),
                        stage="out_json", verdict=agg["verdict"], suites=suites)
    return _j(_receipt(body, t0))


# ────────────────────────────── selftest / help ──────────────────────────────
def evalharness_selftest():
    """Fast in-module self-test: run the assembly suite once (when the assembly layer is present) → assert capture rate/JSON/bad arguments."""
    ev = {}
    t0 = time.perf_counter()
    present = _present()
    try:
        if present.get("assembly"):
            r = json.loads(evalharness_run(suite="assembly"))
            ev["assembly_ok"] = bool(r.get("ok"))
            ev["assembly_capture_ge_08"] = (r.get("capture_rate") or 0.0) >= 0.8
            ev["json_serializable"] = bool(json.dumps(r, ensure_ascii=False))
            ev["scene_clean"] = bool((r.get("scene") or {}).get("scene_clean"))
            ev["bad_suite_okfalse"] = json.loads(evalharness_run(suite="nope")).get("ok") is False
            ev["bad_min_capture_okfalse"] = json.loads(
                evalharness_run(suite="assembly", min_capture=2.0)).get("ok") is False
        else:
            ev["assembly_skipped"] = True
        ok = all(v is True for v in ev.values())
        return _j({"ok": bool(ok), "version": EVALHARNESS_VERSION, "evidence": ev,
                   "present": present, "ms": int((time.perf_counter() - t0) * 1000)})
    except Exception as e:
        import traceback
        return _j({"ok": False, "version": EVALHARNESS_VERSION, "evidence": ev,
                   "error": "%s: %s" % (type(e).__name__, str(e)[:240]),
                   "traceback": traceback.format_exc()[-600:]})


def evalharness_help():
    return _j({
        "module": "evalharness.py", "version": EVALHARNESS_VERSION,
        "what": "Evaluation base: synthetic defect injection (assembly) + synthetic reference-image replay (reference) + gate baseline (calib core) "
                "→ verdict/capture_rate/missed/false_positive/baseline_pass/out_json",
        "ops": {
            "run": {"sig": "suite='all'|core,assembly,reference (comma-combinable), out_json?, keep=false, "
                           "min_capture=0.8",
                    "out": "verdict(pass|fail|degraded) + suites[] + capture_rate + missed + "
                           "false_positive + baseline_pass + out_json{path,md5} + ms",
                    "rules": "fail: any failure; degraded: any skipped/degraded suite or a missing dependency; all pass ⇒ pass"},
            "selftest": {"sig": "no arguments", "out": "runs the assembly suite + bad arguments give ok:false"},
            "help": {"sig": "no arguments"},
        },
        "suite_coverage": {
            "assembly": "D1 shallow clash / D3 fully contained / D4 12mm allow / D5 face contact / D7 floater / D8 inverted normals + a clean baseline",
            "reference": "rectangle (bbox/px_per_mm/probe/measure) / ring (hole diameter) / slant (principal axis) + needs_scale",
            "core": "calib's 8-class defect capture rate + a healthy baseline (needs calib[+gate/audit/printcheck])",
        },
        "deps": {"required": {"core": "calib", "assembly": "assembly", "reference": "imgtools"},
                 "meaning": "Missing required ⇒ that suite is skipped and the overall verdict is at least degraded; "
                            "missing optional ⇒ some cases cannot be confirmed and the suite is degraded"},
        "protocol": [
            "Most stable in a clean headless scene (assembly/calib create objects temporarily and clean up afterwards)",
            "Read the three-state verdict; capture_rate is the detection rate on this base's synthetic set, not a project acceptance rate",
            "The out_json dump carries suite/case details; its md5 allows cross-session comparison",
            "To compare two plugin versions: run twice with the same suite/seed and compare capture_rate + missed + false_positive",
        ],
        "honest_limits": ["A synthetic defect set is not a real project", "Photographic reference images and perspective are outside reference coverage",
                          "core depends on calib's gate configuration; with missing gate dependencies it only yields degraded numbers",
                          "Only objects with the __eval_ prefix are touched; the user's scene is left alone"],
    })


# Registration: module name evalharness (K.dsh_evalharness_api) + the task-agreed entry alias K.dsh_eval_api
_API = _KIT.register("evalharness", EVALHARNESS_VERSION, {
    "run": evalharness_run, "selftest": evalharness_selftest, "help": evalharness_help})
_KK = _kernel()
if _KK is not None:
    _KK.dsh_eval_api = _API
