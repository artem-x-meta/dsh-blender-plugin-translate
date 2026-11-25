"""DSH Blender custom viewpoint capture — no objects touched, no scene camera touched, a frame rendered from the given camera parameters.

Called through blender_rt_see {from, look_at, ...}; the API hangs off K.dsh_view_api.

What it solves:
  get_viewport_screenshot can only produce that one angle "the current user viewport" shows (changing the angle would mean changing the user viewport).
  This module uses its own view/projection matrices + GPUOffScreen.draw_view3d for offscreen drawing,
  so it can render a frame from any position/orientation/focal length **without modifying the scene or the user viewport at all**.

Math (cross-checked against a real camera, error ~1e-7, see selftest_matrices):
  view = (Translation(from) @ dir.to_track_quat('-Z','Y').to_matrix().to_4x4()).inverted()
  proj:  with AUTO the sensor follows the long edge;
         hx = sensor/2 (when the long edge is the width), hy = hx*h/w
         p00 = lens/hx, p11 = lens/hy
         this matches the bpy.types.Camera.calc_matrix_camera() output element by element.
  Orthographic likewise: p00 = 2/x_extent, p11 = 2/y_extent.

Two modes:
  viewport (default)  GPUOffScreen.draw_view3d — exactly what the user viewport renders (including shading/overlay settings), zero scene changes
  render           temporary camera + bpy.ops.render.opengl (Workbench/EEVEE quick render), fully restored afterwards
"""
import bpy, json, time, os, struct, zlib, tempfile

VIEW_VERSION = 3

# PNG byte threshold for a near-empty frame (v0.9.4): **only below it** do the three diagnostics run automatically.
# Why a threshold: measured, the diagnostics (coverage / scene_bbox / objects_in_frame) take 63 ms for 403 objects at 560px,
# 137 ms at 1120px and 488 ms at 2240px, while the actual draw + framebuffer read-back is only ~22 ms ⇒ a normal frame should not pay that every time.
# But the "aimed at nothing" warning must not be lost: a near-empty frame compresses a PNG to something tiny (measured on this machine, a frame with grid lines at 560×315 = 37,908 B),
# so the byte count serves as the mechanical criterion and a near-empty frame re-runs the diagnostics automatically → frame_looks_empty still fires.
EMPTY_PNG_BYTES = 8000

