""" Selection lists and list refresh timer. """

import bpy
import time
import os
import tempfile

from ..selection import read_sub_selection
from ..protocol import redraw_view3d_panels
from ..recorders.activity import get_activity_tracker

LIST_UI_CAP = 500

_LAST_UI_STATE_KEY: dict[str, object] = {"key": None}


class DSHBB_SelectionItem(bpy.types.PropertyGroup):
    obj_name: bpy.props.StringProperty(name="Name", default="")
    obj_type: bpy.props.StringProperty(name="Type", default="")


class DSHBB_UL_ObjectList(bpy.types.UIList):
    bl_idname = "DSHBB_UL_ObjectList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=getattr(item, "obj_name", "") or "<unnamed>", icon='OBJECT_DATA')
        row.label(text=getattr(item, "obj_type", "") or "?")


def sub_mode_label(mode):
    labels = {
        "EDIT_MESH": "Edit Mode (Mesh)",
        "EDIT_ARMATURE": "Edit Mode (Armature)",
        "POSE": "Pose Mode",
        "EDIT_CURVE": "Edit Mode (Curve)",
        "EDIT_SURFACE": "Edit Mode (Surface)",
        "EDIT_LATTICE": "Edit Mode (Lattice)",
        "EDIT_TEXT": "Edit Mode (Text)",
        "PAINT_GPENCIL": "Paint Mode (Grease Pencil)",
        "EDIT_GPENCIL": "Edit Mode (Grease Pencil)",
    }
    return labels.get(str(mode), str(mode))


def _sub_selection_entries(sub):
    """Turn a sub-element selection into UIList rows: one object row + one row per element (label, short type)."""
    if not sub:
        return []
    entries = []
    # object rows are handled by the selected_objects part of _selection_list_entries; here only sub-element rows
    if str(sub.get("type")) == "MESH":
        idx = sub.get("indices") or {}
        for i in (idx.get("vertices") or [])[:LIST_UI_CAP // 3]:
            entries.append(("Vertex %s" % i, "VERT"))
        for pair in (idx.get("edges") or [])[:LIST_UI_CAP // 3]:
            entries.append(("Edge %s" % pair, "EDGE"))
        for i in (idx.get("faces") or [])[:LIST_UI_CAP // 3]:
            entries.append(("Face %s" % i, "FACE"))
    elif str(sub.get("type")) == "ARMATURE":
        for name in (sub.get("bones") or [])[:LIST_UI_CAP]:
            entries.append((str(name), "BONE"))
    elif str(sub.get("type")) in ("CURVE", "LATTICE"):
        for pair in (sub.get("points") or [])[:LIST_UI_CAP]:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                entries.append(("%s : %s" % (pair[0], pair[1]), "POINT"))
    return entries[:LIST_UI_CAP]


def _selection_list_entries():
    entries = [(obj.name, str(getattr(obj, "type", "?"))) for obj in (bpy.context.selected_objects or [])[:LIST_UI_CAP]]
    sub = read_sub_selection()
    if sub is not None:
        entries.extend(_sub_selection_entries(sub))
    return entries[:LIST_UI_CAP]


def _refresh_selection_list(scene, context=None):
    try:
        _sync_ui_list(scene.dshbb_selection_items, _selection_list_entries())
    except Exception:
        pass


def _refresh_collection_list(scene, context=None):
    try:
        coll = getattr(scene, "dshbb_collection_target", None)
        entries = []
        if coll is not None:
            entries = [(obj.name, str(getattr(obj, "type", "?"))) for obj in list(coll.objects)[:LIST_UI_CAP]]
        _sync_ui_list(scene.dshbb_collection_items, entries)
    except Exception:
        pass


def on_show_selection_list_update(self, context):
    _refresh_selection_list(self, context)


def on_show_collection_list_update(self, context):
    _refresh_collection_list(self, context)


def dshbb_ui_list_timer():
    """Keep list content in sync with the scene while a list is open; redraw the N panel on activity/pause changes."""
    try:
        scene = bpy.context.scene
        if scene is not None:
            if getattr(scene, "dshbb_show_selection_list", False):
                _refresh_selection_list(scene)
            if getattr(scene, "dshbb_show_collection_list", False):
                _refresh_collection_list(scene)
            try:
                snap = get_activity_tracker().snapshot(include_current_command=False)
                key = (snap.get("state"), bool(getattr(scene, "dshbb_ai_paused", False)))
                if key != _LAST_UI_STATE_KEY["key"]:
                    _LAST_UI_STATE_KEY["key"] = key
                    redraw_view3d_panels()
            except Exception:
                pass
    except Exception:
        pass
    return 0.5


def _sync_ui_list(collection, entries):
    """Sync [(name, type)] into the PropertyGroup collection; skip when the signature is equal (avoids rebuilding on every redraw)."""
    if len(collection) == len(entries):
        same = True
        for i, (name, typ) in enumerate(entries):
            item = collection[i]
            if item.obj_name != name or item.obj_type != typ:
                same = False
                break
        if same:
            return
    collection.clear()
    for name, typ in entries:
        item = collection.add()
        item.obj_name = name
        item.obj_type = typ


# Panel-draw error record: written to scene properties + a log file (so it can still be diagnosed when the user cannot easily see the console)
def log_panel_error(tb):
    text = str(tb)[-4000:]
    try:
        base = bpy.app.tempdir or tempfile.gettempdir()
        p = os.path.join(base, "dshbb-panel-error.log")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + text + "\n")
    except Exception:
        pass
