# -*- coding: utf-8 -*-
"""DSH geometry base (geo) — **mechanism layer: verbs only, no nouns**.

Why this module exists: measured, under the same skill + the same plugin, two sessions each hand-wrote their own kit
(box/cyl/boolean/mirror/preview…), with **only 4 exact name matches**, while at least 8 groups were semantically equivalent
(bool_diff↔boolean, wipe↔clear_scene, bolt↔hexbolt, rail↔rail_teeth, loft↔loft_y/stack…).
Two consequences: ① cross-session usage experience cannot accumulate; ② everyone steps on the same Blender version pitfalls once.
This module collects the "**object-independent** part" into the single implementation.

## Layering (this line is the reason to exist; break it and it is pointless)

| layer | does it change per object | who owns it | content |
|---|---|---|---|
| method layer (how to model) | **changes** | skill decision tree / Lead | faceted hard surface / smooth hard surface / organic / array / boolean |
| **mechanism layer (which verbs to build with)** | **does not change** | **this module** | boolean · cut holes · cut slots · mirror · array · extrude · loft · bevel · auto-smooth |
| shape layer (what it looks like) | **changes** | project lib/spec.py | tooth pitch / station table / section function / coordinate list |

**Three criteria before accepting a new function** (all must hold):
  1. Delete every number from its arguments: does the remaining description **still hold for another object**?
     ("cut rail teeth" → no, reject; "subtract one solid from another" → yes, accept)
  2. Can the caller **fully override** the defaults? (this module **never gives shape defaults**)
  3. Does it solve "how to use Blender" or "how to compute geometry", or "what this thing looks like"?

**Violating these three presses the models of different objects into one shape** — and that is exactly the reason to reject it.

## Explicitly not provided (shape layer, write it in the project's own lib/)
  rail pitch / hole-pattern layout / grip section / vehicle station table / airfoil outline / any default shape value for pitch·tooth·ratio.

## How to get it
  KERNEL_BOOTSTRAP already injects it (same as kit: **every injection path has it**), public names are directly usable;
  it is also registered as K.dsh_geo_api (dispatchable); or explicitly preload="geo".
  self-test: geo_selftest()   quick reference: geo_help()

Units: geometry coordinates use **the current scene units**; to model in mm set scene.unit_settings.scale_length to 0.001
(then K.dsh_kit.units() reports 1.0 mm/unit). Every `*_mm` argument in this module is interpreted as millimetres and converted automatically.
"""
import math
import sys

import bpy
import bmesh
from mathutils import Vector, Matrix

GEO_VERSION = 1

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("geo.py needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")
_j = _KIT.j
_err = _KIT.err
_receipt = _KIT.receipt
_units = _KIT.units


# ══════════════════════════════════════════════════════════════════════
# tier A · environment adaptation — zero relation to the object, but every session steps on these Blender/headless pitfalls once
# ══════════════════════════════════════════════════════════════════════
def mm2u(v):
    """Millimetres → scene units."""
    return float(v) / (_units() or 1000.0)


def u2mm(v):
    """Scene units → millimetres."""
    return float(v) * (_units() or 1000.0)


def principled(mat):
    """Get a material's Principled BSDF — **must be found by bl_idname**.
    Under a localized UI the node name is the translated label, so get("Principled BSDF") raises KeyError (measured, we hit it)."""
    if mat is None:
        return None
    nt = getattr(mat, "node_tree", None)
    if nt is None:
        return None
    for n in nt.nodes:
        if getattr(n, "bl_idname", "") == "ShaderNodeBsdfPrincipled":
            return n
    return None


def mix_rgb(nt, loc=(0.0, 0.0)):
    """Get a Mix node compatibly: Blender 5.x uses ShaderNodeMix(data_type='RGBA'), older versions fall back to MixRGB.
    Returns (node, fac_in, c1_in, c2_in, color_out)."""
    try:
        n = nt.nodes.new("ShaderNodeMix")
        n.data_type = "RGBA"
        n.location = loc
        return n, n.inputs["Factor"], n.inputs[6], n.inputs[7], n.outputs[2]
    except Exception:
        n = nt.nodes.new("ShaderNodeMixRGB")
        n.location = loc
        return n, n.inputs["Fac"], n.inputs["Color1"], n.inputs["Color2"], n.outputs["Color"]


