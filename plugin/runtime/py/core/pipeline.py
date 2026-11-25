# -*- coding: utf-8 -*-
"""DSH pipeline: **artifact registry + step orchestration** —— lets the 176 ops actually work together instead of each going its own way.

The pain it solves (measured in practice before the refactor):
  · ops could only "carry buckets by hand": vehicle_sections returns a 5,656-character JSON blob and vehicle_loft has to paste the stations array back in;
  · every step's handoff went through the model context ⇒ expensive and easy to miscopy (field names, units, nesting);
  · the 18 multi-step chains in the skill were all prose, and the model had to translate them into N tool calls itself.

Mechanism:
  · **artifact registry**: any step's output can be stored under a name (kept in K.dsh_artifacts, living as long as the persistent kernel K, i.e. one Blender session);
  · **@references**: later steps write "@name" or "@name.a.b" (dot path) in their args; it is resolved to the real value at run time;
  · **pipe_run**: one call runs the whole chain and keeps a receipt per step (duration/whether ok/output key names); on failure it stops per stop_on_fail.

Protocol:
    pipe_put(name, value)            —— store an artifact by hand (numbers/arrays the model computed work too)
    pipe_run(steps=[{"api","op","args","out"}…])  —— run them chained
    pipe_get / pipe_list / pipe_clear

⚠ Boundary: @references are resolved **in this module only** (so they work for pipe_* and for chains going through pipe_run);
  a single plan op does not dereference automatically —— that belongs to the engine routing layer and is left for later (to avoid touching the fragile write path).
"""
import json
import sys
import time

PIPE_VERSION = 1

_K = sys.modules.get("dsh_rt_kernel")
_KIT = getattr(_K, "dsh_kit", None)
if _KIT is None:
    raise RuntimeError("pipeline.py requires the shared kernel K.dsh_kit (injected by KERNEL_BOOTSTRAP)")
_j = _KIT.j


def _reg():
    r = getattr(_K, "dsh_artifacts", None)
    if r is None:
        r = {}
        _K.dsh_artifacts = r
    return r


def _brief(v, depth=0):
    """Short type description for the receipt (do not stuff large objects into the receipt)."""
    if isinstance(v, dict):
        return {"type": "dict", "keys": sorted(list(v.keys()))[:12], "n": len(v)}
    if isinstance(v, (list, tuple)):
        return {"type": "list", "n": len(v), "first": (str(v[0])[:60] if v else None)}
    if isinstance(v, str):
        return {"type": "str", "n": len(v), "head": v[:60]}
    return {"type": type(v).__name__, "value": (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:40])}


def pipe_put(name, value=None, note=None):
    """Store an artifact (name without @; value any JSON-compatible structure)."""
    nm = str(name or "").lstrip("@")
    if not nm:
        return _j({"ok": False, "error": "name is required"})
    reg = _reg()
    reg[nm] = {"value": value, "note": note, "ts": time.time()}
    return _j({"ok": True, "name": nm, "brief": _brief(value), "count": len(reg)})


def pipe_get(name, path=None):
    """Fetch an artifact (optional dot path, e.g. "stations" or "package.length_mm")."""
    nm = str(name or "").lstrip("@")
    reg = _reg()
    if nm not in reg:
        return _j({"ok": False, "error": "no such artifact: %s" % nm, "have": sorted(reg.keys())})
    v = reg[nm]["value"]
    if path:
        try:
            for part in str(path).split("."):
                v = v[int(part)] if isinstance(v, list) else v[part]
        except Exception as e:
            return _j({"ok": False, "error": "path not resolvable: %s (%s)" % (path, str(e)[:80])})
    return _j({"ok": True, "name": nm, "value": v})


def pipe_list():
    reg = _reg()
    return _j({"ok": True, "count": len(reg),
               "artifacts": [{"name": k, "brief": _brief(v["value"]), "note": v.get("note")} for k, v in sorted(reg.items())]})


def pipe_clear(name=None):
    reg = _reg()
    if name:
        nm = str(name).lstrip("@")
        reg.pop(nm, None)
    else:
        reg.clear()
    return _j({"ok": True, "count": len(reg)})


def _resolve(v, reg):
    """Resolve "@name[.path]" in args to the real value (recursively over dict/list)."""
    if isinstance(v, str) and v.startswith("@"):
        body = v[1:]
        parts = body.split(".")
        nm = parts[0]
        if nm not in reg:
            raise KeyError("referenced artifact does not exist @%s (have: %s)" % (nm, ", ".join(sorted(reg.keys())) or "none"))
        cur = reg[nm]["value"]
        for p in parts[1:]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        return cur
    if isinstance(v, dict):
        return {k: _resolve(x, reg) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve(x, reg) for x in v]
    return v