# Output defaults to Blender's own temp directory (the shared build assumes no fixed path; on a normal call the engine passes
# path = the configured workdir, so this is only a fallback).
WIN_DEFAULT = os.path.join(tempfile.gettempdir(), "dsh_view_capture.png")


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("view needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (its own former implementation has been removed)
def _kernel():
    import sys
    return sys.modules.get("dsh_rt_kernel")


# ---------------------------------------------------------------- Matrices

def make_view_matrix(frm, look_at, up=(0.0, 0.0, 1.0)):
    """Camera space → identical to cam.matrix_world.inverted() (-Z looks along the view, Y up)."""
    from mathutils import Vector, Matrix
    frm = Vector(frm[:3])
    look = Vector(look_at[:3])
    d = look - frm
    if d.length < 1e-9:
        d = Vector((0.0, -1.0, 0.0))
    d.normalize()
    q = d.to_track_quat("-Z", "Y")
    return (Matrix.Translation(frm) @ q.to_matrix().to_4x4()).inverted()


def make_proj_matrix(w, h, lens=50.0, sensor=36.0, clip_start=0.1, clip_end=1000.0,
                     sensor_fit="AUTO", ortho=False, ortho_scale=1.0, shift_x=0.0, shift_y=0.0):
    """Element-by-element identical to bpy.types.Camera.calc_matrix_camera() (landscape/portrait/ortho all cross-checked)."""
    from mathutils import Matrix
    w = float(max(1, w)); h = float(max(1, h))
    fit = ("H" if w >= h else "V") if str(sensor_fit).upper().startswith("AUTO") else str(sensor_fit)[0].upper()
    if fit == "H":
        hx = sensor / 2.0
        hy = hx * (h / w)
    else:
        hy = sensor / 2.0
        hx = hy * (w / h)
    cs = float(clip_start); ce = float(clip_end)
    if ortho:
        sx = float(ortho_scale)
        x_extent = sx if fit == "H" else sx * (w / h)
        y_extent = sx * (h / w) if fit == "H" else sx
        p00 = 2.0 / x_extent; p11 = 2.0 / y_extent
        return Matrix(((p00, 0.0, 2.0 * float(shift_x), 0.0),
                       (0.0, p11, 2.0 * float(shift_y), 0.0),
                       (0.0, 0.0, -2.0 / (ce - cs), -(ce + cs) / (ce - cs)),
                       (0.0, 0.0, 0.0, 1.0)))
    p00 = lens / hx; p11 = lens / hy
    return Matrix(((p00, 0.0, 2.0 * float(shift_x), 0.0),
                   (0.0, p11, 2.0 * float(shift_y), 0.0),
                   (0.0, 0.0, -(ce + cs) / (ce - cs), -(2.0 * ce * cs) / (ce - cs)),
                   (0.0, 0.0, -1.0, 0.0)))


# ---------------------------------------------------------------- Direct PNG writing

def write_png(path, w, h, rgba, flip=True):
    """rgba: an RGBA8 byte stream in top-row→bottom-row order (len = w*h*4).

    Why the PNG is written directly (bypassing bpy.data.images): what comes back from the GPU framebuffer are 8-bit values that are **already sRGB encoded**,
    and routing them through image.pixels (linear semantics) before saving applies gamma encoding a second time. Writing the bytes directly = WYSIWYG, and it saves one color-space guess.
    """
    raw = bytearray()
    stride = w * 4
    rng = range(h - 1, -1, -1) if flip else range(h)
    for y in rng:
        raw.append(0)  # filter type 0
        raw += rgba[y * stride:(y + 1) * stride]

    def _chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------- Viewport location

def _find_view3d(area_index=None):
    """Return (window, area, region, space_view3d); raise an explanatory error when no 3D viewport is found."""
    wm = bpy.context.window_manager
    cands = []
    for win in wm.windows:
        scr = win.screen
        if scr is None:
            continue
        for a in scr.areas:
            if a.type == "VIEW_3D":
                cands.append((win, a))
    if not cands:
        raise RuntimeError("no VIEW_3D area found: a 3D viewport has to be open in GUI mode (a background -b process cannot use it)")
    win, area = cands[0] if area_index is None else cands[min(max(0, int(area_index)), len(cands) - 1)]
    reg = next((r for r in area.regions if r.type == "WINDOW"), None)
    if reg is None:
        raise RuntimeError("the VIEW_3D area has no WINDOW sub-region")
    return win, area, reg, area.spaces.active


def _spec(spec):
    s = dict(spec or {})
    frm = s.get("from") or s.get("loc") or s.get("location") or [7.0, -7.0, 5.0]
    look = s.get("look_at") or s.get("target") or s.get("to") or [0.0, 0.0, 1.0]
    w = int(s.get("width") or (s.get("resolution") or [960, 540])[0])
    h = int(s.get("height") or (s.get("resolution") or [960, 540])[1])
    return {
        "from": [float(v) for v in frm],
        "look_at": [float(v) for v in look],
        "lens": float(s.get("lens", 50.0)),
        "sensor": float(s.get("sensor_width", s.get("sensor", 36.0))),
        "sensor_fit": str(s.get("sensor_fit", "AUTO")),
        "clip_start": float(s.get("clip_start", 0.1)),
        "clip_end": float(s.get("clip_end", 1000.0)),
        "ortho": bool(s.get("ortho", False)),
        "ortho_scale": float(s.get("ortho_scale", 10.0)),
        "shift_x": float(s.get("shift_x", 0.0)),
        "shift_y": float(s.get("shift_y", 0.0)),
        "width": max(16, min(4096, w)),
        "height": max(16, min(4096, h)),
        "mode": str(s.get("mode", "viewport")),
        "engine": str(s.get("engine", "BLENDER_WORKBENCH")),
        "shading": s.get("shading"),
        "overlays": s.get("overlays"),
        "color_management": bool(s.get("color_management", True)),
        "background": bool(s.get("background", True)),
        "path": str(s.get("path") or WIN_DEFAULT),
        "area": None if s.get("area") is None else int(s.get("area")),
        "clear": s.get("clear", [0.05, 0.05, 0.05, 1.0]),
        # v0.9.4: the three diagnostics **do not run** by default (saves 45–490 ms per call); true = force them every time
        "diagnostics": bool(s.get("diagnostics", False)),
    }


def matrices_json(spec_json):
    """Compute matrices only, no image (runs without a GUI, handy for cross-checks/debugging)."""
    s = _spec(json.loads(spec_json) if isinstance(spec_json, str) else spec_json)
    vm = make_view_matrix(s["from"], s["look_at"])
    pm = make_proj_matrix(s["width"], s["height"], s["lens"], s["sensor"], s["clip_start"], s["clip_end"],
                          s["sensor_fit"], s["ortho"], s["ortho_scale"], s["shift_x"], s["shift_y"])
    return _j({
        "ok": True, "width": s["width"], "height": s["height"], "mode": "matrices",
        "view_matrix": [[round(v, 6) for v in row] for row in vm],
        "proj_matrix": [[round(v, 6) for v in row] for row in pm],
        "spec": s,
    })


def targets():
    """List every 3D viewport (area index → whether region/shading mode is available), for picking a viewpoint."""
    out = []
    wm = bpy.context.window_manager
    i = 0
    for win in wm.windows:
        scr = win.screen
        if scr is None:
            continue
        for a in scr.areas:
            if a.type == "VIEW_3D":
                reg = next((r for r in a.regions if r.type == "WINDOW"), None)
                sp = a.spaces.active
                out.append({"index": i, "window": [win.width, win.height],
                            "area": [a.x, a.y, a.width, a.height],
                            "region": None if reg is None else [reg.x, reg.y, reg.width, reg.height],
                            "shading": getattr(sp.shading, "type", None),
                            "overlays": bool(getattr(sp.overlay, "show_overlays", False)),
                            "is_active": bool(getattr(sp, "region_3d", None) and sp.region_3d.is_perspective is not None)})
                i += 1
    return _j({"ok": True, "count": len(out), "targets": out})


# ---------------------------------------------------------------- Capture

def _capture_viewport(s):
    import gpu
    win, area, reg, space = _find_view3d(s.get("area"))
    try:
        gpu.init()  # required in background/uninitialized cases; already initialized under the GUI, ignore errors
    except Exception:
        pass
    vm = make_view_matrix(s["from"], s["look_at"])
    pm = make_proj_matrix(s["width"], s["height"], s["lens"], s["sensor"], s["clip_start"], s["clip_end"],
                          s["sensor_fit"], s["ortho"], s["ortho_scale"], s["shift_x"], s["shift_y"])
    old_shading = None
    old_overlays = None
    try:
        if s["shading"]:
            old_shading = space.shading.type
            space.shading.type = str(s["shading"]).upper()
        if s["overlays"] is not None:
            old_overlays = space.overlay.show_overlays
            space.overlay.show_overlays = bool(s["overlays"])
        off = gpu.types.GPUOffScreen(s["width"], s["height"])
        try:
            with off.bind():
                fb = gpu.state.active_framebuffer_get()
                c = s["clear"]
                fb.clear(color=(float(c[0]), float(c[1]), float(c[2]), float(c[3]) if len(c) > 3 else 1.0), depth=1.0)
                scene = getattr(win, "scene", None) or bpy.context.scene
                vl = getattr(win, "view_layer", None) or bpy.context.view_layer
                off.draw_view3d(scene, vl, space, reg, vm, pm,
                                do_color_management=bool(s["color_management"]),
                                draw_background=bool(s["background"]))
                buf = off.texture_color.read()
                rgba = bytes(memoryview(buf))
        finally:
            try:
                off.free()
            except Exception:
                pass
    finally:
        if old_shading is not None:
            try:
                space.shading.type = old_shading
            except Exception:
                pass
        if old_overlays is not None:
            try:
                space.overlay.show_overlays = old_overlays
            except Exception:
                pass
    return rgba, {"region": [reg.x, reg.y, reg.width, reg.height], "area": [area.x, area.y, area.width, area.height],
                  "shading_used": space.shading.type}


def _capture_render(s):
    """Temporary camera + viewport OpenGL render (Workbench/EEVEE quick render); restored item by item afterwards."""
    from mathutils import Vector
    scene = bpy.context.scene
    vl = bpy.context.view_layer
    cam_data = bpy.data.cameras.new("dsh_view_tmp_cam")
    cam = bpy.data.objects.new("dsh_view_tmp_cam", cam_data)
    saved = {}
    try:
        cam_data.lens = s["lens"]
        cam_data.sensor_width = s["sensor"]
        cam_data.sensor_fit = "AUTO" if s["sensor_fit"].upper().startswith("AUTO") else s["sensor_fit"].upper()
        cam_data.type = "ORTHO" if s["ortho"] else "PERSP"
        if s["ortho"]:
            cam_data.ortho_scale = s["ortho_scale"]
        cam_data.clip_start = s["clip_start"]
        cam_data.clip_end = s["clip_end"]
        cam_data.shift_x = s["shift_x"]
        cam_data.shift_y = s["shift_y"]
        cam.location = Vector(s["from"])
        cam.rotation_euler = (Vector(s["look_at"]) - Vector(s["from"])).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(cam)
        vl.update()
        r = scene.render
        saved = {"camera": scene.camera, "engine": r.engine, "rx": r.resolution_x, "ry": r.resolution_y,
                 "pct": r.resolution_percentage, "fp": r.filepath, "fmt": r.image_settings.file_format,
                 "color_mode": r.image_settings.color_mode}
        scene.camera = cam
        r.engine = s["engine"]
        r.resolution_x = s["width"]; r.resolution_y = s["height"]; r.resolution_percentage = 100
        r.filepath = s["path"]; r.image_settings.file_format = "PNG"; r.image_settings.color_mode = "RGBA"
        if s["shading"]:
            try:
                scene.display.shading.type = str(s["shading"]).upper()
            except Exception:
                pass
        bpy.ops.render.opengl(write_still=True, view_context=False)
    finally:
        try:
            if saved.get("camera") is None and scene.camera is not None:
                scene.camera = None
            elif saved.get("camera") is not None:
                scene.camera = saved["camera"]
            if saved:
                scene.render.engine = saved["engine"]
                scene.render.resolution_x = saved["rx"]; scene.render.resolution_y = saved["ry"]
                scene.render.resolution_percentage = saved["pct"]
                scene.render.filepath = saved["fp"]
                scene.render.image_settings.file_format = saved["fmt"]
                scene.render.image_settings.color_mode = saved["color_mode"]
        except Exception:
            pass
        try:
            bpy.data.objects.remove(cam, do_unlink=True)
            bpy.data.cameras.remove(cam_data)
        except Exception:
            pass
    return None, {"method": "render.opengl", "engine": s["engine"], "output": s["path"]}


# ---------------------------------------------------------------- v0.9.1 (93-D1/D2): GUI primitives + custom-viewpoint self-diagnostics

def _win_path(p):
    """Turn a WSL path into a form Blender (Windows) can use: prefer the kernel's K.win_path."""
    K = _kernel()
    try:
        if K is not None and hasattr(K, "win_path"):
            return K.win_path(str(p))
    except Exception:
        pass
    return str(p)


def _scene_bbox():
    """World bbox + longest edge of the visible meshes in the current scene (for the "aimed at nothing" self-diagnosis suggestion)."""
    from mathutils import Vector
    import numpy as np
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not (o.hide_render or o.hide_viewport)]
    if not meshes:
        return None
    pts = []
    for o in meshes:
        for c in o.bound_box:
            p = o.matrix_world @ Vector(c)
            pts.append((p.x, p.y, p.z))
    A = np.asarray(pts, dtype=float)
    mn, mx = A.min(axis=0), A.max(axis=0)
    size = mx - mn
    return {"min": [round(float(x), 4) for x in mn], "max": [round(float(x), 4) for x in mx],
            "center": [round(float(x), 4) for x in (mn + mx) / 2.0],
            "span": round(float(size.max()), 4), "objects": len(meshes)}