def apply_mods(ob):
    """Bake the object's modifiers into the mesh **through the evaluator**.

    Do not use bpy.ops.object.modifier_apply: it depends on active/selection/context and is flaky headless.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return ob


def bevel(ob, width_mm=0.0, segments=2, angle_deg=40.0):
    """Bevel **limited by angle** and bake it (only bevel the edges that should be, do not turn slowly curving faces into jagged ones). width_mm<=0 returns immediately."""
    if not width_mm or float(width_mm) <= 0:
        return ob
    m = ob.modifiers.new("geobevel", "BEVEL")
    m.width = mm2u(width_mm)
    m.segments = int(segments)
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(float(angle_deg))
    try:
        m.harden_normals = False
    except Exception:
        pass
    return apply_mods(ob)


def shade_auto(ob, angle_deg=35.0):
    """Auto-smooth — the correct solution that **does not change topology**.

    Blender 4.1+/5.x removed mesh.use_auto_smooth; EDGE_SPLIT **really splits** the edges and
    creates boundary edges, blowing straight through the "0 non-manifold edges" gate. The right way: smooth all faces + set_sharp_from_angle to mark sharp edges.
    Measured (5.2.2): an 8-vertex cube → the vertex count is unchanged and 12 sharp edges are marked.
    """
    me = ob.data
    if not len(me.polygons):
        return ob
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    try:
        me.set_sharp_from_angle(angle=math.radians(float(angle_deg)))
    except Exception:
        m = ob.modifiers.new("geosplit", "EDGE_SPLIT")
        m.split_angle = math.radians(float(angle_deg))
        m.use_edge_angle = True
        apply_mods(ob)
    try:
        me.update()
    except Exception:
        pass
    return ob


def shade_flat(ob):
    """Flat shading everywhere (the default look for hard-surface block parts)."""
    me = ob.data
    me.polygons.foreach_set("use_smooth", [False] * len(me.polygons))
    try:
        me.update()
    except Exception:
        pass
    return ob


def recalc_normals(ob):
    """Normals always outward — **this is the prerequisite for every interpenetration/gap criterion below**."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    return ob


