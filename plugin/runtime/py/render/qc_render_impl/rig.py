# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403

def _add_rig(az, energies):
    made = []
    for key in ("key", "fill", "rim"):
        en = float((energies or {}).get(key, 0.0) or 0.0)
        if en <= 0:
            continue
        daz, el = LIGHT_ANGLES[key]
        a = math.radians(float(az) + daz)
        e = math.radians(el)
        from_dir = Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
        ld = bpy.data.lights.new("DSH_QC_LIGHT_" + key.upper(), type="SUN")
        ld.energy = en
        try:
            ld.angle = math.radians(LIGHT_SOFT[key])
        except Exception:
            pass
        ob = bpy.data.objects.new("DSH_QC_LIGHT_" + key.upper(), ld)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = Vector((0.0, 0.0, 0.0))
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = (-from_dir).to_track_quat("-Z", "Y")
        made.append(ob)
    return made


def _aim_rig(objs, az):
    for ob in objs:
        key = ob.name.rsplit("_", 1)[-1].lower()
        daz, el = LIGHT_ANGLES.get(key, (0.0, 45.0))
        a = math.radians(float(az) + daz)
        e = math.radians(el)
        from_dir = Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
        ob.rotation_quaternion = (-from_dir).to_track_quat("-Z", "Y")


# ---------------------------------------------------------------- Read back: alpha bounding box

def _alpha_stats(path, thr=0.02):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = int(img.size[0]), int(img.size[1])
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
    finally:
        bpy.data.images.remove(img)
    a = buf.reshape(h, w, 4)[::-1, :, 3]
    m = a > float(thr)
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return {"bbox": None, "coverage": 0.0, "alpha_max": round(float(a.max()), 4), "size": [w, h]}
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    return {"bbox": [x0, y0, x1, y1], "margin_px": [x0, y0, w - 1 - x1, h - 1 - y1],
            "coverage": round(float(m.mean()), 4),
            "fill": round(float((x1 - x0 + 1) * (y1 - y0 + 1)) / float(w * h), 4),
            "alpha_max": round(float(a.max()), 4), "size": [w, h]}


# ---------------------------------------------------------------- Engine / render settings

def _set_engine(mode):
    """mode: eevee | cycles | keep. Returns (before, after) for restoration."""
    sc = bpy.context.scene
    before = sc.render.engine
    m = str(mode or "keep").lower()
    if m in ("eevee", "eevee_rt", "e"):
        try:
            sc.render.engine = "BLENDER_EEVEE"
        except Exception:
            sc.render.engine = "BLENDER_EEVEE_NEXT"
        ee = getattr(sc, "eevee", None)
        if ee is not None:
            for attr, val in (("use_raytracing", True), ("use_shadows", True)):
                if hasattr(ee, attr):
                    try:
                        setattr(ee, attr, val)
                    except Exception:
                        pass
            if hasattr(ee, "ray_tracing_method"):
                try:
                    ee.ray_tracing_method = "SCREEN"
                except Exception:
                    pass
    elif m in ("cycles", "c"):
        sc.render.engine = "CYCLES"
    return before, sc.render.engine