def _coverage(rgba, w, h, clear=None, stride=4):
    """Share of "non-background pixels" in the frame (0..1) — tells whether "the custom viewpoint aimed at nothing". Subsampled (about 1/16 of the pixels)."""
    try:
        import numpy as np
        A = np.frombuffer(rgba, dtype="uint8").reshape(h, w, 4)[::stride, ::stride, :3].astype("int16")
        if clear and len(clear) >= 3:
            ref = np.asarray([int(round(float(c) * 255.0)) for c in clear[:3]], dtype="int16")
            return float((np.abs(A - ref).max(axis=2) > 8).mean())
        flat = A.reshape(-1, 3)
        if len(flat) == 0:
            return 0.0
        uniq, cnt = np.unique(flat, axis=0, return_counts=True)
        ref = uniq[int(np.argmax(cnt))]
        return float((np.abs(flat - ref).max(axis=1) > 8).mean())
    except Exception:
        try:
            n = len(rgba) // 4
            if n == 0:
                return 0.0
            base = tuple(int(round(float(c) * 255.0)) for c in (clear or [0, 0, 0])[:3])
            step = int(max(1, stride))
            diff = total = 0
            for i in range(0, n, step):
                j = i * 4
                total += 1
                if ((rgba[j] - base[0]) ** 2 + (rgba[j + 1] - base[1]) ** 2 + (rgba[j + 2] - base[2]) ** 2) > 64:
                    diff += 1
            return diff / max(1, total)
        except Exception:
            return 0.0