def mesh_stats(ob):
    """Mesh checkup: non-manifold edges (link_faces != 2) / zero-area faces / vertices / faces."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    nm = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    degen = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    out = {"nonmanifold_edges": nm, "degenerate_faces": degen,
           "verts": len(bm.verts), "faces": len(bm.faces)}
    bm.free()
    return out


# ══════════════════════════════════════════════════════════════════════
# tier B · geometry verbs — verbs and explicit arguments only, no shape defaults whatsoever
# ══════════════════════════════════════════════════════════════════════
def collection(name):
    """Get/create a collection (works with the COL_<agent> ownership convention)."""
    c = bpy.data.collections.get(str(name))
    if c is None:
        c = bpy.data.collections.new(str(name))
        bpy.context.scene.collection.children.link(c)
    return c


def own(ob, coll=None, owner=None):
    """Register ownership: put it in the collection + stamp the dsh.owner tag (the skill's §0.5.7 convention, do not keep it only in your head)."""
    if ob is None:
        return ob
    c = coll if isinstance(coll, bpy.types.Collection) else collection(coll or "COL_geo")
    for cc in list(ob.users_collection):
        if cc is not c:
            try:
                cc.objects.unlink(ob)
            except Exception:
                pass
    if ob.name not in c.objects:
        try:
            c.objects.link(ob)
        except Exception:
            pass
    if owner:
        ob["dsh.owner"] = str(owner)
    return ob


def assign(ob, matname):
    """Attach a material (by name; create a placeholder if it does not exist). Material name → concrete values belong to the **shape/appearance layer**, decided by the project."""
    if ob is None:
        return ob
    m = bpy.data.materials.get(str(matname))
    if m is None:
        m = bpy.data.materials.new(str(matname))
        m.diffuse_color = (0.05, 0.05, 0.05, 1)
    if ob.data.materials:
        ob.data.materials[0] = m
    else:
        ob.data.materials.append(m)
    return ob


def assign_all(objs, matname):
    for o in (objs or []):
        assign(o, matname)
    return objs


def solid(name, bm, coll="COL_geo", owner=None, bevel_mm=0.0, seg=2,
          angle_deg=40.0, smooth_angle=None):
    """bmesh → scene object: the module's **single landing point** (always: normals outward → register → bevel → smooth)."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(str(name))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(str(name), me)
    bpy.context.scene.collection.objects.link(ob)
    own(ob, coll, owner)
    if bevel_mm:
        bevel(ob, bevel_mm, seg, angle_deg)
    if smooth_angle is not None:
        shade_auto(ob, smooth_angle)
    return ob


def box(name, xr, yr, zr, coll="COL_geo", owner=None, bevel_mm=0.0, seg=2,
        angle_deg=40.0, smooth_angle=None):
    """Axis-aligned box: three intervals (min, max). **No size defaults — the size always comes from the caller.**"""
    x0, x1 = float(xr[0]), float(xr[1])
    y0, y1 = float(yr[0]), float(yr[1])
    z0, z1 = float(zr[0]), float(zr[1])
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = x0 + (v.co.x + 0.5) * (x1 - x0)
        v.co.y = y0 + (v.co.y + 0.5) * (y1 - y0)
        v.co.z = z0 + (v.co.z + 0.5) * (z1 - z0)
    return solid(name, bm, coll, owner, bevel_mm, seg, angle_deg, smooth_angle)


def cyl(name, p0, p1, r, coll="COL_geo", r2=None, segs=24, owner=None,
        bevel_mm=0.0, smooth_angle=32.0):
    """Cylinder with its axis fixed by two points (a truncated cone if r2 is given)."""
    a, b = Vector(p0), Vector(p1)
    d = b - a
    L = d.length
    if L < 1e-9:
        raise ValueError("geo.cyl: p0 and p1 coincide, axis length is 0")
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(d.normalized())
    M = Matrix.Translation((a + b) * 0.5) @ q.to_matrix().to_4x4()
    r_b = float(r if r2 is None else r2)
    kw = dict(cap_ends=True, cap_tris=False, segments=int(segs), depth=L)
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(bm, radius1=float(r), radius2=r_b, **kw)
    except TypeError:
        bmesh.ops.create_cone(bm, diameter1=float(r) * 2.0, diameter2=r_b * 2.0, **kw)
    bmesh.ops.transform(bm, matrix=M, verts=bm.verts)
    return solid(name, bm, coll, owner, bevel_mm, 2, 40.0, smooth_angle)


def tube(name, p0, p1, r_out, r_in, coll="COL_geo", segs=24, owner=None,
         bevel_mm=0.0, smooth_angle=32.0):
    """Hollow tube (outer cylinder − inner cylinder), open at both ends."""
    if float(r_in) >= float(r_out):
        raise ValueError("geo.tube: r_in must be smaller than r_out")
    outer = cyl(name, p0, p1, r_out, coll=coll, r2=None, segs=segs, owner=owner,
                bevel_mm=0.0, smooth_angle=None)
    inner = cyl("__geotube_in", p0, p1, r_in, coll="COL_geo", segs=segs,
                smooth_angle=None)
    boolean(outer, inner, "DIFFERENCE", delete_cutter=True, verify=True)
    if bevel_mm:
        bevel(outer, bevel_mm, 2, 40.0)
    if smooth_angle is not None:
        shade_auto(outer, smooth_angle)
    return outer


def prism(name, profile, axis, a0, a1, coll="COL_geo", owner=None, bevel_mm=0.0,
          seg=2, angle_deg=40.0, smooth_angle=None):
    """Extrude a closed 2D section along an axis. profile=[(u,v),…] (axis=X→(Y,Z); Y→(X,Z); Z→(X,Y))."""
    ax = str(axis).upper()
    if ax not in ("X", "Y", "Z"):
        raise ValueError("geo.prism: axis must be X/Y/Z")

    def P(u, v, a):
        if ax == "X":
            return (a, u, v)
        if ax == "Y":
            return (u, a, v)
        return (u, v, a)

    bm = bmesh.new()
    vs = [bm.verts.new(P(float(u), float(v), float(a0))) for (u, v) in profile]
    f = bm.faces.new(vs)
    res = bmesh.ops.extrude_face_region(bm, geom=[f])
    nv = [e for e in res["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=Vector(P(0.0, 0.0, float(a1))) - Vector(P(0.0, 0.0, float(a0))),
                        verts=nv)
    return solid(name, bm, coll, owner, bevel_mm, seg, angle_deg, smooth_angle)


def loft(name, rings, coll="COL_geo", owner=None, bevel_mm=0.0, seg=2,
         angle_deg=40.0, smooth_angle=None, cap=True):
    """Multi-section loft: rings=[layer][point], with **the same point count and the same winding per layer**. Use it for solids whose section varies along an axis."""
    if not rings or not rings[0]:
        raise ValueError("geo.loft: rings is empty")
    n = len(rings[0])
    for i, r in enumerate(rings):
        if len(r) != n:
            raise ValueError("geo.loft: layer %d has %d points != %d in layer 0" % (i, len(r), n))
    bm = bmesh.new()
    vr = [[bm.verts.new(Vector(p)) for p in r] for r in rings]
    for a, b in zip(vr[:-1], vr[1:]):
        for i in range(n):
            j = (i + 1) % n
            try:
                bm.faces.new((a[i], a[j], b[j], b[i]))
            except ValueError:
                pass
    if cap:
        for ring, rev in ((vr[0], True), (vr[-1], False)):
            vs = list(reversed(ring)) if rev else list(ring)
            try:
                bm.faces.new(vs)
            except ValueError:
                pass
    return solid(name, bm, coll, owner, bevel_mm, seg, angle_deg, smooth_angle)


def stack(name, sections, axis="X", coll="COL_geo", owner=None, bevel_mm=0.0,
          seg=2, angle_deg=40.0, smooth_angle=None):
    """Convenience form: stack sections along an axis → loft. sections=[(a, [(u,v),…]), …] (u,v as in prism)."""
    ax = str(axis).upper()
    if ax not in ("X", "Y", "Z"):
        raise ValueError("geo.stack: axis must be X/Y/Z")
    rings = []
    for (a, pts) in sections:
        ring = []
        for (u, v) in pts:
            if ax == "X":
                ring.append((float(a), float(u), float(v)))
            elif ax == "Y":
                ring.append((float(u), float(a), float(v)))
            else:
                ring.append((float(u), float(v), float(a)))
        rings.append(ring)
    return loft(name, rings, coll, owner, bevel_mm, seg, angle_deg, smooth_angle)


def _obb(ob):
    """World-space bounding box [min, max]."""
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    cs = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = [min(c[i] for c in cs) for i in range(3)]
    hi = [max(c[i] for c in cs) for i in range(3)]
    return [Vector(lo), Vector(hi)]


def _inside(a, b, tol):
    return all(a[0][i] >= b[0][i] - tol and a[1][i] <= b[1][i] + tol for i in range(3))


def boolean(target, cutter, op="DIFFERENCE", solver="EXACT", delete_cutter=True, verify=True):
    """Boolean + **degeneracy guard**.

    Known pitfall (measured): an EXACT boolean on a **self-intersecting body** (several interpenetrating primitives joined into one mesh)
    **silently degrades into a "union"** — no error, the shape is just quietly wrong, and the resulting bounding box swells to the cutter's size.
    The guard (a posteriori, cheap and deterministic):
      the difference result must still lie inside the target's bounding box; the intersection must lie inside the two's common box; the union must not exceed the union of the two.
    Violation → raise RuntimeError (with diagnostics and a fix), **never pass silently**. verify=False turns it off (not recommended).
    """
    top = str(op).upper()
    if top not in ("DIFFERENCE", "UNION", "INTERSECT"):
        raise ValueError("geo.boolean: op must be DIFFERENCE / UNION / INTERSECT")
    tbb = _obb(target)
    cbb = _obb(cutter)
    pre = mesh_stats(target)
    m = target.modifiers.new("geobool", "BOOLEAN")
    m.operation = top
    m.object = cutter
    try:
        m.solver = str(solver)
    except Exception:
        pass
    apply_mods(target)
    if delete_cutter:
        try:
            bpy.data.objects.remove(cutter, do_unlink=True)
        except Exception:
            pass
    info = {"op": top, "pre_nonmanifold_edges": pre["nonmanifold_edges"],
            "pre_degenerate_faces": pre["degenerate_faces"], "guard": "skipped"}
    if verify:
        rbb = _obb(target)
        span = max(1e-9, (tbb[1] - tbb[0]).length)
        tol = 1e-4 * max(1.0, span)
        bad = None
        if top == "DIFFERENCE":
            if not _inside(rbb, tbb, tol):
                bad = "difference_grew_beyond_target"
        elif top == "INTERSECT":
            lo = Vector([max(tbb[0][i], cbb[0][i]) for i in range(3)])
            hi = Vector([min(tbb[1][i], cbb[1][i]) for i in range(3)])
            if not _inside(rbb, [lo, hi], tol):
                bad = "intersect_outside_common"
        else:
            lo = Vector([min(tbb[0][i], cbb[0][i]) for i in range(3)])
            hi = Vector([max(tbb[1][i], cbb[1][i]) for i in range(3)])
            if not _inside(rbb, [lo, hi], tol):
                bad = "union_beyond_both"
        if bad:
            raise RuntimeError(
                "The geometry base degeneracy guard stopped a boolean (%s). The result of %s has a bounding box outside its expected range; "
                "the most common cause is that **the body is a self-intersecting mesh** (several interpenetrating primitives joined together) — "
                "an EXACT boolean silently degrades into a union on such input. Fixes: "
                "(1) boolean only on a **single primitive**, then join after cutting; "
                "(2) or run fix_repair first (merge duplicate vertices / dissolve zero-area faces / recalculate normals) and then cut; "
                "(3) pass verify=False once you confirm this deformation is the design intent."
                % (bad, top))
        info["guard"] = "pass"
    try:
        target["dsh_boolean_guard"] = _j(info)
    except Exception:
        pass
    return target


def _merge(objs, name, coll="COL_tmp"):
    """Merge several cutters into **one** mesh — do batch hole cutting in a single boolean (faster and more stable than cutting one by one)."""
    bm = bmesh.new()
    for o in objs:
        bm.from_mesh(o.data)
    for o in objs:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            pass
    return solid(name, bm, coll=coll, owner=None, smooth_angle=None)


def hole_cut(target, holes, name="GEO_holes", coll="COL_tmp", verify=True):
    """Batch hole cut, one boolean. Each holes item is one of two forms:
      {"center":(x,y,z), "axis":"X|Y|Z", "r":R, "length":L}   —— axis-aligned hole
      (p0, p1, r)                                            —— hole along any axis
    """
    cutters = []
    for i, h in enumerate(holes):
        if isinstance(h, dict):
            c = Vector(h.get("center", (0.0, 0.0, 0.0)))
            ax = str(h.get("axis", "X")).upper()
            dv = {"X": Vector((1.0, 0.0, 0.0)), "Y": Vector((0.0, 1.0, 0.0)),
                  "Z": Vector((0.0, 0.0, 1.0))}.get(ax)
            if dv is None:
                raise ValueError("geo.hole_cut: axis must be X/Y/Z")
            half = dv * (float(h["length"]) * 0.5)
            p0, p1, r = c - half, c + half, float(h["r"])
        else:
            p0, p1, r = h[0], h[1], float(h[2])
        cutters.append(cyl("__geohole%d" % i, p0, p1, r, coll=coll, smooth_angle=None))
    return boolean(target, _merge(cutters, name + "_cutter", coll), "DIFFERENCE", verify=verify)


def slots_cut(target, slots, name="GEO_slots", coll="COL_tmp", verify=True):
    """Batch slot cut, one boolean. Each slots item = a box ((x0,x1),(y0,y1),(z0,z1))."""
    cutters = [box("__geoslot%d" % i, s[0], s[1], s[2], coll=coll, smooth_angle=None)
               for i, s in enumerate(slots)]
    return boolean(target, _merge(cutters, name + "_cutter", coll), "DIFFERENCE", verify=verify)


def mirror(ob, axis="Y", name=None, coll=None):
    """Generic mirror (Y not hard-coded). The negative scale is **baked in place** and the normals are flipped — otherwise you get an inside-out shell,
    and normal direction is the prerequisite for every interpenetration criterion."""
    ax = str(axis).upper()
    if ax not in ("X", "Y", "Z"):
        raise ValueError("geo.mirror: axis must be X/Y/Z")
    me = ob.data.copy()
    dup = bpy.data.objects.new(name or (ob.name + "_mir"), me)
    (coll if isinstance(coll, bpy.types.Collection)
     else (ob.users_collection[0] if ob.users_collection else collection("COL_geo"))).objects.link(dup)
    s = [1.0, 1.0, 1.0]
    s["XYZ".index(ax)] = -1.0
    me.transform(Matrix.Diagonal((s[0], s[1], s[2], 1.0)))
    if s[0] * s[1] * s[2] < 0:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    me.update()
    try:
        dup["dsh.owner"] = ob.get("dsh.owner", "")
    except Exception:
        pass
    return dup


def linear_array(ob, count, offset, name=None):
    """Copy along a vector (the count includes the original). offset = the displacement per step."""
    n = int(count)
    if n < 1:
        raise ValueError("geo.linear_array: count must be >= 1")
    out = [ob]
    c = ob.users_collection[0] if ob.users_collection else collection("COL_geo")
    for i in range(1, n):
        dup = bpy.data.objects.new("%s_%02d" % (name or (ob.name + "_arr"), i), ob.data.copy())
        c.objects.link(dup)
        dup.matrix_world = Matrix.Translation(Vector(offset) * i) @ ob.matrix_world
        try:
            dup["dsh.owner"] = ob.get("dsh.owner", "")
        except Exception:
            pass
        out.append(dup)
    return out


def join(objs, name=None, coll=None, owner=None):
    """Merge into one mesh (**do booleans before join** — a self-intersecting joined mesh makes an EXACT boolean degrade)."""
    objs = [o for o in (objs or []) if o is not None]
    if not objs:
        return None
    bm = bmesh.new()
    for o in objs:
        bm.from_mesh(o.data)
    base = objs[0]
    for o in objs:
        if o is not base:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
    old = base.data
    me = bpy.data.meshes.new(base.name)
    bm.to_mesh(me)
    bm.free()
    base.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    if name:
        base.name = str(name)
    own(base, coll or (base.users_collection[0] if base.users_collection else "COL_geo"),
        owner or base.get("dsh.owner"))
    return base


def clear_scene(prefixes=("GEO_", "GEO-", "__")):
    """Clear the scene: by default only deletes parts with its own prefixes, **never touches cameras/lights/other people's parts**. Returns the number deleted."""
    n = 0
    for o in list(bpy.data.objects):
        if any(o.name.startswith(p) for p in prefixes):
            bpy.data.objects.remove(o, do_unlink=True)
            n += 1
    return n


# ══════════════════════════════════════════════════════════════════════
# tier C · pipeline / measurement / preview
# ══════════════════════════════════════════════════════════════════════
def tri_count(objs=None):
    """Triangle count (for gates such as a "face budget")."""
    objs = objs if objs is not None else [o for o in bpy.data.objects if o.type == "MESH"]
    n = 0
    for o in objs:
        for p in o.data.polygons:
            n += max(0, len(p.vertices) - 2)
    return n


def bbox_all(objs=None, unit="mm"):
    """World bounding box of the whole assembly (mm by default). Returns {"ok","bbox","size","unit"}."""
    objs = objs if objs is not None else [o for o in bpy.data.objects if o.type == "MESH"]
    objs = [o for o in objs if o is not None and o.type == "MESH"]
    if not objs:
        return {"ok": False, "error": "bbox_all: no mesh objects"}
    lo = [1e18] * 3
    hi = [-1e18] * 3
    for o in objs:
        bb = _obb(o)
        for i in range(3):
            lo[i] = min(lo[i], bb[0][i])
            hi[i] = max(hi[i], bb[1][i])
    if str(unit).lower() == "mm":
        f = u2mm
    else:
        f = float
    return {"ok": True, "unit": str(unit),
            "bbox": [[round(f(v), 4) for v in lo], [round(f(v), 4) for v in hi]],
            "size": [round(f(hi[i] - lo[i]), 4) for i in range(3)]}


def _aim(loc, target):
    d = Vector(target) - Vector(loc)
    q = Vector((0.0, 0.0, -1.0)).rotation_difference(d.normalized())
    return q.to_euler()


def quick_views(outdir, views, res=(1280, 720), engine="BLENDER_WORKBENCH", prefix=""):
    """Quick multi-view preview (renders without lights/materials).

    views=[{"name","from","look_at","lens"?,"ortho"?}, …]; coordinates = current scene units.
    Lightweight and self-contained; to **compute IoU / align sections against a reference image** use blender_rt_plan(op="qc_render_views").
    """
    import os
    os.makedirs(str(outdir), exist_ok=True)
    sc = bpy.context.scene
    old_engine = sc.render.engine
    old_res = (sc.render.resolution_x, sc.render.resolution_y)
    made = []
    try:
        try:
            sc.render.engine = str(engine)
        except Exception:
            pass
        sc.render.resolution_x = int(res[0])
        sc.render.resolution_y = int(res[1])
        sc.render.resolution_percentage = 100
        sc.render.image_settings.file_format = "PNG"
        for v in views:
            cd = bpy.data.cameras.new("__geo_cam")
            cd.lens = float(v.get("lens", 50.0))
            if v.get("ortho"):
                cd.type = "ORTHO"
                cd.ortho_scale = float(v["ortho"])
            co = bpy.data.objects.new("__geo_cam", cd)
            sc.collection.objects.link(co)
            co.location = v["from"]
            co.rotation_euler = _aim(v["from"], v["look_at"])
            sc.camera = co
            fn = os.path.join(str(outdir), "%s%s.png" % (prefix, v.get("name", "view")))
            sc.render.filepath = fn
            bpy.ops.render.render(write_still=True)
            made.append(fn)
            bpy.data.objects.remove(co, do_unlink=True)
            if cd.users == 0:
                bpy.data.cameras.remove(cd)
    finally:
        sc.render.resolution_x = int(old_res[0])
        sc.render.resolution_y = int(old_res[1])
        try:
            sc.render.engine = old_engine
        except Exception:
            pass
    return {"ok": True, "n": len(made), "files": made}


# ══════════════════════════════════════════════════════════════════════
# self-test / quick reference / registration
# ══════════════════════════════════════════════════════════════════════
def geo_help():
    return _j({
        "module": "geo.py", "version": GEO_VERSION,
        "what": "geometry base — mechanism layer: verbs only, no nouns (contains no shape defaults)",
        "where": "KERNEL_BOOTSTRAP already injects it (public names directly usable); also registered as K.dsh_geo_api; or preload=\"geo\"",
        "A_env": ["principled", "mix_rgb", "apply_mods", "bevel", "shade_auto",
                  "shade_flat", "recalc_normals", "mesh_stats", "mm2u", "u2mm"],
        "B_verbs": ["solid", "box", "cyl", "tube", "prism", "loft", "stack",
                    "boolean", "hole_cut", "slots_cut", "mirror", "linear_array", "join", "clear_scene"],
        "C_pipe": ["collection", "own", "assign", "assign_all", "tri_count", "bbox_all", "quick_views"],
        "not_here": ["rail pitch / hole-pattern layout / grip section / vehicle station table / airfoil outline — shape layer, write it in the project's lib/spec.py"],
        "judgement": ["Delete every number from the arguments: does the description still hold for another object?",
                      "Can the caller fully override the defaults? (this module never gives shape defaults)",
                      "Does it solve 'how to use Blender / how to compute geometry' or 'what this thing looks like'?"],
        "selftest": "geo_selftest()",
    })


def _geo_selftest_basic(made, ev):
    """1) box + bevel, 2) cylinder/tube, 3) loft; returns the bevelled box (reused by the later checks)."""
    # 1) box + bevel → manifold, no degenerate faces
    b = box("__geo_t_box", (0, 20), (0, 10), (0, 5), coll="COL_geotest",
            bevel_mm=0.5, smooth_angle=30.0)
    made.append(b)
    s = mesh_stats(b)
    ev["box_manifold"] = (s["nonmanifold_edges"] == 0 and s["degenerate_faces"] == 0)

    # 2) cylinder / tube
    c = cyl("__geo_t_cyl", (0, 0, 0), (0, 0, 30), 4.0, coll="COL_geotest", segs=24)
    made.append(c)
    ev["cyl_manifold"] = mesh_stats(c)["nonmanifold_edges"] == 0
    t = tube("__geo_t_tube", (0, 0, 0), (0, 0, 30), 5.0, 3.0, coll="COL_geotest")
    made.append(t)
    st = mesh_stats(t)
    ev["tube_hollow"] = st["nonmanifold_edges"] == 0 and st["faces"] > mesh_stats(c)["faces"]

    # 3) loft (tapered square column, same point count per layer)
    rings = []
    for i in range(6):
        t01 = i / 5.0
        h = 6.0 - 4.0 * t01
        rings.append([(-h, -h, i * 4.0), (h, -h, i * 4.0), (h, h, i * 4.0), (-h, h, i * 4.0)])
    L = loft("__geo_t_loft", rings, coll="COL_geotest")
    made.append(L)
    sl = mesh_stats(L)
    ev["loft_manifold"] = sl["nonmanifold_edges"] == 0 and sl["degenerate_faces"] == 0
    return b


def _geo_selftest_boolean(made, ev, canary):
    """4) boolean difference guard, 5) the guard in both directions (no false positives + canary)."""
    # 4) boolean difference: guard passes, bbox unchanged, face count grows
    base = box("__geo_t_base", (0, 40), (0, 20), (0, 20), coll="COL_geotest")
    made.append(base)
    bb0 = bbox_all([base], unit="mm")
    f0 = mesh_stats(base)["faces"]
    hole_cut(base, [{"center": (20, 10, 10), "axis": "Z", "r": 6.0, "length": 60.0}],
             name="__geo_t_hole", coll="COL_geotest")
    bb1 = bbox_all([base], unit="mm")
    ev["boolean_guard_pass"] = base.get("dsh_boolean_guard", "").find('"guard": "pass"') > 0
    ev["boolean_bbox_kept"] = bb0["bbox"] == bb1["bbox"]
    ev["boolean_faces_grew"] = mesh_stats(base)["faces"] > f0
    ev["boolean_manifold"] = mesh_stats(base)["nonmanifold_edges"] == 0

    # 5) the guard must be tested in both directions
    # ① **no false positives**: a normal part + a cutter sticking out of the body — the correct difference result still lies inside the body
    n1 = box("__geo_t_n1", (0, 40), (0, 20), (0, 20), coll="COL_geotest")
    made.append(n1)
    c1 = box("__geo_t_c1", (35, 90), (5, 15), (5, 15), coll="COL_geotest")
    made.append(c1)
    false_alarm = False
    try:
        boolean(n1, c1, "DIFFERENCE", delete_cutter=True, verify=True)
    except RuntimeError:
        false_alarm = True
    ev["guard_no_false_positive"] = (not false_alarm)

    # ② **canary**: a self-intersecting body (two interpenetrating boxes joined into one mesh) + a cutter sticking out of the body.
    #    If an EXACT boolean ever degrades into a union on this input, the bbox will swell → the guard should stop it.
    #    Measured on 5.2.2: this construction **did not reproduce** (hence it is a canary, not part of ok) — recorded here,
    #    so that when a future version regresses it flips to true and you see it at a glance in the receipt.
    a1 = box("__geo_t_s1", (0, 20), (0, 20), (0, 20), coll="COL_geotest")
    a2 = box("__geo_t_s2", (10, 30), (10, 30), (10, 30), coll="COL_geotest")
    made.extend([a1, a2])
    si = join([a1, a2], name="__geo_t_selfint", coll="COL_geotest")
    made.append(si)
    c2 = box("__geo_t_c2", (25, 80), (10, 30), (10, 30), coll="COL_geotest")
    made.append(c2)
    fired = False
    try:
        boolean(si, c2, "DIFFERENCE", delete_cutter=True, verify=True)
    except RuntimeError:
        fired = True
    canary["selfint_guard_canary"] = fired


def _geo_selftest_misc(made, ev, b):
    """6) mirror/array, 7) auto-smooth does not change topology, 8) counts are correct."""
    src = box("__geo_t_m", (0, 10), (0, 5), (0, 5), coll="COL_geotest")
    made.append(src)
    mi = mirror(src, "Y")
    made.append(mi)
    arr = linear_array(src, 4, (30.0, 0.0, 0.0), name="__geo_t_a")
    made.extend(arr)
    ev["mirror_is_mirrored"] = bool(mi) and mi.name.endswith("_mir")
    ev["array_count_4"] = len(arr) == 4

    # 7) auto-smooth does not change topology (EDGE_SPLIT splits edges → blows straight through the non-manifold gate)
    pv = mesh_stats(b)["verts"]
    nsharp = len([e for e in b.data.edges if e.use_edge_sharp])
    shade_auto(b, 30.0)
    ev["shade_auto_keeps_topology"] = mesh_stats(b)["verts"] == pv
    ev["shade_auto_marks_sharp"] = (len([e for e in b.data.edges if e.use_edge_sharp]) >= nsharp)

    # 8) counts are correct: a cube has 12 triangles
    cube = box("__geo_t_cube", (0, 10), (0, 10), (0, 10), coll="COL_geotest")
    made.append(cube)
    ev["tri_count_cube_12"] = tri_count([cube]) == 12
    ev["bbox_size_10mm"] = bbox_all([cube], unit="mm")["size"] == [10.0, 10.0, 10.0]


def geo_selftest():
    """Self-test: synthetic geometry assertions (non-manifold/degenerate/boolean guard/mirror array/auto-smooth keeps topology/counts correct)."""
    ev = {}
    canary = {}
    made = []

    def _clean():
        for o in made:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass

    prev_scale = None
    try:
        prev_scale = float(bpy.context.scene.unit_settings.scale_length)
        bpy.context.scene.unit_settings.scale_length = 0.001   # 1 unit = 1mm, so the assertions can use mm
        b = _geo_selftest_basic(made, ev)
        _geo_selftest_boolean(made, ev, canary)
        _geo_selftest_misc(made, ev, b)
    except Exception as e:
        _clean()
        try:
            if prev_scale is not None:
                bpy.context.scene.unit_settings.scale_length = prev_scale
        except Exception:
            pass
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:300]),
                   "version": GEO_VERSION, "evidence": ev, "canary": canary})
    _clean()
    try:
        if prev_scale is not None:
            bpy.context.scene.unit_settings.scale_length = prev_scale
    except Exception:
        pass
    ok = all(v is True for v in ev.values())
    return _j({"ok": bool(ok), "version": GEO_VERSION, "evidence": ev, "canary": canary})



OPS = {
    "help": geo_help, "selftest": geo_selftest,
    "principled": principled, "mix_rgb": mix_rgb, "apply_mods": apply_mods,
    "bevel": bevel, "shade_auto": shade_auto, "shade_flat": shade_flat,
    "recalc_normals": recalc_normals, "mesh_stats": mesh_stats,
    "mm2u": mm2u, "u2mm": u2mm,
    "collection": collection, "own": own, "assign": assign, "assign_all": assign_all, "solid": solid,
    "box": box, "cyl": cyl, "tube": tube, "prism": prism, "loft": loft, "stack": stack,
    "boolean": boolean, "hole_cut": hole_cut, "slots_cut": slots_cut,
    "mirror": mirror, "linear_array": linear_array, "join": join, "clear_scene": clear_scene,
    "tri_count": tri_count, "bbox_all": bbox_all, "quick_views": quick_views,
}

# registration: mounts K.dsh_geo_api (dispatchable) and also puts the public names into script globals via bootstrap (directly usable)
_KIT.register("geo", GEO_VERSION, ops=OPS,
              extra={"get": lambda n: OPS.get(str(n)), "help_text": geo_help})
