# -*- coding: utf-8 -*-
"""Split from qc_render.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .common import _j

PARTS_PALETTE = [
    (230, 60, 60), (60, 130, 230), (70, 200, 90), (240, 190, 50),
    (170, 90, 220), (40, 200, 200), (240, 130, 40), (130, 130, 240),
    (200, 220, 60), (240, 110, 180), (90, 200, 150), (150, 150, 150),
]


def _srgb_to_linear(v):
    """sRGB(0-1) → linear. Base Color / Emission expect linear values; feeding sRGB in directly makes everything too bright,
    and the legend then no longer matches the colours in the image (for false-colour renders the legend must match the image)."""
    v = max(0.0, min(1.0, float(v)))
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _palette_linear(rgb255):
    return tuple(round(_srgb_to_linear(float(c) / 255.0), 6) for c in rgb255[:3])


def _stable_hash(s):
    """Cross-process stable string hash. Pitfall: Python's built-in hash() is randomly salted (PYTHONHASHSEED),
    so two renders of the same scene change colours — deterministic colouring must use md5."""
    return int(hashlib.md5(str(s).encode("utf-8")).hexdigest()[:8], 16)


def _parts_groups(objs, group_by):
    """Part grouping → [(group name, [obj, ...])], sorted by group name (deterministic).

    group_by="object" (default, one object per part) | "collection" (one collection per part: when an object belongs to several collections take
    the one with the **smallest name** — do not use users_collection's natural order, which changes with scene structure).
    """
    g = {}
    for ob in objs:
        if str(group_by) == "collection":
            cols = sorted([str(c.name) for c in ob.users_collection]) or ["(no collection)"]
            key = cols[0]
        else:
            key = str(ob.name)
        g.setdefault(key, []).append(ob)
    return sorted(g.items(), key=lambda kv: str(kv[0]))


def _parts_assign(groups, palette):
    """Assign colours in group-name order → {group name: {"index","rgb","source"}} (colours stay identical across repeated renders of one scene).

    · groups ≤ palette size: group i takes palette[i] (source="order");
    · groups > palette size: the surplus groups are ordered by name hash and each is placed into the "least used right now" colour (source="hash") —
      deterministic + reuse spread as evenly as possible; **never fail because the palette is too small**.
    """
    n = len(palette)
    asg = {}
    used = [0] * n
    for i, (name, _objs) in enumerate(groups):
        if i < n:
            asg[str(name)] = {"index": i, "rgb": [int(palette[i][0]), int(palette[i][1]), int(palette[i][2])],
                              "source": "order"}
            used[i] += 1
    rest = [str(nm) for i, (nm, _o) in enumerate(groups) if i >= n]
    for nm in sorted(rest, key=lambda s: (_stable_hash(s), s)):
        k = min(range(n), key=lambda j: (used[j], _stable_hash("%s#%d" % (nm, j))))   # least-used colour, hash breaks ties
        used[k] += 1
        asg[nm] = {"index": k, "rgb": [int(palette[k][0]), int(palette[k][1]), int(palette[k][2])],
                   "source": "hash"}
    return asg


def _make_part_material(idx, rgb255, flat=False):
    """Temporary flat-colour material: Principled by default (shading reveals interpenetration/floating/orientation; Procedura uses this convention too),
    flat=True uses Emission (unaffected by lighting, image colour ≈ legend colour, good for reading the image against the colour key).
    The material name carries the index and colour value (DSH_PC_07_F0BE32), so afterwards you can tell at a glance in the .blend who left it behind."""
    rgb255 = [int(rgb255[0]), int(rgb255[1]), int(rgb255[2])]
    name = "DSH_PC_%02d_%02X%02X%02X" % (int(idx), rgb255[0], rgb255[1], rgb255[2])
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True           # the only way to enable nodes in 5.2 (removed from 6.0 → do not hardcode)
    except Exception:
        pass
    lin = _palette_linear(rgb255)
    nt = getattr(mat, "node_tree", None)
    if nt is None:
        raise RuntimeError("material %s has no accessible node_tree (Blender version difference)" % name)
    out = None
    for nd in nt.nodes:
        if nd.bl_idname == "ShaderNodeOutputMaterial":
            out = nd
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    if flat:
        nd = nt.nodes.new("ShaderNodeEmission")
        nd.inputs["Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
        try:
            nd.inputs["Strength"].default_value = 1.0
        except Exception:
            pass
        nt.links.new(nd.outputs[0], out.inputs["Surface"])
    else:
        b = None
        for nd in nt.nodes:
            if nd.bl_idname == "ShaderNodeBsdfPrincipled":
                b = nd
        if b is None:
            b = nt.nodes.new("ShaderNodeBsdfPrincipled")
            nt.links.new(b.outputs[0], out.inputs["Surface"])
        b.inputs["Base Color"].default_value = (lin[0], lin[1], lin[2], 1.0)
        for k, v in (("Roughness", 0.55), ("Metallic", 0.0), ("Specular IOR Level", 0.3)):
            if k in b.inputs:
                try:
                    b.inputs[k].default_value = v
                except Exception:
                    pass
    return mat


def _parts_override(objs, assign_by_name, group_of, flat):
    """Temporarily override material slots → (state, mats_by_group, err). state records everything needed to restore, per object.

    Two pitfalls (both measured in practice, written down here so nobody repeats them):
      · **linked copies** (several objects sharing one mesh): changing the DATA slot bleeds colour onto other objects (measured in practice: shared_bleeds=true) →
        isolate first with `ob.data = ob.data.copy()`, then restore the original mesh and delete the copy (the mesh count must return to baseline);
      · **objects with 0 slots** need a slot appended before they can render in colour; when restoring, `mesh.materials.clear()` resets to 0 slots
        (assigning None leaves an empty slot, so the slot count no longer matches).
    """
    state, mats, err = [], {}, None
    mat_cache = {}
    for ob in objs:
        key = str(group_of(ob))
        asg = (assign_by_name or {}).get(key) or {}
        rgb = asg.get("rgb") or [int(PARTS_PALETTE[0][0]), int(PARTS_PALETTE[0][1]), int(PARTS_PALETTE[0][2])]
        idx = int(asg.get("index") or 0)
        mk = (idx, tuple(int(x) for x in rgb), bool(flat))
        mat = mat_cache.get(mk)
        if mat is None:
            mat = _make_part_material(idx, rgb, flat)
            mat_cache[mk] = mat
        mats[key] = mat
        st = {"object": str(ob.name), "group": key, "material": str(mat.name),
              "slots": [[str(s.link), (str(s.material.name) if s.material else None)] for s in ob.material_slots],
              "n_slots": len(ob.material_slots), "appended": False,
              "mesh_before": None, "mesh_copy": None}
        try:
            if int(getattr(ob.data, "users", 0) or 0) > 1:
                st["mesh_before"] = ob.data
                ob.data = ob.data.copy()
                st["mesh_copy"] = ob.data
            if len(ob.material_slots) == 0:
                ob.data.materials.append(mat)
                st["appended"] = True
            else:
                for s in ob.material_slots:
                    s.material = mat
        except Exception as e:
            err = "material override failed (%s): %s: %s" % (ob.name, type(e).__name__, str(e)[:160])
            state.append(st)
            break
        state.append(st)
    return state, mats, err


def _parts_restore(state, mats):
    """Restore the parts_color state: material slots (including swapping linked copies back to the original mesh and deleting the copies) → delete temporary materials → **verify item by item**.

    Verification criterion: the restored `[(slot.link, slot.material.name)]` must equal the pre-override value slot by slot;
    if verification fails → the caller sets ok to false (leaving the scene not fully restored is far worse than one missing image).
    """
    rep = {"objects": len(state), "slots_restored": 0, "mesh_copies_removed": 0,
           "temp_materials_removed": 0, "temp_materials_left": [], "mismatches": [], "ok": False}
    for st in reversed(state):
        ob = bpy.data.objects.get(str(st.get("object")))
        if ob is None:
            rep["mismatches"].append("%s: object no longer exists (cannot verify material slots)" % st.get("object"))
            continue
        try:
            if st.get("appended"):
                ob.data.materials.clear()
            else:
                for i, pair in enumerate(st.get("slots") or []):
                    if i >= len(ob.material_slots):
                        rep["mismatches"].append("%s: slot count %d < recorded %d"
                                                 % (ob.name, len(ob.material_slots), len(st.get("slots") or [])))
                        break
                    s = ob.material_slots[i]
                    if str(s.link) != str(pair[0]):
                        s.link = str(pair[0])
                    s.material = (bpy.data.materials.get(str(pair[1])) if pair[1] else None)
        except Exception as e:
            rep["mismatches"].append("%s: restoring material slots raised %s: %s"
                                     % (st.get("object"), type(e).__name__, str(e)[:140]))
        if st.get("mesh_copy") is not None:
            try:
                ob.data = st["mesh_before"]
                bpy.data.meshes.remove(st["mesh_copy"])
                rep["mesh_copies_removed"] += 1
            except Exception as e:
                rep["mismatches"].append("%s: restoring the linked-copy mesh failed %s: %s"
                                         % (st.get("object"), type(e).__name__, str(e)[:140]))
        try:
            now = [[str(s.link), (str(s.material.name) if s.material else None)] for s in getattr(ob, "material_slots", ())]
            if now != [list(x) for x in (st.get("slots") or [])]:
                rep["mismatches"].append("%s: material slots differ from before the render %s != %s"
                                         % (ob.name, now, st.get("slots")))
            else:
                rep["slots_restored"] += 1
        except Exception as e:
            rep["mismatches"].append("%s: verifying material slots raised %s: %s" % (ob.name, type(e).__name__, str(e)[:120]))
    for mat in set(mats.values()):
        nm = str(mat.name)
        try:
            bpy.data.materials.remove(mat, do_unlink=True)
        except Exception as e:
            rep["mismatches"].append("temporary material %s could not be removed %s: %s" % (nm, type(e).__name__, str(e)[:120]))
        if bpy.data.materials.get(nm) is not None:
            rep["temp_materials_left"].append(nm)
        else:
            rep["temp_materials_removed"] += 1
    rep["ok"] = (not rep["mismatches"]) and (not rep["temp_materials_left"])
    return rep


def _parts_legend_rows(groups, assign):
    """Legend rows: `name<TAB>R,G,B<TAB>face count` (face count = sum of polygons over all objects in that part)."""
    rows = []
    for name, objs in groups:
        asg = assign.get(str(name)) or {}
        rgb = asg.get("rgb") or [0, 0, 0]
        faces = 0
        for ob in objs:
            try:
                faces += len(ob.data.polygons)
            except Exception:
                pass
        rows.append({"name": str(name).replace("\t", " ").replace("\n", " "),
                     "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])], "faces": int(faces),
                     "objects": [str(o.name) for o in objs], "color_index": asg.get("index"),
                     "color_source": asg.get("source")})
    return rows


def _write_parts_legend(txt_path, rows, meta):
    """Write the legend: .txt = one `name<TAB>R,G,B<TAB>face count` per line (**pure data rows, no header** → `wc -l` gives the part count);
    .json = full detail under the same name (palette, sRGB→linear conversion, grouping convention, restore self-check…), still readable by a human."""
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write("%s\t%d,%d,%d\t%d" % (r["name"], r["rgb"][0], r["rgb"][1], r["rgb"][2], r["faces"]) + chr(10))
    jpath = os.path.splitext(txt_path)[0] + ".json"
    with open(jpath, "w", encoding="utf-8") as f:
        f.write(_j(dict(meta, legend_txt=txt_path, legend_json=jpath, rows=rows)))
    return jpath


def _legend_line_count(path):
    """Number of legend data rows (blank lines excluded) — the self-check uses it to assert "rows == part count"."""
    n = 0
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                n += 1
    return n
