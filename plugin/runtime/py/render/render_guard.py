# -*- coding: utf-8 -*-
"""DSH render state tracking (v0.9.6 · upstream integration) — turns "main thread saturated by a render" from a timeout into an instant busy.

Measured motivation: of 8,116 calls on this machine **76/111 failures were timeouts**, and a render saturating Blender's main thread is one of the main causes;
workspace scripts contain bpy.ops.render.render **362 times / 334 files**. The current situation: during a render every
main-thread command queues up → the client waits until it times out → it looks like "the channel is broken".

Approach (the key design decision): the state does not come from "asking Blender" (the main thread is busy then, so asking just queues too), but from
**a flag file that bpy.app.handlers write to disk when a render starts and delete when it ends**; the backend (Node) only has to read the file to
decide busy **instantly** — no Blender round trip needed.

  render_init     → write {state:"rendering", since, scene, frame, pid}
  render_complete → delete (cleared_by="complete")
  render_cancel   → delete (cleared_by="cancel")
  load_post       → delete (file switch / crash recovery, so a stale flag cannot block the channel forever)

Based on that the backend: ① during a render, write commands to the main thread **get an instant busy** (with a suggestion to send them after the render / or to use blender_rt_job);
② the three ops render_state/render_wait/render_reset; ③ a stale flag (default >15 min) is judged stale automatically and let through.

The API hangs off K.dsh_render_guard; install() is idempotent (repeated calls do not register the handler twice).
"""
import json
import os
import sys
import time

import bpy

RG_VERSION = 1
STALE_MS = 15 * 60 * 1000          # stale-flag threshold (the Node side uses the same rule)
_STATE = {"state": "idle", "since": None, "scene": None, "frame": None, "pid": None, "cleared_by": None}
_INSTALLED = False