def _objects_in_frame(s):
    """Project each visible object's bbox into the frame using the camera matrices: returns (in_frame_names, min_margin_px).
    More reliable than "counting non-background pixels" — with background=true the world color also counts as pixels, so raw coverage cannot tell "aimed at nothing".
    Note: mathutils.Matrix can only be multiplied by mathutils.Vector (with a numpy array it raises TypeError; the self-test caught that)."""
    from mathutils import Vector
    vm = make_view_matrix(s["from"], s["look_at"])
    pm = make_proj_matrix(s["width"], s["height"], s["lens"], s["sensor"], s["clip_start"], s["clip_end"],
                          s["sensor_fit"], s["ortho"], s["ortho_scale"], s["shift_x"], s["shift_y"])
    vpm = pm @ vm
    w, h = float(s["width"]), float(s["height"])
    names, best = [], None
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o.hide_render or o.hide_viewport:
            continue
        inside = False
        for c in o.bound_box:
            p = o.matrix_world @ Vector((c[0], c[1], c[2]))
            clip = vpm @ Vector((p.x, p.y, p.z, 1.0))
            if clip[3] <= 1e-9:
                continue                      # behind the camera
            ndc = clip.xyz / clip[3]          # mathutils: slicing [:3] degrades to a tuple; only .xyz yields a Vector
            x = (ndc[0] + 1.0) * 0.5 * w
            y = (ndc[1] + 1.0) * 0.5 * h
            if -0.1 * w <= x <= 1.1 * w and -0.1 * h <= y <= 1.1 * h:
                inside = True
                mx = min(x, w - x, y, h - y)
                best = mx if best is None else min(best, mx)
        if inside:
            names.append(o.name)
    return names, (None if best is None else round(float(best), 4))


def _empty_frame_note(cov, bbox, s, in_frame=None):
    """An actionable warning when the frame is almost empty (rather than making the user press Home themselves)."""
    empty = (in_frame is not None and len(in_frame) == 0)
    if not empty and (cov is None or cov > 0.004):
        return None
    sug = None
    if bbox:
        import math as _m
        c = bbox["center"]
        span = max(float(bbox["span"]), 1e-6)
        v = [float(s["from"][i]) - c[i] for i in range(3)]
        n = _m.sqrt(sum(x * x for x in v)) or 1.0
        d = 2.2 * span
        sug = {"look_at": c, "from": [round(c[i] + v[i] / n * d, 4) for i in range(3)], "lens": s["lens"]}
    return {"code": "frame_looks_empty", "coverage": round(float(cov or 0.0), 6), "scene_bbox": bbox, "suggest": sug,
            "objects_in_frame": list(in_frame or []),
            "why": "no visible geometry in the frame — the custom viewpoint is aimed at nothing (from/look_at are nowhere near the scene)"
                   if in_frame is not None else "almost nothing but background in the frame — the custom viewpoint is most likely aimed at nothing",
            "hint": ("Use the returned scene_bbox.center as look_at; or render once more straight from the from/look_at pair in suggest"
                     if sug else "the current scene has no visible mesh — so a custom viewpoint naturally shows only background")}


def gui_frame(object=None, area=None, all=False):
    """GUI primitive (93-D1): frame an object / the whole scene inside a real UI context (in rt_do, bpy.context.screen is None, so this is impossible there)."""
    win, ar, reg, space = _find_view3d(area)
    prev_sel = [o.name for o in bpy.context.selected_objects][:20]
    got = None
    try:
        with bpy.context.temp_override(window=win, screen=win.screen, area=ar, region=reg):
            if object:
                ob = bpy.data.objects.get(str(object))
                if ob is None:
                    return _j({"ok": False, "error": "object does not exist: %s" % object,
                               "hint": "check the names in bpy.data.objects via K first"})
                ob.select_set(True)
                bpy.context.view_layer.objects.active = ob
                bpy.ops.view3d.view_selected(use_all_regions=False)
                got = ob.name
            else:
                bpy.ops.view3d.view_all(center=bool(all))
    except Exception as e:
        import traceback
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                   "traceback": traceback.format_exc()[-500:],
                   "hint": "needs a GUI 3D viewport; a headless -b process has no UI context (use view.py's capture instead)"})
    return _j({"ok": True, "framed": got, "mode": "all" if not object else "selected",
               "area": [ar.x, ar.y, ar.width, ar.height], "prev_selected": prev_sel,
               "note": "only the viewport framing changes; scene data is untouched"})