def _restore_engine_samples(sc, eng_engine, samp_before):
    """Write the engine/samples back and **check them item by item** (v0.9.1: even the early-return path that cannot get the render lock must do this).

    Why it is factored out: in qc_render_views `_set_engine`/`_apply_samples` run before the try,
    so an early return (e.g. lock wait timeout) never reaches finally — measured: a self-test that timed out on the lock left
    eevee.taa_render_samples at 16 instead of 64 (caught by the self-test E2 snapshot diff). Changed render settings must be restored, early-return paths included.
    """
    out = {"ok": True, "engine": None, "samples": {}, "errors": []}
    try:
        if eng_engine:
            sc.render.engine = str(eng_engine)
        out["engine"] = str(sc.render.engine)
        if eng_engine and str(sc.render.engine) != str(eng_engine):
            out["ok"] = False
            out["errors"].append("engine reads back as %r (expected %r)" % (str(sc.render.engine), str(eng_engine)))
    except Exception as e:
        out["ok"] = False
        out["errors"].append("engine: %s: %s" % (type(e).__name__, str(e)[:100]))
    ee = getattr(sc, "eevee", None)
    if ee is not None and "eevee.taa_render_samples" in (samp_before or {}):
        try:
            ee.taa_render_samples = int(samp_before["eevee.taa_render_samples"])
            out["samples"]["eevee.taa_render_samples"] = int(ee.taa_render_samples)
        except Exception as e:
            out["ok"] = False
            out["errors"].append("eevee: %s: %s" % (type(e).__name__, str(e)[:100]))
    if "cycles.samples" in (samp_before or {}):
        try:
            sc.cycles.samples = int(samp_before["cycles.samples"])
            out["samples"]["cycles.samples"] = int(sc.cycles.samples)
        except Exception as e:
            out["ok"] = False
            out["errors"].append("cycles: %s: %s" % (type(e).__name__, str(e)[:100]))
    return out


def _engine_label():
    sc = bpy.context.scene
    e = str(sc.render.engine)
    if "EEVEE" in e:
        ee = getattr(sc, "eevee", None)
        return e + ("+RT" if getattr(ee, "use_raytracing", False) else "")
    return e


def _apply_samples(n):
    sc = bpy.context.scene
    n = int(max(1, int(n)))
    done = {}
    ee = getattr(sc, "eevee", None)
    if ee is not None and hasattr(ee, "taa_render_samples"):
        done["eevee.taa_render_samples"] = int(ee.taa_render_samples)
        ee.taa_render_samples = n
    if hasattr(sc, "cycles"):
        try:
            done["cycles.samples"] = int(sc.cycles.samples)
            sc.cycles.samples = n
        except Exception:
            pass
    return done


# ---------------------------------------------------------------- v0.8.11 (B): the measured render device
# Why it exists (the original lesson from Procedura src/render/device_line.ts): Cycles **silently falls back to CPU** (the same frame ~7× slower),
# while the jsonl only had {view, ms, bytes, hash} — the reason for the slowness could not be found anywhere in the artifacts;
# on their side `_blender_gpu.py` printed "[render] device: …" explicitly, yet the layer above swallowed it with "on success, throw stdout away".
# Discipline: **read only bpy's real state; when unavailable, null + device_source**, and never guess a device model from the engine name.
# (perf.py's _gpu_setup / _pick_denoiser are "setup" semantics: they change the device; here we only read, never call them, and never modify perf.py.)

def _cycles_prefs():
    """Get the cycles preferences object → (prefs, None) or (None, reason)."""
    try:
        addon = bpy.context.preferences.addons.get("cycles")
        prefs = getattr(addon, "preferences", None) if addon else None
        if prefs is None:
            return None, "cannot get preferences.addons['cycles'].preferences (addon not enabled, or this build has no Cycles)"
        return prefs, None
    except Exception as e:
        return None, "reading cycles preferences raised: %s: %s" % (type(e).__name__, str(e)[:120])


def _cycles_device_list(prefs):
    """Measured device list [{name,type,use}] — snapshot `use` before reading and write it back as-is afterwards; never touch the user's device ticks.

    Trap (measured): prefs.devices is an **empty list** when **get_devices() has never been called** (necessarily so in a fresh -b process),
    and reading it directly yields the false conclusion "there is not a single device" — that is exactly how the silent-CPU misjudgements happen. On 5.2.2
    get_devices() does preserve the use flags, but here we still follow "snapshot first, write back after": a read leaves no side effects.
    """
    snap = {}
    try:
        for d in prefs.devices:
            snap[str(d.name)] = bool(d.use)
    except Exception:
        pass
    try:
        prefs.get_devices()
    except Exception as e:
        return None, "prefs.get_devices() failed: %s: %s" % (type(e).__name__, str(e)[:120])
    out = []
    try:
        for d in prefs.devices:
            nm = str(d.name)
            if nm in snap:
                try:
                    d.use = snap[nm]       # write back: a read must not change the user's enable state
                except Exception:
                    pass
            out.append({"name": nm, "type": str(d.type), "use": bool(d.use)})
    except Exception as e:
        return None, "iterating prefs.devices failed: %s: %s" % (type(e).__name__, str(e)[:120])
    return out, None


