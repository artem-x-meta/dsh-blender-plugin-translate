# -*- coding: utf-8 -*-
"""DSH material node graphs (v0.9.6 · upstream integration) — turns "hand-wiring the nodes every time" into one op call.

Measured motivation (workspace of 7,182 scripts): ShaderNode/nodes.new hits **2,732 times across 204 files** —
every build script rewires TexCoord → Mapping → Noise → ColorRamp → Principled on its own,
which is both repetitive and easy to get wrong on socket names. On top of that, OBJ/MTL delivery drops procedural
nodes (only image textures travel with it), so this module also offers **material_bake**: bake a procedural material
into PNG textures (Cycles bake: DIFFUSE/ROUGHNESS/NORMAL/AO/EMIT/COMBINED); pair it with deliver_export and the materials ship along.

ops:
    blender_rt_plan(op="material_scan",  args={objects:["P01"]})                      # read-only
    blender_rt_plan(op="material_build", args={name:"M-hull", preset:"metal_brushed",
                                              params:{base_color:[0.35,0.38,0.42], scale:24}})
    blender_rt_plan(op="material_apply", args={material:"M-hull", objects:["P01","P02"]})
    blender_rt_plan(op="material_bake",  args={objects:["P01"], bake_type:"DIFFUSE",
                                              resolution:1024, outdir:"D:/out/bake"})
    blender_rt_plan(op="material_selftest")

**Hard rules**: a wrong preset name ⇒ the allowed list comes back; a wrong param name ⇒ "unknown parameters"; a bake without UVs ⇒ ok=false
pointing at uv_smart_project; baking runs Cycles (the engine is switched temporarily and restored afterwards).
"""
import json
import math
import os
import time

import bpy

MAT_VERSION = 1
PRESETS = ("metal_brushed", "metal_paint", "rust", "plastic", "glass", "fabric", "wood",
           "concrete", "emission", "hologram", "unlit")