def gui_shading(mode="SOLID", color_type=None, area=None):
    """GUI primitive (93-D1): switch viewport shading (WIREFRAME/SOLID/MATERIAL/RENDERED) + an optional color_type."""
    win, ar, reg, space = _find_view3d(area)
    before = {"shading": space.shading.type, "color_type": getattr(space.shading, "color_type", None)}
    modes = ("WIREFRAME", "SOLID", "MATERIAL", "RENDERED")
    m = str(mode).upper()
    if m not in modes:
        return _j({"ok": False, "error": "unknown shading: %s" % mode, "allowed": list(modes)})
    try:
        space.shading.type = m
        if color_type:
            space.shading.color_type = str(color_type).upper()
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
    return _j({"ok": True, "shading": space.shading.type, "color_type": getattr(space.shading, "color_type", None),
               "before": before, "note": "only the viewport display changes; render settings are untouched"})


def gui_open(path):
    """GUI primitive (93-D1): open a .blend in the GUI (⚠ replaces the current file; every old reference is invalid afterwards)."""
    if not path:
        return _j({"ok": False, "error": "path is required"})
    wp = _win_path(path)
    try:
        bpy.ops.wm.open_mainfile(filepath=wp)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "path": wp})
    return _j({"ok": True, "opened": wp, "file": bpy.data.filepath, "objects": len(bpy.data.objects),
               "warning": "open_mainfile rebuilds bpy.data: every Object/Collection/material reference obtained earlier is invalidated; fetch them again",
               "note": "this is the current file of this session; to write it to disk use bpy.ops.wm.save_as_mainfile(filepath=...) explicitly"})


def gui_help():
    return _j({"version": VIEW_VERSION,
               "ops": {"gui_frame": "object=<name>|omitted=the whole scene (view_selected / view_all in a real UI context)",
                       "gui_shading": "mode=WIREFRAME|SOLID|MATERIAL|RENDERED, color_type optional",
                       "gui_open": "path=<.blend> (⚠ replaces the current file, old references are invalidated)"},
               "why": "rt_do's execute_code context has no screen/area (measured: bpy.context.screen is None) → these three run on the plugin side in a real UI context",
               "read_only_note": "gui_frame / gui_shading only touch the viewport display; gui_open swaps the file and is a write operation"})


# ---------------------------------------------------------------- Host integration (/host/*)
#
# These three are **user-side** capabilities (a person clicks the viewport → it goes into their own message), not model tools:
# they are not in /plan's op catalog and do not change the addon (contract §0). The math reuses this file's existing
# make_view_matrix / make_proj_matrix / write_png rather than writing a second set.

# Click fallback radius (in **output image** pixels): lights/cameras/empties have no hittable surface,
# ray_cast cannot hit them, so we fall back to "how close its position in the frame is to the click point" (aligned with _PICK_RADIUS_PX in the upstream addon.py).
HOST_PICK_RADIUS_PX = 22.0


def _host_obj_brief(o):
    """Object summary in the pick receipt. Keys are fixed as name/type/detail/location (the example shape in contract §1.5)."""
    detail = str(o.type)
    if o.type == "MESH" and getattr(o, "data", None) is not None:
        try:
            detail = "MESH %dv/%df" % (len(o.data.vertices), len(o.data.polygons))
        except Exception:
            pass
    loc = o.matrix_world.translation
    return {"name": str(o.name), "type": str(o.type), "detail": detail,
            "location": [round(float(loc.x), 6), round(float(loc.y), 6), round(float(loc.z), 6)]}


def host_capture(spec_json):
    """Capture **the current GUI viewport's** frame (matrices taken straight from region_3d) and return the PNG + matrices + origin info.

    How it splits with capture():
      capture()      = "take a look from an arbitrary position" (own matrices, user viewport untouched) — used by the model side, rt_see
      host_capture() = "this frame is exactly what the user sees right now" (region_3d's own view/window matrices) — used by the host panel
    Zero scene changes, zero viewport changes (no shading/overlays/selection/camera changes); only the GPU offscreen buffer is read.

    ⚠ without the matrices it is **ok=false** (so the layer above sets pickable to false); it never fabricates a matrix set to pass itself off as pickable.
    """
    s = json.loads(spec_json) if isinstance(spec_json, str) else dict(spec_json or {})
    try:
        max_size = int(s.get("max_size") or 1000)
    except Exception:
        max_size = 1000
    max_size = max(200, min(2000, max_size))
    path = str(s.get("path") or WIN_DEFAULT)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    t0 = time.perf_counter()
    win, area, reg, space = _find_view3d(s.get("area"))
    r3d = getattr(space, "region_3d", None)
    if r3d is None:
        return _j({"ok": False, "error": "the viewport has no region_3d: camera matrices unavailable, we cannot pretend picking works"})
    src_w, src_h = int(reg.width), int(reg.height)
    if max(src_w, src_h) > max_size:
        k = float(max_size) / float(max(src_w, src_h))
        w, h = max(1, int(src_w * k)), max(1, int(src_h * k))
    else:
        w, h = src_w, src_h
    vm = r3d.view_matrix.copy()
    pm = r3d.window_matrix.copy()
    import gpu
    try:
        gpu.init()          # required in background/uninitialized cases; already initialized under the GUI, ignore errors
    except Exception:
        pass
    off = gpu.types.GPUOffScreen(w, h)
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.05, 0.05, 0.05, 1.0), depth=1.0)
            # draws exactly what the user viewport shows (do_color_management=True → write_png stores the bytes directly, no second gamma)
            off.draw_view3d(bpy.context.scene, bpy.context.view_layer, space, reg, vm, pm,
                            do_color_management=True, draw_background=True)
            rgba = bytes(memoryview(off.texture_color.read()))
    finally:
        try:
            off.free()
        except Exception:
            pass
    n = write_png(path, w, h, rgba)
    return _j({"ok": True, "path": path, "bytes": int(n), "width": int(w), "height": int(h),
               "view_matrix": [[round(float(v), 9) for v in row] for row in vm],
               "window_matrix": [[round(float(v), 9) for v in row] for row in pm],
               "file": str(bpy.data.filepath or ""), "scene": str(bpy.context.scene.name),
               "scene_count": int(len(bpy.data.scenes)),
               "region": [int(reg.x), int(reg.y), int(reg.width), int(reg.height)],
               "perspective": bool(r3d.is_perspective), "method": "region_3d/offscreen",
               "ms": int((time.perf_counter() - t0) * 1000)})


