""" Operators. """

import bpy

from ..commands.selection import best_collection_for_selection, record_selection_send, send_collection_to_dsh, send_selection_to_dsh
from .. import config
from ..config import RODIN_FREE_TRIAL_KEY, get_dshbb_addon_preferences, set_session_credential
from ..protocol import redraw_view3d_panels
from ..server import DSHBlenderBridgeServer

class DSHBB_OT_ToggleAIPause(bpy.types.Operator):
    """Pause / resume AI operations (reject Blender write operations sent by DSH)"""
    bl_idname = "dshbb.toggle_ai_pause"
    bl_label = "Pause AI Operations"
    bl_description = "While paused the model can run read-only queries only; click 'Resume AI Operations' at the top of the N panel to restore"

    def execute(self, context):
        scene = context.scene
        scene.dshbb_ai_paused = not bool(getattr(scene, "dshbb_ai_paused", False))
        redraw_view3d_panels()
        if scene.dshbb_ai_paused:
            self.report({'WARNING'}, "AI operations paused (read-only queries still work)")
        else:
            self.report({'INFO'}, "AI operations resumed")
        return {'FINISHED'}


# Operator to set Hyper3D API Key
class DSHBB_OT_SetFreeTrialHyper3DAPIKey(bpy.types.Operator):
    bl_idname = "dshbb.set_hyper3d_free_trial_api_key"
    bl_label = "Set Free Trial API Key"

    def execute(self, context):
        # The single owner of credentials is the add-on preferences (config.get_credential). The free
        # trial only writes an in-process session override: it applies to this Blender session, expires
        # on reload/restart, and never overwrites a private key the user already saved; the Scene
        # property copy was removed in 4.5.
        set_session_credential("hyper3d_api_key", RODIN_FREE_TRIAL_KEY)
        prefs = get_dshbb_addon_preferences(context)
        if prefs:
            if not prefs.hyper3d_api_key or prefs.hyper3d_api_key == RODIN_FREE_TRIAL_KEY:
                prefs.hyper3d_api_key = RODIN_FREE_TRIAL_KEY
            else:
                self.report(
                    {'INFO'},
                    "Using free trial for this session only; saved private key was kept."
                )
        context.scene.dshbb_hyper3d_mode = 'MAIN_SITE'
        self.report({'INFO'}, "API Key set successfully!")
        return {'FINISHED'}

