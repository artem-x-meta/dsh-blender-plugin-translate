""" Main N-panel: activity state, connection, selection and community links. """

import textwrap

import bpy

from ...commands import selection as selection_commands
from ...commands.selection import selection_collection_summary
from ...config import DISCORD_URL, dshbb_backend_url
from ...protocol import ai_paused
from ...recorders.activity import get_activity_tracker
from ...ui.lists import LIST_UI_CAP, log_panel_error, sub_mode_label


class DSHBB_PT_Panel(bpy.types.Panel):
    bl_label = "DSH Blender Bridge"
    bl_idname = "DSHBB_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DSH Blender Bridge"

    def draw(self, context):
        # Wrap it: record any draw exception (users are not comfortable opening the console) and try not to black out the whole panel
        try:
            self._draw_impl(context)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            log_panel_error(tb)
            try:
                context.scene.dshbb_last_panel_error = tb[-3000:]
            except Exception:
                pass
            try:
                self.layout.label(text="panel draw error: " + str(exc)[:120], icon="ERROR")
            except Exception:
                pass

    def _draw_impl(self, context):
        layout = self.layout
        scene = context.scene
        activity = self._activity_snapshot()
        self._draw_activity(layout, activity)
        self._draw_connection(layout, scene)
        self._draw_selection(layout, scene, activity)
        self._draw_community(layout, context)

    @staticmethod
    def _activity_snapshot():
        try:
            return get_activity_tracker().snapshot(include_current_command=False)
        except Exception:
            return {}

    @staticmethod
    def _draw_activity(layout, activity):
        # v2.5 · activity state pinned to the top (warns while AI is operating) + pause AI operations
        layout.separator()
        act_box = layout.box()
        state = str(activity.get("state") or "idle")
        state_text = {"human": "human: operating", "agent": "AI: running",
                      "both": "human / AI both active", "idle": "idle"}.get(state, state)
        paused = ai_paused()
        if state in ("agent", "both"):
            warn = act_box.row()
            warn.alert = True
            warn.label(text="AI is operating Blender" + (" (a human is operating too)" if state == "both" else ""),
                       icon="ERROR")
        else:
            act_box.label(text="Activity state: " + state_text)
        if paused:
            prow = act_box.row()
            prow.alert = True
            prow.label(text="AI operations are paused · model requests will be refused")
        btn_row = act_box.row()
        btn_row.scale_y = 1.2
        btn_row.operator("dshbb.toggle_ai_pause",
                         text=("Resume AI operations" if paused else "Pause AI operations"))
        if activity.get("last_human_kind"):
            act_box.label(text="Last human action: " + str(activity.get("last_human_kind")))

    @staticmethod
    def _draw_connection(layout, scene):
        # Local bridge server (NOT the DSH plugin connection): the panel must not claim
        # that starting this socket server means the agent is connected.
        box = layout.box()
        col = box.column()
        if scene.dshbb_server_running:
            server = getattr(bpy.types, "dshbb_server", None)
            running_port = getattr(server, "port", scene.dshbb_port)
            col.label(text=f"Bridge listening on 127.0.0.1:{running_port}", icon="CHECKMARK")
            col.operator("dshbb.stop_server", text="Stop bridge server", icon="X")
        else:
            col.label(text="Bridge server stopped (DSH not connected)", icon="RADIOBUT_OFF")
            col.prop(scene, "dshbb_port")
            col.operator("dshbb.start_server", text="Start bridge server", icon="PLAY")

    def _draw_selection(self, layout, scene, activity):
        # v1.8 · Selection → DSH (select in Blender's native selection, press the button to attach it to DSH's next message)
        layout.separator()
        layout.label(text="Selection → DSH")
        sel_box = layout.box()
        selection = activity.get("selection") or {}
        sel_count = int(selection.get("count") or 0)
        sel_names = list(selection.get("names") or [])
        mode = str(getattr(scene, "dshbb_selection_mode", "MULTI") or "MULTI")
        mode_row = sel_box.row(align=True)
        mode_row.prop(scene, "dshbb_selection_mode", expand=True)
        sel_col = sel_box.column(align=True)
        if mode == "COLLECTION":
            self._draw_collection_selection(sel_box, sel_col, scene)
        else:
            self._draw_multi_selection(sel_box, sel_col, scene, selection, sel_count, sel_names)
        self._draw_selection_status(sel_box)
        self._draw_advanced(sel_box, scene)

    @staticmethod
    def _draw_collection_selection(sel_box, sel_col, scene):
        coll_row = sel_box.row(align=True)
        coll_row.prop(scene, "dshbb_collection_target", text="Collection")
        coll_row.operator("dshbb.use_selection_collection", text="", icon="FILE_REFRESH")
        target_coll = getattr(scene, "dshbb_collection_target", None)
        try:
            selected_names = {obj.name for obj in (bpy.context.selected_objects or [])}
        except Exception:
            selected_names = set()
        if target_coll is not None:
            try:
                members = list(target_coll.objects)
            except Exception:
                members = []
            selected_in_coll = sum(1 for obj in members if obj.name in selected_names)
            sel_col.label(text='collection "%s": %d items (%d currently selected) — sends the whole collection'
                               % (target_coll.name, len(members), selected_in_coll), icon="OUTLINER_COLLECTION")
            # member list: collapsible; when expanded it is a UIList (with its own scrollbar when there is a lot), its height is set with the "Height (rows)" slider
            list_open = bool(getattr(scene, "dshbb_show_collection_list", False))
            list_row = sel_box.row()
            list_row.prop(scene, "dshbb_show_collection_list",
                          text="Members (%d)" % len(members), emboss=False,
                          icon="TRIA_DOWN" if list_open else "TRIA_RIGHT")
            if list_open:
                sel_box.prop(scene, "dshbb_list_rows", text="Height (rows)", slider=True)
                ctrl = sel_box.row(align=True)
                ctrl.operator("dshbb.list_rows_dec", text="− Shorter")
                ctrl.operator("dshbb.list_rows_inc", text="+ Taller")
                sel_box.template_list("DSHBB_UL_ObjectList", "dshbb_collection",
                                      scene, "dshbb_collection_items",
                                      scene, "dshbb_collection_index",
                                      rows=int(getattr(scene, "dshbb_list_rows", 8)), maxrows=30)
                if len(members) > LIST_UI_CAP:
                    sel_box.label(text="the list shows only the first %d items (sending is unaffected)" % LIST_UI_CAP, icon="INFO")
                if not members:
                    sel_box.label(text="the collection is empty", icon="INFO")
            try:
                children = list(target_coll.children)
            except Exception:
                children = []
            if children:
                sel_box.label(text="child collections: %d, %s"
                                   % (len(children), ", ".join(c.name for c in children[:4])), icon="OUTLINER_COLLECTION")
        else:
            sel_col.label(text="no collection selected: pick one in the drop-down above", icon="INFO")
        send_row = sel_box.row()
        send_row.scale_y = 1.2
        send_row.enabled = target_coll is not None
        send_row.operator("dshbb.send_collection_to_dsh", text="Send collection to DSH", icon="EXPORT")

    @staticmethod
    def _draw_multi_selection(sel_box, sel_col, scene, selection, sel_count, sel_names):
        if not sel_count:
            sel_col.label(text="nothing selected: select in the viewport, then send", icon="INFO")
            send_row = sel_box.row()
            send_row.scale_y = 1.2
            send_row.enabled = False
            send_row.operator("dshbb.send_selection_to_dsh", text="Send selection to DSH", icon="EXPORT")
            return
        try:
            sub_mode = str(getattr(bpy.context, "mode", "") or "")
        except Exception:
            sub_mode = ""
        if sub_mode and sub_mode != "OBJECT":
            try:
                sub_obj = getattr(bpy.context, "edit_object", None) or getattr(bpy.context, "active_object", None)
            except Exception:
                sub_obj = None
            if sub_obj is not None:
                sel_col.label(text="Sub-elements: " + sub_mode_label(sub_mode) + " · " + sub_obj.name,
                              icon="EDITMODE_HLT")
        shown = ", ".join(sel_names[:3])
        if sel_count > 3 or selection.get("truncated"):
            shown += "…"
        sel_col.label(text="%d selected: %s" % (sel_count, shown), icon="OBJECT_DATA")
        if selection.get("active"):
            sel_col.label(text="Active object: %s · Mode: %s"
                               % (selection.get("active"), selection.get("mode") or "?"))
        if sel_count > 200:
            sel_col.label(text='too many items: switching to "Collection" mode and sending the whole group is faster', icon="INFO")
        try:
            selected_objs = list(bpy.context.selected_objects or [])
        except Exception:
            selected_objs = []
        list_open = bool(getattr(scene, "dshbb_show_selection_list", False))
        list_row = sel_box.row()
        list_row.prop(scene, "dshbb_show_selection_list",
                      text="Object / sub-element list (%d)" % len(selected_objs), emboss=False,
                      icon="TRIA_DOWN" if list_open else "TRIA_RIGHT")
        if list_open:
            sel_box.prop(scene, "dshbb_list_rows", text="Height (rows)", slider=True)
            ctrl = sel_box.row(align=True)
            ctrl.operator("dshbb.list_rows_dec", text="− Shorter")
            ctrl.operator("dshbb.list_rows_inc", text="+ Taller")
            sel_box.template_list("DSHBB_UL_ObjectList", "dshbb_selection",
                                  scene, "dshbb_selection_items",
                                  scene, "dshbb_selection_index",
                                  rows=int(getattr(scene, "dshbb_list_rows", 8)), maxrows=30)
            if len(selected_objs) > LIST_UI_CAP:
                sel_box.label(text="the list shows only the first %d items (sending is unaffected)" % LIST_UI_CAP, icon="INFO")
        send_row = sel_box.row()
        send_row.scale_y = 1.2
        send_row.enabled = True
        send_row.operator("dshbb.send_selection_to_dsh", text="Send selection to DSH", icon="EXPORT")
        if 1 < sel_count <= 200:
            try:
                selected_now = list(bpy.context.selected_objects or [])
            except Exception:
                selected_now = []
            colls = selection_collection_summary(selected_now, cap=4)
            if colls:
                sel_col.label(text="Collections involved: " + ", ".join(
                    "%s(%d)" % (c["name"], c["count"]) for c in colls), icon="OUTLINER_COLLECTION")

    @staticmethod
    def _draw_selection_status(sel_box):
        send_state = selection_commands._selection_send_state
        if send_state:
            if send_state.get("ok"):
                sel_box.label(text="last send: ok (seq %s)" % send_state.get("seq"), icon="CHECKMARK")
            else:
                sel_box.label(text="last send failed: " + str(send_state.get("error") or "unknown")[:120], icon="ERROR")

    @staticmethod
    def _draw_advanced(sel_box, scene):
        # backend address / overrides: collapsed (only expand when troubleshooting)
        adv_open = bool(getattr(scene, "dshbb_show_advanced", False))
        adv_row = sel_box.row()
        adv_row.prop(scene, "dshbb_show_advanced", text="Backend / Advanced", emboss=False,
                     icon="TRIA_DOWN" if adv_open else "TRIA_RIGHT")
        if adv_open:
            sel_box.label(text="DSH backend: " + dshbb_backend_url(), icon="URL")
            sel_box.prop(scene, "dshbb_backend_url", text="Override backend address (may be left empty)")

    @staticmethod
    def _draw_community(layout, context):
        # Community section
        layout.separator()
        community_box = layout.box()
        col = community_box.column(align=True)
        # Wrap by panel width so Blender doesn't elide the phrase mid-line.
        ui_scale = context.preferences.system.ui_scale
        region_width = context.region.width if context.region else 300
        chars = max(12, int((region_width - 30) / (7 * ui_scale)))
        for line in textwrap.wrap("Stay updated with the latest developments", chars):
            col.label(text=line)
        col.separator()
        row = col.row()
        row.scale_y = 1.3
        row.operator("wm.url_open", text="Join Discord", icon="URL").url = DISCORD_URL
