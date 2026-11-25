# -*- coding: utf-8 -*-
r"""Chair-backrest joint experiment -- insufficient external evidence + probe discrimination (example, fully headless and reproducible)

Problem (the scenario from issue #3):
    In the reference image the joint between the backrest and the seat is hidden by a shroud, so you cannot tell whether the backrest is
      H_attach [attached]: the backrest is a single plate pressed against the rear face of the seat (no internal tenon)
      H_insert [inserted]: the same plate + an internal tenon pushed into the seat (the external contour is exactly the same)
    The two hypotheses have identical shape in **all external views** → external evidence cannot discriminate.
    Discrimination is only possible with a **probe**: take the seat apart or hide it to look at the tenon slot (this example substitutes "hide the seat and look again", which is non-destructive).

This example proves four things in a reproducible way:
    1) A hypothesis = an allowed interval + temporarily forbidden items (not one sentence of natural language);
    2) The program searches inside the interval and scores with the **visible contour**;
    3) **Identifiable and unidentifiable must be kept apart**: external views can pin the plate's position dy to millimetre level, yet are completely insensitive to "internal tenon length"
       (the objective function is flat along that dimension → that dimension is unidentifiable);
    4) The verdict must be [unresolved + what probe is needed]; only after obtaining probe evidence do you judge supported / refuted.

Run (headless, about 3 s):
    blender -b --factory-startup --python <this file> -- <outdir>
or with the plugin:
    blender_rt_headless(preload="view", script="exec(open(<this file>).read())", outdir="D:...")

Dependencies: Blender 5.x (offscreen drawing requires gpu.init()) + numpy. With preload="view" it renders through K.dsh_view_api, otherwise it uses the built-in fallback.
"""
import bpy, json, math, os, struct, sys, time, zlib
import numpy as np

VERSION = 2
SPEC = {
    "seat": {"x": 0.45, "y": 0.45, "z": 0.05, "z0": 0.45},
    "plate": {"x": 0.45, "y": 0.03, "z": 0.50},
    "joint_y": 0.225,
    "gt": {"hypothesis": "insert", "tenon_len": 0.060, "dy": 0.010},
    "tol_ext": 220,
    "tol_probe_m": 0.010,          # probe (depth gauge) tolerance: 10 mm
}
VIEW_EXT = {"from": [-2.60, 0.00, 0.78], "look_at": [0.0, 0.16, 0.66], "width": 320, "height": 200,
            "lens": 50, "background": False, "overlays": False}
VIEW_EXT2 = {"from": [1.20, 1.20, 0.35], "look_at": [0.0, 0.28, 0.45], "width": 320, "height": 200,
             "lens": 50, "background": False, "overlays": False}
# The probe view must be on the -y side: the tenon reaches into the seat toward -y, so looking from +y it is hidden by the backrest plate (the first version fell into exactly this)
VIEW_PROBE = {"from": [0.75, -1.45, 0.31], "look_at": [0.0, 0.20, 0.465], "width": 320, "height": 200,
              "lens": 50, "background": False, "overlays": False}
OCC = {"size": [0.06, 0.30, 0.30], "center": [0.0, 0.26, 0.47]}
# Probe (non-destructive disassembly): remove the shroud sleeve + hide the seat → expose the tenon region; assembling back restores it
PROBE_HIDE = ["COMP_Seat", "OCC_Sleeve"]
PNG_MAGIC = bytes([137, 80, 78, 71, 13, 10, 26, 10])

RANGES = {
    "attach": {"dy": (0.000, 0.030), "tilt": (-2.0, 6.0), "dz": (-0.020, 0.020), "tenon_len": (0.000, 0.000)},
    "insert": {"dy": (0.000, 0.030), "tilt": (-2.0, 6.0), "dz": (-0.020, 0.020), "tenon_len": (0.030, 0.100)},
}
FORBIDDEN = ["boolean_union", "weld", "apply_transform"]
UNIDENTIFIABLE = ["tenon_len"]


