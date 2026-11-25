# -*- coding: utf-8 -*-
"""Split from deliver.py; behavior preserved by the facade."""
from .common import *  # noqa: F401,F403
from .export import deliver_export
from .verify import d_dispatch, deliver_help, deliver_verify

import sys as _sys
_dv_K = _sys.modules.get("dsh_rt_kernel")
def d_selftest():
    # delivery self-test: temporary cube -> export OBJ -> on-disk check -> verify against md5
    import json

    def _d(x):
        return json.loads(x) if isinstance(x, str) else x

    import bpy
    import bmesh as _bm
    import os
    import tempfile
    ev = {}
    nm = "__dsh_dv_cube"
    d = None
    try:
        me = bpy.data.meshes.new(nm)
        ob = bpy.data.objects.new(nm, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = _bm.new()
        _bm.ops.create_cube(bm, size=1.0)
        bm.to_mesh(me)
        bm.free()
        d = tempfile.mkdtemp(prefix="dsh_deliver_")
        r = _d(deliver_export(dir=d, objects=[nm], name="selftest", fmt="obj"))
        ev["export_ok"] = isinstance(r, dict) and r.get("ok") is not False
        files = sorted(os.listdir(d)) if os.path.isdir(d) else []
        ev["obj_written"] = any(f.endswith(".obj") for f in files)
        v = _d(deliver_verify(path_or_dir=d, manifest="auto"))
        ev["verify_ok"] = isinstance(v, dict) and v.get("ok") is not False
        return _KIT.j({"ok": all(x is True for x in ev.values()), "evidence": ev, "files": files[:8], "dir": d})
    except Exception as e:
        return _KIT.j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "dir": d})
    finally:
        o = bpy.data.objects.get(nm)
        if o is not None:
            me2 = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if me2 is not None and me2.users == 0:
                bpy.data.meshes.remove(me2, do_unlink=True)



if _dv_K is not None:
    _dv_K.dsh_deliver_api = _KIT.Api({"version": DELIVER_VERSION, "dispatch": _KIT.wrap_dispatch(d_dispatch, {"selftest": d_selftest}),
                          "export": deliver_export, "verify": deliver_verify, "help": deliver_help,
        "selftest": d_selftest})

# ---- v0.9.1 (93-B1/B2): making the API callable (swap in a dict-subclass instance that returns parsed objects) ----
# Background: K.dsh_x_api used to be a plain dict → in-process api(args) raised TypeError: 'dict' object is not callable;
# and dispatch returned a JSON string, so callers had to json.loads it themselves.
# Now: api("op", {…}) or api({…}) → dict; api["dispatch"](op, json_str) still returns str (the engine contract is unchanged).
# Note: dict is a static type, so assigning __class__ on an existing instance fails (measured in practice: TypeError) — hence a new instance.
_DshApi = _KIT.Api  # shared kernel (the registration line at the tail needs no change)
import sys as _sys_api
_K_api = _sys_api.modules.get("dsh_rt_kernel")
if _K_api is not None and isinstance(getattr(_K_api, "dsh_deliver_api", None), dict) \
        and not isinstance(getattr(_K_api, "dsh_deliver_api", None), _DshApi):
    _K_api.dsh_deliver_api = _DshApi(_K_api.dsh_deliver_api)