def host_pick(spec_json):
    """Click unprojection: normalized click coordinates (0..1, top-left origin, y downwards) → world ray → ray_cast hit object.

    **Discipline (contract §1.5)**: validate the file/scene mismatch first and return `*_mismatch` on a mismatch;
    never "project the click onto the current scene" — that turns one user click into one wrong operation.
    """
    s = json.loads(spec_json) if isinstance(spec_json, str) else dict(spec_json or {})
    from mathutils import Matrix, Vector
    try:
        x = min(1.0, max(0.0, float(s.get("x", 0.5))))
        y = min(1.0, max(0.0, float(s.get("y", 0.5))))
    except Exception:
        x, y = 0.5, 0.5
    exp_file = "" if s.get("file") is None else str(s.get("file"))
    exp_scene = "" if s.get("scene") is None else str(s.get("scene"))
    cur_file = str(bpy.data.filepath or "")
    cur_scene = str(bpy.context.scene.name)
    if exp_file != cur_file:
        return _j({"ok": False, "error": "file_mismatch",
                   "expected": (exp_file or None), "current": (cur_file or None)})
    if exp_scene != cur_scene:
        return _j({"ok": False, "error": "scene_mismatch",
                   "expected": (exp_scene or None), "current": (cur_scene or None)})
    try:
        vm = Matrix([[float(v) for v in row] for row in s["view_matrix"]])
        pm = Matrix([[float(v) for v in row] for row in s["window_matrix"]])
    except Exception as e:
        return _j({"ok": False, "error": "unknown_seq", "why": "matrices unavailable: %s" % str(e)[:120]})
    try:
        w = float(s.get("width") or 0.0)
        h = float(s.get("height") or 0.0)
    except Exception:
        w = h = 0.0
    if w <= 0 or h <= 0:
        return _j({"ok": False, "error": "unknown_seq", "why": "width/height missing"})
    vpm = pm @ vm
    try:
        inv = vpm.inverted()
    except Exception:
        return _j({"ok": False, "error": "unknown_seq", "why": "view@proj is not invertible"})
    ndc_x = 2.0 * x - 1.0
    ndc_y = 1.0 - 2.0 * y              # image y goes down → NDC y goes up
    p0 = inv @ Vector((ndc_x, ndc_y, -1.0, 1.0))
    p1 = inv @ Vector((ndc_x, ndc_y, 1.0, 1.0))
    if abs(p0.w) < 1e-12 or abs(p1.w) < 1e-12:
        return _j({"ok": False, "error": "unknown_seq", "why": "homogeneous w≈0"})
    p0 = p0 / p0.w
    p1 = p1 / p1.w
    origin = Vector((p0.x, p0.y, p0.z))
    direction = Vector((p1.x - p0.x, p1.y - p0.y, p1.z - p0.z))
    if direction.length < 1e-12:
        return _j({"ok": False, "error": "unknown_seq", "why": "ray direction is degenerate"})
    direction.normalize()
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    hit, loc, nrm, idx, obj, mtx = scene.ray_cast(dg, origin, direction)
    if hit and obj is not None:
        try:                              # things invisible in the viewport should not be pickable
            if obj.hide_viewport or not obj.visible_get():
                obj = None
        except Exception:
            pass
    if obj is not None:
        return _j({"ok": True, "object": _host_obj_brief(obj)})
    # fallback: lights/cameras/empties have no hittable surface, so take the nearest one by screen distance
    best, best_d = None, None
    for o in scene.objects:
        if o.type not in ("LIGHT", "CAMERA", "EMPTY", "SPEAKER", "LIGHT_PROBE"):
            continue
        try:
            if o.hide_viewport or not o.visible_get():
                continue
        except Exception:
            pass
        p = o.matrix_world.translation
        clip = vpm @ Vector((p.x, p.y, p.z, 1.0))
        if clip.w <= 1e-9:
            continue
        sx = (clip.x / clip.w + 1.0) * 0.5 * w
        sy = (1.0 - clip.y / clip.w) * 0.5 * h
        dd = ((sx - x * w) ** 2 + (sy - y * h) ** 2) ** 0.5
        if dd <= HOST_PICK_RADIUS_PX and (best_d is None or dd < best_d):
            best, best_d = o, dd
    if best is not None:
        return _j({"ok": True, "object": _host_obj_brief(best)})
    return _j({"ok": True, "object": None})


def host_scene_items(spec_json):
    """The data source for `@` mentions (contract §1.6): objects / materials / collections, sorted by name ascending (stable).

    q is a case-insensitive substring filter (empty = everything); limit takes that many of **each** kind (default 200, clamped to [1,1000]).
    Objects come from `bpy.data.objects` (not scene.objects) — the contract requires "a name usable directly in bpy.data.objects".
    """
    s = json.loads(spec_json) if isinstance(spec_json, str) else dict(spec_json or {})
    q = str(s.get("q") or "").lower()
    # convention matches clampItemsLimit on the Node side: absent/non-numeric → 200; a given number → clamped into [1,1000]
    # (an explicit limit=0 → 1, not 200; contract §1.6 says "clamped to [1,1000]")
    lim = s.get("limit")
    if lim is None or lim == "":
        limit = 200
    else:
        try:
            limit = int(lim)
        except Exception:
            limit = 200
    limit = max(1, min(1000, limit))

    def hit(name):
        return (q == "") or (q in str(name).lower())

    objects = sorted([{"name": str(o.name), "type": str(o.type)} for o in bpy.data.objects if hit(o.name)],
                     key=lambda r: r["name"])[:limit]
    materials = sorted([{"name": str(m.name)} for m in bpy.data.materials if hit(m.name)],
                       key=lambda r: r["name"])[:limit]
    collections = sorted([{"name": str(c.name)} for c in bpy.data.collections if hit(c.name)],
                         key=lambda r: r["name"])[:limit]
    return _j({"ok": True, "objects": objects, "materials": materials, "collections": collections})