def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    bpy.context.view_layer.update()


def make_box(name, size, loc):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.object
    ob.name = name
    ob.scale = size
    ob.select_set(False)
    return ob


def set_tenon(length, inner_y):
    """The tenon grows from the plate's inner face inner_y toward -y by length (length=0 → no tenon)"""
    ob = bpy.data.objects.get("HID_Tenon")
    if length <= 1e-6:
        if ob:
            ob.hide_render = True
            ob.hide_viewport = True
        return None
    if ob is None:
        ob = make_box("HID_Tenon", (0.10, 1.0, 0.06), (0, 0, 0))
    ob.hide_render = False
    ob.hide_viewport = False
    L = max(length, 1e-4)
    ob.scale = (0.10, L, 0.06)
    ob.location = (0.0, inner_y - L / 2.0, 0.465)
    bpy.context.view_layer.update()
    return ob


def place_plate(plate_back_y_face, tilt_deg, dz):
    p = SPEC["plate"]
    plate = bpy.data.objects["COMP_Backrest"]
    y_c = plate_back_y_face - p["y"] / 2.0
    z_c = SPEC["seat"]["z0"] + p["z"] / 2.0 + dz
    plate.location = (0.0, y_c, z_c)
    plate.rotation_euler = (math.radians(tilt_deg), 0.0, 0.0)
    bpy.context.view_layer.update()
    return y_c, z_c


def build_scene(hypothesis, tenon_len, dy, tilt=0.0, dz=0.0):
    if bpy.data.objects.get("COMP_Seat") is None:
        s = SPEC["seat"]
        make_box("COMP_Seat", (s["x"], s["y"], s["z"]), (0, 0, s["z0"] + s["z"] / 2))
    if bpy.data.objects.get("OCC_Sleeve") is None:
        make_box("OCC_Sleeve", OCC["size"], OCC["center"])
    if bpy.data.objects.get("COMP_Backrest") is None:
        p = SPEC["plate"]
        make_box("COMP_Backrest", (p["x"], p["y"], p["z"]), (0, 0.24, 0.70))
    inner_y = SPEC["joint_y"] + dy                     # inner face of the plate
    set_tenon(tenon_len, inner_y)
    place_plate(inner_y + SPEC["plate"]["y"], tilt, dz)
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def show_objects(names, visible):
    for n in names:
        ob = bpy.data.objects.get(n)
        if ob:
            ob.hide_render = not visible
            ob.hide_viewport = not visible
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def probe_tenon_len():
    """Probe (depth gauge): after removing the shroud sleeve and the seat, measure how many metres the backrest plate's inner face extends toward -y.
    This is "non-destructive disassembly + measurement" and is independent of rendering, so it is **not affected by pose-estimation error**."""
    from mathutils import Vector
    plate = bpy.data.objects.get("COMP_Backrest")
    if plate is None:
        return 0.0
    inner_y = plate.location.y - SPEC["plate"]["y"] / 2.0
    depth = None
    for ob in bpy.data.objects:
        if ob.type != "MESH" or ob.name in ("COMP_Backrest", "COMP_Seat", "OCC_Sleeve"):
            continue
        if ob.hide_render or ob.hide_viewport:            # hidden ones (no tenon) do not count
            continue
        ys = [(ob.matrix_world @ Vector(c)).y for c in ob.bound_box]
        m = min(ys)
        if depth is None or m < depth:
            depth = m
    if depth is None:
        return 0.0
    return round(max(0.0, inner_y - depth), 4)


def capture(spec, path):
    K = sys.modules.get("dsh_rt_kernel")
    api = getattr(K, "dsh_view_api", None) if K else None
    s = dict(spec); s["path"] = path; s["mode"] = "viewport"
    info = json.loads(api["capture"](json.dumps(s))) if api is not None else _fallback_capture(s)
    if not info.get("ok"):
        raise RuntimeError("capture failed: " + str(info))
    return path