def _device_info():
    """Which device this render will use — {"engine","device","gpu","source","detail"}; device may be null (guessing is not allowed).

    Every device=null case is one where **the criterion really is unavailable**, and source spells out why item by item; when it is available, where the criterion comes from:
      ① CYCLES: scene.cycles.device plus the non-CPU devices with use=True in preferences['cycles'].preferences.devices.
         · device=GPU and an enabled GPU really exists → device=<device type: OPTIX/CUDA/HIP/ONEAPI/METAL>, gpu=device name;
         · device=GPU but **no GPU is enabled** → null, and source names it: "Cycles will silently fall back to CPU (≈7×)";
         · device=CPU → "CPU" (bpy does not distinguish "the user wants CPU" from "fallback after the GPU was unavailable", so CPU itself does not mean healthy);
      ② EEVEE / WORKBENCH: a GPU rasterization engine with no CPU path → device="GPU" (engine semantics, not a guessed model);
         the concrete device model is not exposed by bpy (in a background process gpu.platform needs gpu.init, which this module **does not call**, to avoid side effects).
    """
    sc = bpy.context.scene
    eng = str(getattr(sc.render, "engine", "") or "")
    info = {"engine": eng or None, "device": None, "gpu": None, "source": None, "detail": {}}
    if not eng:
        info["source"] = "unavailable: scene.render.engine is empty"
        return info
    if "CYCLES" in eng:
        c = getattr(sc, "cycles", None)
        if c is None:
            info["source"] = "unavailable: the engine is %s but scene.cycles does not exist → not guessing" % eng
            return info
        cdev = str(getattr(c, "device", "") or "")
        prefs, perr = _cycles_prefs()
        devs, derr = (None, perr) if prefs is None else _cycles_device_list(prefs)
        ctype = None
        try:
            ctype = str(prefs.compute_device_type)
        except Exception:
            ctype = None
        info["detail"] = {"cycles_device": cdev or None, "compute_device_type": ctype,
                          "devices": devs, "devices_error": derr}
        enabled = [d for d in (devs or []) if d.get("use") and str(d.get("type")) != "CPU"]
        if cdev == "GPU" and enabled:
            info["device"] = str(enabled[0]["type"])
            info["gpu"] = ", ".join(sorted(set(str(d["name"]) for d in enabled)))
            info["source"] = ("measured via bpy: scene.cycles.device=GPU, and the non-CPU devices with use=True in the preferences = %s"
                              % info["gpu"])
        elif cdev == "GPU":
            info["source"] = ("unavailable: scene.cycles.device=GPU, but no non-CPU device in the preferences has use=True"
                              " (device list read: %s) → Cycles **silently falls back to CPU** (about 7× slower, exactly the trap Procedura's "
                              "device_line is meant to catch); bpy does not report the actual backend, so device=null and no guessing"
                              % (derr or "0 enabled devices read"))
        elif cdev == "CPU":
            info["device"] = "CPU"
            info["source"] = ("measured via bpy: scene.cycles.device=CPU — note that bpy does not distinguish 'the user wants CPU' from"
                              " 'fallback after the GPU was unavailable', so device=CPU itself **does not mean healthy**")
        else:
            info["source"] = "unavailable: scene.cycles.device=%r is neither CPU nor GPU → not guessing" % cdev
        return info
    if "EEVEE" in eng or "WORKBENCH" in eng:
        info["device"] = "GPU"
        r = None
        try:
            import gpu
            r = "%s %s" % (str(gpu.platform.vendor_get()), str(gpu.platform.renderer_get()))
        except Exception as e:
            info["detail"] = {"gpu_platform_error": "%s: %s" % (type(e).__name__, str(e)[:100])}
        info["gpu"] = r
        info["source"] = (("engine semantics: %s is GPU rasterization (no CPU path) → device=GPU; the model string comes from a measured gpu.platform"
                           % eng) if r else
                          ("engine semantics: %s is GPU rasterization (no CPU path) → device=GPU; the model string is unavailable this time"
                           " (gpu.platform is unavailable in a -b process before the first render; _device_live fills it in afterwards)" % eng))
        return info
    info["source"] = "unavailable: unknown engine %s, which device it takes is unknown → null, no guessing (extend _device_info for a criterion)" % eng
    return info