def capture(spec_json):
    """Main capture entry: render one frame to a PNG from the spec and return JSON (path/size/matrices/timing)."""
    t0 = time.perf_counter()
    s = _spec(json.loads(spec_json) if isinstance(spec_json, str) else spec_json)
    path = s["path"]
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    meta = {}
    rgba = None
    mode = s["mode"].lower()
    err = None
    if mode == "viewport":
        try:
            rgba, meta = _capture_viewport(s)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            mode = "render"  # automatic fallback (e.g. no 3D viewport available)
    if rgba is None:
        rgba, meta2 = _capture_render(s)
        meta.update(meta2 or {})
        if not os.path.isfile(path):
            return _j({"ok": False, "error": err or "capture failed (neither the viewport nor the render path produced output)", "mode": mode})
        size = os.path.getsize(path)
        # v0.9.4: the original implementation called _scene_bbox() **twice in a row** here (each O(objects), ~18 ms×2 for 403 objects);
        #   now it is computed once, and likewise only when "diagnostics are explicitly requested" or for a "near-empty frame".
        need_diag_r = bool(s.get("diagnostics")) or int(size) < EMPTY_PNG_BYTES
        bbox_r = _scene_bbox() if need_diag_r else None
        return _j({"ok": True, "mode": mode, "path": path, "bytes": size,
                   "width": s["width"], "height": s["height"], "fallback_from": err,
                   "diagnostics": need_diag_r,
                   "coverage_estimate": None, "scene_bbox": bbox_r,
                   "warning": (None if bbox_r else (_empty_frame_note(0.0, None, s) if need_diag_r else None)),
                   "matrix": {"view": [[round(v, 6) for v in r] for r in make_view_matrix(s["from"], s["look_at"])],
                              "proj": [[round(v, 6) for v in r] for r in make_proj_matrix(
                                  s["width"], s["height"], s["lens"], s["sensor"], s["clip_start"], s["clip_end"],
                                  s["sensor_fit"], s["ortho"], s["ortho_scale"], s["shift_x"], s["shift_y"])]},
                   "meta": meta, "ms": int((time.perf_counter() - t0) * 1000), "spec": s})
    n = write_png(path, s["width"], s["height"], rgba)
    # ── The three diagnostics: not run by default, re-run automatically for a near-empty frame (v0.9.4)────────────────────────
    # The v0.9.1 (93-D2) self-diagnostics (coverage_estimate / scene_bbox / objects_in_frame + frame_looks_empty)
    # keep their semantics **unchanged**; they just no longer cost every time: a normal frame saves 45–490 ms, while a near-empty frame (PNG < EMPTY_PNG_BYTES)
    # or an explicit diagnostics=true from the caller still runs them in full. The buffer is already in hand, so the extra run needs no redraw.
    need_diag = bool(s.get("diagnostics")) or int(n) < EMPTY_PNG_BYTES
    if need_diag:
        cov = _coverage(rgba, s["width"], s["height"], None)   # background color is the mode (with background=true the world color counts as pixels too)
        bbox = _scene_bbox()
        try:
            in_frame, margin_px = _objects_in_frame(s)
        except Exception:
            in_frame, margin_px = None, None
        warn = _empty_frame_note(cov, bbox, s, in_frame)
    else:
        cov = bbox = in_frame = margin_px = warn = None
    return _j({"ok": True, "mode": "viewport", "path": path, "bytes": n,
               "diagnostics": need_diag,
               "width": s["width"], "height": s["height"], "fallback_from": err,
               "coverage_estimate": (None if cov is None else round(float(cov), 6)), "scene_bbox": bbox,
               "objects_in_frame": in_frame, "min_margin_px": margin_px, "warning": warn,
               "matrix": {"view": [[round(v, 6) for v in r] for r in make_view_matrix(s["from"], s["look_at"])],
                          "proj": [[round(v, 6) for v in r] for r in make_proj_matrix(
                              s["width"], s["height"], s["lens"], s["sensor"], s["clip_start"], s["clip_end"],
                              s["sensor_fit"], s["ortho"], s["ortho_scale"], s["shift_x"], s["shift_y"])]},
               "meta": meta, "ms": int((time.perf_counter() - t0) * 1000), "spec": s})