import sys as _sys_kit
_KIT = getattr(_sys_kit.modules.get("dsh_rt_kernel"), "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("render_guard needs the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")


_j = _KIT.j  # shared kernel (the original built-in implementation has been removed)
def _flag_path():
    """The flag file path is injected by the plugin (DSH_RENDER_FLAG_WIN, Windows form; Blender runs on Windows).
    When it is not injected (headless/self-test) this falls back to the DSH_RENDER_FLAG environment variable → temp directory, so the module stays self-contained and testable."""
    p = globals().get("DSH_RENDER_FLAG_WIN")
    if p:
        return p
    env = os.environ.get("DSH_RENDER_FLAG")
    if env:
        return env
    import tempfile
    return os.path.join(tempfile.gettempdir(), "dsh_render_state.json")


def _write_flag(payload):
    p = _flag_path()
    if not p:
        return False
    try:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _clear_flag(why):
    global _STATE
    _STATE = {"state": "idle", "since": None, "scene": None, "frame": None, "pid": None, "cleared_by": why}
    p = _flag_path()
    try:
        if p and os.path.exists(p):
            os.remove(p)
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------- handlers

def _on_render_init(scene=None, *a):
    global _STATE
    now = time.time()
    _STATE = {"state": "rendering", "since": now,
              "scene": getattr(scene, "name", None),
              "frame": getattr(scene, "frame_current", None),
              "pid": os.getpid(), "cleared_by": None}
    _write_flag({"state": "rendering", "since": now, "since_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                 "scene": _STATE["scene"], "frame": _STATE["frame"], "pid": _STATE["pid"],
                 "engine": getattr(getattr(scene, "render", None), "engine", None)})


def _on_render_complete(scene=None, *a):
    _clear_flag("complete")


def _on_render_cancel(scene=None, *a):
    _clear_flag("cancel")


def _on_load_post(*a):
    # file switch / post-crash recovery: a stale flag would block the write channel forever, so clear it here
    _clear_flag("load_post")


def install(force=False):
    """Register the four handlers (idempotent). Returns the registration result."""
    global _INSTALLED
    H = bpy.app.handlers
    want = [("render_init", _on_render_init), ("render_complete", _on_render_complete),
            ("render_cancel", _on_render_cancel), ("load_post", _on_load_post)]
    added = []
    for name, fn in want:
        lst = getattr(H, name, None)
        if lst is None:
            continue
        if any(getattr(h, "__name__", "") == fn.__name__ for h in lst):
            continue
        lst.append(fn)
        added.append(name)
    _INSTALLED = True
    return {"ok": True, "installed": True, "added": added, "flag_path": _flag_path(),
            "handlers": {n: sum(1 for h in getattr(H, n, []) if getattr(h, "__name__", "").startswith("_on_")) for n, _ in want}}


def mark_rendering(scene=None, note=None):
    """Manual marking (self-test / exception fallback)."""
    _on_render_init(scene or bpy.context.scene)
    return state()


def mark_idle(why="manual"):
    _clear_flag(str(why or "manual"))
    return state()


def state():
    """Local state + disk flag (when the two disagree the disk wins, and in_sync reports it)."""
    p = _flag_path()
    disk = None
    try:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                disk = json.load(f)
    except Exception:
        disk = None
    age_ms = None
    if disk and disk.get("since"):
        age_ms = int((time.time() - float(disk["since"])) * 1000)
    return _j({"ok": True, "installed": _INSTALLED, "local": _STATE, "flag_path": p,
               "flag": disk, "age_ms": age_ms, "stale": bool(age_ms is not None and age_ms > STALE_MS),
               "in_sync": (disk is None) == (_STATE.get("state") != "rendering"),
               "handlers": {n: sum(1 for h in getattr(bpy.app.handlers, n, []) if getattr(h, "__name__", "").startswith("_on_"))
                            for n in ("render_init", "render_complete", "render_cancel", "load_post")}})


def selftest():
    """Self-test: register handlers → mark manually → assert the flag file appears → clear → assert it disappears → (optionally) a real render."""
    ev = {}
    try:
        r = install()
        ev["install"] = r
        p = _flag_path()
        ev["flag_path"] = p
        if not p:
            return _j({"ok": False, "evidence": ev, "error": "DSH_RENDER_FLAG_WIN was not injected (the engine side has to supply the path)"})
        if os.path.exists(p):
            os.remove(p)
        mark_rendering(note="selftest")
        ev["after_mark_exists"] = os.path.exists(p)
        if ev["after_mark_exists"]:
            with open(p, encoding="utf-8") as f:
                ev["flag_content"] = json.load(f)
        st = json.loads(state())
        ev["state_while_marked"] = {"state": (st.get("flag") or {}).get("state"), "age_ms": st.get("age_ms"),
                                    "stale": st.get("stale"), "handlers": st.get("handlers")}
        mark_idle("selftest-clear")
        ev["after_clear_exists"] = os.path.exists(p)
        ok = (bool(ev["after_mark_exists"]) and ev["state_while_marked"]["state"] == "rendering"
              and not ev["after_clear_exists"]
              and all(v >= 1 for v in (ev["install"].get("handlers") or {}).values()))
        return _j({"ok": bool(ok), "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})


def help_():
    return _j({
        "module": "render_guard.py", "version": RG_VERSION,
        "what": "render state tracking: a render start writes a disk flag, and end/cancel/file switch deletes it; the backend reads the file and decides busy instantly (no Blender round trips)",
        "api": {"install": "register the 4 handlers (idempotent)", "state": "local state + disk flag + stale verdict",
                "mark_rendering/mark_idle": "manual marking (self-test and exception fallback)", "selftest": "self-test (including the handler-registration assertion)"},
        "why": "measured: 76 of 111 failures were timeouts, with the render holding the main thread as one of the main causes; workspace render.render 362 times / 334 files",
        "limits": ["stale threshold 15 min: a flag that was not cleared in time is judged stale and let through (so the channel is never blocked forever)",
                   "switching files (load_post) clears the flag; while a real render is running wait for it with render_wait, do not force commands"],
    })


def dispatch(op, args_json):
    args = {}
    if isinstance(args_json, str) and args_json.strip():
        try:
            args = json.loads(args_json)
        except Exception as e:
            return _j({"ok": False, "error": "args is not valid JSON: %s" % str(e)[:120]})
    if not isinstance(args, dict):
        return _j({"ok": False, "error": "args must be an object"})
    kw = {k: v for k, v in args.items() if k != "args"}
    ops = {"install": lambda **k: _j(install(bool(k.get("force")))),
           "state": lambda **k: state(),
           "mark": lambda **k: mark_rendering(note=k.get("note")),
           "clear": lambda **k: mark_idle(k.get("why") or "manual"),
           "selftest": lambda **k: selftest(),
           "help": lambda **k: help_()}
    fn = ops.get(str(op))
    if fn is None:
        return _j({"ok": False, "error": "unknown render op", "op": op, "ops": sorted(ops)})
    try:
        return fn(**kw)
    except Exception as e:
        return _j({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]), "op": op})


_DshApi = _KIT.Api  # shared kernel (the trailing registration line needs no change)
_K = sys.modules.get("dsh_rt_kernel")
if _K is not None:
    _K.dsh_render_guard = _DshApi({"version": RG_VERSION, "dispatch": dispatch, "install": install,
                                   "state": state, "mark": mark_rendering, "clear": mark_idle,
                                   "selftest": selftest, "help": help_})
    # injection registers: hang the handlers as soon as the module loads, so "render first, install later" cannot go unrecorded
    try:
        install()
    except Exception:
        pass