# Operator to start the server
class DSHBB_OT_SendSelectionToDSH(bpy.types.Operator):
    """Send the current native selection to DSH (written into the next message draft, not auto-sent)"""
    bl_idname = "dshbb.send_selection_to_dsh"
    bl_label = "Send Selection to DSH"
    bl_description = "POST the currently selected objects to the DSH plugin backend; DSH inserts them into the current session draft (does not auto-send)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        try:
            return bool(context.selected_objects)
        except Exception:
            return False

    def execute(self, context):
        result = record_selection_send(send_selection_to_dsh())
        if result.get("ok"):
            self.report({'INFO'}, "selection sent to DSH (seq %s)" % result.get("seq"))
        else:
            self.report({'WARNING'}, "send failed: %s"
                        % (result.get("error") or result.get("hint") or "unknown"))
        try:
            context.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class DSHBB_OT_UseSelectionCollection(bpy.types.Operator):
    """Set the "Collection" dropdown to the collection in which the selected objects appear most often"""
    bl_idname = "dshbb.use_selection_collection"
    bl_label = "Use Selection's Collection"
    bl_description = "When the selected objects span several collections, automatically pick the most relevant one into the 'Collection' dropdown"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        try:
            return best_collection_for_selection() is not None
        except Exception:
            return False

    def execute(self, context):
        best = best_collection_for_selection()
        if best is None:
            self.report({'WARNING'}, "the current selection belongs to no collection")
            return {'CANCELLED'}
        try:
            context.scene.dshbb_collection_target = best
        except Exception as exc:
            self.report({'WARNING'}, "failed to set collection: %s" % str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, "collection '%s' selected (%d objects)" % (best.name, len(best.objects)))
        try:
            context.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class DSHBB_OT_ListRowsInc(bpy.types.Operator):
    """Make the N panel lists a bit taller"""
    bl_idname = "dshbb.list_rows_inc"
    bl_label = "Taller List"
    bl_description = "Increase the object/member list height by 2 rows (3-30)"

    @classmethod
    def poll(cls, context):
        try:
            return int(getattr(context.scene, "dshbb_list_rows", 8)) < 30
        except Exception:
            return False

    def execute(self, context):
        scene = context.scene
        scene.dshbb_list_rows = min(30, int(getattr(scene, "dshbb_list_rows", 8)) + 2)
        try:
            context.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class DSHBB_OT_ListRowsDec(bpy.types.Operator):
    """Make the N panel lists a bit shorter"""
    bl_idname = "dshbb.list_rows_dec"
    bl_label = "Shorter List"
    bl_description = "Decrease the object/member list height by 2 rows (3-30)"

    @classmethod
    def poll(cls, context):
        try:
            return int(getattr(context.scene, "dshbb_list_rows", 8)) > 3
        except Exception:
            return False

    def execute(self, context):
        scene = context.scene
        scene.dshbb_list_rows = max(3, int(getattr(scene, "dshbb_list_rows", 8)) - 2)
        try:
            context.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class DSHBB_OT_SendCollectionToDSH(bpy.types.Operator):
    """Send a whole collection to DSH (recommended for large assemblies)"""
    bl_idname = "dshbb.send_collection_to_dsh"
    bl_label = "Send Collection to DSH"
    bl_description = "Send the collection chosen in the N panel 'Collection' dropdown to DSH as a whole (no object selection required)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        try:
            return getattr(context.scene, "dshbb_collection_target", None) is not None
        except Exception:
            return False

    def execute(self, context):
        target = getattr(context.scene, "dshbb_collection_target", None)
        name = getattr(target, "name", None) if target else None
        result = record_selection_send(send_collection_to_dsh(collection_name=name))
        if result.get("ok"):
            self.report({'INFO'}, "collection '%s' sent to DSH (seq %s)" % (name, result.get("seq")))
        else:
            self.report({'WARNING'}, "failed to send collection: %s"
                        % (result.get("error") or result.get("hint") or "unknown"))
        try:
            context.area.tag_redraw()
        except Exception:
            pass
        return {'FINISHED'}


class DSHBB_OT_StartServer(bpy.types.Operator):
    bl_idname = "dshbb.start_server"
    bl_label = "Connect to DSH"
    bl_description = "Start the DSH Blender Bridge server to connect with DSH"

    def execute(self, context):
        config._user_stopped_server = False
        scene = context.scene

        # Create a new server instance
        if not hasattr(bpy.types, "dshbb_server") or not bpy.types.dshbb_server:
            bpy.types.dshbb_server = DSHBlenderBridgeServer(port=scene.dshbb_port)

        # Start the server
        bpy.types.dshbb_server.start()
        scene.dshbb_server_running = bpy.types.dshbb_server.running

        return {'FINISHED'}

# Operator to stop the server
class DSHBB_OT_StopServer(bpy.types.Operator):
    bl_idname = "dshbb.stop_server"
    bl_label = "Stop the connection to DSH"
    bl_description = "Stop the connection to DSH"

    def execute(self, context):
        config._user_stopped_server = True
        scene = context.scene

        # Stop the server if it exists
        if hasattr(bpy.types, "dshbb_server") and bpy.types.dshbb_server:
            bpy.types.dshbb_server.stop()
            del bpy.types.dshbb_server

        scene.dshbb_server_running = False

        return {'FINISHED'}

# Operator to open Terms and Conditions
class DSHBB_OT_OpenTerms(bpy.types.Operator):
    bl_idname = "dshbb.open_terms"
    bl_label = "View Terms and Conditions"
    bl_description = "Open the Terms and Conditions document"

    def execute(self, context):
        # Open the Terms and Conditions on GitHub
        terms_url = "https://github.com/ahujasid/blender-mcp/blob/main/TERMS_AND_CONDITIONS.md"
        try:
            import webbrowser
            webbrowser.open(terms_url)
            self.report({'INFO'}, "Terms and Conditions opened in browser")
        except Exception as e:
            self.report({'ERROR'}, f"Could not open Terms and Conditions: {str(e)}")

        return {'FINISHED'}
