""" Configuration, environment variables, preferences and auto-start. """

import bpy
import socket
import requests
import os
from bpy.app.handlers import persistent

from .compat import ADDON_MODULE

# Compatibility fallback (old environment variable names): read the new name first, and only fall back to the pre-rename name when it is unset.
# The old names appear only in the table below, so environment variables users already set keep working.
_LEGACY_ENV_VARS = {
    # These are environment variable names, not credentials.
    "DSHBB_HYPER3D_API_KEY": "BLENDERMCP_HYPER3D_API_KEY",  # gitleaks:allow
    "DSHBB_SKETCHFAB_API_KEY": "BLENDERMCP_SKETCHFAB_API_KEY",  # gitleaks:allow
    "DSHBB_POLYPIZZA_API_KEY": "BLENDERMCP_POLYPIZZA_API_KEY",  # gitleaks:allow
    "DSHBB_HUNYUAN3D_SECRET_ID": "BLENDERMCP_HUNYUAN3D_SECRET_ID",  # gitleaks:allow
    "DSHBB_HUNYUAN3D_SECRET_KEY": "BLENDERMCP_HUNYUAN3D_SECRET_KEY",  # gitleaks:allow
    "DSHBB_HUNYUAN3D_API_URL": "BLENDERMCP_HUNYUAN3D_API_URL",  # gitleaks:allow
}


def read_env_var(name):
    """Read an environment variable: the new name wins, with a compatibility fallback to the legacy name (pre-rename versions)."""
    value = os.getenv(name)
    if value:
        return value
    legacy = _LEGACY_ENV_VARS.get(name)
    return os.getenv(legacy) if legacy else None


# ---------------------------------------------------------------- credentials
# Single owner for credentials (4.5): the add-on preferences are the only persistent location, and environment variables remain
# the fallback (DSHBB_* new names win, legacy BLENDERMCP_* names kept working, see read_env_var). Historically every
# credential was also mirrored on the Scene (saved with the .blend), so both the server and the panel had to write
# "use prefs if there are prefs, otherwise use scene" branches, which made which key was used depend on the currently open file. Now
# the Scene copies are deleted; the free-trial button uses an in-process override (lost on reload) and does not overwrite the user's
# already saved private key.
_session_credentials = {}


def set_session_credential(name, value):
    """Set a session-only credential override (empty value clears it)."""
    if value:
        _session_credentials[name] = value
    else:
        _session_credentials.pop(name, None)


def clear_session_credentials():
    """Drop every session-only credential override (add-on reload / reset)."""
    _session_credentials.clear()


def get_credential(pref_attr, env_var):
    """Read one credential: session override -> add-on preferences -> env var."""
    override = _session_credentials.get(pref_attr)
    if override:
        return override
    prefs = get_dshbb_addon_preferences()
    if prefs:
        value = getattr(prefs, pref_attr, "")
        if value:
            return value
    return read_env_var(env_var) or ""


RODIN_FREE_TRIAL_KEY = "vibecoding"
DISCORD_URL = "https://discord.gg/SNqPn4TcKQ"
# Public site link shown by the N-panel; kept here so UI code does not import
# the integration clients.
POLYHAVEN_SITE = "https://polyhaven.com"

# Add User-Agent as required by Poly Haven API
REQ_HEADERS = requests.utils.default_headers()
REQ_HEADERS.update({"User-Agent": "dsh-blender-bridge"})

# Set when the user disconnects so opening another blend file does not restart
# the server behind their back. A manual connect or add-on reload clears it.
_user_stopped_server = False


def _dshbb_port_has_listener(host, port):
    """Return True when another process already owns the bridge endpoint."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.15)
    try:
        return probe.connect_ex((host, port)) == 0
    finally:
        probe.close()


def _dshbb_ensure_server_running():
    """Start the bridge after Blender's UI and scene context are ready.

    Returning a delay asks Blender's timer system to retry when a launch-time
    socket or context race prevented the first attempt.
    """
    if bpy.app.background:
        return None

    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return 0.5

    server = getattr(bpy.types, "dshbb_server", None)
    if not scene.dshbb_auto_start_server or _user_stopped_server:
        scene.dshbb_server_running = bool(server is not None and server.running)
        return None

    port = scene.dshbb_port
    if server is None:
        from .server import DSHBlenderBridgeServer

        if _dshbb_port_has_listener("localhost", port):
            scene.dshbb_server_running = False
            print(f"DSH Blender Bridge: port {port} is already in use; auto-start skipped.")
            return None
        server = DSHBlenderBridgeServer(port=port)
        bpy.types.dshbb_server = server  # pyright: ignore[reportAttributeAccessIssue]

    if not server.running:
        # Safe while stopped and necessary when a newly loaded scene selects a
        # different port. Never retarget an active connection.
        server.port = port
        server.start()

    scene.dshbb_server_running = server.running

    return None if server.running else 1.0


def _dshbb_schedule_auto_start(delay=0.5):
    """Schedule one persistent startup callback if none is already pending."""
    if not bpy.app.timers.is_registered(_dshbb_ensure_server_running):
        bpy.app.timers.register(
            _dshbb_ensure_server_running,
            first_interval=delay,
            persistent=True,
        )


@persistent
def _dshbb_load_post(_unused):
    """Retry auto-start after Blender loads a startup file or another blend."""
    _dshbb_schedule_auto_start()


def register_auto_start():
    """Install the load handler and defer the initial startup attempt."""
    global _user_stopped_server
    _user_stopped_server = False
    if _dshbb_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_dshbb_load_post)
    _dshbb_schedule_auto_start()


def unregister_auto_start():
    """Remove callbacks owned by the add-on before it is disabled."""
    if _dshbb_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_dshbb_load_post)
    if bpy.app.timers.is_registered(_dshbb_ensure_server_running):
        bpy.app.timers.unregister(_dshbb_ensure_server_running)


def get_dshbb_addon_preferences(context=None):
    """Get add-on preferences object if available."""
    if context is None:
        context = bpy.context
    addon = context.preferences.addons.get(ADDON_MODULE)  # pyright: ignore[reportAttributeAccessIssue]
    return addon.preferences if addon else None


DEFAULT_DSH_BACKEND = "http://127.0.0.1:9877"


def dshbb_backend_url():
    try:
        url = bpy.context.scene.dshbb_backend_url  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        url = ""
    return (url or DEFAULT_DSH_BACKEND).rstrip("/")