def pipe_run(steps=None, stop_on_fail=True, dry_run=False):
    """Run a list of steps in order; each step is {api, op, args, out}, and args may reference earlier output with "@artifact[.path]"."""
    reg = _reg()
    if not steps:
        return _j({"ok": False, "error": "steps is required: [{api, op, args, out}]"})
    rows, failed = [], []
    t_all = time.time()
    for i, st in enumerate(list(steps)):
        s = dict(st or {})
        api_name = str(s.get("api") or "")
        op = str(s.get("op") or "")
        out = s.get("out")
        row = {"i": i, "api": api_name, "op": op, "out": out}
        try:
            args = _resolve(s.get("args") or {}, reg)
        except Exception as e:
            row.update({"ok": False, "error": "reference resolution failed: %s" % str(e)[:160]})
            rows.append(row)
            failed.append(i)
            if stop_on_fail:
                break
            continue
        if dry_run:
            row.update({"ok": True, "dry_run": True, "args_keys": sorted(args.keys())})
            rows.append(row)
            continue
        api_obj = _KIT.api(api_name)
        if api_obj is None:
            row.update({"ok": False, "error": "module not injected: %s (call one op of that family once first, or add it to preload)" % api_name})
            rows.append(row)
            failed.append(i)
            if stop_on_fail:
                break
            continue
        t0 = time.time()
        try:
            res = api_obj(op, args)
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        row["ms"] = int((time.time() - t0) * 1000)
        if not isinstance(res, dict):
            row.update({"ok": False, "error": "module returned a non-dict (%s)" % type(res).__name__})
            rows.append(row)
            failed.append(i)
            if stop_on_fail:
                break
            continue
        row["ok"] = bool(res.get("ok", True))
        row["keys"] = sorted(res.keys())[:10]
        if not row["ok"]:
            row["error"] = str(res.get("error") or res.get("reason") or "ok=false")[:160]
        if out:
            nm = str(out).lstrip("@")
            reg[nm] = {"value": res, "note": "%s.%s" % (api_name, op), "ts": time.time()}
            row["stored"] = nm
        rows.append(row)
        if not row["ok"]:
            failed.append(i)
            if stop_on_fail:
                break
    ok = not failed
    return _j({"ok": ok, "verdict": ("pass" if ok else "fail"), "steps": rows,
               "step_count": len(rows), "failed_steps": failed,
               "artifacts": sorted(reg.keys()), "ms": int((time.time() - t_all) * 1000),
               "note": "Store each step's output with out=@name, then reference it from later steps' args as \"@name\" or \"@name.a.b\"; "
                       "by default it stops on failure (stop_on_fail=false keeps running to see the whole picture)"})


def pipe_selftest():
    """Self-test: artifact store/get + @reference resolution (incl. dot paths/nesting) + per-step pipeline receipt + fail-fast."""
    ev = {}
    try:
        pipe_clear()
        pipe_put("t", {"a": {"b": [10, 20]}, "s": "hello"})
        ev["get_plain"] = json.loads(pipe_get("t"))["ok"]
        ev["get_path"] = json.loads(pipe_get("t", "a.b"))["value"] == [10, 20]
        ev["get_index"] = json.loads(pipe_get("t", "a.b.1"))["value"] == 20
        reg = _reg()
        ev["resolve_str"] = _resolve("@t.s", reg) == "hello"
        ev["resolve_nested"] = _resolve({"pairs": [{"min_mm": "@t.a.b.0"}]}, reg) == {"pairs": [{"min_mm": 10}]}
        ev["resolve_missing_raises"] = False
        try:
            _resolve("@nope.x", reg)
        except KeyError:
            ev["resolve_missing_raises"] = True
        # Really run a two-step chain: clearance.help → then a check using its output (also validates out= artifact storage)
        cl = _KIT.api("clearance")
        if cl is not None:
            r = json.loads(pipe_run(steps=[
                {"api": "clearance", "op": "help", "args": {}, "out": "helped"},
                {"api": "clearance", "op": "selftest", "args": {}, "out": "checked"}]))
            ev["run_chain_ok"] = bool(r.get("ok")) and r.get("step_count") == 2
            ev["run_stored"] = "helped" in (r.get("artifacts") or [])
        else:
            ev["run_chain_ok"] = "skip (clearance not injected)"
        # Fail-fast: deliberately reference an artifact that does not exist
        r2 = json.loads(pipe_run(steps=[{"api": "clearance", "op": "help", "args": {"x": "@nope"}}]))
        ev["fail_fast"] = r2.get("ok") is False and r2.get("failed_steps") == [0]
        pipe_clear()
        ok = all(v is True for v in ev.values())
        return _j({"ok": bool(ok), "version": PIPE_VERSION, "evidence": ev})
    except Exception as e:
        return _j({"ok": False, "evidence": ev, "error": "%s: %s" % (type(e).__name__, str(e)[:220])})


def pipe_help():
    return _j({
        "module": "pipeline.py", "version": PIPE_VERSION,
        "what": "artifact registry + step orchestration: turn a multi-step chain into one call, pass output around as @name, no more hand-carrying JSON",
        "ops": ["pipe_run(steps)", "pipe_put", "pipe_get", "pipe_list", "pipe_clear", "pipe_selftest", "pipe_help"],
        "step_schema": {"api": "module name (vehicle/audit/clearance/img…)", "op": "that module's sub-op",
                        "args": "arguments (a value may be \"@artifact\" or \"@artifact.a.b\" to reference earlier output)", "out": "@name (optional, stores this step's receipt)"},
        "example": [{"api": "img", "op": "rectify", "args": {"path": "D:/ref/photo.jpg", "quad": [[0, 0], [1, 0], [1, 1], [0, 1]], "out_w": 1600}, "out": "@rect"},
                    {"api": "vehicle", "op": "sections", "args": {"side": "@rect.out", "mm_per_px": 2.0}, "out": "@sec"},
                    {"api": "vehicle", "op": "loft", "args": {"stations": "@sec.stations", "section_shape": "@sec.section_shape"}, "out": "@shell"}],
        "limits": ["@references are resolved inside pipe_run only (a single plan op does not dereference automatically)",
                   "artifacts live in the current Blender session (K survives backend restarts, but a Blender restart clears them)",
                   "steps run synchronously in order; for long tasks use the rt_job/headless path instead"],
    })


_KIT.register("pipe", PIPE_VERSION,
              {"run": pipe_run, "put": pipe_put, "get": pipe_get, "list": pipe_list,
               "clear": pipe_clear, "selftest": pipe_selftest, "help": pipe_help})