def _fallback_capture(s):
    import gpu
    from mathutils import Vector, Matrix
    try:
        gpu.init()
    except Exception:
        pass
    area = None; win = None
    for w in bpy.context.window_manager.windows:
        for a in (w.screen.areas if w.screen else []):
            if a.type == "VIEW_3D":
                win, area = w, a; break
        if area: break
    if area is None:
        raise RuntimeError("no VIEW_3D found (the fallback path requires a 3D viewport)")
    reg = next(r for r in area.regions if r.type == "WINDOW")
    space = area.spaces.active
    frm = Vector(s["from"]); look = Vector(s["look_at"])
    d = (look - frm).normalized()
    view = (Matrix.Translation(frm) @ d.to_track_quat("-Z", "Y").to_matrix().to_4x4()).inverted()
    W = float(s["width"]); H = float(s["height"])
    hx = 36.0 / 2.0; hy = hx * (H / W)
    proj = Matrix(((s.get("lens", 50.0) / hx, 0, 0, 0), (0, s.get("lens", 50.0) / hy, 0, 0),
                   (0, 0, -1.0002, -0.20002), (0, 0, -1, 0)))
    off = gpu.types.GPUOffScreen(int(W), int(H))
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.05, 0.05, 0.05, 1.0), depth=1.0)
            off.draw_view3d(bpy.context.scene, bpy.context.view_layer, space, reg, view, proj,
                            do_color_management=True, draw_background=False)
            rgba = bytes(memoryview(off.texture_color.read()))
    finally:
        off.free()
    _write_png(s["path"], int(W), int(H), rgba)
    return {"ok": True, "mode": "fallback", "path": s["path"]}


def _chunk(t, body):
    return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 4294967295)


