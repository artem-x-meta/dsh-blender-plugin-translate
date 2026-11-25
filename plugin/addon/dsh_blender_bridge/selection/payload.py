""" Read the current edit/pose-mode sub-element selection. """

import bpy

from .caps import SUB_SELECTION_CAP, cap_selection


def _read_mesh_selection(mode):
    obj = getattr(bpy.context, "edit_object", None)
    if obj is None:
        return None
    try:
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        verts = [v.index for v in bm.verts if v.select]
        edges = [e.index for e in bm.edges if e.select]
        faces = [f.index for f in bm.faces if f.select]
    except Exception as exc:
        return {"type": "MESH", "object": obj.name, "mode": mode,
                "note": "selection read failed: " + str(exc), "counts": {}, "indices": {}, "truncated": False}
    try:
        sm = tuple(bool(x) for x in bpy.context.tool_settings.mesh_select_mode)  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        sm = (False, False, False)
    v_cap, v_tr = cap_selection(verts)
    e_cap, e_tr = cap_selection(edges)
    f_cap, f_tr = cap_selection(faces)
    return {"type": "MESH", "object": obj.name, "mode": mode,
            "select_mode": {"vertex": sm[0], "edge": sm[1], "face": sm[2]},
            "counts": {"vertices": len(verts), "edges": len(edges), "faces": len(faces)},
            "indices": {"vertices": v_cap, "edges": e_cap, "faces": f_cap},
            "truncated": bool(v_tr or e_tr or f_tr)}


def _read_armature_selection(mode):
    edit_obj = getattr(bpy.context, "edit_object", None)
    active_obj = getattr(bpy.context, "active_object", None)
    obj = active_obj if mode == "POSE" else (edit_obj or active_obj)
    if obj is None or getattr(obj, "type", "") != "ARMATURE":
        return None
    try:
        if mode == "POSE":
            # in pose mode the selection flag lives on PoseBone.select (Bone itself has no select)
            names = [pb.name for pb in obj.pose.bones if bool(getattr(pb, "select", False))]
        else:
            names = [eb.name for eb in obj.data.edit_bones if bool(getattr(eb, "select", False))]
    except Exception as exc:
        return {"type": "ARMATURE", "object": obj.name, "mode": mode,
                "note": "bone read failed: " + str(exc), "counts": {}, "bones": [], "truncated": False}
    cap, tr = cap_selection(names)
    return {"type": "ARMATURE", "object": obj.name, "mode": mode,
            "counts": {"bones": len(names)}, "bones": cap, "truncated": bool(tr)}


def _read_curve_selection(mode):
    edit_obj = getattr(bpy.context, "edit_object", None)
    active_obj = getattr(bpy.context, "active_object", None)
    obj = edit_obj or active_obj
    if obj is None:
        return None
    points = []
    total = 0
    try:
        for si, spline in enumerate(obj.data.splines):
            if str(getattr(spline, "type", "")) == "BEZIER":
                for pi, bp in enumerate(spline.bezier_points):
                    if bool(getattr(bp, "select_control_point", False)):
                        total += 1
                        if len(points) < SUB_SELECTION_CAP:
                            points.append([si, pi])
            else:
                for pi, pt in enumerate(getattr(spline, "points", [])):
                    if bool(getattr(pt, "select", False)):
                        total += 1
                        if len(points) < SUB_SELECTION_CAP:
                            points.append([si, pi])
    except Exception as exc:
        return {"type": "CURVE", "object": obj.name, "mode": mode,
                "note": "curve point read failed: " + str(exc), "counts": {}, "points": [], "truncated": False}
    return {"type": "CURVE", "object": obj.name, "mode": mode,
            "counts": {"points": total}, "points": points, "truncated": total > len(points)}


def _read_lattice_selection(mode):
    edit_obj = getattr(bpy.context, "edit_object", None)
    active_obj = getattr(bpy.context, "active_object", None)
    obj = edit_obj or active_obj
    if obj is None:
        return None
    try:
        points = [i for i, pt in enumerate(obj.data.points) if bool(getattr(pt, "select", False))]
    except Exception as exc:
        return {"type": "LATTICE", "object": obj.name, "mode": mode,
                "note": "lattice point read failed: " + str(exc), "counts": {}, "points": [], "truncated": False}
    cap, tr = cap_selection(points)
    return {"type": "LATTICE", "object": obj.name, "mode": mode,
            "counts": {"points": len(points)}, "points": cap, "truncated": bool(tr)}


def _read_other_selection(mode):
    edit_obj = getattr(bpy.context, "edit_object", None)
    active_obj = getattr(bpy.context, "active_object", None)
    obj = edit_obj or active_obj
    if not (mode.startswith("EDIT_") or mode == "PAINT_GPENCIL"):
        return None
    return {"type": "OTHER", "object": getattr(obj, "name", None), "mode": mode,
            "note": "sub-elements of this edit mode are not expanded yet; have the model read the selection set directly with Python",
            "counts": {}, "truncated": False}


def read_sub_selection():
    """Return the sub-element selection in the current edit/pose mode; returns None in object mode.

    Called only when needed (send / get_selection / list expansion), never polled from an activity tick —
    enumerating every vertex on a large mesh can be very slow. All arrays are clamped to SUB_SELECTION_CAP
    and carry truncated honestly.
    """
    mode = str(getattr(bpy.context, "mode", "OBJECT") or "OBJECT")
    if mode == "OBJECT":
        return None
    if mode == "EDIT_MESH":
        return _read_mesh_selection(mode)
    if mode in ("EDIT_ARMATURE", "POSE"):
        return _read_armature_selection(mode)
    if mode in ("EDIT_CURVE", "EDIT_SURFACE"):
        return _read_curve_selection(mode)
    if mode == "EDIT_LATTICE":
        return _read_lattice_selection(mode)
    return _read_other_selection(mode)
