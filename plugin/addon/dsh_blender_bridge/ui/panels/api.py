""" Shared API toggle row and the parent API panel. """

import bpy


def draw_api_toggle(layout, scene, prop_name, title):
    """Integration toggle row (no icon, keeps the panel compact)."""
    box = layout.box()
    row = box.row()
    row.prop(scene, prop_name, text="")
    row.label(text=title)
    return box if getattr(scene, prop_name) else None


class DSHBB_PT_EnvModelAPI(bpy.types.Panel):
    bl_label = "Environment and Character Model API Calls"
    bl_idname = "DSHBB_PT_EnvModelAPI"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "DSH Blender Bridge"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        self.layout.label(text="Environment generation: asset libraries; model generation: AI model APIs")