def _write_png(path, w, h, rgba):
    raw = bytearray(); stride = w * 4
    for y in range(h - 1, -1, -1):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    png = (PNG_MAGIC + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def read_mask(path, thresh=0.16):
    d = open(path, "rb").read()
    pos = 8; idat = b""; w = h = None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]; typ = d[pos + 4:pos + 8]
        body = d[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _, ct, _, _, _ = struct.unpack(">IIBBBBB", body)
            assert ct == 6
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = zlib.decompress(idat); stride = w * 4
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        base = y * (stride + 1)
        assert raw[base] == 0
        px = np.frombuffer(raw[base + 1: base + 1 + stride], dtype=np.uint8).reshape(w, 4)
        out[y] = (px[:, :3].mean(axis=1).astype(np.float32) / 255.0) > thresh
    return out


def diff_px(a, b):
    return int(np.logical_xor(a, b).sum())


def grid(rng, ns=(5, 3, 3), tenon_n=4):
    dys = np.linspace(rng["dy"][0], rng["dy"][1], ns[0])
    tls = np.linspace(rng["tilt"][0], rng["tilt"][1], ns[1])
    dzs = np.linspace(rng["dz"][0], rng["dz"][1], ns[2])
    tns = np.linspace(rng["tenon_len"][0], rng["tenon_len"][1], tenon_n)
    out = []
    for a in dys:
        for t in tls:
            for z in dzs:
                for n in tns:
                    out.append({"dy": round(float(a), 4), "tilt": round(float(t), 2),
                                "dz": round(float(z), 4), "tenon_len": round(float(n), 4)})
    return out


def run():
    t0 = time.time()
    outdir = None
    if "--" in sys.argv:
        rest = sys.argv[sys.argv.index("--") + 1:]
        for i, a in enumerate(rest):
            if a == "--out" and i + 1 < len(rest):
                outdir = rest[i + 1]
    if not outdir:
        rest = [a for a in sys.argv[1:] if not a.startswith("-")]
        outdir = rest[-1] if rest else os.path.join(os.path.expanduser("~"), "chair_backrest_out")
    os.makedirs(outdir, exist_ok=True)
    res = {"version": VERSION, "spec": SPEC, "ranges": RANGES, "forbidden": FORBIDDEN,
           "unidentifiable_from_external_views": UNIDENTIFIABLE,
           "views": {"external_side": VIEW_EXT, "external_rear": VIEW_EXT2, "probe": VIEW_PROBE},
           "outdir": outdir}

    clean_scene()
    gt = SPEC["gt"]
    build_scene(gt["hypothesis"], gt["tenon_len"], gt["dy"])
    ext1 = os.path.join(outdir, "gt_external_side.png")
    ext2 = os.path.join(outdir, "gt_external_rear.png")
    capture(VIEW_EXT, ext1)
    capture(VIEW_EXT2, ext2)
    m_gt_ext1 = read_mask(ext1)
    m_gt_ext2 = read_mask(ext2)
    show_objects(PROBE_HIDE, False)
    probe = os.path.join(outdir, "gt_probe_no_seat.png")
    capture(VIEW_PROBE, probe)
    m_gt_probe = read_mask(probe)
    gt_probe_len = probe_tenon_len()          # ground-truth reading (simulating "take it apart and measure it with a depth gauge")
    show_objects(PROBE_HIDE, True)
    res["evidence"] = {"external_side_px": int(m_gt_ext1.sum()), "external_rear_px": int(m_gt_ext2.sum()),
                       "probe_px": int(m_gt_probe.sum()), "gt_probe_tenon_len_m": gt_probe_len,
                       "files": [os.path.basename(ext1), os.path.basename(ext2), os.path.basename(probe)]}

    hyp = {}
    for name in ("attach", "insert"):
        rng = RANGES[name]
        samples = grid(rng, ns=(4, 2, 2), tenon_n=3)
        best = None
        flat = []
        for p in samples:
            build_scene(name, p["tenon_len"], p["dy"], p["tilt"], p["dz"])
            shot = os.path.join(outdir, "cand_%s.png" % name)
            capture(VIEW_EXT, shot)
            e1 = diff_px(read_mask(shot), m_gt_ext1)
            shot2 = os.path.join(outdir, "cand_%s_rear.png" % name)
            capture(VIEW_EXT2, shot2)
            e2 = diff_px(read_mask(shot2), m_gt_ext2)
            err = e1 + e2
            flat.append({"dy": p["dy"], "tilt": p["tilt"], "dz": p["dz"],
                         "tenon_len": p["tenon_len"], "err_ext": err})
            if best is None or err < best["err_ext"]:
                best = dict(p); best["err_ext"] = err; best["err_side"] = e1; best["err_rear"] = e2
        build_scene(name, best["tenon_len"], best["dy"], best["tilt"], best["dz"])
        show_objects(PROBE_HIDE, False)
        ps = os.path.join(outdir, "best_%s_probe.png" % name)
        capture(VIEW_PROBE, ps)
        best["err_probe"] = diff_px(read_mask(ps), m_gt_probe)
        best["shot_probe"] = ps
        show_objects(PROBE_HIDE, True)
        ident = {}
        for param in ("dy", "tilt", "dz", "tenon_len"):
            byv = {}
            for r in flat:
                byv.setdefault(r[param], []).append(r["err_ext"])
            mins = {k: min(v) for k, v in sorted(byv.items())}
            ident[param] = {"min_err_by_value": mins,
                            "range": max(mins.values()) - min(mins.values())}
        # ---- Stage B (probe): external views have already pinned the outer pose, so the probe answers only one question, the "internal" one
        #      => fix the best pose from stage A and search only within that hypothesis's tenon-length range (new evidence → re-identify)
        best_p = None
        tns = np.linspace(rng["tenon_len"][0], rng["tenon_len"][1], 5) if rng["tenon_len"][1] > rng["tenon_len"][0] else [rng["tenon_len"][0]]
        for tl in tns:
            build_scene(name, float(tl), best["dy"], best["tilt"], best["dz"])
            show_objects(PROBE_HIDE, False)
            measured = probe_tenon_len()                       # depth-gauge reading
            if best_p is None or abs(measured - gt_probe_len) < abs(best_p["measured_tenon_len"] - gt_probe_len):
                shotp = os.path.join(outdir, "probe_cand_%s.png" % name)
                capture(VIEW_PROBE, shotp)
                best_p = {"dy": best["dy"], "tilt": best["tilt"], "dz": best["dz"],
                          "tenon_len": round(float(tl), 4), "measured_tenon_len": measured,
                          "err_probe_m": round(abs(measured - gt_probe_len), 4), "probe_shot": shotp}
            show_objects(PROBE_HIDE, True)
        hyp[name] = {"range": rng, "best": best, "candidates_tried": len(samples),
                     "identifiability": ident, "probe_shot": ps,
                     "best_probe": best_p, "probe_candidates_tried": len(list(tns))}

    for name, h in hyp.items():
        b = h["best"]
        if b["err_ext"] > SPEC["tol_ext"]:
            h["verdict_ext"] = "refuted"
            h["why_ext"] = "under external evidence no parameter reaches tolerance (best=%d > %d)" % (b["err_ext"], SPEC["tol_ext"])
        else:
            h["verdict_ext"] = "unresolved"
            h["why_ext"] = ("external evidence is satisfiable (best=%d <= %d), but %s is unidentifiable from external views → a probe is required"
                            % (b["err_ext"], SPEC["tol_ext"], ", ".join(UNIDENTIFIABLE)))
        bp = h["best_probe"]
        h["verdict_probe"] = "supported" if bp["err_probe_m"] <= SPEC["tol_probe_m"] else "refuted"
        h["why_probe"] = ("probe (disassembly + depth gauge): reading %.4f m, difference from ground truth %.4f m is %.4f m %s %.4f m"
                          % (bp["measured_tenon_len"], gt_probe_len, bp["err_probe_m"],
                             "<=" if bp["err_probe_m"] <= SPEC["tol_probe_m"] else ">", SPEC["tol_probe_m"]))
        idt = h["identifiability"]
        h["identifiable_params"] = sorted([k for k, v in idt.items() if v["range"] > 5 * SPEC["tol_ext"] / 10])
        h["unidentifiable_params"] = sorted([k for k, v in idt.items() if v["range"] <= 5 * SPEC["tol_ext"] / 10])

    res["hypotheses"] = hyp
    ext_ok = [k for k, v in hyp.items() if v["verdict_ext"] != "refuted"]
    probe_ok = [k for k, v in hyp.items() if v["verdict_probe"] == "supported"]
    res["stage1_external_only"] = {
        "hypotheses_not_refuted": ext_ok,
        "conclusion": ("external evidence is insufficient (" + ", ".join(ext_ok) + " are all satisfiable) → must report unresolved")
                      if len(ext_ok) > 1 else "external evidence is already sufficient to rule out the other hypotheses"
    }
    res["stage2_with_probe"] = {
        "supported": probe_ok,
        "conclusion": ("only one supported after the probe: " + ", ".join(probe_ok)) if len(probe_ok) == 1
                      else ("the probe could not discriminate: " + ", ".join(sorted(hyp)) if not probe_ok else "more than one still holds")}
    res["gt_matches_supported"] = (SPEC["gt"]["hypothesis"] in probe_ok)
    res["ms"] = int((time.time() - t0) * 1000)
    res["preload_view_api"] = bool(getattr(sys.modules.get("dsh_rt_kernel"), "dsh_view_api", None))

    with open(os.path.join(outdir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    write_report(res, os.path.join(outdir, "results.md"))
    print("HEADLESS " + json.dumps({"ok": True, "stage1": res["stage1_external_only"]["conclusion"],
                                    "stage2": res["stage2_with_probe"]["conclusion"],
                                    "gt_matches_supported": res["gt_matches_supported"],
                                    "err_ext": {k: v["best"]["err_ext"] for k, v in hyp.items()},
                                    "probe_read": {k: v["best_probe"]["measured_tenon_len"] for k, v in hyp.items()},
                                    "probe_truth": gt_probe_len,
                                    "ms": res["ms"], "outdir": outdir}, ensure_ascii=False))


def write_report(res, path):
    L = ["# Chair-backrest joint: insufficient external evidence + probe discrimination (auto-generated)", "",
         "> Stage one (external evidence only): **" + res["stage1_external_only"]["conclusion"] + "**", "",
         "> Stage two (adding probe evidence): **" + res["stage2_with_probe"]["conclusion"] + "**", "",
         "| Hypothesis | Allowed ranges | Tried | Best board parameters | External error (side+rear) | Probe reading | Difference from truth | External verdict | Probe verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res["hypotheses"].items():
        r = v["range"]; b = v["best"]
        bp = v["best_probe"]
        L.append("| %s | dy %s~%s · tilt %s~%s deg · dz %s~%s · tenon length %s~%s | %d | dy=%.3f tilt=%.1f dz=%.3f tenon=%.3f | %d | %.4f m | %.4f m | %s | %s |" % (
            k, r["dy"][0], r["dy"][1], r["tilt"][0], r["tilt"][1], r["dz"][0], r["dz"][1],
            r["tenon_len"][0], r["tenon_len"][1], v["candidates_tried"], b["dy"], b["tilt"], b["dz"],
            b["tenon_len"], b["err_ext"], bp["measured_tenon_len"], bp["err_probe_m"],
            v["verdict_ext"], v["verdict_probe"]))
    L += ["", "## Identifiability (which parameters can be pinned using external evidence only)", "",
          "| Hypothesis | Parameter | Minimum external error at each value of the parameter | Range | Identifiable? |", "|---|---|---|---|---|"]
    for k, v in res["hypotheses"].items():
        for param, idt in v["identifiability"].items():
            vals = " / ".join("%s:%d" % (kk, vv) for kk, vv in idt["min_err_by_value"].items())
            L.append("| %s | %s | %s | %d | %s |" % (
                k, param, vals, idt["range"], "no (flat)" if idt["range"] <= 5 * res["spec"]["tol_ext"] / 10 else "yes"))
    L += ["", "> A range ≈ 0 means that dimension is **unidentifiable** from external evidence: the program must say so rather than casually picking a value (in this example it is tenon_len).", "",
          "## Basis of the verdict (two plain-language sentences)", ""]
    for k, v in res["hypotheses"].items():
        L.append("- **%s**: external -- %s; probe -- %s" % (k, v["why_ext"], v["why_probe"]))
    L += ["", "## Evidence files", "",
          "| File | Content |", "|---|---|",
          "| gt_external_side.png / gt_external_rear.png | the two external ground-truth images (the joint is hidden by the shroud) |",
          "| gt_probe_no_seat.png | probe evidence: the tenon region with the seat hidden |"]
    for k in res["hypotheses"]:
        L.append("| best_%s_probe.png | the best parameters of the %s hypothesis in the probe view |" % (k, k))
    L += ["", "## Reproduction", "",
          "    blender -b --factory-startup --python docs/examples/chair-backrest/run.py -- <outdir>",
          "    # or blender_rt_headless(preload='view', script=..., outdir=...)", "",
          "## How to use the conclusion", "",
          "- When external evidence is insufficient, do not just pick between attach / insert: report unresolved and list 'what probe is needed';",
          "- Before discrimination, boolean_union / weld / apply_transform are forbidden (they destroy rollback-ability);",
          "- Only after obtaining probe evidence judge supported / refuted, and archive the evidence of both judgments together."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    run()