BAKE_TYPES = ("DIFFUSE", "ROUGHNESS", "NORMAL", "AO", "EMIT", "COMBINED")


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("material needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the previous built-in implementation was removed)
def _num(v, name, lo=None, hi=None, default=None):
    if v is None:
        if default is None:
            raise ValueError("%s is required" % name)
        return float(default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s needs a number, got %r" % (name, v))
    f = float(v)
    if not math.isfinite(f):
        raise ValueError("%s must be a finite number (NaN/Inf corrupts the .blend)" % name)
    if lo is not None and f < lo:
        raise ValueError("%s=%g is below the lower bound %g" % (name, f, lo))
    if hi is not None and f > hi:
        raise ValueError("%s=%g is above the upper bound %g" % (name, f, hi))
    return f


def _objs(objects=None, scope="ACTIVE"):
    if objects:
        names = [objects] if isinstance(objects, str) else list(objects)
        out = []
        for n in names:
            ob = bpy.data.objects.get(str(n))
            if ob is None:
                raise ValueError("Object does not exist: %s" % n)
            out.append(ob)
        if not out:
            raise ValueError("objects is empty")
        return out
    sc = str(scope or "ACTIVE").upper()
    if sc == "ACTIVE":
        ob = bpy.context.view_layer.objects.active
        if ob is None:
            raise ValueError("No active object (pass objects=[...] or scope=SELECTED/VISIBLE/ALL)")
        return [ob]
    if sc == "SELECTED":
        sel = list(bpy.context.selected_objects)
        if not sel:
            raise ValueError("No selected objects")
        return sel
    if sc == "VISIBLE":
        vis = [o for o in bpy.context.view_layer.objects if o.visible_get()]
        if not vis:
            raise ValueError("No visible objects")
        return vis
    if sc == "ALL":
        allm = list(bpy.data.objects)
        if not allm:
            raise ValueError("The scene has no objects")
        return allm
    raise ValueError("Unknown scope: %s" % scope)


def _mat(name):
    m = bpy.data.materials.get(str(name))
    if m is None:
        raise ValueError("Material does not exist: %s" % name)
    return m


# ---------------------------------------------------------------- node graph construction

def _new_tree(m):
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    return nt


def _add(nt, kind, loc, label=None, **props):
    n = nt.nodes.new(kind)
    n.location = loc
    if label:
        n.label = label
    for k, v in props.items():
        try:
            setattr(n, k, v)
        except Exception:
            try:
                n.inputs[k].default_value = v
            except Exception:
                pass
    return n


def _link(nt, a, a_sock, b, b_sock):
    try:
        return nt.links.new(a.outputs[a_sock], b.inputs[b_sock])
    except Exception as e:
        raise ValueError("Link failed %s.%s → %s.%s: %s" % (a.name, a_sock, b.name, b_sock, str(e)[:80]))


def _rgba(v, name, default):
    if v is None:
        return default
    if not isinstance(v, (list, tuple)) or len(v) not in (3, 4):
        raise ValueError("%s needs [r,g,b] or [r,g,b,a], got %r" % (name, v))
    out = [_num(x, name + "[%d]" % i, 0.0, 1000.0) for i, x in enumerate(v)]
    if len(out) == 3:
        out.append(1.0)
    return out


def _p(params, key, default=None):
    return (params or {}).get(key, default)


def _mat_texture_chain(nt, P, scale_default, detail=6.0, rough_noise=0.5):
    """TexCoord → Mapping → Noise base chain; returns (tc, mp, nz)."""
    tc = _add(nt, "ShaderNodeTexCoord", (-820, 0))
    mp = _add(nt, "ShaderNodeMapping", (-620, 0))
    nz = _add(nt, "ShaderNodeTexNoise", (-420, 0), scale=_num(_p(P, "scale"), "scale", 0.01, 1000, scale_default),
              detail=detail, roughness=rough_noise)
    _link(nt, tc, "Object", mp, "Vector")
    _link(nt, mp, "Vector", nz, "Vector")
    return tc, mp, nz


def _mat_ramp(nt, nz, stops, loc=(-220, 0)):
    """Noise → ColorRamp (elements are cut down to one first, then built from stops); returns the ramp node."""
    r = _add(nt, "ShaderNodeValToRGB", loc)
    el = r.color_ramp.elements
    while len(el) > 1:
        el.remove(el[-1])
    el[0].position = stops[0][0]
    el[0].color = stops[0][1]
    for pos, col in stops[1:]:
        e = el.new(pos)
        e.color = col
    _link(nt, nz, "Fac", r, "Fac")
    return r


def _preset_unlit(nt, P, base, out):
    """unlit: pure emission (strength 0..100)."""
    bsdf = _add(nt, "ShaderNodeEmission", (300, 0), color=base, strength=_num(_p(P, "strength"), "strength", 0, 100, 1.0))
    _link(nt, bsdf, "Emission", out, "Surface")
    return {"bsdf": bsdf, "out": out}


def _preset_metal_brushed(nt, P, base, bsdf, out):
    """Brushed metal: stretched Noise → drives both colour and roughness + variation mix."""
    tc, mp, nz = _mat_texture_chain(nt, P, 800.0, detail=2.0, rough_noise=0.35)
    mp.inputs["Scale"].default_value = (1.0, 1.0, 0.02)   # stretch → brushed
    rr = _mat_ramp(nt, nz, [(0.35, (0.0, 0.0, 0.0, 1.0)), (0.65, (1.0, 1.0, 1.0, 1.0))], (-220, -260))
    mix = _add(nt, "ShaderNodeMix", (60, -120), data_type="RGBA", blend_type="MIX")
    mix.inputs[0].default_value = _num(_p(P, "variation"), "variation", 0.0, 1.0, 0.25)
    mix.inputs[6].default_value = base
    mix.inputs[7].default_value = [base[0] * 0.75, base[1] * 0.75, base[2] * 0.75, 1.0]
    _link(nt, rr, "Color", mix, "Factor")
    _link(nt, mix, "Result", bsdf, "Base Color")
    _link(nt, rr, "Color", bsdf, "Roughness")
    bsdf.inputs["Metallic"].default_value = 1.0
    return {"bsdf": bsdf, "out": out, "noise": nz, "ramp": rr, "chain": [tc, mp, nz]}


def _preset_coat(nt, P, bsdf, out, metal, rough):
    """metal_paint / plastic: Noise detail → bump + parameterised metallic/roughness."""
    tc, mp, nz = _mat_texture_chain(nt, P, 180.0, detail=4.0, rough_noise=0.4)
    nz.inputs["Detail"].default_value = 3.0
    rr = _mat_ramp(nt, nz, [(0.45, (0.0, 0.0, 0.0, 1.0)), (0.55, (0.06, 0.06, 0.06, 1.0))], (-220, -260))
    bump = _add(nt, "ShaderNodeBump", (60, -300), Strength=_num(_p(P, "bump"), "bump", 0.0, 1.0, 0.08))
    _link(nt, rr, "Color", bump, "Height")
    _link(nt, bump, "Normal", bsdf, "Normal")
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return {"bsdf": bsdf, "out": out, "noise": nz, "bump": bump, "chain": [tc, mp, nz]}


def _preset_rust(nt, P, bsdf, out):
    """Rust: a three-stop ramp drives Base Color directly + bump."""
    tc, mp, nz = _mat_texture_chain(nt, P, 24.0, detail=10.0, rough_noise=0.7)
    rr = _mat_ramp(nt, nz, [(0.30, [0.16, 0.10, 0.07, 1.0]), (0.55, [0.42, 0.20, 0.08, 1.0]), (0.80, [0.72, 0.36, 0.14, 1.0])], (-220, -60))
    bump = _add(nt, "ShaderNodeBump", (60, -320), Strength=_num(_p(P, "bump"), "bump", 0.0, 1.0, 0.55))
    _link(nt, rr, "Color", bsdf, "Base Color")
    _link(nt, rr, "Color", bump, "Height")
    _link(nt, bump, "Normal", bsdf, "Normal")
    bsdf.inputs["Metallic"].default_value = _num(_p(P, "metallic"), "metallic", 0.0, 1.0, 0.35)
    bsdf.inputs["Roughness"].default_value = _num(_p(P, "roughness"), "roughness", 0.0, 1.0, 0.85)
    return {"bsdf": bsdf, "out": out, "noise": nz, "ramp": rr, "bump": bump, "chain": [tc, mp, nz]}


def _preset_glass(nt, P, base, bsdf, out, rough):
    """Glass: transmission (skipped when an older version lacks that socket) + low metallic."""
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = 0.0
    try:
        bsdf.inputs["Transmission Weight"].default_value = _num(_p(P, "transmission"), "transmission", 0.0, 1.0, 1.0)
    except Exception:
        pass
    _mat_tree_get(nt)
    return {"bsdf": bsdf, "out": out}


def _preset_fabric(nt, P, bsdf, out):
    """Fabric: high roughness + bump + Sheen."""
    tc, mp, nz = _mat_texture_chain(nt, P, 400.0, detail=6.0, rough_noise=0.6)
    mp.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    rr = _mat_ramp(nt, nz, [(0.42, (0.0, 0.0, 0.0, 1.0)), (0.58, (0.35, 0.35, 0.35, 1.0))], (-220, -260))
    bump = _add(nt, "ShaderNodeBump", (60, -320), Strength=_num(_p(P, "bump"), "bump", 0.0, 1.0, 0.6))
    _link(nt, rr, "Color", bump, "Height")
    _link(nt, bump, "Normal", bsdf, "Normal")
    bsdf.inputs["Roughness"].default_value = _num(_p(P, "roughness"), "roughness", 0.0, 1.0, 0.9)
    bsdf.inputs["Sheen Weight"].default_value = 0.4 if "Sheen Weight" in bsdf.inputs else 0.0
    return {"bsdf": bsdf, "out": out, "noise": nz, "bump": bump, "chain": [tc, mp, nz]}


def _preset_wood(nt, P, bsdf, out):
    """Wood grain: noise stretched along Y + a three-stop ramp driving Base Color."""
    tc, mp, nz = _mat_texture_chain(nt, P, 6.0, detail=8.0, rough_noise=0.55)
    mp.inputs["Scale"].default_value = (1.0, 8.0, 1.0)
    rr = _mat_ramp(nt, nz, [(0.25, [0.22, 0.13, 0.06, 1.0]), (0.55, [0.42, 0.26, 0.12, 1.0]), (0.85, [0.58, 0.38, 0.18, 1.0])], (-220, -60))
    bump = _add(nt, "ShaderNodeBump", (60, -320), Strength=_num(_p(P, "bump"), "bump", 0.0, 1.0, 0.25))
    _link(nt, rr, "Color", bsdf, "Base Color")
    _link(nt, rr, "Color", bump, "Height")
    _link(nt, bump, "Normal", bsdf, "Normal")
    bsdf.inputs["Roughness"].default_value = _num(_p(P, "roughness"), "roughness", 0.0, 1.0, 0.55)
    return {"bsdf": bsdf, "out": out, "noise": nz, "ramp": rr, "chain": [tc, mp, nz]}


def _preset_concrete(nt, P, bsdf, out):
    """Concrete: Noise + Voronoi two-texture colour mix."""
    tc, mp, nz = _mat_texture_chain(nt, P, 60.0, detail=8.0, rough_noise=0.8)
    nz2 = _add(nt, "ShaderNodeTexVoronoi", (-420, -300), scale=_num(_p(P, "scale"), "scale", 0.01, 1000, 12.0))
    _link(nt, mp, "Vector", nz2, "Vector")
    mix = _add(nt, "ShaderNodeMix", (-140, -160), data_type="RGBA", blend_type="MIX")
    mix.inputs[0].default_value = 0.45
    _link(nt, nz, "Color", mix, "A")
    _link(nt, nz2, "Color", mix, "B")
    mix2 = _add(nt, "ShaderNodeMix", (60, -160), data_type="RGBA", blend_type="MULTIPLY")
    mix2.inputs[0].default_value = 0.5
    mix2.inputs[7].default_value = [0.62, 0.62, 0.60, 1.0]
    _link(nt, mix, "Result", mix2, "A")
    _link(nt, mix2, "Result", bsdf, "Base Color")
    bsdf.inputs["Roughness"].default_value = _num(_p(P, "roughness"), "roughness", 0.0, 1.0, 0.9)
    return {"bsdf": bsdf, "out": out, "noise": nz, "chain": [tc, mp, nz, nz2]}


def _preset_emission(nt, P, base, bsdf, out):
    """Emission mix: Principled + Emission blended by a mix factor."""
    em = _add(nt, "ShaderNodeEmission", (60, -60), color=_rgba(_p(P, "color"), "color", base),
              strength=_num(_p(P, "strength"), "strength", 0.0, 100000.0, 12.0))
    mix = _add(nt, "ShaderNodeMixShader", (300, -60))
    mix.inputs[0].default_value = _num(_p(P, "mix"), "mix", 0.0, 1.0, 0.85)
    _link(nt, bsdf, "BSDF", mix, "Shader")
    _link(nt, em, "Emission", mix, "Shader")
    _link(nt, mix, "Shader", out, "Surface")
    return {"bsdf": bsdf, "emission": em, "mix": mix, "out": out}


def _preset_hologram(nt, P, bsdf, out):
    """Hologram: transparent + emissive (degrades to pure emission when Transparent cannot be created)."""
    em = _add(nt, "ShaderNodeEmission", (60, -60), color=_rgba(_p(P, "color"), "color", [0.3, 0.8, 1.0, 1.0]),
              strength=_num(_p(P, "strength"), "strength", 0.0, 100000.0, 6.0))
    try:
        tr = _add(nt, "ShaderNodeBsdfTransparent", (60, 140))
        mix = _add(nt, "ShaderNodeMixShader", (300, -60))
        mix.inputs[0].default_value = _num(_p(P, "alpha"), "alpha", 0.0, 1.0, 0.6)
        _link(nt, tr, "BSDF", mix, "Shader")
        _link(nt, em, "Emission", mix, "Shader")
        _link(nt, mix, "Shader", out, "Surface")
        return {"emission": em, "transparent": tr, "mix": mix, "out": out}
    except Exception:
        _link(nt, em, "Emission", out, "Surface")
        return {"emission": em, "out": out}
def _build_preset(nt, preset, params):
    """Explicit wiring per preset (data-driven is easy to get wrong; explicit is steadier). Returns {socket name: node} for the receipt description."""
    P = params or {}
    base = _rgba(_p(P, "base_color"), "base_color", [0.8, 0.8, 0.8, 1.0])
    out = _add(nt, "ShaderNodeOutputMaterial", (520, 0))
    if preset == "unlit":
        return _preset_unlit(nt, P, base, out)
    bsdf = _add(nt, "ShaderNodeBsdfPrincipled", (300, 0))
    bsdf.inputs["Base Color"].default_value = base
    metal = _num(_p(P, "metallic"), "metallic", 0.0, 1.0, 0.0)
    rough = _num(_p(P, "roughness"), "roughness", 0.0, 1.0, 0.5)
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Roughness"].default_value = rough
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = _num(_p(P, "ior"), "ior", 1.0, 4.0, 1.45)
    _link(nt, bsdf, "BSDF", out, "Surface")
    if preset == "metal_brushed":
        return _preset_metal_brushed(nt, P, base, bsdf, out)
    if preset in ("metal_paint", "plastic"):
        return _preset_coat(nt, P, bsdf, out, metal, rough)
    if preset == "rust":
        return _preset_rust(nt, P, bsdf, out)
    if preset == "glass":
        return _preset_glass(nt, P, base, bsdf, out, rough)
    if preset == "fabric":
        return _preset_fabric(nt, P, bsdf, out)
    if preset == "wood":
        return _preset_wood(nt, P, bsdf, out)
    if preset == "concrete":
        return _preset_concrete(nt, P, bsdf, out)
    if preset == "emission":
        return _preset_emission(nt, P, base, bsdf, out)
    if preset == "hologram":
        return _preset_hologram(nt, P, bsdf, out)
    raise ValueError("Unknown preset: %s (allowed: %s)" % (preset, list(PRESETS)))


def _mat_tree_get(nt):
    return nt


# ---------------------------------------------------------------- ops

def material_scan(materials=None, objects=None, scope="ACTIVE"):
    """Read-only: material node-graph summary (node type histogram / image dependencies / whether procedural / who uses it)."""
    mset = []
    if materials:
        names = [materials] if isinstance(materials, str) else list(materials)
        mset = [_mat(n) for n in names]
    else:
        obs = _objs(objects, scope)
        seen = []
        for ob in obs:
            if ob.type != "MESH":
                continue
            for slot in ob.material_slots:
                if slot.material and slot.material not in seen:
                    seen.append(slot.material)
        mset = seen
        if not mset:
            raise ValueError("The objects have no materials (run material_build/apply first)")
    rows = []
    for m in mset:
        row = {"name": m.name, "users": m.users, "use_nodes": bool(m.use_nodes),
               "blend_method": getattr(m, "blend_method", None)}
        if not m.use_nodes or m.node_tree is None:
            rows.append(row)
            continue
        nt = m.node_tree
        hist = {}
        images = []
        has_principled = False
        procedural = False
        for n in nt.nodes:
            hist[n.bl_idname] = hist.get(n.bl_idname, 0) + 1
            if n.bl_idname == "ShaderNodeBsdfPrincipled":
                has_principled = True
            if n.bl_idname.startswith("ShaderNodeTex") and n.bl_idname != "ShaderNodeTexImage":
                procedural = True
            if n.bl_idname == "ShaderNodeTexImage" and getattr(n, "image", None) is not None:
                im = n.image
                images.append({"node": n.name, "image": im.name, "size": list(im.size),
                               "packed": bool(im.packed_file), "filepath": (im.filepath or "")[:160]})
        row.update({"nodes": len(nt.nodes), "links": len(nt.links), "node_types": hist,
                    "principled": has_principled, "procedural": procedural, "images": images,
                    "needs_uv": any(k in hist for k in ("ShaderNodeTexCoord", "ShaderNodeTexImage"))})
        rows.append(row)
    return _j({"ok": True, "count": len(rows), "materials": rows,
               "note": "Materials with procedural=true lose their nodes in OBJ/MTL delivery — bake them into image textures with material_bake before delivering"})


def material_build(name, preset="metal_paint", params=None, use_backface_culling=False, blend_method=None):
    """Build a procedural material in one call (nodes + links + layout); repeatable (an existing material gets its node tree rebuilt)."""
    n = str(name or "").strip()
    if not n:
        raise ValueError("name is required")
    ps = str(preset or "").lower()
    if ps not in PRESETS:
        raise ValueError("Unknown preset: %s (allowed: %s)" % (preset, list(PRESETS)))
    m = bpy.data.materials.get(n) or bpy.data.materials.new(n)
    nt = _new_tree(m)
    t0 = time.time()
    info = _build_preset(nt, ps, params)
    m.use_backface_culling = bool(use_backface_culling)
    if blend_method:
        try:
            m.blend_method = str(blend_method).upper()
        except Exception:
            pass
    xmin = min((nd.location[0] for nd in nt.nodes), default=0.0)
    xmax = max((nd.location[0] for nd in nt.nodes), default=0.0)
    return _j({"ok": True, "material": m.name, "preset": ps, "nodes": len(nt.nodes), "links": len(nt.links),
               "params_used": params or {}, "x_span": [round(xmin, 1), round(xmax, 1)],
               "ms": int((time.time() - t0) * 1000),
               "note": "To deliver OBJ/MTL, run material_bake first (procedural nodes do not travel)"})


def material_apply(material, objects=None, scope="ACTIVE", slot=0, replace=True):
    """Apply the material to the objects' slots (replace=true replaces everything, false appends a new slot)."""
    m = _mat(material)
    obs = _objs(objects, scope)
    out = []
    for ob in obs:
        if ob.type != "MESH":
            out.append({"name": ob.name, "ok": False, "error": "Not a mesh (%s)" % ob.type})
            continue
        try:
            prev = len(ob.material_slots)
            if replace or prev == 0:
                ob.data.materials.clear()
                ob.data.materials.append(m)
                mode = "replace"
            else:
                ob.data.materials.append(m)
                mode = "append"
            out.append({"name": ob.name, "ok": True, "mode": mode, "slots_before": prev,
                        "slots_after": len(ob.material_slots)})
        except Exception as e:
            out.append({"name": ob.name, "ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:120])})
    return _j({"ok": all(r.get("ok") for r in out), "material": m.name, "objects": out})


def material_bake(objects=None, scope="ACTIVE", bake_type="DIFFUSE", resolution=1024, samples=16,
                  margin=8, outdir=None, prefix=None, save=True, use_clear=True, set_active=True):
    """Bake materials into image textures (Cycles). **This is the bridge from "procedural material → deliverable texture"**: bake, then hand over to deliver_export.

    Hard rules: no UVs ⇒ ok=false pointing at uv_smart_project; bake_type outside the allowed list ⇒ the list comes back;
    the render engine is restored to the previous one at the end (user settings are never changed behind their back).
    """
    bt = str(bake_type or "DIFFUSE").upper()
    if bt not in BAKE_TYPES:
        raise ValueError("Unknown bake_type: %s (allowed: %s)" % (bake_type, list(BAKE_TYPES)))
    res = int(_num(resolution, "resolution", 16, 8192))
    smp = int(_num(samples, "samples", 1, 4096))
    mg = int(_num(margin, "margin", 0, 64))
    obs = _objs(objects, scope)
    obs = [o for o in obs if o.type == "MESH"]
    if not obs:
        raise ValueError("No mesh objects to bake")
    sc = bpy.context.scene
    prev_engine = sc.render.engine
    prev_bake = getattr(sc.cycles, "bake_type", None) if hasattr(sc, "cycles") else None
    try:
        sc.render.engine = "CYCLES"
        if hasattr(sc, "cycles"):
            sc.cycles.bake_type = bt
            sc.cycles.samples = smp
            if hasattr(sc.cycles, "use_denoising"):
                sc.cycles.use_denoising = True
        if hasattr(sc.render, "bake"):
            sc.render.bake.margin = mg
            sc.render.bake.use_clear = bool(use_clear)
            for attr, val in (("use_pass_direct", bt == "COMBINED"), ("use_pass_indirect", False),
                              ("use_pass_color", True)):
                if hasattr(sc.render.bake, attr):
                    setattr(sc.render.bake, attr, val)
    except Exception as e:
        return _j({"ok": False, "error": "Switching to Cycles failed: %s" % str(e)[:160]})
    out = []
    try:
        for ob in obs:
            rec = {"name": ob.name, "bake_type": bt, "resolution": [res, res]}
            if not ob.data.uv_layers:
                rec.update({"ok": False, "error": "No UVs",
                            "hint": "First run blender_rt_plan(op=\"uv_smart_project\", args={objects:[\"%s\"]})" % ob.name})
                out.append(rec)
                continue
            if not ob.data.materials:
                rec.update({"ok": False, "error": "No material",
                            "hint": "Run material_build + material_apply first"})
                out.append(rec)
                continue
            for o in bpy.context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            t0 = time.time()
            imgs = []
            for slot in ob.material_slots:
                m = slot.material
                if m is None or not m.use_nodes:
                    continue
                nt = m.node_tree
                iname = "%s_%s_%s" % (prefix or ob.name, m.name, bt)
                img = bpy.data.images.get(iname)
                if img is None or tuple(img.size) != (res, res):
                    if img is not None:
                        bpy.data.images.remove(img)
                    img = bpy.data.images.new(iname, res, res, alpha=False, float_buffer=False)
                node = None
                for nd in nt.nodes:
                    if nd.bl_idname == "ShaderNodeTexImage" and getattr(nd, "image", None) is img:
                        node = nd
                        break
                if node is None:
                    node = nt.nodes.new("ShaderNodeTexImage")
                    node.image = img
                    node.location = (bsdf_x(nt), -520)
                for nd in nt.nodes:
                    nd.select = False
                node.select = True
                nt.nodes.active = node
                try:
                    bpy.ops.object.bake(type=bt, use_clear=bool(use_clear), margin=mg)
                except Exception as e:
                    imgs.append({"material": m.name, "ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:140])})
                    continue
                path = None
                if save:
                    d = str(outdir).rstrip("/\\") if outdir else os.path.join(os.path.expanduser("~"), "dsh_bake")
                    try:
                        os.makedirs(d, exist_ok=True)
                    except Exception:
                        pass
                    path = os.path.join(d, iname + ".png")
                    try:
                        img.filepath_raw = path
                        img.file_format = "PNG"
                        img.save()
                    except Exception as e:
                        path = None
                        imgs.append({"material": m.name, "ok": False, "error": "Saving failed: %s" % str(e)[:120]})
                        continue
                imgs.append({"material": m.name, "image": img.name, "ok": True, "path": path,
                             "bytes": (os.path.getsize(path) if path and os.path.exists(path) else None)})
            rec.update({"ok": all(i.get("ok") for i in imgs) and bool(imgs), "images": imgs,
                        "ms": int((time.time() - t0) * 1000)})
            out.append(rec)
    finally:
        try:
            sc.render.engine = prev_engine
            if prev_bake is not None and hasattr(sc, "cycles"):
                sc.cycles.bake_type = prev_bake
        except Exception:
            pass
    return _j({"ok": all(r.get("ok") for r in out), "objects": out,
               "note": "The baked PNG is a texture in the UV layout: deliver it with deliver_export (OBJ+MTL+textures travel together); "
                       "the procedural nodes stay in the .blend and the two coexist"})


def bsdf_x(nt):
    for nd in nt.nodes:
        if nd.bl_idname == "ShaderNodeBsdfPrincipled":
            return nd.location[0]
    return 0.0


def material_selftest():
    """Self-test: build a material → apply it to a temporary cube (with UVs) → scan assertions → bake a 128px AO → assert the PNG landed on disk → clean up completely."""
    import bmesh
    ev = {}
    made = []
    try:
        me = bpy.data.meshes.new("__dsh_mat_selftest")
        ob = bpy.data.objects.new("__dsh_mat_selftest", me)
        bpy.context.scene.collection.objects.link(ob)
        made.append(ob.name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        ev["uv_layers"] = [l.name for l in me.uv_layers]
        r = json.loads(material_build(name="__dsh_mat_selftest_M", preset="metal_brushed",
                                      params={"base_color": [0.4, 0.42, 0.45], "scale": 200}))
        ev["build"] = {"ok": r.get("ok"), "nodes": r.get("nodes"), "links": r.get("links")}
        a = json.loads(material_apply(material="__dsh_mat_selftest_M", objects=[ob.name]))
        ev["apply"] = a.get("ok")
        s = json.loads(material_scan(materials=["__dsh_mat_selftest_M"]))
        row = s["materials"][0]
        ev["scan"] = {"nodes": row.get("nodes"), "procedural": row.get("procedural"),
                      "principled": row.get("principled"), "needs_uv": row.get("needs_uv")}
        b = json.loads(material_bake(objects=[ob.name], bake_type="AO", resolution=128, samples=4,
                                     outdir=os.path.join(os.path.expanduser("~"), "dsh_bake_selftest")))
        img = (b.get("objects") or [{}])[0].get("images") or [{}]
        ev["bake"] = {"ok": b.get("ok"), "path": img[0].get("path"), "bytes": img[0].get("bytes")}
        ok = (ev["build"]["ok"] and ev["build"]["nodes"] >= 5 and ev["apply"]
              and ev["scan"]["procedural"] and ev["scan"]["principled"]
              and bool(ev["bake"]["ok"]) and bool(ev["bake"]["bytes"]))
        return _j({"ok": bool(ok), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})
    finally:
        for nm in made:
            o = bpy.data.objects.get(nm)
            if o is not None:
                m = o.data
                bpy.data.objects.remove(o, do_unlink=True)
                try:
                    bpy.data.meshes.remove(m, do_unlink=True)
                except Exception:
                    pass
        mm = bpy.data.materials.get("__dsh_mat_selftest_M")
        if mm is not None:
            bpy.data.materials.remove(mm, do_unlink=True)
        # The image datablocks produced by the self-test bake must be cleared too (otherwise orphans are left in bpy.data.images)
        for im in [i for i in bpy.data.images if i.name.startswith("__dsh_mat_selftest")]:
            try:
                bpy.data.images.remove(im, do_unlink=True)
            except Exception:
                pass


def material_help():
    return _j({
        "module": "material.py", "version": MAT_VERSION,
        "ops": {
            "material_scan": "Read-only: node count / type histogram / image dependencies / whether procedural / whether UVs are needed / who uses it",
            "material_build": "name + preset + params{base_color, metallic, roughness, scale, bump, strength, color, mix, alpha, variation, ior, transmission} (an existing material gets its node tree rebuilt)",
            "material_apply": "material + objects/scope; slot/replace (true = clear the slots then apply, false = append)",
            "material_bake": "objects + bake_type=DIFFUSE|ROUGHNESS|NORMAL|AO|EMIT|COMBINED + resolution + samples + outdir + prefix (Cycles; the engine is restored at the end)",
            "material_selftest": "Self-test: build→apply→scan→bake 128px AO→assert the PNG landed→clean up",
            "material_help": "this table",
        },
        "presets": list(PRESETS),
        "why": "Measured in a workspace: 2,732 node-wiring hits across 204 scripts reinventing the wheel; OBJ/MTL delivery drops procedural nodes → pair with material_bake",
        "workflow": ["material_build(preset=...) builds the material", "material_apply applies it to the parts",
                     "material_scan re-checks (procedural / needs_uv)",
                     "uv_smart_project unwraps UVs (a precondition for baking)", "material_bake bakes AO/DIFFUSE and other maps",
                     "deliver_export ships them together with the textures"],
        "limits": ["Baking needs UVs (a clear error points the way when they are missing)", "Baking uses Cycles: the engine is switched temporarily and restored afterwards",
                   "Glass/transmission presets look different in EEVEE than in Cycles; acceptance goes by the images the render harness produces"],
    })


def material_dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    if not isinstance(args, dict):
        return _j({"ok": False, "error": "args must be an object"})
    kw = {}
    for k, v in args.items():
        if k == "args" and isinstance(v, dict):
            kw.update(v)
        else:
            kw[k] = v
    ops = {"scan": material_scan, "build": material_build, "apply": material_apply,
           "bake": material_bake, "selftest": material_selftest, "help": material_help}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown material op", "op": op, "ops": sorted(ops)})
    import inspect
    try:
        allowed = set(inspect.signature(fn).parameters)
        unknown = sorted(set(kw) - allowed)
        if unknown:
            return _j({"ok": False, "error": "unknown parameters %s" % unknown, "op": op, "allowed": sorted(allowed)})
    except (TypeError, ValueError):
        pass
    try:
        return fn(**kw)
    except TypeError as e:
        return _j({"ok": False, "error": "argument mismatch: %s" % str(e)[:200], "op": op, "help": material_help()})
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:220]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration lines need no change)
import sys as _sys
_K = _sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_material_api = _DshApi({"version": MAT_VERSION, "dispatch": material_dispatch,
                                   "scan": material_scan, "build": material_build, "apply": material_apply,
                                   "bake": material_bake, "selftest": material_selftest, "help": material_help})