def selftest():
    """Self-test that needs no GUI: GPUOffScreen clear → read back → write the PNG directly → verify the bytes (also runs under background -b)."""
    import gpu
    out = {}
    try:
        gpu.init()
        out["gpu_init"] = "ok"
    except Exception as e:
        out["gpu_init"] = "ERR " + str(e)[:120]
    from mathutils import Vector
    cam_data = bpy.data.cameras.new("st")
    cam = bpy.data.objects.new("st", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    try:
        cam_data.lens = 50.0
        cam.location = (6.0, -4.0, 3.5)
        cam.rotation_euler = (Vector((0, 0, 1)) - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        ref = cam.calc_matrix_camera(dg, x=1920, y=1080)
        mine = make_proj_matrix(1920, 1080, 50.0, 36.0, cam_data.clip_start, cam_data.clip_end)
        out["proj_max_delta"] = max(abs(a - b) for ra, rb in zip([list(r) for r in ref], [list(r) for r in mine])
                                    for a, b in zip(ra, rb))
        vref = cam.matrix_world.inverted()
        vmine = make_view_matrix((6.0, -4.0, 3.5), (0.0, 0.0, 1.0))
        out["view_max_delta"] = max(abs(a - b) for ra, rb in zip([list(r) for r in vref], [list(r) for r in vmine])
                                    for a, b in zip(ra, rb))
        cam_data.type = "ORTHO"; cam_data.ortho_scale = 12.0
        bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        oref = cam.calc_matrix_camera(dg, x=1920, y=1080)
        omine = make_proj_matrix(1920, 1080, ortho=True, ortho_scale=12.0)
        out["ortho_max_delta"] = max(abs(a - b) for ra, rb in zip([list(r) for r in oref], [list(r) for r in omine])
                                     for a, b in zip(ra, rb))
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        bpy.data.cameras.remove(cam_data)
    W, H = 96, 54
    off = gpu.types.GPUOffScreen(W, H)
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(25 / 255.0, 153 / 255.0, 51 / 255.0, 1.0), depth=1.0)
            rgba = bytes(memoryview(off.texture_color.read()))
    finally:
        off.free()
    p = os.path.join(os.path.dirname(WIN_DEFAULT), "dsh_view_selftest.png")
    out["png_bytes"] = write_png(p, W, H, rgba)
    out["png_path"] = p
    out["first_px"] = list(rgba[:4])
    out["ok"] = (out.get("proj_max_delta", 9) < 1e-5 and out.get("view_max_delta", 9) < 1e-5
                 and out.get("ortho_max_delta", 9) < 1e-5 and out["first_px"] == [25, 153, 51, 255])
    return _j(out)


def help():
    return _j({
        "version": VIEW_VERSION,
        "capture": "capture({from, look_at, lens, ortho, ortho_scale, width, height, shading, overlays, mode, path})",
        "fields": {
            "from / look_at": "world coordinates [x,y,z] (required)",
            "lens / sensor_width": "focal length mm / sensor width mm (default 50 / 36, AUTO follows the long edge)",
            "ortho / ortho_scale": "orthographic switch and scale (follows the long edge)",
            "width / height": "output resolution (16..4096)",
            "shading": "WIREFRAME/SOLID/MATERIAL/RENDERED — temporarily switch viewport shading, restored after rendering",
            "overlays": "true/false temporarily toggles overlays (grid/axes/gizmo), restored after rendering",
            "mode": "viewport (default, zero scene changes) / render (temporary camera + render.opengl)",
            "color_management": "default true (output carries color management, WYSIWYG)",
            "background": "default true (draw the world background)",
            "path": "path of the output PNG (visible to Blender; defaults to the configured workdir, with the system temp directory as fallback)",
        },
        "others": {"matrices": "compute matrices only, no image", "targets": "list the available 3D viewports", "selftest": "no-GUI self-test",
                   "gui_frame": "GUI primitive: frame an object / the whole scene (impossible in rt_do where screen is None)",
                   "gui_shading": "GUI primitive: switch viewport shading WIREFRAME/SOLID/MATERIAL/RENDERED",
                   "gui_open": "GUI primitive: open a .blend (⚠ replaces the current file)", "gui_help": "GUI primitive quick reference",
                   "host_capture": "host panel: capture the current GUI viewport frame (region_3d matrices + PNG; zero viewport changes)",
                   "host_pick": "host panel: normalized click → ray_cast hit object (validates the file/scene mismatch first)",
                   "host_scene_items": "host panel: @ mention data source (objects/materials/collections)"},
        "diagnostics_v3": {
            "coverage_estimate": "share of non-background pixels in the frame (subsampled) — tells whether 'the custom viewpoint aimed at nothing'",
            "scene_bbox": "world bbox (center/span) of the visible meshes in the current scene — reset look_at from it when the view aimed at nothing",
            "warning": "when coverage ≤ 0.004 it returns {code:'frame_looks_empty', suggest:{from,look_at,lens}}; render once more straight from it",
            "when": "since v0.9.4 they **do not run by default** (the receipt has diagnostics=false and the three are null); "
                    "a PNG < %d bytes (near-empty frame) re-runs them automatically; spec.diagnostics=true forces a run every time. "
                    "measured saving 45 ms (empty scene) up to 488 ms (2240×1260) per call" % EMPTY_PNG_BYTES,
        },
        "notes": "viewport mode changes nothing in the scene at all (objects/camera/selection untouched); render mode adds a temporary camera, deletes it at the end and restores the render settings item by item",
    })


import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_view_api = _KIT.Api({"version": VIEW_VERSION, "capture": capture, "matrices": matrices_json,
                       "targets": targets, "selftest": selftest, "help": help,
                       "gui_frame": gui_frame, "gui_shading": gui_shading, "gui_open": gui_open,
                       "gui_help": gui_help,
                       # host integration (/host/*, user-side capabilities; contract §1): capture the current GUI viewport frame / click unprojection / @ mention data source
                       "host_capture": host_capture, "host_pick": host_pick,
                       "host_scene_items": host_scene_items,
                       # v0.9.1: the diagnostic primitives are exposed officially (private names do not leak out under preload's namespace isolation,
                       # so anything "reusable / callable by the self-test" has to hang off the API)
                       "diagnostics": {"scene_bbox": _scene_bbox, "coverage": _coverage,
                                       "objects_in_frame": _objects_in_frame,
                                       "empty_frame_note": _empty_frame_note,
                                       # v0.9.4: also expose the threshold for "when the diagnostics run automatically",
                                       # so the self-test can mechanically assert "diagnostics flag == (explicit request or byte count < threshold)"
                                       "empty_png_bytes": EMPTY_PNG_BYTES}})