def _device_slim(info):
    """The slim device block used on each jsonl line ({engine,device,gpu,source}) — the full device table is not included, or each line would be hundreds of bytes."""
    d = {"engine": info.get("engine"), "device": info.get("device"), "gpu": info.get("gpu")}
    det = info.get("detail") or {}
    for k in ("cycles_device", "compute_device_type"):
        if det.get(k) is not None:
            d[k] = det[k]
    d["source"] = info.get("source")
    return d


def _device_line(info):
    """One-line form (Procedura device_line.ts's `[render] device: …`): one grep line is enough when picking through a captured log."""
    if info.get("device") is None:
        return "[render] device: null — %s" % (info.get("source") or "unavailable")
    return "[render] device: %s%s (%s)" % (info.get("device"),
                                           (" — " + str(info["gpu"])) if info.get("gpu") else "",
                                           info.get("engine"))


def _device_live(base):
    """**Immediate read-back** after one frame is rendered (the device line in entry uses this).

    Why it cannot be measured only once before the batch: the traps we hit —
      · in a background process `gpu.platform` becomes available only **after the first render** (the GL/Vulkan context comes up then):
        measuring EEVEE before the batch can only give device=GPU/gpu=null, while after rendering the real renderer string can be filled in
        (measured: "NVIDIA Corporation NVIDIA GeForce RTX 4060 Laptop GPU/PCIe/SSE2");
      · Cycles' `scene.cycles.device` can be changed mid-batch by someone else (script/driver), so it is re-read for every frame;
        the device table reuses the in-batch snapshot (calling get_devices() per frame is pointless, and even a pure read refreshes the device list cache).
    """
    info = dict(base or {})
    info["detail"] = dict((base or {}).get("detail") or {})
    eng = str(info.get("engine") or "")
    if "EEVEE" in eng or "WORKBENCH" in eng:
        if not info.get("gpu"):
            try:
                import gpu
                info["gpu"] = "%s %s" % (str(gpu.platform.vendor_get()), str(gpu.platform.renderer_get()))
                info["source"] = ("engine semantics: %s is GPU rasterization (no CPU path) → device=GPU; the renderer string comes from "
                                  "gpu.platform measured after rendering (unavailable in a background process before the first render)" % eng)
            except Exception as e:
                info["detail"]["gpu_platform_error_after_render"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        return info
    if "CYCLES" in eng:
        try:
            now = str(bpy.context.scene.cycles.device or "")
        except Exception:
            now = None
        old = info["detail"].get("cycles_device")
        if now and now != old:
            info["detail"]["cycles_device_changed_from"] = old
            info["detail"]["cycles_device"] = now
            if now == "CPU":
                info["device"], info["gpu"] = "CPU", None
                info["source"] = ("measured: scene.cycles.device became CPU mid-batch (it was %s before the batch) → this frame was rendered on CPU;"
                                  " bpy does not distinguish 'the user wants CPU' from 'fallback after the GPU was unavailable'" % old)
            elif now == "GPU":
                devs = [d for d in (info["detail"].get("devices") or [])
                        if d.get("use") and str(d.get("type")) != "CPU"]
                if devs:
                    info["device"] = str(devs[0]["type"])
                    info["gpu"] = ", ".join(sorted(set(str(d["name"]) for d in devs)))
                    info["source"] = "measured: switched to GPU mid-batch and the enabled devices = %s" % info["gpu"]
                else:
                    info["device"], info["gpu"] = None, None
                    info["source"] = "unavailable: switched to GPU mid-batch, but the device table has no enabled non-CPU device → it will silently fall back to CPU"
        return info
    return info
